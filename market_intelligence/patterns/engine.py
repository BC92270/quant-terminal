"""Governed unsupervised pattern discovery plus supervised OOS challenge."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math
import platform
from typing import Any, Iterable

import numpy as np
import pandas as pd
import scipy
import sklearn
from sklearn.cluster import KMeans
from sklearn.impute import SimpleImputer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import RobustScaler

from ml_lab.institutional_engine import (
    block_bootstrap_sharpe_interval,
    deflated_sharpe_probability,
    feature_drift_report,
)
from ml_lab.modeling_engine import ModelValidationConfig, run_ml_champion_challenger

from ..evidence import canonical_hash, canonical_json
from .contracts import (
    GateState,
    ModelValidationScore,
    PATTERN_ENGINE_VERSION,
    PATTERN_POLICY_VERSION,
    PATTERN_SCHEMA_VERSION,
    PatternCandidate,
    PatternCandidateState,
    PatternDiscoveryConfig,
    PatternDiscoveryReport,
    PatternFitArtifact,
    PatternGate,
    PatternRunState,
)
from .features import PatternFeatureBundle, build_pattern_feature_bundle


_FEATURE_LABELS = {
    "return_lag_0": ("fresh positive return", "fresh negative return"),
    "return_lag_1": ("positive prior return", "negative prior return"),
    "momentum_3": ("positive short momentum", "negative short momentum"),
    "momentum_5": ("positive 5-bar momentum", "negative 5-bar momentum"),
    "momentum_10": ("positive 10-bar momentum", "negative 10-bar momentum"),
    "momentum_20": ("positive medium momentum", "negative medium momentum"),
    "momentum_60": ("positive long momentum", "negative long momentum"),
    "volatility_5": ("elevated short volatility", "suppressed short volatility"),
    "volatility_20": ("elevated medium volatility", "suppressed medium volatility"),
    "volatility_60": ("elevated long volatility", "suppressed long volatility"),
    "downside_volatility_20": ("elevated downside volatility", "suppressed downside volatility"),
    "trend_distance_10": ("price above short trend", "price below short trend"),
    "trend_distance_20": ("price above medium trend", "price below medium trend"),
    "drawdown_60": ("near the 60-bar high", "deep 60-bar drawdown"),
    "intrabar_range": ("wide intrabar range", "compressed intrabar range"),
    "close_location": ("close near bar high", "close near bar low"),
    "opening_gap": ("positive opening gap", "negative opening gap"),
    "volume_robust_z_20": ("unusually high volume", "unusually low volume"),
    "amihud_20": ("elevated price impact proxy", "low price impact proxy"),
}


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _runtime_versions() -> tuple[tuple[str, str], ...]:
    """Bind the numerical runtime to every signed research artifact."""

    return (
        ("python", platform.python_version()),
        ("numpy", str(np.__version__)),
        ("pandas", str(pd.__version__)),
        ("scipy", str(scipy.__version__)),
        ("scikit-learn", str(sklearn.__version__)),
    )


def _as_utc(value: datetime) -> datetime:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp.to_pydatetime().astimezone(timezone.utc)


def _evaluation_time(bundle: PatternFeatureBundle, evaluation_clock: datetime | None) -> datetime:
    """Never sign a report before any data-availability clock it contains."""

    clocks = [
        _as_utc(evaluation_clock) if evaluation_clock is not None else datetime.now(timezone.utc),
        bundle.audit.data_cutoff,
        bundle.audit.source_known_at,
        bundle.audit.latest_row_known_at,
    ]
    return max(clock for clock in clocks if clock is not None)


def _finalize_report(material: dict[str, Any]) -> PatternDiscoveryReport:
    content_hash = canonical_hash(material)
    report = PatternDiscoveryReport(
        report_id="MI-PAT-" + content_hash[:20].upper(),
        content_hash=content_hash,
        **material,
    )
    if not report.verify_hash():
        raise ValueError("Pattern report hash verification failed")
    return report


def _waiting_report(
    bundle: PatternFeatureBundle,
    config: PatternDiscoveryConfig,
    *,
    state: PatternRunState,
    reason: str,
    evaluation_clock: datetime | None,
    evaluated_at_override: datetime | None = None,
) -> PatternDiscoveryReport:
    evaluated_at = (
        _as_utc(evaluated_at_override)
        if evaluated_at_override is not None
        else _evaluation_time(bundle, evaluation_clock)
    )
    audit_state = GateState.FAIL if bundle.audit.blocking_reasons else GateState.WAITING_EVIDENCE
    gates = (
        PatternGate(
            "INPUT_CONTRACT",
            audit_state,
            reason,
            f"Normalized {bundle.audit.normalized_rows} of {bundle.audit.raw_rows} inherited rows.",
        ),
        PatternGate(
            "MODEL_FIT",
            GateState.NOT_APPLICABLE,
            "No estimator was fitted.",
            "Fail-closed before unsupervised or supervised training.",
        ),
        PatternGate(
            "AUTONOMOUS_EXECUTION",
            GateState.PASS,
            "Execution is prohibited by contract.",
            "autonomous_trading=false; execution_allowed=false",
            blocks_strategic_admission=False,
        ),
    )
    return _finalize_report(
        {
            "schema_version": PATTERN_SCHEMA_VERSION,
            "engine_version": PATTERN_ENGINE_VERSION,
            "policy_version": PATTERN_POLICY_VERSION,
            "state": state,
            "reason": reason,
            "symbol": bundle.audit.symbol,
            "evaluated_at": evaluated_at,
            "input_audit": bundle.audit,
            "config": config,
            "feature_names": tuple(bundle.features.columns),
            "usable_rows": len(bundle.features),
            "train_rows": 0,
            "purge_rows": 0,
            "holdout_rows": 0,
            "selected_clusters": None,
            "silhouette_score": None,
            "current_pattern_id": None,
            "nearest_pattern_id": None,
            "current_assignment_status": "NOT_AVAILABLE",
            "candidates": (),
            "gates": gates,
            "supervised_engine_version": None,
            "supervised_champion": None,
            "supervised_promotion_status": "NOT_RUN",
            "model_scores": (),
            "runtime_versions": _runtime_versions(),
            "fit_artifact": None,
            "autonomous_trading": False,
            "human_review_required": True,
            "execution_allowed": False,
            "order_payload": None,
        }
    )


def _select_cluster_model(
    train_scaled: np.ndarray,
    config: PatternDiscoveryConfig,
) -> tuple[KMeans, int, float, tuple[tuple[int, float], ...]]:
    maximum = min(config.max_clusters, max(config.min_clusters, len(train_scaled) // 12))
    trials: list[tuple[KMeans, int, float]] = []
    for clusters in range(config.min_clusters, maximum + 1):
        if len(train_scaled) <= clusters:
            continue
        model = KMeans(
            n_clusters=clusters,
            n_init=20,
            max_iter=500,
            random_state=config.random_state + clusters,
            algorithm="lloyd",
        )
        labels = model.fit_predict(train_scaled)
        counts = np.bincount(labels, minlength=clusters)
        minimum_cluster = max(5, int(math.ceil(len(train_scaled) * 0.03)))
        if int(counts.min()) < minimum_cluster or len(np.unique(labels)) < 2:
            continue
        score = float(silhouette_score(train_scaled, labels, metric="euclidean"))
        trials.append((model, clusters, score))
    if not trials:
        raise ValueError("No stable cluster partition satisfied minimum training depth.")
    trials.sort(key=lambda item: (item[2], -item[1]), reverse=True)
    model, clusters, score = trials[0]
    search = tuple((candidate_clusters, candidate_score) for _, candidate_clusters, candidate_score in trials)
    return model, clusters, score, search


def _signature(feature_names: Iterable[str], centroid: np.ndarray) -> str:
    pairs = sorted(
        zip(feature_names, centroid),
        key=lambda item: abs(float(item[1])),
        reverse=True,
    )
    phrases: list[str] = []
    for name, value in pairs:
        if abs(float(value)) < 0.25:
            continue
        positive, negative = _FEATURE_LABELS.get(
            str(name),
            (f"high {str(name).replace('_', ' ')}", f"low {str(name).replace('_', ' ')}"),
        )
        phrases.append(positive if float(value) >= 0.0 else negative)
        if len(phrases) == 3:
            break
    return " · ".join(phrases) if phrases else "Near-centroid mixed market state"


def _benjamini_yekutieli(values: list[float | None]) -> list[float | None]:
    """Conservative run-local adjustment valid under arbitrary dependence.

    Missing diagnostics remain in the disclosed family as p=1 but are returned
    as ``None`` so insufficient evidence is never visually converted into a
    numerical result.
    """

    valid = [(index, float(value)) for index, value in enumerate(values) if value is not None]
    if not valid:
        return [None for _ in values]
    ordered = sorted(valid, key=lambda item: item[1])
    adjusted: dict[int, float] = {}
    running = 1.0
    # Under-powered hypotheses stay unreported but remain in the family as p=1.
    # Otherwise missing tests would make the multiplicity penalty spuriously
    # smaller precisely when a cluster lacks enough evidence.
    family_size = len(values)
    harmonic = sum(1.0 / rank for rank in range(1, family_size + 1))
    for rank in range(len(ordered), 0, -1):
        index, value = ordered[rank - 1]
        running = min(running, value * family_size * harmonic / rank)
        adjusted[index] = max(0.0, min(1.0, running))
    return [adjusted.get(index) for index in range(len(values))]


def _circular_shift_uplift_pvalue(
    outcomes: np.ndarray,
    selected: np.ndarray,
    *,
    seed: int,
    simulations: int = 999,
) -> float | None:
    """Test conditional uplift while preserving the complete OOS chronology.

    The directional after-cost outcome series is never compressed to event
    rows.  Circularly shifting the train-frozen cluster mask preserves both
    serial dependence in outcomes and the pattern's occurrence/run structure.
    This is a run-local randomisation test, not a global experiment correction.
    """

    values = np.asarray(outcomes, dtype=float)
    mask = np.asarray(selected, dtype=bool)
    finite = np.isfinite(values)
    if len(values) != len(mask) or len(values) < 5 or not finite.all():
        return None
    if int(mask.sum()) < 5 or int((~mask).sum()) < 5:
        return None
    observed = float(np.mean(values[mask]) - np.mean(values[~mask]))
    if observed <= 0.0:
        return 1.0
    shifts = np.arange(1, len(values), dtype=int)
    rng = np.random.default_rng(seed)
    if len(shifts) > simulations:
        shifts = np.sort(rng.choice(shifts, size=simulations, replace=False))
    exceedances = 0
    for shift in shifts:
        shifted = np.roll(mask, int(shift))
        uplift = float(np.mean(values[shifted]) - np.mean(values[~shifted]))
        if uplift >= observed:
            exceedances += 1
    return float((exceedances + 1) / (len(shifts) + 1))


def _candidate_state(
    *,
    oos_occurrences: int,
    after_cost_mean: float | None,
    conditional_uplift: float | None,
    q_value: float | None,
    stability: str,
    dsr: float | None,
    sharpe_lower: float | None,
    config: PatternDiscoveryConfig,
) -> PatternCandidateState:
    if oos_occurrences < config.min_oos_occurrences:
        return PatternCandidateState.INSUFFICIENT_OOS
    if (
        after_cost_mean is None
        or after_cost_mean <= 0.0
        or conditional_uplift is None
        or conditional_uplift <= 0.0
    ):
        return PatternCandidateState.REJECTED_OOS
    if (
        q_value is not None
        and q_value <= config.fdr_alpha
        and stability == "STABLE_ACROSS_OOS_HALVES"
        and dsr is not None
        and dsr >= 0.95
        and sharpe_lower is not None
        and sharpe_lower > 0.0
    ):
        return PatternCandidateState.RUN_LOCAL_SCREENED_HYPOTHESIS
    return PatternCandidateState.PROMISING_HYPOTHESIS


def _build_candidates(
    *,
    bundle: PatternFeatureBundle,
    train_labels: np.ndarray,
    holdout_labels: np.ndarray,
    current_cluster: int,
    current_distances: np.ndarray,
    train_distances: np.ndarray,
    model: KMeans,
    config: PatternDiscoveryConfig,
    cluster_trials: int,
) -> tuple[PatternCandidate, ...]:
    forward = bundle.forward_returns.to_numpy(dtype=float)
    train_rows = len(train_labels)
    holdout_rows = len(holdout_labels)
    holdout_forward = forward[-holdout_rows:]
    train_forward = forward[:train_rows]
    cost = float(config.transaction_cost_bps) / 10_000.0
    provisional: list[dict[str, Any]] = []
    p_values: list[float | None] = []
    for cluster in range(model.n_clusters):
        train_selected = train_labels == cluster
        holdout_selected = holdout_labels == cluster
        train_values = train_forward[train_selected]
        oos_values = holdout_forward[holdout_selected]
        train_mean = _safe_float(np.mean(train_values)) if len(train_values) else None
        if train_mean is None or abs(train_mean) <= cost:
            direction = "NEUTRAL"
            direction_value = 0.0
        elif train_mean > 0.0:
            direction = "UP"
            direction_value = 1.0
        else:
            direction = "DOWN"
            direction_value = -1.0
        if direction_value == 0.0:
            directional_oos = np.zeros(holdout_rows, dtype=float)
        else:
            directional_oos = direction_value * holdout_forward - cost
        net = directional_oos[holdout_selected]
        rest_net = directional_oos[~holdout_selected]
        oos_mean = _safe_float(np.mean(oos_values)) if len(oos_values) else None
        net_mean = _safe_float(np.mean(net)) if len(net) else None
        rest_mean = _safe_float(np.mean(rest_net)) if len(rest_net) else None
        conditional_uplift = (
            _safe_float(net_mean - rest_mean)
            if net_mean is not None and rest_mean is not None
            else None
        )
        hit_rate = _safe_float(np.mean(net > 0.0)) if len(net) else None
        strategy_returns = np.zeros(holdout_rows, dtype=float)
        strategy_returns[holdout_selected] = net
        interval = block_bootstrap_sharpe_interval(
            strategy_returns,
            annualisation=1,
            block_length=max(2, config.horizon_bars),
            simulations=300,
            seed=config.random_state + cluster,
        )
        strategy_sharpe = _safe_float(interval.get("sharpe"))
        strategy_sharpe_lower = _safe_float(interval.get("lower"))
        selected_positions = np.flatnonzero(holdout_selected)
        nonoverlap_positions: list[int] = []
        for position in selected_positions:
            if (
                not nonoverlap_positions
                or int(position) - nonoverlap_positions[-1] >= config.horizon_bars
            ):
                nonoverlap_positions.append(int(position))
        nonoverlap_returns = directional_oos[np.asarray(nonoverlap_positions, dtype=int)]
        dsr = (
            _safe_float(
                deflated_sharpe_probability(
                    nonoverlap_returns,
                    trials=max(1, model.n_clusters * cluster_trials),
                )
            )
            if len(nonoverlap_returns) >= 20
            else None
        )
        p_value = _circular_shift_uplift_pvalue(
            directional_oos,
            holdout_selected,
            seed=config.random_state + 10_000 + cluster,
        )
        p_values.append(p_value)
        half = len(holdout_labels) // 2
        nonoverlap_index = np.asarray(nonoverlap_positions, dtype=int)
        first = directional_oos[nonoverlap_index[nonoverlap_index < half]]
        second = directional_oos[nonoverlap_index[nonoverlap_index >= half]]
        if len(first) >= 3 and len(second) >= 3:
            stability = (
                "STABLE_ACROSS_OOS_HALVES"
                if float(np.mean(first)) > 0.0 and float(np.mean(second)) > 0.0
                else "UNSTABLE_ACROSS_OOS_HALVES"
            )
        else:
            stability = "INSUFFICIENT_SUBPERIOD_DEPTH"
        pattern_id = "MI-PAT-" + canonical_hash(
            {
                "dataset_id": bundle.audit.dataset_id,
                "horizon": config.horizon_bars,
                "execution_lag": config.execution_lag_bars,
                "clusters": model.n_clusters,
                "cluster": cluster,
                "random_state": config.random_state,
                "feature_names": tuple(bundle.features.columns),
                "centroid": tuple(float(value) for value in model.cluster_centers_[cluster]),
                "engine": PATTERN_ENGINE_VERSION,
            }
        )[:16].upper()
        if cluster == current_cluster:
            reference = train_distances[train_labels == cluster]
            scale = float(np.quantile(reference, 0.95)) if len(reference) else 0.0
            distance = float(current_distances[cluster])
            match_score = max(0.0, min(1.0, 1.0 - distance / max(scale * 1.5, 1e-12)))
        else:
            match_score = None
        provisional.append(
            {
                "pattern_id": pattern_id,
                "cluster_id": cluster,
                "signature": _signature(bundle.features.columns, model.cluster_centers_[cluster]),
                "direction": direction,
                "train_occurrences": int(train_selected.sum()),
                "oos_occurrences": int(holdout_selected.sum()),
                "oos_nonoverlap_occurrences": len(nonoverlap_positions),
                "train_mean_forward_return": train_mean,
                "oos_mean_forward_return": oos_mean,
                "oos_after_cost_mean": net_mean,
                "oos_rest_after_cost_mean": rest_mean,
                "conditional_uplift": conditional_uplift,
                "oos_hit_rate": hit_rate,
                "oos_strategy_sharpe": strategy_sharpe,
                "oos_strategy_sharpe_lower_95": strategy_sharpe_lower,
                "deflated_sharpe_probability": dsr,
                "raw_p_value": p_value,
                "stability": stability,
                "current_match_score": match_score,
            }
        )
    q_values = _benjamini_yekutieli(p_values)
    candidates: list[PatternCandidate] = []
    for values, q_value in zip(provisional, q_values):
        values["fdr_q_value"] = q_value
        values["state"] = _candidate_state(
            oos_occurrences=values["oos_occurrences"],
            after_cost_mean=values["oos_after_cost_mean"],
            conditional_uplift=values["conditional_uplift"],
            q_value=q_value,
            stability=values["stability"],
            dsr=values["deflated_sharpe_probability"],
            sharpe_lower=values["oos_strategy_sharpe_lower_95"],
            config=config,
        )
        candidates.append(PatternCandidate(**values))
    return tuple(sorted(candidates, key=lambda item: item.cluster_id))


def _train_feature_manifest(features: pd.DataFrame, train_rows: int) -> tuple[str, ...]:
    """Select the immutable feature manifest using the selection segment only."""

    train = features.iloc[:train_rows]
    selected = tuple(
        str(column)
        for column in features.columns
        if float(train[column].notna().mean()) >= 0.70
        and int(train[column].nunique(dropna=True)) > 1
    )
    return selected


def _supervised_validation(
    bundle: PatternFeatureBundle,
    config: PatternDiscoveryConfig,
) -> tuple[str | None, str | None, str, tuple[ModelValidationScore, ...], float | None]:
    drift = feature_drift_report(bundle.features)
    max_psi = _safe_float(drift.get("max_psi"))
    validation_config = ModelValidationConfig(
        horizon=config.horizon_bars,
        n_splits=3,
        min_train_rows=max(60, min(config.min_train_rows, 100)),
        min_test_rows=20,
        transaction_cost_bps=config.transaction_cost_bps,
        selected_models=config.selected_models,
        random_state=config.random_state,
    )
    result = run_ml_champion_challenger(
        bundle.labels,
        bundle.features,
        validation_config,
        max_feature_psi=max_psi if max_psi is not None else float("inf"),
    )
    if not result.get("ok"):
        return None, None, "BLOCKED", (), max_psi
    scores: list[ModelValidationScore] = []
    leaderboard = result.get("leaderboard")
    if isinstance(leaderboard, pd.DataFrame):
        for _, row in leaderboard.iterrows():
            scores.append(
                ModelValidationScore(
                    model=str(row["Model"]),
                    oos_rows=int(row["OOS rows"]),
                    balanced_accuracy=_safe_float(row["Balanced accuracy"]),
                    roc_auc=_safe_float(row["ROC AUC"]),
                    brier=_safe_float(row["Brier"]),
                    expected_calibration_error=_safe_float(row["ECE"]),
                )
            )
    return (
        str(result.get("engine_version") or "UNKNOWN"),
        str(result.get("champion") or "UNKNOWN"),
        # The legacy ML Lab's economic screen uses a synthetic class proxy.
        # Its calibrated OOS classification diagnostics are useful here, but
        # they cannot promote a market pattern or claim economic eligibility.
        "CLASSIFICATION_DIAGNOSTIC_ONLY",
        tuple(scores),
        max_psi,
    )


def discover_market_patterns(
    price_data: Any,
    symbol: str,
    config: PatternDiscoveryConfig | None = None,
    *,
    evaluation_clock: datetime | None = None,
) -> PatternDiscoveryReport:
    """Fit a real research engine, failing closed before any unsupported claim."""

    cfg = config or PatternDiscoveryConfig()
    bundle = build_pattern_feature_bundle(price_data, symbol, cfg)
    wall_clock = datetime.now(timezone.utc)
    future_tolerance = timedelta(minutes=5)
    future_clocks: list[str] = []
    if (
        evaluation_clock is not None
        and _as_utc(evaluation_clock) > wall_clock + future_tolerance
    ):
        future_clocks.append("evaluation_clock")
    for name, clock in (
        ("data_cutoff", bundle.audit.data_cutoff),
        ("source_known_at", bundle.audit.source_known_at),
        ("latest_row_known_at", bundle.audit.latest_row_known_at),
    ):
        if clock is not None and _as_utc(clock) > wall_clock + future_tolerance:
            future_clocks.append(name)
    if future_clocks:
        return _waiting_report(
            bundle,
            cfg,
            state=PatternRunState.BLOCKED_DATA_QUALITY,
            reason=(
                "Future-dated availability clock(s) are inadmissible: "
                + ", ".join(future_clocks)
                + "."
            ),
            evaluation_clock=evaluation_clock,
            evaluated_at_override=wall_clock,
        )
    if bundle.audit.blocking_reasons:
        return _waiting_report(
            bundle,
            cfg,
            state=PatternRunState.BLOCKED_DATA_QUALITY,
            reason="; ".join(bundle.audit.blocking_reasons),
            evaluation_clock=evaluation_clock,
        )
    if len(bundle.features) < cfg.min_rows:
        return _waiting_report(
            bundle,
            cfg,
            state=PatternRunState.WAITING_DATA,
            reason=(
                f"{len(bundle.features)} usable causal rows are available; at least {cfg.min_rows} are required "
                "for selection, purge and run-locked terminal OOS."
            ),
            evaluation_clock=evaluation_clock,
        )
    if bundle.features.empty:
        return _waiting_report(
            bundle,
            cfg,
            state=PatternRunState.BLOCKED_DATA_QUALITY,
            reason="No eligible causal feature rows survived the core-history controls.",
            evaluation_clock=evaluation_clock,
        )

    usable_rows = len(bundle.features)
    holdout_rows = max(cfg.min_holdout_rows, int(math.ceil(usable_rows * cfg.holdout_fraction)))
    purge_rows = max(1, cfg.execution_lag_bars + cfg.horizon_bars - 1)
    train_rows = usable_rows - purge_rows - holdout_rows
    if train_rows < cfg.min_train_rows:
        return _waiting_report(
            bundle,
            cfg,
            state=PatternRunState.WAITING_DATA,
            reason=(
                f"Only {train_rows} training rows remain after a {purge_rows}-bar purge and "
                f"{holdout_rows}-row holdout; {cfg.min_train_rows} are required."
            ),
            evaluation_clock=evaluation_clock,
        )

    feature_manifest = _train_feature_manifest(bundle.features, train_rows)
    bundle = replace(
        bundle,
        features=bundle.features.loc[:, feature_manifest].copy(),
        current_features=bundle.current_features.reindex(columns=feature_manifest).copy(),
    )
    if len(feature_manifest) < 4:
        return _waiting_report(
            bundle,
            cfg,
            state=PatternRunState.BLOCKED_DATA_QUALITY,
            reason=(
                "Fewer than four causal features passed selection-segment-only "
                "coverage and variance controls."
            ),
            evaluation_clock=evaluation_clock,
        )

    try:
        train_features = bundle.features.iloc[:train_rows]
        holdout_features = bundle.features.iloc[-holdout_rows:]
        imputer = SimpleImputer(strategy="median", add_indicator=False)
        scaler = RobustScaler(quantile_range=(10.0, 90.0))
        train_scaled = scaler.fit_transform(imputer.fit_transform(train_features))
        holdout_scaled = scaler.transform(imputer.transform(holdout_features))
        model, clusters, silhouette, search = _select_cluster_model(train_scaled, cfg)
        train_labels = model.labels_.astype(int)
        holdout_labels = model.predict(holdout_scaled).astype(int)
        train_distances = np.min(model.transform(train_scaled), axis=1)
        current_frame = bundle.current_features.reindex(columns=bundle.features.columns)
        current_scaled = scaler.transform(imputer.transform(current_frame))
        current_distances = model.transform(current_scaled)[0]
        current_cluster = int(np.argmin(current_distances))
        current_distance = float(current_distances[current_cluster])
        cluster_ood_thresholds = tuple(
            float(np.quantile(train_distances[train_labels == cluster], 0.99))
            if int(np.sum(train_labels == cluster))
            else 0.0
            for cluster in range(clusters)
        )
        ood_threshold = cluster_ood_thresholds[current_cluster]
        current_in_distribution = bool(
            math.isfinite(current_distance)
            and math.isfinite(ood_threshold)
            and current_distance <= max(ood_threshold, 1e-12)
        )
        candidates = _build_candidates(
            bundle=bundle,
            train_labels=train_labels,
            holdout_labels=holdout_labels,
            current_cluster=current_cluster,
            current_distances=current_distances,
            train_distances=train_distances,
            model=model,
            config=cfg,
            cluster_trials=len(search),
        )
        fit_artifact = PatternFitArtifact(
            feature_names=tuple(bundle.features.columns),
            imputer_statistics=tuple(float(value) for value in imputer.statistics_),
            scaler_center=tuple(float(value) for value in scaler.center_),
            scaler_scale=tuple(float(value) for value in scaler.scale_),
            cluster_centers=tuple(
                tuple(float(value) for value in center) for center in model.cluster_centers_
            ),
            cluster_search=tuple((int(k), float(score)) for k, score in search),
            ood_quantile=0.99,
            cluster_ood_thresholds=cluster_ood_thresholds,
            current_scaled_features=tuple(float(value) for value in current_scaled[0]),
            current_distances=tuple(float(value) for value in current_distances),
            current_nearest_distance=current_distance,
        )
        try:
            supervised_version, champion, promotion, model_scores, max_psi = _supervised_validation(bundle, cfg)
        except Exception:
            # Discovery and supervised challenge are independent control planes.
            # A backend-specific challenger incident must not erase a valid,
            # already run-locked unsupervised/OOS report.
            supervised_version, champion, promotion, model_scores, max_psi = (
                None,
                None,
                "ENGINE_UNAVAILABLE",
                (),
                None,
            )
    except Exception as exc:
        return _waiting_report(
            bundle,
            cfg,
            state=PatternRunState.ENGINE_ERROR,
            reason=f"Pattern engine stopped safely ({type(exc).__name__}).",
            evaluation_clock=evaluation_clock,
        )

    nearest_pattern_id = next(
        candidate.pattern_id for candidate in candidates if candidate.cluster_id == current_cluster
    )
    current_pattern_id = nearest_pattern_id if current_in_distribution else None
    current_assignment_status = (
        "ASSIGNED_IN_DISTRIBUTION" if current_in_distribution else "UNASSIGNED_OOD"
    )
    screened = tuple(
        candidate
        for candidate in candidates
        if candidate.state == PatternCandidateState.RUN_LOCAL_SCREENED_HYPOTHESIS
    )
    after_cost_count = sum(candidate.oos_after_cost_mean is not None for candidate in candidates)
    fdr_count = sum(candidate.fdr_q_value is not None for candidate in candidates)
    gates = (
        PatternGate(
            "INPUT_CONTRACT",
            GateState.PASS,
            "Chronological price history has observed next-open pricing, admissible adjustment provenance and deterministic identity.",
            (
                f"Dataset {bundle.audit.dataset_id[:16]}… · {bundle.audit.normalized_rows} rows · "
                f"adjustment {bundle.audit.price_adjustment_policy}."
            ),
        ),
        PatternGate(
            "CAUSAL_FEATURES",
            GateState.PASS,
            "Every discovery feature is contemporaneous or backward-looking and its manifest was frozen on selection data only.",
            (
                f"{len(bundle.features.columns)} train-selected features; next-bar open entry lag "
                f"{cfg.execution_lag_bars}; forward returns remain labels only."
            ),
        ),
        PatternGate(
            "PURGED_LOCKED_HOLDOUT",
            GateState.PASS,
            "Selection and terminal evaluation are separated by the complete entry-to-exit label span.",
            f"Train {train_rows} · purge {purge_rows} · run-locked terminal OOS {holdout_rows}.",
        ),
        PatternGate(
            "UNSUPERVISED_DISCOVERY",
            GateState.PASS,
            "K-means was fitted only on the selection segment; cluster count used return-blind silhouette selection.",
            f"Selected k={clusters} from {len(search)} admissible partition(s); silhouette {silhouette:.3f}.",
        ),
        PatternGate(
            "AFTER_COST_OOS",
            (
                GateState.PASS
                if after_cost_count == len(candidates)
                else GateState.WAITING_EVIDENCE
            ),
            (
                "Every discovered state was observed and evaluated on terminal OOS returns after cost against its matched-rest baseline."
                if after_cost_count == len(candidates)
                else "At least one train-discovered state did not recur in terminal OOS, so its economic evaluation remains unavailable."
            ),
            (
                f"{after_cost_count}/{len(candidates)} candidates evaluated at "
                f"{cfg.transaction_cost_bps:.1f} bps with conditional uplift."
            ),
        ),
        PatternGate(
            "FDR_CORRECTION",
            GateState.WAITING_EVIDENCE,
            "Circular-shift diagnostics with Benjamini-Yekutieli adjustment remain run-local and do not establish validated FDR control under non-stationarity.",
            (
                f"{fdr_count}/{len(candidates)} run-local diagnostics adjusted across the disclosed "
                f"cluster family at q={cfg.fdr_alpha:.0%}; independent inferential validation is open."
            ),
        ),
        PatternGate(
            "FULL_EXPERIMENT_CORRECTION",
            GateState.WAITING_EVIDENCE,
            "White Reality Check / Hansen SPA requires the complete experiment family and history.",
            "Current FDR scope does not correct prior research attempts or undisclosed specification searches.",
        ),
        PatternGate(
            "SUPERVISED_CHALLENGER",
            GateState.WAITING_EVIDENCE,
            "The existing ML Lab contributes purged expanding-OOS classification diagnostics only; it cannot economically promote this pattern report.",
            (
                f"Selected classification challenger {champion or 'unavailable'} · status {promotion} · "
                f"max PSI {max_psi if max_psi is not None else 'N/A'}; real aligned returns required."
            ),
        ),
        PatternGate(
            "PIT_PROVIDER_LINEAGE",
            GateState.PASS if bundle.audit.pit_lineage_complete else GateState.WAITING_EVIDENCE,
            (
                "Provider and row lineage satisfies the declared PIT contract; external verification remains outstanding."
                if bundle.audit.pit_lineage_complete
                else "The inherited provider frame lacks complete known-at and revision lineage."
            ),
            (
                f"Source {bundle.audit.source} · status {bundle.audit.source_status} · recency "
                f"{bundle.audit.recency} · known-at "
                f"{bundle.audit.source_known_at.isoformat() if bundle.audit.source_known_at else 'UNDECLARED'} · "
                f"revisions {bundle.audit.revision_policy}."
            ),
        ),
        PatternGate(
            "CURRENT_STATE_OOD",
            GateState.WAITING_EVIDENCE,
            (
                "The current observation lies within the train-fit novelty heuristic, which is not a calibrated acceptance region."
                if current_in_distribution
                else "The current observation is outside the train-fit novelty heuristic and remains unassigned."
            ),
            (
                f"Nearest state {nearest_pattern_id} · distance {current_distance:.4f} · "
                f"cluster q99 threshold {ood_threshold:.4f} · proximity is heuristic, not probability."
            ),
        ),
        PatternGate(
            "SHADOW_HISTORY",
            GateState.WAITING_EVIDENCE,
            "A fresh discovery run is not a live shadow record.",
            "No append-only forward decision/outcome history is attached to this report.",
        ),
        PatternGate(
            "INDEPENDENT_REVIEW",
            GateState.WAITING_EVIDENCE,
            "Independent model-risk review has not been recorded.",
            "Human review remains mandatory before any governed rebuild.",
        ),
        PatternGate(
            "AUTONOMOUS_EXECUTION",
            GateState.PASS,
            "Execution is prohibited by contract.",
            "autonomous_trading=false; execution_allowed=false; order_payload=null",
            blocks_strategic_admission=False,
        ),
    )
    reason = (
        f"{len(screened)} run-locked terminal-OOS pattern(s) satisfy the conservative run-local diagnostic screen; none is statistically validated or executable."
        if screened
        else "Discovery completed, but no pattern satisfies the conservative run-local terminal-OOS diagnostic screen."
    )
    evaluated_at = _evaluation_time(bundle, evaluation_clock)
    return _finalize_report(
        {
            "schema_version": PATTERN_SCHEMA_VERSION,
            "engine_version": PATTERN_ENGINE_VERSION,
            "policy_version": PATTERN_POLICY_VERSION,
            "state": PatternRunState.COMPLETED_RESEARCH_ONLY,
            "reason": reason,
            "symbol": bundle.audit.symbol,
            "evaluated_at": evaluated_at,
            "input_audit": bundle.audit,
            "config": cfg,
            "feature_names": tuple(bundle.features.columns),
            "usable_rows": usable_rows,
            "train_rows": train_rows,
            "purge_rows": purge_rows,
            "holdout_rows": holdout_rows,
            "selected_clusters": clusters,
            "silhouette_score": _safe_float(silhouette),
            "current_pattern_id": current_pattern_id,
            "nearest_pattern_id": nearest_pattern_id,
            "current_assignment_status": current_assignment_status,
            "candidates": candidates,
            "gates": gates,
            "supervised_engine_version": supervised_version,
            "supervised_champion": champion,
            "supervised_promotion_status": promotion,
            "model_scores": model_scores,
            "runtime_versions": _runtime_versions(),
            "fit_artifact": fit_artifact,
            "autonomous_trading": False,
            "human_review_required": True,
            "execution_allowed": False,
            "order_payload": None,
        }
    )


def pattern_report_json(report: PatternDiscoveryReport) -> str:
    """Export a canonical, self-verifying research artifact."""

    return canonical_json(
        {
            "report": report,
            "verification": {
                "content_hash_valid": report.verify_hash(),
                "scope": "RESEARCH_ONLY",
                "autonomous_trading": False,
                "capital_authority": False,
                "execution_allowed": False,
            },
        }
    )
