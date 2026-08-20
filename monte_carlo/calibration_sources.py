from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

import pandas as pd


_PRIORITY_PATHS: Tuple[Tuple[str, ...], ...] = (
    ("monte_carlo", "calibration_data"),
    ("monte_carlo", "long_history"),
    ("monte_carlo", "history_5y"),
    ("calibration_data",),
    ("long_history",),
    ("history_10y",),
    ("history_5y",),
    ("price_history",),
    ("historical_prices",),
    ("market_data", "price_history"),
    ("data", "price_history"),
)

_MATCHING_KEY_TOKENS = (
    "calibration",
    "long_history",
    "history_5y",
    "history_10y",
    "price_history",
    "historical_prices",
)


def _read_path(payload: Any, path: Sequence[str]) -> Any:
    current = payload
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _to_dataframe(candidate: Any) -> pd.DataFrame | None:
    if isinstance(candidate, pd.DataFrame):
        return candidate.copy()
    if isinstance(candidate, pd.Series):
        name = str(candidate.name or "close")
        return candidate.rename(name).to_frame().reset_index()
    if isinstance(candidate, (list, tuple)) and candidate:
        try:
            frame = pd.DataFrame(candidate)
            return frame if not frame.empty else None
        except Exception:
            return None
    if isinstance(candidate, Mapping):
        for key in ("data", "prices", "history", "records", "results", "candles"):
            if key in candidate:
                frame = _to_dataframe(candidate[key])
                if frame is not None and not frame.empty:
                    return frame
        try:
            frame = pd.DataFrame(candidate)
            return frame if not frame.empty else None
        except Exception:
            return None
    return None


def _looks_like_price_frame(frame: pd.DataFrame | None) -> bool:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return False
    columns = {str(c).strip().lower().replace(" ", "_") for c in frame.columns}
    close_like = {"close", "adj_close", "adjusted_close", "price", "c"}
    return bool(columns & close_like) or (frame.shape[1] == 1 and len(frame) >= 30)


def _recursive_candidates(payload: Any, max_depth: int = 4, prefix: str = "analysis") -> Iterable[Tuple[str, Any]]:
    if max_depth < 0 or not isinstance(payload, Mapping):
        return
    for key, value in payload.items():
        key_text = str(key)
        lowered = key_text.lower()
        path = f"{prefix}.{key_text}"
        if any(token in lowered for token in _MATCHING_KEY_TOKENS):
            yield path, value
        if isinstance(value, Mapping):
            yield from _recursive_candidates(value, max_depth=max_depth - 1, prefix=path)


def parse_uploaded_calibration_file(uploaded: Any) -> Tuple[pd.DataFrame | None, str | None]:
    """Parse a Streamlit upload without importing Streamlit."""
    if uploaded is None:
        return None, None
    name = str(getattr(uploaded, "name", "uploaded_calibration.csv"))
    suffix = name.lower().rsplit(".", 1)[-1] if "." in name else "csv"
    try:
        if hasattr(uploaded, "seek"):
            uploaded.seek(0)
        if suffix in {"parquet", "pq"}:
            frame = pd.read_parquet(uploaded)
        elif suffix in {"xlsx", "xls"}:
            frame = pd.read_excel(uploaded)
        else:
            frame = pd.read_csv(uploaded)
    except Exception as exc:
        return None, f"Impossible de lire {name}: {exc}"
    if not _looks_like_price_frame(frame):
        return None, f"{name} ne contient pas de colonne de prix exploitable."
    return frame, None


def resolve_calibration_data(
    price_data: pd.DataFrame,
    analysis: Mapping[str, Any] | None = None,
    explicit_calibration_data: pd.DataFrame | None = None,
    uploaded_calibration_data: pd.DataFrame | None = None,
    provider_calibration_data: pd.DataFrame | None = None,
    provider_report: Mapping[str, Any] | None = None,
    source_mode: str = "auto",
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Resolve the calibration history with explicit, auditable priority.

    Auto priority: upload > application-supplied > automatic provider >
    recognized analysis history > display history. Provider failure is never
    hidden; its report is preserved even when another source is selected.
    """
    display = price_data.copy() if isinstance(price_data, pd.DataFrame) else pd.DataFrame()
    source_mode = str(source_mode or "auto").lower()
    report: Dict[str, Any] = {
        "mode": source_mode,
        "selected_source": "display_price_data",
        "selected_rows": int(len(display)),
        "display_rows": int(len(display)),
        "candidate_sources": [],
        "warnings": [],
        "auto_discovered": False,
        "provider_report": dict(provider_report or {}),
        "priority_contract": [
            "uploaded_calibration_file",
            "explicit_calibration_data",
            "provider_long_history",
            "analysis_history",
            "display_price_data",
        ],
    }

    candidates: list[Tuple[str, pd.DataFrame, int]] = []

    def add_candidate(source: str, value: Any, priority: int) -> None:
        frame = _to_dataframe(value)
        if not _looks_like_price_frame(frame):
            return
        candidates.append((source, frame, priority))
        report["candidate_sources"].append(
            {"source": source, "rows": int(len(frame)), "priority": priority}
        )

    if uploaded_calibration_data is not None:
        add_candidate("uploaded_calibration_file", uploaded_calibration_data, 100)
    if explicit_calibration_data is not None:
        add_candidate("explicit_calibration_data", explicit_calibration_data, 90)
    if provider_calibration_data is not None:
        provider_name = str((provider_report or {}).get("provider", "provider"))
        add_candidate(f"provider/{provider_name}", provider_calibration_data, 85)

    if isinstance(analysis, Mapping):
        seen_ids: set[int] = set()
        for path in _PRIORITY_PATHS:
            value = _read_path(analysis, path)
            if value is not None and id(value) not in seen_ids:
                seen_ids.add(id(value))
                add_candidate("analysis/" + ".".join(path), value, 80)
        for source, value in _recursive_candidates(analysis, max_depth=4):
            if id(value) in seen_ids:
                continue
            seen_ids.add(id(value))
            add_candidate(source, value, 70)

    add_candidate("display_price_data", display, 10)

    if provider_report:
        for warning in provider_report.get("warnings", []):
            report["warnings"].append(str(warning))
        if provider_report.get("status") == "FAILED":
            error = provider_report.get("error") or "unknown provider error"
            report["warnings"].append(f"Automatic provider unavailable: {error}")
        elif provider_report.get("status") == "STALE_CACHE_FALLBACK":
            report["warnings"].append("Automatic provider is using a stale cache fallback.")

    selected: Tuple[str, pd.DataFrame, int] | None
    if source_mode in {"display", "display_only", "price_data"}:
        selected = next((item for item in candidates if item[0] == "display_price_data"), None)
    elif source_mode in {"explicit", "application"}:
        selected = next((item for item in candidates if item[0] == "explicit_calibration_data"), None)
        if selected is None:
            report["warnings"].append("Calibration explicite demandée mais aucune série explicite n'a été fournie.")
            selected = next((item for item in candidates if item[0] == "display_price_data"), None)
    elif source_mode in {"uploaded", "upload"}:
        selected = next((item for item in candidates if item[0] == "uploaded_calibration_file"), None)
        if selected is None:
            report["warnings"].append("Calibration upload demandée mais aucun fichier exploitable n'a été fourni.")
            selected = next((item for item in candidates if item[0] == "display_price_data"), None)
    elif source_mode in {"provider", "automatic_provider"}:
        selected = next((item for item in candidates if item[0].startswith("provider/")), None)
        if selected is None:
            report["warnings"].append("Calibration provider demandée mais aucune série provider exploitable n'est disponible.")
            selected = next((item for item in candidates if item[0] == "display_price_data"), None)
    else:
        selected = max(candidates, key=lambda item: (item[2], len(item[1]))) if candidates else None

    if selected is None:
        report["warnings"].append("Aucune série de calibration exploitable; échantillon vide.")
        return pd.DataFrame(), report

    source, frame, _ = selected
    report["selected_source"] = source
    report["selected_rows"] = int(len(frame))
    report["auto_discovered"] = source.startswith("analysis/")
    if len(frame) <= len(display) and source != "display_price_data":
        report["warnings"].append(
            "La série de calibration sélectionnée n'est pas plus longue que la fenêtre d'affichage."
        )
    if source == "display_price_data":
        report["warnings"].append(
            "Aucun historique long indépendant détecté; la calibration utilise la fenêtre d'affichage."
        )
    report["warnings"] = list(dict.fromkeys(report["warnings"]))
    return frame.copy(), report
