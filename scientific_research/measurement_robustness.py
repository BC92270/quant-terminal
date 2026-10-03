from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .experiment_factory import run_historical_oos_experiment
from .phase63_models import (
    MeasurementRobustnessProtocol,
    MeasurementRobustnessReport,
    MeasurementVariantResult,
    MeasurementVariantSpec,
)
from .public_data_pipeline import (
    ECB_RTD_DATASET_ID,
    ECB_RTD_NOMINAL_SERIES_KEY,
    ECB_RTD_REAL_SERIES_KEY,
)


UTC = timezone.utc
MEASUREMENT_ROBUSTNESS_POLICY_VERSION = "SRB_ECB_MEASUREMENT_ROBUSTNESS_V1"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _row(value: Any) -> dict[str, Any]:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError("Expected a dataclass or mapping.")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_digest(parts)[:16]}"


def measurement_robustness_executor_digest() -> str:
    """Bind both the comparative transforms and the shared OOS executor source."""

    component_paths = (
        Path(__file__).resolve(),
        Path(__file__).resolve().with_name("experiment_factory.py"),
    )
    digest = hashlib.sha256()
    for path in component_paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _parse_timestamp(value: Any, field: str) -> datetime:
    raw = str(value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include an explicit UTC offset.")
    return parsed.astimezone(UTC)


def _positive(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric.") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} must remain finite and strictly positive.")
    return number


def ecb_measurement_variant_specs() -> tuple[MeasurementVariantSpec, ...]:
    """Return the complete predeclared ECB measurement set.

    The variants are economically different level/wedge measurements. They are not
    sign flips, lag retuning or parameter searches, and all use the same release-event
    support. Changing this allow-list requires a new policy version.
    """

    return (
        MeasurementVariantSpec(
            variant_id="MEASURE-ECB-REAL-LOG-LEVEL",
            label="Real EER · log level",
            formula="log(real_eer_t)",
            economic_interpretation="CPI-deflated broad effective exchange-rate level.",
            source_fields=("price",),
            transform="LOG_REAL_EER_LEVEL",
        ),
        MeasurementVariantSpec(
            variant_id="MEASURE-ECB-NOMINAL-LOG-LEVEL",
            label="Nominal EER · log level",
            formula="log(nominal_eer_t)",
            economic_interpretation="Nominal broad effective exchange-rate level.",
            source_fields=("fundamental_anchor",),
            transform="LOG_NOMINAL_EER_LEVEL",
        ),
        MeasurementVariantSpec(
            variant_id="MEASURE-ECB-REAL-NOMINAL-LOG-WEDGE",
            label="Real − nominal EER · log wedge",
            formula="log(real_eer_t) - log(nominal_eer_t)",
            economic_interpretation="Relative price/competitiveness wedge between real and nominal broad EER indices.",
            source_fields=("price", "fundamental_anchor"),
            transform="LOG_REAL_MINUS_LOG_NOMINAL",
            warnings=(
                "The wedge is an analytical index transformation, not a tradable spread.",
            ),
        ),
    )


def snapshot_rows_fingerprint(rows: Sequence[Mapping[str, Any]]) -> str:
    """Fingerprint every persisted contract-row field in its declared order."""

    normalized: list[dict[str, Any]] = []
    for index, source in enumerate(rows):
        if not isinstance(source, Mapping):
            raise ValueError(f"Snapshot row {index} is not an object.")
        normalized.append({str(key): source[key] for key in sorted(source)})
    if not normalized:
        raise ValueError("A measurement-robustness protocol cannot bind an empty snapshot.")
    return _digest(normalized)


def _validate_ecb_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[tuple[str, ...], tuple[float, ...], tuple[float, ...]]:
    if len(rows) < 40:
        raise ValueError("ECB measurement robustness requires at least 40 causal release events.")
    labels: list[str] = []
    periods: list[str] = []
    real_values: list[float] = []
    nominal_values: list[float] = []
    for index, row in enumerate(rows):
        event_raw = str(row.get("timestamp") or "").strip()
        event = _parse_timestamp(event_raw, f"row {index} timestamp")
        reference_period = str(row.get("reference_period") or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}", reference_period):
            raise ValueError(f"row {index} reference_period must use YYYY-MM.")
        for field in (
            "fundamental_release_timestamp",
            "vintage_timestamp",
            "price_valid_from",
            "anchor_valid_from",
        ):
            available = _parse_timestamp(row.get(field), f"row {index} {field}")
            if available > event:
                raise ValueError(f"row {index} {field} uses information unavailable at the event timestamp.")
        price_available = _parse_timestamp(row.get("price_valid_from"), f"row {index} price_valid_from")
        anchor_available = _parse_timestamp(row.get("anchor_valid_from"), f"row {index} anchor_valid_from")
        if max(price_available, anchor_available) != event:
            raise ValueError(f"row {index} timestamp is not the exact joint release-event time.")
        if str(row.get("price_series_id") or "") != ECB_RTD_REAL_SERIES_KEY:
            raise ValueError(f"row {index} does not use the frozen ECB real EER series.")
        if str(row.get("anchor_series_id") or "") != ECB_RTD_NOMINAL_SERIES_KEY:
            raise ValueError(f"row {index} does not use the frozen ECB nominal EER series.")
        labels.append(event_raw)
        periods.append(reference_period)
        real_values.append(_positive(row.get("price"), f"row {index} price"))
        nominal_values.append(_positive(row.get("fundamental_anchor"), f"row {index} fundamental_anchor"))
    parsed_labels = [_parse_timestamp(value, "timestamp") for value in labels]
    if parsed_labels != sorted(parsed_labels) or len(parsed_labels) != len(set(parsed_labels)):
        raise ValueError("ECB release-event timestamps must be strictly increasing and unique.")
    if periods != sorted(periods) or len(periods) != len(set(periods)):
        raise ValueError("ECB reference periods must be strictly increasing and unique.")
    return tuple(labels), tuple(real_values), tuple(nominal_values)


def build_ecb_measurement_robustness_protocol(
    *,
    snapshot_manifest: Any,
    rows: Sequence[Mapping[str, Any]],
    contract: Any,
    contract_audit: Any,
    experiment: Any,
) -> MeasurementRobustnessProtocol:
    manifest = _row(snapshot_manifest)
    contract_row = _row(contract)
    audit = _row(contract_audit)
    spec = _row(experiment)
    _validate_ecb_rows(rows)

    if str(manifest.get("dataset_id") or "") != ECB_RTD_DATASET_ID:
        raise ValueError("Only the frozen ECB RTD real/nominal snapshot is eligible for this protocol.")
    if str(manifest.get("status") or "") != "VALIDATED":
        raise ValueError("The ECB snapshot must be VALIDATED before protocol freeze.")
    if str(manifest.get("revision_policy") or "") != "POINT_IN_TIME_VINTAGES":
        raise ValueError("Measurement robustness requires point-in-time ECB vintages.")
    if str(manifest.get("availability_time_quality") or "") != "CONTROLLED":
        raise ValueError("Measurement robustness requires controlled observed availability timestamps.")
    if int(manifest.get("row_count") or 0) != len(rows):
        raise ValueError("Snapshot manifest row_count does not match the persisted dataset.")
    dataset_file_sha256 = str(manifest.get("dataset_file_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", dataset_file_sha256):
        raise ValueError("The persisted snapshot is missing a verified contract_rows.csv SHA-256 digest.")

    if str(contract_row.get("asset_identifier") or "") != ECB_RTD_DATASET_ID:
        raise ValueError("The selected HistoricalDataContract is not bound to the ECB RTD pilot.")
    if str(contract_row.get("status") or "") != "VALIDATED":
        raise ValueError("The selected HistoricalDataContract is not VALIDATED.")
    if str(contract_row.get("revision_policy") or "") != "POINT_IN_TIME_VINTAGES":
        raise ValueError("The selected contract does not require point-in-time vintages.")
    if str(contract_row.get("price_field") or "") != "price" or str(contract_row.get("fundamental_field") or "") != "fundamental_anchor":
        raise ValueError("The ECB robustness policy requires the frozen real/nominal source-field mapping.")
    if str(contract_row.get("event_time_field") or "") != "timestamp" or str(contract_row.get("vintage_time_field") or "") != "vintage_timestamp":
        raise ValueError("The ECB robustness policy requires exact event and vintage timestamps.")
    if str(audit.get("contract_id") or "") != str(contract_row.get("contract_id") or ""):
        raise ValueError("The contract audit does not belong to the selected contract.")
    if str(audit.get("overall_status") or "") not in {"VALIDATED", "VALIDATED_WITH_WARNINGS"}:
        raise ValueError("The HistoricalDataContract audit is not validated.")
    if str(audit.get("point_in_time_status") or "") != "PASS":
        raise ValueError("The HistoricalDataContract does not pass its point-in-time audit.")

    if str(spec.get("experiment_id") or "") != str(contract_row.get("experiment_id") or ""):
        raise ValueError("The experiment does not belong to the selected contract lineage.")
    if str(spec.get("status") or "") != "READY" or str(spec.get("transfer_verdict") or "") != "PARTIAL_TRANSFER":
        raise ValueError("Measurement robustness requires a READY PARTIAL_TRANSFER experiment.")
    if str(spec.get("experimental_family") or "") != "OU_MEAN_REVERTING_SDE":
        raise ValueError("Only the audited OU executor is eligible for this protocol.")
    if "NO_EVAL_NO_EXEC" not in str(spec.get("code_policy") or ""):
        raise ValueError("The experiment does not enforce the built-in executor policy.")
    train_fraction = float(contract_row.get("train_fraction") or 0.0)
    if not math.isclose(train_fraction, 0.70, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("The frozen measurement-robustness protocol requires a 70/30 chronological split.")
    forecast_horizon = int(contract_row.get("forecast_horizon") or 0)
    if forecast_horizon != 1:
        raise ValueError("The frozen measurement-robustness protocol requires a one-event forecast horizon.")

    variants = ecb_measurement_variant_specs()
    rows_fingerprint = snapshot_rows_fingerprint(rows)
    executor_code_digest = measurement_robustness_executor_digest()
    protocol_id = _stable_id(
        "MRP",
        MEASUREMENT_ROBUSTNESS_POLICY_VERSION,
        contract_row.get("question_id"),
        spec.get("experiment_id"),
        contract_row.get("contract_id"),
        audit.get("audit_id"),
        manifest.get("snapshot_id"),
        manifest.get("dataset_fingerprint"),
        rows_fingerprint,
        dataset_file_sha256,
        executor_code_digest,
        train_fraction,
        forecast_horizon,
        [asdict(item) for item in variants],
    )
    return MeasurementRobustnessProtocol(
        protocol_id=protocol_id,
        created_at=_now_iso(),
        question_id=str(contract_row.get("question_id") or ""),
        experiment_id=str(spec.get("experiment_id") or ""),
        contract_id=str(contract_row.get("contract_id") or ""),
        contract_audit_id=str(audit.get("audit_id") or ""),
        measurement_model_id=str(contract_row.get("measurement_model_id") or ""),
        measurement_decision_id=str(contract_row.get("measurement_decision_id") or ""),
        primary_observable_id=str(contract_row.get("observable_id") or ""),
        snapshot_id=str(manifest.get("snapshot_id") or ""),
        snapshot_fingerprint=str(manifest.get("dataset_fingerprint") or ""),
        snapshot_rows_fingerprint=rows_fingerprint,
        dataset_file_sha256=dataset_file_sha256,
        dataset_id=ECB_RTD_DATASET_ID,
        executor_code_digest=executor_code_digest,
        point_in_time_status="PASS",
        revision_risk_status="ABSENT",
        train_fraction=train_fraction,
        forecast_horizon=forecast_horizon,
        split_policy="CHRONOLOGICAL_HOLDOUT_70_30_NO_SHUFFLE",
        common_support_policy="IDENTICAL_RELEASE_EVENTS_TIMESTAMPS_SPLIT_AND_HORIZON",
        variants=variants,
        warnings=(
            "Protocol completion tests measurement dependence; it does not prove the transferred hypothesis.",
            "All variants share one ECB source archive and therefore do not constitute independent replication.",
            "All three predeclared screens must remain visible in the multiplicity record.",
        ),
    )


def _variant_values(
    variant_id: str,
    real_values: Sequence[float],
    nominal_values: Sequence[float],
) -> tuple[float, ...]:
    if variant_id == "MEASURE-ECB-REAL-LOG-LEVEL":
        return tuple(math.log(value) for value in real_values)
    if variant_id == "MEASURE-ECB-NOMINAL-LOG-LEVEL":
        return tuple(math.log(value) for value in nominal_values)
    if variant_id == "MEASURE-ECB-REAL-NOMINAL-LOG-WEDGE":
        return tuple(math.log(real) - math.log(nominal) for real, nominal in zip(real_values, nominal_values))
    raise ValueError(f"Unregistered measurement transform: {variant_id}")


def execute_ecb_measurement_robustness(
    *,
    protocol: Any,
    snapshot_manifest: Any,
    rows: Sequence[Mapping[str, Any]],
    experiment: Any,
    executor_code_digest: str,
) -> MeasurementRobustnessReport:
    protocol_row = _row(protocol)
    manifest = _row(snapshot_manifest)
    spec = _row(experiment)
    code_digest = str(executor_code_digest or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", code_digest):
        raise ValueError("Execution requires the exact SHA-256 digest of the audited executor source.")
    if str(protocol_row.get("status") or "") != "FROZEN":
        raise ValueError("Only a persisted FROZEN measurement protocol can execute.")
    expected_variants = [asdict(item) for item in ecb_measurement_variant_specs()]
    if _canonical(protocol_row.get("variants") or []) != _canonical(expected_variants):
        raise ValueError("The frozen measurement list differs from the registered policy allow-list.")
    if str(protocol_row.get("dataset_id") or "") != ECB_RTD_DATASET_ID:
        raise ValueError("The frozen protocol is not bound to the ECB RTD dataset.")
    if code_digest != str(protocol_row.get("executor_code_digest") or ""):
        raise ValueError("The comparative transform or OOS executor source changed after protocol freeze.")
    if str(protocol_row.get("point_in_time_status") or "") != "PASS" or str(protocol_row.get("revision_risk_status") or "") != "ABSENT":
        raise ValueError("The frozen protocol does not carry a clean point-in-time decision.")
    if not math.isclose(float(protocol_row.get("train_fraction") or 0.0), 0.70, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("The frozen train fraction has changed.")
    if int(protocol_row.get("forecast_horizon") or 0) != 1:
        raise ValueError("The frozen forecast horizon has changed.")
    if str(spec.get("experiment_id") or "") != str(protocol_row.get("experiment_id") or ""):
        raise ValueError("The executor specification is outside the frozen protocol lineage.")
    if str(spec.get("status") or "") != "READY" or str(spec.get("experimental_family") or "") != "OU_MEAN_REVERTING_SDE":
        raise ValueError("The audited READY OU executor is unavailable.")
    if "NO_EVAL_NO_EXEC" not in str(spec.get("code_policy") or ""):
        raise ValueError("The built-in-only code policy is no longer satisfied.")

    bindings = {
        "snapshot_id": "snapshot_id",
        "dataset_fingerprint": "snapshot_fingerprint",
        "dataset_file_sha256": "dataset_file_sha256",
        "dataset_id": "dataset_id",
    }
    for manifest_field, protocol_field in bindings.items():
        if str(manifest.get(manifest_field) or "") != str(protocol_row.get(protocol_field) or ""):
            raise ValueError(f"Snapshot binding changed after protocol freeze: {manifest_field}.")
    if snapshot_rows_fingerprint(rows) != str(protocol_row.get("snapshot_rows_fingerprint") or ""):
        raise ValueError("Snapshot rows changed after protocol freeze.")
    if int(manifest.get("row_count") or 0) != len(rows):
        raise ValueError("Snapshot manifest row_count changed after protocol freeze.")
    if str(manifest.get("revision_policy") or "") != "POINT_IN_TIME_VINTAGES" or str(manifest.get("availability_time_quality") or "") != "CONTROLLED":
        raise ValueError("Snapshot point-in-time controls no longer match the frozen protocol.")

    labels, real_values, nominal_values = _validate_ecb_rows(rows)
    results: list[MeasurementVariantResult] = []
    for variant in ecb_measurement_variant_specs():
        values = _variant_values(variant.variant_id, real_values, nominal_values)
        run = run_historical_oos_experiment(
            spec,
            values,
            labels=labels,
            train_fraction=0.70,
            data_contract_id=str(protocol_row.get("contract_id") or ""),
            data_contract_audit_id=str(protocol_row.get("contract_audit_id") or ""),
            dataset_manifest_id=str(protocol_row.get("snapshot_id") or ""),
            measurement_model_id=str(protocol_row.get("measurement_model_id") or ""),
            measurement_decision_id=str(protocol_row.get("measurement_decision_id") or ""),
            observable_id=variant.variant_id,
            forecast_horizon=1,
            selection_context={
                "purpose": "PREDECLARED_MEASUREMENT_ROBUSTNESS",
                "protocol_id": str(protocol_row.get("protocol_id") or ""),
                "predeclared_variant_count": len(expected_variants),
            },
        )
        variant_result_id = _stable_id(
            "MRV",
            protocol_row.get("protocol_id"),
            variant.variant_id,
            run.data_fingerprint,
            run.forecast_trace_fingerprint,
            code_digest,
        )
        results.append(MeasurementVariantResult(
            variant_result_id=variant_result_id,
            variant_id=variant.variant_id,
            label=variant.label,
            formula=variant.formula,
            verdict=run.verdict,
            data_fingerprint=run.data_fingerprint,
            forecast_trace_fingerprint=run.forecast_trace_fingerprint,
            row_count=len(values),
            train_size=run.train_size,
            test_size=run.test_size,
            split_timestamp=run.split_timestamp,
            candidate_metrics=dict(run.candidate_metrics),
            baseline_metrics={name: dict(metrics) for name, metrics in run.baseline_metrics.items()},
            deltas_vs_baseline={name: dict(metrics) for name, metrics in run.deltas_vs_baseline.items()},
            fitted_parameters=dict(run.fitted_parameters),
            chronological_split_robustness=dict(run.robustness),
            forecast_origin_timestamps=tuple(run.forecast_origin_timestamps),
            forecast_timestamps=tuple(run.forecast_timestamps),
            actual_values=tuple(run.actual_values),
            candidate_predictions=tuple(run.candidate_predictions),
            candidate_errors=tuple(run.candidate_errors),
            baseline_predictions={name: tuple(values) for name, values in run.baseline_predictions.items()},
            baseline_errors={name: tuple(values) for name, values in run.baseline_errors.items()},
        ))

    support_signatures = {
        (item.row_count, item.forecast_origin_timestamps, item.forecast_timestamps)
        for item in results
    }
    split_signatures = {
        (item.train_size, item.test_size, item.split_timestamp)
        for item in results
    }
    if len(support_signatures) != 1:
        raise ValueError("The executor did not preserve identical temporal support across measurements.")
    if len(split_signatures) != 1:
        raise ValueError("The executor did not preserve the frozen chronological split across measurements.")
    if len({item.variant_id for item in results}) != len(expected_variants):
        raise ValueError("The execution did not produce every distinct predeclared measurement.")

    promising = sum(item.verdict == "PROMISING_OOS" for item in results)
    no_improvement = sum(item.verdict == "NO_OOS_IMPROVEMENT" for item in results)
    if no_improvement == len(results):
        conclusion = "CONSISTENT_NO_OOS_IMPROVEMENT"
    elif promising == len(results):
        conclusion = "CONSISTENT_PROMISING_REQUIRES_REVIEW"
    else:
        conclusion = "MEASUREMENT_DEPENDENT"
    timestamps_fingerprint = _digest(labels)
    execution_fingerprint = _digest({
        "policy_version": MEASUREMENT_ROBUSTNESS_POLICY_VERSION,
        "protocol_id": protocol_row.get("protocol_id"),
        "executor_code_digest": code_digest,
        "variant_results": [
            {
                "variant_result_id": item.variant_result_id,
                "data_fingerprint": item.data_fingerprint,
                "forecast_trace_fingerprint": item.forecast_trace_fingerprint,
                "verdict": item.verdict,
            }
            for item in results
        ],
    })
    report_id = _stable_id("MRR", protocol_row.get("protocol_id"), execution_fingerprint)
    return MeasurementRobustnessReport(
        report_id=report_id,
        created_at=_now_iso(),
        protocol_id=str(protocol_row.get("protocol_id") or ""),
        question_id=str(protocol_row.get("question_id") or ""),
        experiment_id=str(protocol_row.get("experiment_id") or ""),
        contract_id=str(protocol_row.get("contract_id") or ""),
        snapshot_id=str(protocol_row.get("snapshot_id") or ""),
        snapshot_fingerprint=str(protocol_row.get("snapshot_fingerprint") or ""),
        executor_code_digest=code_digest,
        execution_fingerprint=execution_fingerprint,
        common_timestamps_fingerprint=timestamps_fingerprint,
        common_support_status="PASS",
        common_split_status="PASS",
        point_in_time_status="PASS",
        variant_count=len(results),
        promising_variant_count=promising,
        no_improvement_variant_count=no_improvement,
        conclusion=conclusion,
        gate_status="PASS",
        variant_results=tuple(results),
        warnings=(
            "PASS means the predeclared measurement-dependence protocol completed; it is not positive evidence for the hypothesis.",
            "A negative result is retained unchanged and must not be reinterpreted as model success.",
            "The variants share ECB data lineage and do not satisfy the independent-replication gate.",
            "All three screens count toward selection pressure and multiple-testing review.",
            "RESEARCH_ONLY; production and automatic belief updates remain prohibited.",
        ),
    )
