"""Versioned point-in-time data contracts for the universal backtest engine.

The module deliberately separates *structural readiness* from data quality
certification.  A valid manifest can describe a future or synthetic feed, but
only an authenticated point-in-time manifest can satisfy an institutional
gate.  This keeps adapters useful before licensed datasets arrive without
silently upgrading research data to production evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping


DATA_CONTRACT_VERSION = "universal-data-contract-1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _utc(value: datetime, *, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")


class DataMode(str, Enum):
    """Truth status of a dataset, never inferred from its filename."""

    POINT_IN_TIME = "POINT_IN_TIME"
    CURRENT_SNAPSHOT = "CURRENT_SNAPSHOT"
    SYNTHETIC = "SYNTHETIC"


class DataCapability(str, Enum):
    BARS = "BARS"
    TRADES = "TRADES"
    QUOTES = "QUOTES"
    L2 = "L2"
    L3 = "L3"
    FX = "FX"
    RATES = "RATES"
    CORPORATE_ACTIONS = "CORPORATE_ACTIONS"
    SECURITY_MASTER = "SECURITY_MASTER"
    FUTURES_CHAINS = "FUTURES_CHAINS"
    OPTION_CHAINS = "OPTION_CHAINS"
    IMPLIED_VOLATILITY = "IMPLIED_VOLATILITY"
    BORROW = "BORROW"
    FUNDING = "FUNDING"
    MARGIN_PARAMETERS = "MARGIN_PARAMETERS"
    CALENDARS = "CALENDARS"


@dataclass(frozen=True)
class DatasetPartition:
    """Immutable physical partition and its knowledge-time envelope."""

    partition_id: str
    uri: str
    sha256: str
    observed_from: datetime
    observed_to: datetime
    available_at: datetime
    rows: int
    bytes: int = 0
    revision: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        partition_id = str(self.partition_id).strip()
        uri = str(self.uri).strip()
        digest = str(self.sha256).strip().lower()
        if not partition_id or not uri:
            raise ValueError("partition_id and uri are required")
        if not _SHA256.fullmatch(digest):
            raise ValueError("partition sha256 must be a lowercase SHA-256 digest")
        observed_from = _utc(self.observed_from, name="observed_from")
        observed_to = _utc(self.observed_to, name="observed_to")
        available_at = _utc(self.available_at, name="available_at")
        if observed_to < observed_from:
            raise ValueError("observed_to cannot precede observed_from")
        if available_at < observed_from:
            raise ValueError("available_at cannot precede observed_from")
        if int(self.rows) < 0 or int(self.bytes) < 0:
            raise ValueError("partition rows and bytes must be non-negative")
        object.__setattr__(self, "partition_id", partition_id)
        object.__setattr__(self, "uri", uri)
        object.__setattr__(self, "sha256", digest)
        object.__setattr__(self, "observed_from", observed_from)
        object.__setattr__(self, "observed_to", observed_to)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class DatasetManifest:
    """Content-addressed inventory accepted by future data connectors."""

    dataset_id: str
    vendor: str
    mode: DataMode
    capabilities: tuple[DataCapability, ...]
    partitions: tuple[DatasetPartition, ...]
    created_at: datetime
    schema_version: str
    lineage: tuple[str, ...] = ()
    license_id: str = ""
    signature: str = ""
    signer: str = ""
    contract_version: str = DATA_CONTRACT_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        dataset_id = str(self.dataset_id).strip()
        vendor = str(self.vendor).strip()
        schema_version = str(self.schema_version).strip()
        if not dataset_id or not vendor or not schema_version:
            raise ValueError("dataset_id, vendor and schema_version are required")
        if str(self.contract_version) != DATA_CONTRACT_VERSION:
            raise ValueError("unsupported data contract version")
        created_at = _utc(self.created_at, name="created_at")
        capabilities = tuple(
            sorted({DataCapability(item) for item in self.capabilities}, key=lambda item: item.value)
        )
        partitions = tuple(sorted(self.partitions, key=lambda item: item.partition_id))
        if len({item.partition_id for item in partitions}) != len(partitions):
            raise ValueError("duplicate dataset partition_id")
        if len({item.sha256 for item in partitions}) != len(partitions):
            raise ValueError("duplicate physical partition digest")
        object.__setattr__(self, "dataset_id", dataset_id)
        object.__setattr__(self, "vendor", vendor)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "partitions", partitions)
        object.__setattr__(self, "lineage", tuple(str(item).strip() for item in self.lineage if str(item).strip()))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DatasetManifest":
        """Parse the stable JSON boundary used by future vendor connectors."""

        raw = dict(payload)
        partitions = tuple(
            DatasetPartition(
                partition_id=item["partition_id"],
                uri=item["uri"],
                sha256=item["sha256"],
                observed_from=datetime.fromisoformat(str(item["observed_from"]).replace("Z", "+00:00")),
                observed_to=datetime.fromisoformat(str(item["observed_to"]).replace("Z", "+00:00")),
                available_at=datetime.fromisoformat(str(item["available_at"]).replace("Z", "+00:00")),
                rows=int(item["rows"]),
                bytes=int(item.get("bytes", 0)),
                revision=str(item.get("revision", "")),
                metadata=dict(item.get("metadata") or {}),
            )
            for item in raw.get("partitions") or ()
        )
        return cls(
            dataset_id=raw["dataset_id"],
            vendor=raw["vendor"],
            mode=DataMode(raw["mode"]),
            capabilities=tuple(DataCapability(item) for item in raw.get("capabilities") or ()),
            partitions=partitions,
            created_at=datetime.fromisoformat(str(raw["created_at"]).replace("Z", "+00:00")),
            schema_version=raw["schema_version"],
            lineage=tuple(raw.get("lineage") or ()),
            license_id=str(raw.get("license_id", "")),
            signature=str(raw.get("signature", "")),
            signer=str(raw.get("signer", "")),
            contract_version=str(raw.get("contract_version", DATA_CONTRACT_VERSION)),
            metadata=dict(raw.get("metadata") or {}),
        )

    def payload(self, *, include_signature: bool = False) -> dict[str, Any]:
        payload = {
            "dataset_id": self.dataset_id,
            "vendor": self.vendor,
            "mode": self.mode.value,
            "capabilities": [item.value for item in self.capabilities],
            "partitions": [
                {
                    "partition_id": item.partition_id,
                    "uri": item.uri,
                    "sha256": item.sha256,
                    "observed_from": item.observed_from.isoformat(),
                    "observed_to": item.observed_to.isoformat(),
                    "available_at": item.available_at.isoformat(),
                    "rows": int(item.rows),
                    "bytes": int(item.bytes),
                    "revision": item.revision,
                    "metadata": dict(item.metadata),
                }
                for item in self.partitions
            ],
            "created_at": self.created_at.isoformat(),
            "schema_version": self.schema_version,
            "lineage": list(self.lineage),
            "license_id": self.license_id,
            "signer": self.signer,
            "contract_version": self.contract_version,
            "metadata": dict(self.metadata),
        }
        if include_signature:
            payload["signature"] = self.signature
        return payload

    @property
    def content_sha256(self) -> str:
        return sha256(_canonical(self.payload(include_signature=False))).hexdigest()

    @property
    def authenticated(self) -> bool:
        """Whether provenance fields needed for external verification exist.

        Cryptographic signature verification belongs to a vendor-specific trust
        store.  Presence alone never promotes the dataset; callers must pass a
        verified digest to :meth:`assess`.
        """

        return bool(self.signature.strip() and self.signer.strip() and self.license_id.strip())

    def assess(
        self,
        required: Iterable[DataCapability | str],
        *,
        verified_manifest_sha256: str = "",
    ) -> "DataReadiness":
        required_set = {DataCapability(item) for item in required}
        missing = tuple(sorted(required_set.difference(self.capabilities), key=lambda item: item.value))
        verified = bool(
            _SHA256.fullmatch(str(verified_manifest_sha256).lower())
            and str(verified_manifest_sha256).lower() == self.content_sha256
        )
        blockers: list[str] = []
        if self.mode is not DataMode.POINT_IN_TIME:
            blockers.append(f"dataset mode is {self.mode.value}, not POINT_IN_TIME")
        if missing:
            blockers.append("missing capabilities: " + ", ".join(item.value for item in missing))
        if not self.partitions:
            blockers.append("no immutable data partitions")
        if not self.authenticated:
            blockers.append("vendor signature, signer or license evidence missing")
        if not verified:
            blockers.append("manifest digest has not been externally verified")
        return DataReadiness(
            ready=not blockers,
            manifest_sha256=self.content_sha256,
            missing_capabilities=missing,
            blockers=tuple(blockers),
        )


@dataclass(frozen=True)
class DataReadiness:
    ready: bool
    manifest_sha256: str
    missing_capabilities: tuple[DataCapability, ...] = ()
    blockers: tuple[str, ...] = ()

    @property
    def state(self) -> str:
        return "CERTIFIED" if self.ready else "NOT_CERTIFIED"


class DatasetRegistry:
    """Small in-process reference registry with immutable id semantics."""

    def __init__(self) -> None:
        self._by_id: dict[str, DatasetManifest] = {}

    def register(self, manifest: DatasetManifest) -> DatasetManifest:
        current = self._by_id.get(manifest.dataset_id)
        if current is not None and current.content_sha256 != manifest.content_sha256:
            raise ValueError("dataset_id already resolves to different immutable content")
        self._by_id[manifest.dataset_id] = manifest
        return manifest

    def get(self, dataset_id: str) -> DatasetManifest:
        try:
            return self._by_id[str(dataset_id).strip()]
        except KeyError as exc:
            raise KeyError(f"unknown dataset_id: {dataset_id}") from exc

    def manifests(self) -> tuple[DatasetManifest, ...]:
        return tuple(self._by_id[key] for key in sorted(self._by_id))


__all__ = [
    "DATA_CONTRACT_VERSION",
    "DataCapability",
    "DataMode",
    "DataReadiness",
    "DatasetManifest",
    "DatasetPartition",
    "DatasetRegistry",
]
