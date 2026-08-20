"""Management / earnings-transcript intelligence for Company Intelligence V3.

Design goals
------------
* Lazy-load only inside the dedicated Management / Transcripts workspace.
* Prefer licensed/structured transcript providers already configured in the terminal.
* Never fabricate a transcript from news, filings, or model knowledge.
* Keep local analytics deterministic and auditable: speaker roles, prepared-vs-Q&A,
  tone/uncertainty, guidance language, theme exposure, and quarter-over-quarter deltas.
* Provider sentiment (Alpha Vantage) is used when supplied, otherwise a transparent
  finance-oriented lexical fallback is used.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
import requests

from .common import safe_float, safe_int, first_present_flexible
from .providers import get_fmp_api_key, get_alpha_vantage_api_key, get_finnhub_api_key
from .transcript_cache import (
    clear_provider_circuit,
    list_cached_transcripts,
    load_transcript_payload,
    next_utc_day_reset,
    open_provider_circuit,
    provider_circuit,
    provider_circuit_table,
    save_transcript_payload,
    transcript_cache_root,
)

FMP_STABLE_BASE = "https://financialmodelingprep.com/stable"
ALPHA_URL = "https://www.alphavantage.co/query"
FINNHUB_BASE = "https://finnhub.io/api/v1"


# -----------------------------------------------------------------------------
# Provider access
# -----------------------------------------------------------------------------

def _provider_error(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    low = str(payload).lower()
    return any(k in payload for k in ["Error Message", "Note", "Information", "error"]) or (
        "limit" in low and ("exceed" in low or "rate" in low)
    ) or "invalid api key" in low or "access denied" in low


def _payload_reason(payload: Any, http_status: int | None = None, fallback: str = "Unavailable") -> str:
    if isinstance(payload, dict):
        for key in ["Error Message", "Information", "Note", "error", "message"]:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                text = re.sub(r"\s+", " ", value).strip()
                return text[:220]
    if http_status and int(http_status) >= 400:
        return f"HTTP {int(http_status)}"
    if payload in ({}, [], None, ""):
        return "Empty / no entitled payload"
    return fallback


def _request_json(url: str, params: dict, timeout: int = 25) -> dict[str, Any]:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        status = int(r.status_code)
        try:
            payload = r.json()
        except Exception:
            payload = {}
        if status >= 400 or _provider_error(payload):
            return {"ok": False, "payload": payload, "http_status": status, "reason": _payload_reason(payload, status)}
        return {"ok": bool(payload), "payload": payload, "http_status": status, "reason": "OK" if payload else "Empty / no entitled payload"}
    except Exception as exc:
        return {"ok": False, "payload": {}, "http_status": None, "reason": f"{type(exc).__name__}: {str(exc)[:180]}"}


def _fmp_transcript_dates_result(symbol: str) -> dict[str, Any]:
    key = get_fmp_api_key()
    if not key:
        return {"ok": False, "payload": [], "reason": "FMP API key not configured", "http_status": None}
    result = _request_json(
        f"{FMP_STABLE_BASE}/earning-call-transcript-dates",
        {"symbol": symbol.upper().strip(), "apikey": key},
        timeout=18,
    )
    payload = result.get("payload")
    rows = []
    if isinstance(payload, list):
        rows = [x for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict):
        for k in ["data", "results", "items"]:
            if isinstance(payload.get(k), list):
                rows = [x for x in payload[k] if isinstance(x, dict)]
                break
    result["rows"] = rows
    result["ok"] = bool(rows)
    if not rows and result.get("reason") == "OK":
        result["reason"] = "No transcript-date rows returned"
    return result


def _fmp_transcript_result(symbol: str, year: int, quarter: int) -> dict[str, Any]:
    key = get_fmp_api_key()
    if not key:
        return {"ok": False, "payload": [], "reason": "FMP API key not configured", "http_status": None}
    return _request_json(
        f"{FMP_STABLE_BASE}/earning-call-transcript",
        {"symbol": symbol.upper().strip(), "year": int(year), "quarter": int(quarter), "apikey": key},
        timeout=25,
    )


def _alpha_transcript_result(symbol: str, quarter: str) -> dict[str, Any]:
    key = get_alpha_vantage_api_key()
    if not key:
        return {"ok": False, "payload": {}, "reason": "Alpha Vantage API key not configured", "http_status": None}
    return _request_json(
        ALPHA_URL,
        {"function": "EARNINGS_CALL_TRANSCRIPT", "symbol": symbol.upper().strip(), "quarter": quarter, "apikey": key},
        timeout=25,
    )


def _finnhub_transcript_list_result(symbol: str) -> dict[str, Any]:
    key = get_finnhub_api_key()
    if not key:
        return {"ok": False, "payload": {}, "reason": "Finnhub API key not configured", "http_status": None, "rows": []}
    result = _request_json(
        f"{FINNHUB_BASE}/stock/transcripts/list",
        {"symbol": symbol.upper().strip(), "token": key},
        timeout=20,
    )
    payload = result.get("payload")
    rows = []
    if isinstance(payload, dict) and isinstance(payload.get("transcripts"), list):
        rows = [x for x in payload["transcripts"] if isinstance(x, dict)]
    elif isinstance(payload, list):
        rows = [x for x in payload if isinstance(x, dict)]
    result["rows"] = rows
    result["ok"] = bool(rows)
    if not rows and result.get("reason") == "OK":
        result["reason"] = "No transcript metadata returned (endpoint may require Finnhub Premium)"
    return result


def _finnhub_transcript_result(transcript_id: str) -> dict[str, Any]:
    key = get_finnhub_api_key()
    if not key:
        return {"ok": False, "payload": {}, "reason": "Finnhub API key not configured", "http_status": None}
    return _request_json(
        f"{FINNHUB_BASE}/stock/transcripts",
        {"id": transcript_id, "token": key},
        timeout=25,
    )


# -----------------------------------------------------------------------------
# Quarter resolution
# -----------------------------------------------------------------------------

def _date_from_any(value: Any) -> pd.Timestamp | None:
    dt = pd.to_datetime(value, errors="coerce")
    if pd.isna(dt):
        return None
    return pd.Timestamp(dt).tz_localize(None) if getattr(pd.Timestamp(dt), "tzinfo", None) else pd.Timestamp(dt)


def _latest_fiscal_year_end(company: dict) -> pd.Timestamp | None:
    raw = company.get("raw_data", {}) if isinstance(company, dict) else {}
    alpha = raw.get("alpha", {}) if isinstance(raw, dict) else {}
    income = alpha.get("income_statement", {}) if isinstance(alpha, dict) else {}
    annual = income.get("annualReports", []) if isinstance(income, dict) else []
    if isinstance(annual, list):
        for row in annual:
            if isinstance(row, dict):
                dt = _date_from_any(row.get("fiscalDateEnding"))
                if dt is not None:
                    return dt

    fmp = raw.get("fmp", {}) if isinstance(raw, dict) else {}
    rows = fmp.get("income_annual", []) if isinstance(fmp, dict) else []
    if isinstance(rows, list):
        dates = []
        for row in rows:
            if isinstance(row, dict):
                dt = _date_from_any(first_present_flexible(row, ["date", "fillingDate", "filingDate"]))
                if dt is not None:
                    dates.append(dt)
        if dates:
            return max(dates)
    return None


def _quarter_label_from_date(date: pd.Timestamp, fiscal_year_end: pd.Timestamp | None) -> str:
    """Infer Alpha Vantage fiscal quarter labels from a reported quarter-end date.

    The mapping is exact for standard 3-month fiscal calendars and robust to non-calendar
    fiscal years (e.g. January year-end). If a fiscal year-end cannot be inferred, calendar
    quarter is used as a transparent fallback.
    """
    date = pd.Timestamp(date)
    if fiscal_year_end is None:
        q = (date.month - 1) // 3 + 1
        return f"{date.year}Q{q}"

    fy_month = fiscal_year_end.month
    fy_day = fiscal_year_end.day
    fiscal_year = date.year if (date.month, date.day) <= (fy_month, fy_day) else date.year + 1
    months_until_end = (fy_month - date.month) % 12
    # quarter ends should sit near 0/3/6/9 months before fiscal year-end.
    bucket = int(round(months_until_end / 3.0))
    bucket = min(3, max(0, bucket))
    quarter = 4 - bucket
    return f"{fiscal_year}Q{quarter}"


def _candidate_alpha_quarters(company: dict, limit: int = 8) -> list[str]:
    raw = company.get("raw_data", {}) if isinstance(company, dict) else {}
    alpha = raw.get("alpha", {}) if isinstance(raw, dict) else {}
    earnings = alpha.get("earnings", {}) if isinstance(alpha, dict) else {}
    rows = earnings.get("quarterlyEarnings", []) if isinstance(earnings, dict) else []
    fiscal_end = _latest_fiscal_year_end(company)
    out: list[str] = []

    if isinstance(rows, list):
        dated = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            dt = _date_from_any(first_present_flexible(row, ["fiscalDateEnding", "reportedDate", "reportDate"]))
            if dt is not None:
                dated.append(dt)
        for dt in sorted(dated, reverse=True):
            label = _quarter_label_from_date(dt, fiscal_end)
            if label not in out:
                out.append(label)
            if len(out) >= limit:
                return out

    # Fallback around the current calendar quarter, plus one-year-ahead fiscal labels to
    # support January/February fiscal year ends without burning many requests.
    now = pd.Timestamp.utcnow().tz_localize(None)
    q = (now.month - 1) // 3 + 1
    y = now.year
    for shift in range(0, 8):
        qq = q - shift
        yy = y
        while qq <= 0:
            qq += 4
            yy -= 1
        for candidate in [f"{yy}Q{qq}", f"{yy + 1}Q{qq}"]:
            if candidate not in out:
                out.append(candidate)
            if len(out) >= limit:
                return out
    return out[:limit]


def _normalize_fmp_date_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        year = safe_int(first_present_flexible(row, ["year", "fiscalYear", "calendarYear"]))
        quarter = safe_int(first_present_flexible(row, ["quarter", "fiscalQuarter"]))
        date = _date_from_any(first_present_flexible(row, ["date", "transcriptDate", "reportedDate"]))
        if year is None or quarter is None:
            continue
        out.append({
            "year": int(year),
            "quarter": int(quarter),
            "quarter_label": f"{int(year)}Q{int(quarter)}",
            "date": date,
        })
    out.sort(key=lambda x: (x.get("date") or pd.Timestamp.min, x["year"], x["quarter"]), reverse=True)
    return out


# -----------------------------------------------------------------------------
# Transcript normalization
# -----------------------------------------------------------------------------

def _normalize_finnhub_payload(payload: Any) -> pd.DataFrame:
    """Normalize Finnhub transcript content into the common turn schema.

    Finnhub returns a participant list plus transcript entries with speaker name and
    ``speech`` arrays. The parser preserves each speech item as a distinct turn and
    carries participant descriptions into the Title field when available.
    """
    if not isinstance(payload, dict):
        return pd.DataFrame(columns=["Speaker", "Title", "Content", "Provider Sentiment", "Provider Sentiment Label"])
    participants = payload.get("participant", [])
    title_map: dict[str, str] = {}
    if isinstance(participants, list):
        for row in participants:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            desc = str(row.get("description") or "").strip()
            if name:
                title_map[name.lower()] = desc
    transcript = payload.get("transcript", [])
    rows = []
    if isinstance(transcript, list):
        for entry in transcript:
            if not isinstance(entry, dict):
                continue
            speaker = str(entry.get("name") or entry.get("speaker") or "Unknown").strip() or "Unknown"
            speech = entry.get("speech")
            chunks = speech if isinstance(speech, list) else [speech] if isinstance(speech, str) else []
            for chunk in chunks:
                if not isinstance(chunk, str) or len(chunk.strip()) < 2:
                    continue
                rows.append({
                    "Speaker": speaker,
                    "Title": title_map.get(speaker.lower(), ""),
                    "Content": re.sub(r"\s+", " ", chunk).strip(),
                    "Provider Sentiment": np.nan,
                    "Provider Sentiment Label": "",
                })
    return pd.DataFrame(rows)

SPEAKER_LINE = re.compile(r"^\s*([A-Z][A-Za-z0-9 .,'&/()\-]{1,80})\s*:\s*(.+)$")


def _payload_records(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for k in ["transcript", "data", "results", "items"]:
            v = payload.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        return [payload]
    return []


def _extract_raw_text(payload: Any) -> str:
    for row in _payload_records(payload):
        for key in ["content", "transcript", "text", "body"]:
            value = row.get(key)
            if isinstance(value, str) and len(value.strip()) > 20:
                return value.strip()
    if isinstance(payload, str):
        return payload.strip()
    return ""


def _parse_text_turns(text: str) -> pd.DataFrame:
    if not text:
        return pd.DataFrame(columns=["Speaker", "Title", "Content", "Provider Sentiment", "Provider Sentiment Label"])

    lines = [re.sub(r"\s+", " ", x).strip() for x in re.split(r"[\r\n]+", text) if x.strip()]
    rows: list[dict] = []
    current_speaker = "Management"
    current: list[str] = []

    def flush():
        nonlocal current
        if current:
            rows.append({
                "Speaker": current_speaker,
                "Title": "",
                "Content": " ".join(current).strip(),
                "Provider Sentiment": None,
                "Provider Sentiment Label": "",
            })
            current = []

    for line in lines:
        m = SPEAKER_LINE.match(line)
        if m and len(m.group(2)) > 8:
            flush()
            current_speaker = m.group(1).strip()
            current = [m.group(2).strip()]
        else:
            current.append(line)
    flush()
    return pd.DataFrame(rows)


def _normalize_turns(payload: Any, provider: str) -> pd.DataFrame:
    if "finnhub" in str(provider).lower():
        return _normalize_finnhub_payload(payload)
    rows = _payload_records(payload)
    normalized: list[dict] = []

    # Alpha Vantage exposes turn-by-turn transcript rows with sentiment; FMP commonly
    # returns one full-text content row. Accept both shapes defensively.
    for row in rows:
        content = first_present_flexible(row, ["content", "text", "utterance", "sentence"])
        speaker = first_present_flexible(row, ["speaker", "speakerName", "name"])
        title = first_present_flexible(row, ["title", "speakerTitle", "role"])
        sentiment = first_present_flexible(row, ["sentiment", "sentiment_score", "sentimentScore"])
        sentiment_label = first_present_flexible(row, ["sentiment_label", "sentimentLabel", "label"])
        if isinstance(content, str) and content.strip() and (speaker or len(rows) > 1):
            normalized.append({
                "Speaker": str(speaker or "Unknown").strip(),
                "Title": str(title or "").strip(),
                "Content": content.strip(),
                "Provider Sentiment": sentiment,
                "Provider Sentiment Label": str(sentiment_label or "").strip(),
            })

    if normalized:
        return pd.DataFrame(normalized)

    return _parse_text_turns(_extract_raw_text(payload))


# -----------------------------------------------------------------------------
# Deterministic text analytics
# -----------------------------------------------------------------------------

POSITIVE = {
    "accelerate", "accelerating", "benefit", "confidence", "confident", "demand", "expand",
    "growth", "improve", "improved", "improving", "momentum", "opportunity", "outperform",
    "record", "resilient", "robust", "strong", "strength", "upside", "visibility", "win", "wins",
}
NEGATIVE = {
    "challenge", "challenging", "decline", "delay", "deteriorate", "downturn", "headwind",
    "loss", "pressure", "risk", "slow", "slowing", "soft", "softness", "uncertain", "uncertainty",
    "weak", "weakness", "constraint", "constrained", "shortage", "volatile", "volatility",
}
UNCERTAINTY = {
    "may", "might", "could", "uncertain", "uncertainty", "visibility", "depending", "depends",
    "approximately", "roughly", "potential", "possible", "possibly", "range", "assume", "assuming",
}
CONFIDENCE = {
    "expect", "expects", "expected", "confident", "confidence", "will", "target", "committed",
    "on track", "strong conviction", "clear visibility", "we believe", "we continue to expect",
}
EVASIVE_PHRASES = [
    "not going to comment", "can't comment", "cannot comment", "won't comment", "too early to",
    "not prepared to", "not in a position to", "we don't disclose", "we do not disclose",
    "we haven't provided", "we have not provided", "hard to say", "difficult to say",
    "as we said before", "as we've said", "as we have said", "we'll see", "we will see",
]
GUIDANCE_MARKERS = [
    "guidance", "outlook", "we expect", "we anticipate", "we forecast", "we project", "we target",
    "we continue to expect", "looking ahead", "for the quarter", "for the year", "next quarter",
]

THEMES = {
    "Demand": ["demand", "orders", "backlog", "bookings", "pipeline", "consumption", "utilization"],
    "Margins": ["gross margin", "operating margin", "margin", "mix", "cost", "costs", "profitability"],
    "Pricing": ["pricing", "price", "asp", "average selling price", "discount", "discounting"],
    "Supply": ["supply", "capacity", "constraint", "constraints", "shortage", "lead time", "foundry", "inventory"],
    "Capex / Investment": ["capex", "capital expenditure", "investment", "investing", "infrastructure", "capacity expansion"],
    "China / Regulation": ["china", "export control", "regulation", "regulatory", "license", "geopolitical", "sanction"],
    "AI / Product": ["artificial intelligence", " ai ", "accelerator", "gpu", "product roadmap", "platform", "launch"],
    "Competition": ["competition", "competitive", "competitor", "market share", "share gain", "share loss"],
}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z'\-]*", str(text).lower())


def _count_phrase(text_low: str, phrase: str) -> int:
    if " " in phrase:
        return text_low.count(phrase)
    return len(re.findall(rf"\b{re.escape(phrase)}\b", text_low))


def _provider_sentiment_number(value: Any, label: str = "") -> float | None:
    num = safe_float(value)
    if num is not None:
        # Alpha-like scores are generally centered around zero. Clamp aggressively.
        return float(np.clip(num, -1.0, 1.0))
    low = str(label or value or "").lower()
    if "positive" in low or "bullish" in low:
        return 0.45
    if "negative" in low or "bearish" in low:
        return -0.45
    if "neutral" in low:
        return 0.0
    return None


def _text_metrics(text: str, provider_sentiment: Any = None, provider_label: str = "") -> dict[str, float]:
    text_low = f" {str(text).lower()} "
    toks = _tokens(text)
    n = max(1, len(toks))
    pos = sum(_count_phrase(text_low, x) for x in POSITIVE)
    neg = sum(_count_phrase(text_low, x) for x in NEGATIVE)
    unc = sum(_count_phrase(text_low, x) for x in UNCERTAINTY)
    conf = sum(_count_phrase(text_low, x) for x in CONFIDENCE)
    evasive = sum(text_low.count(x) for x in EVASIVE_PHRASES)

    lexical = (pos - neg) / max(2.0, math.sqrt(n))
    lexical = float(np.tanh(lexical / 2.2))
    p_sent = _provider_sentiment_number(provider_sentiment, provider_label)
    tone = lexical if p_sent is None else 0.65 * p_sent + 0.35 * lexical

    return {
        "word_count": float(n),
        "tone": float(np.clip(tone, -1, 1)),
        "positive_hits": float(pos),
        "negative_hits": float(neg),
        "uncertainty_per_100": 100.0 * unc / n,
        "confidence_per_100": 100.0 * conf / n,
        "evasive_hits": float(evasive),
        "provider_sentiment_available": 1.0 if p_sent is not None else 0.0,
    }


def _management_names(company: dict) -> set[str]:
    inst = company.get("institutional", {}) if isinstance(company, dict) else {}
    gov = inst.get("governance", {}) if isinstance(inst, dict) else {}
    df = gov.get("executives", pd.DataFrame()) if isinstance(gov, dict) else pd.DataFrame()
    names: set[str] = set()
    if isinstance(df, pd.DataFrame) and not df.empty:
        col = next((c for c in ["name", "Name"] if c in df.columns), None)
        if col:
            for x in df[col].dropna().astype(str):
                clean = re.sub(r"[^a-z ]", "", x.lower())
                parts = [p for p in clean.split() if len(p) > 1 and p not in {"mr", "ms", "mrs", "dr", "prof"}]
                if parts:
                    names.add(" ".join(parts))
                    names.add(parts[-1])
    return names


def _classify_roles_and_phase(turns: pd.DataFrame, company: dict) -> pd.DataFrame:
    if turns.empty:
        return turns.copy()
    names = _management_names(company)
    out = turns.copy().reset_index(drop=True)
    phase = "Prepared"
    roles = []
    phases = []
    for _, row in out.iterrows():
        speaker = str(row.get("Speaker", ""))
        title = str(row.get("Title", ""))
        content = str(row.get("Content", ""))
        low = f"{speaker} {title}".lower()
        content_low = content.lower()

        if "question-and-answer" in content_low or "question and answer" in content_low or "q&a session" in content_low:
            phase = "Q&A"

        speaker_clean = re.sub(r"[^a-z ]", "", speaker.lower()).strip()
        is_management_name = any(n and (n in speaker_clean or speaker_clean.endswith(n)) for n in names)
        management_title = any(x in low for x in [
            "chief executive", "ceo", "chief financial", "cfo", "president", "vice president", " vp",
            "chief operating", "coo", "founder", "officer", "investor relations",
        ])
        if "operator" in low:
            role = "Operator"
        elif "analyst" in low:
            role = "Analyst"
        elif is_management_name or management_title:
            role = "Management"
        elif phase == "Q&A" and speaker.strip() and speaker.lower() not in {"management", "unknown"}:
            # Once Q&A begins, unknown external speakers are more likely analysts. A later
            # answer from a known executive will still be classified as Management above.
            role = "Analyst"
        else:
            role = "Management" if speaker.lower() in {"management", "unknown"} else "Other"

        roles.append(role)
        phases.append(phase)
    out["Role"] = roles
    out["Phase"] = phases
    return out


def _annotate_turns(turns: pd.DataFrame, company: dict) -> pd.DataFrame:
    turns = _classify_roles_and_phase(turns, company)
    if turns.empty:
        return turns
    metrics = []
    for _, row in turns.iterrows():
        metrics.append(_text_metrics(
            row.get("Content", ""),
            row.get("Provider Sentiment"),
            row.get("Provider Sentiment Label", ""),
        ))
    mdf = pd.DataFrame(metrics)
    for col in mdf.columns:
        turns[col] = mdf[col].values
    return turns


def _weighted_mean(df: pd.DataFrame, col: str, weight: str = "word_count") -> float | None:
    if df.empty or col not in df.columns:
        return None
    vals = pd.to_numeric(df[col], errors="coerce")
    w = pd.to_numeric(df.get(weight), errors="coerce").fillna(1.0)
    mask = vals.notna() & w.notna() & (w > 0)
    if not mask.any():
        return None
    return float(np.average(vals[mask], weights=w[mask]))


def _score_from_tone(tone: float | None) -> float | None:
    if tone is None:
        return None
    return round(float(np.clip(50 + 45 * tone, 0, 100)), 1)


def _sentence_split(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+", str(text)) if len(x.strip()) >= 25]


def _guidance_evidence(turns: pd.DataFrame, max_rows: int = 12) -> pd.DataFrame:
    rows = []
    if turns.empty:
        return pd.DataFrame()
    mgmt = turns[turns["Role"].eq("Management")] if "Role" in turns.columns else turns
    for _, row in mgmt.iterrows():
        for sentence in _sentence_split(row.get("Content", "")):
            low = sentence.lower()
            if any(marker in low for marker in GUIDANCE_MARKERS):
                tm = _text_metrics(sentence)
                rows.append({
                    "Speaker": row.get("Speaker", ""),
                    "Phase": row.get("Phase", ""),
                    "Tone": round(tm["tone"], 3),
                    "Uncertainty /100w": round(tm["uncertainty_per_100"], 2),
                    "Guidance Evidence": sentence[:420],
                })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["_rank"] = df["Tone"].abs() + 0.05 * df["Uncertainty /100w"]
    return df.sort_values("_rank", ascending=False).drop(columns="_rank").head(max_rows).reset_index(drop=True)


def _guidance_score(evidence: pd.DataFrame) -> float | None:
    if not isinstance(evidence, pd.DataFrame) or evidence.empty:
        return None
    tone = pd.to_numeric(evidence["Tone"], errors="coerce").mean()
    unc = pd.to_numeric(evidence["Uncertainty /100w"], errors="coerce").mean()
    if pd.isna(tone):
        return None
    score = 50 + 38 * float(tone) - 2.5 * float(unc if pd.notna(unc) else 0)
    return round(float(np.clip(score, 0, 100)), 1)


def _qa_diagnostics(turns: pd.DataFrame) -> dict[str, float | None]:
    if turns.empty:
        return {"pressure_score": None, "evasiveness_score": None, "question_count": 0, "answer_count": 0}
    qa = turns[turns["Phase"].eq("Q&A")] if "Phase" in turns.columns else pd.DataFrame()
    if qa.empty:
        return {"pressure_score": None, "evasiveness_score": None, "question_count": 0, "answer_count": 0}
    analysts = qa[qa["Role"].eq("Analyst")]
    mgmt = qa[qa["Role"].eq("Management")]
    analyst_tone = _weighted_mean(analysts, "tone")
    analyst_unc = _weighted_mean(analysts, "uncertainty_per_100")
    evasive_hits = pd.to_numeric(mgmt.get("evasive_hits"), errors="coerce").fillna(0).sum() if not mgmt.empty else 0
    answer_words = pd.to_numeric(mgmt.get("word_count"), errors="coerce").fillna(0).sum() if not mgmt.empty else 0
    evasive_rate_per_100 = 100.0 * float(evasive_hits) / max(1.0, float(answer_words))
    # One explicit non-answer phrase in a ~20-word answer is material but should not
    # automatically saturate the diagnostic. Roughly 1 hit / 20 words maps to ~50/100.
    evasiveness = float(np.clip(10.0 * evasive_rate_per_100, 0, 100))

    # Pressure rises with negative analyst tone, uncertainty/challenge language and
    # management evasiveness. This is descriptive, not a price-direction signal.
    pressure = 35.0
    if analyst_tone is not None:
        pressure += max(0.0, -analyst_tone) * 35
    if analyst_unc is not None:
        pressure += min(20.0, analyst_unc * 3.0)
    pressure += evasiveness * 0.25
    pressure = float(np.clip(pressure, 0, 100))
    return {
        "pressure_score": round(pressure, 1),
        "evasiveness_score": round(evasiveness, 1),
        "question_count": int(len(analysts)),
        "answer_count": int(len(mgmt)),
    }


def _theme_table(turns: pd.DataFrame) -> pd.DataFrame:
    if turns.empty:
        return pd.DataFrame()
    rows = []
    for theme, terms in THEMES.items():
        hit_turns = []
        total_hits = 0
        for idx, row in turns.iterrows():
            low = f" {str(row.get('Content', '')).lower()} "
            hits = sum(_count_phrase(low, t) for t in terms)
            if hits:
                total_hits += hits
                hit_turns.append(idx)
        if not hit_turns:
            rows.append({"Theme": theme, "Mentions": 0, "Tone": None, "Management Mentions": 0, "Q&A Mentions": 0})
            continue
        sub = turns.loc[hit_turns]
        rows.append({
            "Theme": theme,
            "Mentions": int(total_hits),
            "Tone": round(_weighted_mean(sub, "tone") or 0, 3),
            "Management Mentions": int(sub["Role"].eq("Management").sum()),
            "Q&A Mentions": int(sub["Phase"].eq("Q&A").sum()),
        })
    return pd.DataFrame(rows)


def _speaker_table(turns: pd.DataFrame) -> pd.DataFrame:
    if turns.empty:
        return pd.DataFrame()
    rows = []
    for (speaker, role), sub in turns.groupby(["Speaker", "Role"], dropna=False):
        rows.append({
            "Speaker": speaker,
            "Role": role,
            "Turns": int(len(sub)),
            "Words": int(pd.to_numeric(sub["word_count"], errors="coerce").fillna(0).sum()),
            "Tone Score": _score_from_tone(_weighted_mean(sub, "tone")),
            "Uncertainty /100w": round(_weighted_mean(sub, "uncertainty_per_100") or 0, 2),
            "Provider Sentiment Coverage": round(100 * pd.to_numeric(sub["provider_sentiment_available"], errors="coerce").mean(), 1),
        })
    return pd.DataFrame(rows).sort_values(["Role", "Words"], ascending=[True, False]).reset_index(drop=True)


def _quarter_summary(turns: pd.DataFrame) -> dict[str, Any]:
    if turns.empty:
        return {}
    mgmt = turns[turns["Role"].eq("Management")]
    prepared = mgmt[mgmt["Phase"].eq("Prepared")]
    qa_mgmt = mgmt[mgmt["Phase"].eq("Q&A")]
    guidance = _guidance_evidence(turns)
    qa = _qa_diagnostics(turns)

    mgmt_tone = _score_from_tone(_weighted_mean(mgmt, "tone"))
    prepared_tone = _score_from_tone(_weighted_mean(prepared, "tone"))
    qa_tone = _score_from_tone(_weighted_mean(qa_mgmt, "tone"))
    unc = _weighted_mean(mgmt, "uncertainty_per_100")
    q_and_a_delta = None if prepared_tone is None or qa_tone is None else round(qa_tone - prepared_tone, 1)
    return {
        "management_tone": mgmt_tone,
        "prepared_tone": prepared_tone,
        "qa_management_tone": qa_tone,
        "prepared_to_qa_delta": q_and_a_delta,
        "guidance_confidence": _guidance_score(guidance),
        "qa_pressure": qa.get("pressure_score"),
        "evasiveness": qa.get("evasiveness_score"),
        "management_uncertainty_per_100": round(unc, 2) if unc is not None else None,
        "turns": int(len(turns)),
        "management_turns": int(len(mgmt)),
        "analyst_turns": int(turns["Role"].eq("Analyst").sum()),
        "provider_sentiment_coverage": round(100 * pd.to_numeric(turns["provider_sentiment_available"], errors="coerce").mean(), 1),
        "guidance_evidence_count": int(len(guidance)),
        "qa_question_count": qa.get("question_count", 0),
    }


def _data_confidence(record: dict, summary: dict, previous_available: bool) -> dict[str, float]:
    provider = str(record.get("provider", "")).lower()
    source_quality = 90 if "alpha" in provider else 85 if "fmp" in provider else 50
    turns = safe_int(summary.get("turns"), 0) or 0
    mgmt_turns = safe_int(summary.get("management_turns"), 0) or 0
    analyst_turns = safe_int(summary.get("analyst_turns"), 0) or 0
    coverage = min(100, 35 + min(30, turns) * 1.5 + min(20, mgmt_turns) * 1.0)
    if analyst_turns > 0:
        coverage += 10
    coverage = min(100, coverage)
    speaker_quality = 90 if mgmt_turns >= 3 and (analyst_turns >= 2 or summary.get("qa_pressure") is None) else 60
    sentiment_cov = safe_float(summary.get("provider_sentiment_coverage"), 0) or 0
    analytics_quality = min(100, 70 + sentiment_cov * 0.25)
    comparison = 100 if previous_available else 55
    overall = 0.30 * source_quality + 0.30 * coverage + 0.20 * speaker_quality + 0.10 * analytics_quality + 0.10 * comparison
    return {
        "overall": round(float(np.clip(overall, 0, 100)), 1),
        "source_quality": float(source_quality),
        "coverage": round(float(coverage), 1),
        "speaker_quality": float(speaker_quality),
        "analytics_quality": round(float(analytics_quality), 1),
        "comparison": float(comparison),
    }


# -----------------------------------------------------------------------------
# History acquisition and V3 bundle
# -----------------------------------------------------------------------------

def _record_from_payload(symbol: str, quarter_label: str, provider: str, payload: Any, company: dict, date=None) -> dict | None:
    turns = _normalize_turns(payload, provider)
    if turns.empty:
        return None
    turns = _annotate_turns(turns, company)
    summary = _quarter_summary(turns)
    theme = _theme_table(turns)
    return {
        "symbol": symbol.upper(),
        "quarter": quarter_label,
        "date": _date_from_any(date),
        "provider": provider,
        "turns": turns,
        "summary": summary,
        "themes": theme,
        "guidance": _guidance_evidence(turns),
        "speakers": _speaker_table(turns),
    }


def _attempt_row(provider: str, quarter: str, result: dict[str, Any], status: str | None = None) -> dict[str, Any]:
    return {
        "Provider": provider,
        "Quarter": quarter,
        "Status": status or ("OK" if result.get("ok") else "Unavailable"),
        "Reason": str(result.get("reason") or "")[:220],
        "HTTP": result.get("http_status"),
    }


def _circuit_attempt(provider: str, quarter: str, state: dict[str, Any]) -> dict[str, Any]:
    return {
        "Provider": provider,
        "Quarter": quarter,
        "Status": "Circuit open",
        "Reason": f"{state.get('reason', 'Provider temporarily disabled')} · retry after {state.get('open_until', 'cooldown')}",
        "HTTP": state.get("http_status"),
    }


def _should_trip_circuit(provider: str, result: dict[str, Any]) -> dict[str, Any] | None:
    """Return a circuit policy when a failure is quota/entitlement-like.

    Empty transcript payloads are *not* circuit-worthy: a quarter can legitimately have no
    call.  We only suppress further calls when the provider has explicitly told us that more
    requests will be useless or harmful.
    """
    if not isinstance(result, dict) or result.get("ok"):
        return None
    reason = str(result.get("reason") or "").lower()
    status = safe_int(result.get("http_status"))
    provider_l = str(provider or "").lower()

    daily_markers = [
        "25 requests per day", "daily limit", "per day", "daily api", "standard api rate limit",
    ]
    entitlement_markers = [
        "upgrade your plan", "premium", "not entitled", "entitlement", "access denied",
        "subscription", "limit reach", "plan limit",
    ]
    invalid_key_markers = ["invalid api key", "api key is invalid", "apikey invalid", "unauthorized"]

    if "alpha" in provider_l and any(x in reason for x in daily_markers):
        return {
            "kind": "daily_quota",
            "until": next_utc_day_reset(5),
        }
    if any(x in reason for x in invalid_key_markers) or status in {401, 403}:
        return {"kind": "auth_or_entitlement", "seconds": 24 * 3600}
    if any(x in reason for x in entitlement_markers):
        return {"kind": "entitlement_or_quota", "seconds": 24 * 3600}
    if status == 429:
        # Generic rate-limit fallback. FMP's current "Limit Reach" wording is caught above.
        return {"kind": "rate_limit", "seconds": 3600}
    if "rate limit" in reason or "too many request" in reason:
        return {"kind": "rate_limit", "seconds": 3600}
    return None


def _trip_circuit_if_needed(provider: str, result: dict[str, Any]) -> bool:
    policy = _should_trip_circuit(provider, result)
    if not policy:
        return False
    kwargs = {k: v for k, v in policy.items() if k in {"kind", "seconds", "until"}}
    open_provider_circuit(
        provider,
        str(result.get("reason") or "Provider limit / entitlement failure"),
        http_status=safe_int(result.get("http_status")),
        **kwargs,
    )
    return True


def _cached_records(symbol: str, company: dict) -> tuple[list[dict], list[dict]]:
    records: list[dict] = []
    attempts: list[dict] = []
    for meta in list_cached_transcripts(symbol):
        quarter = str(meta.get("quarter") or "").strip()
        if not quarter:
            continue
        entry = load_transcript_payload(symbol, quarter)
        if not isinstance(entry, dict):
            continue
        provider = str(entry.get("provider") or meta.get("provider") or "Cache")
        rec = _record_from_payload(
            symbol,
            quarter,
            provider,
            entry.get("raw_payload"),
            company,
            entry.get("call_date"),
        )
        if rec:
            rec["cache_retrieved_at"] = entry.get("retrieved_at")
            rec["cache_checksum"] = entry.get("checksum")
            records.append(rec)
            attempts.append({
                "Provider": "Cache",
                "Quarter": quarter,
                "Status": "Hit",
                "Reason": f"Persistent transcript cache · source {provider} · retrieved {entry.get('retrieved_at', 'N/A')}",
                "HTTP": None,
            })
    return records, attempts


def _save_provider_record(symbol: str, quarter: str, provider: str, result: dict[str, Any], company: dict, date=None) -> dict | None:
    if not result.get("ok"):
        return None
    rec = _record_from_payload(symbol, quarter, provider, result.get("payload"), company, date)
    if rec is None:
        return None
    save_result = save_transcript_payload(
        symbol,
        quarter,
        provider,
        result.get("payload"),
        call_date=date,
        immutable=True,
    )
    rec["cache_saved"] = bool(save_result.get("ok"))
    rec["cache_path"] = save_result.get("path")
    return rec


def _latest_target_quarter(company: dict) -> str | None:
    labels = _candidate_alpha_quarters(company, limit=1)
    return labels[0] if labels else None


def _fmp_latest_record(symbol: str, company: dict, existing_quarters: set[str], target_quarter: str | None) -> tuple[list[dict], list[dict]]:
    """Probe FMP at most once for metadata and once for one transcript.

    A quota/entitlement response immediately opens the persistent FMP circuit and prevents
    direct-quarter fan-out.  This is the V3.2 provider-budget contract.
    """
    attempts: list[dict] = []
    records: list[dict] = []
    state = provider_circuit("FMP")
    if state.get("open"):
        attempts.append(_circuit_attempt("FMP", "latest", state))
        return records, attempts

    dates_result = _fmp_transcript_dates_result(symbol)
    dates = _normalize_fmp_date_rows(dates_result.get("rows", []))
    attempts.append(_attempt_row("FMP", "dates feed", dates_result))
    if not dates_result.get("ok") and _trip_circuit_if_needed("FMP", dates_result):
        return records, attempts

    meta = None
    if dates:
        for row in dates:
            if str(row.get("quarter_label")) not in existing_quarters:
                meta = row
                break
        if meta is None:
            return records, attempts
    elif target_quarter and target_quarter not in existing_quarters:
        m = re.match(r"(\d{4})Q([1-4])", target_quarter)
        if m:
            meta = {
                "year": int(m.group(1)),
                "quarter": int(m.group(2)),
                "quarter_label": target_quarter,
                "date": None,
            }

    if not meta:
        return records, attempts

    result = _fmp_transcript_result(symbol, int(meta["year"]), int(meta["quarter"]))
    attempts.append(_attempt_row("FMP direct", str(meta["quarter_label"]), result))
    if not result.get("ok"):
        _trip_circuit_if_needed("FMP", result)
        return records, attempts
    rec = _save_provider_record(symbol, str(meta["quarter_label"]), "FMP", result, company, meta.get("date"))
    if rec:
        records.append(rec)
    return records, attempts


def _alpha_latest_record(symbol: str, company: dict, existing_quarters: set[str], target_quarter: str | None) -> tuple[list[dict], list[dict]]:
    attempts: list[dict] = []
    records: list[dict] = []
    if not target_quarter or target_quarter in existing_quarters:
        return records, attempts
    state = provider_circuit("Alpha Vantage")
    if state.get("open"):
        attempts.append(_circuit_attempt("Alpha Vantage", target_quarter, state))
        return records, attempts

    # V3.2: one latest-quarter request only. Historical acquisition is explicit/manual.
    result = _alpha_transcript_result(symbol, target_quarter)
    attempts.append(_attempt_row("Alpha Vantage", target_quarter, result))
    if not result.get("ok"):
        _trip_circuit_if_needed("Alpha Vantage", result)
        return records, attempts
    rec = _save_provider_record(symbol, target_quarter, "Alpha Vantage", result, company)
    if rec:
        records.append(rec)
    return records, attempts


def _finnhub_latest_record(symbol: str, company: dict, existing_quarters: set[str], target_quarter: str | None) -> tuple[list[dict], list[dict]]:
    attempts: list[dict] = []
    records: list[dict] = []
    state = provider_circuit("Finnhub")
    if state.get("open"):
        attempts.append(_circuit_attempt("Finnhub", target_quarter or "latest", state))
        return records, attempts

    listing = _finnhub_transcript_list_result(symbol)
    attempts.append(_attempt_row("Finnhub", "transcript list", listing))
    if not listing.get("ok"):
        _trip_circuit_if_needed("Finnhub", listing)
        return records, attempts
    rows = listing.get("rows", []) if isinstance(listing, dict) else []
    if not rows:
        return records, attempts

    metas = []
    for row in rows:
        year = safe_int(row.get("year"))
        quarter = safe_int(row.get("quarter"))
        tid = str(row.get("id") or "").strip()
        if not tid or year is None or quarter is None:
            continue
        label = f"{int(year)}Q{int(quarter)}"
        if label in existing_quarters:
            continue
        metas.append((label, row))
    if not metas:
        return records, attempts

    chosen = None
    if target_quarter:
        chosen = next((x for x in metas if x[0] == target_quarter), None)
    if chosen is None:
        def _key(pair):
            row = pair[1]
            t = _date_from_any(row.get("time"))
            y = safe_int(row.get("year"), 0) or 0
            q = safe_int(row.get("quarter"), 0) or 0
            return (t or pd.Timestamp.min, y, q)
        chosen = sorted(metas, key=_key, reverse=True)[0]

    label, meta = chosen
    result = _finnhub_transcript_result(str(meta.get("id")))
    attempts.append(_attempt_row("Finnhub", label, result))
    if not result.get("ok"):
        _trip_circuit_if_needed("Finnhub", result)
        return records, attempts
    rec = _save_provider_record(symbol, label, "Finnhub", result, company, meta.get("time"))
    if rec:
        records.append(rec)
    return records, attempts


def _targeted_backfill_provider_sequence(symbol: str, company: dict, quarter: str) -> tuple[list[dict], list[dict]]:
    """Fetch exactly one requested historical quarter, never an automatic range."""
    attempts: list[dict] = []
    records: list[dict] = []
    if load_transcript_payload(symbol, quarter):
        attempts.append({
            "Provider": "Cache", "Quarter": quarter, "Status": "Hit",
            "Reason": "Quarter already exists in persistent cache", "HTTP": None,
        })
        return records, attempts

    m = re.match(r"(\d{4})Q([1-4])", quarter)
    # 1) FMP direct quarter: one call, no metadata call.
    fmp_state = provider_circuit("FMP")
    if fmp_state.get("open"):
        attempts.append(_circuit_attempt("FMP direct", quarter, fmp_state))
    elif m:
        result = _fmp_transcript_result(symbol, int(m.group(1)), int(m.group(2)))
        attempts.append(_attempt_row("FMP direct", quarter, result))
        if result.get("ok"):
            rec = _save_provider_record(symbol, quarter, "FMP", result, company)
            if rec:
                return [rec], attempts
        else:
            _trip_circuit_if_needed("FMP", result)

    # 2) Alpha one call.
    alpha_state = provider_circuit("Alpha Vantage")
    if alpha_state.get("open"):
        attempts.append(_circuit_attempt("Alpha Vantage", quarter, alpha_state))
    else:
        result = _alpha_transcript_result(symbol, quarter)
        attempts.append(_attempt_row("Alpha Vantage", quarter, result))
        if result.get("ok"):
            rec = _save_provider_record(symbol, quarter, "Alpha Vantage", result, company)
            if rec:
                return [rec], attempts
        else:
            _trip_circuit_if_needed("Alpha Vantage", result)

    # 3) Finnhub requires one metadata lookup plus detail when entitled.
    finn_state = provider_circuit("Finnhub")
    if finn_state.get("open"):
        attempts.append(_circuit_attempt("Finnhub", quarter, finn_state))
        return records, attempts
    listing = _finnhub_transcript_list_result(symbol)
    attempts.append(_attempt_row("Finnhub", "transcript list", listing))
    if not listing.get("ok"):
        _trip_circuit_if_needed("Finnhub", listing)
        return records, attempts
    for meta in listing.get("rows", []):
        year = safe_int(meta.get("year"))
        q = safe_int(meta.get("quarter"))
        if year is None or q is None or f"{int(year)}Q{int(q)}" != quarter:
            continue
        tid = str(meta.get("id") or "").strip()
        if not tid:
            continue
        result = _finnhub_transcript_result(tid)
        attempts.append(_attempt_row("Finnhub", quarter, result))
        if not result.get("ok"):
            _trip_circuit_if_needed("Finnhub", result)
            return records, attempts
        rec = _save_provider_record(symbol, quarter, "Finnhub", result, company, meta.get("time"))
        if rec:
            records.append(rec)
        return records, attempts
    attempts.append({
        "Provider": "Finnhub", "Quarter": quarter, "Status": "Unavailable",
        "Reason": "Requested fiscal quarter not present in transcript metadata", "HTTP": listing.get("http_status"),
    })
    return records, attempts

def _sort_records(records: list[dict]) -> list[dict]:
    def key(rec):
        date = rec.get("date")
        if date is not None:
            return (1, pd.Timestamp(date), rec.get("quarter", ""))
        m = re.match(r"(\d{4})Q([1-4])", str(rec.get("quarter", "")))
        if m:
            return (0, pd.Timestamp(int(m.group(1)), int(m.group(2)) * 3, 1), rec.get("quarter", ""))
        return (0, pd.Timestamp.min, str(rec.get("quarter", "")))
    return sorted(records, key=key, reverse=True)


def _delta_table(current: dict, previous: dict | None) -> pd.DataFrame:
    if not previous:
        return pd.DataFrame()
    metrics = [
        ("Management Tone", "management_tone", False),
        ("Prepared Tone", "prepared_tone", False),
        ("Q&A Management Tone", "qa_management_tone", False),
        ("Guidance Confidence", "guidance_confidence", False),
        ("Q&A Pressure", "qa_pressure", True),
        ("Evasiveness", "evasiveness", True),
        ("Management Uncertainty /100w", "management_uncertainty_per_100", True),
    ]
    rows = []
    csum = current.get("summary", {})
    psum = previous.get("summary", {})
    for label, key, lower_better in metrics:
        cur = safe_float(csum.get(key))
        prev = safe_float(psum.get(key))
        if cur is None or prev is None:
            continue
        delta = cur - prev
        if abs(delta) < 0.25:
            direction = "Stable"
        else:
            favorable = delta < 0 if lower_better else delta > 0
            direction = "Improved" if favorable else "Deteriorated"
        rows.append({
            "Metric": label,
            "Current": round(cur, 2),
            "Previous": round(prev, 2),
            "Δ": round(delta, 2),
            "Interpretation": direction,
        })
    return pd.DataFrame(rows)


def _theme_delta(current: dict, previous: dict | None) -> pd.DataFrame:
    cur = current.get("themes", pd.DataFrame())
    if not isinstance(cur, pd.DataFrame) or cur.empty:
        return pd.DataFrame()
    if not previous or not isinstance(previous.get("themes"), pd.DataFrame) or previous["themes"].empty:
        out = cur.copy()
        out["Previous Mentions"] = np.nan
        out["Δ Mentions"] = np.nan
        out["Previous Tone"] = np.nan
        out["Δ Tone"] = np.nan
        return out
    prev = previous["themes"].copy()
    merged = cur.merge(prev[["Theme", "Mentions", "Tone"]], on="Theme", how="left", suffixes=("", " Previous"))
    merged = merged.rename(columns={"Mentions Previous": "Previous Mentions", "Tone Previous": "Previous Tone"})
    merged["Δ Mentions"] = pd.to_numeric(merged["Mentions"], errors="coerce") - pd.to_numeric(merged["Previous Mentions"], errors="coerce")
    merged["Δ Tone"] = pd.to_numeric(merged["Tone"], errors="coerce") - pd.to_numeric(merged["Previous Tone"], errors="coerce")
    return merged


def _dedup_records(records: list[dict], max_quarters: int) -> list[dict]:
    dedup: dict[str, dict] = {}
    for rec in records:
        q = str(rec.get("quarter") or "")
        if not q:
            continue
        # Cache is immutable, so duplicates normally occur only within the same render after
        # a successful fetch. Prefer Alpha when both are simultaneously present because it
        # can carry provider turn sentiment; otherwise keep the first audited record.
        if q not in dedup or rec.get("provider") == "Alpha Vantage":
            dedup[q] = rec
    return _sort_records(list(dedup.values()))[:max_quarters]


def _bundle_runtime_meta(symbol: str, company: dict, cache_hits: int) -> dict[str, Any]:
    cached = list_cached_transcripts(symbol)
    return {
        "symbol": symbol,
        "cache_root": str(transcript_cache_root()),
        "cached_quarters": [str(x.get("quarter")) for x in cached if x.get("quarter")],
        "cache_entries": len(cached),
        "cache_hits": int(cache_hits),
        "latest_target_quarter": _latest_target_quarter(company),
        "probe_policy": "Latest fiscal quarter only; historical quarters require explicit one-at-a-time backfill.",
        "circuits": pd.DataFrame(provider_circuit_table(["FMP", "Alpha Vantage", "Finnhub"])),
    }


def transcript_backfill_candidates(symbol: str, company: dict, limit: int = 12) -> list[str]:
    cached = {str(x.get("quarter")) for x in list_cached_transcripts(symbol) if x.get("quarter")}
    return [q for q in _candidate_alpha_quarters(company, limit=max(4, limit + len(cached))) if q not in cached][:limit]


def clear_transcript_provider_circuits() -> bool:
    """Explicit operator action after a quota reset, API upgrade, or key change."""
    return clear_provider_circuit(None)


def backfill_management_transcript(symbol: str, company: dict, quarter: str) -> dict[str, Any]:
    """Fetch exactly one requested fiscal quarter and persist it if successful."""
    symbol = str(symbol or "").upper().strip()
    quarter = str(quarter or "").upper().strip()
    records, attempts = _targeted_backfill_provider_sequence(symbol, company, quarter)
    cached_entry = load_transcript_payload(symbol, quarter)
    return {
        "ok": bool(records or cached_entry),
        "quarter": quarter,
        "saved": bool(records),
        "cached": bool(cached_entry),
        "attempts": pd.DataFrame(attempts),
        "circuits": pd.DataFrame(provider_circuit_table(["FMP", "Alpha Vantage", "Finnhub"])),
    }


def load_management_transcript_intelligence(
    symbol: str,
    company: dict,
    max_quarters: int = 4,
    *,
    probe_latest: bool = True,
) -> dict[str, Any]:
    """Load V3 transcript analytics with V3.2 budget-aware persistence.

    Runtime contract
    ----------------
    1. Rebuild all available analytics from immutable local transcript payloads first.
    2. If the latest fiscal quarter is absent, probe providers only for that one quarter.
    3. A quota/entitlement response opens a persistent provider circuit and stops further
       calls to that provider until cooldown/reset.
    4. Older quarters are never auto-backfilled; the UI requests them one at a time.

    ``company`` is deliberately not cached because the current executive roster is used for
    speaker-role classification. Raw transcript payloads are persisted instead, allowing the
    analytics layer to be recomputed under the current code without spending API budget.
    """
    symbol = str(symbol or "").upper().strip()
    records, attempts = _cached_records(symbol, company)
    cache_hits = len(records)
    records = _dedup_records(records, max_quarters=max_quarters)
    existing = {str(r.get("quarter")) for r in records}
    target = _latest_target_quarter(company)

    if probe_latest and target and target not in existing:
        # FMP: metadata first, then at most one direct transcript. A 429/entitlement result
        # opens the circuit immediately, so V3.1's request fan-out cannot recur.
        fetched, rows = _fmp_latest_record(symbol, company, existing, target)
        records.extend(fetched)
        attempts.extend(rows)
        existing.update(str(r.get("quarter")) for r in fetched)

        # Alpha: exactly one latest-quarter call. Daily-limit messages open until the next
        # UTC day reset (plus grace), rather than burning the remaining quarter candidates.
        if target not in existing:
            fetched, rows = _alpha_latest_record(symbol, company, existing, target)
            records.extend(fetched)
            attempts.extend(rows)
            existing.update(str(r.get("quarter")) for r in fetched)

        # Finnhub: final fallback. Its list endpoint is called only when the transcript is
        # still unresolved and the provider circuit is closed.
        if target not in existing:
            fetched, rows = _finnhub_latest_record(symbol, company, existing, target)
            records.extend(fetched)
            attempts.extend(rows)
            existing.update(str(r.get("quarter")) for r in fetched)

        # Re-read disk after successful saves so the returned state is exactly what future
        # reruns will see. This also proves persistence before analytics are rendered.
        disk_records, disk_attempts = _cached_records(symbol, company)
        if disk_records:
            records.extend(disk_records)
            # Only add newly meaningful cache audit rows once; duplicates are harmless but
            # make provider diagnostics noisy.
            seen_attempt = {(r.get("Provider"), r.get("Quarter"), r.get("Status")) for r in attempts}
            for row in disk_attempts:
                key = (row.get("Provider"), row.get("Quarter"), row.get("Status"))
                if key not in seen_attempt:
                    attempts.append(row)
                    seen_attempt.add(key)

    records = _dedup_records(records, max_quarters=max_quarters)
    runtime = _bundle_runtime_meta(symbol, company, cache_hits=cache_hits)

    if not records:
        return {
            "available": False,
            "symbol": symbol,
            "records": [],
            "current": None,
            "previous": None,
            "delta": pd.DataFrame(),
            "theme_delta": pd.DataFrame(),
            "attempts": pd.DataFrame(attempts),
            "confidence": {"overall": 0},
            "runtime": runtime,
            "status": "No transcript payload available from persistent cache or configured FMP / Alpha Vantage / Finnhub providers.",
        }

    current = records[0]
    previous = records[1] if len(records) > 1 else None
    confidence = _data_confidence(current, current.get("summary", {}), previous_available=previous is not None)
    return {
        "available": True,
        "symbol": symbol,
        "records": records,
        "current": current,
        "previous": previous,
        "delta": _delta_table(current, previous),
        "theme_delta": _theme_delta(current, previous),
        "attempts": pd.DataFrame(attempts),
        "confidence": confidence,
        "runtime": runtime,
        "status": "OK",
    }

