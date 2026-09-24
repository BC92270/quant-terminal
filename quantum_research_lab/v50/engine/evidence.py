"""Strict offline normalization for the V5.0 historical evidence cohort."""

from __future__ import annotations

import base64
from collections import deque
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


SOURCE_CATALOG = Path("quantum_research_lab/v50/evidence/SOURCES.json")
EXPECTED_BASIS = ("cz", "id", "rz", "sx", "x")
EXPECTED_FAMILY = "Heron"
EXPECTED_REVISION = "2"
EXPECTED_QUBITS = 156
EXPECTED_DIRECTED_COUPLINGS = 352
EXPECTED_TOPOLOGY_SHA256 = "c046a8055488d506935a65d193d209da5b0c891a8b54f59361c7f7b30fed7fcf"


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json_strict(path: Path, *, decimal_numbers: bool = False) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "object_pairs_hook": _strict_pairs,
        "parse_constant": lambda token: (_ for _ in ()).throw(ValueError(token)),
    }
    if decimal_numbers:
        kwargs["parse_float"] = Decimal
    payload = json.loads(path.read_text(encoding="utf-8"), **kwargs)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def raw_file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("Non-finite decimal in evidence")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return {"$decimal": _decimal_text(value)}
    if isinstance(value, Mapping):
        return {str(key): _canonicalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    if isinstance(value, tuple):
        return [_canonicalize(item) for item in value]
    return value


def semantic_sha256(payload: Mapping[str, Any], *, exclude: Iterable[str] = ()) -> str:
    excluded = set(exclude)
    body = {key: value for key, value in payload.items() if key not in excluded}
    encoded = json.dumps(
        _canonicalize(body),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _regular(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Evidence must be a regular file: {relative}")
    return path


def _record_digest(raw_sha256: str) -> str:
    return base64.urlsafe_b64encode(bytes.fromhex(raw_sha256)).decode("ascii").rstrip("=")


def _parameter_map(parameters: Any, *, context: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(parameters, list):
        raise ValueError(f"Missing parameter list: {context}")
    result: dict[str, Mapping[str, Any]] = {}
    for item in parameters:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            raise ValueError(f"Malformed parameter: {context}")
        name = str(item["name"])
        if name in result:
            raise ValueError(f"Duplicate parameter {name}: {context}")
        result[name] = item
    return result


def _decimal_parameter(
    parameters: Mapping[str, Mapping[str, Any]], name: str, *, unit: str, context: str
) -> Decimal:
    item = parameters.get(name)
    if item is None or item.get("unit") != unit:
        raise ValueError(f"Missing {name} [{unit}]: {context}")
    value = item.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValueError(f"Non-numeric {name}: {context}")
    decimal = value if isinstance(value, Decimal) else Decimal(value)
    if not decimal.is_finite():
        raise ValueError(f"Non-finite {name}: {context}")
    return decimal


def _component_sizes(num_qubits: int, edges: Iterable[tuple[int, int]]) -> list[int]:
    adjacency = [set() for _ in range(num_qubits)]
    for source, target in edges:
        adjacency[source].add(target)
        adjacency[target].add(source)
    unseen = set(range(num_qubits))
    sizes: list[int] = []
    while unseen:
        start = min(unseen)
        queue: deque[int] = deque([start])
        unseen.remove(start)
        size = 0
        while queue:
            node = queue.popleft()
            size += 1
            for neighbor in sorted(adjacency[node]):
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    queue.append(neighbor)
        sizes.append(size)
    return sorted(sizes, reverse=True)


def _topology_sha256(coupling_map: list[list[int]]) -> str:
    encoded = json.dumps(
        sorted(coupling_map), separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_snapshot(
    root: Path,
    source: Mapping[str, Any],
    distributions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    version = str(source.get("distribution_version"))
    distribution = distributions.get(version)
    if distribution is None:
        raise ValueError(f"Unknown distribution version: {version}")

    configuration_path = _regular(root, str(source["configuration_path"]))
    properties_path = _regular(root, str(source["properties_path"]))
    configuration_raw = raw_file_sha256(configuration_path)
    properties_raw = raw_file_sha256(properties_path)
    if configuration_raw != source.get("configuration_raw_sha256"):
        raise ValueError(f"Configuration raw identity mismatch: {source.get('snapshot_id')}")
    if properties_raw != source.get("properties_raw_sha256"):
        raise ValueError(f"Properties raw identity mismatch: {source.get('snapshot_id')}")
    if configuration_path.stat().st_size != int(source.get("configuration_size", -1)):
        raise ValueError(f"Configuration size mismatch: {source.get('snapshot_id')}")
    if properties_path.stat().st_size != int(source.get("properties_size", -1)):
        raise ValueError(f"Properties size mismatch: {source.get('snapshot_id')}")
    if _record_digest(configuration_raw) != source.get(
        "configuration_record_sha256_urlsafe_b64"
    ):
        raise ValueError(f"Configuration RECORD identity mismatch: {source.get('snapshot_id')}")
    if _record_digest(properties_raw) != source.get("properties_record_sha256_urlsafe_b64"):
        raise ValueError(f"Properties RECORD identity mismatch: {source.get('snapshot_id')}")

    configuration = read_json_strict(configuration_path, decimal_numbers=True)
    properties = read_json_strict(properties_path, decimal_numbers=True)
    backend_name = str(source.get("backend_name"))
    backend_version = str(source.get("backend_version"))
    source_epoch = str(source.get("source_epoch"))
    if configuration.get("backend_name") != backend_name:
        raise ValueError(f"Configuration backend mismatch: {source.get('snapshot_id')}")
    if properties.get("backend_name") != backend_name:
        raise ValueError(f"Properties backend mismatch: {source.get('snapshot_id')}")
    if configuration.get("backend_version") != backend_version:
        raise ValueError(f"Configuration version mismatch: {source.get('snapshot_id')}")
    if properties.get("backend_version") != backend_version:
        raise ValueError(f"Properties version mismatch: {source.get('snapshot_id')}")
    if properties.get("last_update_date") != source_epoch:
        raise ValueError(f"Properties epoch mismatch: {source.get('snapshot_id')}")

    processor = configuration.get("processor_type")
    if not isinstance(processor, Mapping):
        raise ValueError("Processor type is absent")
    family = str(processor.get("family"))
    revision = str(processor.get("revision"))
    num_qubits = int(configuration.get("n_qubits", -1))
    basis_gates = tuple(configuration.get("basis_gates") or ())
    dt_value = configuration.get("dt")
    if not isinstance(dt_value, (int, Decimal)) or isinstance(dt_value, bool):
        raise ValueError("Backend dt is non-numeric")
    dt_ns = dt_value if isinstance(dt_value, Decimal) else Decimal(dt_value)
    coupling_raw = configuration.get("coupling_map")
    if not isinstance(coupling_raw, list):
        raise ValueError("Coupling map is absent")
    coupling_map: list[list[int]] = []
    for edge in coupling_raw:
        if (
            not isinstance(edge, list)
            or len(edge) != 2
            or any(isinstance(item, bool) or not isinstance(item, int) for item in edge)
        ):
            raise ValueError("Malformed directed coupling")
        source_qubit, target_qubit = int(edge[0]), int(edge[1])
        if not (0 <= source_qubit < num_qubits and 0 <= target_qubit < num_qubits):
            raise ValueError("Coupling endpoint outside backend width")
        coupling_map.append([source_qubit, target_qubit])
    topology_sha = _topology_sha256(coupling_map)
    if (
        family != EXPECTED_FAMILY
        or revision != EXPECTED_REVISION
        or num_qubits != EXPECTED_QUBITS
        or basis_gates != EXPECTED_BASIS
        or dt_ns != Decimal("4.0")
        or len(coupling_map) != EXPECTED_DIRECTED_COUPLINGS
        or len({tuple(edge) for edge in coupling_map}) != EXPECTED_DIRECTED_COUPLINGS
        or topology_sha != EXPECTED_TOPOLOGY_SHA256
    ):
        raise ValueError(f"Pinned Heron topology contract mismatch: {source.get('snapshot_id')}")

    gates = properties.get("gates")
    if not isinstance(gates, list):
        raise ValueError("Properties gate list is absent")
    directed_quality: dict[tuple[int, int], tuple[Decimal, int, bool]] = {}
    unit_error_sentinels = 0
    nonintegral_duration_count = 0
    for index, gate in enumerate(gates):
        if not isinstance(gate, Mapping) or gate.get("gate") != "cz":
            continue
        qubits = gate.get("qubits")
        if not isinstance(qubits, list) or len(qubits) != 2:
            raise ValueError(f"Malformed CZ qubits at gate {index}")
        edge = (int(qubits[0]), int(qubits[1]))
        if edge in directed_quality:
            raise ValueError(f"Duplicate CZ property: {edge}")
        parameters = _parameter_map(gate.get("parameters"), context=f"CZ {edge}")
        error = _decimal_parameter(parameters, "gate_error", unit="", context=f"CZ {edge}")
        duration_ns = _decimal_parameter(
            parameters, "gate_length", unit="ns", context=f"CZ {edge}"
        )
        duration_ticks_decimal = duration_ns / dt_ns
        duration_integral = duration_ticks_decimal == duration_ticks_decimal.to_integral_value()
        if not duration_integral:
            nonintegral_duration_count += 1
        duration_ticks = int(duration_ticks_decimal) if duration_integral else -1
        healthy = Decimal(0) < error < Decimal(1) and duration_ticks > 0
        if error == Decimal(1):
            unit_error_sentinels += 1
        directed_quality[edge] = (error, duration_ticks, healthy)

    expected_edges = {tuple(edge) for edge in coupling_map}
    observed_edges = set(directed_quality)
    missing_edges = sorted(expected_edges - observed_edges)
    extra_edges = sorted(observed_edges - expected_edges)
    if missing_edges or extra_edges or nonintegral_duration_count:
        raise ValueError(f"CZ property coverage mismatch: {source.get('snapshot_id')}")
    healthy_rows = [row for row in directed_quality.values() if row[2]]
    if not healthy_rows:
        raise ValueError("No healthy directed CZ properties")
    minimum_error = min(row[0] for row in healthy_rows)
    minimum_duration_ticks = min(row[1] for row in healthy_rows)

    qubits = properties.get("qubits")
    if not isinstance(qubits, list) or len(qubits) != num_qubits:
        raise ValueError("Qubit property coverage mismatch")
    t2_ticks_exact: list[Decimal] = []
    for index, parameters_raw in enumerate(qubits):
        parameters = _parameter_map(parameters_raw, context=f"qubit {index}")
        t2_us = _decimal_parameter(parameters, "T2", unit="us", context=f"qubit {index}")
        if t2_us > 0:
            t2_ticks_exact.append((t2_us * Decimal(1000)) / dt_ns)
    if not t2_ticks_exact:
        raise ValueError("No positive T2 property")
    maximum_t2_ticks_exact = max(t2_ticks_exact)
    maximum_t2_ticks_floor = int(maximum_t2_ticks_exact)

    healthy_undirected: set[tuple[int, int]] = set()
    for source_qubit, target_qubit in expected_edges:
        if source_qubit >= target_qubit:
            continue
        forward = directed_quality.get((source_qubit, target_qubit))
        reverse = directed_quality.get((target_qubit, source_qubit))
        if forward and reverse and forward[2] and reverse[2]:
            healthy_undirected.add((source_qubit, target_qubit))
    component_sizes = _component_sizes(num_qubits, healthy_undirected)
    parallel_capacity = num_qubits // 2
    error_ceiling_exclusive = int(
        (Decimal(1) / minimum_error).to_integral_value(rounding=ROUND_CEILING)
    )
    maximum_strict_duration_layers = int(
        (maximum_t2_ticks_exact / Decimal(minimum_duration_ticks))
        .to_integral_value(rounding=ROUND_CEILING)
    ) - 1
    duration_ceiling_exclusive = (
        maximum_strict_duration_layers * parallel_capacity
    ) + 1
    required_maximum_direct_cx = min(
        error_ceiling_exclusive, duration_ceiling_exclusive
    ) - 1

    return {
        "snapshot_id": source["snapshot_id"],
        "distribution": {
            "package": distribution["package"],
            "version": version,
            "filename": distribution["filename"],
            "wheel_sha256": distribution["wheel_sha256"],
            "wheel_url": distribution["wheel_url"],
            "pypi_metadata_url": distribution["pypi_metadata_url"],
            "uploaded_at": distribution["uploaded_at"],
        },
        "archive_members": {
            "configuration": source["configuration_archive_member"],
            "properties": source["properties_archive_member"],
        },
        "backend_name": backend_name,
        "backend_version": backend_version,
        "processor_family": family,
        "processor_revision": revision,
        "source_epoch": source_epoch,
        "configuration_path": source["configuration_path"],
        "configuration_raw_sha256": configuration_raw,
        "properties_path": source["properties_path"],
        "properties_raw_sha256": properties_raw,
        "normalized_properties_sha256": semantic_sha256(properties),
        "directed_topology_sha256": topology_sha,
        "num_qubits": num_qubits,
        "basis_gates": list(basis_gates),
        "dt_ns": _decimal_text(dt_ns),
        "directed_cz_property_count": len(directed_quality),
        "fault_excluded_directed_cz_count": sum(1 for row in healthy_rows if row[2]),
        "unit_error_sentinel_count": unit_error_sentinels,
        "missing_cz_property_count": len(missing_edges),
        "extra_cz_property_count": len(extra_edges),
        "minimum_cz_reported_error": _decimal_text(minimum_error),
        "minimum_cz_duration_ticks": minimum_duration_ticks,
        "maximum_t2_ticks_floor": maximum_t2_ticks_floor,
        "maximum_t2_ticks_exact": _decimal_text(maximum_t2_ticks_exact),
        "idealized_parallel_cz_capacity": parallel_capacity,
        "fault_excluded_component_sizes": component_sizes,
        "largest_fault_excluded_component_qubits": component_sizes[0],
        "strict_error_ceiling_exclusive": error_ceiling_exclusive,
        "strict_duration_ceiling_exclusive": duration_ceiling_exclusive,
        "required_maximum_direct_cx": required_maximum_direct_cx,
        "current_hardware_evidence": False,
        "live_provider_export": False,
    }


def load_evidence_cohort(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    catalog_path = _regular(root, str(SOURCE_CATALOG))
    catalog = read_json_strict(catalog_path)
    distributions_raw = catalog.get("distributions")
    snapshots = catalog.get("snapshots")
    if not isinstance(distributions_raw, list) or not all(
        isinstance(item, Mapping) for item in distributions_raw
    ):
        raise ValueError("Malformed source distribution registry")
    if not isinstance(snapshots, list) or not all(isinstance(item, Mapping) for item in snapshots):
        raise ValueError("Malformed snapshot registry")
    distributions = {str(item.get("version")): item for item in distributions_raw}
    if len(distributions) != len(distributions_raw):
        raise ValueError("Duplicate distribution version")
    normalized = [normalize_snapshot(root, item, distributions) for item in snapshots]
    snapshot_ids = [str(item["snapshot_id"]) for item in normalized]
    if len(snapshot_ids) != len(set(snapshot_ids)):
        raise ValueError("Duplicate snapshot identity")
    return catalog, normalized


__all__ = [
    "EXPECTED_BASIS",
    "EXPECTED_DIRECTED_COUPLINGS",
    "EXPECTED_FAMILY",
    "EXPECTED_QUBITS",
    "EXPECTED_REVISION",
    "EXPECTED_TOPOLOGY_SHA256",
    "SOURCE_CATALOG",
    "load_evidence_cohort",
    "normalize_snapshot",
    "raw_file_sha256",
    "read_json_strict",
    "semantic_sha256",
]
