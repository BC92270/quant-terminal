"""Authenticity verification for institutional evidence manifests.

SHA-256 binds bytes to a manifest, but it does not identify who asserted the
manifest.  Promotion gates therefore require an Ed25519 signature whose public
key is installed independently by the server operator.  Keys embedded in an
upload are deliberately ignored.
"""
from __future__ import annotations

import base64
from collections.abc import Mapping
import json
import os
import re
from hashlib import sha256
from typing import Any

try:  # Optional at import time; absence is a fail-closed runtime state.
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
except ImportError:  # pragma: no cover - supported deployments install requirements.txt.
    InvalidSignature = Exception
    Ed25519PublicKey = None


TRUST_STORE_ENV = "BACKTEST_TRUSTED_EVIDENCE_ED25519_KEYS_JSON"
SIGNATURE_ALGORITHM = "ed25519-sha256-manifest-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _decode_base64(value: Any, *, expected_bytes: int) -> bytes | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        decoded = base64.b64decode(text, validate=True)
    except (ValueError, TypeError):
        return None
    return decoded if len(decoded) == expected_bytes else None


def trusted_ed25519_keys() -> tuple[dict[str, bytes], list[str]]:
    """Load active trust anchors from a server-controlled environment variable.

    Accepted JSON forms are ``{"key-id": "base64-public-key"}`` or a mapping
    whose values contain ``public_key_base64`` and optional ``status``.  Invalid
    entries are ignored and reported; upload content can never add trust anchors.
    """
    raw = os.environ.get(TRUST_STORE_ENV, "").strip()
    if not raw:
        return {}, [f"server trust store {TRUST_STORE_ENV} is not configured"]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}, [f"server trust store {TRUST_STORE_ENV} is invalid JSON"]
    if not isinstance(payload, Mapping):
        return {}, [f"server trust store {TRUST_STORE_ENV} must be a JSON object"]

    keys: dict[str, bytes] = {}
    issues: list[str] = []
    for raw_key_id, value in payload.items():
        key_id = str(raw_key_id).strip()
        if not key_id:
            issues.append("trust store contains an empty key id")
            continue
        if isinstance(value, Mapping):
            status = str(value.get("status", "active")).strip().lower()
            encoded = value.get("public_key_base64")
            if status != "active":
                continue
        else:
            encoded = value
        public_key = _decode_base64(encoded, expected_bytes=32)
        if public_key is None:
            issues.append(f"trust key {key_id} is not a 32-byte base64 Ed25519 key")
            continue
        keys[key_id] = public_key
    if not keys and not issues:
        issues.append("server trust store has no active keys")
    return keys, issues


def verify_trusted_manifest_signature(
    *,
    manifest_hash: Any,
    signing_key_id: Any,
    signature_algorithm: Any,
    signature_base64: Any,
) -> dict[str, Any]:
    """Verify a manifest-hash signature against independently trusted keys."""
    digest = str(manifest_hash or "").strip().lower()
    key_id = str(signing_key_id or "").strip()
    algorithm = str(signature_algorithm or "").strip().lower()
    signature = _decode_base64(signature_base64, expected_bytes=64)
    reasons: list[str] = []
    if not _SHA256_RE.fullmatch(digest):
        reasons.append("manifest hash is not a valid SHA-256")
    if algorithm != SIGNATURE_ALGORITHM:
        reasons.append(f"signature_algorithm must be {SIGNATURE_ALGORITHM}")
    if not key_id:
        reasons.append("signing_key_id is missing")
    if signature is None:
        reasons.append("evidence signature is not a 64-byte base64 Ed25519 signature")

    trust, trust_issues = trusted_ed25519_keys()
    public_key = trust.get(key_id)
    if not trust:
        reasons.extend(trust_issues)
    elif public_key is None:
        reasons.append(f"signing key {key_id or '<missing>'} is not trusted by the server")
    if Ed25519PublicKey is None:
        reasons.append("cryptography Ed25519 runtime is unavailable")

    if not reasons:
        try:
            Ed25519PublicKey.from_public_bytes(public_key).verify(
                signature,
                digest.encode("ascii"),
            )
        except (InvalidSignature, ValueError, TypeError):
            reasons.append("Ed25519 signature verification failed")

    return {
        "state": "VERIFIED" if not reasons else "UNAVAILABLE",
        "verified": not reasons,
        "reasons": reasons,
        "signing_key_id": key_id,
        "signature_algorithm": algorithm,
        "public_key_sha256": sha256(public_key).hexdigest() if public_key is not None else "",
        "trusted_key_count": int(len(trust)),
        "trust_store": TRUST_STORE_ENV,
    }
