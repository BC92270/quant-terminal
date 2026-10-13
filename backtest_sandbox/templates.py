"""Language-native strategy templates for the causal sandbox SDK."""
from __future__ import annotations

from .contracts import StrategyLanguage


STRATEGY_TEMPLATES: dict[StrategyLanguage, str] = {
    StrategyLanguage.PYTHON: """def initialize(ctx):
    ctx.state.fast = int(ctx.parameters.get("fast", 20))
    ctx.state.slow = int(ctx.parameters.get("slow", 100))

def on_bar(ctx, bar):
    close = ctx.history(bar.symbol, "close", ctx.state.slow)
    if len(close) < ctx.state.slow:
        ctx.target_percent(bar.symbol, 0.0, reason_code="WARMUP")
        return
    fast = close[-ctx.state.fast:].mean()
    slow = close.mean()
    ctx.target_percent(
        bar.symbol,
        1.0 if fast > slow else 0.0,
        reason_code="SMA_CROSS",
    )
""",
    StrategyLanguage.JAVASCRIPT: """function initialize(ctx) {
  ctx.state.fast = Number(ctx.parameters.fast ?? 20);
  ctx.state.slow = Number(ctx.parameters.slow ?? 100);
}

function onBar(ctx, bar) {
  const close = ctx.history(bar.symbol, "close", ctx.state.slow);
  if (close.length < ctx.state.slow) {
    ctx.targetPercent(bar.symbol, 0.0, "WARMUP");
    return;
  }
  const mean = xs => xs.reduce((a, b) => a + b, 0) / xs.length;
  const fast = mean(close.slice(-ctx.state.fast));
  ctx.targetPercent(bar.symbol, fast > mean(close) ? 1.0 : 0.0, "SMA_CROSS");
}
""",
    StrategyLanguage.TYPESCRIPT: """function initialize(ctx: any): void {
  ctx.state.fast = Number(ctx.parameters.fast ?? 20);
  ctx.state.slow = Number(ctx.parameters.slow ?? 100);
}

function onBar(ctx: any, bar: any): void {
  const close: number[] = ctx.history(bar.symbol, "close", ctx.state.slow);
  if (close.length < ctx.state.slow) {
    ctx.targetPercent(bar.symbol, 0.0, "WARMUP");
    return;
  }
  const mean = (xs: number[]): number => xs.reduce((a, b) => a + b, 0) / xs.length;
  const fast = mean(close.slice(-ctx.state.fast));
  ctx.targetPercent(bar.symbol, fast > mean(close) ? 1.0 : 0.0, "SMA_CROSS");
}
""",
    StrategyLanguage.CPP: """void initialize(Context& ctx) {
    ctx.state_number["fast"] = ctx.parameter("fast", 20.0);
    ctx.state_number["slow"] = ctx.parameter("slow", 100.0);
}

void on_bar(Context& ctx, const Bar& bar) {
    const int fast_n = static_cast<int>(ctx.state_number["fast"]);
    const int slow_n = static_cast<int>(ctx.state_number["slow"]);
    const auto close = ctx.history(bar.symbol, "close", slow_n);
    if (static_cast<int>(close.size()) < slow_n) {
        ctx.target_percent(bar.symbol, 0.0, "WARMUP");
        return;
    }
    const double slow = mean(close);
    const double fast = mean(tail(close, fast_n));
    ctx.target_percent(bar.symbol, fast > slow ? 1.0 : 0.0, "SMA_CROSS");
}
""",
    StrategyLanguage.RUST: """fn initialize(ctx: &mut Context) {
    let fast = ctx.parameter("fast", 20.0);
    let slow = ctx.parameter("slow", 100.0);
    ctx.state_number.insert("fast".to_string(), fast);
    ctx.state_number.insert("slow".to_string(), slow);
}

fn on_bar(ctx: &mut Context, bar: &Bar) {
    let fast_n = ctx.state_number["fast"] as usize;
    let slow_n = ctx.state_number["slow"] as usize;
    let close = ctx.history(&bar.symbol, "close", slow_n);
    if close.len() < slow_n {
        ctx.target_percent(&bar.symbol, 0.0, "WARMUP");
        return;
    }
    let slow = mean(&close);
    let fast = mean(&close[close.len() - fast_n..]);
    ctx.target_percent(&bar.symbol, if fast > slow { 1.0 } else { 0.0 }, "SMA_CROSS");
}
""",
    StrategyLanguage.CSHARP: """public static void Initialize(Context ctx) {
    ctx.StateNumber["fast"] = ctx.Parameter("fast", 20.0);
    ctx.StateNumber["slow"] = ctx.Parameter("slow", 100.0);
}

public static void OnBar(Context ctx, Bar bar) {
    int fastN = (int)ctx.StateNumber["fast"];
    int slowN = (int)ctx.StateNumber["slow"];
    var close = ctx.History(bar.Symbol, "close", slowN);
    if (close.Count < slowN) {
        ctx.TargetPercent(bar.Symbol, 0.0, "WARMUP");
        return;
    }
    double slow = Mean(close);
    double fast = Mean(close.GetRange(close.Count - fastN, fastN));
    ctx.TargetPercent(bar.Symbol, fast > slow ? 1.0 : 0.0, "SMA_CROSS");
}
""",
}


def template_for(language: str | StrategyLanguage) -> str:
    return STRATEGY_TEMPLATES[StrategyLanguage.parse(language)]
