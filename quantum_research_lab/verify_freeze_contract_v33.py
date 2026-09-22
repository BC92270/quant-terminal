"""Verify the V3.3 release freeze, every listed byte digest and release lineage."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .verify_phase3_v33 import verify_release_chain


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_freeze_contract(
    root: str | Path,
    contract_path: str | Path,
) -> dict[str, Any]:
    release_root = Path(root).resolve()
    freeze_path = Path(contract_path).resolve()
    errors: list[str] = []
    try:
        payload = json.loads(freeze_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "checks": {"freeze_readable": False},
            "errors": [str(exc)],
            "failed_checks": ["freeze_readable"],
            "valid": False,
        }

    core = {
        key: value
        for key, value in payload.items()
        if key != "freeze_contract_sha256"
    }
    computed_self_hash = _canonical_sha256(core)
    file_results: dict[str, dict[str, Any]] = {}
    for relative, expected in sorted((payload.get("frozen_files") or {}).items()):
        target = release_root / relative
        try:
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            exists = True
        except OSError as exc:
            actual = None
            exists = False
            errors.append(f"{relative}: {exc}")
        file_results[relative] = {
            "actual_sha256": actual,
            "exists": exists,
            "expected_sha256": expected,
            "valid": bool(exists and actual == expected),
        }

    release_report = verify_release_chain(
        release_root / "SEALED_EXACT_DYADIC_BANDS_ORACLE.json",
        release_root
        / "outputs/quantum_phase3/gate_compiler/SEALED_GATE_COMPILER_ARTIFACT.json",
        release_root
        / "outputs/quantum_phase3/algorithmic_contract/SEALED_FEASIBLE_SUBSPACE_MIXER_ARTIFACT.json",
    )
    boundary = payload.get("claim_boundary") or {}
    checks = {
        "freeze_self_hash": payload.get("freeze_contract_sha256")
        == computed_self_hash,
        "all_frozen_files_present_and_exact": bool(file_results)
        and all(row["valid"] for row in file_results.values()),
        "release_chain_13_of_13": bool(
            release_report.get("valid")
            and len(release_report.get("checks") or {}) == 13
            and all((release_report.get("checks") or {}).values())
        ),
        "hardware_boundary_false": bool(
            boundary.get("hardware_executable") is False
            and boundary.get("qpu_submission_enabled") is False
            and boundary.get("qpu_jobs_submitted") == 0
        ),
        "negative_results_retained": bool(
            payload.get("scientific_decisions", {}).get("complete_global_connectivity")
            == "INDETERMINATE"
            and str(
                payload.get("scientific_decisions", {}).get("ring_topology", "")
            ).startswith("REJECTED")
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "checks": checks,
        "errors": list(dict.fromkeys(errors + release_report.get("errors", []))),
        "failed_checks": failed,
        "file_count": len(file_results),
        "file_results": file_results,
        "freeze_contract_sha256_computed": computed_self_hash,
        "freeze_contract_sha256_stored": payload.get("freeze_contract_sha256"),
        "release_checks": release_report.get("checks"),
        "valid": bool(not failed and not errors and release_report.get("valid")),
        "verifier": "QUANTUM LAB V3.3 FREEZE CONTRACT VERIFIER · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the V3.3 freeze contract.")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("FREEZE_CONTRACT_V3_3.json"),
    )
    args = parser.parse_args(argv)
    report = verify_freeze_contract(args.root, args.contract)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["verify_freeze_contract"]
