#!/usr/bin/env python3
"""In-container compiler and causal JSONL/TSV strategy gateway.

Only this fixed program can talk to the host controller. User code runs in a
child process and receives atomic slices of simultaneously available bars. It
can emit targets and logs; it never receives future observations. Authoritative
portfolio, cash, fills and P&L stay unavailable until an explicit ledger bridge
is connected.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Mapping


ROOT = Path("/tmp/quant-strategy")
MAX_SOURCE_BYTES = 128 * 1024
MAX_DIAGNOSTIC_BYTES = 256 * 1024
SANDBOX_PROTOCOL_VERSION = "quant-strategy-jsonl-3"
SUPPORTED_PROTOCOL_VERSIONS = {
    "quant-strategy-jsonl-1",
    "quant-strategy-jsonl-2",
    SANDBOX_PROTOCOL_VERSION,
}


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def clean_text(value: object, limit: int = 16_000) -> str:
    return str(value).replace("\x00", "").strip()[:limit]


PYTHON_PRELUDE = r"""from __future__ import annotations
import random
import sys

class History(list):
    def mean(self):
        return sum(self) / len(self) if self else float("nan")
    def __getitem__(self, item):
        value = super().__getitem__(item)
        return History(value) if isinstance(item, slice) else value

class State:
    def __init__(self):
        object.__setattr__(self, "_values", {})
    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc
    def __setattr__(self, name, value):
        self._values[name] = value
    def __getitem__(self, name):
        return self._values[name]
    def __setitem__(self, name, value):
        self._values[name] = value

class Bar:
    def __init__(self, parts):
        self.event_time, self.available_at, self.symbol = parts[1], parts[2], parts[3]
        self.open, self.high, self.low, self.close, self.volume = map(float, parts[4:9])

class Slice:
    def __init__(self, event_time, available_at, bars):
        self.event_time = event_time
        self.available_at = available_at
        self.bars = dict(sorted((bar.symbol, bar) for bar in bars))
        self.symbols = tuple(self.bars)
    def __getitem__(self, symbol):
        return self.bars[str(symbol).upper()]
    def __iter__(self):
        return iter(self.bars)
    def __len__(self):
        return len(self.bars)

class PortfolioSnapshot:
    def __init__(self):
        self.available = False
        self.as_of = None
        self.base_currency = ""
        self.nav_base = None
        self.sequence = 0
        self.ledger_sha256 = ""
        self.source = ""
        self.reason = "AUTHORITATIVE_PORTFOLIO_NOT_CONNECTED"
        self.positions = {}
        self.cash = {}
        self.unsettled_cash = {}
        self.open_orders = ()
        self.margin = {}
        self.pnl = {}

class Context:
    def __init__(self, parameters, seed):
        self.parameters = parameters
        self.state = State()
        self.rng = random.Random(seed)
        self.now = None
        self._history = {}
        self._pending = {}
        self.portfolio = PortfolioSnapshot()
        self.positions = self.portfolio.positions
        self.cash = self.portfolio.cash
        self.open_orders = ()
    def history(self, symbol, field, periods):
        values = self._history.get((str(symbol).upper(), str(field).lower()), [])
        return History(values[-max(0, int(periods)):])
    def target_percent(self, symbol, target, *, reason_code=""):
        self._pending[str(symbol).upper()] = (float(target), str(reason_code))
    def log(self, message, *, level="INFO"):
        text = str(message).replace("\t", " ").replace("\n", " ")[:2000]
        print("LOG\t" + str(level).upper()[:16] + "\t" + text, flush=True)
"""

PYTHON_POSTLUDE = r"""
def _append_bar(ctx, bar):
    for field in ("open", "high", "low", "close", "volume"):
        ctx._history.setdefault((bar.symbol, field), []).append(float(getattr(bar, field)))

def _read_portfolio(ctx, parts):
    if len(parts) < 14:
        raise RuntimeError("invalid portfolio header")
    snap = PortfolioSnapshot()
    snap.available = parts[1] == "1"
    snap.as_of = parts[2] or None
    snap.base_currency = parts[3]
    snap.nav_base = None if parts[4] == "" else float(parts[4])
    snap.sequence = int(parts[5])
    snap.ledger_sha256 = parts[6]
    snap.source = parts[7]
    snap.reason = parts[8]
    position_count, cash_count, order_count = map(int, parts[9:12])
    margin_count, pnl_count = map(int, parts[12:14])
    positions, cash, unsettled, orders, margin, pnl = {}, {}, {}, [], {}, {}
    for _ in range(position_count):
        row = next(sys.stdin).rstrip("\n").split("\t")
        if len(row) < 8 or row[0] != "POSITION":
            raise RuntimeError("invalid portfolio position")
        positions[row[1]] = {"quantity":float(row[2]), "average_price":float(row[3]),
            "last_price":float(row[4]), "market_value_base":float(row[5]),
            "realized_pnl_base":float(row[6]), "unrealized_pnl_base":float(row[7])}
    for _ in range(cash_count):
        row = next(sys.stdin).rstrip("\n").split("\t")
        if len(row) < 4 or row[0] != "CASH": raise RuntimeError("invalid portfolio cash")
        cash[row[1]], unsettled[row[1]] = float(row[2]), float(row[3])
    for _ in range(order_count):
        row = next(sys.stdin).rstrip("\n").split("\t")
        if len(row) < 10 or row[0] != "OPEN_ORDER": raise RuntimeError("invalid open order")
        orders.append({"order_id":row[1], "instrument_id":row[2], "side":row[3],
            "order_type":row[4], "time_in_force":row[5], "status":row[6],
            "quantity":float(row[7]), "filled_quantity":float(row[8]),
            "remaining_quantity":float(row[9])})
    for _ in range(margin_count):
        row = next(sys.stdin).rstrip("\n").split("\t")
        if len(row) < 3 or row[0] != "MARGIN": raise RuntimeError("invalid margin value")
        margin[row[1]] = float(row[2])
    for _ in range(pnl_count):
        row = next(sys.stdin).rstrip("\n").split("\t")
        if len(row) < 3 or row[0] != "PNL": raise RuntimeError("invalid pnl value")
        pnl[row[1]] = float(row[2])
    snap.positions, snap.cash, snap.unsettled_cash = positions, cash, unsettled
    snap.open_orders, snap.margin, snap.pnl = tuple(orders), margin, pnl
    ctx.portfolio, ctx.positions, ctx.cash, ctx.open_orders = snap, positions, cash, tuple(orders)

_parameters = {}
_seed = 41
for _line in sys.stdin:
    _parts = _line.rstrip("\n").split("\t")
    if not _parts:
        continue
    if _parts[0] == "PARAM" and len(_parts) >= 3:
        _parameters[_parts[1]] = float(_parts[2])
    elif _parts[0] == "SEED" and len(_parts) >= 2:
        _seed = int(_parts[1])
    elif _parts[0] == "START":
        break
_ctx = Context(_parameters, _seed)
if "initialize" in globals():
    initialize(_ctx)
print("READY", flush=True)
for _line in sys.stdin:
    _parts = _line.rstrip("\n").split("\t")
    if not _parts:
        continue
    if _parts[0] == "STOP":
        break
    if _parts[0] == "PORTFOLIO":
        _read_portfolio(_ctx, _parts)
        continue
    if _parts[0] != "SLICE" or len(_parts) < 4:
        print("ERROR\tinvalid child protocol", flush=True)
        continue
    _event_time, _available_at, _count = _parts[1], _parts[2], int(_parts[3])
    _bars = []
    for _ in range(_count):
        _bar_parts = next(sys.stdin).rstrip("\n").split("\t")
        if _bar_parts[0] != "BAR" or len(_bar_parts) < 9:
            raise RuntimeError("invalid bar in slice")
        _bars.append(Bar(_bar_parts))
    _ctx.now = _available_at
    _ctx._pending = {}
    for _bar in _bars:
        _append_bar(_ctx, _bar)
    _slice = Slice(_event_time, _available_at, _bars)
    if "on_slice" in globals():
        on_slice(_ctx, _slice)
    else:
        for _bar in _bars:
            on_bar(_ctx, _bar)
    for _symbol, (_target, _reason) in sorted(_ctx._pending.items()):
        _reason = _reason.replace("\t", " ").replace("\n", " ")[:256]
        print(f"SIGNAL\t{_symbol}\t{_target:.17g}\t{_reason}", flush=True)
    print("END", flush=True)
"""


JS_PRELUDE = r""""use strict";
const readline = require("readline");
class Context {
  constructor(parameters, seed) {
    this.parameters = parameters; this.state = {}; this.seed = seed;
    this.now = null; this._history = new Map(); this._pending = new Map();
    this.portfolio = Object.freeze({available:false, asOf:null, baseCurrency:"", navBase:null,
      sequence:0, ledgerSha256:"", source:"", reason:"AUTHORITATIVE_PORTFOLIO_NOT_CONNECTED",
      positions:Object.freeze({}), cash:Object.freeze({}), unsettledCash:Object.freeze({}),
      openOrders:Object.freeze([]), margin:Object.freeze({}), pnl:Object.freeze({})});
    this.positions = Object.freeze({}); this.cash = Object.freeze({});
    this.openOrders = Object.freeze([]);
  }
  history(symbol, field, periods) {
    const key = String(symbol).toUpperCase() + "|" + String(field).toLowerCase();
    const values = this._history.get(key) || [];
    return values.slice(-Math.max(0, Number(periods)));
  }
  targetPercent(symbol, target, reasonCode = "") {
    this._pending.set(String(symbol).toUpperCase(), [Number(target), String(reasonCode)]);
  }
  log(message, level = "INFO") {
    const text = String(message).replace(/[\t\r\n]/g, " ").slice(0, 2000);
    process.stdout.write("LOG\t" + String(level).toUpperCase().slice(0,16) + "\t" + text + "\n");
  }
}
"""

JS_POSTLUDE = r"""
const rl = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
const parameters = {}; let seed = 41; let ctx = null;
let sliceMeta = null; let sliceBars = [];
let portfolioPending = null;
function finishPortfolio() {
  const p = portfolioPending.snapshot;
  p.positions = Object.freeze(p.positions); p.cash = Object.freeze(p.cash);
  p.unsettledCash = Object.freeze(p.unsettledCash); p.openOrders = Object.freeze(p.openOrders);
  p.margin = Object.freeze(p.margin); p.pnl = Object.freeze(p.pnl);
  ctx.portfolio = Object.freeze(p); ctx.positions = p.positions; ctx.cash = p.cash;
  ctx.openOrders = p.openOrders; portfolioPending = null;
}
function appendBar(context, bar) {
  for (const field of ["open", "high", "low", "close", "volume"]) {
    const key = bar.symbol + "|" + field;
    const values = context._history.get(key) || []; values.push(Number(bar[field]));
    context._history.set(key, values);
  }
}
rl.on("line", (line) => {
  const p = line.split("\t");
  if (portfolioPending !== null) {
    const pending = portfolioPending;
    if (p[0] === "POSITION" && pending.positions > 0 && p.length >= 8) {
      pending.snapshot.positions[p[1]] = Object.freeze({quantity:Number(p[2]), averagePrice:Number(p[3]),
        lastPrice:Number(p[4]), marketValueBase:Number(p[5]), realizedPnlBase:Number(p[6]),
        unrealizedPnlBase:Number(p[7])}); pending.positions -= 1;
    } else if (p[0] === "CASH" && pending.cash > 0 && p.length >= 4) {
      pending.snapshot.cash[p[1]] = Number(p[2]); pending.snapshot.unsettledCash[p[1]] = Number(p[3]); pending.cash -= 1;
    } else if (p[0] === "OPEN_ORDER" && pending.orders > 0 && p.length >= 10) {
      pending.snapshot.openOrders.push(Object.freeze({orderId:p[1], instrumentId:p[2], side:p[3],
        orderType:p[4], timeInForce:p[5], status:p[6], quantity:Number(p[7]),
        filledQuantity:Number(p[8]), remainingQuantity:Number(p[9])})); pending.orders -= 1;
    } else if (p[0] === "MARGIN" && pending.margin > 0 && p.length >= 3) {
      pending.snapshot.margin[p[1]] = Number(p[2]); pending.margin -= 1;
    } else if (p[0] === "PNL" && pending.pnl > 0 && p.length >= 3) {
      pending.snapshot.pnl[p[1]] = Number(p[2]); pending.pnl -= 1;
    } else { process.stdout.write("ERROR\tinvalid portfolio row\n"); portfolioPending = null; return; }
    if (pending.positions + pending.cash + pending.orders + pending.margin + pending.pnl === 0) finishPortfolio();
    return;
  }
  if (p[0] === "PARAM" && p.length >= 3) { parameters[p[1]] = Number(p[2]); return; }
  if (p[0] === "SEED") { seed = Number(p[1]); return; }
  if (p[0] === "START") {
    ctx = new Context(parameters, seed); if (typeof initialize === "function") initialize(ctx);
    process.stdout.write("READY\n"); return;
  }
  if (p[0] === "STOP") { rl.close(); return; }
  if (p[0] === "PORTFOLIO" && p.length >= 14 && ctx !== null) {
    portfolioPending = {snapshot:{available:p[1] === "1", asOf:p[2] || null,
      baseCurrency:p[3], navBase:p[4] === "" ? null : Number(p[4]), sequence:Number(p[5]),
      ledgerSha256:p[6], source:p[7], reason:p[8], positions:{}, cash:{}, unsettledCash:{},
      openOrders:[], margin:{}, pnl:{}}, positions:Number(p[9]), cash:Number(p[10]),
      orders:Number(p[11]), margin:Number(p[12]), pnl:Number(p[13])};
    if (portfolioPending.positions + portfolioPending.cash + portfolioPending.orders +
        portfolioPending.margin + portfolioPending.pnl === 0) finishPortfolio();
    return;
  }
  if (p[0] === "SLICE" && p.length >= 4 && ctx !== null) {
    sliceMeta = {eventTime:p[1], availableAt:p[2], count:Number(p[3])};
    sliceBars = []; return;
  }
  if (p[0] !== "BAR" || p.length < 9 || ctx === null || sliceMeta === null) {
    process.stdout.write("ERROR\tinvalid child protocol\n"); return;
  }
  const bar = {eventTime:p[1], availableAt:p[2], symbol:p[3], open:Number(p[4]),
    high:Number(p[5]), low:Number(p[6]), close:Number(p[7]), volume:Number(p[8])};
  sliceBars.push(Object.freeze(bar));
  if (sliceBars.length < sliceMeta.count) return;
  if (sliceBars.length > sliceMeta.count) {
    process.stdout.write("ERROR\ttoo many bars in slice\n"); return;
  }
  ctx.now = sliceMeta.availableAt; ctx._pending = new Map();
  for (const item of sliceBars) appendBar(ctx, item);
  const bars = Object.freeze(Object.fromEntries(sliceBars.map(item => [item.symbol, item])));
  const slice = Object.freeze({eventTime:sliceMeta.eventTime,
    availableAt:sliceMeta.availableAt, bars:bars, symbols:Object.freeze(Object.keys(bars).sort())});
  __CALLBACK_JS__
  for (const [symbol, pair] of Array.from(ctx._pending.entries()).sort()) {
    const reason = String(pair[1]).replace(/[\t\r\n]/g, " ").slice(0,256);
    process.stdout.write("SIGNAL\t" + symbol + "\t" + Number(pair[0]).toPrecision(17) + "\t" + reason + "\n");
  }
  process.stdout.write("END\n");
  sliceMeta = null; sliceBars = [];
});
"""


CPP_PRELUDE = r"""#include <algorithm>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <map>
#include <numeric>
#include <sstream>
#include <string>
#include <utility>
#include <vector>
struct Bar { std::string event_time, available_at, symbol; double open, high, low, close, volume; };
struct Slice { std::string event_time, available_at; std::map<std::string,Bar> bars; };
struct PositionSnapshot { double quantity=0, average_price=0, last_price=0, market_value_base=0, realized_pnl_base=0, unrealized_pnl_base=0; };
struct OpenOrderSnapshot { std::string order_id, instrument_id, side, order_type, time_in_force, status; double quantity=0, filled_quantity=0, remaining_quantity=0; };
struct PortfolioSnapshot { bool available=false; std::string as_of, base_currency, ledger_sha256, source, reason="AUTHORITATIVE_PORTFOLIO_NOT_CONNECTED"; double nav_base=NAN; long sequence=0; std::map<std::string,PositionSnapshot> positions; std::map<std::string,double> cash, unsettled_cash, margin, pnl; std::vector<OpenOrderSnapshot> open_orders; };
static std::vector<std::string> split_tab(const std::string& s) { std::vector<std::string> out; std::stringstream ss(s); std::string x; while(std::getline(ss,x,'\t')) out.push_back(x); return out; }
static std::string clean(std::string s) { std::replace(s.begin(),s.end(),'\t',' '); std::replace(s.begin(),s.end(),'\n',' '); if(s.size()>256)s.resize(256); return s; }
static double mean(const std::vector<double>& x) { return x.empty()?NAN:std::accumulate(x.begin(),x.end(),0.0)/x.size(); }
static std::vector<double> tail(const std::vector<double>& x, int n) { if(n<=0)return {}; auto p=x.begin()+std::max(0,static_cast<int>(x.size())-n); return {p,x.end()}; }
struct Context {
  std::map<std::string,double> parameters, state_number;
  std::map<std::string,std::vector<double>> histories;
  std::map<std::string,std::pair<double,std::string>> pending;
  PortfolioSnapshot portfolio;
  std::map<std::string,PositionSnapshot> positions;
  std::map<std::string,double> cash;
  std::vector<OpenOrderSnapshot> open_orders;
  std::string now;
  double parameter(const std::string& k,double fallback) const { auto it=parameters.find(k); return it==parameters.end()?fallback:it->second; }
  std::vector<double> history(const std::string& symbol,const std::string& field,int periods) const { auto it=histories.find(symbol+"|"+field); if(it==histories.end())return {}; return tail(it->second,periods); }
  void target_percent(const std::string& symbol,double target,const std::string& reason="") { pending[symbol]={target,reason}; }
  void log(const std::string& message,const std::string& level="INFO") { std::cout<<"LOG\t"<<clean(level)<<"\t"<<clean(message)<<std::endl; }
};
"""

CPP_POSTLUDE = r"""
int main(){ std::ios::sync_with_stdio(false); Context ctx; std::string line; long seed=41;
  while(std::getline(std::cin,line)){ auto p=split_tab(line); if(p.empty())continue; if(p[0]=="PARAM"&&p.size()>=3)ctx.parameters[p[1]]=std::stod(p[2]); else if(p[0]=="SEED"&&p.size()>=2)seed=std::stol(p[1]); else if(p[0]=="START")break; }
  (void)seed; initialize(ctx); std::cout<<"READY"<<std::endl;
  while(std::getline(std::cin,line)){ auto p=split_tab(line); if(p.empty())continue; if(p[0]=="STOP")break;
    if(p[0]=="PORTFOLIO"&&p.size()>=14){PortfolioSnapshot s;s.available=p[1]=="1";s.as_of=p[2];s.base_currency=p[3];s.nav_base=p[4].empty()?NAN:std::stod(p[4]);s.sequence=std::stol(p[5]);s.ledger_sha256=p[6];s.source=p[7];s.reason=p[8];int pc=std::stoi(p[9]),cc=std::stoi(p[10]),oc=std::stoi(p[11]),mc=std::stoi(p[12]),nc=std::stoi(p[13]);
      for(int i=0;i<pc;++i){std::getline(std::cin,line);auto r=split_tab(line);if(r.size()<8||r[0]!="POSITION")return 2;s.positions[r[1]]={std::stod(r[2]),std::stod(r[3]),std::stod(r[4]),std::stod(r[5]),std::stod(r[6]),std::stod(r[7])};}
      for(int i=0;i<cc;++i){std::getline(std::cin,line);auto r=split_tab(line);if(r.size()<4||r[0]!="CASH")return 2;s.cash[r[1]]=std::stod(r[2]);s.unsettled_cash[r[1]]=std::stod(r[3]);}
      for(int i=0;i<oc;++i){std::getline(std::cin,line);auto r=split_tab(line);if(r.size()<10||r[0]!="OPEN_ORDER")return 2;s.open_orders.push_back({r[1],r[2],r[3],r[4],r[5],r[6],std::stod(r[7]),std::stod(r[8]),std::stod(r[9])});}
      for(int i=0;i<mc;++i){std::getline(std::cin,line);auto r=split_tab(line);if(r.size()<3||r[0]!="MARGIN")return 2;s.margin[r[1]]=std::stod(r[2]);}
      for(int i=0;i<nc;++i){std::getline(std::cin,line);auto r=split_tab(line);if(r.size()<3||r[0]!="PNL")return 2;s.pnl[r[1]]=std::stod(r[2]);}
      ctx.portfolio=s;ctx.positions=s.positions;ctx.cash=s.cash;ctx.open_orders=s.open_orders;continue;}
    if(p[0]!="SLICE"||p.size()<4){std::cout<<"ERROR\tinvalid child protocol"<<std::endl;continue;}
    Slice slice; slice.event_time=p[1]; slice.available_at=p[2]; const int count=std::stoi(p[3]); std::vector<Bar> ordered;
    for(int i=0;i<count;++i){if(!std::getline(std::cin,line))return 2;auto bparts=split_tab(line);if(bparts.size()<9||bparts[0]!="BAR")return 2;Bar b{bparts[1],bparts[2],bparts[3],std::stod(bparts[4]),std::stod(bparts[5]),std::stod(bparts[6]),std::stod(bparts[7]),std::stod(bparts[8])};ordered.push_back(b);slice.bars[b.symbol]=b;}
    ctx.now=slice.available_at; ctx.pending.clear();
    for(const auto& b:ordered){ctx.histories[b.symbol+"|open"].push_back(b.open);ctx.histories[b.symbol+"|high"].push_back(b.high);ctx.histories[b.symbol+"|low"].push_back(b.low);ctx.histories[b.symbol+"|close"].push_back(b.close);ctx.histories[b.symbol+"|volume"].push_back(b.volume);}
    __CALLBACK_CPP__
    for(const auto& kv:ctx.pending)std::cout<<"SIGNAL\t"<<kv.first<<"\t"<<std::setprecision(17)<<kv.second.first<<"\t"<<clean(kv.second.second)<<std::endl; std::cout<<"END"<<std::endl;
  } return 0; }
"""


RUST_PRELUDE = r"""use std::collections::{BTreeMap, HashMap};
use std::io::{self, BufRead, Write};
#[derive(Clone)] struct Bar { event_time:String, available_at:String, symbol:String, open:f64, high:f64, low:f64, close:f64, volume:f64 }
struct Slice { event_time:String, available_at:String, bars:BTreeMap<String,Bar> }
#[derive(Clone)] struct PositionSnapshot { quantity:f64, average_price:f64, last_price:f64, market_value_base:f64, realized_pnl_base:f64, unrealized_pnl_base:f64 }
#[derive(Clone)] struct OpenOrderSnapshot { order_id:String, instrument_id:String, side:String, order_type:String, time_in_force:String, status:String, quantity:f64, filled_quantity:f64, remaining_quantity:f64 }
struct PortfolioSnapshot { available:bool, as_of:String, base_currency:String, nav_base:f64, sequence:i64, ledger_sha256:String, source:String, reason:String, positions:BTreeMap<String,PositionSnapshot>, cash:BTreeMap<String,f64>, unsettled_cash:BTreeMap<String,f64>, open_orders:Vec<OpenOrderSnapshot>, margin:BTreeMap<String,f64>, pnl:BTreeMap<String,f64> }
struct Context { parameters:HashMap<String,f64>, state_number:HashMap<String,f64>, histories:HashMap<String,Vec<f64>>, pending:BTreeMap<String,(f64,String)>, now:String, portfolio:PortfolioSnapshot, positions:BTreeMap<String,PositionSnapshot>, cash:BTreeMap<String,f64>, open_orders:Vec<OpenOrderSnapshot> }
impl Context {
 fn parameter(&self,k:&str,fallback:f64)->f64{*self.parameters.get(k).unwrap_or(&fallback)}
 fn history(&self,symbol:&str,field:&str,periods:usize)->Vec<f64>{let key=format!("{}|{}",symbol,field);match self.histories.get(&key){None=>vec![],Some(v)=>v[v.len().saturating_sub(periods)..].to_vec()}}
 fn target_percent(&mut self,symbol:&str,target:f64,reason:&str){self.pending.insert(symbol.to_string(),(target,reason.to_string()));}
 fn log(&self,message:&str,level:&str){println!("LOG\t{}\t{}",clean(level),clean(message));let _=io::stdout().flush();}
}
fn clean(s:&str)->String{s.replace(['\t','\n','\r']," ").chars().take(256).collect()}
fn mean(x:&[f64])->f64{if x.is_empty(){f64::NAN}else{x.iter().sum::<f64>()/x.len() as f64}}
"""

RUST_POSTLUDE = r"""
fn main(){let stdin=io::stdin();let mut lines=stdin.lock().lines();let mut parameters=HashMap::new();let mut _seed:i64=41;
 while let Some(Ok(line))=lines.next(){let p:Vec<&str>=line.split('\t').collect();if p.is_empty(){continue}if p[0]=="PARAM"&&p.len()>=3{parameters.insert(p[1].to_string(),p[2].parse().unwrap());}else if p[0]=="SEED"&&p.len()>=2{_seed=p[1].parse().unwrap();}else if p[0]=="START"{break}}
 let empty=PortfolioSnapshot{available:false,as_of:String::new(),base_currency:String::new(),nav_base:f64::NAN,sequence:0,ledger_sha256:String::new(),source:String::new(),reason:"AUTHORITATIVE_PORTFOLIO_NOT_CONNECTED".into(),positions:BTreeMap::new(),cash:BTreeMap::new(),unsettled_cash:BTreeMap::new(),open_orders:Vec::new(),margin:BTreeMap::new(),pnl:BTreeMap::new()};
 let mut ctx=Context{parameters,state_number:HashMap::new(),histories:HashMap::new(),pending:BTreeMap::new(),now:String::new(),portfolio:empty,positions:BTreeMap::new(),cash:BTreeMap::new(),open_orders:Vec::new()};initialize(&mut ctx);println!("READY");let _=io::stdout().flush();
 while let Some(Ok(line))=lines.next(){let p:Vec<&str>=line.split('\t').collect();if p.is_empty(){continue}if p[0]=="STOP"{break}
  if p[0]=="PORTFOLIO"&&p.len()>=14{let mut s=PortfolioSnapshot{available:p[1]=="1",as_of:p[2].into(),base_currency:p[3].into(),nav_base:if p[4].is_empty(){f64::NAN}else{p[4].parse().unwrap()},sequence:p[5].parse().unwrap(),ledger_sha256:p[6].into(),source:p[7].into(),reason:p[8].into(),positions:BTreeMap::new(),cash:BTreeMap::new(),unsettled_cash:BTreeMap::new(),open_orders:Vec::new(),margin:BTreeMap::new(),pnl:BTreeMap::new()};let pc:usize=p[9].parse().unwrap();let cc:usize=p[10].parse().unwrap();let oc:usize=p[11].parse().unwrap();let mc:usize=p[12].parse().unwrap();let nc:usize=p[13].parse().unwrap();
   for _ in 0..pc{let raw=lines.next().and_then(Result::ok).expect("missing position");let r:Vec<&str>=raw.split('\t').collect();if r.len()<8||r[0]!="POSITION"{panic!("invalid position")};s.positions.insert(r[1].into(),PositionSnapshot{quantity:r[2].parse().unwrap(),average_price:r[3].parse().unwrap(),last_price:r[4].parse().unwrap(),market_value_base:r[5].parse().unwrap(),realized_pnl_base:r[6].parse().unwrap(),unrealized_pnl_base:r[7].parse().unwrap()});}
   for _ in 0..cc{let raw=lines.next().and_then(Result::ok).expect("missing cash");let r:Vec<&str>=raw.split('\t').collect();if r.len()<4||r[0]!="CASH"{panic!("invalid cash")};s.cash.insert(r[1].into(),r[2].parse().unwrap());s.unsettled_cash.insert(r[1].into(),r[3].parse().unwrap());}
   for _ in 0..oc{let raw=lines.next().and_then(Result::ok).expect("missing order");let r:Vec<&str>=raw.split('\t').collect();if r.len()<10||r[0]!="OPEN_ORDER"{panic!("invalid order")};s.open_orders.push(OpenOrderSnapshot{order_id:r[1].into(),instrument_id:r[2].into(),side:r[3].into(),order_type:r[4].into(),time_in_force:r[5].into(),status:r[6].into(),quantity:r[7].parse().unwrap(),filled_quantity:r[8].parse().unwrap(),remaining_quantity:r[9].parse().unwrap()});}
   for _ in 0..mc{let raw=lines.next().and_then(Result::ok).expect("missing margin");let r:Vec<&str>=raw.split('\t').collect();if r.len()<3||r[0]!="MARGIN"{panic!("invalid margin")};s.margin.insert(r[1].into(),r[2].parse().unwrap());}
   for _ in 0..nc{let raw=lines.next().and_then(Result::ok).expect("missing pnl");let r:Vec<&str>=raw.split('\t').collect();if r.len()<3||r[0]!="PNL"{panic!("invalid pnl")};s.pnl.insert(r[1].into(),r[2].parse().unwrap());}
   ctx.positions=s.positions.clone();ctx.cash=s.cash.clone();ctx.open_orders=s.open_orders.clone();ctx.portfolio=s;continue}
  if p[0]!="SLICE"||p.len()<4{println!("ERROR\tinvalid child protocol");continue}
  let count:usize=p[3].parse().unwrap();let mut ordered:Vec<Bar>=Vec::new();let mut bars:BTreeMap<String,Bar>=BTreeMap::new();
  for _ in 0..count{let raw=lines.next().and_then(Result::ok).expect("missing bar");let bp:Vec<&str>=raw.split('\t').collect();if bp.len()<9||bp[0]!="BAR"{panic!("invalid bar in slice")};let b=Bar{event_time:bp[1].into(),available_at:bp[2].into(),symbol:bp[3].into(),open:bp[4].parse().unwrap(),high:bp[5].parse().unwrap(),low:bp[6].parse().unwrap(),close:bp[7].parse().unwrap(),volume:bp[8].parse().unwrap()};bars.insert(b.symbol.clone(),b.clone());ordered.push(b);}
  let slice=Slice{event_time:p[1].into(),available_at:p[2].into(),bars};ctx.now=slice.available_at.clone();ctx.pending.clear();
  for b in &ordered{for (field,value) in [("open",b.open),("high",b.high),("low",b.low),("close",b.close),("volume",b.volume)]{ctx.histories.entry(format!("{}|{}",b.symbol,field)).or_default().push(value);}}
  __CALLBACK_RUST__
  for (symbol,(target,reason)) in &ctx.pending{println!("SIGNAL\t{}\t{:.17}\t{}",symbol,target,clean(reason));}println!("END");let _=io::stdout().flush();
 }}
"""


CSHARP_PRELUDE = r"""using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
public class Bar { public string EventTime, AvailableAt, Symbol; public double Open, High, Low, Close, Volume; }
public class Slice { public string EventTime, AvailableAt; public SortedDictionary<string,Bar> Bars=new SortedDictionary<string,Bar>(); }
public class PositionSnapshot { public double Quantity, AveragePrice, LastPrice, MarketValueBase, RealizedPnlBase, UnrealizedPnlBase; }
public class OpenOrderSnapshot { public string OrderId, InstrumentId, Side, OrderType, TimeInForce, Status; public double Quantity, FilledQuantity, RemainingQuantity; }
public class PortfolioSnapshot { public bool Available=false; public string AsOf="", BaseCurrency="", LedgerSha256="", Source="", Reason="AUTHORITATIVE_PORTFOLIO_NOT_CONNECTED"; public double NavBase=double.NaN; public long Sequence=0; public SortedDictionary<string,PositionSnapshot> Positions=new SortedDictionary<string,PositionSnapshot>(); public SortedDictionary<string,double> Cash=new SortedDictionary<string,double>(), UnsettledCash=new SortedDictionary<string,double>(), Margin=new SortedDictionary<string,double>(), Pnl=new SortedDictionary<string,double>(); public List<OpenOrderSnapshot> OpenOrders=new List<OpenOrderSnapshot>(); }
public class Context {
 public Dictionary<string,double> Parameters=new Dictionary<string,double>(); public Dictionary<string,double> StateNumber=new Dictionary<string,double>(); public Dictionary<string,List<double>> Histories=new Dictionary<string,List<double>>(); public SortedDictionary<string,Tuple<double,string>> Pending=new SortedDictionary<string,Tuple<double,string>>(); public string Now="";
 public PortfolioSnapshot Portfolio=new PortfolioSnapshot(); public SortedDictionary<string,PositionSnapshot> Positions=new SortedDictionary<string,PositionSnapshot>(); public SortedDictionary<string,double> Cash=new SortedDictionary<string,double>(); public List<OpenOrderSnapshot> OpenOrders=new List<OpenOrderSnapshot>();
 public double Parameter(string k,double fallback){return Parameters.ContainsKey(k)?Parameters[k]:fallback;}
 public List<double> History(string symbol,string field,int periods){string k=symbol+"|"+field; if(!Histories.ContainsKey(k))return new List<double>();var v=Histories[k];return v.Skip(Math.Max(0,v.Count-periods)).ToList();}
 public void TargetPercent(string symbol,double target,string reason=""){Pending[symbol]=Tuple.Create(target,reason);}
 public void Log(string message,string level="INFO"){Console.WriteLine("LOG\t"+Program.Clean(level)+"\t"+Program.Clean(message));}
}
public static class UserStrategy {
 public static double Mean(List<double> x){return x.Count==0?double.NaN:x.Average();}
"""

CSHARP_POSTLUDE = r"""
}
public class Program {
 public static string Clean(string s){return (s??"").Replace("\t"," ").Replace("\r"," ").Replace("\n"," ").Substring(0,Math.Min(256,(s??"").Length));}
 public static void Main(){var ctx=new Context();string line;while((line=Console.ReadLine())!=null){var p=line.Split('\t');if(p[0]=="PARAM"&&p.Length>=3)ctx.Parameters[p[1]]=double.Parse(p[2],CultureInfo.InvariantCulture);else if(p[0]=="START")break;}UserStrategy.Initialize(ctx);Console.WriteLine("READY");
  while((line=Console.ReadLine())!=null){var p=line.Split('\t');if(p[0]=="STOP")break;
   if(p[0]=="PORTFOLIO"&&p.Length>=14){var s=new PortfolioSnapshot{Available=p[1]=="1",AsOf=p[2],BaseCurrency=p[3],NavBase=p[4]==""?double.NaN:double.Parse(p[4],CultureInfo.InvariantCulture),Sequence=long.Parse(p[5],CultureInfo.InvariantCulture),LedgerSha256=p[6],Source=p[7],Reason=p[8]};int pc=int.Parse(p[9]),cc=int.Parse(p[10]),oc=int.Parse(p[11]),mc=int.Parse(p[12]),nc=int.Parse(p[13]);
    for(int i=0;i<pc;i++){var r=Console.ReadLine().Split('\t');if(r[0]!="POSITION"||r.Length<8)throw new Exception("invalid position");s.Positions[r[1]]=new PositionSnapshot{Quantity=double.Parse(r[2],CultureInfo.InvariantCulture),AveragePrice=double.Parse(r[3],CultureInfo.InvariantCulture),LastPrice=double.Parse(r[4],CultureInfo.InvariantCulture),MarketValueBase=double.Parse(r[5],CultureInfo.InvariantCulture),RealizedPnlBase=double.Parse(r[6],CultureInfo.InvariantCulture),UnrealizedPnlBase=double.Parse(r[7],CultureInfo.InvariantCulture)};}
    for(int i=0;i<cc;i++){var r=Console.ReadLine().Split('\t');if(r[0]!="CASH"||r.Length<4)throw new Exception("invalid cash");s.Cash[r[1]]=double.Parse(r[2],CultureInfo.InvariantCulture);s.UnsettledCash[r[1]]=double.Parse(r[3],CultureInfo.InvariantCulture);}
    for(int i=0;i<oc;i++){var r=Console.ReadLine().Split('\t');if(r[0]!="OPEN_ORDER"||r.Length<10)throw new Exception("invalid order");s.OpenOrders.Add(new OpenOrderSnapshot{OrderId=r[1],InstrumentId=r[2],Side=r[3],OrderType=r[4],TimeInForce=r[5],Status=r[6],Quantity=double.Parse(r[7],CultureInfo.InvariantCulture),FilledQuantity=double.Parse(r[8],CultureInfo.InvariantCulture),RemainingQuantity=double.Parse(r[9],CultureInfo.InvariantCulture)});}
    for(int i=0;i<mc;i++){var r=Console.ReadLine().Split('\t');if(r[0]!="MARGIN"||r.Length<3)throw new Exception("invalid margin");s.Margin[r[1]]=double.Parse(r[2],CultureInfo.InvariantCulture);}
    for(int i=0;i<nc;i++){var r=Console.ReadLine().Split('\t');if(r[0]!="PNL"||r.Length<3)throw new Exception("invalid pnl");s.Pnl[r[1]]=double.Parse(r[2],CultureInfo.InvariantCulture);}
    ctx.Portfolio=s;ctx.Positions=s.Positions;ctx.Cash=s.Cash;ctx.OpenOrders=s.OpenOrders;continue;}
   if(p[0]!="SLICE"||p.Length<4){Console.WriteLine("ERROR\tinvalid child protocol");continue;}var slice=new Slice{EventTime=p[1],AvailableAt=p[2]};var ordered=new List<Bar>();int count=int.Parse(p[3],CultureInfo.InvariantCulture);for(int i=0;i<count;i++){var bp=Console.ReadLine().Split('\t');if(bp[0]!="BAR"||bp.Length<9)throw new Exception("invalid bar in slice");var b=new Bar{EventTime=bp[1],AvailableAt=bp[2],Symbol=bp[3],Open=double.Parse(bp[4],CultureInfo.InvariantCulture),High=double.Parse(bp[5],CultureInfo.InvariantCulture),Low=double.Parse(bp[6],CultureInfo.InvariantCulture),Close=double.Parse(bp[7],CultureInfo.InvariantCulture),Volume=double.Parse(bp[8],CultureInfo.InvariantCulture)};ordered.Add(b);slice.Bars[b.Symbol]=b;}ctx.Now=slice.AvailableAt;ctx.Pending.Clear();
   foreach(var b in ordered){foreach(var item in new[]{Tuple.Create("open",b.Open),Tuple.Create("high",b.High),Tuple.Create("low",b.Low),Tuple.Create("close",b.Close),Tuple.Create("volume",b.Volume)}){string k=b.Symbol+"|"+item.Item1;if(!ctx.Histories.ContainsKey(k))ctx.Histories[k]=new List<double>();ctx.Histories[k].Add(item.Item2);}}
   __CALLBACK_CSHARP__
   foreach(var kv in ctx.Pending)Console.WriteLine("SIGNAL\t"+kv.Key+"\t"+kv.Value.Item1.ToString("R",CultureInfo.InvariantCulture)+"\t"+Clean(kv.Value.Item2));Console.WriteLine("END");
  }} }
"""


def write(path: Path, payload: str) -> None:
    path.write_text(payload, encoding="utf-8")


def compiler_version(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=5, check=False
        )
        return clean_text((result.stdout or result.stderr).splitlines()[0], 300)
    except Exception as exc:
        return f"unavailable: {exc}"


def callback_mode(language: str, source: str) -> str:
    patterns = {
        "python": r"\bdef\s+on_slice\s*\(",
        "javascript": r"\bfunction\s+onSlice\s*\(",
        "typescript": r"\bfunction\s+onSlice\s*\(",
        "cpp": r"\bvoid\s+on_slice\s*\(",
        "rust": r"\bfn\s+on_slice\s*\(",
        "csharp": r"\b(?:static\s+)?void\s+OnSlice\s*\(",
    }
    pattern = patterns.get(str(language))
    return "on_slice" if pattern and re.search(pattern, source) else "on_bar"


def javascript_postlude(language: str, source: str, mode: str) -> str:
    """Build the JavaScript-family gateway without inventing SDK callbacks.

    JavaScript permits ``typeof initialize`` when the identifier is absent,
    whereas TypeScript rejects that same expression at compile time.  The
    TypeScript wrapper therefore emits the optional initialization call only
    when user code actually declares the callback.
    """

    postlude = JS_POSTLUDE.replace(
        "__CALLBACK_JS__",
        "onSlice(ctx, slice);"
        if mode == "on_slice"
        else "for (const item of sliceBars) onBar(ctx, item);",
    )
    if language != "typescript":
        return postlude

    postlude = postlude.replace(
        "const parameters = {}; let seed = 41; let ctx = null;",
        "const parameters: Record<string, number> = {}; "
        "let seed = 41; let ctx: Context | null = null;",
    )
    initializer_declared = re.search(
        r"\b(?:function\s+initialize\s*\(|(?:const|let|var)\s+initialize\b)",
        source,
    )
    return postlude.replace(
        'if (typeof initialize === "function") initialize(ctx);',
        "initialize(ctx);" if initializer_declared else "",
    )


def compile_strategy(
    language: str, source: str, timeout: int
) -> tuple[list[str], str, str, str]:
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True, mode=0o700)
    mode = callback_mode(language, source)
    if language == "python":
        path = ROOT / "strategy.py"
        write(path, PYTHON_PRELUDE + "\n" + source + "\n" + PYTHON_POSTLUDE)
        command = ["python3", "-m", "py_compile", str(path)]
        run_command = ["python3", "-I", str(path)]
        version = compiler_version(["python3", "--version"])
    elif language in {"javascript", "typescript"}:
        suffix = ".ts" if language == "typescript" else ".js"
        path = ROOT / ("strategy" + suffix)
        prefix = (
            "declare const require: any; declare const process: any;\n"
            "interface Context { parameters: Record<string, number>; "
            "state: Record<string, any>; seed: number; now: string | null; "
            "portfolio: Readonly<any>; "
            "positions: Readonly<Record<string, any>>; "
            "cash: Readonly<Record<string, number>>; "
            "openOrders: readonly any[]; "
            "_history: Map<string, number[]>; "
            "_pending: Map<string, [number, string]>; }\n"
            if language == "typescript"
            else ""
        )
        postlude = javascript_postlude(language, source, mode)
        write(path, prefix + JS_PRELUDE + "\n" + source + "\n" + postlude)
        if language == "typescript":
            command = [
                "tsc",
                str(path),
                "--target",
                "ES2020",
                "--module",
                "commonjs",
                "--outDir",
                str(ROOT / "out"),
                "--strict",
                "false",
                "--skipLibCheck",
            ]
            run_command = ["node", str(ROOT / "out" / "strategy.js")]
            version = compiler_version(["tsc", "--version"])
        else:
            command = ["node", "--check", str(path)]
            run_command = ["node", str(path)]
            version = compiler_version(["node", "--version"])
    elif language == "cpp":
        path = ROOT / "strategy.cpp"
        binary = ROOT / "strategy"
        postlude = CPP_POSTLUDE.replace(
            "__CALLBACK_CPP__",
            "on_slice(ctx,slice);"
            if mode == "on_slice"
            else "for(const auto& b:ordered)on_bar(ctx,b);",
        )
        write(path, CPP_PRELUDE + "\n" + source + "\n" + postlude)
        command = ["g++", "-std=c++20", "-O2", "-pipe", str(path), "-o", str(binary)]
        run_command = [str(binary)]
        version = compiler_version(["g++", "--version"])
    elif language == "rust":
        path = ROOT / "strategy.rs"
        binary = ROOT / "strategy"
        postlude = RUST_POSTLUDE.replace(
            "__CALLBACK_RUST__",
            "on_slice(&mut ctx,&slice);"
            if mode == "on_slice"
            else "for b in &ordered{on_bar(&mut ctx,b);}",
        )
        write(path, RUST_PRELUDE + "\n" + source + "\n" + postlude)
        command = ["rustc", "--edition=2021", "-O", str(path), "-o", str(binary)]
        run_command = [str(binary)]
        version = compiler_version(["rustc", "--version"])
    elif language == "csharp":
        path = ROOT / "strategy.cs"
        binary = ROOT / "strategy.exe"
        postlude = CSHARP_POSTLUDE.replace(
            "__CALLBACK_CSHARP__",
            "UserStrategy.OnSlice(ctx,slice);"
            if mode == "on_slice"
            else "foreach(var b in ordered)UserStrategy.OnBar(ctx,b);",
        )
        write(path, CSHARP_PRELUDE + "\n" + source + "\n" + postlude)
        command = ["mcs", "-optimize+", "-out:" + str(binary), str(path)]
        run_command = ["mono", str(binary)]
        version = compiler_version(["mcs", "--version"])
    else:
        raise ValueError(f"unsupported language: {language}")
    started = time.monotonic()
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout, check=False, cwd=ROOT
    )
    diagnostics = clean_text(
        (result.stdout or "") + "\n" + (result.stderr or ""), MAX_DIAGNOSTIC_BYTES
    )
    if result.returncode != 0:
        raise RuntimeError(diagnostics or f"compiler exited {result.returncode}")
    return run_command, version, diagnostics, mode


class LineReader:
    """Drain text pipes continuously so TextIO buffering cannot hide lines."""

    def __init__(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            raise RuntimeError("child stdout unavailable")
        self.process = process
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.thread = threading.Thread(
            target=self._drain, args=(process.stdout,), daemon=True
        )
        self.thread.start()

    def _drain(self, stream: Any) -> None:
        for line in stream:
            self.lines.put(line.rstrip("\r\n"))
        self.lines.put(None)

    def read(self, timeout: float) -> str:
        try:
            line = self.lines.get(timeout=max(0.01, timeout))
        except queue.Empty as exc:
            raise TimeoutError("strategy callback timeout") from exc
        if line is None:
            code = self.process.poll()
            raise RuntimeError(f"strategy process exited before response (code={code})")
        return line


def send_child(process: subprocess.Popen[str], line: str) -> None:
    if process.stdin is None:
        raise RuntimeError("child stdin unavailable")
    process.stdin.write(line + "\n")
    process.stdin.flush()


def _protocol_text(value: object, *, limit: int = 512) -> str:
    return str(value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")[:limit]


def _protocol_number(value: object, *, default: float = 0.0) -> str:
    if value is None:
        number = float(default)
    elif isinstance(value, bool):
        number = float(int(value))
    else:
        number = float(value)
    if not math.isfinite(number):
        raise ValueError("portfolio contains a non-finite numeric value")
    return f"{number:.17g}"


def send_portfolio(
    process: subprocess.Popen[str], payload: Mapping[str, Any] | None
) -> None:
    """Transmit a bounded, language-neutral authoritative snapshot."""

    raw = dict(payload or {})
    available = bool(raw.get("available", False))
    as_of = _protocol_text(raw.get("as_of"))
    source = _protocol_text(raw.get("source"))
    ledger_sha256 = _protocol_text(raw.get("ledger_sha256"), limit=64).lower()
    if available:
        if not as_of or source != "OMS_EXECUTION_LEDGER":
            raise ValueError("available portfolio must identify its OMS ledger clock")
        if len(ledger_sha256) != 64 or any(
            item not in "0123456789abcdef" for item in ledger_sha256
        ):
            raise ValueError("available portfolio requires an OMS ledger SHA-256")
    positions = dict(raw.get("positions") or {})
    cash = dict(raw.get("cash") or {})
    unsettled = dict(raw.get("unsettled_cash") or {})
    orders = list(raw.get("open_orders") or [])
    margin = {
        str(key): value
        for key, value in dict(raw.get("margin") or {}).items()
        if value is not None
    }
    pnl = {
        str(key): value
        for key, value in dict(raw.get("pnl") or {}).items()
        if value is not None
    }
    if len(positions) > 100_000 or len(orders) > 100_000:
        raise ValueError("portfolio snapshot exceeds protocol limits")
    nav = "" if raw.get("nav_base") is None else _protocol_number(raw.get("nav_base"))
    header = [
        "PORTFOLIO",
        "1" if available else "0",
        as_of,
        _protocol_text(raw.get("base_currency"), limit=3).upper(),
        nav,
        str(max(0, int(raw.get("sequence", 0)))),
        ledger_sha256,
        source,
        _protocol_text(
            raw.get("reason") or ("" if available else "AUTHORITATIVE_PORTFOLIO_NOT_CONNECTED")
        ),
        str(len(positions)),
        str(len(cash)),
        str(len(orders)),
        str(len(margin)),
        str(len(pnl)),
    ]
    send_child(process, "\t".join(header))
    for symbol, values in sorted(positions.items()):
        item = dict(values or {})
        send_child(
            process,
            "\t".join(
                [
                    "POSITION",
                    _protocol_text(symbol, limit=128).upper(),
                    _protocol_number(item.get("quantity")),
                    _protocol_number(item.get("average_price")),
                    _protocol_number(item.get("last_price")),
                    _protocol_number(item.get("market_value_base")),
                    _protocol_number(item.get("realized_pnl_base")),
                    _protocol_number(item.get("unrealized_pnl_base")),
                ]
            ),
        )
    for currency, value in sorted(cash.items()):
        send_child(
            process,
            "\t".join(
                [
                    "CASH",
                    _protocol_text(currency, limit=3).upper(),
                    _protocol_number(value),
                    _protocol_number(unsettled.get(currency, 0.0)),
                ]
            ),
        )
    for raw_order in orders:
        order = dict(raw_order or {})
        send_child(
            process,
            "\t".join(
                [
                    "OPEN_ORDER",
                    _protocol_text(order.get("order_id"), limit=128),
                    _protocol_text(
                        order.get("instrument_id") or order.get("symbol"), limit=128
                    ).upper(),
                    _protocol_text(order.get("side"), limit=16),
                    _protocol_text(order.get("order_type"), limit=32),
                    _protocol_text(order.get("time_in_force"), limit=16),
                    _protocol_text(order.get("status"), limit=32),
                    _protocol_number(order.get("quantity")),
                    _protocol_number(order.get("filled_quantity")),
                    _protocol_number(order.get("remaining_quantity")),
                ]
            ),
        )
    for name, value in sorted(margin.items()):
        send_child(
            process,
            "\t".join(["MARGIN", _protocol_text(name, limit=128), _protocol_number(value)]),
        )
    for name, value in sorted(pnl.items()):
        send_child(
            process,
            "\t".join(["PNL", _protocol_text(name, limit=128), _protocol_number(value)]),
        )


def main() -> int:
    raw = sys.stdin.readline()
    try:
        request = json.loads(raw)
        if request.get("type") != "prepare":
            raise ValueError("first message must be prepare")
        protocol_version = str(
            request.get("protocol_version") or SANDBOX_PROTOCOL_VERSION
        )
        if protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise ValueError(f"unsupported sandbox protocol: {protocol_version}")
        source = str(request.get("source", ""))
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("source exceeds 128 KiB")
        language = str(request["language"])
        compile_timeout = max(1, min(180, int(request.get("compile_seconds", 30))))
        callback_timeout = max(1, min(60, int(request.get("callback_seconds", 5))))
        started = time.monotonic()
        run_command, version, diagnostics, mode = compile_strategy(
            language, source, compile_timeout
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        if bool(request.get("compile_only")):
            emit(
                {
                    "type": "compiled",
                    "status": "PASS",
                    "compiler": version,
                    "duration_ms": duration_ms,
                    "diagnostics": diagnostics,
                    "callback_mode": mode,
                    "protocol_version": SANDBOX_PROTOCOL_VERSION,
                }
            )
            return 0
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONHASHSEED": str(int(request.get("seed", 41))),
        }
        process = subprocess.Popen(
            run_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1,
            cwd=ROOT,
            env=env,
            close_fds=True,
        )
        reader = LineReader(process)
        parameters = request.get("parameters") or {}
        if not isinstance(parameters, dict):
            raise ValueError("parameters must be an object")
        for key, value in sorted(parameters.items()):
            if not str(key).replace("_", "").isalnum():
                raise ValueError(f"invalid parameter name: {key}")
            if isinstance(value, bool):
                value = int(value)
            if not isinstance(value, (int, float)):
                raise ValueError(f"parameter {key} must be numeric")
            send_child(process, f"PARAM\t{key}\t{float(value):.17g}")
        send_child(process, f"SEED\t{int(request.get('seed',41))}")
        send_child(process, "START")
        while True:
            line = reader.read(callback_timeout)
            if line == "READY":
                break
            if line.startswith("LOG\t"):
                parts = line.split("\t", 2)
                emit(
                    {
                        "type": "log",
                        "level": parts[1] if len(parts) > 1 else "INFO",
                        "message": parts[2] if len(parts) > 2 else "",
                    }
                )
                continue
            raise RuntimeError(
                "unexpected strategy startup output: " + clean_text(line, 500)
            )
        emit(
            {
                "type": "ready",
                "status": "PASS",
                "compiler": version,
                "compile_duration_ms": duration_ms,
                "diagnostics": diagnostics,
                "callback_mode": mode,
                "protocol_version": SANDBOX_PROTOCOL_VERSION,
            }
        )
        for host_line in sys.stdin:
            message = json.loads(host_line)
            if message.get("type") == "stop":
                send_child(process, "STOP")
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                emit({"type": "stopped", "status": "PASS"})
                return 0
            message_type = message.get("type")
            if message_type not in {"bar", "slice"}:
                raise ValueError("expected slice, bar or stop")
            if message_type == "bar":
                bars = [message]
                event_time = message.get("event_time")
                available_at = message.get("available_at")
            else:
                bars = message.get("bars")
                event_time = message.get("event_time")
                available_at = message.get("available_at")
                if not isinstance(bars, list) or not bars:
                    raise ValueError("slice bars must be a non-empty list")
            send_portfolio(process, message.get("portfolio"))
            header = [event_time, available_at, len(bars)]
            if any("\t" in str(value) or "\n" in str(value) for value in header):
                raise ValueError("slice contains invalid control characters")
            send_child(process, "SLICE\t" + "\t".join(str(value) for value in header))
            seen_symbols: set[str] = set()
            for bar in bars:
                if not isinstance(bar, dict):
                    raise ValueError("slice bar must be an object")
                values = [
                    bar.get(name)
                    for name in (
                        "event_time",
                        "available_at",
                        "symbol",
                        "open",
                        "high",
                        "low",
                        "close",
                        "volume",
                    )
                ]
                if values[0] != event_time or values[1] != available_at:
                    raise ValueError("all bars in a slice must share its clocks")
                symbol = str(values[2]).strip().upper()
                if not symbol or symbol in seen_symbols:
                    raise ValueError("slice symbols must be non-empty and unique")
                seen_symbols.add(symbol)
                if any("\t" in str(value) or "\n" in str(value) for value in values):
                    raise ValueError("bar contains invalid control characters")
                send_child(process, "BAR\t" + "\t".join(str(value) for value in values))
            signals: list[dict[str, Any]] = []
            while True:
                line = reader.read(callback_timeout)
                if line == "END":
                    break
                parts = line.split("\t", 3)
                if parts[0] == "LOG":
                    emit(
                        {
                            "type": "log",
                            "level": parts[1] if len(parts) > 1 else "INFO",
                            "message": parts[2] if len(parts) > 2 else "",
                        }
                    )
                elif parts[0] == "SIGNAL" and len(parts) >= 3:
                    signals.append(
                        {
                            "symbol": parts[1],
                            "target": float(parts[2]),
                            "reason": parts[3] if len(parts) > 3 else "",
                        }
                    )
                elif parts[0] == "ERROR":
                    raise RuntimeError(
                        parts[1] if len(parts) > 1 else "strategy protocol error"
                    )
                else:
                    raise RuntimeError(
                        "unexpected strategy output: " + clean_text(line, 500)
                    )
            emit(
                {
                    "type": "signals",
                    "sequence": message.get("sequence"),
                    "signals": signals,
                }
            )
        return 0
    except Exception as exc:
        emit(
            {
                "type": "error",
                "status": "FAIL",
                "message": clean_text(exc),
                "error_class": type(exc).__name__,
            }
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
