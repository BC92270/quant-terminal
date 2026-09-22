"""Fail-closed trust guard for the frozen V3.1 dyadic-oracle artifact.

The V3.2 compiler must consume the V3.1 artifact as immutable input.  This
module deliberately depends only on the Python standard library so it can be
used before importing any scientific or compiler runtime.

Two hashes have different roles:

* ``raw_file_sha256`` authenticates the exact bytes of an artifact file when
  the caller supplies the expected digest;
* ``canonical_json_sha256`` identifies the parsed JSON independently of
  whitespace and object-key order.

The embedded V3.1 ``certificate_sha`` and ``dyadic_oracle_sha`` fields are
also recomputed with their original (legacy) JSON serialization.  They must
not be replaced by the newer canonical serialization because doing so would
rewrite the frozen parent's identity.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


ARTIFACT_GUARD_VERSION = "PHASE III · DYADIC ARTIFACT GUARD · V1"

SEALED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)

EXPECTED_DYADIC_ORACLE_VERSION = "PHASE III · EXACT DYADIC BANDS ORACLE · V1"
EXPECTED_DYADIC_ORACLE_SHA = "D9D109D117E1795CFFEF"
EXPECTED_DYADIC_SPEC_SHA = "9A6F664368F4AC592281"
EXPECTED_PHASE2_PROTOCOL_SHA = "8E5EF191FAE97A75"
EXPECTED_PHASE2_EXECUTION_SPEC_SHA = "40D3225B0AFC86BC01DD"
EXPECTED_PHASE3_PREPARATION_SPEC_SHA = "CDC693C22A3838B0B3C1"
EXPECTED_FIXED_POINT_ORACLE_SPEC_SHA = "62854F1D7076BA742775"
EXPECTED_PARENT_RAW_SHA256 = (
    "7b39a20ec9200b16996ec25edd660ba7bf26bfb2b454ed44dd1a333513afd50e"
)

EXPECTED_FIDELITY_STATUS = "EXACT DYADIC FAMILY PASS · BY CONSTRUCTION"
EXPECTED_CERTIFICATE_STATUS = "EXACT DYADIC PARAMETERIZATION PASS"
EXPECTED_FIXED_POINT_STATUS = "8/12/16 APPROXIMATE FIXED-POINT LADDER FALSIFIED"
EXPECTED_COMPILER_STATUS = "LOGICAL DYADIC IR ONLY · GATE-LEVEL COMPILER NOT YET SEALED"

EXPECTED_FAMILY = {
    "N": 40,
    "Regime": "BANDS",
    "seeds": list(SEALED_SEEDS),
}

EXPECTED_RESOURCE_SUMMARY = {
    "logical_qubits_sequential_reuse_max": 151,
    "logical_qubits_parallel_envelope_max": 336,
    "max_factor_accumulator_bits": 68,
    "max_dyadic_denominator_exponent": 63,
    "controlled_add_operations_max": 160,
    "integer_comparisons": 14,
}

_TOP_LEVEL_KEYS = frozenset(
    {
        "compiler_status",
        "created_utc",
        "dyadic_oracle_sha",
        "dyadic_oracle_version",
        "dyadic_spec_sha",
        "family",
        "fidelity_status",
        "hardware_executable",
        "phase2_execution_spec_sha",
        "phase2_protocol_sha",
        "phase3_preparation_spec_sha",
        "resource_blueprints",
        "resource_summary",
        "reversible_schedule",
        "seed_certificates",
        "semantic_contract",
        "source_fixed_point_oracle_spec_sha",
        "v3_fixed_point_ladder_status",
    }
)

_CERTIFICATE_REQUIRED_KEYS = frozenset(
    {
        "K",
        "N",
        "certificate_sha",
        "created_utc",
        "dyadic_spec_sha",
        "factor_bands",
        "group_bands",
        "instance_id",
        "parameter_identity_count",
        "parameter_identity_pass",
        "parameter_identity_total",
        "roundoff_diagnostics",
        "seed",
        "semantic_note",
        "status",
        "universal_algebraic_equivalence",
        "witness_dyadic_feasible",
        "witness_phase2_tolerant_feasible",
        "witness_strict_float_feasible",
    }
)

_RESOURCE_REQUIRED_KEYS = frozenset(
    {
        "band_flags",
        "clean_uncompute_required",
        "controlled_add_operations",
        "data_qubits",
        "factor_accumulator_widths",
        "factor_common_denominator_exponents",
        "group_counter_widths",
        "integer_comparisons",
        "max_factor_common_denominator_exponent",
        "parallel_register_logical_qubits",
        "seed",
        "sequential_reuse_logical_qubits",
    }
)


class _DuplicateJsonKey(ValueError):
    """Raised internally when a JSON object contains a repeated key."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _canonical_json_bytes(payload: Any) -> bytes:
    """Return the V3.2 canonical UTF-8 JSON encoding for *payload*.

    ``allow_nan=False`` makes the operation fail closed for Python payloads
    containing non-JSON floating-point values.
    """

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(payload: Any) -> str:
    """Return the lowercase SHA-256 of the V3.2 canonical JSON encoding."""

    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _legacy_json_bytes(payload: Any) -> bytes:
    """Reproduce the exact V3.1 ``_stable_json`` serialization."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _legacy_sha256(payload: Any) -> str:
    return hashlib.sha256(_legacy_json_bytes(payload)).hexdigest()


def _legacy_sha20(payload: Any) -> str:
    return _legacy_sha256(payload)[:20].upper()


def _without_top_level(payload: Mapping[str, Any], excluded: set[str]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in excluded}


def _strict_int(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def _strict_int_list(value: Any, *, length: int | None = None) -> bool:
    if not isinstance(value, list):
        return False
    if length is not None and len(value) != length:
        return False
    return all(type(item) is int for item in value)


def _safe_seed_list(records: Any) -> list[Any]:
    if not isinstance(records, list):
        return []
    return [record.get("seed") if isinstance(record, dict) else None for record in records]


def _unique_count(values: Any) -> int | None:
    """Return a uniqueness count, or ``None`` for non-list/unhashable input."""

    if not isinstance(values, list):
        return None
    try:
        return len(set(values))
    except TypeError:
        return None


def _record_check(
    report: dict[str, Any],
    name: str,
    passed: bool,
    *,
    expected: Any = None,
    actual: Any = None,
    detail: str | None = None,
) -> None:
    """Append one deterministic boolean check and its bounded diagnostic."""

    report["checks"][name] = bool(passed)
    diagnostic: dict[str, Any] = {}
    if expected is not None:
        diagnostic["expected"] = expected
    if actual is not None:
        diagnostic["actual"] = actual
    if detail is not None:
        diagnostic["detail"] = detail
    if diagnostic:
        report["check_details"][name] = diagnostic


def _finish_report(report: dict[str, Any]) -> dict[str, Any]:
    report["failed_checks"] = [
        name for name, passed in report["checks"].items() if not passed
    ]
    report["valid"] = bool(
        report["checks"]
        and all(report["checks"].values())
        and not report["errors"]
    )
    return report


def _new_report(source_kind: str) -> dict[str, Any]:
    return {
        "guard_version": ARTIFACT_GUARD_VERSION,
        "valid": False,
        "source": {"kind": source_kind},
        "checks": {},
        "check_details": {},
        "failed_checks": [],
        "errors": [],
        "hashes": {
            "raw_file_sha256": None,
            "expected_raw_file_sha256": None,
            "canonical_json_sha256": None,
            "canonical_content_sha256": None,
            "legacy_canonical_content_sha256": None,
            "stored_dyadic_oracle_sha": None,
            "computed_dyadic_oracle_sha": None,
            "certificate_sha": [],
        },
        "observed": {
            "family": None,
            "certificate_seeds": [],
            "resource_seeds": [],
            "resource_summary": None,
            "recomputed_resource_summary": None,
        },
    }


def _family_is_exact(family: Any) -> bool:
    return bool(
        isinstance(family, dict)
        and set(family) == set(EXPECTED_FAMILY)
        and _strict_int(family.get("N"), 40)
        and family.get("Regime") == "BANDS"
        and _strict_int_list(family.get("seeds"), length=8)
        and family.get("seeds") == list(SEALED_SEEDS)
    )


def _certificate_shape_and_identity(certificate: Any, expected_seed: int) -> bool:
    if not isinstance(certificate, dict):
        return False
    if not _CERTIFICATE_REQUIRED_KEYS.issubset(certificate):
        return False
    if not (
        _strict_int(certificate.get("N"), 40)
        and _strict_int(certificate.get("K"), 10)
        and _strict_int(certificate.get("seed"), expected_seed)
        and certificate.get("instance_id") == f"QH-N040-BANDS-S{expected_seed}"
        and certificate.get("dyadic_spec_sha") == EXPECTED_DYADIC_SPEC_SHA
        and isinstance(certificate.get("created_utc"), str)
        and bool(certificate.get("created_utc"))
    ):
        return False

    groups = certificate.get("group_bands")
    factors = certificate.get("factor_bands")
    if not (isinstance(groups, list) and len(groups) == 4):
        return False
    if not (isinstance(factors, list) and len(factors) == 3):
        return False

    all_group_indices: list[int] = []
    for index, group in enumerate(groups, start=1):
        if not isinstance(group, dict):
            return False
        indices = group.get("indices")
        if not (
            group.get("name") == f"GROUP_{index}"
            and _strict_int_list(indices, length=10)
            and _strict_int(group.get("counter_bits"), 4)
            and type(group.get("lower")) is int
            and type(group.get("upper")) is int
            and 0 <= group["lower"] <= group["upper"] <= 10
        ):
            return False
        all_group_indices.extend(indices)
    if sorted(all_group_indices) != list(range(40)):
        return False

    identity_count = 0
    identity_total = 0
    for index, factor in enumerate(factors, start=1):
        if not isinstance(factor, dict):
            return False
        coefficients = factor.get("coefficients_int")
        source_hex = factor.get("source_float_hex")
        if not (
            factor.get("name") == f"FACTOR_{index}"
            and _strict_int_list(coefficients, length=40)
            and isinstance(source_hex, list)
            and len(source_hex) == 42
            and all(isinstance(value, str) for value in source_hex)
            and factor.get("parameter_identity_pass") is True
            and _strict_int(factor.get("parameter_identity_count"), 42)
            and _strict_int(factor.get("parameter_identity_total"), 42)
            and type(factor.get("common_denominator_exponent")) is int
            and factor["common_denominator_exponent"] >= 0
            and type(factor.get("accumulator_signed_bits")) is int
            and factor["accumulator_signed_bits"] > 0
        ):
            return False
        identity_count += factor["parameter_identity_count"]
        identity_total += factor["parameter_identity_total"]

    return bool(
        identity_count == 126
        and identity_total == 126
        and certificate.get("parameter_identity_pass") is True
        and _strict_int(certificate.get("parameter_identity_count"), 126)
        and _strict_int(certificate.get("parameter_identity_total"), 126)
    )


def _certificate_status_is_exact(certificate: Any) -> bool:
    return bool(
        isinstance(certificate, dict)
        and certificate.get("status") == EXPECTED_CERTIFICATE_STATUS
        and certificate.get("universal_algebraic_equivalence") is True
        and certificate.get("witness_strict_float_feasible") is True
        and certificate.get("witness_dyadic_feasible") is True
        and certificate.get("witness_phase2_tolerant_feasible") is True
    )


def _expected_resource_from_certificate(certificate: Mapping[str, Any]) -> dict[str, Any]:
    groups = certificate["group_bands"]
    factors = certificate["factor_bands"]
    count_widths = [int(group["counter_bits"]) for group in groups]
    accumulator_widths = [int(factor["accumulator_signed_bits"]) for factor in factors]
    denominator_exponents = [
        int(factor["common_denominator_exponent"]) for factor in factors
    ]
    flags = len(count_widths) + len(accumulator_widths)
    max_work = max(count_widths + accumulator_widths + [1])
    comparator_work = max(3, int(math.ceil(max_work / 2)))
    data_qubits = int(certificate["N"])
    return {
        "seed": int(certificate["seed"]),
        "data_qubits": data_qubits,
        "group_counter_widths": count_widths,
        "factor_accumulator_widths": accumulator_widths,
        "factor_common_denominator_exponents": denominator_exponents,
        "max_factor_common_denominator_exponent": max(denominator_exponents),
        "band_flags": flags,
        "controlled_add_operations": (
            data_qubits * len(accumulator_widths)
            + sum(len(group["indices"]) for group in groups)
        ),
        "integer_comparisons": 2 * flags,
        "sequential_reuse_logical_qubits": (
            data_qubits + max_work + comparator_work + flags + 2
        ),
        "parallel_register_logical_qubits": (
            data_qubits
            + sum(count_widths)
            + sum(accumulator_widths)
            + 2 * flags
            + max_work
            + 2
        ),
        "clean_uncompute_required": True,
    }


def _resource_matches_certificate(resource: Any, certificate: Any) -> bool:
    if not isinstance(resource, dict) or not isinstance(certificate, dict):
        return False
    if not _RESOURCE_REQUIRED_KEYS.issubset(resource):
        return False
    try:
        expected = _expected_resource_from_certificate(certificate)
    except (KeyError, TypeError, ValueError):
        return False
    scalar_keys = (
        "seed",
        "data_qubits",
        "max_factor_common_denominator_exponent",
        "band_flags",
        "controlled_add_operations",
        "integer_comparisons",
        "sequential_reuse_logical_qubits",
        "parallel_register_logical_qubits",
    )
    list_keys = (
        "group_counter_widths",
        "factor_accumulator_widths",
        "factor_common_denominator_exponents",
    )
    return bool(
        all(resource.get(key) == value for key, value in expected.items())
        and all(type(resource.get(key)) is int for key in scalar_keys)
        and all(
            _strict_int_list(resource.get(key), length=len(expected[key]))
            for key in list_keys
        )
        and resource.get("clean_uncompute_required") is True
    )


def _recompute_resource_summary(resources: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "logical_qubits_sequential_reuse_max": max(
            int(resource["sequential_reuse_logical_qubits"]) for resource in resources
        ),
        "logical_qubits_parallel_envelope_max": max(
            int(resource["parallel_register_logical_qubits"]) for resource in resources
        ),
        "max_factor_accumulator_bits": max(
            max(int(width) for width in resource["factor_accumulator_widths"])
            for resource in resources
        ),
        "max_dyadic_denominator_exponent": max(
            int(resource["max_factor_common_denominator_exponent"])
            for resource in resources
        ),
        "controlled_add_operations_max": max(
            int(resource["controlled_add_operations"]) for resource in resources
        ),
        "integer_comparisons": max(
            int(resource["integer_comparisons"]) for resource in resources
        ),
    }


def validate_dyadic_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a parsed V3.1 sealed dyadic-oracle payload.

    The function never trusts stored status or digest fields in isolation.  It
    returns a deterministic report and sets ``valid`` only when every recorded
    check passes.  Malformed or non-canonicalizable inputs are reported as
    invalid instead of raising.

    Raw-byte identity cannot be established from an already parsed mapping;
    use :func:`load_and_validate_dyadic_artifact` for that check.
    """

    report = _new_report("payload")
    payload_is_object = isinstance(payload, dict)
    _record_check(
        report,
        "payload_is_json_object",
        payload_is_object,
        expected="dict",
        actual=type(payload).__name__,
    )
    if not payload_is_object:
        return _finish_report(report)

    try:
        canonical_bytes = _canonical_json_bytes(payload)
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        report["errors"].append(
            {"code": "CANONICAL_JSON_ERROR", "message": str(exc)}
        )
        _record_check(
            report,
            "canonical_json_serializable",
            False,
            detail="Payload is outside the strict JSON data model.",
        )
        return _finish_report(report)

    _record_check(report, "canonical_json_serializable", True)
    report["hashes"]["canonical_json_sha256"] = hashlib.sha256(
        canonical_bytes
    ).hexdigest()

    top_level_schema_ok = set(payload) == _TOP_LEVEL_KEYS
    _record_check(
        report,
        "top_level_schema_exact",
        top_level_schema_ok,
        expected=sorted(_TOP_LEVEL_KEYS),
        actual=sorted(str(key) for key in payload),
    )

    for field, expected in (
        ("dyadic_oracle_version", EXPECTED_DYADIC_ORACLE_VERSION),
        ("dyadic_spec_sha", EXPECTED_DYADIC_SPEC_SHA),
        ("phase2_protocol_sha", EXPECTED_PHASE2_PROTOCOL_SHA),
        ("phase2_execution_spec_sha", EXPECTED_PHASE2_EXECUTION_SPEC_SHA),
        ("phase3_preparation_spec_sha", EXPECTED_PHASE3_PREPARATION_SPEC_SHA),
        (
            "source_fixed_point_oracle_spec_sha",
            EXPECTED_FIXED_POINT_ORACLE_SPEC_SHA,
        ),
    ):
        _record_check(
            report,
            f"parent_{field}",
            payload.get(field) == expected,
            expected=expected,
            actual=payload.get(field),
        )

    family = payload.get("family")
    report["observed"]["family"] = family if isinstance(family, dict) else None
    _record_check(
        report,
        "family_exact",
        _family_is_exact(family),
        expected=EXPECTED_FAMILY,
        actual=family,
    )
    family_seeds = family.get("seeds") if isinstance(family, dict) else None
    _record_check(
        report,
        "family_seed_order_exact",
        isinstance(family_seeds, list) and family_seeds == list(SEALED_SEEDS),
        expected=list(SEALED_SEEDS),
        actual=family_seeds,
    )
    _record_check(
        report,
        "family_seeds_unique",
        isinstance(family_seeds, list)
        and _unique_count(family_seeds) == len(family_seeds),
        expected=8,
        actual=_unique_count(family_seeds),
    )

    _record_check(
        report,
        "fidelity_status_exact",
        payload.get("fidelity_status") == EXPECTED_FIDELITY_STATUS,
        expected=EXPECTED_FIDELITY_STATUS,
        actual=payload.get("fidelity_status"),
    )
    _record_check(
        report,
        "hardware_executable_is_false",
        payload.get("hardware_executable") is False,
        expected=False,
        actual=payload.get("hardware_executable"),
    )
    _record_check(
        report,
        "compiler_boundary_preserved",
        payload.get("compiler_status") == EXPECTED_COMPILER_STATUS,
        expected=EXPECTED_COMPILER_STATUS,
        actual=payload.get("compiler_status"),
    )
    _record_check(
        report,
        "fixed_point_falsification_preserved",
        payload.get("v3_fixed_point_ladder_status") == EXPECTED_FIXED_POINT_STATUS,
        expected=EXPECTED_FIXED_POINT_STATUS,
        actual=payload.get("v3_fixed_point_ladder_status"),
    )
    _record_check(
        report,
        "top_level_created_utc_present",
        isinstance(payload.get("created_utc"), str) and bool(payload.get("created_utc")),
        expected="non-empty string",
        actual=payload.get("created_utc"),
    )

    certificates = payload.get("seed_certificates")
    certificates_is_list = isinstance(certificates, list)
    certificate_seeds = _safe_seed_list(certificates)
    report["observed"]["certificate_seeds"] = certificate_seeds
    _record_check(
        report,
        "certificate_count_exact",
        certificates_is_list and len(certificates) == 8,
        expected=8,
        actual=len(certificates) if certificates_is_list else None,
    )
    _record_check(
        report,
        "certificate_seed_order_exact",
        certificate_seeds == list(SEALED_SEEDS),
        expected=list(SEALED_SEEDS),
        actual=certificate_seeds,
    )
    _record_check(
        report,
        "certificate_seeds_unique",
        len(certificate_seeds) == 8 and _unique_count(certificate_seeds) == 8,
        expected=8,
        actual=_unique_count(certificate_seeds),
    )

    certificate_shape_passes: list[bool] = []
    certificate_status_passes: list[bool] = []
    certificate_hash_passes: list[bool] = []
    certificate_ids: list[Any] = []
    certificate_hash_rows: list[dict[str, Any]] = []
    for index, expected_seed in enumerate(SEALED_SEEDS):
        certificate = (
            certificates[index]
            if certificates_is_list and index < len(certificates)
            else None
        )
        certificate_shape_passes.append(
            _certificate_shape_and_identity(certificate, expected_seed)
        )
        certificate_status_passes.append(_certificate_status_is_exact(certificate))
        certificate_ids.append(
            certificate.get("instance_id") if isinstance(certificate, dict) else None
        )
        stored_sha = (
            certificate.get("certificate_sha")
            if isinstance(certificate, dict)
            else None
        )
        computed_sha = None
        if isinstance(certificate, dict):
            try:
                computed_sha = _legacy_sha20(
                    _without_top_level(
                        certificate, {"created_utc", "certificate_sha"}
                    )
                )
            except (TypeError, ValueError, OverflowError, RecursionError):
                computed_sha = None
        sha_matches = bool(
            isinstance(stored_sha, str)
            and computed_sha is not None
            and hmac.compare_digest(stored_sha, computed_sha)
        )
        certificate_hash_passes.append(sha_matches)
        certificate_hash_rows.append(
            {
                "index": index,
                "seed": certificate_seeds[index]
                if index < len(certificate_seeds)
                else None,
                "stored": stored_sha,
                "computed": computed_sha,
                "matches": sha_matches,
            }
        )
    report["hashes"]["certificate_sha"] = certificate_hash_rows

    _record_check(
        report,
        "certificate_identity_126_of_126",
        len(certificate_shape_passes) == 8 and all(certificate_shape_passes),
        expected=[True] * 8,
        actual=certificate_shape_passes,
    )
    _record_check(
        report,
        "certificate_fidelity_exact",
        len(certificate_status_passes) == 8 and all(certificate_status_passes),
        expected=[True] * 8,
        actual=certificate_status_passes,
    )
    _record_check(
        report,
        "certificate_hashes_recomputed",
        len(certificate_hash_passes) == 8 and all(certificate_hash_passes),
        expected=[True] * 8,
        actual=certificate_hash_passes,
    )
    stored_certificate_hashes = [
        row["stored"] for row in certificate_hash_rows if isinstance(row["stored"], str)
    ]
    _record_check(
        report,
        "certificate_hashes_unique",
        len(stored_certificate_hashes) == 8
        and len(set(stored_certificate_hashes)) == 8,
        expected=8,
        actual=len(set(stored_certificate_hashes)),
    )
    _record_check(
        report,
        "certificate_instance_ids_unique",
        len(certificate_ids) == 8
        and all(isinstance(value, str) for value in certificate_ids)
        and len(set(certificate_ids)) == 8,
        expected=8,
        actual=len(set(certificate_ids)),
    )

    resources = payload.get("resource_blueprints")
    resources_is_list = isinstance(resources, list)
    resource_seeds = _safe_seed_list(resources)
    report["observed"]["resource_seeds"] = resource_seeds
    _record_check(
        report,
        "resource_blueprint_count_exact",
        resources_is_list and len(resources) == 8,
        expected=8,
        actual=len(resources) if resources_is_list else None,
    )
    _record_check(
        report,
        "resource_seed_order_exact",
        resource_seeds == list(SEALED_SEEDS),
        expected=list(SEALED_SEEDS),
        actual=resource_seeds,
    )
    _record_check(
        report,
        "resource_seeds_unique",
        len(resource_seeds) == 8 and _unique_count(resource_seeds) == 8,
        expected=8,
        actual=_unique_count(resource_seeds),
    )

    resource_consistency: list[bool] = []
    if resources_is_list and certificates_is_list:
        for index in range(8):
            resource = resources[index] if index < len(resources) else None
            certificate = certificates[index] if index < len(certificates) else None
            resource_consistency.append(
                _resource_matches_certificate(resource, certificate)
            )
    _record_check(
        report,
        "resource_blueprints_match_certificates",
        len(resource_consistency) == 8 and all(resource_consistency),
        expected=[True] * 8,
        actual=resource_consistency,
    )

    resource_summary = payload.get("resource_summary")
    report["observed"]["resource_summary"] = (
        resource_summary if isinstance(resource_summary, dict) else None
    )
    resource_summary_exact = bool(
        isinstance(resource_summary, dict)
        and set(resource_summary) == set(EXPECTED_RESOURCE_SUMMARY)
        and all(
            _strict_int(resource_summary.get(key), expected)
            for key, expected in EXPECTED_RESOURCE_SUMMARY.items()
        )
    )
    _record_check(
        report,
        "resource_summary_exact",
        resource_summary_exact,
        expected=EXPECTED_RESOURCE_SUMMARY,
        actual=resource_summary,
    )

    recomputed_resource_summary = None
    if len(resource_consistency) == 8 and all(resource_consistency):
        try:
            recomputed_resource_summary = _recompute_resource_summary(resources)
        except (KeyError, TypeError, ValueError):
            recomputed_resource_summary = None
    report["observed"]["recomputed_resource_summary"] = recomputed_resource_summary
    _record_check(
        report,
        "resource_summary_recomputed",
        recomputed_resource_summary == EXPECTED_RESOURCE_SUMMARY
        and recomputed_resource_summary == resource_summary,
        expected=EXPECTED_RESOURCE_SUMMARY,
        actual=recomputed_resource_summary,
    )

    legacy_content = _without_top_level(
        payload, {"created_utc", "dyadic_oracle_sha"}
    )
    try:
        computed_oracle_sha = _legacy_sha20(legacy_content)
        report["hashes"]["legacy_canonical_content_sha256"] = _legacy_sha256(
            legacy_content
        )
        report["hashes"]["canonical_content_sha256"] = canonical_json_sha256(
            legacy_content
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        computed_oracle_sha = None
    stored_oracle_sha = payload.get("dyadic_oracle_sha")
    report["hashes"]["stored_dyadic_oracle_sha"] = stored_oracle_sha
    report["hashes"]["computed_dyadic_oracle_sha"] = computed_oracle_sha
    _record_check(
        report,
        "dyadic_oracle_sha_recomputed",
        isinstance(stored_oracle_sha, str)
        and computed_oracle_sha is not None
        and hmac.compare_digest(stored_oracle_sha, computed_oracle_sha),
        expected=computed_oracle_sha,
        actual=stored_oracle_sha,
    )
    _record_check(
        report,
        "dyadic_oracle_sha_frozen_parent",
        stored_oracle_sha == EXPECTED_DYADIC_ORACLE_SHA,
        expected=EXPECTED_DYADIC_ORACLE_SHA,
        actual=stored_oracle_sha,
    )

    return _finish_report(report)


def _load_error_report(
    path: Any,
    *,
    code: str,
    message: str,
    expected_raw_sha256: str | None,
    raw_sha256: str | None = None,
) -> dict[str, Any]:
    report = _new_report("path")
    report["source"]["path"] = str(path)
    report["hashes"]["raw_file_sha256"] = raw_sha256
    report["hashes"]["expected_raw_file_sha256"] = expected_raw_sha256
    report["errors"].append({"code": code, "message": message})
    _record_check(report, "file_readable", code != "FILE_READ_ERROR")
    _record_check(report, "json_decodable_with_unique_keys", False)
    return _finish_report(report)


def load_and_validate_dyadic_artifact(
    path: str | Path,
    expected_raw_sha256: str | None = None,
) -> dict[str, Any]:
    """Read and validate a V3.1 dyadic artifact without modifying it.

    Args:
        path: JSON artifact path.
        expected_raw_sha256: Optional 64-hex SHA-256 for exact byte identity.
            When omitted, the raw digest is still reported but does not gate
            semantic validity.  V3.2 callers should pass the digest frozen in
            their compiler specification (available here as
            :data:`EXPECTED_PARENT_RAW_SHA256`).

    Returns:
        A deterministic validation report.  Read errors, invalid UTF-8,
        duplicate JSON object keys, non-standard numeric constants, malformed
        payloads, and digest mismatches all produce ``valid=False``.
    """

    try:
        artifact_path = Path(path)
        raw = artifact_path.read_bytes()
    except (OSError, TypeError, ValueError) as exc:
        return _load_error_report(
            path,
            code="FILE_READ_ERROR",
            message=str(exc),
            expected_raw_sha256=expected_raw_sha256,
        )

    raw_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJsonKey, ValueError) as exc:
        return _load_error_report(
            artifact_path,
            code="JSON_DECODE_ERROR",
            message=str(exc),
            expected_raw_sha256=expected_raw_sha256,
            raw_sha256=raw_sha256,
        )

    report = validate_dyadic_payload(payload)
    report["source"] = {"kind": "path", "path": str(artifact_path)}
    report["hashes"]["raw_file_sha256"] = raw_sha256
    report["hashes"]["expected_raw_file_sha256"] = expected_raw_sha256

    loader_checks: dict[str, bool] = {
        "file_readable": True,
        "json_decodable_with_unique_keys": True,
        "raw_file_sha256_computed": len(raw_sha256) == 64,
    }
    loader_details: dict[str, Any] = {
        "raw_file_sha256_computed": {"actual": raw_sha256}
    }

    if expected_raw_sha256 is not None:
        expected_is_well_formed = bool(
            isinstance(expected_raw_sha256, str)
            and len(expected_raw_sha256) == 64
            and all(character in "0123456789abcdefABCDEF" for character in expected_raw_sha256)
        )
        loader_checks["expected_raw_sha256_well_formed"] = expected_is_well_formed
        loader_details["expected_raw_sha256_well_formed"] = {
            "expected": "64 hexadecimal characters",
            "actual": expected_raw_sha256,
        }
        raw_matches = bool(
            expected_is_well_formed
            and hmac.compare_digest(raw_sha256, expected_raw_sha256.lower())
        )
        loader_checks["raw_file_sha256_matches_expected"] = raw_matches
        loader_details["raw_file_sha256_matches_expected"] = {
            "expected": expected_raw_sha256.lower()
            if isinstance(expected_raw_sha256, str)
            else expected_raw_sha256,
            "actual": raw_sha256,
        }

    report["checks"] = {**loader_checks, **report["checks"]}
    report["check_details"] = {**loader_details, **report["check_details"]}
    return _finish_report(report)


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed validation of a frozen V3.1 dyadic artifact."
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--expected-raw-sha256")
    args = parser.parse_args(argv)
    report = load_and_validate_dyadic_artifact(
        args.artifact, expected_raw_sha256=args.expected_raw_sha256
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":  # pragma: no cover - exercised as a CLI smoke test.
    raise SystemExit(_main())
