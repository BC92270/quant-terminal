"""Reproducible experiment manifests and a local immutable registry."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile
from typing import Any

import numpy as np
import pandas as pd

from .types import RunManifest


_MARKET_IDENTITY_KEYS = frozenset({
    "as_of",
    "authoritative_source",
    "corporate_actions_embedded",
    "data_quality_issues",
    "data_source",
    "currency",
    "dataset",
    "dataset_id",
    "dataset_version",
    "effective_at",
    "exchange",
    "exchange_calendar",
    "interval_label",
    "market_calendar",
    "periods_per_year",
    "point_in_time",
    "point_in_time_manifest",
    "point_in_time_manifest_hash",
    "point_in_time_signature_base64",
    "price_basis",
    "provider",
    "provenance",
    "quality_flags",
    "required_capabilities",
    "source",
    "source_version",
    "snapshot_id",
    "session",
    "session_calendar",
    "source_snapshot_hash",
    "source_snapshot_id",
    "vendor",
    "timezone",
    "time_zone",
})
_VOLATILE_PROVENANCE_KEYS = frozenset({
    "cache_timestamp",
    "created_at",
    "download_timestamp",
    "downloaded_at",
    "fetch_time",
    "fetched_at",
    "generated_at",
    "ingested_at",
    "loaded_at",
    "request_timestamp",
    "refreshed_at",
    "retrieved_at",
    "retrieval_timestamp",
    "run_timestamp",
    "last_refreshed",
    "updated_at",
})
_DEPENDENCY_MANIFEST_NAMES = frozenset({
    "Pipfile",
    "Pipfile.lock",
    "conda-lock.yml",
    "environment.yaml",
    "environment.yml",
    "poetry.lock",
    "pyproject.toml",
    "requirements.in",
    "requirements.txt",
    "setup.cfg",
    "setup.py",
    "uv.lock",
})
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|x[_-]?api[_-]?key|client[_-]?secret|password|passwd|"
    r"private[_-]?key|access[_-]?token|refresh[_-]?token|secret|token|authorization)[\"']?"
    r"\s*[=:]\s*)"
    r"(?:\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s,;\]}]+)"
)
_SECRET_TOKEN = re.compile(
    r"(?i)\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,}|AKIA[0-9A-Z]{12,}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b"
)
_AUTHORIZATION_HEADER = re.compile(
    r"(?im)(authorization\s*:\s*(?:bearer|basic)\s+)[^\s\"']+"
)
_CREDENTIAL_URL = re.compile(r"(?i)(https?://)([^\s/:@]+):([^\s/@]+)@")
_PEM_BLOCK = re.compile(
    r"-----BEGIN [^-\r\n]+-----.*?-----END [^-\r\n]+-----",
    flags=re.DOTALL,
)
_LONG_SECRET_LITERAL = re.compile(
    r"(?P<quote>['\"])(?=[A-Za-z0-9_+/=.:-]{32,}(?P=quote))"
    r"[A-Za-z0-9_+/=.:-]{32,}(?P=quote)"
)


def _json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, set):
        safe = [_json_safe(v) for v in value]
        return sorted(safe, key=lambda item: json.dumps(item, sort_keys=True, default=repr))
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.ndarray):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, pd.Series):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, pd.DataFrame):
        return [_json_safe(v) for v in value.to_dict(orient="records")]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def stable_hash(value: Any) -> str:
    encoded = json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return sha256(encoded).hexdigest()


def _stable_provenance_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _stable_provenance_value(nested)
            for key, nested in sorted(value.items(), key=lambda item: str(item[0]))
            if str(key).strip().lower().replace("-", "_").replace(" ", "_")
            not in _VOLATILE_PROVENANCE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_stable_provenance_value(item) for item in value]
    return _json_safe(value)


def _identity_provenance(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """Select stable provenance and quality facts for semantic run identity.

    Acquisition wall-clock timestamps describe *when* an identical snapshot was
    fetched, not what was tested. They remain available to callers/registries but
    are deliberately excluded from the run identity. Effective dates contained
    in an explicit provenance object are retained unless their key is one of the
    acquisition-time fields above.
    """
    selected: dict[str, Any] = {}
    for key, value in (values or {}).items():
        name = str(key)
        normalised = name.strip().lower().replace("-", "_").replace(" ", "_")
        if normalised in _VOLATILE_PROVENANCE_KEYS:
            continue
        if (
            normalised in _MARKET_IDENTITY_KEYS
            or "provenance" in normalised
            or "quality" in normalised
            or normalised.endswith("_source")
        ):
            selected[name] = _stable_provenance_value(value)
    return {key: selected[key] for key in sorted(selected)}


def semantic_provenance(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """Public, stable subset for configs/artifacts that participate in run identity."""
    return _identity_provenance(values)


def data_hash(frame: pd.DataFrame | pd.Series) -> str:
    obj = frame.to_frame() if isinstance(frame, pd.Series) else frame
    index = obj.index
    if isinstance(index, pd.MultiIndex):
        index_dtypes = [str(level.dtype) for level in index.levels]
        index_timezones = [
            str(getattr(level, "tz", "") or "") for level in index.levels
        ]
    else:
        index_dtypes = [str(getattr(index, "dtype", type(index).__name__))]
        index_timezones = [str(getattr(index, "tz", "") or "")]
    index_schema = {
        "class": type(index).__name__,
        "dtypes": index_dtypes,
        "timezones": index_timezones,
        "frequency": str(getattr(index, "freqstr", "") or ""),
    }
    if obj.empty:
        schema = {
            "columns": [str(column) for column in obj.columns],
            "dtypes": [str(dtype) for dtype in obj.dtypes],
            "index_names": [str(name) for name in obj.index.names],
            "index_schema": index_schema,
            "series_name": str(frame.name) if isinstance(frame, pd.Series) else None,
        }
        return stable_hash({"schema": schema, "rows": "EMPTY"})
    hashes = pd.util.hash_pandas_object(obj, index=True).values.tobytes()
    schema = stable_hash({
        "columns": [str(column) for column in obj.columns],
        "dtypes": [str(dtype) for dtype in obj.dtypes],
        "index_names": [str(name) for name in obj.index.names],
        "index_schema": index_schema,
        "series_name": str(frame.name) if isinstance(frame, pd.Series) else None,
    }).encode()
    return sha256(schema + hashes).hexdigest()


def artifact_hash(value: Any) -> str:
    """Hash heterogeneous research artifacts without embedding them in a manifest.

    DataFrames and Series retain their index/schema semantics. Nested mappings can
    therefore safely contain candidate returns, factor histories and legacy result
    tables without falling back to process-dependent object representations.
    """

    def fingerprint(item: Any) -> Any:
        if isinstance(item, (pd.DataFrame, pd.Series)):
            return {
                "artifact_type": type(item).__name__,
                "shape": list(item.shape),
                "hash": data_hash(item),
            }
        if isinstance(item, np.ndarray):
            array = np.asarray(item)
            if array.dtype.hasobject:
                digest = stable_hash(array.tolist())
            else:
                digest = sha256(np.ascontiguousarray(array).tobytes()).hexdigest()
            return {
                "artifact_type": "ndarray",
                "shape": list(array.shape),
                "dtype": str(array.dtype),
                "hash": digest,
            }
        if is_dataclass(item) and not isinstance(item, type):
            return fingerprint(asdict(item))
        if isinstance(item, Mapping):
            return {
                str(key): fingerprint(nested)
                for key, nested in sorted(item.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(item, (list, tuple)):
            return [fingerprint(nested) for nested in item]
        if isinstance(item, set):
            return sorted((fingerprint(nested) for nested in item), key=stable_hash)
        return _json_safe(item)

    return stable_hash(fingerprint(value))


def _resolve_requested_path(code_path: str | Path, package: Path) -> Path:
    requested = Path(code_path)
    if not requested.is_absolute():
        package_sibling = package.parent / requested
        working_copy = Path.cwd() / requested
        # The package checkout is authoritative. CWD is only a compatibility
        # fallback for callers that intentionally point outside that checkout.
        requested = package_sibling if package_sibling.exists() else working_copy
    return requested.resolve()


def _git_bytes(start: Path, *args: str) -> bytes | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(start), *args],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout if completed.returncode == 0 else None


def _redact_patch(patch: bytes) -> tuple[bytes, int]:
    """Redact credential-bearing shapes before repository evidence is exported.

    This intentionally over-redacts long literals.  The original patch digest
    remains in provenance, while a redacted bundle must never be treated as a
    complete source reconstruction.
    """
    text = patch.decode("utf-8", errors="replace")
    # Broad structures run first so a narrower assignment match cannot leave a
    # suffix from a quoted, multi-word credential behind.
    text, pem_blocks = _PEM_BLOCK.subn("[REDACTED_PEM_BLOCK]", text)
    text, authorizations = _AUTHORIZATION_HEADER.subn(r"\1[REDACTED]", text)
    text, urls = _CREDENTIAL_URL.subn(r"\1[REDACTED]:[REDACTED]@", text)
    text, assignments = _SECRET_ASSIGNMENT.subn(r"\1[REDACTED]", text)
    text, tokens = _SECRET_TOKEN.subn("[REDACTED_TOKEN]", text)
    text, long_literals = _LONG_SECRET_LITERAL.subn("[REDACTED_LONG_LITERAL]", text)
    return (
        text.encode("utf-8"),
        assignments + tokens + authorizations + urls + pem_blocks + long_literals,
    )


def repository_provenance(
    code_path: str | Path,
    package_path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Capture cwd-independent Git/dependency evidence for the executable scope.

    The raw tracked diff is hashed for identity. Only a credential-redacted patch
    is retained as bundle evidence. Untracked files are represented by path, size
    and SHA-256 rather than content, preventing accidental secret capture.
    """
    package = Path(package_path).resolve() if package_path is not None else Path(__file__).resolve().parent
    requested = _resolve_requested_path(code_path, package)
    starts = [package if package.is_dir() else package.parent, requested if requested.is_dir() else requested.parent]
    root: Path | None = None
    for start in starts:
        root_bytes = _git_bytes(start, "rev-parse", "--show-toplevel")
        if root_bytes:
            candidate = Path(root_bytes.decode("utf-8", errors="replace").strip()).resolve()
            if candidate.exists():
                root = candidate
                break
    if root is None:
        return ({
            "state": "UNAVAILABLE",
            "reason": "No Git repository found from package_path/code_path",
            "identity": {"state": "UNAVAILABLE"},
        }, {})

    def relative_scope(path: Path) -> str | None:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return None

    scope = sorted({
        item for item in (relative_scope(package), relative_scope(requested)) if item
    })
    code_files: set[str] = set()
    if package.is_dir():
        code_files.update(
            relative
            for path in package.rglob("*.py")
            if "__pycache__" not in path.parts
            for relative in [relative_scope(path)]
            if relative
        )
    if requested.is_file():
        relative = relative_scope(requested)
        if relative:
            code_files.add(relative)
    elif requested.is_dir():
        code_files.update(
            relative
            for path in requested.rglob("*.py")
            if "__pycache__" not in path.parts
            for relative in [relative_scope(path)]
            if relative
        )
    if scope:
        head_files = _git_bytes(
            root, "ls-tree", "-r", "--name-only", "-z", "HEAD", "--", *scope
        ) or b""
        code_files.update(
            relative
            for encoded in head_files.split(b"\0")
            for relative in [encoded.decode("utf-8", errors="replace")]
            if relative.endswith(".py") and "__pycache__" not in Path(relative).parts
        )
    commit_bytes = _git_bytes(root, "rev-parse", "HEAD")
    commit = commit_bytes.decode("ascii", errors="replace").strip() if commit_bytes else "UNAVAILABLE"
    branch_bytes = _git_bytes(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    branch = branch_bytes.decode("utf-8", errors="replace").strip() if branch_bytes else "DETACHED"
    status_bytes = _git_bytes(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    worktree_dirty = bool(status_bytes)

    diff_args = ["diff", "--binary", "--no-ext-diff", "HEAD"]
    raw_patch = b""
    if code_files:
        diff_args.extend(["--", *sorted(code_files)])
        raw_patch = _git_bytes(root, *diff_args) or b""
    redacted_patch, redaction_count = _redact_patch(raw_patch)

    def is_dependency_manifest(path: Path) -> bool:
        return path.name in _DEPENDENCY_MANIFEST_NAMES or (
            path.name.startswith("requirements-") and path.suffix in {".in", ".txt"}
        )

    untracked_args = ["ls-files", "--others", "--exclude-standard", "-z"]
    if scope:
        untracked_args.extend(["--", *scope])
    untracked_bytes = _git_bytes(root, *untracked_args) or b""
    untracked: dict[str, dict[str, Any]] = {}
    for encoded_path in filter(None, untracked_bytes.split(b"\0")):
        relative = encoded_path.decode("utf-8", errors="replace")
        path = root / relative
        if not path.is_file():
            continue
        content = path.read_bytes()
        untracked[relative] = {
            "sha256": sha256(content).hexdigest(),
            "bytes": len(content),
        }

    # Dependency manifests are execution inputs even when they sit outside the
    # Python package/entrypoint scope.  Record every root-level untracked one so
    # the bundle cannot claim a clean, reconstructible dependency state while
    # silently omitting it.
    all_untracked_bytes = _git_bytes(
        root, "ls-files", "--others", "--exclude-standard", "-z"
    ) or b""
    for encoded_path in filter(None, all_untracked_bytes.split(b"\0")):
        relative = encoded_path.decode("utf-8", errors="replace")
        path = root / relative
        if path.parent != root or not path.is_file() or not is_dependency_manifest(path):
            continue
        content = path.read_bytes()
        untracked[relative] = {
            "sha256": sha256(content).hexdigest(),
            "bytes": len(content),
            "dependency_manifest": True,
        }

    dependencies: dict[str, dict[str, Any]] = {}
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if not path.is_file():
            continue
        if not is_dependency_manifest(path):
            continue
        content = path.read_bytes()
        dependencies[path.name] = {
            "sha256": sha256(content).hexdigest(),
            "bytes": len(content),
        }
    dependency_patch = b""
    if dependencies:
        dependency_patch = _git_bytes(
            root,
            "diff",
            "--binary",
            "--no-ext-diff",
            "HEAD",
            "--",
            *sorted(dependencies),
        ) or b""
    redacted_dependency_patch, dependency_redactions = _redact_patch(dependency_patch)

    identity = {
        "commit": commit,
        "tracked_diff_sha256": sha256(raw_patch).hexdigest(),
        "dependency_diff_sha256": sha256(dependency_patch).hexdigest(),
        "untracked_inventory": untracked,
        "dependency_manifests": dependencies,
    }
    scoped_dirty = bool(raw_patch or dependency_patch or untracked)
    public = {
        "state": "AVAILABLE",
        "commit": commit,
        "head_state": "DETACHED" if branch == "DETACHED" else "BRANCH",
        "branch": branch,
        "worktree_dirty": worktree_dirty,
        "captured_scope_dirty": scoped_dirty,
        "captured_scope": scope,
        "tracked_patch_scope": sorted(code_files),
        "tracked_diff_sha256": identity["tracked_diff_sha256"],
        "tracked_diff_bytes": len(raw_patch),
        "dependency_diff_sha256": identity["dependency_diff_sha256"],
        "dependency_diff_bytes": len(dependency_patch),
        "patch_redactions": redaction_count,
        "dependency_patch_redactions": dependency_redactions,
        "patch_reconstruction_complete": bool(
            redaction_count == 0 and dependency_redactions == 0 and not untracked
        ),
        "untracked_inventory": untracked,
        "dependency_manifests": dependencies,
        "identity": identity,
        "identity_hash": stable_hash(identity),
    }
    evidence: dict[str, bytes] = {}
    if worktree_dirty:
        evidence["dirty.patch"] = redacted_patch or (
            b"# Repository is dirty, but no tracked Python source diff exists in the captured scope.\n"
            b"# Dependency diffs and untracked content are represented by hashes only; see provenance.json.\n"
        )
    if dependency_patch:
        evidence["dependencies.patch"] = redacted_dependency_patch
    return public, evidence


def _code_snapshot(
    code_path: str | Path,
    package_path: str | Path | None = None,
) -> tuple[str, dict[str, str]]:
    """Hash the complete institutional package plus the legacy entrypoint.

    Labels are repository-relative and never contain an absolute workstation path,
    so an identical checkout produces the same digest on another host.
    """
    package = Path(package_path).resolve() if package_path is not None else Path(__file__).resolve().parent
    files: dict[str, Path] = {}
    if package.is_dir():
        for path in sorted(package.rglob("*.py")):
            if "__pycache__" not in path.parts:
                files[f"backtest_institutional/{path.relative_to(package).as_posix()}"] = path

    requested = _resolve_requested_path(code_path, package)
    if requested.is_file():
        try:
            requested.relative_to(package)
        except ValueError:
            files[f"entrypoint/{requested.name}"] = requested
    elif requested.is_dir():
        try:
            requested.relative_to(package)
            requested_is_package = True
        except ValueError:
            requested_is_package = False
        if not requested_is_package:
            for path in sorted(requested.rglob("*.py")):
                if "__pycache__" not in path.parts:
                    files[f"entrypoint/{path.relative_to(requested).as_posix()}"] = path

    inventory = {
        label: sha256(path.read_bytes()).hexdigest()
        for label, path in sorted(files.items())
    }
    if not inventory:
        return "UNAVAILABLE", {}
    return stable_hash(inventory), inventory


def environment_snapshot() -> dict[str, Any]:
    packages = {}
    for name in ("numpy", "pandas", "scipy", "streamlit", "plotly", "scikit-learn"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "UNAVAILABLE"
    return {"python": platform.python_version(), "platform": platform.platform(), "packages": packages}


def build_run_manifest(
    *,
    config: dict[str, Any],
    market_data: pd.DataFrame | pd.Series,
    strategy: str,
    symbol: str,
    seed: int,
    code_path: str | Path = "backtest_lab.py",
    engine_version: str = "7.0.0",
    parent_run_id: str | None = None,
    tags: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
    created_at: str | None = None,
    package_path: str | Path | None = None,
    candidate_returns: pd.DataFrame | pd.Series | None = None,
    factor_returns: pd.DataFrame | pd.Series | None = None,
    legacy_result: Any = None,
    additional_artifacts: Mapping[str, Any] | None = None,
) -> RunManifest:
    code_digest, code_inventory = _code_snapshot(code_path, package_path)
    repository, repository_evidence = repository_provenance(code_path, package_path)
    env = environment_snapshot()
    config_digest = stable_hash(config)
    data_digest = data_hash(market_data)
    artifacts: dict[str, Any] = dict(additional_artifacts or {})
    if candidate_returns is not None:
        artifacts["candidate_returns"] = candidate_returns
    if factor_returns is not None:
        artifacts["factor_returns"] = factor_returns
    if legacy_result is not None:
        artifacts["legacy_result"] = legacy_result
    artifact_hashes = {
        str(name): artifact_hash(value)
        for name, value in sorted(artifacts.items(), key=lambda pair: str(pair[0]))
    }
    market_identity = _identity_provenance(getattr(market_data, "attrs", {}))
    declared_identity = _identity_provenance(metadata)
    provenance_identity = {
        "market_data_attrs": market_identity,
        "declared_metadata": declared_identity,
    }
    identity = {
        "engine_version": engine_version, "strategy": strategy, "symbol": symbol,
        "seed": int(seed), "config_hash": config_digest, "data_hash": data_digest,
        "code_hash": code_digest, "environment_hash": stable_hash(env),
        "parent_run_id": parent_run_id,
        "artifact_hashes": artifact_hashes,
        "provenance_hash": stable_hash(provenance_identity),
        "repository_identity_hash": repository.get("identity_hash", "UNAVAILABLE"),
    }
    run_id = "BT-" + stable_hash(identity)[:20].upper()
    return RunManifest(
        run_id=run_id,
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        engine_version=engine_version,
        strategy=strategy,
        symbol=symbol,
        seed=int(seed),
        config_hash=config_digest,
        data_hash=data_digest,
        code_hash=code_digest,
        environment_hash=stable_hash(env),
        parent_run_id=parent_run_id,
        tags=tags,
        metadata=_json_safe(metadata or {}) | {
            "environment": env,
            "code_inventory": code_inventory,
            "artifact_hashes": artifact_hashes,
            "identity_provenance": provenance_identity,
            "provenance_hash": stable_hash(provenance_identity),
            "repository": repository,
            "_bundle_evidence": repository_evidence,
        },
    )


class ExperimentRegistry:
    def __init__(self, root: str | Path = ".quant_cache/backtest_registry") -> None:
        self.root = Path(root)
        self.runs = self.root / "runs"

    def persist(self, manifest: RunManifest, payload: dict[str, Any]) -> Path:
        self.runs.mkdir(parents=True, exist_ok=True)
        target = self.runs / f"{manifest.run_id}.json"
        manifest_payload = asdict(manifest)
        if isinstance(manifest_payload.get("metadata"), dict):
            manifest_payload["metadata"].pop("_bundle_evidence", None)
        document = {"manifest": _json_safe(manifest_payload), "payload": _json_safe(payload)}
        encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
        if target.exists():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Corrupt immutable run for {manifest.run_id}") from exc
            # created_at is descriptive provenance, not part of the run identity.
            # Rebuilding the same semantic run later must therefore be idempotent.
            candidate = json.loads(encoded)
            existing.get("manifest", {}).pop("created_at", None)
            candidate.get("manifest", {}).pop("created_at", None)
            if existing != candidate:
                raise RuntimeError(f"Immutable run collision for {manifest.run_id}")
            return target
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{manifest.run_id}.", dir=str(self.runs))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return target

    def get(self, run_id: str) -> dict[str, Any]:
        path = self.runs / f"{run_id}.json"
        if not path.exists():
            raise KeyError(run_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def list_runs(self, limit: int = 100) -> pd.DataFrame:
        if not self.runs.exists():
            return pd.DataFrame()
        rows = []
        paths = sorted(self.runs.glob("BT-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in paths[:limit]:
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8"))["manifest"])
            except (json.JSONDecodeError, KeyError):
                rows.append({"run_id": path.stem, "status": "CORRUPT"})
        return pd.DataFrame(rows)

    def lineage(self, run_id: str) -> list[str]:
        lineage: list[str] = []
        current: str | None = run_id
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            lineage.append(current)
            try:
                current = self.get(current)["manifest"].get("parent_run_id")
            except KeyError:
                break
        return lineage
