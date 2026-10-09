from __future__ import annotations

import io
import json
import zipfile
from hashlib import sha256

import numpy as np
import pandas as pd

from .engine import PairDependencyAnalysis
from ..correlation_intelligence_v3.provenance import dataframe_sha256


_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _write(z: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o600 << 16
    z.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _jsonable(x):
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (np.floating,)): return float(x) if np.isfinite(x) else None
    if isinstance(x, pd.Timestamp): return x.isoformat()
    if isinstance(x, dict): return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [_jsonable(v) for v in x]
    return x


def dependency_research_pack_zip(b: PairDependencyAnalysis) -> bytes:
    buf = io.BytesIO()
    tables = {
        "force_registry_coverage.csv": b.coverage,
        "dependency_spaces.csv": b.spaces,
        "lead_lag.csv": b.lead_lag,
        "extreme_move_dependency.csv": b.extremes,
        "jump_dependency_LEGACY_ALIAS.csv": b.jumps,
        "higher_moments.csv": b.higher_moments,
        "liquidity_commonality.csv": b.liquidity,
        "event_attribution.csv": b.events,
        "economic_context.csv": b.economic_context,
        "factor_diagnostics.csv": b.force_model.factor_diagnostics,
        "factor_selection_diagnostics.csv": b.force_model.selection_diagnostics,
        "data_hub_audit.csv": b.data_hub_audit,
        "mechanism_covariance_attribution.csv": b.force_model.group_attribution,
        "shapley_correlation_bridge.csv": b.force_model.shapley_bridge,
    }
    meta = {
        "engine": "Dependency Intelligence V4.1.0",
        "primary": b.primary,
        "peer": b.peer,
        "summary": b.summary,
        "force_model": {
            "status": b.force_model.status,
            "obs": b.force_model.obs,
            "factors_used": b.force_model.factors_used,
            "factors_dropped": b.force_model.factors_dropped,
            "raw_corr": b.force_model.raw_corr,
            "residual_corr": b.force_model.residual_corr,
            "raw_cov": b.force_model.raw_cov,
            "systematic_cov": b.force_model.systematic_cov,
            "residual_cov": b.force_model.residual_cov,
            "reconstruction_error": b.force_model.reconstruction_error,
            "primary_r2": b.force_model.primary_r2,
            "peer_r2": b.force_model.peer_r2,
            "meta": b.force_model.meta,
        },
        "base_currency": b.inputs.base_currency if b.inputs else None,
        "data_hub": b.data_hub_summary,
        "doctrine": "Association/predictive attribution by default; no causal claim without explicit upstream identification.",
        "authority": "RESEARCH_ONLY",
    }
    populated = {name: df for name, df in tables.items() if isinstance(df, pd.DataFrame) and not df.empty}
    payloads = {
        name: df.to_csv(index=False, float_format="%.17g", lineterminator="\n").encode("utf-8")
        for name, df in sorted(populated.items())
    }
    manifest = {
        "schema": {"name": "quant-terminal.dependency-research-pack", "version": "1.0.0"},
        "engine": "Dependency Intelligence V4.1.0",
        "primary": b.primary,
        "peer": b.peer,
        "authority": "RESEARCH_ONLY",
        "table_hashes": {
            name: {
                "dataframe_sha256": dataframe_sha256(populated[name]),
                "csv_sha256": sha256(payload).hexdigest(),
                "csv_bytes": int(len(payload)),
            }
            for name, payload in payloads.items()
        },
        "table_shapes": {name: [int(df.shape[0]), int(df.shape[1])] for name, df in sorted(populated.items())},
        "doctrine": meta["doctrine"],
    }
    meta["research_manifest"] = manifest
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        _write(z, "manifest.json", (json.dumps(_jsonable(manifest), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
        _write(z, "metadata.json", (json.dumps(_jsonable(meta), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"))
        for name, payload in payloads.items():
            _write(z, name, payload)
    return buf.getvalue()
