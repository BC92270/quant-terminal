"""Language-native strategy templates for the causal sandbox SDK."""
from __future__ import annotations

from .contracts import StrategyLanguage


STRATEGY_TEMPLATES: dict[StrategyLanguage, str] = {
    StrategyLanguage.PYTHON: """def initialize(ctx):
    ctx.state.fast = int(ctx.parameters.get("fast", 20))
    ctx.state.slow = int(ctx.parameters.get("slow", 100))

def on_slice(ctx, slice):
    for symbol, bar in slice.bars.items():
        close = ctx.history(symbol, "close", ctx.state.slow)
        if len(close) < ctx.state.slow:
            ctx.target_percent(symbol, 0.0, reason_code="WARMUP")
            continue
        fast = close[-ctx.state.fast:].mean()
        slow = close.mean()
        ctx.target_percent(
            symbol,
            1.0 if fast > slow else 0.0,
            reason_code="SMA_CROSS",
        )
""",
    StrategyLanguage.JAVASCRIPT: """function initialize(ctx) {
  ctx.state.fast = Number(ctx.parameters.fast ?? 20);
  ctx.state.slow = Number(ctx.parameters.slow ?? 100);
}

function onSlice(ctx, slice) {
  const mean = xs => xs.reduce((a, b) => a + b, 0) / xs.length;
  for (const symbol of slice.symbols) {
    const close = ctx.history(symbol, "close", ctx.state.slow);
    if (close.length < ctx.state.slow) {
      ctx.targetPercent(symbol, 0.0, "WARMUP");
      continue;
    }
    const fast = mean(close.slice(-ctx.state.fast));
    ctx.targetPercent(symbol, fast > mean(close) ? 1.0 : 0.0, "SMA_CROSS");
  }
}
""",
    StrategyLanguage.TYPESCRIPT: """function initialize(ctx: any): void {
  ctx.state.fast = Number(ctx.parameters.fast ?? 20);
  ctx.state.slow = Number(ctx.parameters.slow ?? 100);
}

function onSlice(ctx: any, slice: any): void {
  const mean = (xs: number[]): number => xs.reduce((a, b) => a + b, 0) / xs.length;
  for (const symbol of slice.symbols) {
    const close: number[] = ctx.history(symbol, "close", ctx.state.slow);
    if (close.length < ctx.state.slow) {
      ctx.targetPercent(symbol, 0.0, "WARMUP");
      continue;
    }
    const fast = mean(close.slice(-ctx.state.fast));
    ctx.targetPercent(symbol, fast > mean(close) ? 1.0 : 0.0, "SMA_CROSS");
  }
}
""",
    StrategyLanguage.CPP: """void initialize(Context& ctx) {
    ctx.state_number["fast"] = ctx.parameter("fast", 20.0);
    ctx.state_number["slow"] = ctx.parameter("slow", 100.0);
}

void on_slice(Context& ctx, const Slice& slice) {
    const int fast_n = static_cast<int>(ctx.state_number["fast"]);
    const int slow_n = static_cast<int>(ctx.state_number["slow"]);
    for (const auto& item : slice.bars) {
        const auto& bar = item.second;
        const auto close = ctx.history(bar.symbol, "close", slow_n);
        if (static_cast<int>(close.size()) < slow_n) {
            ctx.target_percent(bar.symbol, 0.0, "WARMUP");
            continue;
        }
        const double slow = mean(close);
        const double fast = mean(tail(close, fast_n));
        ctx.target_percent(bar.symbol, fast > slow ? 1.0 : 0.0, "SMA_CROSS");
    }
}
""",
    StrategyLanguage.RUST: """fn initialize(ctx: &mut Context) {
    let fast = ctx.parameter("fast", 20.0);
    let slow = ctx.parameter("slow", 100.0);
    ctx.state_number.insert("fast".to_string(), fast);
    ctx.state_number.insert("slow".to_string(), slow);
}

fn on_slice(ctx: &mut Context, slice: &Slice) {
    let fast_n = ctx.state_number["fast"] as usize;
    let slow_n = ctx.state_number["slow"] as usize;
    for bar in slice.bars.values() {
        let close = ctx.history(&bar.symbol, "close", slow_n);
        if close.len() < slow_n {
            ctx.target_percent(&bar.symbol, 0.0, "WARMUP");
            continue;
        }
        let slow = mean(&close);
        let fast = mean(&close[close.len() - fast_n..]);
        ctx.target_percent(&bar.symbol, if fast > slow { 1.0 } else { 0.0 }, "SMA_CROSS");
    }
}
""",
    StrategyLanguage.CSHARP: """public static void Initialize(Context ctx) {
    ctx.StateNumber["fast"] = ctx.Parameter("fast", 20.0);
    ctx.StateNumber["slow"] = ctx.Parameter("slow", 100.0);
}

public static void OnSlice(Context ctx, Slice slice) {
    int fastN = (int)ctx.StateNumber["fast"];
    int slowN = (int)ctx.StateNumber["slow"];
    foreach (var bar in slice.Bars.Values) {
        var close = ctx.History(bar.Symbol, "close", slowN);
        if (close.Count < slowN) {
            ctx.TargetPercent(bar.Symbol, 0.0, "WARMUP");
            continue;
        }
        double slow = Mean(close);
        double fast = Mean(close.GetRange(close.Count - fastN, fastN));
        ctx.TargetPercent(bar.Symbol, fast > slow ? 1.0 : 0.0, "SMA_CROSS");
    }
}
""",
}


def template_for(language: str | StrategyLanguage) -> str:
    return STRATEGY_TEMPLATES[StrategyLanguage.parse(language)]
