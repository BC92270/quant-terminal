"""Verify the V3.4 release freeze, byte inventory and full lineage."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_gate_compiler import canonical_json_sha256
from .phase3_optimized_oracle import load_v34_spec
from .verify_phase3_v34 import verify_release_chain


VERIFY_VERSION = "QUANTUM LAB V3.4 FREEZE CONTRACT VERIFIER · V1"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def verify_freeze_contract(
    root: str | Path,
    contract_path: str | Path,
) -> dict[str, Any]:
    release_root = Path(root).resolve()
    freeze_path = Path(contract_path).resolve()
    try:
        payload = _read_json(freeze_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "checks": {"freeze_readable": False},
            "errors": [str(exc)],
            "failed_checks": ["freeze_readable"],
            "valid": False,
            "verifier_version": VERIFY_VERSION,
        }

    errors: list[str] = []
    core = {
        key: value for key, value in payload.items() if key != "freeze_contract_sha256"
    }
    computed_self_hash = canonical_json_sha256(core)
    file_results: dict[str, dict[str, Any]] = {}
    for relative, expected in sorted((payload.get("frozen_files") or {}).items()):
        target = release_root / relative
        try:
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
        except OSError as exc:
            actual = None
            errors.append(f"{relative}: {exc}")
        file_results[relative] = {
            "actual_sha256": actual,
            "expected_sha256": expected,
            "valid": actual == expected,
        }

    paths = payload.get("release_paths") or {}
    try:
        release_report = verify_release_chain(
            release_root / paths["v31_parent"],
            release_root / paths["v32_parent"],
            release_root / paths["v33_parent"],
            release_root / paths["v33_freeze"],
            release_root / paths["v34_artifact"],
        )
    except Exception as exc:
        release_report = {"valid": False, "checks": {}, "errors": [str(exc)]}
    try:
        spec = load_v34_spec()
    except Exception as exc:
        spec = {}
        errors.append(str(exc))
    boundary = payload.get("claim_boundary") or {}
    decisions = payload.get("scientific_decisions") or {}
    expected_superseded = (
        (spec.get("lineage_change_control") or {}).get(
            "v33_frozen_files_superseded_after_v34_artifact", []
        )
    )
    checks = {
        "freeze_self_hash": payload.get("freeze_contract_sha256")
        == computed_self_hash,
        "all_v34_frozen_files_present_and_exact": bool(file_results)
        and all(row["valid"] for row in file_results.values()),
        "release_chain_18_of_18": bool(
            release_report.get("valid")
            and len(release_report.get("checks") or {}) == 18
            and all((release_report.get("checks") or {}).values())
        ),
        "successor_policy_exact": payload.get("lineage", {}).get(
            "v33_superseded_files"
        )
        == expected_superseded,
        "hardware_boundary_false": bool(
            boundary.get("hardware_executable") is False
            and boundary.get("qpu_submission_enabled") is False
            and boundary.get("qpu_jobs_submitted") == 0
            and boundary.get("quantum_advantage") == "NOT_CLAIMED"
        ),
        "negative_results_retained": bool(
            decisions.get("complete_global_connectivity") == "INDETERMINATE"
            and str(decisions.get("ring_topology", "")).startswith("REJECTED")
            and decisions.get("backend_native_lowering") == "NOT_RUN"
        ),
    }
    errors.extend(str(item) for item in release_report.get("errors", []))
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "file_count": len(file_results),
        "file_results": file_results,
        "freeze_contract_sha256_computed": computed_self_hash,
        "freeze_contract_sha256_stored": payload.get("freeze_contract_sha256"),
        "release_checks": release_report.get("checks"),
        "valid": bool(all(checks.values()) and not errors),
        "verifier_version": VERIFY_VERSION,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the V3.4 freeze contract.")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument(
        "--contract", type=Path, default=Path("FREEZE_CONTRACT_V3_4.json")
    )
    args = parser.parse_args(argv)
    report = verify_freeze_contract(args.root, args.contract)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["VERIFY_VERSION", "verify_freeze_contract"]
