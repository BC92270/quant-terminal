from __future__ import annotations

import hashlib
import json
import math
import statistics
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from .phase63_models import (
    BreakDiagnostic,
    CausalTransformStep,
    DataContractAudit,
    DataFieldSpec,
    DatasetManifest,
    ExperimentAttemptRecord,
    HistoricalDataContract,
    MaterializedDataset,
    ReproducibilityCapsule,
    SelectionPressureSnapshot,
)


ALLOWED_ANCHOR_FAMILIES = {
    "CAPE_STYLE_EARNINGS",
    "DIVIDENDS",
    "BOOK_VALUE",
    "CASH_FLOW",
    "ETF_NAV",
    "OTHER_DECLARED",
}
ALLOWED_REVISION_POLICIES = {
    "POINT_IN_TIME_VINTAGES",
    "REVISED_WITH_RISK_FLAG",
    "NOT_REVISED",
}
ALLOWED_FREQUENCIES = {"DAILY", "WEEKLY", "MONTHLY", "QUARTERLY"}
ALLOWED_TRANSFORMS = {
    "ASSERT_STRICT_CHRONOLOGY",
    "ALIGN_BY_PUBLIC_AVAILABILITY",
    "FORWARD_FILL_AFTER_RELEASE_ONLY",
    "POSITIVE_LOG_RATIO",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if is_dataclass(value):
        return asdict(value)
    return dict(value)


def _clean_refs(values: Iterable[str] | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(value).strip() for value in (values or ()) if str(value).strip()))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _stable_id(prefix: str, value: Any) -> str:
    return f"{prefix}-{_fingerprint(value)[:16]}"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_time(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        raw = _text(value)
        if not raw:
            raise ValueError(f"Missing timestamp in {field_name}.")
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError(f"Timestamp in {field_name} is not ISO-8601 parseable: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _positive_float(value: Any, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric.") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{field_name} must be finite and strictly positive before log transformation.")
    return parsed


def build_historical_data_contract(
    *,
    question: Any,
    plan: Any,
    experiment: Any,
    measurement_model: Any,
    measurement_decision: Any,
    observable: Any,
    market: str,
    universe: str,
    asset_identifier: str,
    provider: str,
    raw_data_uri: str,
    license_or_terms: str,
    anchor_family: str,
    price_field: str = "price",
    fundamental_field: str = "fundamental_anchor",
    event_time_field: str = "timestamp",
    availability_time_field: str = "fundamental_release_timestamp",
    vintage_time_field: str = "",
    frequency: str = "MONTHLY",
    timezone_name: str = "UTC",
    publication_lag_days: int = 0,
    revision_policy: str = "REVISED_WITH_RISK_FLAG",
    missing_data_policy: str = "DROP_LEADING_ROWS_BEFORE_FIRST_RELEASE_ONLY",
    duplicate_policy: str = "REJECT",
    train_fraction: float = 0.70,
    forecast_horizon: int = 1,
    embargo_periods: int = 0,
    max_rows: int = 250000,
    source_refs: Iterable[str] = (),
    rationale: str = "",
) -> HistoricalDataContract:
    q = _row(question)
    plan_row = _row(plan)
    exp = _row(experiment)
    model = _row(measurement_model)
    decision = _row(measurement_decision)
    obs = _row(observable)
    blockers: list[str] = []
    warnings: list[str] = []

    qid = _text(q.get("question_id"))
    plan_id = _text(plan_row.get("plan_id"))
    experiment_id = _text(exp.get("experiment_id"))
    model_id = _text(model.get("measurement_model_id"))
    decision_id = _text(decision.get("decision_id"))
    observable_id = _text(obs.get("observable_id"))

    if not all((qid, plan_id, experiment_id, model_id, decision_id, observable_id)):
        blockers.append("Question, plan, experiment, measurement model, decision and observable IDs are all required.")
    if _text(plan_row.get("question_id")) != qid:
        blockers.append("Research plan does not belong to the selected question.")
    if _text(model.get("question_id")) != qid:
        blockers.append("Measurement model does not belong to the selected question.")
    if _text(decision.get("measurement_model_id")) != model_id:
        blockers.append("Measurement decision does not belong to the selected measurement model.")
    if _text(decision.get("selected_observable_id")) != observable_id:
        blockers.append("Data contract observable is not the explicit primary MeasurementDecision.")
    if observable_id not in {str(value) for value in (model.get("observable_ids") or ())}:
        blockers.append("Observable is not a member of the selected Measurement Model.")
    if _text(model.get("primary_observable_id")) not in {"", observable_id}:
        blockers.append("Measurement Model primary observable conflicts with the MeasurementDecision.")
    if _text(q.get("selected_observable_id")) not in {"", observable_id}:
        blockers.append("Research Question primary observable conflicts with the MeasurementDecision.")
    if _text(obs.get("status")).upper() != "SELECTED":
        blockers.append(
            "The MeasurementDecision has not been reconciled into the observable lifecycle; "
            "the selected observable must be explicitly SELECTED before a historical contract can validate."
        )
    label_and_definition = f"{obs.get('label', '')} {obs.get('mathematical_definition', '')}".lower()
    if "fundamental" not in label_and_definition:
        blockers.append("The first v0.6.3 materializer is restricted to a declared price-to-fundamental observable.")

    market = _text(market)
    universe = _text(universe)
    asset_identifier = _text(asset_identifier)
    provider = _text(provider)
    raw_data_uri = _text(raw_data_uri)
    license_or_terms = _text(license_or_terms)
    rationale = _text(rationale)
    price_field = _text(price_field)
    fundamental_field = _text(fundamental_field)
    event_time_field = _text(event_time_field)
    availability_time_field = _text(availability_time_field)
    vintage_time_field = _text(vintage_time_field)
    anchor_family = _text(anchor_family).upper()
    frequency = _text(frequency).upper()
    revision_policy = _text(revision_policy).upper()
    publication_lag_days = int(publication_lag_days)
    forecast_horizon = int(forecast_horizon)
    embargo_periods = int(embargo_periods)
    max_rows = int(max_rows)
    train_fraction = float(train_fraction)

    for value, label in (
        (market, "market"), (universe, "universe"), (asset_identifier, "asset identifier"),
        (provider, "provider"), (raw_data_uri, "raw data URI"), (license_or_terms, "license/terms"),
        (price_field, "price field"), (fundamental_field, "fundamental field"),
        (event_time_field, "event-time field"), (availability_time_field, "availability-time field"),
        (rationale, "contract rationale"),
    ):
        if not value:
            blockers.append(f"An explicit {label} is required.")
    if anchor_family not in ALLOWED_ANCHOR_FAMILIES:
        blockers.append(f"Anchor family must be exactly one allowed family: {', '.join(sorted(ALLOWED_ANCHOR_FAMILIES))}.")
    if frequency not in ALLOWED_FREQUENCIES:
        blockers.append(f"Unsupported sampling frequency: {frequency or 'EMPTY'}.")
    if revision_policy not in ALLOWED_REVISION_POLICIES:
        blockers.append("Revision policy must be POINT_IN_TIME_VINTAGES, REVISED_WITH_RISK_FLAG or NOT_REVISED.")
    if revision_policy == "POINT_IN_TIME_VINTAGES" and not vintage_time_field:
        blockers.append("POINT_IN_TIME_VINTAGES requires a vintage timestamp field.")
    if revision_policy == "REVISED_WITH_RISK_FLAG":
        warnings.append("Only revised history is declared; REVISION_RISK_PRESENT will remain visible in every manifest and result.")
    if publication_lag_days < 0:
        blockers.append("Publication lag cannot be negative.")
    if not 0.50 <= train_fraction <= 0.90:
        blockers.append("Chronological training fraction must be between 0.50 and 0.90.")
    if forecast_horizon < 1:
        blockers.append("Forecast horizon must be at least one period.")
    if embargo_periods < 0:
        blockers.append("Embargo periods cannot be negative.")
    if max_rows < 40 or max_rows > 2_000_000:
        blockers.append("max_rows must be between 40 and 2,000,000.")
    if _text(missing_data_policy) != "DROP_LEADING_ROWS_BEFORE_FIRST_RELEASE_ONLY":
        blockers.append("v0.6.3 only permits dropping leading rows before the first public anchor release; silent interior imputation is forbidden.")
    if _text(duplicate_policy) != "REJECT":
        blockers.append("Duplicate timestamps must be rejected in v0.6.3.")

    fields = (
        DataFieldSpec(event_time_field or "timestamp", "EVENT_TIME", "ISO8601", "UTC timestamp"),
        DataFieldSpec(price_field or "price", "PRICE", "FLOAT", "declared price units", strictly_positive=True),
        DataFieldSpec(fundamental_field or "fundamental_anchor", "FUNDAMENTAL_ANCHOR", "FLOAT", "declared anchor units", strictly_positive=True),
        DataFieldSpec(availability_time_field or "fundamental_release_timestamp", "PUBLIC_AVAILABILITY_TIME", "ISO8601", "UTC timestamp"),
    ) + ((DataFieldSpec(vintage_time_field, "VINTAGE_TIME", "ISO8601", "UTC timestamp"),) if vintage_time_field else ())
    transforms = (
        CausalTransformStep("STEP-1", "ASSERT_STRICT_CHRONOLOGY", "Reject missing, duplicate or non-monotonic event timestamps."),
        CausalTransformStep("STEP-2", "ALIGN_BY_PUBLIC_AVAILABILITY", "Use a fundamental anchor only when its public availability timestamp is at or before event time.", {"publication_lag_days": publication_lag_days}),
        CausalTransformStep("STEP-3", "FORWARD_FILL_AFTER_RELEASE_ONLY", "Permit a previously released anchor to persist; never backfill from a future release."),
        CausalTransformStep("STEP-4", "POSITIVE_LOG_RATIO", "Materialize x_t = log(price_t) - log(fundamental_anchor_t) after positivity checks."),
    )
    contract_payload = {
        "question_id": qid, "plan_id": plan_id, "experiment_id": experiment_id,
        "measurement_model_id": model_id, "measurement_decision_id": decision_id, "observable_id": observable_id,
        "market": market, "universe": universe, "asset_identifier": asset_identifier,
        "provider": provider, "raw_data_uri": raw_data_uri, "license_or_terms": license_or_terms,
        "price_field": price_field, "fundamental_field": fundamental_field, "event_time_field": event_time_field,
        "availability_time_field": availability_time_field, "vintage_time_field": vintage_time_field,
        "anchor_family": anchor_family, "frequency": frequency, "timezone": _text(timezone_name) or "UTC",
        "publication_lag_days": publication_lag_days, "revision_policy": revision_policy,
        "missing_data_policy": _text(missing_data_policy), "duplicate_policy": _text(duplicate_policy),
        "train_fraction": train_fraction, "forecast_horizon": forecast_horizon,
        "embargo_periods": embargo_periods, "max_rows": max_rows, "source_refs": _clean_refs(source_refs),
        "rationale": rationale, "transform_operations": [step.operation for step in transforms],
    }
    contract_id = _stable_id("HDC", contract_payload)
    warnings.extend((
        "A validated data contract is an auditable protocol, not evidence that the anchor measures fundamental value correctly.",
        "Competing measurements and anchor sensitivity remain required before generalizing any result.",
    ))
    return HistoricalDataContract(
        contract_id=contract_id,
        created_at=_now_iso(),
        question_id=qid,
        plan_id=plan_id,
        experiment_id=experiment_id,
        measurement_model_id=model_id,
        measurement_decision_id=decision_id,
        observable_id=observable_id,
        target_concept=_text(model.get("target_concept")) or _text(q.get("target_variable")) or "market_state",
        market=market,
        universe=universe,
        asset_identifier=asset_identifier,
        provider=provider,
        raw_data_uri=raw_data_uri,
        license_or_terms=license_or_terms,
        price_field=price_field,
        fundamental_field=fundamental_field,
        event_time_field=event_time_field,
        availability_time_field=availability_time_field,
        vintage_time_field=vintage_time_field,
        anchor_family=anchor_family,
        frequency=frequency,
        timezone=_text(timezone_name) or "UTC",
        publication_lag_days=publication_lag_days,
        revision_policy=revision_policy,
        missing_data_policy=_text(missing_data_policy),
        duplicate_policy=_text(duplicate_policy),
        split_policy="CHRONOLOGICAL_HOLDOUT",
        train_fraction=train_fraction,
        forecast_horizon=forecast_horizon,
        embargo_periods=embargo_periods,
        max_rows=max_rows,
        formula="market_state_t = log(price_t) - log(fundamental_anchor_t)",
        field_specs=fields,
        transform_steps=transforms,
        source_refs=_clean_refs(source_refs),
        rationale=rationale,
        status="BLOCKED" if blockers else "VALIDATED",
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def audit_historical_data_contract(contract: Any) -> DataContractAudit:
    row = _row(contract)
    blockers = list(row.get("blockers") or ())
    warnings = list(row.get("warnings") or ())
    checks: list[dict[str, Any]] = []

    required_fields = (
        "contract_id", "question_id", "plan_id", "experiment_id", "measurement_model_id",
        "measurement_decision_id", "observable_id", "market", "universe", "asset_identifier",
        "provider", "raw_data_uri", "license_or_terms", "price_field", "fundamental_field",
        "event_time_field", "availability_time_field", "anchor_family", "frequency", "revision_policy",
    )
    missing = [field for field in required_fields if not _text(row.get(field))]
    schema_status = "PASS" if not missing else "BLOCKED"
    checks.append({"check": "required_schema", "status": schema_status, "detail": "complete" if not missing else f"missing: {', '.join(missing)}"})
    if missing:
        blockers.append(f"Required contract fields are missing: {', '.join(missing)}.")

    chronology_status = "PASS" if row.get("split_policy") == "CHRONOLOGICAL_HOLDOUT" and row.get("duplicate_policy") == "REJECT" else "BLOCKED"
    checks.append({"check": "chronology_policy", "status": chronology_status, "detail": "strict timestamps + chronological holdout required"})
    if chronology_status == "BLOCKED":
        blockers.append("Chronology policy is not strict enough for historical OOS.")

    revision_policy = _text(row.get("revision_policy")).upper()
    if revision_policy == "POINT_IN_TIME_VINTAGES" and _text(row.get("vintage_time_field")):
        point_status = "PASS"
    elif revision_policy == "NOT_REVISED":
        point_status = "PASS"
    elif revision_policy == "REVISED_WITH_RISK_FLAG":
        point_status = "WARNING"
        warnings.append("Point-in-time vintages are unavailable; revision risk is explicitly present.")
    else:
        point_status = "BLOCKED"
        blockers.append("Point-in-time/revision policy is unresolved.")
    checks.append({"check": "point_in_time_policy", "status": point_status, "detail": revision_policy or "missing"})

    links = (
        _text(row.get("question_id")), _text(row.get("measurement_model_id")),
        _text(row.get("measurement_decision_id")), _text(row.get("observable_id")),
    )
    measurement_status = "PASS" if all(links) and "log(price" in _text(row.get("formula")) else "BLOCKED"
    checks.append({"check": "measurement_alignment", "status": measurement_status, "detail": _text(row.get("observable_id"))})
    if measurement_status == "BLOCKED":
        blockers.append("Measurement lineage or materialization formula is incomplete.")

    operations = [str(step.get("operation") or "") for step in (row.get("transform_steps") or ()) if isinstance(step, Mapping)]
    required_operations = {
        "ASSERT_STRICT_CHRONOLOGY", "ALIGN_BY_PUBLIC_AVAILABILITY",
        "FORWARD_FILL_AFTER_RELEASE_ONLY", "POSITIVE_LOG_RATIO",
    }
    transform_status = "PASS" if required_operations.issubset(set(operations)) and set(operations).issubset(ALLOWED_TRANSFORMS) else "BLOCKED"
    checks.append({"check": "allowlisted_transforms", "status": transform_status, "detail": ", ".join(operations)})
    if transform_status == "BLOCKED":
        blockers.append("Transform pipeline is incomplete or contains a non-allowlisted operation.")

    blockers = list(dict.fromkeys(blockers))
    warnings = list(dict.fromkeys(warnings))
    overall = "BLOCKED" if blockers else "VALIDATED_WITH_WARNINGS" if point_status == "WARNING" else "VALIDATED"
    audit_payload = {
        "contract_id": row.get("contract_id"), "schema": schema_status, "chronology": chronology_status,
        "point": point_status, "measurement": measurement_status, "transform": transform_status,
        "blockers": blockers, "warnings": warnings,
    }
    return DataContractAudit(
        audit_id=_stable_id("HDCAUDIT", audit_payload),
        created_at=_now_iso(),
        contract_id=_text(row.get("contract_id")),
        schema_status=schema_status,
        chronology_status=chronology_status,
        point_in_time_status=point_status,
        measurement_alignment_status=measurement_status,
        transformation_status=transform_status,
        overall_status=overall,
        checks=tuple(checks),
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def materialize_price_to_fundamental(
    rows: Sequence[Mapping[str, Any]],
    contract: Any,
    *,
    dataset_label: str,
    contract_audit: Any | None = None,
) -> MaterializedDataset:
    contract_row = _row(contract)
    audit = _row(contract_audit) if contract_audit is not None else _row(audit_historical_data_contract(contract_row))
    if str(audit.get("overall_status") or "").startswith("BLOCKED"):
        raise ValueError("Historical data contract is blocked and cannot materialize a dataset.")
    if len(rows) > int(contract_row.get("max_rows") or 250000):
        raise ValueError("Dataset exceeds the contract row limit.")
    if len(rows) < 40:
        raise ValueError("At least 40 chronological observations are required.")

    time_field = _text(contract_row.get("event_time_field"))
    price_field = _text(contract_row.get("price_field"))
    anchor_field = _text(contract_row.get("fundamental_field"))
    availability_field = _text(contract_row.get("availability_time_field"))
    vintage_field = _text(contract_row.get("vintage_time_field"))
    revision_policy = _text(contract_row.get("revision_policy")).upper()

    timestamps: list[str] = []
    prices: list[float] = []
    anchors: list[float] = []
    availability_timestamps: list[str] = []
    vintage_timestamps: list[str] = []
    values: list[float] = []
    raw_records: list[dict[str, Any]] = []
    previous_event: datetime | None = None
    previous_availability: datetime | None = None
    previous_anchor: float | None = None
    previous_vintage: datetime | None = None
    excluded_leading_rows = 0
    causal_forward_fills = 0
    first_anchor_seen = False
    publication_lag_days = int(contract_row.get("publication_lag_days") or 0)

    for index, source_row in enumerate(rows):
        row = dict(source_row)
        for field in (time_field, price_field):
            if field not in row or row.get(field) in (None, ""):
                raise ValueError(f"Row {index} is missing required field {field}.")
        event_time = _parse_time(row.get(time_field), time_field)
        if previous_event is not None and event_time <= previous_event:
            raise ValueError("Event timestamps must be strictly increasing and unique in input order.")
        previous_event = event_time
        price = _positive_float(row.get(price_field), price_field)

        anchor_missing = anchor_field not in row or row.get(anchor_field) in (None, "")
        availability_missing = availability_field not in row or row.get(availability_field) in (None, "")
        if anchor_missing != availability_missing:
            missing_name = anchor_field if anchor_missing else availability_field
            raise ValueError(
                f"Row {index} is missing only {missing_name}; anchor values and their public-availability "
                "timestamps must appear together."
            )
        carried_forward = anchor_missing and availability_missing and first_anchor_seen
        if anchor_missing and availability_missing and not first_anchor_seen:
            raw_records.append({
                "event_time": _iso(event_time), "price": round(price, 12),
                "raw_anchor": None, "materialized_anchor": None,
                "raw_availability_time": None, "materialized_availability_time": None,
                "vintage_time": row.get(vintage_field) if vintage_field else "",
                "lineage_action": "EXCLUDED_LEADING_ROW_BEFORE_FIRST_PUBLIC_ANCHOR",
            })
            excluded_leading_rows += 1
            continue

        if carried_forward:
            if previous_anchor is None or previous_availability is None:
                raise ValueError("Causal forward-fill state is unavailable after the first anchor release.")
            anchor = previous_anchor
            availability_time = previous_availability
            vintage_time = previous_vintage
            if vintage_field and row.get(vintage_field) not in (None, ""):
                declared_vintage = _parse_time(row.get(vintage_field), vintage_field)
                if previous_vintage is None or declared_vintage != previous_vintage:
                    raise ValueError(
                        f"Row {index} declares a new vintage while carrying forward an old anchor; "
                        "new vintage lineage requires an explicit anchor and availability timestamp."
                    )
            causal_forward_fills += 1
        else:
            first_anchor_seen = True
            anchor = _positive_float(row.get(anchor_field), anchor_field)
            availability_time = _parse_time(row.get(availability_field), availability_field)
            vintage_time: datetime | None = None
            if vintage_field:
                if row.get(vintage_field) in (None, ""):
                    if revision_policy == "POINT_IN_TIME_VINTAGES":
                        raise ValueError(f"Row {index} is missing the required point-in-time vintage timestamp.")
                else:
                    vintage_time = _parse_time(row.get(vintage_field), vintage_field)
                    if vintage_time > event_time:
                        raise ValueError(f"Row {index} uses a vintage not available at event time.")

        usable_time = availability_time + timedelta(days=publication_lag_days)
        if usable_time > event_time:
            raise ValueError(
                f"Row {index} uses a fundamental anchor before its public availability timestamp "
                "plus the declared publication lag."
            )
        if previous_availability is not None and availability_time < previous_availability:
            raise ValueError("Fundamental availability timestamps move backward; causal as-of lineage is inconsistent.")
        state = math.log(price) - math.log(anchor)
        timestamps.append(_iso(event_time))
        availability_timestamps.append(_iso(availability_time))
        vintage_timestamps.append(_iso(vintage_time) if vintage_time is not None else "")
        prices.append(price)
        anchors.append(anchor)
        values.append(state)
        raw_records.append({
            "event_time": _iso(event_time), "price": round(price, 12),
            "raw_anchor": None if carried_forward else round(anchor, 12),
            "materialized_anchor": round(anchor, 12),
            "raw_availability_time": None if carried_forward else _iso(availability_time),
            "materialized_availability_time": _iso(availability_time),
            "vintage_time": _iso(vintage_time) if vintage_time else "",
            "lineage_action": "CAUSAL_FORWARD_FILL_AFTER_RELEASE" if carried_forward else "DIRECT_RELEASE_OBSERVATION",
        })
        previous_availability = availability_time
        previous_anchor = anchor
        previous_vintage = vintage_time

    if len(values) < 40:
        raise ValueError("At least 40 valid chronological observations are required after leading pre-release rows are excluded.")

    train_fraction = float(contract_row.get("train_fraction") or 0.70)
    split = max(20, min(len(values) - 10, int(len(values) * train_fraction)))
    contract_fingerprint = _fingerprint({key: value for key, value in contract_row.items() if key != "created_at"})
    raw_fingerprint = _fingerprint(raw_records)
    # Keep this payload identical to experiment_factory.dataset_fingerprint so the
    # manifest and the executed run can be matched without trusting UI state.
    materialized_fingerprint = _fingerprint({
        "values": [round(value, 12) for value in values],
        "labels": timestamps,
    })
    point_status = str(audit.get("point_in_time_status") or "BLOCKED")
    revision_risk = "PRESENT" if revision_policy == "REVISED_WITH_RISK_FLAG" else "CONTROLLED"
    checks = (
        {"check": "strict_chronology", "status": "PASS", "detail": f"{len(rows)} unique increasing raw timestamps"},
        {"check": "public_availability", "status": "PASS", "detail": f"availability_time + {publication_lag_days} day lag <= event_time for every materialized row"},
        {"check": "leading_missing_policy", "status": "PASS", "detail": f"{excluded_leading_rows} leading pre-release row(s) excluded; no interior rows dropped"},
        {"check": "causal_forward_fill", "status": "PASS", "detail": f"{causal_forward_fills} post-release row(s) carried forward from information already public"},
        {"check": "positive_log_inputs", "status": "PASS", "detail": "all prices and anchors finite and > 0"},
        {"check": "chronological_split", "status": "PASS", "detail": f"train={split}; test={len(values)-split}"},
        {"check": "revision_policy", "status": point_status, "detail": revision_policy},
    )
    warnings = list(audit.get("warnings") or ())
    if revision_risk == "PRESENT":
        warnings.append("Materialized values use revised history; target-domain conclusions must retain REVISION_RISK_PRESENT.")
    manifest_payload = {
        "contract_id": contract_row.get("contract_id"), "raw": raw_fingerprint,
        "materialized": materialized_fingerprint, "rows": len(values), "split": split,
    }
    manifest = DatasetManifest(
        manifest_id=_stable_id("MANIFEST", manifest_payload),
        created_at=_now_iso(),
        contract_id=_text(contract_row.get("contract_id")),
        observable_id=_text(contract_row.get("observable_id")),
        dataset_label=_text(dataset_label) or f"Dataset {materialized_fingerprint[:10]}",
        raw_fingerprint=raw_fingerprint,
        materialized_fingerprint=materialized_fingerprint,
        contract_fingerprint=contract_fingerprint,
        row_count=len(rows),
        valid_row_count=len(values),
        excluded_row_count=excluded_leading_rows,
        start_timestamp=timestamps[0],
        end_timestamp=timestamps[-1],
        split_timestamp=timestamps[split],
        train_size=split,
        test_size=len(values) - split,
        point_in_time_status=point_status,
        revision_risk_status=revision_risk,
        checks=checks,
        status="VALIDATED_WITH_REVISION_RISK" if revision_risk == "PRESENT" else "VALIDATED",
        source_refs=_clean_refs(contract_row.get("source_refs") or ()),
        warnings=tuple(dict.fromkeys(warnings)),
    )
    return MaterializedDataset(
        manifest=manifest,
        timestamps=tuple(timestamps),
        values=tuple(values),
        prices=tuple(prices),
        fundamental_anchors=tuple(anchors),
        availability_timestamps=tuple(availability_timestamps),
        vintage_timestamps=tuple(vintage_timestamps),
    )


def build_experiment_attempt(
    *,
    experiment: Any,
    contract: Any,
    manifest: Any,
    purpose: str,
    actor: str = "HUMAN",
) -> ExperimentAttemptRecord:
    exp = _row(experiment)
    contract_row = _row(contract)
    manifest_row = _row(manifest)
    if _text(exp.get("experiment_id")) != _text(contract_row.get("experiment_id")):
        raise ValueError("Experiment and data contract IDs do not align.")
    if _text(contract_row.get("contract_id")) != _text(manifest_row.get("contract_id")):
        raise ValueError("Dataset manifest does not belong to the selected contract.")
    run_payload = {
        "experiment_id": exp.get("experiment_id"),
        "experimental_family": exp.get("experimental_family"),
        "manifest_fingerprint": manifest_row.get("materialized_fingerprint"),
        "contract_fingerprint": manifest_row.get("contract_fingerprint"),
        "observable_id": contract_row.get("observable_id"),
        "train_fraction": contract_row.get("train_fraction"),
        "forecast_horizon": contract_row.get("forecast_horizon"),
        "seed": exp.get("seed"),
        "executor": "SRB_BUILTIN_OU_HISTORICAL_V2",
    }
    run_signature = _stable_id("RUNSIG", run_payload)
    evidence_unit_id = _stable_id("EUNIT", {**run_payload, "purpose": _text(purpose)})
    created_at = _now_iso()
    attempt_id = f"ATTEMPT-{uuid.uuid4().hex[:16]}"
    return ExperimentAttemptRecord(
        attempt_id=attempt_id,
        created_at=created_at,
        experiment_id=_text(exp.get("experiment_id")),
        run_signature=run_signature,
        evidence_unit_id=evidence_unit_id,
        contract_id=_text(contract_row.get("contract_id")),
        manifest_id=_text(manifest_row.get("manifest_id")),
        observable_id=_text(contract_row.get("observable_id")),
        purpose=_text(purpose) or "PREDECLARED_HISTORICAL_OOS",
        status="PLANNED",
        actor=_text(actor) or "HUMAN",
        lifecycle_history=({
            "at": created_at, "from": "", "to": "PLANNED", "actor": _text(actor) or "HUMAN",
            "reason": "Explicit experiment attempt registered before execution.",
        },),
    )


def build_break_diagnostic(
    run: Any,
    *,
    baseline_name: str = "Random Walk / Last Observation",
    calibration_fraction: float = 0.40,
    threshold: float = 5.0,
) -> BreakDiagnostic:
    row = _row(run)
    timestamps = [str(value) for value in (row.get("forecast_timestamps") or ())]
    candidate_errors = [float(value) for value in (row.get("candidate_errors") or ())]
    baseline_errors_map = row.get("baseline_errors") or {}
    baseline_errors = [float(value) for value in (baseline_errors_map.get(baseline_name) or ())]
    if not timestamps or len(timestamps) != len(candidate_errors) or len(timestamps) != len(baseline_errors):
        raise ValueError("Break diagnostics require aligned forecast timestamps, candidate errors and baseline errors.")
    if len(timestamps) < 20:
        raise ValueError("At least 20 OOS forecast errors are required for the predeclared break diagnostic.")
    if not 0.20 <= float(calibration_fraction) <= 0.60:
        raise ValueError("Calibration fraction must be between 0.20 and 0.60.")
    if float(threshold) <= 0:
        raise ValueError("CUSUM threshold must be positive.")

    differential = [candidate * candidate - baseline * baseline for candidate, baseline in zip(candidate_errors, baseline_errors)]
    calibration_size = max(8, min(len(differential) - 5, int(len(differential) * float(calibration_fraction))))
    calibration = differential[:calibration_size]
    center = statistics.fmean(calibration)
    scale = statistics.stdev(calibration) if len(calibration) > 1 else 0.0
    if scale <= 1e-15:
        scale = max(1e-12, abs(center), 1.0)
    cumulative = 0.0
    path: list[float] = []
    signals: list[str] = []
    for index, value in enumerate(differential):
        cumulative += (value - center) / (scale * math.sqrt(len(differential)))
        rounded = round(cumulative, 8)
        path.append(rounded)
        if index >= calibration_size and abs(cumulative) >= float(threshold):
            signals.append(timestamps[index])
    max_abs = max(abs(value) for value in path) if path else 0.0
    payload = {
        "run_id": row.get("run_id"), "baseline": baseline_name,
        "calibration_fraction": calibration_fraction, "threshold": threshold,
        "trace": row.get("forecast_trace_fingerprint"),
    }
    return BreakDiagnostic(
        diagnostic_id=_stable_id("BREAK", payload),
        created_at=_now_iso(),
        run_id=_text(row.get("run_id")),
        experiment_id=_text(row.get("experiment_id")),
        observable_id=_text(row.get("observable_id")),
        baseline_name=baseline_name,
        method="PREDECLARED_OOS_LOSS_DIFFERENTIAL_CUSUM_V1",
        calibration_size=calibration_size,
        threshold=float(threshold),
        status="SIGNAL_DETECTED" if signals else "NO_SIGNAL",
        signal_timestamps=tuple(signals),
        cumulative_path=tuple(path),
        max_abs_statistic=round(max_abs, 8),
        warnings=(
            "This diagnostic screens forecast-loss instability; it does not identify a causal regime or validate a regime-switching model.",
            "Threshold and calibration settings are research design choices and count toward selection pressure.",
        ),
    )


def build_selection_pressure_snapshot(
    *,
    question_id: str,
    experiment_id: str,
    attempts: Sequence[Mapping[str, Any]],
    runs: Sequence[Mapping[str, Any]],
) -> SelectionPressureSnapshot:
    related_attempts = [dict(row) for row in attempts if _text(row.get("experiment_id")) == _text(experiment_id)]
    related_runs = [dict(row) for row in runs if _text(row.get("experiment_id")) == _text(experiment_id)]
    baseline_comparisons = sum(len(row.get("baseline_metrics") or {}) for row in related_runs)
    robustness_variants = sum(len(row.get("robustness") or {}) for row in related_runs)
    observed_screens = len(related_attempts) + baseline_comparisons + robustness_variants
    risk = "LOW" if observed_screens <= 5 else "MODERATE" if observed_screens <= 15 else "HIGH"
    payload = {
        "question_id": question_id, "experiment_id": experiment_id,
        "attempt_ids": sorted(_text(row.get("attempt_id")) for row in related_attempts),
        "run_ids": sorted(_text(row.get("run_id")) for row in related_runs),
    }
    return SelectionPressureSnapshot(
        snapshot_id=_stable_id("SELECTION", payload),
        created_at=_now_iso(),
        question_id=_text(question_id),
        experiment_id=_text(experiment_id),
        total_attempts=len(related_attempts),
        completed_runs=len(related_runs),
        unique_run_signatures=len({_text(row.get("run_signature")) or _text(row.get("run_id")) for row in related_runs}),
        unique_evidence_units=len({_text(row.get("evidence_unit_id")) or _text(row.get("run_id")) for row in related_runs}),
        unique_data_fingerprints=len({_text(row.get("data_fingerprint")) for row in related_runs if _text(row.get("data_fingerprint"))}),
        unique_observables=len({_text(row.get("observable_id")) for row in related_runs if _text(row.get("observable_id"))}),
        baseline_comparisons=baseline_comparisons,
        robustness_variants=robustness_variants,
        observed_screens=observed_screens,
        selection_risk=risk,
        warnings=(
            "Every attempt is counted, including reruns with an identical signature.",
            "Theory weighting must use unique evidence units so repeated execution cannot manufacture independent evidence.",
        ),
    )


def build_reproducibility_capsule(
    *,
    run: Any,
    attempt: Any,
    contract: Any,
    manifest: Any,
    code_digest: str,
    source_refs: Iterable[str] = (),
) -> ReproducibilityCapsule:
    run_row = _row(run)
    attempt_row = _row(attempt)
    contract_row = _row(contract)
    manifest_row = _row(manifest)
    blockers: list[str] = []
    if _text(run_row.get("experiment_id")) != _text(attempt_row.get("experiment_id")):
        blockers.append("Run and attempt experiment IDs do not align.")
    if not _text(run_row.get("attempt_id")) or _text(run_row.get("attempt_id")) != _text(attempt_row.get("attempt_id")):
        blockers.append("Run and attempt identities do not align.")
    if not _text(run_row.get("run_signature")) or _text(run_row.get("run_signature")) != _text(attempt_row.get("run_signature")):
        blockers.append("Run and attempt protocol signatures do not align.")
    if not _text(run_row.get("evidence_unit_id")) or _text(run_row.get("evidence_unit_id")) != _text(attempt_row.get("evidence_unit_id")):
        blockers.append("Run and attempt evidence-unit identities do not align.")
    if _text(attempt_row.get("contract_id")) != _text(contract_row.get("contract_id")):
        blockers.append("Attempt and data contract IDs do not align.")
    if _text(attempt_row.get("manifest_id")) != _text(manifest_row.get("manifest_id")):
        blockers.append("Attempt and dataset manifest IDs do not align.")
    if _text(run_row.get("data_contract_id")) != _text(contract_row.get("contract_id")):
        blockers.append("Run does not reference the selected data contract.")
    if _text(run_row.get("dataset_manifest_id")) != _text(manifest_row.get("manifest_id")):
        blockers.append("Run does not reference the selected dataset manifest.")
    if _text(run_row.get("observable_id")) != _text(contract_row.get("observable_id")):
        blockers.append("Run observable does not match the data contract.")
    if _text(run_row.get("data_fingerprint")) != _text(manifest_row.get("materialized_fingerprint")):
        blockers.append("Run data fingerprint does not match the materialized dataset manifest.")
    if not _text(run_row.get("forecast_trace_fingerprint")):
        blockers.append("Forecast trace fingerprint is missing.")
    if not _text(code_digest):
        blockers.append("Executor code digest is missing.")
    replay_grade = "EXACT" if not blockers and _text(manifest_row.get("revision_risk_status")) == "CONTROLLED" else "CONDITIONAL" if not blockers else "NON_REPLAYABLE"
    payload = {
        "run_id": run_row.get("run_id"), "attempt_id": attempt_row.get("attempt_id"),
        "contract": manifest_row.get("contract_fingerprint"), "data": run_row.get("data_fingerprint"),
        "trace": run_row.get("forecast_trace_fingerprint"), "code": _text(code_digest),
    }
    environment = {str(key): str(value) for key, value in (run_row.get("environment") or {}).items() if "key" not in str(key).lower() and "secret" not in str(key).lower() and "token" not in str(key).lower()}
    return ReproducibilityCapsule(
        capsule_id=_stable_id("CAPSULE", payload),
        created_at=_now_iso(),
        experiment_id=_text(run_row.get("experiment_id")),
        run_id=_text(run_row.get("run_id")),
        attempt_id=_text(attempt_row.get("attempt_id")),
        contract_id=_text(contract_row.get("contract_id")),
        contract_fingerprint=_text(manifest_row.get("contract_fingerprint")),
        manifest_id=_text(manifest_row.get("manifest_id")),
        data_fingerprint=_text(run_row.get("data_fingerprint")),
        forecast_trace_fingerprint=_text(run_row.get("forecast_trace_fingerprint")),
        observable_id=_text(run_row.get("observable_id")) or _text(contract_row.get("observable_id")),
        measurement_model_id=_text(contract_row.get("measurement_model_id")),
        measurement_decision_id=_text(contract_row.get("measurement_decision_id")),
        run_signature=_text(run_row.get("run_signature")) or _text(attempt_row.get("run_signature")),
        evidence_unit_id=_text(run_row.get("evidence_unit_id")) or _text(attempt_row.get("evidence_unit_id")),
        executor=_text(environment.get("executor")) or "UNKNOWN",
        executor_version=_text(run_row.get("run_protocol_version")) or "UNKNOWN",
        code_digest=_text(code_digest),
        seed=int(run_row.get("seed") or 0),
        train_size=int(run_row.get("train_size") or 0),
        test_size=int(run_row.get("test_size") or 0),
        split_timestamp=_text(manifest_row.get("split_timestamp")),
        environment=environment,
        source_refs=_clean_refs(tuple(source_refs) + tuple(contract_row.get("source_refs") or ())),
        replay_grade=replay_grade,
        status="COMPLETE" if not blockers else "INCOMPLETE",
        blockers=tuple(blockers),
        warnings=(
            "A capsule supports computational replay; it does not validate the economic measurement or causal interpretation.",
            "External data licensing and availability may still constrain exact third-party replay.",
        ),
    )
