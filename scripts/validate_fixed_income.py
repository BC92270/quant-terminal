"""Fail-closed validation gate for the fixed-income industrialized core."""

from __future__ import annotations

import compileall
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from fixed_income.analytics.portfolio import optimize_portfolio
from fixed_income.analytics.refinancing import analyze_refinancing_schedule
from fixed_income.contracts import DataClassification, DataPoint
from fixed_income.data.store import PointInTimeStore
from fixed_income.governance.audit import AuditTrail
from fixed_income.services.observability import HealthMonitor


def main() -> int:
    checks: dict[str, object] = {}
    checks["compile"] = bool(compileall.compile_dir("fixed_income", quiet=1))

    universe = pd.DataFrame(
        [
            ["A", "Issuer A", "Technology", "A", 5.0, 4.0, 25, 0, 50, 4.0, 3.8, 20, 80],
            ["B", "Issuer B", "Financials", "BBB", 6.0, 5.0, 25, 0, 50, 5.0, 4.8, 40, 70],
            ["C", "Issuer C", "Utilities", "BBB", 6.5, 6.0, 25, 0, 50, 7.0, 6.8, 50, 65],
            ["D", "Cash", "Liquidity", "NR", 3.5, 0.5, 25, 0, 50, 0.1, 0.0, 0, 100],
        ],
        columns=[
            "identifier", "issuer", "sector", "rating", "expected_return_pct",
            "volatility_pct", "current_weight_pct", "min_weight_pct",
            "max_weight_pct", "duration", "spread_duration", "expected_loss_bp",
            "liquidity_score",
        ],
    )
    optimized = optimize_portfolio(universe, sector_cap_pct=50.0)
    checks["optimizer"] = (
        optimized.get("errors") == []
        and abs(float(optimized["assets"]["optimized_weight_pct"].sum()) - 100.0) < 1e-7
    )

    schedule = pd.DataFrame(
        {
            "year": [2027, 2028],
            "debt_due": [100.0, 200.0],
            "coupon_pct": [3.0, 4.0],
            "benchmark_pct": [4.0, 4.0],
            "current_spread_bp": [100.0, 100.0],
            "refi_spread_bp": [150.0, 175.0],
            "secured_pct": [0.0, 0.0],
        }
    )
    _, refinancing = analyze_refinancing_schedule(
        schedule, cash=100.0, revolver=50.0, annual_fcf=25.0
    )
    checks["refinancing"] = refinancing["total_debt_due"] == 300.0

    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = PointInTimeStore(root / "pit.sqlite3")
        point = DataPoint(
            series_id="VALIDATION",
            value=1.0,
            observation_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            available_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
            source="validation",
            classification=DataClassification.OBSERVED,
        )
        store.insert_observations([point])
        checks["store"] = (
            store.latest_as_of(
                "VALIDATION", datetime(2026, 1, 3, tzinfo=timezone.utc)
            ) is not None
            and store.health()["integrity"] == "ok"
        )
        trail = AuditTrail(root / "audit.jsonl")
        trail.append("validator", "CHECK", "release", "fixed-income-v8", checks)
        checks["audit"] = trail.verify()["ok"]

    monitor = HealthMonitor()
    for name, value in checks.items():
        monitor.register(name, lambda value=value: value if value else _fail(name))
    health = monitor.check()
    result = {"ok": all(bool(value) for value in checks.values()), "checks": checks, "health": health}
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["ok"] else 1


def _fail(name: str) -> None:
    raise RuntimeError(f"validation failed: {name}")


if __name__ == "__main__":
    raise SystemExit(main())
