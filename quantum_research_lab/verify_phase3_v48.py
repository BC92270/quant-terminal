"""Fail-closed scientific release-chain verifier for Quantum Lab V4.8.

Identity mode authenticates the sealed architecture result and non-execution
boundary. Deep mode runs the independent 96-check validation. Rebuild mode
also regenerates the artifact in a clean process and requires byte equality.
No mode contacts a provider or submits a simulator/backend/QPU job.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence

from .phase3_v48_independent_checker import (
    EXPECTED_MULTI_SNAPSHOT,
    EXPECTED_OVERALL,
    EXPECTED_PRODUCTION,
    EXPECTED_SEEDS,
    EXPECTED_WIDTHS,
)
from .phase3_v48_validation import (
    ARTIFACT_PATH,
    CHECKER_PATH,
    EXPECTED_CHECK_COUNT as EXPECTED_SCIENTIFIC_CHECK_COUNT,
    SOURCE_PATH,
    canonical_json_sha256,
    raw_file_sha256,
    read_json_strict,
    run_v48_validation,
)


EXPECTED_RELEASE_CHECK_COUNT = 20
ARTIFACT_VERSION = "PHASE III · V4.8 SEALED MULTI-SNAPSHOT / ARCHITECTURE ARTIFACT · V1"
EXPECTED_NEXT_GATE = (
    "ACQUIRE_TWO_ADDITIONAL_AUTHENTIC_OFFLINE_SNAPSHOT_EPOCHS_AND_REDUCE_"
    "DIRECT_CX_BELOW_BOTH_HISTORICAL_NECESSARY_THRESHOLDS_BEFORE_ANY_"
    "CURRENT_PROVIDER_DISCOVERY"
)


def _is_sha(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _contained_regular(root: Path, relative: str) -> Path:
    item = Path(relative)
    if not relative or item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts):
        raise ValueError(f"Unsafe release path: {relative!r}")
    release_root = root.resolve(strict=True)
    cursor = release_root
    for part in item.parts:
        cursor = cursor / part
        mode = cursor.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symlinked release path rejected: {relative}")
    if not stat.S_ISREG(cursor.lstat().st_mode):
        raise ValueError(f"Release path is not a regular file: {relative}")
    cursor.resolve(strict=True).relative_to(release_root)
    return cursor


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        return []
    return list(value)


def _self_hash(payload: Mapping[str, Any], field: str) -> bool:
    return bool(
        _is_sha(payload.get(field))
        and payload.get(field)
        == canonical_json_sha256({key: value for key, value in payload.items() if key != field})
    )


def _clean_rebuild(
    root: Path,
    *,
    expected_raw: str,
    expected_semantic: str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="quantum-v48-release-replay.") as temporary:
        output = Path(temporary) / "replay.json"
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(root),
            "PYTHONHASHSEED": "0",
            "LC_ALL": "C",
        }
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "quantum_research_lab.phase3_v48_multi_snapshot_architecture_optimizer",
                    "--root",
                    str(root),
                    "--output",
                    str(output),
                ],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=21_600,
                check=False,
            )
        except Exception as exc:
            return {"errors": [str(exc)], "performed": True, "valid": False}
        if completed.returncode != 0 or not output.is_file():
            return {
                "errors": [completed.stderr or completed.stdout or "V4.8 rebuild failed."],
                "performed": True,
                "returncode": completed.returncode,
                "valid": False,
            }
        payload = read_json_strict(output)
        sealed = _contained_regular(root, ARTIFACT_PATH)
        replay_raw = raw_file_sha256(output)
        replay_semantic = payload.get("artifact_sha256")
        byte_exact = output.read_bytes() == sealed.read_bytes()
        valid = bool(
            replay_raw == expected_raw
            and replay_semantic == expected_semantic
            and _self_hash(payload, "artifact_sha256")
            and byte_exact
        )
        return {
            "artifact_raw_file_sha256": replay_raw,
            "artifact_sha256": replay_semantic,
            "byte_for_byte_equal": byte_exact,
            "errors": [] if valid else ["Clean-process V4.8 replay identity mismatch."],
            "performed": True,
            "returncode": completed.returncode,
            "valid": valid,
        }


def verify_release_chain(
    root: str | Path,
    *,
    deep: bool = False,
    rebuild: bool = False,
    expected_artifact_raw_sha256: str | None = None,
    expected_artifact_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify V4.8 without trusting a mutable freeze-file assertion."""

    if rebuild and not deep:
        raise ValueError("Deterministic rebuild requires deep validation.")
    release_root = Path(root).resolve(strict=True)
    raw_pin = expected_artifact_raw_sha256
    semantic_pin = expected_artifact_sha256
    pins_present = _is_sha(raw_pin) and _is_sha(semantic_pin)
    errors: list[str] = []
    try:
        artifact_path = _contained_regular(release_root, ARTIFACT_PATH)
        source_path = _contained_regular(release_root, SOURCE_PATH)
        checker_path = _contained_regular(release_root, CHECKER_PATH)
        artifact = read_json_strict(artifact_path)
    except Exception as exc:
        artifact_path = release_root / ARTIFACT_PATH
        source_path = release_root / SOURCE_PATH
        checker_path = release_root / CHECKER_PATH
        artifact = {}
        errors.append(f"V4.8 release inputs unavailable: {exc}")

    boundary = _mapping(artifact.get("claim_boundary"))
    decisions = _mapping(artifact.get("decisions"))
    aggregate = _mapping(artifact.get("aggregate"))
    rows = _rows(artifact.get("seed_evaluations"))
    zero_fields = (
        "credential_reads",
        "provider_calls",
        "network_calls",
        "backend_run_calls",
        "local_simulator_jobs_submitted",
        "qpu_jobs_submitted",
    )
    artifact_raw = raw_file_sha256(artifact_path) if artifact_path.is_file() else None
    if deep:
        try:
            scientific = run_v48_validation(
                root=release_root,
                expected_artifact_raw_sha256=str(raw_pin),
                expected_artifact_sha256=str(semantic_pin),
            )
        except Exception as exc:
            scientific = {
                "counts": {"checks_passed": 0, "checks_total": EXPECTED_SCIENTIFIC_CHECK_COUNT},
                "errors": [str(exc)],
                "failed_checks": ["exception"],
                "passed": False,
            }
            errors.append(f"V4.8 deep validation failed: {exc}")
    else:
        scientific = {
            "counts": {"checks_passed": 0, "checks_total": EXPECTED_SCIENTIFIC_CHECK_COUNT},
            "errors": [],
            "failed_checks": [],
            "passed": None,
        }
    rebuild_report = (
        _clean_rebuild(
            release_root,
            expected_raw=str(raw_pin),
            expected_semantic=str(semantic_pin),
        )
        if rebuild and pins_present
        else {
            "errors": ["Artifact pins unavailable for rebuild."] if rebuild else [],
            "performed": rebuild,
            "valid": not rebuild,
        }
    )
    errors.extend(str(item) for item in scientific.get("errors") or [])
    errors.extend(str(item) for item in rebuild_report.get("errors") or [])

    checks: dict[str, bool] = {
        "artifact_identity_pins_present": pins_present,
        "artifact_raw_identity": bool(pins_present and artifact_raw == raw_pin),
        "artifact_semantic_identity": bool(pins_present and artifact.get("artifact_sha256") == semantic_pin),
        "artifact_self_hash": _self_hash(artifact, "artifact_sha256"),
        "artifact_version_exact": artifact.get("artifact_version") == ARTIFACT_VERSION,
        "source_crosslink_exact": bool(source_path.is_file() and artifact.get("source_raw_file_sha256") == raw_file_sha256(source_path)),
        "checker_crosslink_exact": bool(checker_path.is_file() and artifact.get("independent_checker_raw_file_sha256") == raw_file_sha256(checker_path)),
        "research_classification_exact": artifact.get("research_classification") == boundary.get("research_classification") == "RESEARCH_ONLY",
        "provider_network_and_jobs_zero": all(boundary.get(field) == 0 for field in zero_fields),
        "provider_sdk_and_credentials_not_used": boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False,
        "hardware_and_current_snapshot_rejected": boundary.get("hardware_executable") is False and boundary.get("snapshot_is_current_hardware_evidence") is False,
        "production_admission_rejected": decisions.get("production_admission") == EXPECTED_PRODUCTION,
        "next_gate_exact": decisions.get("next_falsifiable_gate") == EXPECTED_NEXT_GATE and decisions.get("overall") == EXPECTED_OVERALL,
        "seed_order_exact": [row.get("seed") for row in rows] == list(EXPECTED_SEEDS),
        "widths_exact": [row.get("logical_qubits") for row in rows] == list(EXPECTED_WIDTHS),
        "all_architecture_reductions_exact": len(rows) == 8 and aggregate.get("all_eight_candidate_streams_materialized") is True and aggregate.get("all_eight_basic_swap_routes_materialized") is True and aggregate.get("all_eight_logical_cx_reduced") is True and all((_mapping(row.get("comparison"))).get("strict_logical_cx_reduction") is True and (_mapping(row.get("comparison"))).get("strict_routed_cz_reduction") is True for row in rows),
        "multi_snapshot_not_evaluable_exact": decisions.get("multi_snapshot_robustness") == EXPECTED_MULTI_SNAPSHOT and aggregate.get("multi_snapshot_robustness_evaluable") is False and aggregate.get("multi_snapshot_distinct_authentic_snapshot_count") == 1,
        "deep_scientific_validation": scientific.get("passed") is True if deep else True,
        "deep_scientific_check_count": (_mapping(scientific.get("counts")).get("checks_passed") == EXPECTED_SCIENTIFIC_CHECK_COUNT and _mapping(scientific.get("counts")).get("checks_total") == EXPECTED_SCIENTIFIC_CHECK_COUNT) if deep else True,
        "optional_clean_rebuild_byte_exact": rebuild_report.get("valid") is True,
    }
    if len(checks) != EXPECTED_RELEASE_CHECK_COUNT:
        raise AssertionError(
            f"V4.8 release verification check count drifted: {len(checks)} != {EXPECTED_RELEASE_CHECK_COUNT}"
        )
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "artifact_raw_file_sha256": artifact_raw,
        "artifact_sha256": artifact.get("artifact_sha256"),
        "checks": checks,
        "counts": {
            "checks_passed": sum(passed is True for passed in checks.values()),
            "checks_total": len(checks),
        },
        "deep": deep,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "passed": not failed and not errors,
        "rebuild": rebuild_report,
        "verifier": "QUANTUM LAB V4.8 SCIENTIFIC RELEASE-CHAIN VERIFIER · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root_positional", nargs="?", type=Path)
    parser.add_argument("--root", dest="root_option", type=Path)
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--expected-artifact-raw-sha256")
    parser.add_argument("--expected-artifact-sha256")
    args = parser.parse_args(argv)
    if args.root_positional is not None and args.root_option is not None:
        parser.error("Pass root positionally or with --root, not both.")
    root = args.root_option or args.root_positional or Path(__file__).resolve().parents[1]
    try:
        report = verify_release_chain(
            root,
            deep=args.deep,
            rebuild=args.rebuild,
            expected_artifact_raw_sha256=args.expected_artifact_raw_sha256,
            expected_artifact_sha256=args.expected_artifact_sha256,
        )
    except Exception as exc:
        report = {
            "counts": {"checks_passed": 0, "checks_total": EXPECTED_RELEASE_CHECK_COUNT},
            "errors": [str(exc)],
            "failed_checks": ["unhandled_exception"],
            "passed": False,
            "verifier": "QUANTUM LAB V4.8 SCIENTIFIC RELEASE-CHAIN VERIFIER · V1",
        }
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["EXPECTED_RELEASE_CHECK_COUNT", "verify_release_chain"]
