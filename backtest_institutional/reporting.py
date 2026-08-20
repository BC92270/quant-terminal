"""Governance model cards and reproducible export bundles."""
from __future__ import annotations

from dataclasses import asdict
from io import BytesIO
import json
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd

from .registry import _json_safe
from .types import RunManifest


def build_model_card(
    *,
    manifest: RunManifest,
    data_catalog: dict[str, Any],
    execution: dict[str, Any],
    validation: dict[str, Any],
    scenarios: dict[str, Any],
) -> dict[str, Any]:
    capabilities = data_catalog.get("capabilities", {})
    unavailable = [name for name, item in capabilities.items() if item.get("state") == "UNAVAILABLE"]
    limitations = []
    if unavailable:
        limitations.append("Unavailable data capabilities: " + ", ".join(unavailable))
    if execution.get("short_borrow_available") is False:
        limitations.append("Short borrow/rebate was not fully observable")
    if validation.get("candidate_count", 1) <= 1:
        limitations.append("Multiple-testing statistics are conservative with a single supplied candidate")
    return {
        "model_id": "Institutional-Backtest-V7",
        "run_id": manifest.run_id,
        "purpose": "Research validation, execution realism, scenario analysis and deployment gating",
        "intended_use": "Decision support; not an order-routing or accounting book of record",
        "methodology": {
            "signal_timing": "Signal is executed no earlier than the next eligible bar",
            "execution": execution.get("model", "UNAVAILABLE"),
            "statistics": ["PSR", "DSR", "CSCV/PBO", "White Reality Check", "Hansen SPA", "Holm", "BH/FDR"],
            "scenarios": ["Student-t multivariate", "Markov regimes", "EVT tail", "liquidity spiral", "reverse stress"],
        },
        "data_verdict": data_catalog.get("verdict", "UNAVAILABLE"),
        "limitations": limitations,
        "approval_policy": {
            "fail_closed": True,
            "data_unavailable_is_not_zero": True,
            "required_gates": ["data", "execution", "statistical validity", "scenario resilience", "operational QA"],
        },
    }


def build_governance_bundle(
    *,
    manifest: RunManifest,
    config: dict[str, Any],
    data_catalog: dict[str, Any],
    execution: dict[str, Any],
    validation: dict[str, Any],
    scenarios: dict[str, Any],
    tables: dict[str, pd.DataFrame] | None = None,
) -> bytes:
    model_card = build_model_card(
        manifest=manifest,
        data_catalog=data_catalog,
        execution=execution,
        validation=validation,
        scenarios=scenarios,
    )
    payloads = {
        "manifest.json": asdict(manifest),
        "config.json": config,
        "data_catalog.json": data_catalog,
        "execution_diagnostics.json": execution,
        "validation.json": validation,
        "scenario_metadata.json": scenarios,
        "model_card.json": model_card,
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in payloads.items():
            archive.writestr(name, json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n")
        for name, table in (tables or {}).items():
            archive.writestr(f"tables/{name}.csv", table.to_csv(index=True))
        archive.writestr(
            "README.txt",
            "Institutional Backtest V7 reproducibility bundle\n"
            "All N/A states are explicit; unavailable external data is never coerced to zero.\n"
            "Validate the code, data licence and approvals before production use.\n",
        )
    return buffer.getvalue()
