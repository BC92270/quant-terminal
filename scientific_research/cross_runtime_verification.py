from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import asdict, fields, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase65_models import CrossRuntimeVerificationRecord
from .replication_engine import (
    INDEPENDENT_REPLICATION_PROTOCOL_VERSION,
    REPLICATION_EVENT_TIME_SUPPORT_POLICY,
    load_persisted_alfred_snapshot_bundle,
)


CROSS_RUNTIME_PROTOCOL_VERSION = "SRB_CROSS_RUNTIME_VERIFICATION_V1"
CROSS_RUNTIME_ENGINE_PROTOCOL = "SRB_TYPESCRIPT_REPLICATION_ENGINE_V1"
CROSS_RUNTIME_TOLERANCE = 1e-6
ENGINE_SOURCE_FILES = (
    "src/replication/cross-runtime-engine.ts",
    "bin/cross-runtime-verify.mjs",
)


class CrossRuntimeVerificationError(RuntimeError):
    """Raised when a frozen cross-runtime challenge cannot be trusted or executed."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=lambda item: str(item))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _digest(value: Any) -> str:
    encoded = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _file_digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _replication_row(value: Any) -> dict[str, Any]:
    return asdict(value) if is_dataclass(value) else dict(value)


def _verification_record(value: Any) -> CrossRuntimeVerificationRecord:
    if isinstance(value, CrossRuntimeVerificationRecord):
        return value
    row = dict(value)
    allowed = {field.name for field in fields(CrossRuntimeVerificationRecord)}
    return CrossRuntimeVerificationRecord(**{key: row[key] for key in allowed if key in row})


def _package_root(package_root: str | os.PathLike[str] | None = None) -> Path:
    root = Path(package_root or Path(__file__).resolve().parent).resolve()
    if not (root / "src" / "replication" / "cross-runtime-engine.ts").is_file():
        raise CrossRuntimeVerificationError(f"Cross-runtime package root is incomplete: {root}")
    return root


def _engine_inventory(root: Path) -> tuple[list[dict[str, str]], str]:
    rows = []
    for relative in ENGINE_SOURCE_FILES:
        path = (root / relative).resolve()
        if path.parent != root and root not in path.parents:
            raise CrossRuntimeVerificationError("Engine source path escaped the package root.")
        if not path.is_file():
            raise CrossRuntimeVerificationError(f"Cross-runtime engine source is missing: {relative}")
        rows.append({"relative_path": relative, "sha256": _file_digest(path)})
    return rows, _digest(rows)


def _required_series(replication: Mapping[str, Any]) -> tuple[str, ...]:
    matrix = replication.get("series_matrix") or {}
    markets = replication.get("markets") or ()
    return tuple(dict.fromkeys(
        str((matrix.get(market) or {}).get(key) or "").strip()
        for market in markets
        for key in ("real_series_id", "nominal_series_id")
        if str((matrix.get(market) or {}).get(key) or "").strip()
    ))


def freeze_cross_runtime_verification(
    replication: Any,
    *,
    data_root: str | os.PathLike[str],
    package_root: str | os.PathLike[str] | None = None,
) -> CrossRuntimeVerificationRecord:
    row = _replication_row(replication)
    if str(row.get("protocol_version") or "") != INDEPENDENT_REPLICATION_PROTOCOL_VERSION:
        raise CrossRuntimeVerificationError("A governed independent-replication record is required.")
    if str(row.get("execution_status") or "") != "COMPLETE" or str(row.get("status") or "") != "COMPLETE":
        raise CrossRuntimeVerificationError("Cross-runtime verification requires a completed source replication.")
    if str(row.get("event_time_support_policy") or "") != REPLICATION_EVENT_TIME_SUPPORT_POLICY:
        raise CrossRuntimeVerificationError("Source replication lacks the current causal event-time policy.")
    if str(row.get("point_in_time_status") or "") != "PASS" or str(row.get("independence_gate_status") or "") != "PASS":
        raise CrossRuntimeVerificationError("Source replication has not passed its point-in-time and independence gates.")
    if row.get("automatic_promotion_authorized") is not False or str(row.get("production_status") or "") != "RESEARCH_ONLY":
        raise CrossRuntimeVerificationError("Source replication lost its research-only promotion lock.")
    for key in ("replication_id", "protocol_fingerprint", "snapshot_id", "source_snapshot_fingerprint", "execution_fingerprint"):
        if not str(row.get(key) or ""):
            raise CrossRuntimeVerificationError(f"Source replication is missing {key}.")

    root = Path(data_root).resolve()
    package = _package_root(package_root)
    required = _required_series(row)
    snapshots = load_persisted_alfred_snapshot_bundle(
        root,
        str(row["snapshot_id"]),
        expected_fingerprint=str(row["source_snapshot_fingerprint"]),
        required_series=required,
    )
    snapshot_dir = root / "public_data" / "alfred_initial_release" / str(row["snapshot_id"])
    canonical_files: dict[str, dict[str, Any]] = {}
    for series_id in required:
        path = (snapshot_dir / f"{series_id}_canonical.csv").resolve()
        if root not in path.parents or not path.is_file():
            raise CrossRuntimeVerificationError(f"Canonical snapshot file is missing: {series_id}")
        canonical_files[series_id] = {
            "relative_path": str(path.relative_to(root)),
            "sha256": _file_digest(path),
            "row_count": len(snapshots[series_id].rows),
        }
    snapshot_manifest = (snapshot_dir / "manifest.json").resolve()
    if not snapshot_manifest.is_file():
        raise CrossRuntimeVerificationError("Sealed ALFRED snapshot manifest is missing.")
    engine_files, engine_source_fingerprint = _engine_inventory(package)
    payload = {
        "schema_version": CROSS_RUNTIME_PROTOCOL_VERSION,
        "replication_id": str(row["replication_id"]),
        "protocol_fingerprint": str(row["protocol_fingerprint"]),
        "snapshot_id": str(row["snapshot_id"]),
        "snapshot_fingerprint": str(row["source_snapshot_fingerprint"]),
        "snapshot_manifest_sha256": _file_digest(snapshot_manifest),
        "event_time_support_policy": str(row["event_time_support_policy"]),
        "markets": list(row.get("markets") or ()),
        "measurement_variants": [dict(item) for item in (row.get("measurement_variants") or ())],
        "series_matrix": dict(row.get("series_matrix") or {}),
        "train_fraction": float(row.get("train_fraction") or 0.0),
        "forecast_horizon": int(row.get("forecast_horizon") or 0),
        "min_common_rows": int(row.get("min_common_rows") or 0),
        "multiplicity_policy": str(row.get("multiplicity_policy") or ""),
        "canonical_files": canonical_files,
        "engine_files": engine_files,
        "engine_source_fingerprint": engine_source_fingerprint,
        "implementation_independence_claim": "SEPARATE_TYPESCRIPT_NODE_CODEPATH",
        "investigator_independent": False,
        "automatic_promotion_authorized": False,
        "production_status": "RESEARCH_ONLY",
    }
    challenge_fingerprint = _digest(payload)
    verification_id = f"XRV-{challenge_fingerprint.split(':', 1)[1][:16]}"
    base = root / "cross_runtime" / verification_id
    manifest_path = base / "challenge.json"
    if base.exists():
        if not manifest_path.is_file():
            raise CrossRuntimeVerificationError(f"Existing cross-runtime challenge is incomplete: {verification_id}")
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing_payload = {key: value for key, value in existing.items() if key not in {"challenge_id", "challenge_fingerprint", "created_at"}}
        if _digest(existing_payload) != challenge_fingerprint or str(existing.get("challenge_id") or "") != verification_id:
            raise CrossRuntimeVerificationError(f"Cross-runtime challenge identity collision: {verification_id}")
        created_at = str(existing.get("created_at") or "")
    else:
        base.parent.mkdir(parents=True, exist_ok=True)
        created_at = _now_iso()
        manifest = {
            "challenge_id": verification_id,
            "challenge_fingerprint": challenge_fingerprint,
            "created_at": created_at,
            **payload,
        }
        temporary = Path(tempfile.mkdtemp(prefix=f".{verification_id}-", dir=str(base.parent)))
        try:
            target = temporary / "challenge.json"
            with target.open("x", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, base)
            temporary = None
            try:
                descriptor = os.open(base.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            except OSError:
                pass
        finally:
            if temporary is not None and temporary.exists():
                shutil.rmtree(temporary)
    return CrossRuntimeVerificationRecord(
        verification_id=verification_id,
        created_at=created_at,
        replication_id=str(row["replication_id"]),
        challenge_fingerprint=challenge_fingerprint,
        challenge_manifest_path=str(manifest_path.relative_to(root)),
        source_snapshot_id=str(row["snapshot_id"]),
        source_snapshot_fingerprint=str(row["source_snapshot_fingerprint"]),
        reference_execution_fingerprint=str(row["execution_fingerprint"]),
        engine_source_fingerprint=engine_source_fingerprint,
        lifecycle_history=({
            "at": created_at,
            "from": "",
            "to": "FROZEN",
            "actor": "SYSTEM_ON_EXPLICIT_USER_ACTION",
            "reason": "Cross-runtime challenge frozen before TypeScript execution.",
            "evidence_refs": [str(row["replication_id"]), str(row["snapshot_id"])],
        },),
    )


def _compare_value(expected: Any, actual: Any, path: str, discrepancies: list[str], tolerance: float) -> None:
    if isinstance(expected, bool) or isinstance(actual, bool):
        if expected is not actual:
            discrepancies.append(f"{path}: expected {expected!r}, got {actual!r}")
        return
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if not math.isfinite(float(expected)) or not math.isfinite(float(actual)):
            if float(expected) != float(actual):
                discrepancies.append(f"{path}: non-finite values differ")
            return
        allowed = tolerance * max(1.0, abs(float(expected)))
        if abs(float(expected) - float(actual)) > allowed:
            discrepancies.append(f"{path}: expected {expected!r}, got {actual!r}, tolerance {allowed:.3g}")
        return
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        for key in expected:
            if key not in actual:
                discrepancies.append(f"{path}.{key}: missing")
            else:
                _compare_value(expected[key], actual[key], f"{path}.{key}", discrepancies, tolerance)
        for key in actual:
            if key not in expected:
                discrepancies.append(f"{path}.{key}: unexpected")
        return
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        if len(expected) != len(actual):
            discrepancies.append(f"{path}: length {len(expected)} != {len(actual)}")
            return
        for index, (left, right) in enumerate(zip(expected, actual)):
            _compare_value(left, right, f"{path}[{index}]", discrepancies, tolerance)
        return
    if expected != actual:
        discrepancies.append(f"{path}: expected {expected!r}, got {actual!r}")


def compare_cross_runtime_results(
    replication: Any,
    output: Mapping[str, Any],
    *,
    tolerance: float = CROSS_RUNTIME_TOLERANCE,
) -> dict[str, Any]:
    reference = _replication_row(replication)
    discrepancies: list[str] = []
    exact_root = (
        "replication_id", "snapshot_id", "snapshot_fingerprint", "replication_outcome",
        "result_count", "promising_result_count", "no_improvement_result_count",
        "production_status", "automatic_promotion_authorized",
    )
    expected_root = {
        "replication_id": reference.get("replication_id"),
        "snapshot_id": reference.get("snapshot_id"),
        "snapshot_fingerprint": reference.get("source_snapshot_fingerprint"),
        "replication_outcome": reference.get("replication_outcome"),
        "result_count": reference.get("result_count"),
        "promising_result_count": reference.get("promising_result_count"),
        "no_improvement_result_count": reference.get("no_improvement_result_count"),
        "production_status": "RESEARCH_ONLY",
        "automatic_promotion_authorized": False,
    }
    for key in exact_root:
        _compare_value(expected_root[key], output.get(key), f"output.{key}", discrepancies, tolerance)
    if str(output.get("engine_protocol_version") or "") != CROSS_RUNTIME_ENGINE_PROTOCOL:
        discrepancies.append("output.engine_protocol_version: unsupported engine protocol")
    if str(output.get("implementation_separation") or "") != "SEPARATE_TYPESCRIPT_NODE_CODEPATH":
        discrepancies.append("output.implementation_separation: independent code path not declared")
    if output.get("investigator_independent") is not False:
        discrepancies.append("output.investigator_independent: must remain false")

    fields_to_compare = (
        "market", "market_label", "variant_id", "variant_label", "formula", "real_series_id", "nominal_series_id",
        "event_time_support_policy", "raw_common_row_count", "co_release_excluded_count",
        "non_advancing_backfill_excluded_count", "excluded_support_rows", "row_count", "verdict", "train_size",
        "test_size", "split_timestamp", "candidate_metrics", "baseline_metrics", "deltas_vs_baseline",
        "fitted_parameters", "forecast_origin_timestamps", "forecast_timestamps", "actual_values",
        "candidate_predictions", "candidate_errors", "baseline_predictions", "baseline_errors", "forecast_comparison",
        "production_status",
    )
    expected_results = {
        (str(item.get("market") or ""), str(item.get("variant_id") or "")): dict(item)
        for item in (reference.get("results") or ())
    }
    actual_results = {
        (str(item.get("market") or ""), str(item.get("variant_id") or "")): dict(item)
        for item in (output.get("results") or ())
        if isinstance(item, Mapping)
    }
    missing = sorted(set(expected_results) - set(actual_results))
    extra = sorted(set(actual_results) - set(expected_results))
    if missing:
        discrepancies.append(f"results: missing keys {missing}")
    if extra:
        discrepancies.append(f"results: unexpected keys {extra}")
    matched = 0
    for key in sorted(set(expected_results).intersection(actual_results)):
        before = len(discrepancies)
        expected = expected_results[key]
        actual = actual_results[key]
        for field_name in fields_to_compare:
            _compare_value(expected.get(field_name), actual.get(field_name), f"results[{key!r}].{field_name}", discrepancies, tolerance)
        if len(discrepancies) == before:
            matched += 1
    return {
        "parity_status": "PASS" if not discrepancies else "FAIL",
        "matched_result_count": matched,
        "result_count": len(expected_results),
        "discrepancy_count": len(discrepancies),
        "discrepancies": tuple(discrepancies[:250]),
        "numerical_tolerance": float(tolerance),
    }


def cross_runtime_runtime_status(
    package_root: str | os.PathLike[str] | None = None,
    *,
    node_executable: str | None = None,
) -> dict[str, Any]:
    package = _package_root(package_root)
    node = node_executable or shutil.which("node")
    build = package / "dist" / "replication" / "cross-runtime-engine.js"
    cli = package / "bin" / "cross-runtime-verify.mjs"
    return {
        "ready": bool(node and build.is_file() and cli.is_file()),
        "node_executable": str(node or ""),
        "build_path": str(build),
        "build_exists": build.is_file(),
        "cli_exists": cli.is_file(),
    }


def execute_cross_runtime_verification(
    frozen: Any,
    replication: Any,
    *,
    data_root: str | os.PathLike[str],
    package_root: str | os.PathLike[str] | None = None,
    node_executable: str | None = None,
    timeout_seconds: float = 120.0,
) -> CrossRuntimeVerificationRecord:
    record = _verification_record(frozen)
    source = _replication_row(replication)
    if record.status != "FROZEN" or record.execution_status != "NOT_RUN":
        raise CrossRuntimeVerificationError("Only a persisted, unexecuted FROZEN cross-runtime challenge may run.")
    if record.protocol_version != CROSS_RUNTIME_PROTOCOL_VERSION:
        raise CrossRuntimeVerificationError("Unsupported cross-runtime verification protocol.")
    if record.replication_id != str(source.get("replication_id") or ""):
        raise CrossRuntimeVerificationError("Frozen challenge is not tied to the supplied replication.")
    if record.reference_execution_fingerprint != str(source.get("execution_fingerprint") or ""):
        raise CrossRuntimeVerificationError("Source replication execution fingerprint changed after challenge freeze.")
    if record.automatic_promotion_authorized or record.production_status != "RESEARCH_ONLY":
        raise CrossRuntimeVerificationError("Frozen cross-runtime promotion lock is not intact.")

    root = Path(data_root).resolve()
    package = _package_root(package_root)
    manifest_path = (root / record.challenge_manifest_path).resolve()
    if root not in manifest_path.parents or not manifest_path.is_file():
        raise CrossRuntimeVerificationError("Frozen cross-runtime challenge manifest is missing or unsafe.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = {key: value for key, value in manifest.items() if key not in {"challenge_id", "challenge_fingerprint", "created_at"}}
    if _digest(payload) != record.challenge_fingerprint or str(manifest.get("challenge_id") or "") != record.verification_id:
        raise CrossRuntimeVerificationError("Frozen cross-runtime challenge fingerprint mismatch.")
    _, current_source_fingerprint = _engine_inventory(package)
    if current_source_fingerprint != record.engine_source_fingerprint:
        raise CrossRuntimeVerificationError("TypeScript engine source changed after challenge freeze.")
    runtime = cross_runtime_runtime_status(package, node_executable=node_executable)
    if not runtime["ready"]:
        raise CrossRuntimeVerificationError("TypeScript verifier is not built or Node.js is unavailable; run the pinned pnpm build first.")
    build_path = Path(str(runtime["build_path"]))
    cli_path = package / "bin" / "cross-runtime-verify.mjs"
    build_fingerprint = _digest([
        {"relative_path": "dist/replication/cross-runtime-engine.js", "sha256": _file_digest(build_path)},
        {"relative_path": "bin/cross-runtime-verify.mjs", "sha256": _file_digest(cli_path)},
    ])
    challenge_dir = manifest_path.parent
    pending = challenge_dir / f".typescript-result-{uuid.uuid4().hex}.json"
    final_output = challenge_dir / "typescript-result.json"
    try:
        completed = subprocess.run(
            [str(runtime["node_executable"]), str(cli_path), str(manifest_path), str(root), str(package), str(pending)],
            cwd=str(package),
            capture_output=True,
            text=True,
            timeout=max(5.0, float(timeout_seconds)),
            check=False,
            env={**os.environ, "NODE_NO_WARNINGS": "1"},
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "Node process failed without output.").strip()[:1200]
            raise CrossRuntimeVerificationError(f"TypeScript verifier failed closed: {detail}")
        if not pending.is_file() or pending.stat().st_size > 25_000_000:
            raise CrossRuntimeVerificationError("TypeScript verifier did not produce a bounded result artifact.")
        output_bytes = pending.read_bytes()
        output = json.loads(output_bytes.decode("utf-8"))
        if not isinstance(output, Mapping):
            raise CrossRuntimeVerificationError("TypeScript verifier output must be a JSON object.")
        if str(output.get("challenge_id") or "") != record.verification_id:
            raise CrossRuntimeVerificationError("TypeScript verifier output references the wrong challenge.")
        if str(output.get("challenge_fingerprint") or "") != record.challenge_fingerprint:
            raise CrossRuntimeVerificationError("TypeScript verifier output challenge fingerprint mismatch.")
        if str(output.get("engine_source_fingerprint") or "") != record.engine_source_fingerprint:
            raise CrossRuntimeVerificationError("TypeScript verifier output engine fingerprint mismatch.")
        comparison = compare_cross_runtime_results(source, output, tolerance=record.numerical_tolerance)
        if final_output.exists():
            if final_output.read_bytes() != output_bytes:
                raise CrossRuntimeVerificationError("Cross-runtime result identity collision; prior artifact retained.")
            pending.unlink()
        else:
            os.replace(pending, final_output)
            try:
                descriptor = os.open(challenge_dir, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            except OSError:
                pass
        result_fingerprint = f"sha256:{hashlib.sha256(output_bytes).hexdigest()}"
        finished = _now_iso()
        lifecycle = tuple(record.lifecycle_history) + ({
            "at": finished,
            "from": "FROZEN",
            "to": "COMPLETE",
            "actor": "SYSTEM_ON_EXPLICIT_USER_ACTION",
            "reason": f"Independent TypeScript parity execution completed with {comparison['parity_status']}.",
            "evidence_refs": [record.replication_id, record.source_snapshot_id, result_fingerprint],
        },)
        return replace(
            record,
            status="COMPLETE",
            execution_status="COMPLETE",
            implementation_gate_status="PASS" if comparison["parity_status"] == "PASS" else "FAIL",
            parity_status=str(comparison["parity_status"]),
            numerical_tolerance=float(comparison["numerical_tolerance"]),
            engine_build_fingerprint=build_fingerprint,
            runtime_version=str(output.get("node_version") or ""),
            runtime_platform=str(output.get("runtime_platform") or ""),
            result_path=str(final_output.relative_to(root)),
            result_fingerprint=result_fingerprint,
            result_count=int(comparison["result_count"]),
            matched_result_count=int(comparison["matched_result_count"]),
            discrepancy_count=int(comparison["discrepancy_count"]),
            discrepancies=tuple(comparison["discrepancies"]),
            lifecycle_history=lifecycle,
        )
    finally:
        if pending.exists():
            pending.unlink()


__all__ = [
    "CROSS_RUNTIME_ENGINE_PROTOCOL",
    "CROSS_RUNTIME_PROTOCOL_VERSION",
    "CROSS_RUNTIME_TOLERANCE",
    "CrossRuntimeVerificationError",
    "CrossRuntimeVerificationRecord",
    "compare_cross_runtime_results",
    "cross_runtime_runtime_status",
    "execute_cross_runtime_verification",
    "freeze_cross_runtime_verification",
]
