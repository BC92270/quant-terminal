#!/usr/bin/env python3
"""In-container compiler and causal JSONL/TSV strategy gateway.

Only this fixed program can talk to the host controller.  User code runs in a
child process and receives one already-available bar at a time.  It can emit
targets and logs; it never receives cash, fills, P&L or future observations.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
from typing import Any


ROOT = Path("/tmp/quant-strategy")
MAX_SOURCE_BYTES = 128 * 1024
MAX_DIAGNOSTIC_BYTES = 256 * 1024


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

class Context:
    def __init__(self, parameters, seed):
        self.parameters = parameters
        self.state = State()
        self.rng = random.Random(seed)
        self.now = None
        self._history = {}
        self._pending = {}
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
    if _parts[0] != "BAR" or len(_parts) < 9:
        print("ERROR\tinvalid child protocol", flush=True)
        continue
    _bar = Bar(_parts)
    _ctx.now = _bar.available_at
    _ctx._pending = {}
    _append_bar(_ctx, _bar)
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
function appendBar(context, bar) {
  for (const field of ["open", "high", "low", "close", "volume"]) {
    const key = bar.symbol + "|" + field;
    const values = context._history.get(key) || []; values.push(Number(bar[field]));
    context._history.set(key, values);
  }
}
rl.on("line", (line) => {
  const p = line.split("\t");
  if (p[0] === "PARAM" && p.length >= 3) { parameters[p[1]] = Number(p[2]); return; }
  if (p[0] === "SEED") { seed = Number(p[1]); return; }
  if (p[0] === "START") {
    ctx = new Context(parameters, seed); if (typeof initialize === "function") initialize(ctx);
    process.stdout.write("READY\n"); return;
  }
  if (p[0] === "STOP") { rl.close(); return; }
  if (p[0] !== "BAR" || p.length < 9 || ctx === null) {
    process.stdout.write("ERROR\tinvalid child protocol\n"); return;
  }
  const bar = {eventTime:p[1], availableAt:p[2], symbol:p[3], open:Number(p[4]),
    high:Number(p[5]), low:Number(p[6]), close:Number(p[7]), volume:Number(p[8])};
  ctx.now = bar.availableAt; ctx._pending = new Map(); appendBar(ctx, bar); onBar(ctx, bar);
  for (const [symbol, pair] of Array.from(ctx._pending.entries()).sort()) {
    const reason = String(pair[1]).replace(/[\t\r\n]/g, " ").slice(0,256);
    process.stdout.write("SIGNAL\t" + symbol + "\t" + Number(pair[0]).toPrecision(17) + "\t" + reason + "\n");
  }
  process.stdout.write("END\n");
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
static std::vector<std::string> split_tab(const std::string& s) { std::vector<std::string> out; std::stringstream ss(s); std::string x; while(std::getline(ss,x,'\t')) out.push_back(x); return out; }
static std::string clean(std::string s) { std::replace(s.begin(),s.end(),'\t',' '); std::replace(s.begin(),s.end(),'\n',' '); if(s.size()>256)s.resize(256); return s; }
static double mean(const std::vector<double>& x) { return x.empty()?NAN:std::accumulate(x.begin(),x.end(),0.0)/x.size(); }
static std::vector<double> tail(const std::vector<double>& x, int n) { if(n<=0)return {}; auto p=x.begin()+std::max(0,static_cast<int>(x.size())-n); return {p,x.end()}; }
struct Context {
  std::map<std::string,double> parameters, state_number;
  std::map<std::string,std::vector<double>> histories;
  std::map<std::string,std::pair<double,std::string>> pending;
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
  while(std::getline(std::cin,line)){ auto p=split_tab(line); if(p.empty())continue; if(p[0]=="STOP")break; if(p[0]!="BAR"||p.size()<9){std::cout<<"ERROR\tinvalid child protocol"<<std::endl;continue;}
    Bar b{p[1],p[2],p[3],std::stod(p[4]),std::stod(p[5]),std::stod(p[6]),std::stod(p[7]),std::stod(p[8])}; ctx.now=b.available_at; ctx.pending.clear();
    ctx.histories[b.symbol+"|open"].push_back(b.open);ctx.histories[b.symbol+"|high"].push_back(b.high);ctx.histories[b.symbol+"|low"].push_back(b.low);ctx.histories[b.symbol+"|close"].push_back(b.close);ctx.histories[b.symbol+"|volume"].push_back(b.volume);
    on_bar(ctx,b); for(const auto& kv:ctx.pending)std::cout<<"SIGNAL\t"<<kv.first<<"\t"<<std::setprecision(17)<<kv.second.first<<"\t"<<clean(kv.second.second)<<std::endl; std::cout<<"END"<<std::endl;
  } return 0; }
"""


RUST_PRELUDE = r"""use std::collections::{BTreeMap, HashMap};
use std::io::{self, BufRead, Write};
#[derive(Clone)] struct Bar { event_time:String, available_at:String, symbol:String, open:f64, high:f64, low:f64, close:f64, volume:f64 }
struct Context { parameters:HashMap<String,f64>, state_number:HashMap<String,f64>, histories:HashMap<String,Vec<f64>>, pending:BTreeMap<String,(f64,String)>, now:String }
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
 let mut ctx=Context{parameters,state_number:HashMap::new(),histories:HashMap::new(),pending:BTreeMap::new(),now:String::new()};initialize(&mut ctx);println!("READY");let _=io::stdout().flush();
 while let Some(Ok(line))=lines.next(){let p:Vec<&str>=line.split('\t').collect();if p.is_empty(){continue}if p[0]=="STOP"{break}if p[0]!="BAR"||p.len()<9{println!("ERROR\tinvalid child protocol");continue}
  let b=Bar{event_time:p[1].into(),available_at:p[2].into(),symbol:p[3].into(),open:p[4].parse().unwrap(),high:p[5].parse().unwrap(),low:p[6].parse().unwrap(),close:p[7].parse().unwrap(),volume:p[8].parse().unwrap()};ctx.now=b.available_at.clone();ctx.pending.clear();
  for (field,value) in [("open",b.open),("high",b.high),("low",b.low),("close",b.close),("volume",b.volume)]{ctx.histories.entry(format!("{}|{}",b.symbol,field)).or_default().push(value);}
  on_bar(&mut ctx,&b);for (symbol,(target,reason)) in &ctx.pending{println!("SIGNAL\t{}\t{:.17}\t{}",symbol,target,clean(reason));}println!("END");let _=io::stdout().flush();
 }}
"""


CSHARP_PRELUDE = r"""using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
public class Bar { public string EventTime, AvailableAt, Symbol; public double Open, High, Low, Close, Volume; }
public class Context {
 public Dictionary<string,double> Parameters=new Dictionary<string,double>(); public Dictionary<string,double> StateNumber=new Dictionary<string,double>(); public Dictionary<string,List<double>> Histories=new Dictionary<string,List<double>>(); public SortedDictionary<string,Tuple<double,string>> Pending=new SortedDictionary<string,Tuple<double,string>>(); public string Now="";
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
  while((line=Console.ReadLine())!=null){var p=line.Split('\t');if(p[0]=="STOP")break;if(p[0]!="BAR"||p.Length<9){Console.WriteLine("ERROR\tinvalid child protocol");continue;}var b=new Bar{EventTime=p[1],AvailableAt=p[2],Symbol=p[3],Open=double.Parse(p[4],CultureInfo.InvariantCulture),High=double.Parse(p[5],CultureInfo.InvariantCulture),Low=double.Parse(p[6],CultureInfo.InvariantCulture),Close=double.Parse(p[7],CultureInfo.InvariantCulture),Volume=double.Parse(p[8],CultureInfo.InvariantCulture)};ctx.Now=b.AvailableAt;ctx.Pending.Clear();
   foreach(var item in new[]{Tuple.Create("open",b.Open),Tuple.Create("high",b.High),Tuple.Create("low",b.Low),Tuple.Create("close",b.Close),Tuple.Create("volume",b.Volume)}){string k=b.Symbol+"|"+item.Item1;if(!ctx.Histories.ContainsKey(k))ctx.Histories[k]=new List<double>();ctx.Histories[k].Add(item.Item2);}UserStrategy.OnBar(ctx,b);foreach(var kv in ctx.Pending)Console.WriteLine("SIGNAL\t"+kv.Key+"\t"+kv.Value.Item1.ToString("R",CultureInfo.InvariantCulture)+"\t"+Clean(kv.Value.Item2));Console.WriteLine("END");
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


def compile_strategy(
    language: str, source: str, timeout: int
) -> tuple[list[str], str, str]:
    shutil.rmtree(ROOT, ignore_errors=True)
    ROOT.mkdir(parents=True, mode=0o700)
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
            if language == "typescript"
            else ""
        )
        write(path, prefix + JS_PRELUDE + "\n" + source + "\n" + JS_POSTLUDE)
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
        write(path, CPP_PRELUDE + "\n" + source + "\n" + CPP_POSTLUDE)
        command = ["g++", "-std=c++20", "-O2", "-pipe", str(path), "-o", str(binary)]
        run_command = [str(binary)]
        version = compiler_version(["g++", "--version"])
    elif language == "rust":
        path = ROOT / "strategy.rs"
        binary = ROOT / "strategy"
        write(path, RUST_PRELUDE + "\n" + source + "\n" + RUST_POSTLUDE)
        command = ["rustc", "--edition=2021", "-O", str(path), "-o", str(binary)]
        run_command = [str(binary)]
        version = compiler_version(["rustc", "--version"])
    elif language == "csharp":
        path = ROOT / "strategy.cs"
        binary = ROOT / "strategy.exe"
        write(path, CSHARP_PRELUDE + "\n" + source + "\n" + CSHARP_POSTLUDE)
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
    return run_command, version, diagnostics


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


def main() -> int:
    raw = sys.stdin.readline()
    try:
        request = json.loads(raw)
        if request.get("type") != "prepare":
            raise ValueError("first message must be prepare")
        source = str(request.get("source", ""))
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("source exceeds 128 KiB")
        language = str(request["language"])
        compile_timeout = max(1, min(180, int(request.get("compile_seconds", 30))))
        callback_timeout = max(1, min(60, int(request.get("callback_seconds", 5))))
        started = time.monotonic()
        run_command, version, diagnostics = compile_strategy(
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
            if message.get("type") != "bar":
                raise ValueError("expected bar or stop")
            values = [
                message.get(name)
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
