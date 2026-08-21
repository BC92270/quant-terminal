"""Apply the fixed-income V8 modular migration atomically and reproducibly."""

from __future__ import annotations

import hashlib
from pathlib import Path


TARGET = Path("fixed_income_credit.py")
EXPECTED_V7_SHA256 = "192fbb036711ae5fed32f5e690a5f8ae2f5cde28726512547acc8c353cd66eee"


def replace_function(source: str, name: str, next_name: str, replacement: str) -> str:
    start = source.index(f"def {name}(")
    end = source.index(f"\ndef {next_name}(", start)
    return source[:start] + replacement.rstrip() + "\n\n" + source[end + 1 :]


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    if 'MODULE_VERSION = "8.0.0-industrialized-core"' in source:
        print("V8 migration already applied")
        return
    if digest != EXPECTED_V7_SHA256:
        raise RuntimeError(
            "Refusing migration: fixed_income_credit.py does not match the protected V7 baseline"
        )

    source = replace_function(
        source,
        "refinancing_schedule_analytics",
        "_fic7_bounded_simplex",
        '''def refinancing_schedule_analytics(
    schedule: pd.DataFrame,
    cash: float = 0.0,
    revolver: float = 0.0,
    annual_fcf: float = 0.0,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Compatibility facade backed by the modular refinancing engine."""
    from fixed_income.analytics.refinancing import analyze_refinancing_schedule

    return analyze_refinancing_schedule(schedule, cash, revolver, annual_fcf)
''',
    )
    source = replace_function(
        source,
        "fixed_income_portfolio_optimizer",
        "decision_journal_diagnostics",
        '''def fixed_income_portfolio_optimizer(
    universe: pd.DataFrame,
    objective: str = "Risk-adjusted",
    risk_aversion: float = 6.0,
    turnover_cost_bp: float = 15.0,
    sector_cap_pct: float = 35.0,
    nav: float = 100_000_000.0,
) -> dict[str, Any]:
    """Compatibility facade backed by the modular constrained optimizer."""
    from fixed_income.analytics.portfolio import optimize_portfolio

    return optimize_portfolio(
        universe,
        objective=objective,
        risk_aversion=risk_aversion,
        turnover_cost_bp=turnover_cost_bp,
        sector_cap_pct=sector_cap_pct,
        nav=nav,
    )
''',
    )
    source = replace_function(
        source,
        "decision_journal_diagnostics",
        "point_in_time_leakage_audit",
        '''def decision_journal_diagnostics(
    journal: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Compatibility facade backed by the modular decision engine."""
    from fixed_income.research.decision import diagnose_decisions

    return diagnose_decisions(journal)
''',
    )
    source = replace_function(
        source,
        "point_in_time_leakage_audit",
        "_fic7_money",
        '''def point_in_time_leakage_audit(
    observations: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Compatibility facade backed by the modular point-in-time control."""
    from fixed_income.research.decision import audit_point_in_time

    return audit_point_in_time(observations)
''',
    )
    source = source.replace(
        'MODULE_VERSION = "7.0.0-decision-intelligence"',
        'MODULE_VERSION = "8.0.0-industrialized-core"',
    )
    source = source.replace(
        '"""Institutional V7.0 public entry point — integrated research and decision workstation."""',
        '"""Institutional V8.0 public entry point — modular research and decision workstation."""',
    )
    source = source.replace(
        "point-in-time validation and evidence-governed decisions. Version {MODULE_VERSION}.",
        "point-in-time validation, modular engines, validated units and evidence-governed decisions. Version {MODULE_VERSION}.",
    )

    compile(source, str(TARGET), "exec")
    temporary = TARGET.with_suffix(".py.v8tmp")
    temporary.write_text(source, encoding="utf-8")
    temporary.replace(TARGET)
    migrated_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    print(f"V8 migration applied: {migrated_hash}")


if __name__ == "__main__":
    main()
