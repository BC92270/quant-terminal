"""Small, typed evidence-certificate contract shared by research workspaces.

Certificates communicate owner evidence to the shadow-governance layer.  They
are deliberately not orders, approvals, or live-trading authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Mapping, MutableMapping


CERTIFICATE_REGISTRY_KEY = "momentum_evidence_certificates_v1"
_ALLOWED_STATUS = frozenset({"PASS", "WARN", "VETO", "STALE", "UNAVAILABLE"})


def _utc(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _safe_payload(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


@dataclass(frozen=True)
class EvidenceCertificate:
    domain: str
    owner: str
    ticker: str
    status: str
    detail: str
    impact: str
    source: str
    evidence_id: str
    size_multiplier: float
    issued_at: datetime
    expires_at: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)
    research_only: bool = True
    production_authorized: bool = False

    def as_mapping(self) -> dict[str, Any]:
        return {
            "schema": "momentum.evidence-certificate.v1",
            "domain": self.domain,
            "owner": self.owner,
            "ticker": self.ticker,
            "status": self.status,
            "detail": self.detail,
            "impact": self.impact,
            "source": self.source,
            "evidence_id": self.evidence_id,
            "size_multiplier": self.size_multiplier,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "payload": dict(self.payload),
            "research_only": self.research_only,
            "production_authorized": self.production_authorized,
        }


def issue_certificate(
    *,
    domain: str,
    owner: str,
    ticker: str,
    status: str,
    detail: str,
    impact: str,
    source: str,
    evidence_id: str,
    size_multiplier: float,
    payload: Mapping[str, Any] | None = None,
    issued_at: datetime | None = None,
    ttl: timedelta = timedelta(hours=1),
) -> EvidenceCertificate:
    normalized_status = str(status).upper().strip()
    if normalized_status not in _ALLOWED_STATUS:
        raise ValueError(f"Unsupported certificate status: {status}")
    if not str(domain).strip() or not str(owner).strip() or not str(source).strip():
        raise ValueError("Certificate domain, owner and source are required")
    if not str(evidence_id).strip():
        raise ValueError("Certificate evidence_id is required")
    if ttl <= timedelta(0):
        raise ValueError("Certificate ttl must be positive")
    multiplier = float(size_multiplier)
    if not 0.0 <= multiplier <= 1.0:
        raise ValueError("Certificate size_multiplier must be in [0, 1]")
    if normalized_status in {"VETO", "UNAVAILABLE"} and multiplier != 0.0:
        raise ValueError(f"{normalized_status} certificates must have zero size_multiplier")

    timestamp = _utc(issued_at)
    return EvidenceCertificate(
        domain=str(domain).strip().lower(),
        owner=str(owner).strip(),
        ticker=str(ticker).upper().strip(),
        status=normalized_status,
        detail=str(detail).strip(),
        impact=str(impact).strip(),
        source=str(source).strip(),
        evidence_id=str(evidence_id).strip(),
        size_multiplier=multiplier,
        issued_at=timestamp,
        expires_at=timestamp + ttl,
        payload=_safe_payload(payload),
    )


def publish_certificate(
    state: MutableMapping[str, Any],
    certificate: EvidenceCertificate,
) -> dict[str, Any]:
    """Idempotently publish the latest owner certificate into session state."""
    if not isinstance(certificate, EvidenceCertificate):
        raise TypeError("certificate must be an EvidenceCertificate")
    registry = state.get(CERTIFICATE_REGISTRY_KEY, {})
    registry = dict(registry) if isinstance(registry, Mapping) else {}
    key = f"{certificate.ticker}:{certificate.domain}:{certificate.owner}"
    registry[key] = certificate.as_mapping()
    state[CERTIFICATE_REGISTRY_KEY] = registry
    return registry[key]
