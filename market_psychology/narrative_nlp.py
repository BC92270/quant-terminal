from __future__ import annotations

"""
Market Psychology V2.1 — Narrative & Belief NLP

Design goals
------------
1. Keep the NLP layer deterministic and auditable by default.
2. Use semantic similarity/clustering when scikit-learn is available.
3. Degrade cleanly to taxonomy/lexical analysis when it is not.
4. Separate source text, extracted beliefs and inferred narrative states.
5. Never pretend that a current corpus is a historical point-in-time archive.

No external model/API is required by this module. Provider aggregation lives in data.py.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
import math
import re
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .config import (
    NARRATIVE_THEMES,
    NEGATIVE_WORDS,
    POSITIVE_WORDS,
    UNCERTAINTY_WORDS,
)

try:  # optional semantic backend; V2.1 has a deterministic fallback
    from sklearn.cluster import AgglomerativeClustering
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    from sklearn.decomposition import TruncatedSVD
    from sklearn.preprocessing import Normalizer

    SKLEARN_AVAILABLE = True
except Exception:  # pragma: no cover
    AgglomerativeClustering = None
    TfidfVectorizer = None
    cosine_similarity = None
    TruncatedSVD = None
    Normalizer = None
    SKLEARN_AVAILABLE = False


_EMPTY_NEWS_COLUMNS = [
    "published", "source", "title", "summary", "symbol", "provider", "url",
    "provider_sentiment", "relevance",
]

_CERTAINTY_WORDS = {
    "will", "must", "certain", "certainly", "clearly", "expects", "expect",
    "confident", "confidence", "conviction", "strongly", "inevitable",
    "confirmed", "demonstrates", "shows", "likely",
}
_HEDGE_WORDS = {
    "could", "may", "might", "possibly", "possible", "uncertain", "unclear",
    "perhaps", "appears", "suggests", "seems", "risk", "risks", "if",
}
_POSITIVE_BELIEF_WORDS = POSITIVE_WORDS | {
    "buy", "bull", "upside", "higher", "increase", "increases", "rising",
    "stronger", "improve", "improves", "improved", "outlook", "resilient",
    "accelerating", "expanding", "tailwind", "tailwinds",
}
_NEGATIVE_BELIEF_WORDS = NEGATIVE_WORDS | {
    "sell", "bear", "downside", "lower", "decrease", "decreases", "falling",
    "weaker", "deteriorate", "deteriorates", "deterioration", "headwind",
    "headwinds", "contracting", "compression",
}

_DRIVER_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Earnings / fundamentals", ("earnings", "eps", "revenue", "profit", "margin", "guidance", "cash flow", "free cash flow")),
    ("Demand / growth", ("demand", "orders", "bookings", "growth", "adoption", "shipments", "sales")),
    ("Rates / discount rate", ("fed", "rate", "rates", "yield", "yields", "powell", "cut", "hike", "monetary")),
    ("Inflation", ("inflation", "cpi", "pce", "prices", "disinflation")),
    ("Liquidity / leverage", ("liquidity", "funding", "leverage", "margin", "credit", "spread", "spreads")),
    ("Positioning / flows", ("flows", "flow", "positioning", "short interest", "short squeeze", "options", "calls", "puts", "gamma")),
    ("Valuation", ("valuation", "multiple", "p/e", "price target", "fair value", "discounted cash flow")),
    ("Geopolitics / policy", ("war", "sanction", "tariff", "china", "russia", "iran", "regulation", "policy")),
    ("Technology / innovation", ("ai", "artificial intelligence", "semiconductor", "chip", "gpu", "software", "innovation", "data center", "datacenter")),
)

_MENTAL_MODEL_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("EXTRAPOLATIVE / MOMENTUM", ("rally", "record high", "breakout", "momentum", "trend", "surge", "winning streak", "continues", "extends")),
    ("FUNDAMENTAL / EARNINGS", ("earnings", "revenue", "profit", "margin", "cash flow", "valuation", "guidance", "fundamental")),
    ("MACRO / DISCOUNT-RATE", ("fed", "rates", "yield", "inflation", "cpi", "pce", "gdp", "recession", "soft landing")),
    ("FLOW / POSITIONING", ("flows", "positioning", "short interest", "options", "gamma", "hedging", "etf inflow", "etf outflow")),
    ("NARRATIVE / THEMATIC", ("ai", "theme", "story", "narrative", "megatrend", "structural", "supercycle", "adoption")),
)


@dataclass(frozen=True)
class BeliefRecord:
    direction: str
    score: float
    confidence: float
    horizon: str
    driver: str
    mental_model: str
    claim: str


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or isinstance(value, (pd.Series, pd.DataFrame, list, tuple, dict)):
            return default
        x = float(value)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    return str(value)


def _clean_text(value: Any) -> str:
    text = _text(value)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _normalize_title(value: Any) -> str:
    text = _clean_text(value).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z\-']+", text.lower())


def _contains_phrase(text: str, phrase: str) -> bool:
    t = text.lower()
    p = str(phrase).lower().strip()
    if not p:
        return False
    # Phrase boundaries avoid false matches such as "rate" inside "accelerates".
    pattern = r"(?<![a-z0-9])" + re.escape(p).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
    return re.search(pattern, t) is not None


def _lexical_sentiment(text: str) -> tuple[float, float]:
    toks = _tokens(text)
    if not toks:
        return 0.0, 0.0
    pos = sum(1 for t in toks if t in _POSITIVE_BELIEF_WORDS)
    neg = sum(1 for t in toks if t in _NEGATIVE_BELIEF_WORDS)
    unc = sum(1 for t in toks if t in UNCERTAINTY_WORDS or t in _HEDGE_WORDS)
    sentiment = (pos - neg) / max(pos + neg, 1)
    uncertainty = min(1.0, unc / max(3.0, len(toks) * 0.055))
    return float(np.clip(sentiment, -1, 1)), float(np.clip(uncertainty, 0, 1))


def _provider_sentiment(value: Any) -> float | None:
    x = _safe_float(value)
    if x is None:
        return None
    # Providers used by data.py are normalized to [-1, 1] where possible.
    return float(np.clip(x, -1, 1))


def _extract_horizon(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(today|tomorrow|this week|next week|days?|near[- ]term|short[- ]term)\b", t):
        return "DAYS / WEEKS"
    if re.search(r"\b(quarter|next quarter|this quarter|q[1-4]|months?|earnings season)\b", t):
        return "1–6 MONTHS"
    if re.search(r"\b(20\d{2}|year|years|long[- ]term|structural|cycle|multi[- ]year)\b", t):
        return "6–24+ MONTHS"
    return "UNSPECIFIED"


def _extract_driver(text: str) -> str:
    t = text.lower()
    for label, keys in _DRIVER_RULES:
        if any(_contains_phrase(t, k) for k in keys):
            return label
    return "Unclassified driver"


def _extract_mental_model(text: str) -> str:
    t = text.lower()
    scored: list[tuple[int, str]] = []
    for label, keys in _MENTAL_MODEL_RULES:
        score = sum(1 for k in keys if _contains_phrase(t, k))
        scored.append((score, label))
    best = max(scored, key=lambda x: x[0]) if scored else (0, "NARRATIVE / THEMATIC")
    return best[1] if best[0] > 0 else "MIXED / UNIDENTIFIED"


def _extract_claim(title: str, summary: str) -> str:
    source = _clean_text(summary) or _clean_text(title)
    if not source:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", source, maxsplit=1)[0]
    return sentence[:280]


def extract_belief(title: str, summary: str, provider_sentiment: Any = None) -> BeliefRecord:
    text = f"{_clean_text(title)} {_clean_text(summary)}".strip()
    lex_sent, uncertainty = _lexical_sentiment(text)
    ps = _provider_sentiment(provider_sentiment)
    sentiment = 0.65 * lex_sent + 0.35 * ps if ps is not None else lex_sent
    sentiment = float(np.clip(sentiment, -1, 1))

    if sentiment >= 0.16:
        direction = "BULLISH"
    elif sentiment <= -0.16:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL / MIXED"

    toks = _tokens(text)
    certainty = sum(1 for t in toks if t in _CERTAINTY_WORDS)
    hedges = sum(1 for t in toks if t in _HEDGE_WORDS or t in UNCERTAINTY_WORDS)
    directional_strength = min(abs(sentiment), 1.0)
    confidence = 0.48 + 0.18 * directional_strength + 0.025 * min(certainty, 6) - 0.025 * min(hedges, 6)
    confidence *= (1.0 - 0.20 * uncertainty)
    confidence = float(np.clip(confidence, 0.15, 0.95))

    return BeliefRecord(
        direction=direction,
        score=sentiment,
        confidence=confidence,
        horizon=_extract_horizon(text),
        driver=_extract_driver(text),
        mental_model=_extract_mental_model(text),
        claim=_extract_claim(title, summary),
    )


def _theme_label(texts: Iterable[str], top_terms: list[str] | None = None) -> str:
    combined = " ".join(_clean_text(t).lower() for t in texts)
    theme_scores: list[tuple[int, str]] = []
    for theme, keys in NARRATIVE_THEMES.items():
        score = sum(1 for k in keys if _contains_phrase(combined, k))
        theme_scores.append((score, theme))
    if theme_scores:
        score, label = max(theme_scores, key=lambda x: x[0])
        if score > 0:
            return label
    terms = [t for t in (top_terms or []) if len(t) > 2][:3]
    return " / ".join(t.title() for t in terms) if terms else "Other / fragmented"


def _semantic_dedupe(frame: pd.DataFrame, threshold: float = 0.92) -> tuple[pd.DataFrame, dict[str, Any]]:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=_EMPTY_NEWS_COLUMNS), {"raw": 0, "exact_removed": 0, "semantic_removed": 0}

    work = frame.copy().reset_index(drop=True)
    for col in _EMPTY_NEWS_COLUMNS:
        if col not in work.columns:
            work[col] = np.nan
    work["title_norm"] = work["title"].map(_normalize_title)
    before = len(work)
    work = work[work["title_norm"].str.len() >= 5].copy()
    work = work.sort_values("published", ascending=False, na_position="last")
    work = work.drop_duplicates("title_norm", keep="first").reset_index(drop=True)
    exact_removed = before - len(work)

    semantic_removed = 0
    if SKLEARN_AVAILABLE and len(work) >= 3:
        try:
            vect = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1, max_features=5000)
            mat = vect.fit_transform(work["title_norm"].tolist())
            sims = cosine_similarity(mat)
            keep: list[int] = []
            for i in range(len(work)):
                if not keep:
                    keep.append(i)
                    continue
                if max(float(sims[i, j]) for j in keep) < threshold:
                    keep.append(i)
            semantic_removed = len(work) - len(keep)
            work = work.iloc[keep].reset_index(drop=True)
        except Exception:
            semantic_removed = 0

    return work.drop(columns=["title_norm"], errors="ignore"), {
        "raw": int(before),
        "exact_removed": int(max(exact_removed, 0)),
        "semantic_removed": int(max(semantic_removed, 0)),
    }


def _cluster_documents(work: pd.DataFrame) -> tuple[np.ndarray, dict[int, list[str]], np.ndarray | None, str]:
    n = len(work)
    if n == 0:
        return np.array([], dtype=int), {}, None, "EMPTY"

    texts = (work["title"].fillna("") + ". " + work["summary"].fillna("")).astype(str).tolist()
    if not SKLEARN_AVAILABLE or n < 5:
        labels = []
        for text in texts:
            matched = []
            low = text.lower()
            for theme, keys in NARRATIVE_THEMES.items():
                if any(_contains_phrase(low, k) for k in keys):
                    matched.append(theme)
            labels.append(hash(matched[0]) % 10_000 if matched else -1)
        uniq = {v: i for i, v in enumerate(dict.fromkeys(labels))}
        arr = np.array([uniq[v] for v in labels], dtype=int)
        top_terms = {i: [] for i in np.unique(arr)}
        return arr, top_terms, None, "TAXONOMY FALLBACK"

    try:
        vectorizer = TfidfVectorizer(
            lowercase=True,
            stop_words="english",
            ngram_range=(1, 2),
            min_df=1,
            max_df=0.96,
            max_features=3500,
            sublinear_tf=True,
        )
        matrix = vectorizer.fit_transform(texts)
        if matrix.shape[1] == 0:
            raise ValueError("empty vocabulary")

        # Latent Semantic Analysis reduces sparse lexical noise before cosine clustering.
        # It remains deterministic/local and avoids model/API version drift.
        if n >= 8 and matrix.shape[1] >= 12:
            n_components = max(2, min(32, n - 1, matrix.shape[1] - 1))
            svd = TruncatedSVD(n_components=n_components, random_state=17)
            dense = svd.fit_transform(matrix)
            dense = Normalizer(copy=False).fit_transform(dense)
            backend = "TF-IDF + LSA COSINE / AGGLOMERATIVE"
            distance_threshold = 0.80
        else:
            dense = matrix.toarray().astype(float)
            backend = "TF-IDF COSINE / AGGLOMERATIVE"
            distance_threshold = 0.74

        # Average-linkage cosine clustering. Distance threshold is intentionally
        # conservative so related articles merge without forcing a fixed K.
        clusterer = AgglomerativeClustering(
            n_clusters=None,
            metric="cosine",
            linkage="average",
            distance_threshold=distance_threshold,
        )
        labels = clusterer.fit_predict(dense)

        # Avoid a dashboard with dozens of singleton narratives: map tiny clusters
        # to one fragmented bucket when the corpus is sufficiently large.
        counts = Counter(labels.tolist())
        if n >= 20:
            major = {lab for lab, c in counts.items() if c >= 2}
            if major:
                fragmented_label = max(labels) + 1
                labels = np.array([lab if lab in major else fragmented_label for lab in labels], dtype=int)

        feature_names = np.asarray(vectorizer.get_feature_names_out())
        top_terms: dict[int, list[str]] = {}
        for lab in np.unique(labels):
            idx = np.where(labels == lab)[0]
            centroid = np.asarray(matrix[idx].mean(axis=0)).ravel()
            if centroid.size:
                order = centroid.argsort()[::-1][:8]
                top_terms[int(lab)] = [str(feature_names[i]) for i in order if centroid[i] > 0]
            else:
                top_terms[int(lab)] = []
        return labels.astype(int), top_terms, dense, backend
    except Exception:
        labels = np.arange(n, dtype=int)
        return labels, {int(i): [] for i in labels}, None, "LEXICAL FALLBACK"


def _semantic_novelty(embeddings: np.ndarray | None, published: pd.Series) -> np.ndarray:
    n = len(published)
    if embeddings is None or n == 0:
        return np.full(n, 0.5, dtype=float)
    sims = cosine_similarity(embeddings)
    times = pd.to_datetime(published, errors="coerce", utc=True)
    novelty = np.full(n, 0.5, dtype=float)
    for i in range(n):
        older = [j for j in range(n) if j != i and (pd.isna(times.iloc[i]) or pd.isna(times.iloc[j]) or times.iloc[j] <= times.iloc[i])]
        if older:
            max_sim = max(float(sims[i, j]) for j in older)
            novelty[i] = float(np.clip(1.0 - max_sim, 0, 1))
    return novelty


def _share_in_window(work: pd.DataFrame, label: int, end: pd.Timestamp, start_days: float, end_days: float) -> float | None:
    if work.empty or "published" not in work.columns:
        return None
    ts = pd.to_datetime(work["published"], errors="coerce", utc=True)
    age = (end - ts).dt.total_seconds() / 86400.0
    mask = (age >= start_days) & (age < end_days)
    denom = int(mask.sum())
    if denom <= 0:
        return None
    key_col = "narrative_id" if "narrative_id" in work.columns else "cluster_id"
    return float((work.loc[mask, key_col] == label).mean())


def _lifecycle(share: float, intensity: float, momentum: float | None, acceleration: float | None,
               novelty: float, consensus: float, sentiment: float, persistence_days: float) -> str:
    m = momentum if momentum is not None and np.isfinite(momentum) else 0.0
    a = acceleration if acceleration is not None and np.isfinite(acceleration) else 0.0
    if share < 0.08 and novelty >= 65 and m > 0:
        return "EMERGENCE"
    if novelty >= 60 and m >= 8:
        return "DISCOVERY"
    if m >= 10 and share < 0.30:
        return "DIFFUSION"
    if share >= 0.38 and consensus >= 70 and sentiment >= 0.12 and m >= 5:
        return "EUPHORIA"
    if share >= 0.30 and consensus >= 62 and m >= -3:
        return "CONSENSUS"
    if persistence_days >= 4 and share >= 0.25 and m < -5:
        return "SATURATION"
    if m <= -12 or (a <= -12 and m < 0):
        return "DECAY"
    return "MATURITY"


def _normalized_entropy(shares: list[float]) -> float:
    vals = [float(x) for x in shares if x > 0]
    if not vals:
        return 1.0
    ent = -sum(p * math.log(p + 1e-12) for p in vals)
    max_ent = math.log(max(len(vals), 2))
    return float(ent / max_ent) if max_ent > 0 else 0.0


def _build_timeline(work: pd.DataFrame, narrative_labels: dict[int, str], top_ids: list[int]) -> pd.DataFrame:
    if work.empty or "published" not in work.columns:
        return pd.DataFrame()
    tmp = work.dropna(subset=["published"]).copy()
    if tmp.empty:
        return pd.DataFrame()
    tmp["date"] = pd.to_datetime(tmp["published"], utc=True, errors="coerce").dt.floor("D")
    tmp = tmp.dropna(subset=["date"])
    if tmp.empty or tmp["date"].nunique() < 2:
        return pd.DataFrame()
    total = tmp.groupby("date").size().rename("total")
    rows = []
    for cid in top_ids:
        key_col = "narrative_id" if "narrative_id" in tmp.columns else "cluster_id"
        sub = tmp[tmp[key_col] == cid].groupby("date").size().rename("count")
        joined = pd.concat([total, sub], axis=1).fillna(0)
        joined["share"] = joined["count"] / joined["total"].replace(0, np.nan)
        for dt, row in joined.iterrows():
            rows.append({"date": dt, "Narrative": narrative_labels.get(cid, str(cid)), "Share": float(row["share"] or 0)})
    return pd.DataFrame(rows).sort_values(["date", "Narrative"]).reset_index(drop=True)


def empty_analysis() -> dict[str, Any]:
    return {
        "count": 0,
        "raw_count": 0,
        "dedup_removed": 0,
        "provider_count": 0,
        "source_count": 0,
        "sentiment_mean": 0.0,
        "sentiment_std": 0.0,
        "negative_share": 0.0,
        "uncertainty_share": 0.0,
        "theme_concentration": 0.0,
        "theme_entropy": 1.0,
        "headline_redundancy": 0.0,
        "semantic_redundancy": 0.0,
        "belief_confidence_mean": 0.0,
        "belief_disagreement": 50.0,
        "belief_bullish_share": 0.0,
        "belief_bearish_share": 0.0,
        "belief_neutral_share": 0.0,
        "narrative_state_score": 35.0,
        "narrative_momentum": 0.0,
        "narrative_acceleration": 0.0,
        "narrative_persistence": 0.0,
        "narrative_consensus": 50.0,
        "narrative_polarization": 0.0,
        "dominant_narrative": "N/A",
        "dominant_lifecycle": "N/A",
        "dominant_mental_model": "MIXED / UNIDENTIFIED",
        "corpus_quality": 0.0,
        "backend": "UNAVAILABLE",
        "themes": pd.DataFrame(columns=["Theme", "Mentions", "Share"]),
        "narratives": pd.DataFrame(),
        "beliefs": pd.DataFrame(),
        "headline_scores": pd.DataFrame(),
        "narrative_timeline": pd.DataFrame(),
        "provider_diagnostics": [],
    }


def analyze_news_corpus(news_df: pd.DataFrame) -> dict[str, Any]:
    if news_df is None or news_df.empty:
        return empty_analysis()

    raw = news_df.copy()
    for col in _EMPTY_NEWS_COLUMNS:
        if col not in raw.columns:
            raw[col] = np.nan
    raw["published"] = pd.to_datetime(raw["published"], errors="coerce", utc=True)
    raw["title"] = raw["title"].map(_clean_text)
    raw["summary"] = raw["summary"].map(_clean_text)
    raw["provider"] = raw["provider"].fillna("Unknown").astype(str)
    raw["source"] = raw["source"].fillna("Unknown").astype(str)
    raw = raw[raw["title"].str.len() >= 5].copy()
    if raw.empty:
        return empty_analysis()

    work, dedup = _semantic_dedupe(raw)
    if work.empty:
        return empty_analysis()

    labels, top_terms, embeddings, backend = _cluster_documents(work)
    work = work.reset_index(drop=True)
    work["cluster_id"] = labels
    work["semantic_novelty"] = _semantic_novelty(embeddings, work["published"])

    narrative_labels: dict[int, str] = {}
    for cid in sorted(set(labels.tolist())):
        idx = work.index[work["cluster_id"] == cid].tolist()
        narrative_labels[int(cid)] = _theme_label(
            (f"{work.loc[i, 'title']} {work.loc[i, 'summary']}" for i in idx),
            top_terms.get(int(cid), []),
        )
    work["narrative"] = work["cluster_id"].map(narrative_labels)
    # Multiple semantic clusters can resolve to the same canonical narrative label;
    # merge them for market-level narrative accounting while preserving semantic clustering upstream.
    merged_ids, merged_labels = pd.factorize(work["narrative"], sort=False)
    work["narrative_id"] = merged_ids.astype(int)
    merged_label_map = {int(i): str(label) for i, label in enumerate(merged_labels.tolist())}

    belief_rows = []
    doc_sentiments = []
    doc_uncertainty = []
    for i, row in work.iterrows():
        belief = extract_belief(row.get("title", ""), row.get("summary", ""), row.get("provider_sentiment"))
        _, uncertainty = _lexical_sentiment(f"{row.get('title','')} {row.get('summary','')}")
        doc_sentiments.append(belief.score)
        doc_uncertainty.append(uncertainty)
        belief_rows.append({
            "published": row.get("published"),
            "provider": row.get("provider"),
            "source": row.get("source"),
            "title": row.get("title"),
            "narrative": row.get("narrative"),
            "belief_direction": belief.direction,
            "belief_score": belief.score,
            "belief_confidence": belief.confidence,
            "horizon": belief.horizon,
            "driver": belief.driver,
            "mental_model": belief.mental_model,
            "claim": belief.claim,
            "uncertainty": uncertainty,
            "semantic_novelty": float(work.loc[i, "semantic_novelty"]),
            "relevance": _safe_float(row.get("relevance"), np.nan),
        })
    beliefs = pd.DataFrame(belief_rows)
    work["sentiment"] = np.asarray(doc_sentiments, dtype=float)
    work["uncertainty"] = np.asarray(doc_uncertainty, dtype=float)
    work["belief_direction"] = beliefs["belief_direction"].to_numpy()
    work["belief_confidence"] = beliefs["belief_confidence"].to_numpy(dtype=float)
    work["driver"] = beliefs["driver"].to_numpy()
    work["mental_model"] = beliefs["mental_model"].to_numpy()

    total = len(work)
    max_ts = work["published"].max()
    if pd.isna(max_ts):
        max_ts = pd.Timestamp.utcnow(tz="UTC")

    narrative_rows = []
    for cid, sub in work.groupby("narrative_id", sort=False):
        share = len(sub) / total
        sentiment = float(sub["sentiment"].mean()) if len(sub) else 0.0
        sentiment_std = float(sub["sentiment"].std(ddof=0)) if len(sub) > 1 else 0.0
        bull = float((sub["belief_direction"] == "BULLISH").mean())
        bear = float((sub["belief_direction"] == "BEARISH").mean())
        neutral = float((sub["belief_direction"] == "NEUTRAL / MIXED").mean())
        polarization = float(np.clip(200 * min(bull, bear) + 35 * sentiment_std, 0, 100))
        direction_consistency = max(bull, bear, neutral)
        consensus = float(np.clip(100 * (0.55 * direction_consistency + 0.45 * (1 - min(sentiment_std, 1))), 0, 100))
        novelty = float(np.clip(100 * sub["semantic_novelty"].mean(), 0, 100))
        belief_conf = float(np.clip(100 * sub["belief_confidence"].mean(), 0, 100))
        source_diversity = len(set(sub["source"].astype(str))) / max(len(sub), 1)
        provider_diversity = len(set(sub["provider"].astype(str))) / max(len(sub), 1)
        ages = (max_ts - pd.to_datetime(sub["published"], errors="coerce", utc=True)).dt.total_seconds() / 86400.0
        recency = float(np.nanmean(np.exp(-np.clip(ages, 0, 30) / 5.0))) if ages.notna().any() else 0.5
        intensity = float(np.clip(
            100 * (0.55 * share + 0.15 * source_diversity + 0.10 * provider_diversity + 0.20 * recency),
            0, 100,
        ))

        s0 = _share_in_window(work, int(cid), max_ts, 0, 2)
        s1 = _share_in_window(work, int(cid), max_ts, 2, 5)
        s2 = _share_in_window(work, int(cid), max_ts, 5, 9)
        momentum = 100 * (s0 - s1) if s0 is not None and s1 is not None else np.nan
        acceleration = 100 * ((s0 - s1) - (s1 - s2)) if s0 is not None and s1 is not None and s2 is not None else np.nan
        ts = pd.to_datetime(sub["published"], errors="coerce", utc=True).dropna()
        persistence_days = float((ts.max() - ts.min()).total_seconds() / 86400.0) if len(ts) >= 2 else 0.0
        lifecycle = _lifecycle(
            share=share,
            intensity=intensity,
            momentum=_safe_float(momentum),
            acceleration=_safe_float(acceleration),
            novelty=novelty,
            consensus=consensus,
            sentiment=sentiment,
            persistence_days=persistence_days,
        )
        narrative_rows.append({
            "Narrative": merged_label_map.get(int(cid), str(cid)),
            "Mentions": int(len(sub)),
            "Share": float(share),
            "Intensity": round(intensity, 1),
            "Momentum 2D": round(float(momentum), 1) if np.isfinite(momentum) else np.nan,
            "Acceleration": round(float(acceleration), 1) if np.isfinite(acceleration) else np.nan,
            "Persistence d": round(persistence_days, 1),
            "Consensus": round(consensus, 1),
            "Polarization": round(polarization, 1),
            "Novelty": round(novelty, 1),
            "Belief confidence": round(belief_conf, 1),
            "Sentiment": round(sentiment, 3),
            "Uncertainty": round(float(100 * sub["uncertainty"].mean()), 1),
            "Sources": int(sub["source"].nunique()),
            "Providers": int(sub["provider"].nunique()),
            "Lifecycle": lifecycle,
            "cluster_id": int(cid),
        })

    narratives = pd.DataFrame(narrative_rows)
    if not narratives.empty:
        narratives = narratives.sort_values(["Share", "Intensity"], ascending=False).reset_index(drop=True)

    shares = narratives["Share"].astype(float).tolist() if not narratives.empty else []
    concentration = max(shares) if shares else 0.0
    entropy = _normalized_entropy(shares)
    semantic_redundancy = float(np.clip(1.0 - work["semantic_novelty"].mean(), 0, 1))
    dedup_removed = int(dedup.get("exact_removed", 0) + dedup.get("semantic_removed", 0))
    headline_redundancy = float(np.clip(
        0.55 * semantic_redundancy + 0.45 * dedup_removed / max(dedup.get("raw", total), 1),
        0, 1,
    ))

    sent = pd.to_numeric(work["sentiment"], errors="coerce").fillna(0)
    unc = pd.to_numeric(work["uncertainty"], errors="coerce").fillna(0)
    directions = work["belief_direction"].astype(str)
    bull_share = float((directions == "BULLISH").mean())
    bear_share = float((directions == "BEARISH").mean())
    neutral_share = float((directions == "NEUTRAL / MIXED").mean())
    belief_disagreement = float(np.clip(
        100 * (0.55 * (1 - max(bull_share, bear_share, neutral_share)) / (2 / 3) + 0.45 * min(sent.std(ddof=0), 1.0)),
        0, 100,
    ))

    dominant = narratives.iloc[0].to_dict() if not narratives.empty else {}
    dominant_id = int(dominant.get("cluster_id")) if dominant else -1
    dominant_narrative = str(dominant.get("Narrative", "N/A"))
    dominant_lifecycle = str(dominant.get("Lifecycle", "N/A"))
    narrative_momentum = _safe_float(dominant.get("Momentum 2D"), 0.0) or 0.0
    narrative_acceleration = _safe_float(dominant.get("Acceleration"), 0.0) or 0.0
    narrative_persistence = _safe_float(dominant.get("Persistence d"), 0.0) or 0.0
    narrative_consensus = _safe_float(dominant.get("Consensus"), 50.0) or 50.0
    narrative_polarization = _safe_float(dominant.get("Polarization"), 0.0) or 0.0
    dominant_intensity = _safe_float(dominant.get("Intensity"), 0.0) or 0.0

    # Current narrative state: concentration alone is not enough. It also rewards
    # multi-source intensity, persistence and consensus while preserving uncertainty.
    narrative_state_score = float(np.clip(
        25
        + 34 * concentration
        + 0.20 * dominant_intensity
        + 0.10 * narrative_consensus
        + 0.08 * min(narrative_persistence, 30)
        + 0.08 * max(narrative_momentum, 0)
        - 0.08 * narrative_polarization,
        0, 100,
    ))

    mental_counts = Counter(work["mental_model"].astype(str).tolist())
    dominant_mental_model = mental_counts.most_common(1)[0][0] if mental_counts else "MIXED / UNIDENTIFIED"

    provider_count = int(work["provider"].nunique())
    source_count = int(work["source"].nunique())
    timestamp_share = float(work["published"].notna().mean())
    corpus_quality = float(np.clip(
        18
        + min(38, 1.1 * total)
        + min(16, 5 * provider_count)
        + min(14, 1.5 * source_count)
        + 8 * timestamp_share
        + (6 if "TF-IDF" in backend else 0),
        0, 100,
    ))

    top_ids = narratives.head(6)["cluster_id"].astype(int).tolist() if not narratives.empty else []
    timeline = _build_timeline(work, merged_label_map, top_ids)

    # Backward-compatible theme table used elsewhere in the UI/engine.
    theme_rows = narratives[["Narrative", "Mentions", "Share"]].copy() if not narratives.empty else pd.DataFrame(columns=["Narrative", "Mentions", "Share"])
    if not theme_rows.empty:
        theme_rows = theme_rows.rename(columns={"Narrative": "Theme"})

    headline_scores = work[[
        "published", "provider", "source", "title", "sentiment", "uncertainty",
        "narrative", "belief_direction", "belief_confidence", "semantic_novelty",
    ]].copy()
    headline_scores = headline_scores.rename(columns={"narrative": "themes"})

    provider_diagnostics = []
    provider_raw_count = int(dedup.get("raw", len(raw)))
    try:
        provider_diagnostics = list(news_df.attrs.get("provider_attempts", []))
        provider_raw_count = int(news_df.attrs.get("raw_provider_rows", provider_raw_count))
    except Exception:
        provider_diagnostics = []

    return {
        "count": int(total),
        "raw_count": int(provider_raw_count),
        "dedup_removed": int(dedup_removed),
        "provider_count": provider_count,
        "source_count": source_count,
        "sentiment_mean": float(sent.mean()) if len(sent) else 0.0,
        "sentiment_std": float(sent.std(ddof=0)) if len(sent) > 1 else 0.0,
        "negative_share": float((sent < -0.16).mean()) if len(sent) else 0.0,
        "uncertainty_share": float((unc > 0.25).mean()) if len(unc) else 0.0,
        "theme_concentration": float(concentration),
        "theme_entropy": float(entropy),
        "headline_redundancy": headline_redundancy,
        "semantic_redundancy": semantic_redundancy,
        "belief_confidence_mean": float(100 * beliefs["belief_confidence"].mean()) if not beliefs.empty else 0.0,
        "belief_disagreement": belief_disagreement,
        "belief_bullish_share": bull_share,
        "belief_bearish_share": bear_share,
        "belief_neutral_share": neutral_share,
        "narrative_state_score": narrative_state_score,
        "narrative_momentum": float(narrative_momentum),
        "narrative_acceleration": float(narrative_acceleration),
        "narrative_persistence": float(narrative_persistence),
        "narrative_consensus": float(narrative_consensus),
        "narrative_polarization": float(narrative_polarization),
        "dominant_narrative": dominant_narrative,
        "dominant_lifecycle": dominant_lifecycle,
        "dominant_mental_model": dominant_mental_model,
        "corpus_quality": corpus_quality,
        "backend": backend,
        "themes": theme_rows,
        "narratives": narratives.drop(columns=["cluster_id"], errors="ignore"),
        "beliefs": beliefs.sort_values("published", ascending=False, na_position="last").reset_index(drop=True),
        "headline_scores": headline_scores.sort_values("published", ascending=False, na_position="last").reset_index(drop=True),
        "narrative_timeline": timeline,
        "provider_diagnostics": provider_diagnostics,
    }

# ============================================================================
# V2.1.1 — SEMANTIC RELIABILITY OVERRIDES
# ============================================================================
# The V2.1 infrastructure is intentionally kept above for backward readability.
# These definitions override the public analysis entry point with stricter
# story-level deduplication, cluster validation, economic labeling and belief
# confidence calibration. No external LLM/API is required.

from dataclasses import dataclass as _v211_dataclass

_V211_UNRESOLVED = "OTHER / UNRESOLVED"
_V211_ECONOMIC_THEMES: dict[str, tuple[str, ...]] = {
    "AI / semiconductors": (
        "ai", "artificial intelligence", "semiconductor", "semiconductors", "chip", "chips", "gpu", "gpus",
        "data center", "data centers", "datacenter", "compute", "hyperscaler", "hyperscalers",
    ),
    "Rates / Fed": (
        "federal reserve", "fed", "powell", "interest rate", "interest rates", "rate cut", "rate cuts",
        "rate hike", "rate hikes", "treasury yield", "treasury yields", "bond yield", "bond yields", "monetary policy",
    ),
    "Inflation": (
        "inflation", "cpi", "pce", "consumer price index", "producer prices", "disinflation", "price pressures",
    ),
    "Growth / recession": (
        "gdp", "recession", "slowdown", "soft landing", "hard landing", "economic growth", "labor market",
        "jobs report", "payrolls", "unemployment", "consumer spending",
    ),
    "Earnings / fundamentals": (
        "earnings", "eps", "revenue", "revenues", "profit", "profits", "guidance", "margin", "margins",
        "free cash flow", "cash flow", "sales growth", "earnings growth",
    ),
    "Liquidity / credit": (
        "liquidity", "funding", "credit spread", "credit spreads", "high yield", "investment grade",
        "leverage", "margin debt", "financial conditions", "bank lending",
    ),
    "Market structure / ETF flows": (
        "etf", "etfs", "inflow", "inflows", "outflow", "outflows", "fund flows", "passive", "index fund",
        "rebalancing", "market breadth", "breadth", "advance decline", "holdings",
    ),
    "Valuation / positioning": (
        "valuation", "valuations", "multiple", "multiples", "price target", "fair value", "overvalued", "undervalued",
        "positioning", "crowded", "short interest", "short squeeze", "hedge funds", "systematic flows",
    ),
    "Geopolitics / trade": (
        "war", "sanction", "sanctions", "geopolitical", "conflict", "tariff", "tariffs", "trade war",
        "china", "russia", "iran", "export controls",
    ),
    "Crypto / speculative": (
        "bitcoin", "crypto", "cryptocurrency", "token", "meme stock", "meme stocks", "retail traders", "speculation",
    ),
    "Energy / commodities": (
        "oil", "crude", "brent", "wti", "natural gas", "gold", "copper", "commodity", "commodities", "opec",
    ),
    "Healthcare / biotech": (
        "healthcare", "biotech", "biotechnology", "pharma", "pharmaceutical", "fda", "drug approval", "clinical trial",
    ),
}

_V211_BROAD_MARKET_TERMS = (
    "s&p 500", "s&p", "spy", "stock market", "stocks", "equities", "equity market", "wall street", "market rally",
    "market selloff", "market outlook", "market breadth", "risk assets", "investors", "index", "indexes", "indices",
)
_V211_MACRO_TERMS = tuple(sorted({k for vals in (
    _V211_ECONOMIC_THEMES["Rates / Fed"],
    _V211_ECONOMIC_THEMES["Inflation"],
    _V211_ECONOMIC_THEMES["Growth / recession"],
    _V211_ECONOMIC_THEMES["Liquidity / credit"],
    _V211_ECONOMIC_THEMES["Geopolitics / trade"],
) for k in vals}))
_V211_EXPLICIT_BELIEF_MARKERS = (
    "expects", "expect", "forecast", "forecasts", "predicts", "predict", "projects", "project", "sees", "believes",
    "guidance", "outlook", "estimates", "estimate", "target", "will", "should", "likely to", "set to",
)
_V211_CONDITIONAL_MARKERS = (" if ", " unless ", " assuming ", " provided ", " depending on ", " conditional on ")


@_v211_dataclass(frozen=True)
class BeliefRecordV211:
    direction: str
    score: float
    confidence: float
    magnitude: str
    horizon: str
    driver: str
    mental_model: str
    claim: str
    inference_type: str
    conditionality: str


def _v211_weighted_mean(values: pd.Series, weights: pd.Series, default: float = 0.0) -> float:
    v = pd.to_numeric(values, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce").fillna(0).clip(lower=0)
    mask = v.notna() & w.gt(0)
    if not mask.any():
        vv = v.dropna()
        return float(vv.mean()) if not vv.empty else float(default)
    return float(np.average(v[mask], weights=w[mask]))


def _v211_document_relevance(title: str, summary: str, symbol: str | None, provider_relevance: Any) -> float:
    """Target/context relevance score used as an analysis weight, never as truth."""
    symbol = str(symbol or "").upper().strip()
    text = f"{_clean_text(title)} {_clean_text(summary)}".lower()
    base = _safe_float(provider_relevance, 0.55)
    base = float(np.clip(base if base is not None else 0.55, 0.05, 1.0))

    aliases = {
        "SPY": ("spy", "s&p 500", "s&p"),
        "QQQ": ("qqq", "nasdaq 100", "nasdaq"),
        "IWM": ("iwm", "russell 2000", "small caps", "small-cap"),
        "DIA": ("dia", "dow jones", "dow"),
        "TLT": ("tlt", "treasury bonds", "treasuries"),
        "HYG": ("hyg", "high yield", "junk bonds"),
        "GLD": ("gld", "gold"),
        "^GSPC": ("s&p 500", "s&p"),
        "^IXIC": ("nasdaq",),
        "^VIX": ("vix", "volatility index"),
    }
    explicit = any(_contains_phrase(text, a) for a in aliases.get(symbol, (symbol.lower(),) if symbol else ()))
    broad = any(_contains_phrase(text, a) for a in _V211_BROAD_MARKET_TERMS)
    macro = any(_contains_phrase(text, a) for a in _V211_MACRO_TERMS)

    is_index_proxy = symbol in {"SPY", "QQQ", "IWM", "DIA", "^GSPC", "^IXIC"}
    score = 0.58 * base + 0.24 * float(explicit) + 0.11 * float(broad) + 0.07 * float(macro)
    if is_index_proxy and not (explicit or broad or macro):
        # ETF-native company-news endpoints often return single-stock stories.
        # They remain visible/auditable but receive low market-state weight.
        score *= 0.48
    return float(np.clip(score, 0.10, 1.0))


def _v211_taxonomy_scores(title: str, summary: str) -> dict[str, float]:
    title_l = _clean_text(title).lower()
    summary_l = _clean_text(summary).lower()
    out: dict[str, float] = {}
    for theme, keys in _V211_ECONOMIC_THEMES.items():
        title_hits = sum(1 for k in keys if _contains_phrase(title_l, k))
        summary_hits = sum(1 for k in keys if _contains_phrase(summary_l, k))
        out[theme] = 2.4 * title_hits + 0.85 * summary_hits
    return out


def _v211_cluster_label(sub: pd.DataFrame, top_terms: list[str] | None = None) -> tuple[str, float, float, dict[str, float]]:
    """Map a mathematical cluster to an economic narrative only when support is real."""
    if sub is None or sub.empty:
        return _V211_UNRESOLVED, 0.0, 0.0, {}
    weights = pd.to_numeric(sub.get("document_weight", 1.0), errors="coerce").fillna(1.0).clip(lower=0.05)
    totals = defaultdict(float)
    supports = defaultdict(float)
    for pos, (_, row) in enumerate(sub.iterrows()):
        scores = _v211_taxonomy_scores(row.get("title", ""), row.get("summary", ""))
        w = float(weights.iloc[pos])
        for theme, score in scores.items():
            if score > 0:
                totals[theme] += w * score
                supports[theme] += w
    if not totals:
        return _V211_UNRESOLVED, 0.0, 0.0, {}
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    winner, win_score = ranked[0]
    total_score = sum(max(v, 0.0) for v in totals.values())
    win_share = win_score / total_score if total_score > 0 else 0.0
    total_weight = float(weights.sum()) or 1.0
    support_ratio = float(supports[winner] / total_weight)
    density = min(1.0, win_score / max(2.4 * total_weight, 1e-9))
    confidence = 100 * (0.44 * win_share + 0.36 * support_ratio + 0.20 * density)

    n = len(sub)
    if n == 1:
        # A singleton needs a clear title/summary taxonomy signal to be resolved.
        raw = _v211_taxonomy_scores(sub.iloc[0].get("title", ""), sub.iloc[0].get("summary", ""))
        strong_single = raw.get(winner, 0.0) >= 2.4
        resolved = strong_single and confidence >= 52
    else:
        resolved = (support_ratio >= 0.34 and confidence >= 50 and win_share >= 0.48)
    # Reliability score is evidence confidence, not a probability. Single-story
    # labels are deliberately capped because there is no cross-document confirmation.
    confidence = min(confidence, 82.0 if n == 1 else 96.0)
    if not resolved:
        return _V211_UNRESOLVED, float(round(confidence, 1)), float(round(support_ratio * 100, 1)), dict(totals)
    return winner, float(round(confidence, 1)), float(round(support_ratio * 100, 1)), dict(totals)


def _v211_story_groups(work: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Group near-duplicate coverage into stories instead of pretending each article is independent evidence."""
    out = work.copy().reset_index(drop=True)
    n = len(out)
    if n == 0:
        return out, {"story_count": 0, "duplicate_story_docs": 0, "story_compression": 0.0}
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    if SKLEARN_AVAILABLE and n >= 2:
        try:
            titles = out["title"].map(_normalize_title).str.replace("federal reserve", "fed", regex=False).tolist()
            text = (out["title"].fillna("") + ". " + out["summary"].fillna("")).astype(str).tolist()
            tv = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1, max_features=6000)
            tm = tv.fit_transform(titles)
            title_sim = cosine_similarity(tm)
            wv = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), min_df=1, max_features=5000, sublinear_tf=True)
            wm = wv.fit_transform(text)
            text_sim = cosine_similarity(wm)
            times = pd.to_datetime(out.get("published"), errors="coerce", utc=True)
            for i in range(n):
                for j in range(i):
                    close_time = True
                    if times.notna().iloc[i] and times.notna().iloc[j]:
                        close_time = abs((times.iloc[i] - times.iloc[j]).total_seconds()) <= 96 * 3600
                    if not close_time:
                        continue
                    tsi = float(title_sim[i, j])
                    xsi = float(text_sim[i, j])
                    ti = set(titles[i].split())
                    tj = set(titles[j].split())
                    jac = len(ti & tj) / max(len(ti | tj), 1)
                    if tsi >= 0.84 or (tsi >= 0.62 and xsi >= 0.72) or xsi >= 0.88 or jac >= 0.58:
                        union(i, j)
        except Exception:
            pass

    roots = [find(i) for i in range(n)]
    remap = {root: idx for idx, root in enumerate(dict.fromkeys(roots))}
    out["story_id"] = [remap[r] for r in roots]
    story_sizes = out.groupby("story_id").size().to_dict()
    out["story_size"] = out["story_id"].map(story_sizes).astype(int)
    out["story_weight"] = 1.0 / out["story_size"].clip(lower=1)
    story_count = int(out["story_id"].nunique())
    duplicate_story_docs = int(n - story_count)
    return out, {
        "story_count": story_count,
        "duplicate_story_docs": duplicate_story_docs,
        "story_compression": float(duplicate_story_docs / max(n, 1)),
    }


def _v211_cluster_documents(work: pd.DataFrame) -> tuple[np.ndarray, dict[int, list[str]], np.ndarray | None, str, dict[str, float]]:
    n = len(work)
    if n == 0:
        return np.array([], dtype=int), {}, None, "EMPTY", {"silhouette": np.nan, "cohesion": 0.0, "cluster_count": 0}
    texts = (
        work["title"].fillna("").astype(str) + ". " +
        work["title"].fillna("").astype(str) + ". " +
        work["summary"].fillna("").astype(str)
    ).tolist()
    if not SKLEARN_AVAILABLE or n < 5:
        labels = np.arange(n, dtype=int)
        return labels, {int(i): [] for i in labels}, None, "TAXONOMY / SINGLE-STORY FALLBACK", {
            "silhouette": np.nan, "cohesion": 55.0, "cluster_count": int(n),
        }
    try:
        vectorizer = TfidfVectorizer(
            lowercase=True, strip_accents="unicode", stop_words="english", ngram_range=(1, 2),
            min_df=1, max_df=0.88, max_features=4500, sublinear_tf=True,
        )
        matrix = vectorizer.fit_transform(texts)
        if matrix.shape[1] == 0:
            raise ValueError("empty vocabulary")
        if n >= 8 and matrix.shape[1] >= 12:
            n_components = max(2, min(24, n - 1, matrix.shape[1] - 1))
            svd = TruncatedSVD(n_components=n_components, random_state=17)
            dense = Normalizer(copy=False).fit_transform(svd.fit_transform(matrix))
            backend = "TF-IDF + LSA COSINE / AGGLOMERATIVE · V2.1.1 STRICT"
            distance_threshold = 0.58
        else:
            dense = Normalizer(copy=False).fit_transform(matrix.toarray().astype(float))
            backend = "TF-IDF COSINE / AGGLOMERATIVE · V2.1.1 STRICT"
            distance_threshold = 0.50
        clusterer = AgglomerativeClustering(
            n_clusters=None, metric="cosine", linkage="average", distance_threshold=distance_threshold,
        )
        labels = clusterer.fit_predict(dense).astype(int)
        feature_names = np.asarray(vectorizer.get_feature_names_out())
        top_terms: dict[int, list[str]] = {}
        cohesions = []
        sim = cosine_similarity(dense)
        for lab in np.unique(labels):
            idx = np.where(labels == lab)[0]
            centroid = np.asarray(matrix[idx].mean(axis=0)).ravel()
            order = centroid.argsort()[::-1][:10] if centroid.size else []
            top_terms[int(lab)] = [str(feature_names[i]) for i in order if centroid[i] > 0]
            if len(idx) <= 1:
                cohesions.append(0.55)
            else:
                vals = sim[np.ix_(idx, idx)]
                tri = vals[np.triu_indices(len(idx), k=1)]
                cohesions.append(float(np.nanmean(tri)) if len(tri) else 0.55)
        silhouette = np.nan
        unique = np.unique(labels)
        if 1 < len(unique) < n:
            try:
                from sklearn.metrics import silhouette_score
                silhouette = float(silhouette_score(dense, labels, metric="cosine"))
            except Exception:
                silhouette = np.nan
        return labels, top_terms, dense, backend, {
            "silhouette": silhouette,
            "cohesion": float(np.clip(100 * np.nanmean(cohesions), 0, 100)) if cohesions else 0.0,
            "cluster_count": int(len(np.unique(labels))),
        }
    except Exception:
        labels = np.arange(n, dtype=int)
        return labels, {int(i): [] for i in labels}, None, "LEXICAL / SINGLE-STORY FALLBACK", {
            "silhouette": np.nan, "cohesion": 45.0, "cluster_count": int(n),
        }


def extract_belief(title: str, summary: str, provider_sentiment: Any = None, document_relevance: float = 1.0) -> BeliefRecordV211:
    title_c = _clean_text(title)
    summary_c = _clean_text(summary)
    text = f"{title_c} {summary_c}".strip()
    lex_sent, uncertainty = _lexical_sentiment(text)
    ps = _provider_sentiment(provider_sentiment)
    sentiment = 0.68 * lex_sent + 0.32 * ps if ps is not None else lex_sent

    low = text.lower()
    explicit_markers = sum(1 for m in _V211_EXPLICIT_BELIEF_MARKERS if _contains_phrase(low, m))
    pos_hits = sum(1 for t in _tokens(low) if t in _POSITIVE_BELIEF_WORDS)
    neg_hits = sum(1 for t in _tokens(low) if t in _NEGATIVE_BELIEF_WORDS)
    directional_hits = pos_hits + neg_hits
    question_like = "?" in title_c or bool(re.search(r"\b(buy|hold|sell)\s*,?\s*(or|vs\.?|versus)\b", title_c.lower()))
    if question_like and explicit_markers == 0 and (ps is None or abs(ps) < 0.35):
        sentiment *= 0.22

    if explicit_markers >= 1 and directional_hits >= 1:
        inference_type = "OBSERVED STATEMENT"
    elif directional_hits >= 2 or (ps is not None and abs(ps) >= 0.25):
        inference_type = "INFERRED"
    else:
        inference_type = "WEAK INFERENCE"
        sentiment *= 0.55

    sentiment = float(np.clip(sentiment, -1, 1))
    if sentiment >= 0.18:
        direction = "BULLISH"
    elif sentiment <= -0.18:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL / MIXED"

    abs_s = abs(sentiment)
    magnitude = "STRONG" if abs_s >= 0.65 else "MODERATE" if abs_s >= 0.38 else "MILD" if abs_s >= 0.18 else "NEUTRAL"
    toks = _tokens(text)
    certainty = sum(1 for t in toks if t in _CERTAINTY_WORDS)
    hedges = sum(1 for t in toks if t in _HEDGE_WORDS or t in UNCERTAINTY_WORDS)
    confidence = 0.34 + 0.22 * min(abs_s, 1.0) + 0.045 * min(explicit_markers, 3) + 0.018 * min(certainty, 6) - 0.025 * min(hedges, 6)
    confidence *= (1.0 - 0.22 * uncertainty)
    confidence *= (0.72 + 0.28 * float(np.clip(document_relevance, 0, 1)))
    if inference_type == "WEAK INFERENCE":
        confidence = min(confidence, 0.46)
    elif inference_type == "INFERRED":
        confidence = min(confidence, 0.74)
    else:
        confidence = min(confidence, 0.92)
    confidence = float(np.clip(confidence, 0.12, 0.92))

    conditionality = "CONDITIONAL" if any(m in f" {low} " for m in _V211_CONDITIONAL_MARKERS) else "UNCONDITIONAL / UNSPECIFIED"
    return BeliefRecordV211(
        direction=direction,
        score=sentiment,
        confidence=confidence,
        magnitude=magnitude,
        horizon=_extract_horizon(text),
        driver=_extract_driver(text),
        mental_model=_extract_mental_model(text),
        claim=_extract_claim(title_c, summary_c),
        inference_type=inference_type,
        conditionality=conditionality,
    )


def empty_analysis() -> dict[str, Any]:
    base = {
        "count": 0, "raw_count": 0, "dedup_removed": 0, "provider_count": 0, "source_count": 0,
        "story_count": 0, "duplicate_story_docs": 0, "story_compression": 0.0,
        "sentiment_mean": 0.0, "sentiment_std": 0.0, "negative_share": 0.0, "uncertainty_share": 0.0,
        "theme_concentration": 0.0, "theme_entropy": 1.0, "headline_redundancy": 0.0, "semantic_redundancy": 0.0,
        "belief_confidence_mean": 0.0, "belief_disagreement": 50.0, "belief_bullish_share": 0.0,
        "belief_bearish_share": 0.0, "belief_neutral_share": 0.0,
        "narrative_state_score": 35.0, "narrative_momentum": 0.0, "narrative_acceleration": 0.0,
        "narrative_persistence": 0.0, "narrative_consensus": 50.0, "narrative_polarization": 0.0,
        "dominant_narrative": "N/A", "dominant_lifecycle": "N/A", "dominant_mental_model": "MIXED / UNIDENTIFIED",
        "corpus_quality": 0.0, "provider_diversity_score": 0.0, "cluster_separation_score": 0.0,
        "cluster_cohesion_score": 0.0, "label_confidence_score": 0.0, "resolved_coverage": 0.0,
        "belief_extraction_quality": 0.0, "semantic_validity_score": 0.0, "nlp_evidence_score": 0.0,
        "backend": "UNAVAILABLE", "themes": pd.DataFrame(columns=["Theme", "Mentions", "Share"]),
        "narratives": pd.DataFrame(), "beliefs": pd.DataFrame(), "headline_scores": pd.DataFrame(),
        "narrative_timeline": pd.DataFrame(), "narrative_belief_matrix": pd.DataFrame(), "narrative_phase_space": pd.DataFrame(),
        "provider_diagnostics": [],
    }
    return base


def analyze_news_corpus(news_df: pd.DataFrame, symbol: str | None = None) -> dict[str, Any]:
    if news_df is None or news_df.empty:
        return empty_analysis()
    raw = news_df.copy()
    for col in _EMPTY_NEWS_COLUMNS:
        if col not in raw.columns:
            raw[col] = np.nan
    raw["published"] = pd.to_datetime(raw["published"], errors="coerce", utc=True)
    raw["title"] = raw["title"].map(_clean_text)
    raw["summary"] = raw["summary"].map(_clean_text)
    raw["provider"] = raw["provider"].fillna("Unknown").astype(str)
    raw["source"] = raw["source"].fillna("Unknown").astype(str)
    raw = raw[raw["title"].str.len() >= 5].copy()
    if raw.empty:
        return empty_analysis()

    # Exact and only ultra-high semantic duplicates are removed. Near-duplicates
    # remain auditable but are compressed at story level below.
    work = raw.sort_values("published", ascending=False, na_position="last").copy().reset_index(drop=True)
    work["title_norm"] = work["title"].map(_normalize_title)
    before = len(work)
    work = work.drop_duplicates("title_norm", keep="first").reset_index(drop=True)
    exact_removed = before - len(work)
    semantic_removed = 0
    if SKLEARN_AVAILABLE and len(work) >= 3:
        try:
            vect = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=1, max_features=6000)
            mat = vect.fit_transform(work["title_norm"].tolist())
            sims = cosine_similarity(mat)
            keep: list[int] = []
            for i in range(len(work)):
                if not keep or max(float(sims[i, j]) for j in keep) < 0.975:
                    keep.append(i)
            semantic_removed = len(work) - len(keep)
            work = work.iloc[keep].reset_index(drop=True)
        except Exception:
            semantic_removed = 0
    work = work.drop(columns=["title_norm"], errors="ignore")

    work["document_relevance"] = [
        _v211_document_relevance(r.get("title", ""), r.get("summary", ""), symbol or r.get("symbol"), r.get("relevance"))
        for _, r in work.iterrows()
    ]
    work, story_diag = _v211_story_groups(work)
    work["document_weight"] = work["story_weight"] * (0.30 + 0.70 * work["document_relevance"])

    # Cluster one representative per story so syndicated coverage cannot create a false narrative.
    reps = []
    for sid, sub in work.groupby("story_id", sort=False):
        rank = sub.copy()
        rank["_len"] = rank["summary"].fillna("").astype(str).str.len()
        rank["_rank"] = rank["document_relevance"] + 0.0005 * rank["_len"].clip(upper=800)
        rep = rank.sort_values("_rank", ascending=False).iloc[0].copy()
        rep["story_id"] = sid
        reps.append(rep)
    story_frame = pd.DataFrame(reps).reset_index(drop=True)
    story_labels, top_terms, story_embeddings, backend, cluster_diag = _v211_cluster_documents(story_frame)
    story_frame["cluster_id"] = story_labels
    story_to_cluster = dict(zip(story_frame["story_id"].astype(int), story_frame["cluster_id"].astype(int)))
    work["cluster_id"] = work["story_id"].map(story_to_cluster).astype(int)

    label_rows = []
    cluster_label_map: dict[int, str] = {}
    cluster_label_conf: dict[int, float] = {}
    cluster_support: dict[int, float] = {}
    for cid in sorted(work["cluster_id"].unique().tolist()):
        sub = work[work["cluster_id"] == cid]
        label, conf, support, votes = _v211_cluster_label(sub, top_terms.get(int(cid), []))
        cluster_label_map[int(cid)] = label
        cluster_label_conf[int(cid)] = conf
        cluster_support[int(cid)] = support
        label_rows.append({"cluster_id": int(cid), "label": label, "confidence": conf, "support": support, "votes": votes})
    work["narrative"] = work["cluster_id"].map(cluster_label_map).fillna(_V211_UNRESOLVED)
    work["label_confidence"] = work["cluster_id"].map(cluster_label_conf).fillna(0.0)
    work["label_support"] = work["cluster_id"].map(cluster_support).fillna(0.0)
    merged_ids, merged_labels = pd.factorize(work["narrative"], sort=False)
    work["narrative_id"] = merged_ids.astype(int)
    merged_label_map = {int(i): str(label) for i, label in enumerate(merged_labels.tolist())}

    belief_rows = []
    doc_sentiments = []
    doc_uncertainty = []
    for i, row in work.iterrows():
        belief = extract_belief(
            row.get("title", ""), row.get("summary", ""), row.get("provider_sentiment"),
            document_relevance=float(row.get("document_relevance", 1.0)),
        )
        _, uncertainty = _lexical_sentiment(f"{row.get('title','')} {row.get('summary','')}")
        doc_sentiments.append(belief.score)
        doc_uncertainty.append(uncertainty)
        belief_rows.append({
            "published": row.get("published"), "provider": row.get("provider"), "source": row.get("source"),
            "title": row.get("title"), "narrative": row.get("narrative"), "label_confidence": row.get("label_confidence"),
            "belief_direction": belief.direction, "belief_score": belief.score, "belief_confidence": belief.confidence,
            "magnitude": belief.magnitude, "inference_type": belief.inference_type, "conditionality": belief.conditionality,
            "horizon": belief.horizon, "driver": belief.driver, "mental_model": belief.mental_model, "claim": belief.claim,
            "uncertainty": uncertainty, "semantic_novelty": np.nan, "relevance": float(row.get("document_relevance", 0.5)),
            "story_id": int(row.get("story_id", i)), "story_size": int(row.get("story_size", 1)),
        })
    beliefs = pd.DataFrame(belief_rows)
    work["sentiment"] = np.asarray(doc_sentiments, dtype=float)
    work["uncertainty"] = np.asarray(doc_uncertainty, dtype=float)
    work["belief_direction"] = beliefs["belief_direction"].to_numpy()
    work["belief_confidence"] = beliefs["belief_confidence"].to_numpy(dtype=float)
    work["driver"] = beliefs["driver"].to_numpy()
    work["mental_model"] = beliefs["mental_model"].to_numpy()

    # Story-level novelty: map representative novelty back to all article variants.
    story_novelty = _semantic_novelty(story_embeddings, story_frame["published"])
    story_frame["semantic_novelty"] = story_novelty
    novelty_map = dict(zip(story_frame["story_id"].astype(int), story_frame["semantic_novelty"].astype(float)))
    work["semantic_novelty"] = work["story_id"].map(novelty_map).fillna(0.5)
    beliefs["semantic_novelty"] = beliefs["story_id"].map(novelty_map).fillna(0.5)

    total_weight = float(work["document_weight"].sum()) or 1.0
    resolved_mask = work["narrative"].ne(_V211_UNRESOLVED)
    resolved_weight = float(work.loc[resolved_mask, "document_weight"].sum())
    resolved_coverage = float(np.clip(resolved_weight / total_weight, 0, 1))
    max_ts = work["published"].max()
    if pd.isna(max_ts):
        max_ts = pd.Timestamp.utcnow(tz="UTC")

    narrative_rows = []
    matrix_rows = []
    for cid, sub in work.groupby("narrative_id", sort=False):
        label = merged_label_map.get(int(cid), str(cid))
        weights = sub["document_weight"].astype(float)
        share = float(weights.sum() / total_weight)
        sentiment = _v211_weighted_mean(sub["sentiment"], weights, 0.0)
        sent_vals = pd.to_numeric(sub["sentiment"], errors="coerce").fillna(0).to_numpy()
        wvals = weights.to_numpy()
        sentiment_std = float(np.sqrt(np.average((sent_vals - sentiment) ** 2, weights=wvals))) if len(sub) > 1 and wvals.sum() > 0 else 0.0
        dir_weights = {d: float(weights[sub["belief_direction"].eq(d)].sum()) for d in ["BULLISH", "BEARISH", "NEUTRAL / MIXED"]}
        denom = sum(dir_weights.values()) or 1.0
        bull, bear, neutral = (dir_weights["BULLISH"] / denom, dir_weights["BEARISH"] / denom, dir_weights["NEUTRAL / MIXED"] / denom)
        polarization = float(np.clip(200 * min(bull, bear) + 35 * sentiment_std, 0, 100))
        direction_consistency = max(bull, bear, neutral)
        consensus = float(np.clip(100 * (0.55 * direction_consistency + 0.45 * (1 - min(sentiment_std, 1))), 0, 100))
        novelty = float(np.clip(100 * _v211_weighted_mean(sub["semantic_novelty"], weights, 0.5), 0, 100))
        belief_conf = float(np.clip(100 * _v211_weighted_mean(sub["belief_confidence"], weights, 0.0), 0, 100))
        source_diversity = min(1.0, sub["source"].nunique() / max(sub["story_id"].nunique(), 1))
        provider_diversity = min(1.0, sub["provider"].nunique() / max(sub["story_id"].nunique(), 1))
        ages = (max_ts - pd.to_datetime(sub["published"], errors="coerce", utc=True)).dt.total_seconds() / 86400.0
        recency = float(np.nanmean(np.exp(-np.clip(ages, 0, 30) / 5.0))) if ages.notna().any() else 0.5
        label_conf = _v211_weighted_mean(sub["label_confidence"], weights, 0.0)
        quality_multiplier = 0.45 + 0.55 * min(label_conf / 100.0, 1.0) if label != _V211_UNRESOLVED else 0.30
        intensity = float(np.clip(
            100 * (0.50 * share + 0.14 * source_diversity + 0.10 * provider_diversity + 0.18 * recency + 0.08 * min(label_conf / 100.0, 1.0)) * quality_multiplier,
            0, 100,
        ))

        # Window shares are still snapshot-only. They are based on weighted story evidence.
        def weighted_share(start_days: float, end_days: float) -> float | None:
            ts = pd.to_datetime(work["published"], errors="coerce", utc=True)
            age = (max_ts - ts).dt.total_seconds() / 86400.0
            mask = (age >= start_days) & (age < end_days)
            denom_w = float(work.loc[mask, "document_weight"].sum())
            if denom_w <= 0:
                return None
            return float(work.loc[mask & work["narrative_id"].eq(cid), "document_weight"].sum() / denom_w)

        s0, s1, s2 = weighted_share(0, 2), weighted_share(2, 5), weighted_share(5, 9)
        momentum = 100 * (s0 - s1) if s0 is not None and s1 is not None else np.nan
        acceleration = 100 * ((s0 - s1) - (s1 - s2)) if s0 is not None and s1 is not None and s2 is not None else np.nan
        ts2 = pd.to_datetime(sub["published"], errors="coerce", utc=True).dropna()
        persistence_days = float((ts2.max() - ts2.min()).total_seconds() / 86400.0) if len(ts2) >= 2 else 0.0
        lifecycle = "UNRESOLVED" if label == _V211_UNRESOLVED else _lifecycle(
            share=share, intensity=intensity, momentum=_safe_float(momentum), acceleration=_safe_float(acceleration),
            novelty=novelty, consensus=consensus, sentiment=sentiment, persistence_days=persistence_days,
        )
        narrative_rows.append({
            "Narrative": label, "Mentions": int(len(sub)), "Stories": int(sub["story_id"].nunique()), "Share": share,
            "Intensity": round(intensity, 1), "Momentum 2D": round(float(momentum), 1) if np.isfinite(momentum) else np.nan,
            "Acceleration": round(float(acceleration), 1) if np.isfinite(acceleration) else np.nan,
            "Persistence d": round(persistence_days, 1), "Consensus": round(consensus, 1), "Polarization": round(polarization, 1),
            "Novelty": round(novelty, 1), "Belief confidence": round(belief_conf, 1), "Label confidence": round(label_conf, 1),
            "Sentiment": round(sentiment, 3), "Uncertainty": round(100 * _v211_weighted_mean(sub["uncertainty"], weights, 0.0), 1),
            "Sources": int(sub["source"].nunique()), "Providers": int(sub["provider"].nunique()), "Lifecycle": lifecycle,
            "cluster_id": int(cid),
        })
        matrix_rows.append({
            "Narrative": label, "Bullish": bull, "Neutral / mixed": neutral, "Bearish": bear, "Consensus": consensus,
            "Share": share, "Momentum": float(momentum) if np.isfinite(momentum) else np.nan, "Sentiment": sentiment,
            "Label confidence": label_conf, "Lifecycle": lifecycle,
        })

    narratives = pd.DataFrame(narrative_rows)
    if not narratives.empty:
        narratives = narratives.sort_values(["Share", "Intensity"], ascending=False).reset_index(drop=True)
    belief_matrix = pd.DataFrame(matrix_rows)

    resolved_narratives = narratives[narratives["Narrative"].ne(_V211_UNRESOLVED)].copy() if not narratives.empty else pd.DataFrame()
    shares = resolved_narratives["Share"].astype(float).tolist() if not resolved_narratives.empty else []
    concentration = max(shares) if shares else 0.0
    entropy = _normalized_entropy(shares) if shares else 1.0
    semantic_redundancy = float(np.clip(story_diag.get("story_compression", 0.0), 0, 1))
    dedup_removed = int(exact_removed + semantic_removed)
    headline_redundancy = float(np.clip(0.55 * semantic_redundancy + 0.45 * dedup_removed / max(before, 1), 0, 1))

    # Belief distribution weighted by story/relevance and confidence tier.
    bweights = work["document_weight"].astype(float) * (0.45 + 0.55 * work["belief_confidence"].astype(float))
    dir_w = {d: float(bweights[work["belief_direction"].eq(d)].sum()) for d in ["BULLISH", "BEARISH", "NEUTRAL / MIXED"]}
    bden = sum(dir_w.values()) or 1.0
    bull_share, bear_share, neutral_share = dir_w["BULLISH"] / bden, dir_w["BEARISH"] / bden, dir_w["NEUTRAL / MIXED"] / bden
    sent = pd.to_numeric(work["sentiment"], errors="coerce").fillna(0)
    sent_mean = _v211_weighted_mean(sent, bweights, 0.0)
    sent_std = float(np.sqrt(np.average((sent.to_numpy() - sent_mean) ** 2, weights=bweights.to_numpy()))) if len(sent) > 1 and bweights.sum() > 0 else 0.0
    belief_disagreement = float(np.clip(100 * (0.55 * (1 - max(bull_share, bear_share, neutral_share)) / (2 / 3) + 0.45 * min(sent_std, 1.0)), 0, 100))
    belief_confidence_mean = float(100 * _v211_weighted_mean(work["belief_confidence"], work["document_weight"], 0.0))

    dominant = resolved_narratives.iloc[0].to_dict() if not resolved_narratives.empty else {}
    dominant_narrative = str(dominant.get("Narrative", _V211_UNRESOLVED))
    dominant_lifecycle = str(dominant.get("Lifecycle", "UNRESOLVED"))
    narrative_momentum = _safe_float(dominant.get("Momentum 2D"), 0.0) or 0.0
    narrative_acceleration = _safe_float(dominant.get("Acceleration"), 0.0) or 0.0
    narrative_persistence = _safe_float(dominant.get("Persistence d"), 0.0) or 0.0
    narrative_consensus = _safe_float(dominant.get("Consensus"), 50.0) or 50.0
    narrative_polarization = _safe_float(dominant.get("Polarization"), 0.0) or 0.0
    dominant_intensity = _safe_float(dominant.get("Intensity"), 0.0) or 0.0
    dominant_label_conf = _safe_float(dominant.get("Label confidence"), 0.0) or 0.0
    narrative_state_score = float(np.clip(
        (25 + 34 * concentration + 0.20 * dominant_intensity + 0.10 * narrative_consensus
         + 0.08 * min(narrative_persistence, 30) + 0.08 * max(narrative_momentum, 0) - 0.08 * narrative_polarization)
        * (0.50 + 0.50 * resolved_coverage) * (0.65 + 0.35 * dominant_label_conf / 100.0),
        0, 100,
    ))

    # Mental model uses only non-weak beliefs and document weights.
    mm = work.copy()
    mm["inference_type"] = beliefs["inference_type"].to_numpy()
    mm = mm[mm["inference_type"].ne("WEAK INFERENCE")]
    if mm.empty:
        dominant_mental_model = "MIXED / UNIDENTIFIED"
    else:
        mm_scores = mm.groupby("mental_model")["document_weight"].sum().sort_values(ascending=False)
        dominant_mental_model = str(mm_scores.index[0]) if not mm_scores.empty else "MIXED / UNIDENTIFIED"

    provider_count = int(work["provider"].nunique())
    source_count = int(work["source"].nunique())
    timestamp_share = float(work["published"].notna().mean())
    corpus_quality = float(np.clip(15 + min(36, 1.05 * len(work)) + min(16, 5 * provider_count) + min(14, 1.2 * source_count) + 8 * timestamp_share, 0, 100))
    provider_diversity_score = float(np.clip(100 * min(1.0, provider_count / 4.0) * 0.65 + 100 * min(1.0, source_count / 12.0) * 0.35, 0, 100))
    silhouette = cluster_diag.get("silhouette", np.nan)
    cluster_separation_score = float(np.clip(50 + 50 * silhouette, 0, 100)) if np.isfinite(silhouette) else 45.0
    cluster_cohesion_score = float(np.clip(cluster_diag.get("cohesion", 0.0), 0, 100))
    label_confidence_score = float(np.clip(_v211_weighted_mean(work.loc[resolved_mask, "label_confidence"], work.loc[resolved_mask, "document_weight"], 0.0), 0, 100)) if resolved_mask.any() else 0.0
    weak_share = float((beliefs["inference_type"] == "WEAK INFERENCE").mean()) if not beliefs.empty else 1.0
    belief_extraction_quality = float(np.clip(0.55 * belief_confidence_mean + 45 * (1 - weak_share), 0, 100))
    semantic_validity_score = float(np.clip(
        0.30 * (100 * resolved_coverage) + 0.30 * label_confidence_score + 0.20 * cluster_separation_score + 0.20 * cluster_cohesion_score,
        0, 100,
    ))
    nlp_evidence_score = float(np.clip(
        0.22 * corpus_quality + 0.14 * provider_diversity_score + 0.34 * semantic_validity_score + 0.30 * belief_extraction_quality,
        0, 100,
    ))

    # Timeline uses canonical labels; unresolved stays visible but is not treated as a coherent market narrative.
    timeline = []
    tmp = work.dropna(subset=["published"]).copy()
    if not tmp.empty and tmp["published"].dt.floor("D").nunique() >= 2:
        tmp["date"] = tmp["published"].dt.floor("D")
        top_labels = narratives.head(6)["Narrative"].tolist() if not narratives.empty else []
        for dt, day in tmp.groupby("date"):
            denom = float(day["document_weight"].sum()) or 1.0
            for lab in top_labels:
                share = float(day.loc[day["narrative"].eq(lab), "document_weight"].sum() / denom)
                timeline.append({"date": dt, "Narrative": lab, "Share": share})
    timeline_df = pd.DataFrame(timeline)

    theme_rows = narratives[["Narrative", "Mentions", "Share"]].rename(columns={"Narrative": "Theme"}) if not narratives.empty else pd.DataFrame(columns=["Theme", "Mentions", "Share"])
    headline_scores = work[[
        "published", "provider", "source", "title", "sentiment", "uncertainty", "narrative", "label_confidence",
        "belief_direction", "belief_confidence", "semantic_novelty", "document_relevance", "story_id", "story_size",
    ]].copy().rename(columns={"narrative": "themes"})
    phase_space = belief_matrix[[c for c in ["Narrative", "Share", "Consensus", "Momentum", "Sentiment", "Label confidence", "Lifecycle"] if c in belief_matrix.columns]].copy()

    provider_diagnostics = []
    provider_raw_count = int(before)
    try:
        provider_diagnostics = list(news_df.attrs.get("provider_attempts", []))
        provider_raw_count = int(news_df.attrs.get("raw_provider_rows", provider_raw_count))
    except Exception:
        pass

    return {
        "count": int(len(work)), "raw_count": int(provider_raw_count), "dedup_removed": int(dedup_removed),
        "story_count": int(story_diag.get("story_count", len(work))), "duplicate_story_docs": int(story_diag.get("duplicate_story_docs", 0)),
        "story_compression": float(story_diag.get("story_compression", 0.0)), "provider_count": provider_count, "source_count": source_count,
        "sentiment_mean": float(sent_mean), "sentiment_std": float(sent_std), "negative_share": float(bear_share),
        "uncertainty_share": float(_v211_weighted_mean(work["uncertainty"], work["document_weight"], 0.0)),
        "theme_concentration": float(concentration), "theme_entropy": float(entropy), "headline_redundancy": headline_redundancy,
        "semantic_redundancy": semantic_redundancy, "belief_confidence_mean": belief_confidence_mean, "belief_disagreement": belief_disagreement,
        "belief_bullish_share": float(bull_share), "belief_bearish_share": float(bear_share), "belief_neutral_share": float(neutral_share),
        "narrative_state_score": narrative_state_score, "narrative_momentum": float(narrative_momentum),
        "narrative_acceleration": float(narrative_acceleration), "narrative_persistence": float(narrative_persistence),
        "narrative_consensus": float(narrative_consensus), "narrative_polarization": float(narrative_polarization),
        "dominant_narrative": dominant_narrative, "dominant_lifecycle": dominant_lifecycle, "dominant_mental_model": dominant_mental_model,
        "corpus_quality": corpus_quality, "provider_diversity_score": provider_diversity_score,
        "cluster_separation_score": cluster_separation_score, "cluster_cohesion_score": cluster_cohesion_score,
        "label_confidence_score": label_confidence_score, "resolved_coverage": float(100 * resolved_coverage),
        "belief_extraction_quality": belief_extraction_quality, "semantic_validity_score": semantic_validity_score,
        "nlp_evidence_score": nlp_evidence_score, "backend": backend,
        "themes": theme_rows, "narratives": narratives.drop(columns=["cluster_id"], errors="ignore"),
        "beliefs": beliefs.sort_values("published", ascending=False, na_position="last").reset_index(drop=True),
        "headline_scores": headline_scores.sort_values("published", ascending=False, na_position="last").reset_index(drop=True),
        "narrative_timeline": timeline_df.sort_values(["date", "Narrative"]).reset_index(drop=True) if not timeline_df.empty else timeline_df,
        "narrative_belief_matrix": belief_matrix, "narrative_phase_space": phase_space,
        "provider_diagnostics": provider_diagnostics,
    }
