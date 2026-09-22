from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from math import comb, erf, exp, log, pi, sqrt
from time import perf_counter
from typing import Any, Iterable

import numpy as np
import pandas as pd


REGIME_LABELS = ("RISK-ON", "RISK-OFF", "INFLATION", "DEFLATION")
_EPS = 1e-12


@dataclass(frozen=True)
class QuantumRuntimeStatus:
    qiskit_available: bool
    execution_mode: str
    note: str


def runtime_status() -> QuantumRuntimeStatus:
    try:
        import importlib.util

        available = importlib.util.find_spec("qiskit") is not None
    except Exception:
        available = False

    if available:
        return QuantumRuntimeStatus(
            qiskit_available=True,
            execution_mode="SIMULATOR READY",
            note="Qiskit detected. Hardware execution remains opt-in and is not assumed.",
        )
    return QuantumRuntimeStatus(
        qiskit_available=False,
        execution_mode="CLASSICAL QUANTUM-INSPIRED",
        note="No Qiskit runtime detected. All research views remain reproducible on NumPy/Pandas.",
    )


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        out = float(value)
        if not np.isfinite(out):
            return default
        return out
    except Exception:
        return default


def ensure_price_frame(price_data: pd.DataFrame | None) -> pd.DataFrame:
    if not isinstance(price_data, pd.DataFrame) or price_data.empty:
        return pd.DataFrame(columns=["date", "close"])

    df = price_data.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]

    if "date" not in df.columns:
        df = df.reset_index()
        first = str(df.columns[0])
        df = df.rename(columns={first: "date"})

    if "close" not in df.columns:
        close_like = [c for c in df.columns if "close" in str(c).lower()]
        if not close_like:
            return pd.DataFrame(columns=["date", "close"])
        df = df.rename(columns={close_like[0]: "close"})

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["date", "close"]).sort_values("date")
    return df.reset_index(drop=True)


def market_features(price_data: pd.DataFrame | None) -> dict[str, float]:
    df = ensure_price_frame(price_data)
    if len(df) < 25:
        return {
            "ann_return": 0.0,
            "ann_vol": 0.20,
            "drawdown": -0.05,
            "momentum_20": 0.0,
            "momentum_60": 0.0,
            "last": 100.0,
            "observations": float(len(df)),
        }

    close = df["close"].astype(float)
    ret = close.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    ann_return = float(ret.mean() * 252.0) if not ret.empty else 0.0
    ann_vol = float(ret.std(ddof=1) * sqrt(252.0)) if len(ret) >= 2 else 0.20
    running_max = close.cummax().replace(0, np.nan)
    drawdown = float((close / running_max - 1.0).iloc[-1])
    momentum_20 = float(close.iloc[-1] / close.iloc[-21] - 1.0) if len(close) >= 21 else 0.0
    momentum_60 = float(close.iloc[-1] / close.iloc[-61] - 1.0) if len(close) >= 61 else momentum_20

    return {
        "ann_return": ann_return,
        "ann_vol": max(ann_vol, 0.001),
        "drawdown": drawdown,
        "momentum_20": momentum_20,
        "momentum_60": momentum_60,
        "last": float(close.iloc[-1]),
        "observations": float(len(df)),
    }


def _softmax(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    x = x - np.nanmax(x)
    e = np.exp(np.clip(x, -50, 50))
    total = float(e.sum())
    if total <= 0 or not np.isfinite(total):
        return np.full(len(x), 1.0 / len(x))
    return e / total


def encode_regime_state(features: dict[str, float]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Experimental state encoding. It is a testable representation, not a claim that markets are physical qubits."""
    ar = float(features.get("ann_return", 0.0))
    vol = float(features.get("ann_vol", 0.20))
    dd = float(features.get("drawdown", -0.05))
    m20 = float(features.get("momentum_20", 0.0))
    m60 = float(features.get("momentum_60", 0.0))

    logits = np.array(
        [
            1.35 * ar + 2.10 * m20 + 1.20 * m60 - 0.90 * vol + 0.40 * dd,
            -1.00 * ar - 1.45 * m20 - 0.75 * m60 + 1.55 * vol - 2.10 * dd,
            0.45 * ar + 0.55 * max(m20, 0.0) + 1.00 * vol + 0.25 * abs(dd),
            -0.85 * ar - 0.70 * m20 - 0.45 * m60 - 0.45 * vol + 0.55 * abs(min(dd, 0.0)),
        ],
        dtype=float,
    )
    probs = _softmax(logits)

    phase_raw = np.array(
        [m20 * 5.0, -dd * 4.0, (vol - 0.20) * 3.0, -m60 * 4.0], dtype=float
    )
    phases = np.pi * np.tanh(phase_raw)
    amplitudes = np.sqrt(probs) * np.exp(1j * phases)
    amplitudes = amplitudes / max(np.linalg.norm(amplitudes), _EPS)
    return amplitudes, probs, phases


def density_matrix_from_state(amplitudes: np.ndarray, decoherence: float = 0.10) -> np.ndarray:
    psi = np.asarray(amplitudes, dtype=complex).reshape(-1)
    psi = psi / max(np.linalg.norm(psi), _EPS)
    rho_pure = np.outer(psi, np.conjugate(psi))
    d = len(psi)
    decoherence = float(np.clip(decoherence, 0.0, 1.0))
    rho = (1.0 - decoherence) * rho_pure + decoherence * np.eye(d, dtype=complex) / d
    rho = (rho + rho.conj().T) / 2.0
    rho = rho / max(float(np.trace(rho).real), _EPS)
    return rho


def evolve_density_matrix(
    rho: np.ndarray,
    features: dict[str, float],
    dt: float = 0.25,
    coupling: float = 0.35,
    decoherence_rate: float = 0.08,
) -> np.ndarray:
    """Unitary evolution plus depolarizing open-system term; intentionally compact and reproducible."""
    rho = np.asarray(rho, dtype=complex)
    d = rho.shape[0]
    ar = float(features.get("ann_return", 0.0))
    vol = float(features.get("ann_vol", 0.20))
    dd = abs(float(features.get("drawdown", -0.05)))
    m20 = float(features.get("momentum_20", 0.0))

    diag = np.array([ar + m20, vol + dd, vol + max(ar, 0.0), -ar + dd], dtype=float)
    diag = diag[:d]
    H = np.diag(diag)
    for i in range(d):
        for j in range(i + 1, d):
            distance = 1.0 + abs(i - j)
            c = float(coupling) * (0.15 + vol + abs(m20)) / distance
            H[i, j] = c
            H[j, i] = c

    eigvals, eigvecs = np.linalg.eigh(H)
    U = eigvecs @ np.diag(np.exp(-1j * eigvals * float(dt))) @ eigvecs.conj().T
    evolved = U @ rho @ U.conj().T

    gamma = float(np.clip(decoherence_rate * max(dt, 0.0), 0.0, 1.0))
    evolved = (1.0 - gamma) * evolved + gamma * np.eye(d, dtype=complex) / d
    evolved = (evolved + evolved.conj().T) / 2.0
    return evolved / max(float(np.trace(evolved).real), _EPS)


def von_neumann_entropy(rho: np.ndarray, normalized: bool = True) -> float:
    vals = np.linalg.eigvalsh((rho + rho.conj().T) / 2.0).real
    vals = np.clip(vals, 0.0, 1.0)
    vals = vals[vals > _EPS]
    entropy = float(-np.sum(vals * np.log(vals))) if len(vals) else 0.0
    if normalized and rho.shape[0] > 1:
        entropy /= log(rho.shape[0])
    return float(np.clip(entropy, 0.0, 1.0 if normalized else np.inf))


def purity(rho: np.ndarray) -> float:
    return float(np.real(np.trace(rho @ rho)))


def l1_coherence(rho: np.ndarray) -> float:
    matrix = np.asarray(rho, dtype=complex)
    off = matrix.copy()
    np.fill_diagonal(off, 0.0)
    return float(np.abs(off).sum())


def effective_dimension(rho: np.ndarray) -> float:
    p = purity(rho)
    return float(1.0 / max(p, _EPS))


def quantum_regime_snapshot(
    price_data: pd.DataFrame | None,
    decoherence: float = 0.12,
    evolve: bool = True,
    evolution_dt: float = 0.25,
) -> dict[str, Any]:
    features = market_features(price_data)
    amplitudes, initial_probs, phases = encode_regime_state(features)
    rho = density_matrix_from_state(amplitudes, decoherence=decoherence)
    if evolve:
        rho = evolve_density_matrix(
            rho,
            features,
            dt=evolution_dt,
            coupling=0.30,
            decoherence_rate=max(0.02, decoherence * 0.65),
        )

    probs = np.clip(np.real(np.diag(rho)), 0.0, 1.0)
    probs = probs / max(float(probs.sum()), _EPS)
    idx = int(np.argmax(probs))

    return {
        "features": features,
        "labels": list(REGIME_LABELS),
        "amplitudes": amplitudes,
        "phases": phases,
        "initial_probabilities": initial_probs,
        "probabilities": probs,
        "rho": rho,
        "dominant_regime": REGIME_LABELS[idx],
        "dominant_probability": float(probs[idx]),
        "entropy": von_neumann_entropy(rho, normalized=True),
        "purity": purity(rho),
        "coherence": l1_coherence(rho),
        "effective_dimension": effective_dimension(rho),
    }


def regime_timeline(
    price_data: pd.DataFrame | None,
    window: int = 60,
    max_points: int = 140,
    decoherence: float = 0.12,
) -> pd.DataFrame:
    df = ensure_price_frame(price_data)
    if len(df) < max(window + 5, 30):
        return pd.DataFrame()

    start = max(window, len(df) - max_points)
    rows: list[dict[str, Any]] = []
    for end in range(start, len(df) + 1):
        sub = df.iloc[max(0, end - window):end]
        snap = quantum_regime_snapshot(sub, decoherence=decoherence, evolve=False)
        row = {"date": sub["date"].iloc[-1], "dominant": snap["dominant_regime"]}
        for label, p in zip(REGIME_LABELS, snap["probabilities"]):
            row[label] = float(p)
        rows.append(row)
    return pd.DataFrame(rows)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def black_scholes_call(s0: float, strike: float, maturity: float, rate: float, vol: float) -> float:
    s0 = max(float(s0), _EPS)
    strike = max(float(strike), _EPS)
    maturity = max(float(maturity), _EPS)
    vol = max(float(vol), _EPS)
    d1 = (log(s0 / strike) + (rate + 0.5 * vol * vol) * maturity) / (vol * sqrt(maturity))
    d2 = d1 - vol * sqrt(maturity)
    return float(s0 * _norm_cdf(d1) - strike * exp(-rate * maturity) * _norm_cdf(d2))


def monte_carlo_call_price(
    s0: float,
    strike: float,
    maturity: float,
    rate: float,
    vol: float,
    paths: int = 20_000,
    seed: int = 17,
) -> dict[str, float]:
    paths = int(max(100, min(paths, 2_000_000)))
    rng = np.random.default_rng(seed)
    half = max(paths // 2, 1)
    z = rng.standard_normal(half)
    z = np.concatenate([z, -z])[:paths]
    drift = (rate - 0.5 * vol * vol) * maturity
    diffusion = vol * sqrt(max(maturity, _EPS)) * z
    st = s0 * np.exp(drift + diffusion)
    payoff = np.maximum(st - strike, 0.0)
    discounted = exp(-rate * maturity) * payoff
    price = float(discounted.mean())
    stderr = float(discounted.std(ddof=1) / sqrt(len(discounted))) if len(discounted) > 1 else 0.0
    return {
        "price": price,
        "stderr": stderr,
        "ci_low": price - 1.96 * stderr,
        "ci_high": price + 1.96 * stderr,
        "paths": float(len(discounted)),
    }


def qae_resource_projection(
    target_error_fraction: float,
    confidence: float = 0.95,
) -> dict[str, float]:
    """Illustrative query-complexity envelope. This is not a hardware runtime estimate."""
    eps = float(np.clip(target_error_fraction, 1e-4, 0.25))
    confidence = float(np.clip(confidence, 0.50, 0.9999))
    delta = 1.0 - confidence

    classical_calls = int(np.ceil(np.log(2.0 / max(delta, 1e-9)) / (2.0 * eps * eps)))
    qae_calls = int(np.ceil(pi / eps))
    speedup_ratio = classical_calls / max(qae_calls, 1)
    return {
        "epsilon": eps,
        "confidence": confidence,
        "classical_calls": float(classical_calls),
        "qae_calls": float(qae_calls),
        "query_ratio": float(speedup_ratio),
    }


def qae_scaling_curve(errors: Iterable[float], confidence: float = 0.95) -> pd.DataFrame:
    rows = []
    for eps in errors:
        proj = qae_resource_projection(float(eps), confidence=confidence)
        rows.append(
            {
                "target_error": proj["epsilon"],
                "Classical MC": proj["classical_calls"],
                "QAE asymptotic": proj["qae_calls"],
            }
        )
    return pd.DataFrame(rows)



# ---------------------------------------------------------------------------
# Quantum Monte Carlo / Risk V2
# ---------------------------------------------------------------------------

QMC_METHODS = ("Pseudo-random", "Antithetic", "Control variate", "Sobol QMC")
QAE_ALGORITHMS = ("Canonical QAE", "Iterative QAE", "Maximum-Likelihood QAE")


def black_scholes_price(
    s0: float,
    strike: float,
    maturity: float,
    rate: float,
    vol: float,
    option_type: str = "Call",
) -> float:
    """Black-Scholes European option control used only when its assumptions apply."""
    s0 = max(float(s0), _EPS)
    strike = max(float(strike), _EPS)
    maturity = max(float(maturity), _EPS)
    vol = max(float(vol), _EPS)
    d1 = (log(s0 / strike) + (rate + 0.5 * vol * vol) * maturity) / (vol * sqrt(maturity))
    d2 = d1 - vol * sqrt(maturity)
    if str(option_type).strip().lower().startswith("p"):
        return float(strike * exp(-rate * maturity) * _norm_cdf(-d2) - s0 * _norm_cdf(-d1))
    return float(s0 * _norm_cdf(d1) - strike * exp(-rate * maturity) * _norm_cdf(d2))


def black_scholes_greeks(
    s0: float,
    strike: float,
    maturity: float,
    rate: float,
    vol: float,
    option_type: str = "Call",
) -> dict[str, float]:
    s0 = max(float(s0), _EPS)
    strike = max(float(strike), _EPS)
    maturity = max(float(maturity), _EPS)
    vol = max(float(vol), _EPS)
    root_t = sqrt(maturity)
    d1 = (log(s0 / strike) + (rate + 0.5 * vol * vol) * maturity) / (vol * root_t)
    d2 = d1 - vol * root_t
    pdf = exp(-0.5 * d1 * d1) / sqrt(2.0 * pi)
    is_put = str(option_type).strip().lower().startswith("p")
    delta = _norm_cdf(d1) - 1.0 if is_put else _norm_cdf(d1)
    gamma = pdf / (s0 * vol * root_t)
    vega = s0 * pdf * root_t  # per 1.00 vol point
    if is_put:
        theta = -(s0 * pdf * vol) / (2.0 * root_t) + rate * strike * exp(-rate * maturity) * _norm_cdf(-d2)
        rho = -strike * maturity * exp(-rate * maturity) * _norm_cdf(-d2)
    else:
        theta = -(s0 * pdf * vol) / (2.0 * root_t) - rate * strike * exp(-rate * maturity) * _norm_cdf(d2)
        rho = strike * maturity * exp(-rate * maturity) * _norm_cdf(d2)
    return {"delta": float(delta), "gamma": float(gamma), "vega": float(vega), "theta": float(theta), "rho": float(rho)}


def _normal_draws(paths: int, dimensions: int, method: str, seed: int) -> tuple[np.ndarray, str]:
    """Generate standard normals. Sobol is classical quasi-Monte Carlo, not quantum execution."""
    paths = int(max(16, paths)); dimensions = int(max(1, dimensions)); method = str(method)
    if method == "Sobol QMC":
        try:
            from scipy.stats import qmc
            from scipy.special import ndtri
            m = int(np.ceil(np.log2(paths)))
            sampler = qmc.Sobol(d=dimensions, scramble=True, seed=int(seed))
            u = sampler.random_base2(m=m)[:paths]
            u = np.clip(u, 1e-12, 1.0 - 1e-12)
            return ndtri(u), "Sobol QMC"
        except Exception:
            # Reproducible fallback: never pretend Sobol was executed.
            rng = np.random.default_rng(seed)
            return rng.standard_normal((paths, dimensions)), "Pseudo-random fallback"
    rng = np.random.default_rng(seed)
    if method in {"Antithetic", "Control variate"}:
        half = int(np.ceil(paths / 2))
        z = rng.standard_normal((half, dimensions))
        z = np.vstack([z, -z])[:paths]
        return z, method
    return rng.standard_normal((paths, dimensions)), "Pseudo-random"


def _gbm_paths_from_normals(
    s0: float, maturity: float, rate: float, vol: float, z: np.ndarray
) -> np.ndarray:
    paths, steps = z.shape
    dt = float(maturity) / float(steps)
    increments = (float(rate) - 0.5 * float(vol) ** 2) * dt + float(vol) * sqrt(max(dt, _EPS)) * z
    log_path = np.cumsum(increments, axis=1)
    return float(s0) * np.exp(log_path)


def _heston_paths_from_normals(
    s0: float,
    maturity: float,
    rate: float,
    z_price: np.ndarray,
    z_var_independent: np.ndarray,
    kappa: float,
    theta: float,
    xi: float,
    rho: float,
    v0: float,
) -> np.ndarray:
    """Full-truncation Euler Heston path simulation for research benchmarking."""
    paths, steps = z_price.shape
    dt = float(maturity) / float(steps)
    sqrt_dt = sqrt(max(dt, _EPS))
    rho = float(np.clip(rho, -0.999, 0.999))
    z_var = rho * z_price + sqrt(max(1.0 - rho * rho, _EPS)) * z_var_independent
    s = np.full(paths, float(s0), dtype=float)
    v = np.full(paths, max(float(v0), 1e-8), dtype=float)
    out = np.empty((paths, steps), dtype=float)
    for j in range(steps):
        v_pos = np.maximum(v, 0.0)
        s *= np.exp((float(rate) - 0.5 * v_pos) * dt + np.sqrt(v_pos) * sqrt_dt * z_price[:, j])
        v = v + float(kappa) * (float(theta) - v_pos) * dt + float(xi) * np.sqrt(v_pos) * sqrt_dt * z_var[:, j]
        v = np.maximum(v, 0.0)
        out[:, j] = s
    return out


def _payoff_from_paths(
    paths_array: np.ndarray,
    strike: float,
    option_type: str,
    product: str,
    barrier_level: float | None = None,
    barrier_direction: str = "Down-and-Out",
) -> np.ndarray:
    sign = -1.0 if str(option_type).strip().lower().startswith("p") else 1.0
    product = str(product)
    terminal = paths_array[:, -1]
    if product == "Asian Arithmetic":
        underlying = paths_array.mean(axis=1)
        return np.maximum(sign * (underlying - float(strike)), 0.0)
    base = np.maximum(sign * (terminal - float(strike)), 0.0)
    if product == "Barrier":
        b = float(barrier_level if barrier_level is not None else 0.80 * float(np.nanmedian(paths_array[:, 0])))
        if str(barrier_direction).startswith("Up"):
            alive = paths_array.max(axis=1) < b
        else:
            alive = paths_array.min(axis=1) > b
        return base * alive.astype(float)
    return base


def monte_carlo_option_price(
    s0: float,
    strike: float,
    maturity: float,
    rate: float,
    vol: float,
    product: str = "European",
    option_type: str = "Call",
    model: str = "GBM / Black-Scholes",
    paths: int = 25_000,
    steps: int = 64,
    method: str = "Antithetic",
    seed: int = 17,
    barrier_level: float | None = None,
    barrier_direction: str = "Down-and-Out",
    basket_assets: int = 4,
    basket_corr: float = 0.35,
    heston_kappa: float = 1.8,
    heston_theta: float | None = None,
    heston_xi: float = 0.45,
    heston_rho: float = -0.65,
    heston_v0: float | None = None,
    return_sample: bool = False,
) -> dict[str, Any]:
    """Executed classical pricing engine used as the control stack for QAE research.

    QAE results are never synthesized here; this function only measures classical pricing.
    """
    start = perf_counter()
    s0 = max(float(s0), _EPS); strike = max(float(strike), _EPS); maturity = max(float(maturity), 1e-5)
    vol = max(float(vol), 1e-5); paths = int(np.clip(paths, 100, 500_000)); steps = int(np.clip(steps, 1, 512))
    product = str(product); model = str(model); requested_method = str(method)

    if product == "European" and not model.startswith("Heston"):
        sim_steps = 1
    else:
        sim_steps = steps

    actual_method = requested_method
    if product == "Basket":
        n_assets = int(np.clip(basket_assets, 2, 12))
        corr = float(np.clip(basket_corr, -0.90 / max(n_assets - 1, 1), 0.95))
        # One-step basket terminal distribution; equicorrelation factorization.
        z, actual_method = _normal_draws(paths, n_assets, requested_method, seed)
        corr_m = np.full((n_assets, n_assets), corr, dtype=float); np.fill_diagonal(corr_m, 1.0)
        eigval, eigvec = np.linalg.eigh(corr_m); root = eigvec @ np.diag(np.sqrt(np.clip(eigval, 1e-10, None))) @ eigvec.T
        zc = z @ root.T
        terminal_assets = s0 * np.exp((rate - 0.5 * vol * vol) * maturity + vol * sqrt(maturity) * zc)
        basket_terminal = terminal_assets.mean(axis=1)
        sign = -1.0 if option_type.lower().startswith("p") else 1.0
        payoff = np.maximum(sign * (basket_terminal - strike), 0.0)
        control_underlying = exp(-rate * maturity) * basket_terminal
    else:
        if model.startswith("Heston"):
            # Need two normal streams; use the same generation mode for each.
            z1, actual_method = _normal_draws(paths, sim_steps, requested_method, seed)
            z2, method2 = _normal_draws(paths, sim_steps, requested_method, seed + 7919)
            if "fallback" in method2.lower(): actual_method = method2
            theta = float(heston_theta if heston_theta is not None else vol * vol)
            v0 = float(heston_v0 if heston_v0 is not None else vol * vol)
            path_array = _heston_paths_from_normals(s0, maturity, rate, z1, z2, heston_kappa, theta, heston_xi, heston_rho, v0)
        else:
            z, actual_method = _normal_draws(paths, sim_steps, requested_method, seed)
            path_array = _gbm_paths_from_normals(s0, maturity, rate, vol, z)
        payoff = _payoff_from_paths(path_array, strike, option_type, product, barrier_level, barrier_direction)
        control_underlying = exp(-rate * maturity) * path_array[:, -1]

    discounted = exp(-rate * maturity) * payoff
    raw_discounted = discounted.copy()
    beta = 0.0
    if requested_method == "Control variate" and len(discounted) > 2:
        x = np.asarray(control_underlying, dtype=float)
        vx = float(np.var(x, ddof=1))
        if vx > _EPS:
            beta = float(np.cov(discounted, x, ddof=1)[0, 1] / vx)
            # E[e^-rT S_T]=S0 under the risk-neutral model.
            discounted = discounted - beta * (x - s0)

    price = float(np.mean(discounted))
    if requested_method in {"Antithetic", "Control variate"} and len(discounted) >= 4:
        split = int(np.ceil(len(discounted) / 2.0))
        pair_n = int(len(discounted) - split)
        paired = 0.5 * (discounted[:pair_n] + discounted[split:split + pair_n])
        stderr = float(np.std(paired, ddof=1) / sqrt(len(paired))) if len(paired) > 1 else 0.0
        stderr_basis = "antithetic pair-means"
    elif requested_method == "Sobol QMC" and len(discounted) >= 64:
        # A single randomized Sobol scramble does not provide an IID standard error.
        # We expose a conservative block-dispersion diagnostic and label it as such.
        blocks = min(8, max(2, len(discounted) // 64))
        chunks = [x for x in np.array_split(discounted, blocks) if len(x)]
        means = np.array([np.mean(x) for x in chunks], dtype=float)
        stderr = float(np.std(means, ddof=1) / sqrt(len(means))) if len(means) > 1 else 0.0
        stderr_basis = "single-scramble block proxy"
    else:
        stderr = float(np.std(discounted, ddof=1) / sqrt(len(discounted))) if len(discounted) > 1 else 0.0
        stderr_basis = "IID sample SE"
    elapsed_ms = (perf_counter() - start) * 1000.0
    out: dict[str, Any] = {
        "price": price, "stderr": stderr, "ci_low": price - 1.96 * stderr, "ci_high": price + 1.96 * stderr,
        "paths": int(len(discounted)), "steps": int(sim_steps), "runtime_ms": float(elapsed_ms),
        "method_requested": requested_method, "method_executed": actual_method, "control_beta": float(beta), "stderr_basis": stderr_basis,
        "payoff_mean": float(np.mean(raw_discounted)),
        "payoff_std": float(np.std(raw_discounted, ddof=1)) if len(raw_discounted) > 1 else 0.0,
    }
    if return_sample:
        cap = min(len(discounted), 20_000)
        out["discounted_payoff_sample"] = np.asarray(discounted[:cap], dtype=float)
        # Raw discounted payoff is kept separately from control-variate adjusted observations.
        # QAE amplitude normalisation must be based on the actual non-negative payoff, not on
        # a variance-reduced estimator that can take negative values.
        out["raw_discounted_payoff_sample"] = np.asarray(raw_discounted[:cap], dtype=float)
    return out


def classical_reference_price(
    **kwargs: Any,
) -> dict[str, Any]:
    """Return an analytic control when valid; otherwise a clearly-labelled high-path classical reference."""
    product = str(kwargs.get("product", "European")); model = str(kwargs.get("model", "GBM / Black-Scholes"))
    if product == "European" and model.startswith("GBM"):
        price = black_scholes_price(kwargs["s0"], kwargs["strike"], kwargs["maturity"], kwargs["rate"], kwargs["vol"], kwargs.get("option_type", "Call"))
        return {"price": price, "kind": "Analytic Black-Scholes", "stderr": 0.0, "runtime_ms": 0.0}
    ref_paths = int(np.clip(max(int(kwargs.get("paths", 25_000)) * 4, 100_000), 100_000, 300_000))
    ref_kwargs = dict(kwargs); ref_kwargs.update(paths=ref_paths, method="Control variate", seed=131071, return_sample=False)
    ref = monte_carlo_option_price(**ref_kwargs)
    return {"price": float(ref["price"]), "kind": "High-path classical reference", "stderr": float(ref["stderr"]), "runtime_ms": float(ref["runtime_ms"]), "paths": ref_paths}


def monte_carlo_method_benchmark(
    methods: Iterable[str],
    reference_price: float,
    **kwargs: Any,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for i, method in enumerate(methods):
        run_kwargs = dict(kwargs); run_kwargs.update(method=str(method), seed=int(kwargs.get("seed", 17)) + i * 997, return_sample=False)
        res = monte_carlo_option_price(**run_kwargs)
        err = float(res["price"] - float(reference_price))
        rows.append({
            "Method": str(method), "Executed": res["method_executed"], "Price": float(res["price"]),
            "Abs Error": abs(err), "Signed Error": err, "Std Error": float(res["stderr"]),
            "CI Width": float(2.0 * 1.96 * res["stderr"]), "Runtime ms": float(res["runtime_ms"]),
            "Paths": int(res["paths"]), "Control Beta": float(res["control_beta"]), "SE Basis": str(res.get("stderr_basis", "")),
        })
    return pd.DataFrame(rows).sort_values(["Std Error", "Abs Error"], ascending=True).reset_index(drop=True)


def monte_carlo_convergence_study(
    methods: Iterable[str],
    path_grid: Iterable[int],
    reference_price: float,
    **kwargs: Any,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for m_idx, method in enumerate(methods):
        for n in path_grid:
            run_kwargs = dict(kwargs); run_kwargs.update(paths=int(n), method=str(method), seed=1031 + m_idx * 7919 + int(n), return_sample=False)
            res = monte_carlo_option_price(**run_kwargs)
            rows.append({"Method": str(method), "Paths": int(n), "Abs Error": abs(float(res["price"]) - float(reference_price)), "Std Error": float(res["stderr"]), "Runtime ms": float(res["runtime_ms"])})
    return pd.DataFrame(rows)


def finite_difference_greeks(
    base_kwargs: dict[str, Any],
    paths: int = 20_000,
) -> dict[str, float]:
    """Common-seed bump-and-revalue Greeks for non-analytic products."""
    kw = dict(base_kwargs); kw.update(paths=int(min(paths, 50_000)), method="Control variate", seed=4049, return_sample=False)
    s0 = float(kw["s0"]); vol = float(kw["vol"])
    ds = max(0.005 * s0, 0.01); dv = max(0.01, 0.05 * vol)
    base = monte_carlo_option_price(**kw)["price"]
    up_kw = dict(kw); up_kw["s0"] = s0 + ds
    dn_kw = dict(kw); dn_kw["s0"] = max(s0 - ds, 1e-6)
    up = monte_carlo_option_price(**up_kw)["price"]; dn = monte_carlo_option_price(**dn_kw)["price"]
    vu_kw = dict(kw); vu_kw["vol"] = vol + dv
    vd_kw = dict(kw); vd_kw["vol"] = max(vol - dv, 1e-5)
    vu = monte_carlo_option_price(**vu_kw)["price"]; vd = monte_carlo_option_price(**vd_kw)["price"]
    return {
        "delta": float((up - dn) / (2.0 * ds)),
        "gamma": float((up - 2.0 * base + dn) / (ds * ds)),
        "vega": float((vu - vd) / (2.0 * dv)),
        "theta": float("nan"), "rho": float("nan"), "base_price": float(base),
    }


def option_market_risk(
    s0: float,
    strike: float,
    maturity: float,
    rate: float,
    vol: float,
    option_type: str = "Call",
    current_price: float | None = None,
    horizon_days: int = 10,
    scenarios: int = 50_000,
    drift: float = 0.0,
    seed: int = 8128,
) -> dict[str, Any]:
    """Full Black-Scholes revaluation market-risk control for a European option."""
    scenarios = int(np.clip(scenarios, 2_000, 500_000)); horizon_days = int(np.clip(horizon_days, 1, 252))
    horizon = horizon_days / 252.0; rem = max(float(maturity) - horizon, 1.0 / 252.0)
    rng = np.random.default_rng(seed); z = rng.standard_normal(scenarios)
    st_h = float(s0) * np.exp((float(drift) - 0.5 * float(vol) ** 2) * horizon + float(vol) * sqrt(horizon) * z)
    base = float(current_price) if current_price is not None else black_scholes_price(s0, strike, maturity, rate, vol, option_type)
    values = np.array([black_scholes_price(x, strike, rem, rate, vol, option_type) for x in st_h], dtype=float)
    pnl = values - base; loss = -pnl
    def tail(alpha: float) -> tuple[float, float]:
        q = float(np.quantile(loss, alpha)); c = float(loss[loss >= q].mean()) if np.any(loss >= q) else q
        return q, c
    v95, c95 = tail(0.95); v99, c99 = tail(0.99)
    return {
        "base_price": base, "pnl": pnl, "loss": loss, "var_95": v95, "cvar_95": c95, "var_99": v99, "cvar_99": c99,
        "mean_pnl": float(np.mean(pnl)), "pnl_std": float(np.std(pnl, ddof=1)), "scenarios": scenarios, "horizon_days": horizon_days,
    }



def delta_gamma_market_risk(
    s0: float,
    delta: float,
    gamma: float,
    vol: float,
    horizon_days: int = 10,
    scenarios: int = 50_000,
    drift: float = 0.0,
    seed: int = 8128,
) -> dict[str, Any]:
    """Delta-gamma market-risk approximation for products without cheap full repricing."""
    scenarios = int(np.clip(scenarios, 2_000, 500_000)); horizon_days = int(np.clip(horizon_days, 1, 252))
    horizon = horizon_days / 252.0; rng = np.random.default_rng(seed); z = rng.standard_normal(scenarios)
    st_h = float(s0) * np.exp((float(drift) - 0.5 * float(vol) ** 2) * horizon + float(vol) * sqrt(horizon) * z)
    ds = st_h - float(s0); pnl = float(delta) * ds + 0.5 * float(gamma) * ds * ds; loss = -pnl
    def tail(alpha: float) -> tuple[float, float]:
        q = float(np.quantile(loss, alpha)); c = float(loss[loss >= q].mean()) if np.any(loss >= q) else q
        return q, c
    v95, c95 = tail(0.95); v99, c99 = tail(0.99)
    return {"pnl": pnl, "loss": loss, "var_95": v95, "cvar_95": c95, "var_99": v99, "cvar_99": c99, "mean_pnl": float(np.mean(pnl)), "pnl_std": float(np.std(pnl, ddof=1)), "scenarios": scenarios, "horizon_days": horizon_days}


def exposure_cva_profile(
    s0: float,
    strike: float,
    maturity: float,
    rate: float,
    vol: float,
    option_type: str = "Call",
    paths: int = 15_000,
    exposure_points: int = 12,
    pfe_quantile: float = 0.95,
    hazard_rate: float = 0.02,
    recovery: float = 0.40,
    seed: int = 65537,
) -> dict[str, Any]:
    """Unilateral EE/PFE/CVA control under risk-neutral GBM European revaluation."""
    paths = int(np.clip(paths, 2_000, 100_000)); exposure_points = int(np.clip(exposure_points, 3, 36))
    times = np.linspace(float(maturity) / exposure_points, float(maturity), exposure_points)
    dt = np.diff(np.concatenate([[0.0], times])); rng = np.random.default_rng(seed)
    z = rng.standard_normal((paths, exposure_points)); log_s = np.zeros(paths); spots = np.empty((paths, exposure_points))
    for j, step in enumerate(dt):
        log_s += (float(rate) - 0.5 * float(vol) ** 2) * step + float(vol) * sqrt(max(step, _EPS)) * z[:, j]
        spots[:, j] = float(s0) * np.exp(log_s)
    ee: list[float] = []; pfe: list[float] = []
    for j, t in enumerate(times):
        rem = max(float(maturity) - float(t), 1e-6)
        vals = np.array([black_scholes_price(x, strike, rem, rate, vol, option_type) for x in spots[:, j]], dtype=float)
        exposure = np.maximum(vals, 0.0)
        ee.append(float(np.mean(exposure))); pfe.append(float(np.quantile(exposure, float(pfe_quantile))))
    survival_prev = 1.0; cva = 0.0; lgd = 1.0 - float(np.clip(recovery, 0.0, 1.0))
    marginal_pd: list[float] = []
    for t, e in zip(times, ee):
        survival = exp(-float(hazard_rate) * float(t)); dp = max(survival_prev - survival, 0.0); marginal_pd.append(dp)
        cva += lgd * exp(-float(rate) * float(t)) * e * dp; survival_prev = survival
    profile = pd.DataFrame({"Time": times, "EE": ee, f"PFE {int(pfe_quantile*100)}": pfe, "Marginal PD": marginal_pd})
    return {"profile": profile, "cva": float(cva), "peak_pfe": float(max(pfe) if pfe else 0.0), "peak_ee": float(max(ee) if ee else 0.0)}


def qae_algorithm_projection(target_error_fraction: float, confidence: float = 0.95) -> pd.DataFrame:
    """Illustrative algorithm-level query envelopes, not exact implementation guarantees."""
    eps = float(np.clip(target_error_fraction, 1e-4, 0.25)); conf = float(np.clip(confidence, 0.5, 0.9999)); delta = max(1.0 - conf, 1e-9)
    canonical = int(np.ceil(pi / eps))
    iterative = int(np.ceil((2.0 / eps) * np.log(2.0 / delta)))
    maximum_likelihood = int(np.ceil((1.25 / eps) * np.log(2.0 / delta)))
    classical = int(np.ceil(np.log(2.0 / delta) / (2.0 * eps * eps)))
    return pd.DataFrame([
        {"Algorithm": "Classical MC envelope", "Queries": classical, "Scaling": "O(1/ε²)", "Ancilla model": 0},
        {"Algorithm": "Canonical QAE", "Queries": canonical, "Scaling": "O(1/ε)", "Ancilla model": int(np.ceil(np.log2(max(canonical, 2))))},
        {"Algorithm": "Iterative QAE", "Queries": iterative, "Scaling": "O((1/ε) log(1/δ))", "Ancilla model": 1},
        {"Algorithm": "Maximum-Likelihood QAE", "Queries": maximum_likelihood, "Scaling": "O((1/ε) log(1/δ))", "Ancilla model": 1},
    ])


def quantum_resource_estimate(
    epsilon: float,
    confidence: float,
    algorithm: str,
    state_qubits: int,
    state_prep_depth: int,
    payoff_depth: int,
    logical_gate_ns: float,
    fault_tolerance_overhead: float,
    measurement_us: float,
    physical_per_logical: int = 1000,
) -> dict[str, float]:
    table = qae_algorithm_projection(epsilon, confidence)
    row = table[table["Algorithm"] == str(algorithm)]
    if row.empty: row = table[table["Algorithm"] == "Iterative QAE"]
    calls = int(row.iloc[0]["Queries"]); ancilla = int(row.iloc[0]["Ancilla model"])
    logical_qubits = int(max(1, state_qubits) + max(1, ancilla) + 2)
    # A-query-A† plus payoff / comparison work. This is an engineering envelope, not compiled circuit depth.
    per_query_depth = int(max(1, 2 * int(state_prep_depth) + int(payoff_depth) + 24))
    total_depth = int(calls * per_query_depth)
    gate_time_s = max(float(logical_gate_ns), 0.01) * 1e-9
    ft = max(float(fault_tolerance_overhead), 1.0)
    measurement_s = max(float(measurement_us), 0.0) * 1e-6
    projected_runtime_s = total_depth * gate_time_s * ft + calls * measurement_s
    physical_qubits = logical_qubits * int(max(1, physical_per_logical))
    return {
        "queries": float(calls), "logical_qubits": float(logical_qubits), "physical_qubits": float(physical_qubits),
        "per_query_depth": float(per_query_depth), "total_depth": float(total_depth), "projected_runtime_s": float(projected_runtime_s),
        "state_prep_share": float((2 * int(state_prep_depth)) / max(per_query_depth, 1)),
        "per_query_ms": float(projected_runtime_s * 1000.0 / max(calls, 1)),
    }


def qae_error_budget(
    amplitude_error: float,
    discretization_error: float,
    state_prep_error: float,
    hardware_error: float,
    truncation_error: float = 0.0,
) -> dict[str, float]:
    """Root-sum-square diagnostic envelope in normalized amplitude units.

    This is intentionally an engineering diagnostic, not a theorem about correlated
    fault-tolerant hardware errors. Truncation is explicit because unbounded financial
    payoffs must be mapped to a bounded amplitude before amplitude estimation applies.
    """
    vals = np.array([amplitude_error, discretization_error, state_prep_error, hardware_error, truncation_error], dtype=float)
    vals = np.clip(vals, 0.0, None)
    rss = float(np.sqrt(np.sum(vals * vals)))
    return {
        "amplitude": float(vals[0]), "discretization": float(vals[1]),
        "state_prep": float(vals[2]), "hardware": float(vals[3]),
        "truncation": float(vals[4]), "rss_total": rss,
    }


def qae_total_error_feasibility(
    target_price_error: float,
    payoff_cap: float,
    discretization_error: float,
    state_prep_error: float,
    hardware_error: float,
    truncation_price_error: float = 0.0,
) -> dict[str, float | bool]:
    """Map a total price-error target into the amplitude-estimation budget.

    Non-AE components form an irreducible engineering floor. If the requested
    total error is below that floor, the resource point is infeasible and no
    QAE runtime should be reported as though the target were attainable.
    """
    cap = max(float(payoff_cap), 1e-12)
    target_price = max(float(target_price_error), 0.0)
    target_norm = target_price / cap
    trunc_norm = max(float(truncation_price_error), 0.0) / cap
    floor_vec = np.array([discretization_error, state_prep_error, hardware_error, trunc_norm], dtype=float)
    floor_vec = np.clip(floor_vec, 0.0, None)
    floor_norm = float(np.sqrt(np.sum(floor_vec * floor_vec)))
    floor_price = floor_norm * cap
    slack_sq = target_norm * target_norm - floor_norm * floor_norm
    feasible = bool(slack_sq > 1e-18)
    ae_budget = float(np.sqrt(max(slack_sq, 0.0))) if feasible else 0.0
    return {
        "feasible": feasible,
        "target_price_error": target_price,
        "target_normalized_error": target_norm,
        "error_floor_normalized": floor_norm,
        "error_floor_price": floor_price,
        "ae_budget_normalized": ae_budget,
        "ae_budget_price": ae_budget * cap,
        "truncation_normalized": trunc_norm,
    }


def advantage_frontier(
    errors: Iterable[float],
    confidence: float,
    algorithm: str,
    classical_ms_per_sample: float,
    resource_kwargs: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, float]] = []
    for eps in errors:
        eps = float(eps)
        classical = qae_resource_projection(eps, confidence)["classical_calls"]
        qres = quantum_resource_estimate(eps, confidence, algorithm=algorithm, **resource_kwargs)
        c_ms = float(classical) * max(float(classical_ms_per_sample), 1e-9)
        q_ms = float(qres["projected_runtime_s"]) * 1000.0
        q_calls = max(float(qres["queries"]), 1.0)
        rows.append({
            "epsilon": eps, "Classical projected ms": c_ms, "Quantum engineering ms": q_ms,
            "Speed ratio C/Q": c_ms / max(q_ms, 1e-12), "Break-even query ms": c_ms / q_calls,
            "Projected query ms": float(qres["per_query_ms"]), "Classical calls": float(classical), "Quantum queries": q_calls,
        })
    return pd.DataFrame(rows)


def randomized_sobol_study(
    path_grid: Iterable[int],
    reference_price: float,
    scrambles: int = 16,
    **kwargs: Any,
) -> pd.DataFrame:
    """Randomized-QMC convergence diagnostic using independent Sobol scrambles.

    RMSE across independent randomized scrambles is a statistically meaningful quantity;
    a single Sobol scramble is never treated as an IID standard error.
    """
    rows: list[dict[str, float]] = []
    scrambles = int(np.clip(scrambles, 4, 64))
    for n in path_grid:
        estimates: list[float] = []
        runtimes: list[float] = []
        executed = "Sobol QMC"
        for j in range(scrambles):
            run_kwargs = dict(kwargs)
            run_kwargs.update(paths=int(n), method="Sobol QMC", seed=8101 + 104729 * j + int(n), return_sample=False)
            res = monte_carlo_option_price(**run_kwargs)
            estimates.append(float(res["price"])); runtimes.append(float(res["runtime_ms"]))
            executed = str(res.get("method_executed", executed))
        est = np.asarray(estimates, dtype=float)
        errors = est - float(reference_price)
        rmse = float(np.sqrt(np.mean(errors * errors)))
        scramble_sd = float(np.std(est, ddof=1)) if len(est) > 1 else 0.0
        rows.append({
            "Paths": int(n), "Scrambles": int(scrambles), "Mean Price": float(np.mean(est)),
            "RMSE": rmse, "Mean Abs Error": float(np.mean(np.abs(errors))),
            "Scramble SD": scramble_sd, "SE of Scramble Mean": scramble_sd / sqrt(max(len(est), 1)),
            "Mean Runtime ms": float(np.mean(runtimes)), "Median Runtime ms": float(np.median(runtimes)),
            "Executed": executed,
        })
    out = pd.DataFrame(rows)
    if len(out) >= 2 and np.all(out["RMSE"].to_numpy(dtype=float) > 0):
        x = np.log(out["Paths"].to_numpy(dtype=float)); y = np.log(out["RMSE"].to_numpy(dtype=float))
        slope, intercept = np.polyfit(x, y, 1)
        out["Empirical RMSE slope"] = float(slope)
        out["Empirical RMSE intercept"] = float(intercept)
    else:
        out["Empirical RMSE slope"] = np.nan; out["Empirical RMSE intercept"] = np.nan
    return out


def _fit_power_law(x: np.ndarray, y: np.ndarray, decreasing: bool = False) -> dict[str, float]:
    """Fit y ~= c*x^b in log space with basic diagnostics."""
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y) & (x > 0) & (y > 0)
    x = x[mask]; y = y[mask]
    if len(x) < 2:
        return {"c": float(np.nanmedian(y) if len(y) else 1.0), "beta": -0.5 if decreasing else 1.0, "r2": 0.0}
    lx, ly = np.log(x), np.log(y)
    beta, logc = np.polyfit(lx, ly, 1)
    if decreasing and beta >= -1e-4:
        beta = -0.5
        logc = float(np.mean(ly - beta * lx))
    if (not decreasing) and beta < 0.05:
        # Runtime noise/cache effects can make short benchmarks look decreasing.
        # Do not extrapolate an unphysical negative runtime exponent.
        beta = 1.0
        logc = float(np.mean(ly - beta * lx))
    pred = logc + beta * lx
    ss_res = float(np.sum((ly - pred) ** 2)); ss_tot = float(np.sum((ly - np.mean(ly)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > _EPS else 1.0
    r2 = float(np.clip(r2, 0.0, 1.0))
    return {"c": float(np.exp(logc)), "beta": float(beta), "r2": r2}


def classical_convergence_models(
    convergence: pd.DataFrame,
    randomized_sobol: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Fit empirical precision/runtime power laws and retain calibration domain.

    The observed path range is stored explicitly so the advantage frontier can
    distinguish interpolation from extrapolation and never extrapolate below the
    smallest actually benchmarked sample size.
    """
    rows: list[dict[str, Any]] = []
    if isinstance(convergence, pd.DataFrame) and not convergence.empty:
        for method, g in convergence.groupby("Method"):
            if str(method) == "Sobol QMC" and isinstance(randomized_sobol, pd.DataFrame) and not randomized_sobol.empty:
                pg = randomized_sobol
                precision = pg["RMSE"].to_numpy(dtype=float)
                paths = pg["Paths"].to_numpy(dtype=float)
                runtime = pg["Mean Runtime ms"].to_numpy(dtype=float)
                precision_basis = "randomized Sobol RMSE"
            else:
                paths = g["Paths"].to_numpy(dtype=float)
                precision = g["Std Error"].to_numpy(dtype=float)
                runtime = g["Runtime ms"].to_numpy(dtype=float)
                precision_basis = "executed SE scaling"
            pf = _fit_power_law(paths, precision, decreasing=True)
            rf = _fit_power_law(paths, runtime, decreasing=False)
            finite_paths = paths[np.isfinite(paths) & (paths > 0)]
            n_min = float(np.min(finite_paths)) if len(finite_paths) else float("nan")
            n_max = float(np.max(finite_paths)) if len(finite_paths) else float("nan")
            fit_quality = "STRONG" if min(pf["r2"], rf["r2"]) >= 0.80 else ("MODERATE" if min(pf["r2"], rf["r2"]) >= 0.50 else "WEAK")
            rows.append({
                "Method": str(method), "Precision c": pf["c"], "Precision beta": pf["beta"], "Precision R2": pf["r2"],
                "Runtime c": rf["c"], "Runtime gamma": rf["beta"], "Runtime R2": rf["r2"], "Precision basis": precision_basis,
                "Min Observed Paths": n_min, "Max Observed Paths": n_max, "Fit Quality": fit_quality,
            })
    return pd.DataFrame(rows)

def qae_payoff_normalization(
    s0: float,
    strike: float,
    maturity: float,
    rate: float,
    vol: float,
    product: str,
    option_type: str,
    model: str,
    tail_probability: float = 1e-4,
    raw_discounted_sample: np.ndarray | None = None,
) -> dict[str, float | str]:
    """Construct a bounded [0,1] payoff map and estimate truncation cost.

    European GBM uses lognormal quantiles and an analytic clipped-tail expectation.
    Other contracts use the raw non-negative discounted payoff sample and are clearly
    labelled empirical because no exact truncation theorem is asserted.
    """
    s0 = max(float(s0), _EPS); strike = max(float(strike), _EPS); maturity = max(float(maturity), 1e-8)
    vol = max(float(vol), 1e-8); tail = float(np.clip(tail_probability, 1e-8, 0.05)); disc = exp(-float(rate) * maturity)
    side_call = not str(option_type).lower().startswith("p")
    if str(product) == "European" and str(model).startswith("GBM"):
        try:
            from scipy.stats import norm
            zlo = float(norm.ppf(tail / 2.0)); zhi = float(norm.ppf(1.0 - tail / 2.0))
        except Exception:
            zlo, zhi = -3.8906, 3.8906
        mu = (float(rate) - 0.5 * vol * vol) * maturity; sig = vol * sqrt(maturity)
        smin = s0 * exp(mu + sig * zlo); smax = s0 * exp(mu + sig * zhi)
        if side_call:
            raw_cap = max(smax - strike, 1e-10); cap = disc * raw_cap
            # Error from clipping payoff at payoff(Smax): E[(S-Smax) 1_{S>Smax}] discounted.
            a = max(smax, strike)
            d2_tail = (log(s0 / a) + (float(rate) - 0.5 * vol * vol) * maturity) / (vol * sqrt(maturity))
            d1_tail = d2_tail + vol * sqrt(maturity)
            tail_prob_eff = 0.5 * (1.0 + erf(d2_tail / sqrt(2.0)))
            tail_stock = s0 * 0.5 * (1.0 + erf(d1_tail / sqrt(2.0)))
            trunc = max(tail_stock - a * disc * tail_prob_eff, 0.0)
        else:
            raw_cap = max(strike - smin, 1e-10); cap = disc * raw_cap
            a = min(smin, strike)
            z2 = (log(a / s0) - (float(rate) - 0.5 * vol * vol) * maturity) / (vol * sqrt(maturity))
            z1 = (log(a / s0) - (float(rate) + 0.5 * vol * vol) * maturity) / (vol * sqrt(maturity))
            p_low = 0.5 * (1.0 + erf(z2 / sqrt(2.0)))
            stock_low_disc = s0 * 0.5 * (1.0 + erf(z1 / sqrt(2.0)))
            trunc = max(a * disc * p_low - stock_low_disc, 0.0)
        return {
            "payoff_cap": float(cap), "s_min": float(smin), "s_max": float(smax),
            "truncation_price_error": float(trunc), "tail_probability": tail,
            "normalization_kind": "analytic lognormal truncation", "empirical_resolution": 0.0,
        }
    sample = np.asarray(raw_discounted_sample if raw_discounted_sample is not None else [], dtype=float)
    sample = sample[np.isfinite(sample) & (sample >= 0)]
    if len(sample) < 32:
        cap = max(float(strike) * disc, 1.0)
        return {"payoff_cap": cap, "s_min": float("nan"), "s_max": float("nan"), "truncation_price_error": 0.0, "tail_probability": tail, "normalization_kind": "fallback engineering cap", "empirical_resolution": 1.0}
    resolution = 1.0 / len(sample); effective_tail = max(tail, resolution)
    q = float(np.quantile(sample, 1.0 - effective_tail))
    cap = max(q, float(np.mean(sample)) * 1.05, 1e-8)
    trunc = float(np.mean(np.maximum(sample - cap, 0.0)))
    return {
        "payoff_cap": float(cap), "s_min": float("nan"), "s_max": float("nan"),
        "truncation_price_error": trunc, "tail_probability": tail,
        "normalization_kind": "empirical payoff truncation", "empirical_resolution": float(resolution),
    }


def product_resource_profile(
    product: str,
    model: str,
    steps: int,
    basket_assets: int,
) -> dict[str, float | str]:
    """Transparent heuristic multipliers for product-dependent resource envelopes.

    These are not compiled-circuit estimates. They make the current engineering model
    sensitive to path dependence, basket dimensionality and stochastic-volatility state.
    """
    product = str(product); model = str(model); steps = int(max(1, steps)); basket_assets = int(max(1, basket_assets))
    work = 0; prep_mult = 1.0; payoff_mult = 1.0; label = "European terminal-state"
    if product == "Asian Arithmetic":
        work = int(np.ceil(np.log2(steps + 1))) + 5; prep_mult = max(2.0, 0.75 * steps); payoff_mult = max(2.0, 0.50 * steps); label = "path average accumulator"
    elif product == "Barrier":
        work = int(np.ceil(np.log2(steps + 1))) + 4; prep_mult = max(2.0, 0.75 * steps); payoff_mult = max(2.0, 0.35 * steps); label = "path barrier comparator"
    elif product == "Basket":
        work = int(np.ceil(np.log2(basket_assets + 1))) + basket_assets; prep_mult = max(1.5, 1.2 * basket_assets); payoff_mult = max(1.5, 0.8 * basket_assets); label = "multi-asset correlated state"
    if model.startswith("Heston"):
        work += 8; prep_mult *= max(2.0, 0.90 * steps); payoff_mult *= 1.25; label += " + stochastic variance register"
    return {"work_qubits": float(work), "prep_multiplier": float(prep_mult), "payoff_multiplier": float(payoff_mult), "resource_label": label}


def quantum_resource_estimate_product(
    epsilon: float,
    confidence: float,
    algorithm: str,
    state_qubits: int,
    state_prep_depth: int,
    payoff_depth: int,
    logical_gate_ns: float,
    fault_tolerance_overhead: float,
    measurement_us: float,
    physical_per_logical: int,
    product: str,
    model: str,
    steps: int,
    basket_assets: int,
) -> dict[str, float | str]:
    profile = product_resource_profile(product, model, steps, basket_assets)
    adjusted_state = int(max(1, state_qubits) + int(profile["work_qubits"]))
    adjusted_prep = int(max(1, round(float(state_prep_depth) * float(profile["prep_multiplier"]))))
    adjusted_payoff = int(max(1, round(float(payoff_depth) * float(profile["payoff_multiplier"]))))
    out = quantum_resource_estimate(
        epsilon, confidence, algorithm, adjusted_state, adjusted_prep, adjusted_payoff,
        logical_gate_ns, fault_tolerance_overhead, measurement_us, physical_per_logical,
    )
    out.update({
        "base_state_qubits": float(state_qubits), "work_qubits": float(profile["work_qubits"]),
        "adjusted_state_qubits": float(adjusted_state), "adjusted_prep_depth": float(adjusted_prep),
        "adjusted_payoff_depth": float(adjusted_payoff), "resource_label": str(profile["resource_label"]),
    })
    return out


def empirical_classical_frontier(
    price_errors: Iterable[float],
    convergence_models: pd.DataFrame,
) -> pd.DataFrame:
    """Best empirical classical runtime for each absolute price-error target.

    Requirements below the smallest observed benchmark size are floored to that
    observed minimum rather than extrapolated. Requirements above the largest
    observed size are retained but labelled EXTRAPOLATED and are ineligible for
    a break-even declaration.
    """
    rows: list[dict[str, Any]] = []
    if not isinstance(convergence_models, pd.DataFrame) or convergence_models.empty:
        return pd.DataFrame()
    for err in price_errors:
        err = max(float(err), 1e-12)
        candidates: list[dict[str, Any]] = []
        for _, r in convergence_models.iterrows():
            c = max(float(r["Precision c"]), 1e-12); beta = float(r["Precision beta"])
            if beta >= -1e-6:
                continue
            raw_n = float((err / c) ** (1.0 / beta))
            n_min = max(float(r.get("Min Observed Paths", 16.0)), 1.0)
            n_max = max(float(r.get("Max Observed Paths", n_min)), n_min)
            if raw_n < n_min:
                n_req = n_min
                domain = "FLOORED TO OBSERVED MIN"
            else:
                n_req = raw_n
                domain = "INTERPOLATED" if n_req <= n_max else "EXTRAPOLATED"
            rc = max(float(r["Runtime c"]), 1e-12); gamma = max(float(r["Runtime gamma"]), 0.05)
            runtime = rc * (n_req ** gamma)
            candidates.append({
                "Method": str(r["Method"]), "Required Paths": n_req, "Raw Required Paths": raw_n,
                "Projected Runtime ms": runtime, "Precision R2": float(r["Precision R2"]), "Runtime R2": float(r["Runtime R2"]),
                "Min Observed Paths": n_min, "Max Observed Paths": n_max, "Domain Status": domain,
                "Break-even Eligible": bool(domain != "EXTRAPOLATED"), "Fit Quality": str(r.get("Fit Quality", "N/A")),
            })
        if candidates:
            best = min(candidates, key=lambda x: x["Projected Runtime ms"])
            best["Target price error"] = err
            rows.append(best)
    return pd.DataFrame(rows)


def product_advantage_frontier(
    total_price_errors: Iterable[float],
    payoff_cap: float,
    confidence: float,
    algorithm: str,
    convergence_models: pd.DataFrame,
    resource_kwargs: dict[str, Any],
    discretization_error: float = 0.0,
    state_prep_error: float = 0.0,
    hardware_error: float = 0.0,
    truncation_price_error: float = 0.0,
) -> pd.DataFrame:
    """Total-error classical↔quantum engineering frontier.

    The target is an absolute TOTAL price error. Non-amplitude error components
    create an irreducible floor. Only the residual amplitude-estimation budget is
    passed to the QAE resource model. Infeasible targets receive no quantum runtime.
    """
    price_errs = np.asarray(list(total_price_errors), dtype=float)
    price_errs = np.maximum(price_errs, 1e-12)
    classical = empirical_classical_frontier(price_errs, convergence_models)
    rows: list[dict[str, Any]] = []
    for perr in price_errs:
        c = classical.iloc[(classical["Target price error"] - perr).abs().argmin()] if not classical.empty else None
        feas = qae_total_error_feasibility(
            float(perr), float(payoff_cap), float(discretization_error), float(state_prep_error),
            float(hardware_error), float(truncation_price_error),
        )
        c_ms = float(c["Projected Runtime ms"]) if c is not None else float("nan")
        if bool(feas["feasible"]):
            qres = quantum_resource_estimate_product(float(feas["ae_budget_normalized"]), float(confidence), str(algorithm), **resource_kwargs)
            q_ms = float(qres["projected_runtime_s"]) * 1000.0
            q_calls = max(float(qres["queries"]), 1.0)
            projected_query = float(qres["per_query_ms"])
            ratio = c_ms / max(q_ms, 1e-12)
            break_even_query = c_ms / q_calls
            classical_domain = str(c["Domain Status"]) if c is not None else "N/A"
            quantum_status = "FEASIBLE"
            eligible = bool(c is not None and c.get("Break-even Eligible", False))
        else:
            q_ms = float("nan"); q_calls = float("nan"); projected_query = float("nan")
            ratio = float("nan"); break_even_query = float("nan")
            classical_domain = str(c["Domain Status"]) if c is not None else "N/A"
            quantum_status = "INFEASIBLE"; eligible = False
        rows.append({
            "Target price error": float(perr),
            "Target normalized total error": float(feas["target_normalized_error"]),
            "Error floor price": float(feas["error_floor_price"]),
            "AE budget normalized": float(feas["ae_budget_normalized"]),
            "AE budget price": float(feas["ae_budget_price"]),
            "Feasible": bool(feas["feasible"]),
            "Best classical method": str(c["Method"]) if c is not None else "N/A",
            "Classical required paths": float(c["Required Paths"]) if c is not None else float("nan"),
            "Raw classical required paths": float(c["Raw Required Paths"]) if c is not None else float("nan"),
            "Classical projected ms": c_ms,
            "Classical domain": classical_domain,
            "Quantum status": quantum_status,
            "Precision R2": float(c["Precision R2"]) if c is not None else float("nan"),
            "Runtime R2": float(c["Runtime R2"]) if c is not None else float("nan"),
            "Quantum engineering ms": q_ms,
            "Speed ratio C/Q": ratio,
            "Break-even query ms": break_even_query,
            "Projected query ms": projected_query,
            "Quantum queries": q_calls,
            "Break-even Eligible": eligible,
        })
    return pd.DataFrame(rows)

def clean_returns_frame(returns: pd.DataFrame | None) -> pd.DataFrame:
    if not isinstance(returns, pd.DataFrame) or returns.empty:
        return pd.DataFrame()
    out = returns.copy()
    for c in out.columns:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.replace([np.inf, -np.inf], np.nan).dropna(how="all")
    keep = [c for c in out.columns if out[c].notna().sum() >= max(20, int(len(out) * 0.50))]
    if not keep:
        return pd.DataFrame()
    return out[keep].dropna()


def synthetic_returns(
    assets: list[str] | None = None,
    observations: int = 504,
    seed: int = 23,
) -> pd.DataFrame:
    assets = assets or ["SPY", "QQQ", "IWM", "TLT", "GLD", "HYG"]
    n = len(assets)
    rng = np.random.default_rng(seed)
    base_corr = np.full((n, n), 0.20, dtype=float)
    np.fill_diagonal(base_corr, 1.0)
    for i in range(n):
        for j in range(i + 1, n):
            if assets[i] in {"SPY", "QQQ", "IWM", "HYG"} and assets[j] in {"SPY", "QQQ", "IWM", "HYG"}:
                base_corr[i, j] = base_corr[j, i] = 0.62
            if "TLT" in {assets[i], assets[j]}:
                base_corr[i, j] = base_corr[j, i] = -0.12
            if "GLD" in {assets[i], assets[j]}:
                base_corr[i, j] = base_corr[j, i] = 0.05
    eig = np.linalg.eigvalsh(base_corr)
    if eig.min() <= 0:
        base_corr += np.eye(n) * (abs(float(eig.min())) + 0.02)
        d = np.sqrt(np.diag(base_corr))
        base_corr = base_corr / np.outer(d, d)

    ann_vol = np.linspace(0.14, 0.28, n)
    daily_vol = ann_vol / sqrt(252.0)
    cov = base_corr * np.outer(daily_vol, daily_vol)
    ann_mu = np.linspace(0.045, 0.11, n)
    daily_mu = ann_mu / 252.0
    draws = rng.multivariate_normal(daily_mu, cov, size=int(observations))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=int(observations))
    return pd.DataFrame(draws, index=idx, columns=assets)


def annualized_moments(returns: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    ret = clean_returns_frame(returns)
    if ret.empty:
        return np.array([]), np.empty((0, 0))
    mu = ret.mean().to_numpy(dtype=float) * 252.0
    cov = ret.cov().to_numpy(dtype=float) * 252.0
    return mu, cov


def build_qubo(
    mu: np.ndarray,
    cov: np.ndarray,
    risk_aversion: float,
    cardinality: int,
    penalty: float,
) -> np.ndarray:
    mu = np.asarray(mu, dtype=float).reshape(-1)
    cov = np.asarray(cov, dtype=float)
    n = len(mu)
    if cov.shape != (n, n):
        raise ValueError("covariance shape mismatch")
    k = int(np.clip(cardinality, 1, max(n, 1)))
    # Equal-weight cardinality objective:
    #   lambda * (x/k)' Sigma (x/k) - mu' (x/k)
    # plus the exact-cardinality penalty (1'x - k)^2.
    Q = (float(risk_aversion) / (k * k)) * cov.copy()
    Q += float(penalty) * np.ones((n, n), dtype=float)
    diag = np.diag_indices(n)
    Q[diag] += -(mu / k) - 2.0 * float(penalty) * k
    return (Q + Q.T) / 2.0


def portfolio_objective(
    x: np.ndarray,
    mu: np.ndarray,
    cov: np.ndarray,
    risk_aversion: float,
) -> tuple[float, float, float]:
    x = np.asarray(x, dtype=float)
    k = max(float(x.sum()), 1.0)
    w = x / k
    expected_return = float(w @ mu)
    variance = float(w @ cov @ w)
    objective = float(risk_aversion) * variance - expected_return
    return objective, expected_return, sqrt(max(variance, 0.0))


def solve_cardinality_portfolio_exact(
    mu: np.ndarray,
    cov: np.ndarray,
    cardinality: int,
    risk_aversion: float,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    mu = np.asarray(mu, dtype=float).reshape(-1)
    cov = np.asarray(cov, dtype=float)
    n = len(mu)
    k = int(np.clip(cardinality, 1, max(n, 1)))
    if n == 0 or cov.shape != (n, n):
        return {"available": False, "reason": "invalid moments"}
    if n > 16:
        return {"available": False, "reason": "exact benchmark capped at 16 assets"}

    best: dict[str, Any] | None = None
    evaluated = 0
    for combo in combinations(range(n), k):
        x = np.zeros(n, dtype=float)
        x[list(combo)] = 1.0
        objective, expected_return, vol = portfolio_objective(x, mu, cov, risk_aversion)
        evaluated += 1
        if best is None or objective < best["objective"]:
            best = {
                "objective": objective,
                "expected_return": expected_return,
                "volatility": vol,
                "x": x,
                "indices": list(combo),
            }

    assert best is not None
    names = labels or [f"A{i+1}" for i in range(n)]
    best["selected"] = [names[i] for i in best["indices"]]
    best["evaluated"] = evaluated
    best["available"] = True
    return best



def _binary_vector_from_labels(labels: list[str], selected: Iterable[str] | None) -> np.ndarray:
    names = {str(x).strip().upper() for x in (selected or []) if str(x).strip()}
    return np.array([1.0 if str(label).upper() in names else 0.0 for label in labels], dtype=float)


def build_portfolio_qubo_components(
    mu: np.ndarray,
    cov: np.ndarray,
    *,
    risk_aversion: float,
    cardinality: int,
    constraint_penalty: float,
    turnover_penalty: float = 0.0,
    transaction_cost_bps: float = 0.0,
    previous_x: np.ndarray | None = None,
    target_return: float | None = None,
    target_return_penalty: float = 0.0,
    required_mask: np.ndarray | None = None,
    excluded_mask: np.ndarray | None = None,
) -> dict[str, Any]:
    """Compile an equal-weight binary selection problem into auditable QUBO terms.

    Decision x_i is binary. If exactly K assets are selected, the economic portfolio is
    w_i=x_i/K. Hard business constraints are represented as penalties in the QUBO and
    are independently checked by classical controls.
    """
    mu = np.asarray(mu, dtype=float).reshape(-1)
    cov = np.asarray(cov, dtype=float)
    n = len(mu)
    if n == 0 or cov.shape != (n, n):
        raise ValueError("invalid moment dimensions")
    k = int(np.clip(cardinality, 1, n))
    lam = float(max(risk_aversion, 0.0))
    penalty = float(max(constraint_penalty, 0.0))

    zeros = lambda: np.zeros((n, n), dtype=float)
    parts: dict[str, np.ndarray] = {}
    offsets: dict[str, float] = {}

    risk = (lam / (k * k)) * cov
    parts["Risk"] = (risk + risk.T) / 2.0
    offsets["Risk"] = 0.0

    ret = zeros()
    ret[np.diag_indices(n)] = -mu / k
    parts["Return"] = ret
    offsets["Return"] = 0.0

    cardinality_q = penalty * np.ones((n, n), dtype=float)
    cardinality_q[np.diag_indices(n)] += -2.0 * penalty * k
    parts["Cardinality"] = cardinality_q
    offsets["Cardinality"] = penalty * k * k

    prev = np.zeros(n, dtype=float) if previous_x is None else np.asarray(previous_x, dtype=float).reshape(-1)
    if len(prev) != n:
        raise ValueError("previous_x size mismatch")
    prev = (prev > 0.5).astype(float)
    # One-way equal-weight turnover = 0.5/K * sum |x_i-x0_i| when prior K is comparable.
    turnover_coeff = float(max(turnover_penalty, 0.0)) + float(max(transaction_cost_bps, 0.0)) / 10000.0
    turnover_q = zeros()
    turnover_offset = 0.0
    if turnover_coeff > 0:
        unit = 0.5 * turnover_coeff / k
        linear = np.where(prev > 0.5, -unit, unit)
        turnover_q[np.diag_indices(n)] = linear
        turnover_offset = float(unit * prev.sum())
    parts["Turnover + Costs"] = turnover_q
    offsets["Turnover + Costs"] = turnover_offset

    target_q = zeros()
    target_offset = 0.0
    if target_return is not None and float(target_return_penalty) > 0:
        eta = float(target_return_penalty)
        target = float(target_return)
        target_q += (eta / (k * k)) * np.outer(mu, mu)
        target_q[np.diag_indices(n)] += -(2.0 * eta * target / k) * mu
        target_offset = eta * target * target
    parts["Target Return"] = (target_q + target_q.T) / 2.0
    offsets["Target Return"] = target_offset

    req = np.zeros(n, dtype=float) if required_mask is None else (np.asarray(required_mask).reshape(-1) > 0.5).astype(float)
    exc = np.zeros(n, dtype=float) if excluded_mask is None else (np.asarray(excluded_mask).reshape(-1) > 0.5).astype(float)
    if len(req) != n or len(exc) != n:
        raise ValueError("constraint mask size mismatch")
    if np.any((req > 0.5) & (exc > 0.5)):
        raise ValueError("an asset cannot be both required and excluded")
    hard_q = zeros()
    hard_offset = 0.0
    diag = np.zeros(n, dtype=float)
    diag += penalty * exc
    diag += -penalty * req
    hard_offset += float(penalty * req.sum())
    hard_q[np.diag_indices(n)] = diag
    parts["Required / Excluded"] = hard_q
    offsets["Required / Excluded"] = hard_offset

    total = np.zeros((n, n), dtype=float)
    total_offset = 0.0
    for name, q in parts.items():
        total += q
        total_offset += offsets[name]
    total = (total + total.T) / 2.0

    return {
        "Q": total,
        "offset": float(total_offset),
        "components": parts,
        "component_offsets": offsets,
        "cardinality": k,
        "previous_x": prev,
        "required_mask": req,
        "excluded_mask": exc,
        "target_return": None if target_return is None else float(target_return),
        "risk_aversion": lam,
        "constraint_penalty": penalty,
        "turnover_penalty": float(max(turnover_penalty, 0.0)),
        "transaction_cost_bps": float(max(transaction_cost_bps, 0.0)),
        "target_return_penalty": float(max(target_return_penalty, 0.0)),
    }


def qubo_energy(x: np.ndarray, Q: np.ndarray, offset: float = 0.0) -> float:
    xv = np.asarray(x, dtype=float).reshape(-1)
    q = np.asarray(Q, dtype=float)
    return float(xv @ q @ xv + float(offset))


def qubo_component_energies(x: np.ndarray, compiled: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name, q in compiled.get("components", {}).items():
        out[name] = qubo_energy(x, q, compiled.get("component_offsets", {}).get(name, 0.0))
    return out


def qubo_to_ising(Q: np.ndarray, offset: float = 0.0) -> dict[str, Any]:
    """Convert x'Qx with x=(1-z)/2 into E=c+h'z+sum_{i<j}J_ij z_i z_j."""
    q = np.asarray(Q, dtype=float)
    if q.ndim != 2 or q.shape[0] != q.shape[1]:
        raise ValueError("Q must be square")
    q = (q + q.T) / 2.0
    n = q.shape[0]
    h = np.zeros(n, dtype=float)
    J = np.zeros((n, n), dtype=float)
    c = float(offset)
    for i in range(n):
        c += 0.5 * q[i, i]
        h[i] += -0.5 * q[i, i]
    for i in range(n):
        for j in range(i + 1, n):
            cij = q[i, j]
            c += 0.5 * cij
            h[i] += -0.5 * cij
            h[j] += -0.5 * cij
            J[i, j] = J[j, i] = 0.5 * cij
    return {"h": h, "J": J, "offset": float(c)}


def portfolio_solution_metrics(
    x: np.ndarray,
    mu: np.ndarray,
    cov: np.ndarray,
    *,
    labels: list[str] | None = None,
    previous_x: np.ndarray | None = None,
    transaction_cost_bps: float = 0.0,
    required_mask: np.ndarray | None = None,
    excluded_mask: np.ndarray | None = None,
    cardinality: int | None = None,
) -> dict[str, Any]:
    xv = (np.asarray(x, dtype=float).reshape(-1) > 0.5).astype(float)
    mu = np.asarray(mu, dtype=float).reshape(-1)
    cov = np.asarray(cov, dtype=float)
    n = len(mu)
    if len(xv) != n:
        raise ValueError("solution size mismatch")
    count = int(xv.sum())
    w = xv / max(count, 1)
    exp_ret = float(w @ mu) if count else 0.0
    variance = float(w @ cov @ w) if count else 0.0
    vol = sqrt(max(variance, 0.0))
    sharpe = exp_ret / vol if vol > _EPS else float("nan")

    prev = np.zeros(n, dtype=float) if previous_x is None else (np.asarray(previous_x).reshape(-1) > 0.5).astype(float)
    prev_count = int(prev.sum())
    prev_w = prev / max(prev_count, 1)
    turnover = float(0.5 * np.abs(w - prev_w).sum()) if previous_x is not None else 0.0
    cost = float(max(transaction_cost_bps, 0.0) / 10000.0 * turnover)

    req = np.zeros(n, dtype=float) if required_mask is None else (np.asarray(required_mask).reshape(-1) > 0.5).astype(float)
    exc = np.zeros(n, dtype=float) if excluded_mask is None else (np.asarray(excluded_mask).reshape(-1) > 0.5).astype(float)
    violations = {
        "cardinality": 0 if cardinality is None else abs(count - int(cardinality)),
        "required": int(np.sum((req > 0.5) & (xv < 0.5))),
        "excluded": int(np.sum((exc > 0.5) & (xv > 0.5))),
    }
    feasible = all(v == 0 for v in violations.values())
    names = labels or [f"A{i+1}" for i in range(n)]
    return {
        "x": xv,
        "selected": [names[i] for i in range(n) if xv[i] > 0.5],
        "count": count,
        "weights": w,
        "expected_return": exp_ret,
        "volatility": vol,
        "sharpe": sharpe,
        "turnover": turnover,
        "transaction_cost": cost,
        "net_expected_return": exp_ret - cost,
        "violations": violations,
        "feasible": feasible,
    }


def solve_qubo_exact(
    Q: np.ndarray,
    *,
    offset: float = 0.0,
    max_variables: int = 18,
) -> dict[str, Any]:
    q = np.asarray(Q, dtype=float)
    n = q.shape[0]
    if q.shape != (n, n) or n == 0:
        return {"available": False, "reason": "invalid QUBO"}
    if n > int(max_variables):
        return {"available": False, "reason": f"exact QUBO enumeration capped at {int(max_variables)} variables"}
    start = perf_counter()
    total_states = 1 << n
    best_energy = float("inf")
    best_x: np.ndarray | None = None
    chunk = 32768
    shifts = np.arange(n, dtype=np.uint64)
    for lo in range(0, total_states, chunk):
        ids = np.arange(lo, min(total_states, lo + chunk), dtype=np.uint64)
        bits = ((ids[:, None] >> shifts[None, :]) & 1).astype(float)
        e = np.einsum("bi,ij,bj->b", bits, q, bits, optimize=True) + float(offset)
        idx = int(np.argmin(e))
        if float(e[idx]) < best_energy:
            best_energy = float(e[idx])
            best_x = bits[idx].copy()
    return {
        "available": True,
        "x": best_x,
        "energy": best_energy,
        "states_evaluated": total_states,
        "runtime_ms": (perf_counter() - start) * 1000.0,
        "exact": True,
    }



def qubo_penalty_audit(
    Q: np.ndarray,
    *,
    offset: float = 0.0,
    cardinality: int,
    required_mask: np.ndarray | None = None,
    excluded_mask: np.ndarray | None = None,
    max_variables: int = 18,
) -> dict[str, Any]:
    q = np.asarray(Q, dtype=float)
    n = q.shape[0]
    if q.shape != (n, n) or n == 0:
        return {"available": False, "reason": "invalid QUBO"}
    if n > int(max_variables):
        return {"available": False, "reason": f"penalty audit capped at {int(max_variables)} variables"}
    req = np.zeros(n, dtype=bool) if required_mask is None else (np.asarray(required_mask).reshape(-1) > 0.5)
    exc = np.zeros(n, dtype=bool) if excluded_mask is None else (np.asarray(excluded_mask).reshape(-1) > 0.5)
    k = int(cardinality)
    best_feasible = float("inf")
    best_infeasible = float("inf")
    best_feasible_x = None
    best_infeasible_x = None
    feasible_count = 0
    total_states = 1 << n
    shifts = np.arange(n, dtype=np.uint64)
    for lo in range(0, total_states, 32768):
        ids = np.arange(lo, min(total_states, lo + 32768), dtype=np.uint64)
        bits = ((ids[:, None] >> shifts[None, :]) & 1).astype(float)
        energy = np.einsum("bi,ij,bj->b", bits, q, bits, optimize=True) + float(offset)
        feas = bits.sum(axis=1) == k
        if req.any(): feas &= np.all(bits[:, req] > 0.5, axis=1)
        if exc.any(): feas &= np.all(bits[:, exc] < 0.5, axis=1)
        feasible_count += int(feas.sum())
        if np.any(feas):
            loc = np.where(feas)[0]
            j = loc[int(np.argmin(energy[loc]))]
            if float(energy[j]) < best_feasible:
                best_feasible = float(energy[j]); best_feasible_x = bits[j].copy()
        if np.any(~feas):
            loc = np.where(~feas)[0]
            j = loc[int(np.argmin(energy[loc]))]
            if float(energy[j]) < best_infeasible:
                best_infeasible = float(energy[j]); best_infeasible_x = bits[j].copy()
    margin = best_infeasible - best_feasible if np.isfinite(best_feasible) and np.isfinite(best_infeasible) else float("nan")
    return {
        "available": True,
        "best_feasible_energy": best_feasible,
        "best_infeasible_energy": best_infeasible,
        "penalty_margin": margin,
        "pass": bool(np.isfinite(margin) and margin > 1e-10),
        "best_feasible_x": best_feasible_x,
        "best_infeasible_x": best_infeasible_x,
        "feasible_states": feasible_count,
        "total_states": total_states,
    }


def solve_qubo_local_search(
    Q: np.ndarray,
    *,
    offset: float = 0.0,
    restarts: int = 64,
    seed: int = 2026,
) -> dict[str, Any]:
    q = np.asarray(Q, dtype=float)
    n = q.shape[0]
    rng = np.random.default_rng(int(seed))
    start = perf_counter()
    best_e = float("inf")
    best_x = np.zeros(n, dtype=float)
    iterations = 0
    for _ in range(max(int(restarts), 1)):
        x = rng.integers(0, 2, size=n).astype(float)
        e = qubo_energy(x, q, offset)
        improved = True
        while improved:
            improved = False
            order = rng.permutation(n)
            for i in order:
                cand = x.copy(); cand[i] = 1.0 - cand[i]
                ce = qubo_energy(cand, q, offset)
                iterations += 1
                if ce < e - 1e-12:
                    x, e = cand, ce
                    improved = True
            if e < best_e:
                best_e, best_x = e, x.copy()
    return {
        "available": True,
        "x": best_x,
        "energy": best_e,
        "runtime_ms": (perf_counter() - start) * 1000.0,
        "iterations": iterations,
        "exact": False,
    }


def solve_qubo_simulated_annealing(
    Q: np.ndarray,
    *,
    offset: float = 0.0,
    sweeps: int = 250,
    restarts: int = 24,
    seed: int = 2026,
) -> dict[str, Any]:
    q = np.asarray(Q, dtype=float)
    n = q.shape[0]
    rng = np.random.default_rng(int(seed))
    start = perf_counter()
    scale = max(float(np.std(q)) * max(n, 1), 1e-4)
    best_e = float("inf")
    best_x = np.zeros(n, dtype=float)
    accepted = 0
    proposals = 0
    for _ in range(max(int(restarts), 1)):
        x = rng.integers(0, 2, size=n).astype(float)
        e = qubo_energy(x, q, offset)
        for step in range(max(int(sweeps), 2)):
            frac = step / max(int(sweeps) - 1, 1)
            temp = scale * (0.02 ** frac)
            for i in rng.permutation(n):
                cand = x.copy(); cand[i] = 1.0 - cand[i]
                ce = qubo_energy(cand, q, offset)
                de = ce - e
                proposals += 1
                if de <= 0 or rng.random() < np.exp(-de / max(temp, 1e-12)):
                    x, e = cand, ce
                    accepted += 1
                if e < best_e:
                    best_e, best_x = e, x.copy()
    return {
        "available": True,
        "x": best_x,
        "energy": best_e,
        "runtime_ms": (perf_counter() - start) * 1000.0,
        "iterations": proposals,
        "acceptance_rate": accepted / max(proposals, 1),
        "exact": False,
    }


def solve_qubo_milp(
    Q: np.ndarray,
    *,
    offset: float = 0.0,
    cardinality: int | None = None,
    required_mask: np.ndarray | None = None,
    excluded_mask: np.ndarray | None = None,
    time_limit_s: float = 5.0,
) -> dict[str, Any]:
    """Linearized binary quadratic control using scipy.optimize.milp when available."""
    try:
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import lil_matrix
    except Exception as exc:
        return {"available": False, "reason": f"scipy.milp unavailable: {exc}"}
    q = np.asarray(Q, dtype=float)
    n = q.shape[0]
    if q.shape != (n, n) or n == 0:
        return {"available": False, "reason": "invalid QUBO"}
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n) if abs(q[i, j]) > 1e-15]
    m = n + len(pairs)
    c = np.zeros(m, dtype=float)
    c[:n] = np.diag(q)
    for pos, (i, j) in enumerate(pairs):
        c[n + pos] = 2.0 * q[i, j]

    rows = []
    lbs = []
    ubs = []
    # y_ij <= x_i; y_ij <= x_j; y_ij >= x_i + x_j - 1
    A = lil_matrix((3 * len(pairs) + (1 if cardinality is not None else 0), m), dtype=float)
    row = 0
    for pos, (i, j) in enumerate(pairs):
        y = n + pos
        A[row, y] = 1; A[row, i] = -1; lbs.append(-np.inf); ubs.append(0.0); row += 1
        A[row, y] = 1; A[row, j] = -1; lbs.append(-np.inf); ubs.append(0.0); row += 1
        A[row, y] = -1; A[row, i] = 1; A[row, j] = 1; lbs.append(-np.inf); ubs.append(1.0); row += 1
    if cardinality is not None:
        A[row, :n] = 1.0; lbs.append(float(cardinality)); ubs.append(float(cardinality)); row += 1
    constraints = LinearConstraint(A.tocsr(), np.asarray(lbs), np.asarray(ubs))

    lb = np.zeros(m, dtype=float); ub = np.ones(m, dtype=float)
    req = np.zeros(n, dtype=float) if required_mask is None else (np.asarray(required_mask).reshape(-1) > 0.5).astype(float)
    exc = np.zeros(n, dtype=float) if excluded_mask is None else (np.asarray(excluded_mask).reshape(-1) > 0.5).astype(float)
    for i in range(n):
        if req[i] > 0.5: lb[i] = ub[i] = 1.0
        if exc[i] > 0.5: lb[i] = ub[i] = 0.0
    start = perf_counter()
    try:
        res = milp(
            c=c,
            integrality=np.ones(m, dtype=int),
            bounds=Bounds(lb, ub),
            constraints=constraints,
            options={"time_limit": float(max(time_limit_s, 0.1))},
        )
    except Exception as exc:
        return {"available": False, "reason": f"MILP failed: {exc}"}
    runtime = (perf_counter() - start) * 1000.0
    if res.x is None:
        return {"available": False, "reason": str(res.message), "runtime_ms": runtime}
    x = np.rint(np.asarray(res.x[:n])).astype(float)
    return {
        "available": True,
        "x": x,
        "energy": qubo_energy(x, q, offset),
        "runtime_ms": runtime,
        "status": int(res.status),
        "message": str(res.message),
        "exact": bool(res.success),
    }


def _apply_qaoa_mixer(psi: np.ndarray, beta: float, n: int) -> np.ndarray:
    out = np.asarray(psi, dtype=complex).copy()
    c = np.cos(float(beta)); s = np.sin(float(beta))
    dim = len(out)
    for q in range(n):
        stride = 1 << q
        block = stride << 1
        for start in range(0, dim, block):
            a = out[start:start + stride].copy()
            b = out[start + stride:start + block].copy()
            out[start:start + stride] = c * a - 1j * s * b
            out[start + stride:start + block] = -1j * s * a + c * b
    return out


def qaoa_statevector_simulation(
    Q: np.ndarray,
    *,
    offset: float = 0.0,
    p_layers: int = 1,
    trials: int = 48,
    shots: int = 2048,
    seed: int = 2026,
    max_qubits: int = 12,
) -> dict[str, Any]:
    """Small-n classical statevector emulator for QAOA research; never a QPU result."""
    q = np.asarray(Q, dtype=float)
    n = q.shape[0]
    if q.shape != (n, n) or n == 0:
        return {"available": False, "reason": "invalid QUBO"}
    if n > int(max_qubits):
        return {"available": False, "reason": f"statevector QAOA capped at {int(max_qubits)} binary variables"}
    start = perf_counter()
    dim = 1 << n
    ids = np.arange(dim, dtype=np.uint64)
    shifts = np.arange(n, dtype=np.uint64)
    bits = ((ids[:, None] >> shifts[None, :]) & 1).astype(float)
    energies = np.einsum("bi,ij,bj->b", bits, q, bits, optimize=True) + float(offset)
    ground = float(np.min(energies))
    centered = energies - float(np.mean(energies))
    scale = max(float(np.std(centered)), float(np.ptp(centered)) / 6.0, 1e-8)
    cost = centered / scale
    rng = np.random.default_rng(int(seed))
    p = int(np.clip(p_layers, 1, 4))
    best_exp = float("inf")
    best_prob: np.ndarray | None = None
    best_params: tuple[np.ndarray, np.ndarray] | None = None
    uniform = np.ones(dim, dtype=complex) / sqrt(dim)

    candidates: list[tuple[np.ndarray, np.ndarray]] = []
    # Stable anchors plus deterministic random search.
    for g in np.linspace(0.15, 2.8, 5):
        for b in np.linspace(0.12, 1.35, 4):
            candidates.append((np.full(p, g), np.full(p, b)))
    for _ in range(max(int(trials), 1)):
        candidates.append((rng.uniform(0.0, 2.0 * pi, size=p), rng.uniform(0.0, 0.5 * pi, size=p)))

    for gammas, betas in candidates:
        psi = uniform.copy()
        for layer in range(p):
            psi *= np.exp(-1j * float(gammas[layer]) * cost)
            psi = _apply_qaoa_mixer(psi, float(betas[layer]), n)
        probs = np.abs(psi) ** 2
        probs /= max(float(probs.sum()), _EPS)
        exp_e = float(probs @ energies)
        if exp_e < best_exp:
            best_exp = exp_e
            best_prob = probs.copy()
            best_params = (gammas.copy(), betas.copy())

    assert best_prob is not None and best_params is not None
    ground_mask = np.isclose(energies, ground, atol=1e-10, rtol=1e-9)
    ground_prob = float(best_prob[ground_mask].sum())
    draw = rng.choice(dim, size=max(int(shots), 1), p=best_prob)
    counts = np.bincount(draw, minlength=dim)
    best_sample_id = int(np.min(np.where(counts > 0, energies, np.inf).argmin())) if np.any(counts > 0) else int(np.argmin(energies))
    # Correct best sample selection explicitly.
    observed = np.where(counts > 0)[0]
    if len(observed):
        best_sample_id = int(observed[np.argmin(energies[observed])])
    top = np.argsort(best_prob)[::-1][: min(16, dim)]
    distribution = pd.DataFrame({
        "state": [format(int(i), f"0{n}b")[::-1] for i in top],
        "probability": best_prob[top],
        "energy": energies[top],
        "shots": counts[top],
    })
    return {
        "available": True,
        "execution": "CLASSICAL STATEVECTOR EMULATOR",
        "x": bits[best_sample_id].copy(),
        "best_sample_energy": float(energies[best_sample_id]),
        "expected_energy": best_exp,
        "ground_energy": ground,
        "ground_probability": ground_prob,
        "expected_gap": best_exp - ground,
        "best_sample_gap": float(energies[best_sample_id] - ground),
        "gammas": best_params[0],
        "betas": best_params[1],
        "p_layers": p,
        "shots": int(shots),
        "distribution": distribution,
        "runtime_ms": (perf_counter() - start) * 1000.0,
        "statevector_dimension": dim,
        "exact": False,
    }


def qubo_solver_arena(
    compiled: dict[str, Any],
    mu: np.ndarray,
    cov: np.ndarray,
    *,
    labels: list[str],
    qaoa_layers: int = 1,
    qaoa_trials: int = 48,
    qaoa_shots: int = 2048,
    heuristic_seed: int = 2026,
) -> dict[str, Any]:
    Q = np.asarray(compiled["Q"], dtype=float)
    offset = float(compiled.get("offset", 0.0))
    k = int(compiled["cardinality"])
    req = compiled.get("required_mask")
    exc = compiled.get("excluded_mask")
    prev = compiled.get("previous_x")
    tcbps = float(compiled.get("transaction_cost_bps", 0.0))

    # MILP receives the economic objective with hard constraints explicitly enforced.
    # Penalty terms are identically zero on feasible states and can create severe
    # coefficient cancellation / MIP scaling if redundantly left in the solver objective.
    econ_q = np.zeros_like(Q)
    econ_offset = 0.0
    for _name, _part in compiled.get("components", {}).items():
        if _name in {"Cardinality", "Required / Excluded"}:
            continue
        econ_q += np.asarray(_part, dtype=float)
        econ_offset += float(compiled.get("component_offsets", {}).get(_name, 0.0))
    milp_control = solve_qubo_milp(econ_q, offset=econ_offset, cardinality=k, required_mask=req, excluded_mask=exc)
    if milp_control.get("available"):
        milp_control["economic_energy"] = float(milp_control.get("energy", np.nan))
        milp_control["energy"] = qubo_energy(milp_control["x"], Q, offset)

    raw: dict[str, dict[str, Any]] = {
        "Exact QUBO": solve_qubo_exact(Q, offset=offset),
        "MILP · hard constraints": milp_control,
        "Simulated Annealing": solve_qubo_simulated_annealing(Q, offset=offset, seed=heuristic_seed),
        "Local Search": solve_qubo_local_search(Q, offset=offset, seed=heuristic_seed + 17),
        "QAOA · statevector": qaoa_statevector_simulation(Q, offset=offset, p_layers=qaoa_layers, trials=qaoa_trials, shots=qaoa_shots, seed=heuristic_seed + 31),
    }
    exact_energy = float(raw["Exact QUBO"].get("energy", np.nan)) if raw["Exact QUBO"].get("available") else float("nan")
    rows: list[dict[str, Any]] = []
    for method, res in raw.items():
        if not res.get("available"):
            rows.append({"Method": method, "Available": False, "Status": res.get("reason", "unavailable")})
            continue
        metrics = portfolio_solution_metrics(
            res["x"], mu, cov, labels=labels, previous_x=prev,
            transaction_cost_bps=tcbps, required_mask=req, excluded_mask=exc, cardinality=k,
        )
        energy = float(res.get("energy", res.get("best_sample_energy", np.nan)))
        gap = energy - exact_energy if np.isfinite(exact_energy) and np.isfinite(energy) else float("nan")
        rows.append({
            "Method": method,
            "Available": True,
            "Energy": energy,
            "Gap vs Exact": gap,
            "Feasible": metrics["feasible"],
            "Selected": ", ".join(metrics["selected"]),
            "Expected Return": metrics["expected_return"],
            "Volatility": metrics["volatility"],
            "Sharpe": metrics["sharpe"],
            "Turnover": metrics["turnover"],
            "Net Expected Return": metrics["net_expected_return"],
            "Runtime ms": float(res.get("runtime_ms", np.nan)),
            "Iterations / States": int(res.get("states_evaluated", res.get("iterations", res.get("shots", 0))) or 0),
            "Ground Probability": float(res.get("ground_probability", np.nan)),
        })
        res["metrics"] = metrics
    return {"table": pd.DataFrame(rows), "results": raw, "exact_energy": exact_energy}


def qubo_complexity_profile(n_assets: int, cardinality: int, exact_runtime_ms: float | None = None) -> dict[str, Any]:
    n = int(max(n_assets, 0)); k = int(np.clip(cardinality, 0, max(n, 0))) if n else 0
    unconstrained = int(2 ** n) if n < 63 else float("inf")
    feasible = int(comb(n, k)) if n and 0 <= k <= n else 0
    if feasible <= 1_000:
        scale = "TRIVIAL"
    elif feasible <= 100_000:
        scale = "SMALL"
    elif feasible <= 10_000_000:
        scale = "RESEARCH-SCALE"
    else:
        scale = "LARGE"
    runtime = float(exact_runtime_ms) if exact_runtime_ms is not None and np.isfinite(exact_runtime_ms) else float("nan")
    if feasible <= 100_000 or (np.isfinite(runtime) and runtime < 1_000.0):
        eligibility = "NOT ELIGIBLE"
        rationale = "credible classical exact control remains too cheap"
    elif feasible <= 10_000_000:
        eligibility = "EXPLORATORY"
        rationale = "combinatorics are material; classical heuristics remain mandatory controls"
    else:
        eligibility = "BENCHMARK CANDIDATE"
        rationale = "exact enumeration is structurally difficult; no quantum advantage is implied"
    return {
        "n_assets": n,
        "cardinality": k,
        "unconstrained_states": unconstrained,
        "feasible_states": feasible,
        "scale": scale,
        "quantum_research_eligibility": eligibility,
        "rationale": rationale,
    }


# ============================================================================
# QUBO / ISING PORTFOLIO ENGINE V2.4.1
# Constraint-preserving QAOA, hard-constraint presolve, penalty frontier,
# and empirical classical-hardness controls.
# ============================================================================

def _reduce_qubo_with_fixed_bits(
    Q: np.ndarray,
    offset: float,
    free_idx: np.ndarray,
    fixed_idx: np.ndarray,
    fixed_values: np.ndarray,
) -> tuple[np.ndarray, float]:
    """Substitute fixed binary variables into x'Qx + offset exactly."""
    q = np.asarray(Q, dtype=float)
    free_idx = np.asarray(free_idx, dtype=int)
    fixed_idx = np.asarray(fixed_idx, dtype=int)
    fixed_values = np.asarray(fixed_values, dtype=float).reshape(-1)
    if len(fixed_idx) != len(fixed_values):
        raise ValueError("fixed index/value mismatch")
    qff = q[np.ix_(free_idx, free_idx)].copy()
    new_offset = float(offset)
    if len(fixed_idx):
        qfc = q[np.ix_(free_idx, fixed_idx)]
        qcc = q[np.ix_(fixed_idx, fixed_idx)]
        linear = 2.0 * (qfc @ fixed_values)
        qff[np.diag_indices(len(free_idx))] += linear
        new_offset += float(fixed_values @ qcc @ fixed_values)
    return (qff + qff.T) / 2.0, new_offset


def presolve_portfolio_qubo(compiled: dict[str, Any], labels: list[str] | None = None) -> dict[str, Any]:
    """Fix required/excluded bits before quantum optimization and reduce the QUBO exactly.

    Required assets are fixed to 1 and excluded assets to 0.  This removes known
    business-rule bits from the Hilbert space rather than asking a penalty Hamiltonian
    to rediscover them.  Cardinality is reduced to K_free = K - #required.
    """
    Q = np.asarray(compiled["Q"], dtype=float)
    n = Q.shape[0]
    req = (np.asarray(compiled.get("required_mask", np.zeros(n))).reshape(-1) > 0.5)
    exc = (np.asarray(compiled.get("excluded_mask", np.zeros(n))).reshape(-1) > 0.5)
    if np.any(req & exc):
        raise ValueError("required/excluded conflict")
    fixed_mask = req | exc
    free_idx = np.where(~fixed_mask)[0]
    fixed_idx = np.where(fixed_mask)[0]
    fixed_values = req[fixed_idx].astype(float)
    k_full = int(compiled["cardinality"])
    k_free = k_full - int(req.sum())
    if k_free < 0 or k_free > len(free_idx):
        return {"available": False, "reason": "hard constraints are incompatible with cardinality"}

    reduced_q, reduced_offset = _reduce_qubo_with_fixed_bits(
        Q, float(compiled.get("offset", 0.0)), free_idx, fixed_idx, fixed_values
    )
    component_q: dict[str, np.ndarray] = {}
    component_offsets: dict[str, float] = {}
    for name, qpart in compiled.get("components", {}).items():
        rq, ro = _reduce_qubo_with_fixed_bits(
            np.asarray(qpart, dtype=float),
            float(compiled.get("component_offsets", {}).get(name, 0.0)),
            free_idx,
            fixed_idx,
            fixed_values,
        )
        component_q[name] = rq
        component_offsets[name] = ro

    economic_names = [name for name in component_q if name not in {"Cardinality", "Required / Excluded"}]
    economic_q = np.zeros_like(reduced_q)
    economic_offset = 0.0
    for name in economic_names:
        economic_q += component_q[name]
        economic_offset += component_offsets[name]
    economic_q = (economic_q + economic_q.T) / 2.0

    names = labels or [f"A{i+1}" for i in range(n)]
    prev_full = np.asarray(compiled.get("previous_x", np.zeros(n)), dtype=float).reshape(-1)
    return {
        "available": True,
        "Q": reduced_q,
        "offset": float(reduced_offset),
        "economic_Q": economic_q,
        "economic_offset": float(economic_offset),
        "components": component_q,
        "component_offsets": component_offsets,
        "free_idx": free_idx,
        "fixed_idx": fixed_idx,
        "fixed_values": fixed_values,
        "free_labels": [names[i] for i in free_idx],
        "fixed_labels": {names[i]: int(req[i]) for i in fixed_idx},
        "cardinality_full": k_full,
        "cardinality_free": int(k_free),
        "full_size": n,
        "reduced_size": len(free_idx),
        "previous_x_free": prev_full[free_idx] if len(prev_full) == n else np.zeros(len(free_idx)),
    }


def lift_presolved_solution(x_free: np.ndarray, presolved: dict[str, Any]) -> np.ndarray:
    if not presolved.get("available"):
        raise ValueError("presolved problem unavailable")
    x_free = (np.asarray(x_free, dtype=float).reshape(-1) > 0.5).astype(float)
    if len(x_free) != int(presolved["reduced_size"]):
        raise ValueError("reduced solution size mismatch")
    full = np.zeros(int(presolved["full_size"]), dtype=float)
    full[np.asarray(presolved["free_idx"], dtype=int)] = x_free
    if len(presolved["fixed_idx"]):
        full[np.asarray(presolved["fixed_idx"], dtype=int)] = np.asarray(presolved["fixed_values"], dtype=float)
    return full


def qubo_coefficient_diagnostics(Q: np.ndarray) -> dict[str, float]:
    q = np.asarray(Q, dtype=float)
    vals = np.abs(q[np.abs(q) > 1e-14])
    if vals.size == 0:
        return {"max_abs": 0.0, "min_abs": 0.0, "dynamic_range": 1.0, "frobenius": 0.0}
    return {
        "max_abs": float(vals.max()),
        "min_abs": float(vals.min()),
        "dynamic_range": float(vals.max() / max(vals.min(), 1e-15)),
        "frobenius": float(np.linalg.norm(q)),
    }


def qubo_penalty_frontier(
    compiled: dict[str, Any],
    *,
    points: int = 31,
    max_variables: int = 18,
) -> dict[str, Any]:
    """Find the minimum safe linear penalty exactly when exhaustive auditing is possible.

    Because cardinality and required/excluded penalties are linear in M and vanish on
    feasible states, the minimum M that separates every infeasible state can be derived
    from E(x;M)=F(x)+M P(x) without tuning against the QAOA output.
    """
    Q = np.asarray(compiled["Q"], dtype=float)
    n = Q.shape[0]
    current_m = float(compiled.get("constraint_penalty", 0.0))
    if n > int(max_variables):
        return {"available": False, "reason": f"penalty frontier capped at {int(max_variables)} variables"}
    if current_m <= 0:
        return {"available": False, "reason": "current penalty must be positive"}

    components = compiled.get("components", {})
    offsets = compiled.get("component_offsets", {})
    penalty_names = [x for x in ("Cardinality", "Required / Excluded") if x in components]
    financial_names = [x for x in components if x not in penalty_names]
    q_fin = np.zeros_like(Q); off_fin = 0.0
    q_unit = np.zeros_like(Q); off_unit = 0.0
    for name in financial_names:
        q_fin += np.asarray(components[name], dtype=float); off_fin += float(offsets.get(name, 0.0))
    for name in penalty_names:
        q_unit += np.asarray(components[name], dtype=float) / current_m
        off_unit += float(offsets.get(name, 0.0)) / current_m

    dim = 1 << n
    ids = np.arange(dim, dtype=np.uint64)
    shifts = np.arange(n, dtype=np.uint64)
    bits = ((ids[:, None] >> shifts[None, :]) & 1).astype(float)
    f_energy = np.einsum("bi,ij,bj->b", bits, q_fin, bits, optimize=True) + off_fin
    p_energy = np.einsum("bi,ij,bj->b", bits, q_unit, bits, optimize=True) + off_unit
    req = (np.asarray(compiled.get("required_mask", np.zeros(n))).reshape(-1) > 0.5)
    exc = (np.asarray(compiled.get("excluded_mask", np.zeros(n))).reshape(-1) > 0.5)
    k = int(compiled["cardinality"])
    feasible = bits.sum(axis=1) == k
    if req.any(): feasible &= np.all(bits[:, req] > 0.5, axis=1)
    if exc.any(): feasible &= np.all(bits[:, exc] < 0.5, axis=1)
    if not np.any(feasible):
        return {"available": False, "reason": "no feasible states"}
    best_feasible_fin = float(np.min(f_energy[feasible]))
    infeas = ~feasible
    p_bad = p_energy[infeas]
    f_bad = f_energy[infeas]
    valid = p_bad > 1e-12
    if np.any(valid):
        thresholds = (best_feasible_fin - f_bad[valid]) / p_bad[valid]
        min_safe = float(max(0.0, np.max(thresholds)))
    else:
        min_safe = 0.0
    # Strict separation rather than equality at the limiting state.
    strict_safe = max(min_safe * (1.0 + 1e-8), min_safe + 1e-10)
    recommended = max(strict_safe * 1.10, 1e-8)

    lo = max(min(recommended, current_m, 1.0) / 50.0, 1e-6)
    hi = max(current_m * 2.0, recommended * 5.0, lo * 10.0)
    m_grid = np.unique(np.concatenate([
        np.geomspace(lo, hi, max(int(points), 8)),
        np.array([strict_safe, recommended, current_m]),
    ]))
    rows = []
    for m in np.sort(m_grid):
        total = f_energy + float(m) * p_energy
        bf = float(np.min(total[feasible]))
        bi = float(np.min(total[infeas])) if np.any(infeas) else float("inf")
        margin = bi - bf
        q_m = q_fin + float(m) * q_unit
        diag = qubo_coefficient_diagnostics(q_m)
        rows.append({
            "Penalty M": float(m),
            "Ground feasible": bool(margin > 1e-10),
            "Penalty margin": float(margin),
            "Q dynamic range": float(diag["dynamic_range"]),
            "Q max abs": float(diag["max_abs"]),
        })
    financial_norm = float(np.linalg.norm(q_fin))
    penalty_norm = float(np.linalg.norm(current_m * q_unit))
    return {
        "available": True,
        "minimum_safe_penalty": strict_safe,
        "recommended_penalty": recommended,
        "current_penalty": current_m,
        "safety_multiple": current_m / max(strict_safe, 1e-12),
        "financial_norm": financial_norm,
        "current_penalty_norm": penalty_norm,
        "penalty_to_financial_norm": penalty_norm / max(financial_norm, 1e-12),
        "frontier": pd.DataFrame(rows),
        "feasible_states": int(feasible.sum()),
        "total_states": dim,
    }


def _bit_matrix(n: int) -> np.ndarray:
    dim = 1 << int(n)
    ids = np.arange(dim, dtype=np.uint64)
    shifts = np.arange(int(n), dtype=np.uint64)
    return ((ids[:, None] >> shifts[None, :]) & 1).astype(float)


def _apply_xy_pair_mixer(psi: np.ndarray, beta: float, n: int, i: int, j: int) -> np.ndarray:
    """Apply exp[-i beta (XX+YY)/2] on a qubit pair; Hamming weight is preserved."""
    if i == j:
        return np.asarray(psi, dtype=complex).copy()
    out = np.asarray(psi, dtype=complex).copy()
    ids = np.arange(len(out), dtype=np.uint64)
    bi = ((ids >> np.uint64(i)) & 1)
    bj = ((ids >> np.uint64(j)) & 1)
    left = ids[(bi == 0) & (bj == 1)]
    partner = left ^ (np.uint64(1) << np.uint64(i)) ^ (np.uint64(1) << np.uint64(j))
    a = out[left].copy(); b = out[partner].copy()
    c = np.cos(float(beta)); s = np.sin(float(beta))
    out[left] = c * a - 1j * s * b
    out[partner] = c * b - 1j * s * a
    return out


def _apply_xy_ring_mixer(psi: np.ndarray, beta: float, n: int) -> np.ndarray:
    out = np.asarray(psi, dtype=complex).copy()
    if n <= 1:
        return out
    pairs = [(i, i + 1) for i in range(n - 1)]
    if n > 2:
        pairs.append((n - 1, 0))
    for i, j in pairs:
        out = _apply_xy_pair_mixer(out, beta, n, i, j)
    return out


def qaoa_statevector_diagnostics(
    Q: np.ndarray,
    *,
    offset: float = 0.0,
    evaluation_Q: np.ndarray | None = None,
    evaluation_offset: float | None = None,
    p_layers: int = 1,
    trials: int = 48,
    shots: int = 2048,
    seed: int = 2026,
    mixer: str = "X",
    hamming_weight: int | None = None,
    max_qubits: int = 12,
) -> dict[str, Any]:
    """Small-n QAOA diagnostics with either X mixer or Hamming-weight-preserving XY mixer."""
    q = np.asarray(Q, dtype=float)
    n = q.shape[0]
    if q.shape != (n, n) or n == 0:
        return {"available": False, "reason": "invalid QUBO"}
    if n > int(max_qubits):
        return {"available": False, "reason": f"statevector QAOA capped at {int(max_qubits)} free binary variables"}
    p = int(np.clip(p_layers, 1, 4))
    mode = str(mixer).strip().upper()
    if mode not in {"X", "XY"}:
        raise ValueError("mixer must be X or XY")
    bits = _bit_matrix(n)
    dim = len(bits)
    cost_energy = np.einsum("bi,ij,bj->b", bits, q, bits, optimize=True) + float(offset)
    eq = q if evaluation_Q is None else np.asarray(evaluation_Q, dtype=float)
    eo = float(offset if evaluation_offset is None else evaluation_offset)
    eval_energy = np.einsum("bi,ij,bj->b", bits, eq, bits, optimize=True) + eo
    if hamming_weight is None:
        feasible = np.ones(dim, dtype=bool)
    else:
        feasible = bits.sum(axis=1) == int(hamming_weight)
    if not np.any(feasible):
        return {"available": False, "reason": "empty feasible Hamming-weight subspace"}
    feasible_ground = float(np.min(eval_energy[feasible]))
    ground_mask = feasible & np.isclose(eval_energy, feasible_ground, atol=1e-10, rtol=1e-9)

    support = feasible if mode == "XY" else np.ones(dim, dtype=bool)
    center = float(np.mean(cost_energy[support]))
    centered = cost_energy - center
    scale = max(float(np.std(centered[support])), float(np.ptp(centered[support])) / 6.0, 1e-8)
    scaled_cost = centered / scale
    if mode == "XY":
        psi0 = np.zeros(dim, dtype=complex)
        psi0[feasible] = 1.0 / sqrt(float(feasible.sum()))
    else:
        psi0 = np.ones(dim, dtype=complex) / sqrt(dim)

    rng = np.random.default_rng(int(seed))
    candidates: list[tuple[np.ndarray, np.ndarray]] = []
    for g in np.linspace(0.15, 2.8, 5):
        for b in np.linspace(0.12, 1.35, 4):
            candidates.append((np.full(p, g), np.full(p, b)))
    for _ in range(max(int(trials), 1)):
        candidates.append((rng.uniform(0.0, 2.0 * pi, size=p), rng.uniform(0.0, 0.5 * pi, size=p)))

    start = perf_counter()
    best_exp_cost = float("inf")
    best_prob = None; best_params = None
    for gammas, betas in candidates:
        psi = psi0.copy()
        for layer in range(p):
            psi *= np.exp(-1j * float(gammas[layer]) * scaled_cost)
            if mode == "XY":
                psi = _apply_xy_ring_mixer(psi, float(betas[layer]), n)
            else:
                psi = _apply_qaoa_mixer(psi, float(betas[layer]), n)
        probs = np.abs(psi) ** 2
        probs /= max(float(probs.sum()), _EPS)
        exp_cost = float(probs @ cost_energy)
        if exp_cost < best_exp_cost:
            best_exp_cost = exp_cost; best_prob = probs.copy(); best_params = (gammas.copy(), betas.copy())
    assert best_prob is not None and best_params is not None

    feasible_mass = float(best_prob[feasible].sum())
    ground_probability = float(best_prob[ground_mask].sum())
    if feasible_mass > _EPS:
        conditional_expected = float(best_prob[feasible] @ eval_energy[feasible] / feasible_mass)
        conditional_gap = conditional_expected - feasible_ground
    else:
        conditional_expected = float("nan"); conditional_gap = float("nan")
    expected_eval = float(best_prob @ eval_energy)

    draw = rng.choice(dim, size=max(int(shots), 1), p=best_prob)
    counts = np.bincount(draw, minlength=dim)
    observed_feasible = np.where((counts > 0) & feasible)[0]
    if len(observed_feasible):
        best_sample_id = int(observed_feasible[np.argmin(eval_energy[observed_feasible])])
    else:
        observed = np.where(counts > 0)[0]
        best_sample_id = int(observed[np.argmin(eval_energy[observed])]) if len(observed) else int(np.argmin(eval_energy))

    top = np.argsort(best_prob)[::-1][: min(14, dim)]
    distribution = pd.DataFrame({
        "state": [format(int(i), f"0{n}b")[::-1] for i in top],
        "probability": best_prob[top],
        "cost_energy": cost_energy[top],
        "economic_energy": eval_energy[top],
        "feasible": feasible[top],
        "ground": ground_mask[top],
        "shots": counts[top],
    })

    def shots_needed(prob: float, confidence: float) -> float:
        if prob <= 0: return float("inf")
        if prob >= 1: return 1.0
        return float(np.ceil(np.log(1.0 - confidence) / np.log(1.0 - prob)))

    return {
        "available": True,
        "execution": "CLASSICAL STATEVECTOR EMULATOR",
        "mixer": mode,
        "initial_state": "DICKE / FIXED-HAMMING-WEIGHT" if mode == "XY" else "UNIFORM |+>",
        "x": bits[best_sample_id].copy(),
        "best_sample_economic_energy": float(eval_energy[best_sample_id]),
        "best_sample_feasible": bool(feasible[best_sample_id]),
        "expected_cost_energy": best_exp_cost,
        "expected_economic_energy": expected_eval,
        "feasible_ground_energy": feasible_ground,
        "ground_probability": ground_probability,
        "feasible_probability": feasible_mass,
        "conditional_expected_energy": conditional_expected,
        "conditional_expected_gap": conditional_gap,
        "shots_to_50": shots_needed(ground_probability, 0.50),
        "shots_to_95": shots_needed(ground_probability, 0.95),
        "shots_to_99": shots_needed(ground_probability, 0.99),
        "gammas": best_params[0],
        "betas": best_params[1],
        "p_layers": p,
        "shots": int(shots),
        "distribution": distribution,
        "runtime_ms": (perf_counter() - start) * 1000.0,
        "statevector_dimension": dim,
        "feasible_dimension": int(feasible.sum()),
        "probabilities": best_prob,
        "bits": bits,
        "evaluation_energies": eval_energy,
        "feasible_mask": feasible,
        "ground_mask": ground_mask,
    }


def constraint_preserving_qaoa_study(
    compiled: dict[str, Any],
    *,
    labels: list[str],
    max_depth: int = 3,
    trials: int = 48,
    shots: int = 2048,
    starts: int = 3,
    seed: int = 2026,
) -> dict[str, Any]:
    """Compare penalty/X-mixer QAOA with presolved Dicke+XY QAOA on the same economic objective."""
    pre = presolve_portfolio_qubo(compiled, labels)
    if not pre.get("available"):
        return {"available": False, "reason": pre.get("reason", "presolve unavailable")}
    n = int(pre["reduced_size"]); k = int(pre["cardinality_free"])
    if n == 0:
        return {"available": False, "reason": "all variables fixed by hard constraints"}
    if n > 12:
        return {"available": False, "reason": "constraint-preserving statevector study capped at 12 free variables", "presolved": pre}

    rows = []; runs: dict[tuple[str, int], dict[str, Any]] = {}
    start_rows = []
    for p in range(1, int(np.clip(max_depth, 1, 3)) + 1):
        for mixer in ("X", "XY"):
            candidates = []
            for s in range(max(int(starts), 1)):
                if mixer == "X":
                    res = qaoa_statevector_diagnostics(
                        pre["Q"], offset=pre["offset"],
                        evaluation_Q=pre["economic_Q"], evaluation_offset=pre["economic_offset"],
                        p_layers=p, trials=trials, shots=shots, seed=seed + 100*p + 17*s,
                        mixer="X", hamming_weight=k,
                    )
                else:
                    res = qaoa_statevector_diagnostics(
                        pre["economic_Q"], offset=pre["economic_offset"],
                        evaluation_Q=pre["economic_Q"], evaluation_offset=pre["economic_offset"],
                        p_layers=p, trials=trials, shots=shots, seed=seed + 1000 + 100*p + 17*s,
                        mixer="XY", hamming_weight=k,
                    )
                if res.get("available"):
                    candidates.append(res)
                    start_rows.append({
                        "Mixer": mixer, "Depth p": p, "Start": s + 1,
                        "Ground Probability": res["ground_probability"],
                        "Feasible Mass": res["feasible_probability"],
                        "Conditional Gap": res["conditional_expected_gap"],
                    })
            if not candidates:
                continue
            # Select the optimizer run by minimum expected cost, preserving the actual QAOA objective.
            best = min(candidates, key=lambda r: float(r["expected_cost_energy"]))
            runs[(mixer, p)] = best
            gp = np.array([r["ground_probability"] for r in candidates], dtype=float)
            fm = np.array([r["feasible_probability"] for r in candidates], dtype=float)
            rows.append({
                "Mixer": "Penalty X" if mixer == "X" else "Dicke + XY",
                "Depth p": p,
                "Free qubits": n,
                "Feasible dimension": int(best["feasible_dimension"]),
                "Ground Probability": best["ground_probability"],
                "Feasible Mass": best["feasible_probability"],
                "Conditional Expected Gap": best["conditional_expected_gap"],
                "Shots to 95%": best["shots_to_95"],
                "Shots to 99%": best["shots_to_99"],
                "Best Sample Feasible": best["best_sample_feasible"],
                "Ground P mean across starts": float(gp.mean()),
                "Ground P std across starts": float(gp.std(ddof=0)),
                "Feasible P mean across starts": float(fm.mean()),
                "Runtime ms": best["runtime_ms"],
            })
    table = pd.DataFrame(rows)
    if table.empty:
        return {"available": False, "reason": "no QAOA study results", "presolved": pre}
    return {
        "available": True,
        "presolved": pre,
        "table": table,
        "runs": runs,
        "start_stability": pd.DataFrame(start_rows),
        "uniform_full_ground_baseline": 1.0 / float(2 ** n),
        "uniform_feasible_ground_baseline": 1.0 / float(max(comb(n, k), 1)),
    }


def qaoa_p1_landscape(
    Q: np.ndarray,
    *,
    offset: float = 0.0,
    evaluation_Q: np.ndarray | None = None,
    evaluation_offset: float | None = None,
    mixer: str = "XY",
    hamming_weight: int | None = None,
    gamma_points: int = 25,
    beta_points: int = 21,
    max_qubits: int = 10,
) -> dict[str, Any]:
    q = np.asarray(Q, dtype=float); n = q.shape[0]
    if n > int(max_qubits):
        return {"available": False, "reason": f"landscape capped at {int(max_qubits)} qubits"}
    bits = _bit_matrix(n); dim = len(bits)
    cost_e = np.einsum("bi,ij,bj->b", bits, q, bits, optimize=True) + float(offset)
    eq = q if evaluation_Q is None else np.asarray(evaluation_Q, dtype=float)
    eo = float(offset if evaluation_offset is None else evaluation_offset)
    eval_e = np.einsum("bi,ij,bj->b", bits, eq, bits, optimize=True) + eo
    feasible = np.ones(dim, dtype=bool) if hamming_weight is None else bits.sum(axis=1) == int(hamming_weight)
    if not np.any(feasible): return {"available": False, "reason": "empty feasible subspace"}
    mode = str(mixer).upper()
    support = feasible if mode == "XY" else np.ones(dim, dtype=bool)
    centered = cost_e - float(np.mean(cost_e[support]))
    scale = max(float(np.std(centered[support])), float(np.ptp(centered[support])) / 6.0, 1e-8)
    cscaled = centered / scale
    if mode == "XY":
        psi0 = np.zeros(dim, dtype=complex); psi0[feasible] = 1.0 / sqrt(float(feasible.sum()))
    else:
        psi0 = np.ones(dim, dtype=complex) / sqrt(dim)
    ground = float(np.min(eval_e[feasible])); gmask = feasible & np.isclose(eval_e, ground, atol=1e-10, rtol=1e-9)
    gammas = np.linspace(0.0, 2.0*pi, max(int(gamma_points), 5))
    betas = np.linspace(0.0, 0.5*pi, max(int(beta_points), 5))
    gap = np.zeros((len(betas), len(gammas)), dtype=float)
    gp = np.zeros_like(gap)
    for ib, beta in enumerate(betas):
        for ig, gamma in enumerate(gammas):
            psi = psi0 * np.exp(-1j * gamma * cscaled)
            psi = _apply_xy_ring_mixer(psi, beta, n) if mode == "XY" else _apply_qaoa_mixer(psi, beta, n)
            probs = np.abs(psi)**2; probs /= max(float(probs.sum()), _EPS)
            fm = float(probs[feasible].sum())
            cond = float(probs[feasible] @ eval_e[feasible] / max(fm, _EPS))
            gap[ib, ig] = cond - ground
            gp[ib, ig] = float(probs[gmask].sum())
    return {"available": True, "gammas": gammas, "betas": betas, "conditional_gap": gap, "ground_probability": gp, "mixer": mode}


def _solve_fixed_cardinality_exact_q(Q: np.ndarray, k: int, offset: float = 0.0, max_states: int = 1_500_000) -> dict[str, Any]:
    q = np.asarray(Q, dtype=float); n = q.shape[0]; states = comb(n, int(k))
    if states > int(max_states):
        return {"available": False, "reason": "exact feasible enumeration cap", "states": int(states)}
    start = perf_counter(); best_e = float("inf"); best_x = None
    for idx in combinations(range(n), int(k)):
        x = np.zeros(n, dtype=float); x[list(idx)] = 1.0
        e = qubo_energy(x, q, offset)
        if e < best_e: best_e = e; best_x = x
    return {"available": True, "x": best_x, "energy": best_e, "states": int(states), "runtime_ms": (perf_counter()-start)*1000.0}


def _solve_swap_local_search(Q: np.ndarray, k: int, offset: float = 0.0, restarts: int = 24, seed: int = 2026) -> dict[str, Any]:
    q = np.asarray(Q, dtype=float); n = q.shape[0]; rng = np.random.default_rng(seed); start = perf_counter()
    best_e = float("inf"); best_x = None; iters = 0
    for _ in range(max(int(restarts), 1)):
        x = np.zeros(n, dtype=float); x[rng.choice(n, size=int(k), replace=False)] = 1.0
        e = qubo_energy(x, q, offset); improved = True
        while improved:
            improved = False; ones = np.where(x>0.5)[0]; zeros = np.where(x<0.5)[0]
            pairs = [(int(i), int(j)) for i in rng.permutation(ones) for j in rng.permutation(zeros)]
            for i,j in pairs:
                cand=x.copy(); cand[i]=0.0; cand[j]=1.0; ce=qubo_energy(cand,q,offset); iters+=1
                if ce < e-1e-12: x,e=cand,ce; improved=True; break
            if e < best_e: best_e=e; best_x=x.copy()
    return {"available": True, "x": best_x, "energy": best_e, "runtime_ms": (perf_counter()-start)*1000.0, "iterations": iters}


def _solve_swap_annealing(Q: np.ndarray, k: int, offset: float = 0.0, sweeps: int = 120, restarts: int = 8, seed: int = 2026) -> dict[str, Any]:
    q=np.asarray(Q,dtype=float); n=q.shape[0]; rng=np.random.default_rng(seed); start=perf_counter(); best_e=float("inf"); best_x=None; props=0
    scale=max(float(np.std(q))*max(n,1),1e-4)
    for _ in range(max(int(restarts),1)):
        x=np.zeros(n,dtype=float); x[rng.choice(n,size=int(k),replace=False)]=1.0; e=qubo_energy(x,q,offset)
        for s in range(max(int(sweeps),2)):
            temp=scale*(0.02**(s/max(int(sweeps)-1,1)))
            for _ in range(max(n,1)):
                ones=np.where(x>0.5)[0]; zeros=np.where(x<0.5)[0]
                i=int(rng.choice(ones)); j=int(rng.choice(zeros)); cand=x.copy(); cand[i]=0; cand[j]=1; ce=qubo_energy(cand,q,offset); props+=1
                if ce<=e or rng.random()<np.exp(-(ce-e)/max(temp,1e-12)):
                    x,e=cand,ce
                if e<best_e: best_e=e; best_x=x.copy()
    return {"available": True, "x":best_x,"energy":best_e,"runtime_ms":(perf_counter()-start)*1000.0,"iterations":props}


def _synthetic_portfolio_moments(base_mu: np.ndarray, base_cov: np.ndarray, n: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    base_mu=np.asarray(base_mu,dtype=float); base_cov=np.asarray(base_cov,dtype=float)
    m=float(np.mean(base_mu)); s=float(max(np.std(base_mu),0.02)); mu=rng.normal(m,s,size=int(n))
    base_vol=np.sqrt(np.clip(np.diag(base_cov),1e-8,None)); vols=rng.choice(base_vol,size=int(n),replace=True)*rng.uniform(0.85,1.15,size=int(n))
    rank=min(4,int(n)); F=rng.normal(size=(int(n),rank)); gram=F@F.T; d=np.sqrt(np.clip(np.diag(gram),1e-12,None)); corr=gram/np.outer(d,d)
    corr=0.55*corr+0.45*np.eye(int(n)); cov=corr*np.outer(vols,vols); cov=(cov+cov.T)/2.0
    return mu,cov


def classical_hardness_benchmark(
    base_mu: np.ndarray,
    base_cov: np.ndarray,
    *,
    cardinality_ratio: float = 0.5,
    risk_aversion: float = 5.0,
    n_grid: Iterable[int] = (6, 8, 10, 12, 14, 16, 18),
    instances: int = 2,
    seed: int = 2026,
) -> dict[str, Any]:
    """Empirical classical scaling suite on synthetic instances calibrated to current moments."""
    rng=np.random.default_rng(int(seed)); rows=[]
    for n in [int(x) for x in n_grid]:
        k=max(1,min(n-1,int(round(float(cardinality_ratio)*n))))
        for inst in range(max(int(instances),1)):
            mu,cov=_synthetic_portfolio_moments(base_mu,base_cov,n,rng)
            # Economic Q only: cardinality is handled as a hard feasibility rule.
            q=(float(risk_aversion)/(k*k))*cov
            q=(q+q.T)/2.0; q[np.diag_indices(n)] += -mu/k
            exact=_solve_fixed_cardinality_exact_q(q,k)
            milp=solve_qubo_milp(q,offset=0.0,cardinality=k,time_limit_s=2.0)
            sa=_solve_swap_annealing(q,k,seed=seed+n*37+inst)
            ls=_solve_swap_local_search(q,k,seed=seed+n*53+inst)
            exact_e=float(exact.get("energy",np.nan)) if exact.get("available") else float("nan")
            def gap(res):
                e=float(res.get("energy",np.nan)); return e-exact_e if np.isfinite(e) and np.isfinite(exact_e) else float("nan")
            rows.append({
                "N":n,"K":k,"Instance":inst+1,"Feasible states":int(comb(n,k)),
                "Exact available":bool(exact.get("available")),"Exact runtime ms":float(exact.get("runtime_ms",np.nan)),
                "MILP runtime ms":float(milp.get("runtime_ms",np.nan)),"MILP gap":gap(milp),"MILP solved":bool(milp.get("available")),
                "SA runtime ms":float(sa.get("runtime_ms",np.nan)),"SA gap":gap(sa),
                "Local runtime ms":float(ls.get("runtime_ms",np.nan)),"Local gap":gap(ls),
            })
    detail=pd.DataFrame(rows)
    if detail.empty: return {"available":False,"reason":"no hardness results"}
    summary=detail.groupby(["N","K"],as_index=False).agg({
        "Feasible states":"first","Exact runtime ms":"median","MILP runtime ms":"median","MILP gap":"median",
        "SA runtime ms":"median","SA gap":"median","Local runtime ms":"median","Local gap":"median"
    })
    max_milp=float(np.nanmax(summary["MILP runtime ms"].to_numpy(dtype=float)))
    max_gap=float(np.nanmax(np.abs(summary[["MILP gap","SA gap","Local gap"]].to_numpy(dtype=float))))
    if max_milp < 250 and max_gap < 1e-4:
        eligibility="NOT ELIGIBLE"; rationale="classical controls remain fast and effectively exact on the measured scaling suite"
    elif max_milp < 2000:
        eligibility="EXPLORATORY"; rationale="classical difficulty is measurable but not yet a quantum-advantage regime"
    else:
        eligibility="BENCHMARK CANDIDATE"; rationale="classical controls show material runtime pressure; equal-objective quantum benchmarking may be informative"
    return {"available":True,"detail":detail,"summary":summary,"eligibility":eligibility,"rationale":rationale,"synthetic":True}

def density_matrix_from_asset_returns(returns: pd.DataFrame) -> dict[str, Any]:
    ret = clean_returns_frame(returns)
    if ret.empty or ret.shape[1] < 2:
        return {"available": False, "reason": "Need at least two assets with aligned returns."}

    centered = ret - ret.mean(axis=0)
    cov = centered.cov().to_numpy(dtype=float)
    cov = (cov + cov.T) / 2.0
    vals, vecs = np.linalg.eigh(cov)
    vals = np.clip(vals, 0.0, None)
    cov_psd = vecs @ np.diag(vals) @ vecs.T
    tr = float(np.trace(cov_psd))
    if tr <= _EPS:
        return {"available": False, "reason": "Degenerate covariance matrix."}

    rho = cov_psd / tr
    eigvals = np.linalg.eigvalsh(rho)[::-1]
    corr = ret.corr().to_numpy(dtype=float)
    return {
        "available": True,
        "labels": list(ret.columns),
        "rho": rho.astype(complex),
        "correlation": corr,
        "eigenvalues": eigvals,
        "entropy": von_neumann_entropy(rho.astype(complex), normalized=True),
        "purity": purity(rho.astype(complex)),
        "effective_dimension": effective_dimension(rho.astype(complex)),
        "observations": int(len(ret)),
    }


# ============================================================
# QUANTUM INFORMATION & TENSOR NETWORK ENGINE V2.5
# Classical quantum-information representations + TT/MPS controls
# ============================================================

def _psd_normalize(matrix: np.ndarray, ridge: float = 0.0) -> np.ndarray:
    """Project a Hermitian matrix to PSD and normalize it to unit trace."""
    a = np.asarray(matrix, dtype=complex)
    a = (a + a.conj().T) / 2.0
    vals, vecs = np.linalg.eigh(a)
    vals = np.clip(np.real(vals), 0.0, None)
    if ridge > 0:
        vals = vals + float(ridge)
    tr = float(np.sum(vals))
    if tr <= _EPS:
        n = a.shape[0]
        return np.eye(n, dtype=complex) / max(n, 1)
    return (vecs @ np.diag(vals / tr) @ vecs.conj().T).astype(complex)


def _matrix_sqrt_psd(matrix: np.ndarray) -> np.ndarray:
    a = _psd_normalize(matrix)
    vals, vecs = np.linalg.eigh(a)
    vals = np.clip(np.real(vals), 0.0, None)
    return (vecs @ np.diag(np.sqrt(vals)) @ vecs.conj().T).astype(complex)


def _matrix_log_psd(matrix: np.ndarray, floor: float = 1e-12) -> np.ndarray:
    a = _psd_normalize(matrix)
    vals, vecs = np.linalg.eigh(a)
    vals = np.clip(np.real(vals), float(floor), None)
    return (vecs @ np.diag(np.log(vals)) @ vecs.conj().T).astype(complex)


def quantum_fidelity(rho: np.ndarray, sigma: np.ndarray) -> float:
    """Uhlmann fidelity F(rho,sigma) in [0,1]."""
    r = _psd_normalize(rho)
    s = _psd_normalize(sigma)
    sr = _matrix_sqrt_psd(r)
    middle = (sr @ s @ sr + (sr @ s @ sr).conj().T) / 2.0
    vals = np.linalg.eigvalsh(middle)
    root_trace = float(np.sum(np.sqrt(np.clip(np.real(vals), 0.0, None))))
    return float(np.clip(root_trace * root_trace, 0.0, 1.0))


def quantum_trace_distance(rho: np.ndarray, sigma: np.ndarray) -> float:
    """Trace distance 0.5 * ||rho-sigma||_1."""
    d = np.asarray(rho, dtype=complex) - np.asarray(sigma, dtype=complex)
    d = (d + d.conj().T) / 2.0
    vals = np.linalg.eigvalsh(d)
    return float(np.clip(0.5 * np.sum(np.abs(np.real(vals))), 0.0, 1.0))


def quantum_relative_entropy(rho: np.ndarray, sigma: np.ndarray, floor: float = 1e-10) -> float:
    """Regularized D(rho||sigma), natural-log units."""
    r = _psd_normalize(rho, ridge=floor)
    s = _psd_normalize(sigma, ridge=floor)
    lr = _matrix_log_psd(r, floor=floor)
    ls = _matrix_log_psd(s, floor=floor)
    val = np.trace(r @ (lr - ls))
    return float(max(np.real(val), 0.0))


def quantum_jensen_shannon_divergence(rho: np.ndarray, sigma: np.ndarray) -> float:
    """Symmetric quantum Jensen-Shannon divergence, natural-log units."""
    r = _psd_normalize(rho)
    s = _psd_normalize(sigma)
    m = _psd_normalize(0.5 * (r + s))
    return float(0.5 * quantum_relative_entropy(r, m) + 0.5 * quantum_relative_entropy(s, m))


def _density_state_metrics(rho: np.ndarray) -> dict[str, float]:
    r = _psd_normalize(rho)
    eig = np.sort(np.real(np.linalg.eigvalsh(r)))[::-1]
    gap = float(eig[0] - eig[1]) if len(eig) >= 2 else float(eig[0])
    spectral_concentration = float(eig[0]) if len(eig) else float("nan")
    return {
        "entropy": float(von_neumann_entropy(r, normalized=True)),
        "purity": float(purity(r)),
        "effective_dimension": float(effective_dimension(r)),
        "spectral_gap": gap,
        "top_eigenvalue": spectral_concentration,
    }


def rolling_quantum_information(
    returns: pd.DataFrame,
    window: int = 63,
    step: int = 5,
    min_observations: int = 40,
) -> dict[str, Any]:
    """Rolling covariance-density states and dependence-aware state-change diagnostics."""
    ret = clean_returns_frame(returns)
    window = int(max(window, min_observations))
    step = int(max(step, 1))
    if ret.empty or ret.shape[1] < 2 or len(ret) < window + step:
        return {"available": False, "reason": "Insufficient aligned history for rolling information states."}

    rows: list[dict[str, Any]] = []
    states: list[np.ndarray] = []
    dates: list[pd.Timestamp] = []
    for end in range(window, len(ret) + 1, step):
        sample = ret.iloc[end - window:end]
        info = density_matrix_from_asset_returns(sample)
        if not info.get("available"):
            continue
        rho = np.asarray(info["rho"], dtype=complex)
        met = _density_state_metrics(rho)
        date = pd.Timestamp(ret.index[end - 1]) if isinstance(ret.index, pd.DatetimeIndex) else pd.Timestamp("1970-01-01") + pd.Timedelta(days=end - 1)
        row: dict[str, Any] = {"Date": date, **met}
        if states:
            prev = states[-1]
            row["fidelity_prev"] = quantum_fidelity(rho, prev)
            row["trace_distance_prev"] = quantum_trace_distance(rho, prev)
            row["relative_entropy_prev"] = quantum_relative_entropy(rho, prev)
            row["qjs_prev"] = quantum_jensen_shannon_divergence(rho, prev)
        else:
            row["fidelity_prev"] = np.nan
            row["trace_distance_prev"] = np.nan
            row["relative_entropy_prev"] = np.nan
            row["qjs_prev"] = np.nan
        states.append(rho)
        dates.append(date)
        rows.append(row)

    timeline = pd.DataFrame(rows)
    if timeline.empty:
        return {"available": False, "reason": "No valid rolling information states."}
    timeline = timeline.set_index("Date")
    shocks = timeline.dropna(subset=["trace_distance_prev"]).nlargest(min(12, max(len(timeline) - 1, 0)), "trace_distance_prev").reset_index()
    current_rho = states[-1]
    previous_rho = states[-2] if len(states) >= 2 else states[-1]
    current = _density_state_metrics(current_rho)
    current.update({
        "fidelity_prev": quantum_fidelity(current_rho, previous_rho),
        "trace_distance_prev": quantum_trace_distance(current_rho, previous_rho),
        "relative_entropy_prev": quantum_relative_entropy(current_rho, previous_rho),
        "qjs_prev": quantum_jensen_shannon_divergence(current_rho, previous_rho),
    })
    hist_td = timeline["trace_distance_prev"].dropna().to_numpy(dtype=float)
    current_td = float(current["trace_distance_prev"])
    current["trace_distance_percentile"] = float(np.mean(hist_td <= current_td)) if len(hist_td) else float("nan")
    return {
        "available": True,
        "timeline": timeline,
        "shocks": shocks,
        "states": states,
        "dates": dates,
        "current_rho": current_rho,
        "previous_rho": previous_rho,
        "current": current,
        "window": window,
        "step": step,
        "observations": int(len(ret)),
    }


def _entropy_bits_from_eigenvalues(vals: np.ndarray) -> float:
    p = np.clip(np.real(np.asarray(vals, dtype=float)), 0.0, None)
    s = float(np.sum(p))
    if s <= _EPS:
        return 0.0
    p = p / s
    p = p[p > _EPS]
    return float(-np.sum(p * np.log2(p)))


def _classical_mutual_information_binary(prob: np.ndarray) -> float:
    p = np.asarray(prob, dtype=float).reshape(2, 2)
    p = p / max(float(p.sum()), _EPS)
    pa = p.sum(axis=1, keepdims=True)
    pb = p.sum(axis=0, keepdims=True)
    denom = pa @ pb
    mask = p > _EPS
    return float(np.sum(p[mask] * np.log2(p[mask] / np.clip(denom[mask], _EPS, None))))


def amplitude_encoded_pair_information(
    returns: pd.DataFrame,
    lookback: int = 252,
    smoothing: float = 0.5,
) -> dict[str, Any]:
    """Pairwise sign-state amplitude encoding.

    For each asset pair, empirical up/down joint probabilities p_ij are mapped to
    |psi> = sum sqrt(p_ij)|ij>.  Entanglement entropy/concurrence therefore describe
    the chosen amplitude representation of classical data, not physical entanglement.
    """
    ret = clean_returns_frame(returns)
    if lookback > 0:
        ret = ret.tail(int(lookback))
    if ret.empty or ret.shape[1] < 2 or len(ret) < 30:
        return {"available": False, "reason": "Need at least 30 aligned observations and two assets."}
    labels = list(ret.columns)
    n = len(labels)
    qmi = np.zeros((n, n), dtype=float)
    cmi = np.zeros((n, n), dtype=float)
    concurrence = np.zeros((n, n), dtype=float)
    ent = np.zeros((n, n), dtype=float)
    edges: list[dict[str, Any]] = []
    signs = (ret.to_numpy(dtype=float) >= 0.0).astype(int)
    for i in range(n):
        for j in range(i + 1, n):
            counts = np.full((2, 2), float(smoothing), dtype=float)
            for a, b in zip(signs[:, i], signs[:, j]):
                counts[int(a), int(b)] += 1.0
            p = counts / counts.sum()
            amp = np.sqrt(p)
            # Coefficient matrix for a two-qubit pure state.
            rho_a = amp @ amp.T
            rho_b = amp.T @ amp
            eig_a = np.linalg.eigvalsh((rho_a + rho_a.T) / 2.0)
            eig_b = np.linalg.eigvalsh((rho_b + rho_b.T) / 2.0)
            s_a = _entropy_bits_from_eigenvalues(eig_a)
            s_b = _entropy_bits_from_eigenvalues(eig_b)
            qmi_ij = s_a + s_b  # global pure state has S(AB)=0
            cmi_ij = _classical_mutual_information_binary(p)
            conc = float(np.clip(2.0 * abs(amp[0, 0] * amp[1, 1] - amp[0, 1] * amp[1, 0]), 0.0, 1.0))
            qmi[i, j] = qmi[j, i] = qmi_ij
            cmi[i, j] = cmi[j, i] = cmi_ij
            concurrence[i, j] = concurrence[j, i] = conc
            ent[i, j] = ent[j, i] = 0.5 * (s_a + s_b)
            edges.append({
                "Asset A": labels[i], "Asset B": labels[j],
                "Amplitude QMI bits": qmi_ij,
                "Classical sign MI bits": cmi_ij,
                "Amplitude concurrence": conc,
                "Amplitude entanglement entropy bits": 0.5 * (s_a + s_b),
                "Pearson correlation": float(ret.iloc[:, i].corr(ret.iloc[:, j])),
            })
    edge_df = pd.DataFrame(edges).sort_values("Amplitude QMI bits", ascending=False).reset_index(drop=True)
    return {
        "available": True,
        "labels": labels,
        "qmi": qmi,
        "classical_mi": cmi,
        "concurrence": concurrence,
        "entanglement_entropy": ent,
        "edges": edge_df,
        "observations": int(len(ret)),
        "lookback": int(lookback),
    }


def _tt_svd(
    tensor: np.ndarray,
    max_rank: int = 8,
    energy_threshold: float = 0.999,
) -> dict[str, Any]:
    """Tensor-Train SVD for a dense tensor. Classical deterministic algorithm."""
    x = np.asarray(tensor, dtype=float)
    dims = tuple(int(v) for v in x.shape)
    if x.ndim < 2 or np.prod(dims) == 0:
        return {"available": False, "reason": "Tensor must have at least two non-empty modes."}
    max_rank = int(max(1, max_rank))
    energy_threshold = float(np.clip(energy_threshold, 0.5, 1.0))
    cores: list[np.ndarray] = []
    ranks = [1]
    singular_values: list[np.ndarray] = []
    bond_entropies: list[float] = []
    retained_energy: list[float] = []
    energy_required_ranks: list[int] = []
    current = x.copy()
    r_prev = 1
    for mode in range(len(dims) - 1):
        n_mode = dims[mode]
        current = current.reshape(r_prev * n_mode, -1)
        u, s, vh = np.linalg.svd(current, full_matrices=False)
        singular_values.append(s.copy())
        sq = s * s
        if float(sq.sum()) <= _EPS:
            rank_energy = 1
        else:
            cum = np.cumsum(sq) / sq.sum()
            rank_energy = int(np.searchsorted(cum, energy_threshold) + 1)
        r = int(max(1, min(max_rank, rank_energy, len(s))))
        energy_required_ranks.append(int(rank_energy))
        retained = float(np.sum(sq[:r]) / max(float(np.sum(sq)), _EPS))
        retained_energy.append(retained)
        # Bond entropy of the retained Schmidt spectrum, not the discarded tail.
        entropy = _entropy_bits_from_eigenvalues(sq[:r])
        bond_entropies.append(float(entropy))
        core = u[:, :r].reshape(r_prev, n_mode, r)
        cores.append(core)
        current = (s[:r, None] * vh[:r, :])
        ranks.append(r)
        r_prev = r
    cores.append(current.reshape(r_prev, dims[-1], 1))
    ranks.append(1)

    rec = cores[0]
    for core in cores[1:]:
        rec = np.tensordot(rec, core, axes=([-1], [0]))
    rec = np.squeeze(rec, axis=(0, -1))
    norm = float(np.linalg.norm(x.ravel()))
    rel_error = float(np.linalg.norm((x - rec).ravel()) / max(norm, _EPS))
    params = int(sum(c.size for c in cores))
    original = int(x.size)
    compression = float(original / max(params, 1))
    return {
        "available": True,
        "shape": dims,
        "cores": cores,
        "ranks": ranks,
        "singular_values": singular_values,
        "bond_entropies_bits": bond_entropies,
        "retained_energy_by_bond": retained_energy,
        "energy_required_ranks": energy_required_ranks,
        "rank_cap_binding": bool(any(req > max_rank for req in energy_required_ranks)),
        "reconstruction": rec,
        "relative_error": rel_error,
        "parameters": params,
        "original_parameters": original,
        "compression_ratio": compression,
        "max_rank_used": int(max(ranks)),
        "energy_threshold": energy_threshold,
    }


def _matrix_svd_budget_baseline(tensor: np.ndarray, parameter_budget: int) -> dict[str, Any]:
    x = np.asarray(tensor, dtype=float)
    # Flatten temporal modes into rows, asset/channel modes into columns.
    if x.ndim >= 4:
        m = int(np.prod(x.shape[:2])); n = int(np.prod(x.shape[2:]))
    else:
        split = max(1, x.ndim // 2)
        m = int(np.prod(x.shape[:split])); n = int(np.prod(x.shape[split:]))
    mat = x.reshape(m, n)
    u, s, vh = np.linalg.svd(mat, full_matrices=False)
    denom = max(m + n + 1, 1)
    rank = int(max(1, min(len(s), parameter_budget // denom)))
    approx = (u[:, :rank] * s[:rank]) @ vh[:rank, :]
    err = float(np.linalg.norm(mat - approx) / max(np.linalg.norm(mat), _EPS))
    params = int(rank * (m + n + 1))
    return {"rank": rank, "relative_error": err, "parameters": params, "shape": (m, n), "singular_values": s}


def build_market_structure_tensor(
    returns: pd.DataFrame,
    block_size: int = 20,
    channels: tuple[str, ...] = ("z_return", "abs_z", "squared_z"),
) -> dict[str, Any]:
    ret = clean_returns_frame(returns)
    block_size = int(max(block_size, 5))
    if ret.empty or ret.shape[1] < 2 or len(ret) < block_size * 3:
        return {"available": False, "reason": "Need at least three tensor blocks of aligned returns."}
    arr = ret.to_numpy(dtype=float)
    mu = np.nanmean(arr, axis=0, keepdims=True)
    sd = np.nanstd(arr, axis=0, ddof=1, keepdims=True)
    sd = np.where(sd > 1e-12, sd, 1.0)
    z = np.clip((arr - mu) / sd, -6.0, 6.0)
    channel_arrays: list[np.ndarray] = []
    for name in channels:
        if name == "z_return": channel_arrays.append(z)
        elif name == "abs_z": channel_arrays.append(np.abs(z))
        elif name == "squared_z": channel_arrays.append(np.clip(z * z, 0.0, 36.0))
        else: raise ValueError(f"Unsupported tensor channel: {name}")
    c = np.stack(channel_arrays, axis=-1)
    n_blocks = int(len(c) // block_size)
    c = c[-n_blocks * block_size:]
    tensor = c.reshape(n_blocks, block_size, ret.shape[1], len(channels))
    return {
        "available": True,
        "tensor": tensor,
        "shape": tensor.shape,
        "labels": list(ret.columns),
        "channels": list(channels),
        "block_size": block_size,
        "blocks": n_blocks,
        "observations": int(n_blocks * block_size),
    }


def tensor_network_market_analysis(
    returns: pd.DataFrame,
    block_size: int = 20,
    max_rank: int = 8,
    energy_threshold: float = 0.995,
    seed: int = 2026,
) -> dict[str, Any]:
    built = build_market_structure_tensor(returns, block_size=block_size)
    if not built.get("available"):
        return built
    tensor = np.asarray(built["tensor"], dtype=float)
    tt = _tt_svd(tensor, max_rank=max_rank, energy_threshold=energy_threshold)
    if not tt.get("available"):
        return tt
    svd = _matrix_svd_budget_baseline(tensor, parameter_budget=int(tt["parameters"]))

    # Temporal-order null: permute daily observations before rebuilding equal-shaped tensor.
    rng = np.random.default_rng(seed)
    flat = tensor.reshape(-1, tensor.shape[2], tensor.shape[3]).copy()
    perm = rng.permutation(flat.shape[0])
    shuffled = flat[perm].reshape(tensor.shape)
    shuffled_tt = _tt_svd(shuffled, max_rank=max_rank, energy_threshold=energy_threshold)

    # Channel-wise reconstruction errors.
    rec = np.asarray(tt["reconstruction"], dtype=float)
    channel_rows: list[dict[str, Any]] = []
    for k, name in enumerate(built["channels"]):
        orig_k = tensor[..., k]
        rec_k = rec[..., k]
        err = float(np.linalg.norm(orig_k - rec_k) / max(np.linalg.norm(orig_k), _EPS))
        channel_rows.append({"Channel": name, "TT relative error": err})
    channel_error = pd.DataFrame(channel_rows)

    # Asset-wise errors over all time blocks/channels.
    asset_rows: list[dict[str, Any]] = []
    for j, name in enumerate(built["labels"]):
        orig_j = tensor[:, :, j, :]
        rec_j = rec[:, :, j, :]
        err = float(np.linalg.norm(orig_j - rec_j) / max(np.linalg.norm(orig_j), _EPS))
        asset_rows.append({"Asset": name, "TT relative error": err})
    asset_error = pd.DataFrame(asset_rows)

    return {
        "available": True,
        **built,
        "tt": tt,
        "svd_baseline": svd,
        "shuffled_tt": shuffled_tt,
        "channel_error": channel_error,
        "asset_error": asset_error,
        "structure_gain_vs_shuffle": float(shuffled_tt["relative_error"] - tt["relative_error"]),
        "tt_vs_svd_error_delta": float(svd["relative_error"] - tt["relative_error"]),
        "classical_only": True,
    }



# ============================================================
# QUANTUM INFORMATION V2.5.1 · VALIDATION & ROBUSTNESS LAYER
# ============================================================

def density_state_variants(returns: pd.DataFrame) -> dict[str, Any]:
    """Decompose the market state into covariance, correlation and volatility density operators.

    All three objects are classical PSD constructions normalized to unit trace.  This
    separation prevents a covariance-density shift from being interpreted as a pure
    correlation-geometry shift when it is actually driven by relative volatilities.
    """
    ret = clean_returns_frame(returns)
    if ret.empty or ret.shape[1] < 2:
        return {"available": False, "reason": "Need at least two aligned assets."}
    centered = ret - ret.mean(axis=0)
    cov = centered.cov().to_numpy(dtype=float)
    corr = ret.corr().to_numpy(dtype=float)
    variances = np.clip(np.diag(cov), 0.0, None)
    rho_cov = _psd_normalize(cov)
    rho_corr = _psd_normalize(corr)
    rho_vol = _psd_normalize(np.diag(variances))
    out = {
        "available": True,
        "labels": list(ret.columns),
        "covariance": rho_cov,
        "correlation": rho_corr,
        "volatility": rho_vol,
        "raw_correlation": corr,
        "raw_covariance": cov,
        "volatility_share": variances / max(float(np.sum(variances)), _EPS),
        "observations": int(len(ret)),
    }
    for name, rho in [("covariance", rho_cov), ("correlation", rho_corr), ("volatility", rho_vol)]:
        out[f"{name}_metrics"] = _density_state_metrics(rho)
    out["cov_vs_corr_trace_distance"] = quantum_trace_distance(rho_cov, rho_corr)
    out["cov_vs_vol_trace_distance"] = quantum_trace_distance(rho_cov, rho_vol)
    return out


def rolling_density_decomposition(
    returns: pd.DataFrame,
    window: int = 63,
    step: int = 5,
) -> dict[str, Any]:
    """Rolling decomposition of total covariance-density change into correlation and volatility channels."""
    ret = clean_returns_frame(returns)
    window = int(max(window, 30)); step = int(max(step, 1))
    if ret.empty or len(ret) < window + step:
        return {"available": False, "reason": "Insufficient history for rolling density decomposition."}
    rows=[]; prev=None
    for end in range(window, len(ret)+1, step):
        sample=ret.iloc[end-window:end]
        d=density_state_variants(sample)
        if not d.get("available"): continue
        date=pd.Timestamp(ret.index[end-1]) if isinstance(ret.index,pd.DatetimeIndex) else pd.Timestamp('1970-01-01')+pd.Timedelta(days=end-1)
        row={"Date":date}
        if prev is not None:
            total=quantum_trace_distance(d["covariance"],prev["covariance"])
            corr=quantum_trace_distance(d["correlation"],prev["correlation"])
            vol=quantum_trace_distance(d["volatility"],prev["volatility"])
            denom=max(corr+vol,_EPS)
            row.update({
                "total_shift":total,"correlation_shift":corr,"volatility_shift":vol,
                "correlation_share":corr/denom,"volatility_share":vol/denom,
            })
        else:
            row.update({"total_shift":np.nan,"correlation_shift":np.nan,"volatility_shift":np.nan,"correlation_share":np.nan,"volatility_share":np.nan})
        rows.append(row); prev=d
    tl=pd.DataFrame(rows)
    if tl.empty: return {"available":False,"reason":"No rolling density states."}
    tl=tl.set_index("Date")
    current=tl.dropna().iloc[-1].to_dict() if len(tl.dropna()) else {}
    return {"available":True,"timeline":tl,"current":current}


def _distance_correlation(x: np.ndarray, y: np.ndarray) -> float:
    """Bias-corrected style distance-correlation proxy using doubly centered distance matrices."""
    x=np.asarray(x,dtype=float).reshape(-1); y=np.asarray(y,dtype=float).reshape(-1)
    mask=np.isfinite(x)&np.isfinite(y); x=x[mask]; y=y[mask]
    n=len(x)
    if n < 5: return float('nan')
    a=np.abs(x[:,None]-x[None,:]); b=np.abs(y[:,None]-y[None,:])
    A=a-a.mean(axis=0,keepdims=True)-a.mean(axis=1,keepdims=True)+a.mean()
    B=b-b.mean(axis=0,keepdims=True)-b.mean(axis=1,keepdims=True)+b.mean()
    dcov2=float(np.mean(A*B)); dvarx=float(np.mean(A*A)); dvary=float(np.mean(B*B))
    if dvarx<=_EPS or dvary<=_EPS: return 0.0
    return float(np.clip(np.sqrt(max(dcov2,0.0)/np.sqrt(dvarx*dvary)),0.0,1.0))


def _qmi_from_binary_vectors(a: np.ndarray, b: np.ndarray, smoothing: float=0.5) -> tuple[float,float,float]:
    counts=np.full((2,2),float(smoothing),dtype=float)
    for aa,bb in zip(a,b): counts[int(aa),int(bb)]+=1.0
    p=counts/counts.sum(); amp=np.sqrt(p)
    rho_a=amp@amp.T; rho_b=amp.T@amp
    sa=_entropy_bits_from_eigenvalues(np.linalg.eigvalsh((rho_a+rho_a.T)/2.0))
    sb=_entropy_bits_from_eigenvalues(np.linalg.eigvalsh((rho_b+rho_b.T)/2.0))
    qmi=float(sa+sb); cmi=float(_classical_mutual_information_binary(p))
    conc=float(np.clip(2.0*abs(amp[0,0]*amp[1,1]-amp[0,1]*amp[1,0]),0.0,1.0))
    return qmi,cmi,conc


def _bh_fdr(p_values: np.ndarray) -> np.ndarray:
    p=np.asarray(p_values,dtype=float); n=len(p)
    if n==0: return p
    order=np.argsort(p); ranked=p[order]
    q=np.empty(n,dtype=float); prev=1.0
    for i in range(n-1,-1,-1):
        rank=i+1; val=min(prev, ranked[i]*n/rank); q[i]=val; prev=val
    out=np.empty(n,dtype=float); out[order]=np.clip(q,0.0,1.0)
    return out


def pairwise_dependence_validation(
    returns: pd.DataFrame,
    lookback: int = 252,
    permutations: int = 99,
    seed: int = 2026,
) -> dict[str, Any]:
    """Strong classical controls + permutation significance for the amplitude representation."""
    ret=clean_returns_frame(returns)
    if lookback>0: ret=ret.tail(int(lookback))
    if ret.empty or ret.shape[1]<2 or len(ret)<40:
        return {"available":False,"reason":"Insufficient history for dependence validation."}
    labels=list(ret.columns); signs=(ret.to_numpy(dtype=float)>=0).astype(int); arr=ret.to_numpy(dtype=float)
    rng=np.random.default_rng(seed); rows=[]
    for i in range(len(labels)):
        for j in range(i+1,len(labels)):
            qmi,cmi,conc=_qmi_from_binary_vectors(signs[:,i],signs[:,j])
            spearman=float(pd.Series(arr[:,i]).corr(pd.Series(arr[:,j]),method='spearman'))
            pearson=float(np.corrcoef(arr[:,i],arr[:,j])[0,1])
            dcor=_distance_correlation(arr[:,i],arr[:,j])
            q_null=[]; mi_null=[]
            for _ in range(int(max(permutations,0))):
                perm=rng.permutation(len(ret))
                q0,m0,_=_qmi_from_binary_vectors(signs[:,i],signs[perm,j])
                q_null.append(q0); mi_null.append(m0)
            if q_null:
                q_p=(1+sum(v>=qmi for v in q_null))/(len(q_null)+1)
                mi_p=(1+sum(v>=cmi for v in mi_null))/(len(mi_null)+1)
            else: q_p=mi_p=float('nan')
            rows.append({"Asset A":labels[i],"Asset B":labels[j],"Amplitude QMI bits":qmi,"QMI permutation p":q_p,
                         "Classical sign MI bits":cmi,"Sign MI permutation p":mi_p,"Amplitude concurrence":conc,
                         "Pearson":pearson,"Spearman":spearman,"Distance correlation":dcor})
    df=pd.DataFrame(rows)
    if df.empty: return {"available":False,"reason":"No asset pairs."}
    df["QMI FDR q"]=_bh_fdr(df["QMI permutation p"].to_numpy(dtype=float))
    df["Sign MI FDR q"]=_bh_fdr(df["Sign MI permutation p"].to_numpy(dtype=float))
    return {"available":True,"table":df.sort_values("Amplitude QMI bits",ascending=False).reset_index(drop=True),
            "permutations":int(permutations),"significant_qmi_fdr":int((df["QMI FDR q"]<0.05).sum()),"pairs":int(len(df))}


def _mode_product(tensor: np.ndarray, matrix: np.ndarray, mode: int) -> np.ndarray:
    """n-mode product where matrix shape = [new_dim, old_dim]."""
    res=np.tensordot(matrix,tensor,axes=(1,mode))
    return np.moveaxis(res,0,mode)


def _tucker_hosvd_budget_baseline(tensor: np.ndarray, parameter_budget: int, rank_cap: int=16) -> dict[str, Any]:
    """Parameter-budgeted Tucker/HOSVD baseline using a spectral-energy proxy to choose multilinear ranks."""
    x=np.asarray(tensor,dtype=float); dims=x.shape; nd=x.ndim
    spectra=[]; factors=[]
    for mode in range(nd):
        unfold=np.moveaxis(x,mode,0).reshape(dims[mode],-1)
        u,s,_=np.linalg.svd(unfold,full_matrices=False)
        spectra.append(s); factors.append(u)
    rank_ranges=[range(1,min(int(d),int(rank_cap))+1) for d in dims]
    best=None
    import itertools
    total_norm=max(float(np.linalg.norm(x)),_EPS)
    # Exhaustive rank tuple search is small for the 4D market tensor.
    for ranks in itertools.product(*rank_ranges):
        params=int(np.prod(ranks)+sum(int(d)*int(r) for d,r in zip(dims,ranks)))
        if params>parameter_budget: continue
        score=1.0
        for s,r in zip(spectra,ranks):
            e=float(np.sum(s[:r]**2)/max(np.sum(s**2),_EPS)); score*=e
        if best is None or score>best[0]: best=(score,ranks,params)
    if best is None:
        ranks=tuple(1 for _ in dims); params=int(1+sum(d for d in dims))
    else: _,ranks,params=best
    core=x.copy(); used=[]
    for mode,(u,r) in enumerate(zip(factors,ranks)):
        U=u[:,:r]; used.append(U); core=_mode_product(core,U.T,mode)
    rec=core.copy()
    for mode,U in enumerate(used): rec=_mode_product(rec,U,mode)
    err=float(np.linalg.norm(x-rec)/total_norm)
    return {"relative_error":err,"ranks":tuple(int(r) for r in ranks),"parameters":int(params),"core_parameters":int(core.size),"reconstruction":rec}


def tensor_null_distribution(
    tensor: np.ndarray,
    max_rank: int,
    energy_threshold: float,
    shuffles: int=100,
    seed: int=2026,
) -> dict[str, Any]:
    """Permutation null for temporal ordering. Lower reconstruction error is better."""
    x=np.asarray(tensor,dtype=float); flat=x.reshape(-1,x.shape[2],x.shape[3])
    rng=np.random.default_rng(seed); errors=[]
    for _ in range(int(max(shuffles,1))):
        perm=rng.permutation(flat.shape[0]); sh=flat[perm].reshape(x.shape)
        tt=_tt_svd(sh,max_rank=max_rank,energy_threshold=energy_threshold)
        errors.append(float(tt["relative_error"]))
    errors=np.asarray(errors,dtype=float)
    return {"errors":errors,"median":float(np.median(errors)),"mean":float(np.mean(errors)),
            "ci_low":float(np.quantile(errors,0.025)),"ci_high":float(np.quantile(errors,0.975)),"shuffles":int(len(errors))}


def tensor_rank_frontier(
    tensor: np.ndarray,
    ranks: Iterable[int]=(1,2,4,6,8,12,16),
    energy_threshold: float=0.995,
) -> pd.DataFrame:
    rows=[]
    max_possible=max(tensor.shape)
    for r in sorted(set(int(v) for v in ranks if int(v)>=1 and int(v)<=max_possible)):
        tt=_tt_svd(tensor,max_rank=r,energy_threshold=energy_threshold)
        svd=_matrix_svd_budget_baseline(tensor,int(tt["parameters"]))
        tucker=_tucker_hosvd_budget_baseline(tensor,int(tt["parameters"]),rank_cap=max(r,2))
        rows.append({"Max rank":r,"TT error":tt["relative_error"],"Compression":tt["compression_ratio"],
                     "Parameters":tt["parameters"],"Min retained":min(tt["retained_energy_by_bond"]),
                     "SVD error":svd["relative_error"],"Tucker error":tucker["relative_error"],
                     "TT−SVD edge":svd["relative_error"]-tt["relative_error"],"TT−Tucker edge":tucker["relative_error"]-tt["relative_error"]})
    return pd.DataFrame(rows)


def tensor_block_frontier(
    returns: pd.DataFrame,
    block_sizes: Iterable[int]=(5,10,20,40,63),
    max_rank: int=8,
    energy_threshold: float=0.995,
    null_shuffles: int=20,
    seed: int=2027,
) -> pd.DataFrame:
    rows=[]
    for b in block_sizes:
        built=build_market_structure_tensor(returns,block_size=int(b))
        if not built.get("available"): continue
        x=np.asarray(built["tensor"],dtype=float); tt=_tt_svd(x,max_rank=max_rank,energy_threshold=energy_threshold)
        svd=_matrix_svd_budget_baseline(x,int(tt["parameters"])); tucker=_tucker_hosvd_budget_baseline(x,int(tt["parameters"]),rank_cap=max(max_rank,2))
        null=tensor_null_distribution(x,max_rank=max_rank,energy_threshold=energy_threshold,shuffles=null_shuffles,seed=seed+int(b))
        p=(1+int(np.sum(null["errors"]<=tt["relative_error"])))/(len(null["errors"])+1)
        rows.append({"Block size":int(b),"Blocks":int(built["blocks"]),"TT error":tt["relative_error"],"Compression":tt["compression_ratio"],
                     "SVD error":svd["relative_error"],"Tucker error":tucker["relative_error"],"Null median":null["median"],"Order gain":null["median"]-tt["relative_error"],"Null p":p})
    return pd.DataFrame(rows)


def _spectral_distance(a: list[np.ndarray], b: list[np.ndarray]) -> float:
    vals=[]
    for sa,sb in zip(a,b):
        pa=np.asarray(sa,dtype=float)**2; pb=np.asarray(sb,dtype=float)**2
        pa=pa/max(float(pa.sum()),_EPS); pb=pb/max(float(pb.sum()),_EPS)
        n=max(len(pa),len(pb)); aa=np.pad(pa,(0,n-len(pa))); bb=np.pad(pb,(0,n-len(pb)))
        vals.append(0.5*float(np.sum(np.abs(aa-bb))))
    return float(np.mean(vals)) if vals else float('nan')


def rolling_tensor_stability(
    returns: pd.DataFrame,
    block_size: int=20,
    max_rank: int=8,
    energy_threshold: float=0.995,
    rolling_observations: int=240,
    step: int=20,
) -> dict[str, Any]:
    """Rolling TT structural stability; descriptive, not a return forecast."""
    ret=clean_returns_frame(returns); block_size=int(max(block_size,5))
    roll=int(max(block_size*3,(rolling_observations//block_size)*block_size)); step=int(max(step,1))
    if len(ret)<roll+step: return {"available":False,"reason":"Insufficient history for rolling TT stability."}
    rows=[]; prev_tt=None; prev_rec=None
    for end in range(roll,len(ret)+1,step):
        sample=ret.iloc[end-roll:end]; built=build_market_structure_tensor(sample,block_size=block_size)
        if not built.get("available"): continue
        x=np.asarray(built["tensor"],dtype=float); tt=_tt_svd(x,max_rank=max_rank,energy_threshold=energy_threshold)
        date=pd.Timestamp(ret.index[end-1]) if isinstance(ret.index,pd.DatetimeIndex) else pd.Timestamp('1970-01-01')+pd.Timedelta(days=end-1)
        row={"Date":date,"TT error":tt["relative_error"],"Compression":tt["compression_ratio"],"Mean bond entropy":float(np.mean(tt["bond_entropies_bits"])),"Max rank":tt["max_rank_used"],"Min retained":min(tt["retained_energy_by_bond"])}
        if prev_tt is not None:
            row["Spectrum drift"]=_spectral_distance(tt["singular_values"],prev_tt["singular_values"])
            # Relative-template transfer: previous low-rank template vs the current standardized tensor.
            row["Template transfer error"]=float(np.linalg.norm(x-prev_rec)/max(np.linalg.norm(x),_EPS)) if prev_rec is not None and prev_rec.shape==x.shape else np.nan
        else:
            row["Spectrum drift"]=np.nan; row["Template transfer error"]=np.nan
        rows.append(row); prev_tt=tt; prev_rec=np.asarray(tt["reconstruction"],dtype=float)
    tl=pd.DataFrame(rows)
    if tl.empty: return {"available":False,"reason":"No rolling TT states."}
    tl=tl.set_index("Date")
    return {"available":True,"timeline":tl,"rolling_observations":roll,"step":step}


def tensor_network_market_analysis_v251(
    returns: pd.DataFrame,
    block_size: int=20,
    max_rank: int=8,
    energy_threshold: float=0.995,
    null_shuffles: int=100,
    seed: int=2026,
) -> dict[str, Any]:
    base=tensor_network_market_analysis(returns,block_size=block_size,max_rank=max_rank,energy_threshold=energy_threshold,seed=seed)
    if not base.get("available"): return base
    x=np.asarray(base["tensor"],dtype=float); tt=base["tt"]
    tucker=_tucker_hosvd_budget_baseline(x,int(tt["parameters"]),rank_cap=max(max_rank,2))
    null=tensor_null_distribution(x,max_rank=max_rank,energy_threshold=energy_threshold,shuffles=null_shuffles,seed=seed)
    p=(1+int(np.sum(null["errors"]<=tt["relative_error"])))/(len(null["errors"])+1)
    rank_front=tensor_rank_frontier(x,energy_threshold=energy_threshold)
    block_front=tensor_block_frontier(returns,max_rank=max_rank,energy_threshold=energy_threshold,null_shuffles=max(10,min(30,null_shuffles//4)),seed=seed+11)
    rolling=rolling_tensor_stability(returns,block_size=block_size,max_rank=max_rank,energy_threshold=energy_threshold)
    # Robustness share across rank/block configurations: positive edge versus both SVD and Tucker.
    r_ok=float(np.mean((rank_front["TT−SVD edge"]>0)&(rank_front["TT−Tucker edge"]>0))) if not rank_front.empty else 0.0
    b_ok=float(np.mean((block_front["TT error"]<block_front["SVD error"])&(block_front["TT error"]<block_front["Tucker error"]))) if not block_front.empty else 0.0
    robust_share=float(np.nanmean([r_ok,b_ok]))
    level=0; label="L0 · NO COMPRESSION VALUE"
    if base["tt_vs_svd_error_delta"]>0: level=1; label="L1 · BEATS MATRIX SVD"
    if level>=1 and (tucker["relative_error"]-tt["relative_error"])>0: level=2; label="L2 · BEATS TENSOR CONTROL"
    if level>=2 and p<0.05: level=3; label="L3 · SURVIVES TEMPORAL NULL"
    if level>=3 and robust_share>=0.60: level=4; label="L4 · ROBUST ACROSS RANK / BLOCK"
    return {**base,"tucker_baseline":tucker,"null_distribution":null,"null_p_value":float(p),"rank_frontier":rank_front,
            "block_frontier":block_front,"rolling_stability":rolling,"robustness_share":robust_share,
            "validation_level":level,"validation_label":label,
            "tt_vs_tucker_error_delta":float(tucker["relative_error"]-tt["relative_error"]),"v251":True}

def quantum_information_v2(
    returns: pd.DataFrame,
    rolling_window: int = 63,
    rolling_step: int = 5,
    pair_lookback: int = 252,
    tensor_block_size: int = 20,
    tensor_max_rank: int = 8,
    tensor_energy: float = 0.995,
    pair_permutations: int = 99,
    tensor_null_shuffles: int = 100,
) -> dict[str, Any]:
    base = density_matrix_from_asset_returns(returns)
    if not base.get("available"):
        return base
    variants = density_state_variants(returns)
    rolling = rolling_quantum_information(returns, window=rolling_window, step=rolling_step)
    density_decomp = rolling_density_decomposition(returns, window=rolling_window, step=rolling_step)
    pairwise = amplitude_encoded_pair_information(returns, lookback=pair_lookback)
    pair_validation = pairwise_dependence_validation(returns, lookback=pair_lookback, permutations=pair_permutations)
    tensor = tensor_network_market_analysis_v251(returns, block_size=tensor_block_size, max_rank=tensor_max_rank, energy_threshold=tensor_energy, null_shuffles=tensor_null_shuffles)
    return {"available": True, "base": base, "density_variants": variants, "rolling": rolling, "density_decomposition": density_decomp,
            "pairwise": pairwise, "pair_validation": pair_validation, "tensor": tensor}

def research_registry() -> pd.DataFrame:
    rows = [
        ("Quantum Monte Carlo / QAE", "High", "V2.3.2 total-error feasibility frontier", "Canonical classical snapshots, randomized Sobol validation, bounded-payoff amplitude mapping, product-aware resources and empirical break-even controls."),
        ("Quantum Risk / Greeks", "High", "V2.3.2 P/Q-separated risk workbench", "Physical-measure VaR/CVaR is separated from risk-neutral EE/PFE/CVA exposure controls; non-European approximations remain explicitly labelled."),
        ("Quantum Derivatives", "High", "V2.3.2 multi-payoff + resource fidelity", "European, Asian, barrier, basket and Heston controls with analytic/high-path references, explicit payoff truncation and product-dependent resource envelopes."),
        ("QUBO / Ising Portfolio", "High", "V2.4.1 constraint-preserving QAOA + hardness controls", "Hard-constraint presolve, minimum-safe penalty frontier, exact/MILP/heuristic controls, X-vs-XY statevector QAOA, Dicke-state feasibility preservation and empirical classical-hardness benchmarking."),
        ("Quantum Regime Probability", "High-Exploratory", "V2.2.1 purged OOS + dependency-aware validation", "Persistent multi-horizon regime targets, purged expanding-window labels, dependency-aware block bootstrap, HMM / Markov switching / matched classical encoder, calibration and economic-utility gates."),
        ("Quantum Information Networks", "High-Exploratory", "V2.5.1 validation workbench", "Rolling density states, fidelity/trace-distance shocks and amplitude-encoded pair information are benchmarked against correlation and classical sign-MI controls."),
        ("Quantum Kernels / QML", "Medium", "Guarded", "Use point-in-time data, purged CV, multiple-testing controls and kernel-swap baselines."),
        ("Quantum Microstructure Features", "Medium-High", "Frontier", "Promising empirical direction; hardware noise and regularisation need isolation tests."),
        ("Tensor Networks", "High", "V2.5.1 TT/MPS validation engine", "Tensor-Train SVD compresses a multi-channel market tensor and is benchmarked against parameter-budgeted matrix SVD, Tucker/HOSVD, multi-shuffle temporal nulls, rank/block frontiers and rolling stability."),
    ]
    return pd.DataFrame(rows, columns=["Research Block", "Priority", "Status", "Control Principle"])

# ============================================================
# QUANTUM REGIME ENGINE V2 — CONTROLLED OOS RESEARCH LAYER
# ============================================================

V2_FEATURE_COLUMNS = (
    "eq_ret_1",
    "eq_mom_20",
    "eq_mom_60",
    "rv_20",
    "drawdown_60",
    "vix_level",
    "vix_change_5",
    "tlt_ret_20",
    "gold_ret_20",
    "hyg_ret_20",
    "credit_rel_20",
    "eq_vs_bond_20",
)


def _logsumexp(values: np.ndarray, axis: int | None = None) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    m = np.max(arr, axis=axis, keepdims=True)
    out = m + np.log(np.sum(np.exp(arr - m), axis=axis, keepdims=True) + _EPS)
    if axis is not None:
        out = np.squeeze(out, axis=axis)
    return out


def _rolling_zscore(series: pd.Series, window: int = 126, min_periods: int = 40) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    mean = s.rolling(window, min_periods=min_periods).mean()
    std = s.rolling(window, min_periods=min_periods).std(ddof=1).replace(0, np.nan)
    return (s - mean) / std


def prepare_regime_feature_frame(
    market_frame: pd.DataFrame,
    horizon: int = 5,
) -> pd.DataFrame:
    """
    Build point-in-time market features plus a *forward* cross-asset regime proxy.

    The forward proxy is used only as an evaluation label.  It is never included
    in the feature matrix and therefore does not leak into model inputs.
    """
    if not isinstance(market_frame, pd.DataFrame) or market_frame.empty:
        return pd.DataFrame()

    df = market_frame.copy()
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).set_index("date")
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, errors="coerce")
    df = df[~df.index.isna()].sort_index()

    # Canonical series.  PRIMARY is the selected instrument; SPY is the equity
    # fallback so the engine remains usable for non-equity terminal contexts.
    primary_col = "PRIMARY" if "PRIMARY" in df.columns else "SPY" if "SPY" in df.columns else None
    if primary_col is None:
        return pd.DataFrame()

    def col(name: str, fallback: str | None = None) -> pd.Series:
        key = name if name in df.columns else fallback
        if key is None or key not in df.columns:
            return pd.Series(np.nan, index=df.index, dtype=float)
        return pd.to_numeric(df[key], errors="coerce")

    eq = col(primary_col)
    spy = col("SPY", primary_col)
    tlt = col("TLT")
    gold = col("GLD")
    hyg = col("HYG")
    vix = col("VIX")

    out = pd.DataFrame(index=df.index)
    out["eq_ret_1"] = eq.pct_change(fill_method=None)
    out["eq_mom_20"] = eq.pct_change(20, fill_method=None)
    out["eq_mom_60"] = eq.pct_change(60, fill_method=None)
    out["rv_20"] = out["eq_ret_1"].rolling(20, min_periods=15).std(ddof=1) * sqrt(252.0)
    out["drawdown_60"] = eq / eq.rolling(60, min_periods=20).max() - 1.0

    # VIX is normally quoted in vol points.  Synthetic fallback may already be
    # a comparable level; divide by 100 only when values are clearly index-like.
    vix_med = float(vix.dropna().median()) if not vix.dropna().empty else np.nan
    out["vix_level"] = vix / 100.0 if np.isfinite(vix_med) and vix_med > 3.0 else vix
    out["vix_change_5"] = vix.pct_change(5, fill_method=None)

    out["tlt_ret_20"] = tlt.pct_change(20, fill_method=None)
    out["gold_ret_20"] = gold.pct_change(20, fill_method=None)
    out["hyg_ret_20"] = hyg.pct_change(20, fill_method=None)
    out["credit_rel_20"] = hyg.pct_change(20, fill_method=None) - tlt.pct_change(20, fill_method=None)
    out["eq_vs_bond_20"] = spy.pct_change(20, fill_method=None) - tlt.pct_change(20, fill_method=None)

    h = max(int(horizon), 1)
    # Forward realized moves — evaluation only.
    f_eq = eq.shift(-h) / eq - 1.0
    f_spy = spy.shift(-h) / spy - 1.0
    f_tlt = tlt.shift(-h) / tlt - 1.0
    f_gold = gold.shift(-h) / gold - 1.0
    f_hyg = hyg.shift(-h) / hyg - 1.0
    f_vix = vix.shift(-h) / vix - 1.0

    # Scale forward moves by rolling historical dispersion computed strictly
    # from information available at t.  This keeps score magnitudes comparable.
    eq_scale = out["eq_ret_1"].rolling(126, min_periods=40).std(ddof=1) * sqrt(h)
    spy_ret1 = spy.pct_change(fill_method=None)
    tlt_ret1 = tlt.pct_change(fill_method=None)
    gold_ret1 = gold.pct_change(fill_method=None)
    hyg_ret1 = hyg.pct_change(fill_method=None)
    vix_ret1 = vix.pct_change(fill_method=None)

    def scaled(fwd: pd.Series, hist: pd.Series) -> pd.Series:
        scale = hist.rolling(126, min_periods=40).std(ddof=1) * sqrt(h)
        return fwd / scale.replace(0, np.nan)

    z_eq = f_eq / eq_scale.replace(0, np.nan)
    z_spy = scaled(f_spy, spy_ret1)
    z_tlt = scaled(f_tlt, tlt_ret1)
    z_gold = scaled(f_gold, gold_ret1)
    z_hyg = scaled(f_hyg, hyg_ret1)
    z_vix = scaled(f_vix, vix_ret1)

    score = pd.DataFrame(index=out.index)
    score["RISK-ON"] = 1.25 * z_eq + 0.55 * z_hyg + 0.35 * z_spy - 0.55 * z_vix - 0.15 * z_tlt
    score["RISK-OFF"] = -1.15 * z_eq - 0.75 * z_hyg + 0.75 * z_vix + 0.35 * z_tlt
    score["INFLATION"] = -0.25 * z_spy - 1.10 * z_tlt + 0.85 * z_gold + 0.20 * z_vix
    score["DEFLATION"] = -0.45 * z_spy + 1.20 * z_tlt - 0.20 * z_gold - 0.35 * z_hyg + 0.25 * z_vix

    valid_target = score.notna().all(axis=1)
    target = pd.Series(index=out.index, dtype=object)
    if valid_target.any():
        target.loc[valid_target] = score.loc[valid_target].idxmax(axis=1)
    out["target_regime"] = target
    # Keep score components and the top-vs-second margin for target-integrity
    # diagnostics. These are evaluation-only forward objects and never features.
    for _label in REGIME_LABELS:
        out[f"target_score_{_label.lower()}"] = score[_label]
    _score_values = score.to_numpy(dtype=float)
    _sorted = np.sort(_score_values, axis=1)
    _margin = np.where(valid_target.to_numpy(), _sorted[:, -1] - _sorted[:, -2], np.nan)
    out["target_margin"] = _margin

    # Raw forward values are retained for auditability but not used as inputs.
    out["fwd_eq"] = f_eq
    out["fwd_tlt"] = f_tlt
    out["fwd_gold"] = f_gold
    out["fwd_hyg"] = f_hyg
    out["fwd_vix"] = f_vix

    return out.replace([np.inf, -np.inf], np.nan)


def _standardize_fit(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x, dtype=float)
    mean = np.nanmean(x, axis=0)
    std = np.nanstd(x, axis=0, ddof=1)
    std = np.where(np.isfinite(std) & (std > 1e-8), std, 1.0)
    mean = np.where(np.isfinite(mean), mean, 0.0)
    return mean, std


def _standardize_apply(x: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    out = (np.asarray(x, dtype=float) - mean) / std
    return np.clip(np.nan_to_num(out, nan=0.0, posinf=6.0, neginf=-6.0), -8.0, 8.0)


def _gaussian_log_emission(x: np.ndarray, means: np.ndarray, variances: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    means = np.asarray(means, dtype=float)
    variances = np.clip(np.asarray(variances, dtype=float), 1e-5, None)
    diff = x[:, None, :] - means[None, :, :]
    return -0.5 * np.sum(np.log(2.0 * pi * variances)[None, :, :] + (diff * diff) / variances[None, :, :], axis=2)


def _forward_backward(
    log_emit: np.ndarray,
    transition: np.ndarray,
    initial: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float]:
    t_count, k = log_emit.shape
    log_a = np.log(np.clip(transition, _EPS, 1.0))
    log_pi = np.log(np.clip(initial, _EPS, 1.0))

    alpha = np.empty((t_count, k), dtype=float)
    alpha[0] = log_pi + log_emit[0]
    for t in range(1, t_count):
        alpha[t] = log_emit[t] + _logsumexp(alpha[t - 1][:, None] + log_a, axis=0)

    log_likelihood = float(_logsumexp(alpha[-1], axis=0))

    beta = np.zeros((t_count, k), dtype=float)
    for t in range(t_count - 2, -1, -1):
        beta[t] = _logsumexp(log_a + log_emit[t + 1][None, :] + beta[t + 1][None, :], axis=1)

    log_gamma = alpha + beta - log_likelihood
    gamma = np.exp(np.clip(log_gamma, -700, 30))
    gamma = gamma / np.clip(gamma.sum(axis=1, keepdims=True), _EPS, None)

    xi_sum = np.zeros((k, k), dtype=float)
    for t in range(t_count - 1):
        log_xi = alpha[t][:, None] + log_a + log_emit[t + 1][None, :] + beta[t + 1][None, :] - log_likelihood
        xi = np.exp(np.clip(log_xi, -700, 30))
        denom = float(xi.sum())
        if denom > 0:
            xi_sum += xi / denom
    return gamma, xi_sum, log_likelihood


def fit_gaussian_hmm(
    x: np.ndarray,
    n_states: int = 4,
    max_iter: int = 18,
    persistence: float = 0.90,
    seed: int = 7,
) -> dict[str, np.ndarray | float]:
    """Small diagonal-Gaussian HMM used only as a classical control."""
    x = np.asarray(x, dtype=float)
    if x.ndim != 2 or len(x) < max(40, n_states * 8):
        raise ValueError("insufficient observations for HMM")

    n_states = int(n_states)
    rng = np.random.default_rng(seed)
    # Deterministic spread along a low-dimensional score, with tiny jitter to
    # avoid duplicated centroids in flat samples.
    score = np.nanmean(x[:, : min(4, x.shape[1])], axis=1)
    order = np.argsort(score)
    positions = np.linspace(0, len(order) - 1, n_states).astype(int)
    means = x[order[positions]].copy() + rng.normal(0.0, 1e-3, size=(n_states, x.shape[1]))
    global_var = np.nanvar(x, axis=0, ddof=1)
    global_var = np.where(np.isfinite(global_var) & (global_var > 1e-4), global_var, 1.0)
    variances = np.tile(global_var, (n_states, 1))

    off = (1.0 - persistence) / max(n_states - 1, 1)
    transition = np.full((n_states, n_states), off, dtype=float)
    np.fill_diagonal(transition, persistence)
    initial = np.full(n_states, 1.0 / n_states, dtype=float)
    last_ll = -np.inf

    for _ in range(int(max_iter)):
        log_emit = _gaussian_log_emission(x, means, variances)
        gamma, xi_sum, ll = _forward_backward(log_emit, transition, initial)
        weights = np.clip(gamma.sum(axis=0), 1e-8, None)
        means = (gamma.T @ x) / weights[:, None]
        for j in range(n_states):
            diff = x - means[j]
            state_var = (gamma[:, j][:, None] * diff * diff).sum(axis=0) / weights[j]
            # Shrink toward the global variance so the classical control does
            # not become spuriously over-confident in small latent clusters.
            variances[j] = 0.78 * state_var + 0.22 * global_var
        variances = np.clip(variances, 0.04, 25.0)
        transition = xi_sum + 0.75 * np.eye(n_states) + 0.05
        transition = transition / np.clip(transition.sum(axis=1, keepdims=True), _EPS, None)
        initial = np.clip(gamma[0], 1e-6, None)
        initial = initial / initial.sum()
        if np.isfinite(last_ll) and abs(ll - last_ll) < 1e-4 * (1.0 + abs(last_ll)):
            break
        last_ll = ll

    return {
        "means": means,
        "variances": variances,
        "transition": transition,
        "initial": initial,
        "log_likelihood": float(last_ll),
    }


def hmm_filter_probabilities(model: dict[str, Any], x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    means = np.asarray(model["means"], dtype=float)
    variances = np.asarray(model["variances"], dtype=float)
    transition = np.asarray(model["transition"], dtype=float)
    state = np.asarray(model["initial"], dtype=float)
    log_emit = _gaussian_log_emission(x, means, variances)
    log_emit = log_emit - np.max(log_emit, axis=1, keepdims=True)
    emit = np.exp(np.clip(log_emit, -80, 0))
    probs = np.empty((len(x), len(state)), dtype=float)
    k = len(state)
    for t in range(len(x)):
        prior = state if t == 0 else state @ transition
        posterior = prior * emit[t]
        posterior = posterior / max(float(posterior.sum()), _EPS)
        # Small probability floor is a calibration safeguard, not a source of
        # alpha: it prevents an unsupervised classical model from receiving
        # absurd log-loss penalties from numerical certainty.
        posterior = 0.97 * posterior + 0.03 / k
        posterior = posterior / posterior.sum()
        probs[t] = posterior
        state = posterior
    return probs


def _best_state_mapping(hidden_probs: np.ndarray, target_codes: np.ndarray, n_states: int = 4) -> list[int]:
    from itertools import permutations

    hidden = np.argmax(hidden_probs, axis=1)
    best_perm = list(range(n_states))
    best_score = -1
    for perm in permutations(range(n_states)):
        pred = np.array([perm[s] for s in hidden], dtype=int)
        score = int(np.sum(pred == target_codes))
        if score > best_score:
            best_score = score
            best_perm = list(perm)
    return best_perm


def _remap_probabilities(probs: np.ndarray, mapping: list[int], n_classes: int = 4) -> np.ndarray:
    out = np.zeros((len(probs), n_classes), dtype=float)
    for hidden_state, class_code in enumerate(mapping):
        out[:, class_code] += probs[:, hidden_state]
    return out / np.clip(out.sum(axis=1, keepdims=True), _EPS, None)




def _temperature_scale_probabilities(probs: np.ndarray, temperature: float) -> np.ndarray:
    p = np.clip(np.asarray(probs, dtype=float), 1e-9, 1.0)
    t = max(float(temperature), 1e-3)
    logp = np.log(p) / t
    logp = logp - np.max(logp, axis=1, keepdims=True)
    out = np.exp(np.clip(logp, -60, 20))
    return out / np.clip(out.sum(axis=1, keepdims=True), _EPS, None)


def _fit_probability_temperature(probs: np.ndarray, y: np.ndarray) -> float:
    y = np.asarray(y, dtype=int)
    best_t = 1.0
    best_loss = np.inf
    for t in (0.65, 0.85, 1.0, 1.25, 1.5, 2.0, 2.75, 3.5, 5.0):
        scaled = _temperature_scale_probabilities(probs, t)
        loss = float(np.mean(-np.log(np.clip(scaled[np.arange(len(y)), y], 1e-9, 1.0))))
        if loss < best_loss:
            best_loss = loss
            best_t = float(t)
    return best_t

def _estimate_transition_from_codes(codes: np.ndarray, n_states: int = 4, smoothing: float = 0.75) -> np.ndarray:
    mat = np.full((n_states, n_states), float(smoothing), dtype=float)
    codes = np.asarray(codes, dtype=int)
    for a, b in zip(codes[:-1], codes[1:]):
        if 0 <= a < n_states and 0 <= b < n_states:
            mat[a, b] += 1.0
    mat += 1.25 * np.eye(n_states)
    return mat / np.clip(mat.sum(axis=1, keepdims=True), _EPS, None)


def fit_centroid_model(x: np.ndarray, y: np.ndarray, n_classes: int = 4) -> dict[str, Any]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=int)
    global_centroid = np.mean(x, axis=0)
    centroids = []
    priors = []
    for c in range(n_classes):
        mask = y == c
        centroids.append(np.mean(x[mask], axis=0) if mask.any() else global_centroid)
        priors.append(float(mask.mean()) if len(y) else 1.0 / n_classes)
    centroids = np.asarray(centroids, dtype=float)
    priors = np.clip(np.asarray(priors, dtype=float), 1e-4, None)
    priors /= priors.sum()

    best_temp = 1.0
    best_loss = np.inf
    for temp in (0.35, 0.55, 0.80, 1.00, 1.40, 2.00, 3.00):
        p = centroid_probabilities(x, {"centroids": centroids, "priors": priors, "temperature": temp})
        loss = float(np.mean(-np.log(np.clip(p[np.arange(len(y)), y], 1e-9, 1.0))))
        if loss < best_loss:
            best_loss = loss
            best_temp = temp
    return {"centroids": centroids, "priors": priors, "temperature": best_temp}


def centroid_probabilities(x: np.ndarray, model: dict[str, Any]) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    centroids = np.asarray(model["centroids"], dtype=float)
    priors = np.asarray(model.get("priors", np.full(len(centroids), 1.0 / len(centroids))), dtype=float)
    temperature = max(float(model.get("temperature", 1.0)), 1e-3)
    dist2 = np.sum((x[:, None, :] - centroids[None, :, :]) ** 2, axis=2)
    logits = -0.5 * dist2 / temperature + np.log(np.clip(priors, 1e-8, 1.0))[None, :]
    logits = logits - np.max(logits, axis=1, keepdims=True)
    p = np.exp(np.clip(logits, -60, 20))
    return p / np.clip(p.sum(axis=1, keepdims=True), _EPS, None)


def _phase_vector(x_row: np.ndarray, n_states: int = 4) -> np.ndarray:
    x = np.asarray(x_row, dtype=float)
    if len(x) == 0:
        return np.zeros(n_states)
    weights = np.empty((n_states, len(x)), dtype=float)
    for s in range(n_states):
        for j in range(len(x)):
            weights[s, j] = np.sin((s + 1) * (j + 1) * 0.71) + 0.5 * np.cos((s + 2) * (j + 1) * 0.37)
    raw = weights @ x / max(sqrt(len(x)), 1.0)
    return np.pi * np.tanh(raw / 3.0)


def _transition_hamiltonian(prob: np.ndarray, transition: np.ndarray, coupling: float) -> np.ndarray:
    prob = np.asarray(prob, dtype=float)
    transition = np.asarray(transition, dtype=float)
    k = len(prob)
    energy = -np.log(np.clip(prob, 1e-8, 1.0))
    energy = energy - float(np.mean(energy))
    h = np.diag(energy)
    for i in range(k):
        for j in range(i + 1, k):
            c = float(coupling) * sqrt(max(transition[i, j] * transition[j, i], 0.0))
            h[i, j] = c
            h[j, i] = c
    return h.astype(complex)


def quantum_density_probabilities(
    x: np.ndarray,
    centroid_model: dict[str, Any],
    transition: np.ndarray,
    decoherence: float = 0.12,
    coupling: float = 0.35,
    evolution_dt: float = 0.30,
    memory: float = 0.18,
) -> tuple[np.ndarray, list[np.ndarray], list[np.ndarray]]:
    """
    Calibrated quantum-like probability channel.

    Classical centroid probabilities are encoded as amplitudes; phase,
    density-matrix mixing and a transition-derived Hamiltonian are then applied.
    This is deliberately paired with the classical centroid control so any OOS
    difference isolates the density/Hamiltonian layer rather than the encoder.
    """
    x = np.asarray(x, dtype=float)
    classical_p = centroid_probabilities(x, centroid_model)
    k = classical_p.shape[1]
    output = np.empty_like(classical_p)
    rhos: list[np.ndarray] = []
    hamiltonians: list[np.ndarray] = []
    previous: np.ndarray | None = None

    for t in range(len(x)):
        p = classical_p[t]
        phases = _phase_vector(x[t], n_states=k)
        psi = np.sqrt(np.clip(p, 0.0, 1.0)) * np.exp(1j * phases)
        psi = psi / max(np.linalg.norm(psi), _EPS)
        rho_obs = np.outer(psi, np.conjugate(psi))
        rho_obs = (1.0 - decoherence) * rho_obs + decoherence * np.eye(k, dtype=complex) / k
        if previous is not None:
            rho = (1.0 - memory) * rho_obs + memory * previous
        else:
            rho = rho_obs
        rho = (rho + rho.conj().T) / 2.0
        rho /= max(float(np.trace(rho).real), _EPS)

        h = _transition_hamiltonian(p, transition, coupling=coupling)
        eigvals, eigvecs = np.linalg.eigh(h)
        u = eigvecs @ np.diag(np.exp(-1j * eigvals * float(evolution_dt))) @ eigvecs.conj().T
        rho = u @ rho @ u.conj().T
        gamma = float(np.clip(decoherence * evolution_dt * 0.25, 0.0, 0.40))
        rho = (1.0 - gamma) * rho + gamma * np.eye(k, dtype=complex) / k
        rho = (rho + rho.conj().T) / 2.0
        rho /= max(float(np.trace(rho).real), _EPS)
        prob = np.clip(np.real(np.diag(rho)), 0.0, 1.0)
        prob /= max(float(prob.sum()), _EPS)

        output[t] = prob
        rhos.append(rho)
        hamiltonians.append(h)
        previous = rho

    return output, rhos, hamiltonians


def _confusion_matrix(y: np.ndarray, pred: np.ndarray, n_classes: int = 4) -> np.ndarray:
    out = np.zeros((n_classes, n_classes), dtype=int)
    for true, guessed in zip(np.asarray(y, dtype=int), np.asarray(pred, dtype=int)):
        if 0 <= true < n_classes and 0 <= guessed < n_classes:
            out[int(true), int(guessed)] += 1
    return out


def _multiclass_mcc(confusion: np.ndarray) -> float:
    cmat = np.asarray(confusion, dtype=float)
    s = float(cmat.sum())
    if s <= 0:
        return np.nan
    c = float(np.trace(cmat))
    true_sum = cmat.sum(axis=1)
    pred_sum = cmat.sum(axis=0)
    numerator = c * s - float(np.dot(true_sum, pred_sum))
    denom = sqrt(max((s * s - float(np.dot(pred_sum, pred_sum))) * (s * s - float(np.dot(true_sum, true_sum))), 0.0))
    return float(numerator / denom) if denom > _EPS else 0.0


def _classification_diagnostics(probs: np.ndarray, y: np.ndarray) -> tuple[dict[str, float], pd.DataFrame, np.ndarray]:
    probs = np.asarray(probs, dtype=float)
    y = np.asarray(y, dtype=int)
    pred = np.argmax(probs, axis=1)
    conf = _confusion_matrix(y, pred, n_classes=probs.shape[1])
    supports = conf.sum(axis=1)
    predicted = conf.sum(axis=0)
    recalls: list[float] = []
    f1s: list[float] = []
    rows: list[dict[str, Any]] = []
    for i, label in enumerate(REGIME_LABELS[: probs.shape[1]]):
        tp = float(conf[i, i])
        support = float(supports[i])
        pred_count = float(predicted[i])
        recall = tp / support if support > 0 else np.nan
        precision = tp / pred_count if pred_count > 0 else np.nan
        f1 = (2.0 * precision * recall / (precision + recall)) if np.isfinite(precision) and np.isfinite(recall) and (precision + recall) > 0 else 0.0
        if support > 0:
            recalls.append(float(recall))
            f1s.append(float(f1))
        rows.append(
            {
                "Regime": label,
                "Support": int(support),
                "Prevalence": support / max(float(len(y)), 1.0),
                "Precision": float(precision) if np.isfinite(precision) else np.nan,
                "Recall": float(recall) if np.isfinite(recall) else np.nan,
                "F1": float(f1),
                "Predicted Share": pred_count / max(float(len(y)), 1.0),
            }
        )
    return {
        "Balanced Accuracy": float(np.mean(recalls)) if recalls else np.nan,
        "Macro F1": float(np.mean(f1s)) if f1s else np.nan,
        "MCC": _multiclass_mcc(conf),
    }, pd.DataFrame(rows), conf


def _confidence_calibration(probs: np.ndarray, y: np.ndarray, bins: int = 10) -> tuple[float, pd.DataFrame]:
    probs = np.asarray(probs, dtype=float)
    y = np.asarray(y, dtype=int)
    pred = np.argmax(probs, axis=1)
    confidence = np.max(probs, axis=1)
    correct = (pred == y).astype(float)
    edges = np.linspace(0.0, 1.0, int(max(3, bins)) + 1)
    rows: list[dict[str, Any]] = []
    ece = 0.0
    n = max(len(y), 1)
    for b in range(len(edges) - 1):
        lo, hi = float(edges[b]), float(edges[b + 1])
        mask = (confidence >= lo) & (confidence < hi if b < len(edges) - 2 else confidence <= hi)
        if not mask.any():
            continue
        avg_conf = float(np.mean(confidence[mask]))
        empirical = float(np.mean(correct[mask]))
        count = int(mask.sum())
        ece += (count / n) * abs(avg_conf - empirical)
        rows.append({"Bin Low": lo, "Bin High": hi, "Count": count, "Mean Confidence": avg_conf, "Empirical Accuracy": empirical, "Calibration Gap": empirical - avg_conf})
    return float(ece), pd.DataFrame(rows)


def _metric_row(name: str, probs: np.ndarray, y: np.ndarray, dates: pd.Index) -> tuple[dict[str, Any], np.ndarray]:
    probs = np.asarray(probs, dtype=float)
    y = np.asarray(y, dtype=int)
    probs = probs / np.clip(probs.sum(axis=1, keepdims=True), _EPS, None)
    pred = np.argmax(probs, axis=1)
    true_p = np.clip(probs[np.arange(len(y)), y], 1e-9, 1.0)
    log_losses = -np.log(true_p)
    onehot = np.eye(probs.shape[1])[y]
    brier = float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))
    accuracy = float(np.mean(pred == y))
    confidence = float(np.mean(np.max(probs, axis=1)))

    transitions = np.zeros(len(y), dtype=bool)
    if len(y) > 1:
        transitions[1:] = y[1:] != y[:-1]
    transition_accuracy = float(np.mean(pred[transitions] == y[transitions])) if transitions.any() else np.nan
    risk_off_code = REGIME_LABELS.index("RISK-OFF")
    stress_mask = y == risk_off_code
    stress_recall = float(np.mean(pred[stress_mask] == risk_off_code)) if stress_mask.any() else np.nan
    cls_diag, _, _ = _classification_diagnostics(probs, y)
    ece, _ = _confidence_calibration(probs, y, bins=10)

    row = {
        "Model": name,
        "OOS Log Loss": float(np.mean(log_losses)),
        "Brier Score": brier,
        "Accuracy": accuracy,
        "Balanced Accuracy": cls_diag["Balanced Accuracy"],
        "Macro F1": cls_diag["Macro F1"],
        "MCC": cls_diag["MCC"],
        "ECE": ece,
        "Transition Accuracy": transition_accuracy,
        "Risk-Off Recall": stress_recall,
        "Mean Confidence": confidence,
        "Observations": int(len(y)),
        "Start": pd.Timestamp(dates[0]) if len(dates) else pd.NaT,
        "End": pd.Timestamp(dates[-1]) if len(dates) else pd.NaT,
    }
    return row, log_losses


def _bootstrap_delta(loss_quantum: np.ndarray, loss_control: np.ndarray, seed: int = 19, draws: int = 900) -> dict[str, float]:
    q = np.asarray(loss_quantum, dtype=float)
    c = np.asarray(loss_control, dtype=float)
    n = min(len(q), len(c))
    if n < 20:
        return {"delta": np.nan, "ci_low": np.nan, "ci_high": np.nan, "p_value": np.nan}
    diff = c[:n] - q[:n]  # positive => quantum lower loss / better
    rng = np.random.default_rng(seed)
    stats = np.empty(draws, dtype=float)
    for i in range(draws):
        idx = rng.integers(0, n, size=n)
        stats[i] = float(np.mean(diff[idx]))
    p_left = float(np.mean(stats <= 0.0))
    p_right = float(np.mean(stats >= 0.0))
    return {
        "delta": float(np.mean(diff)),
        "ci_low": float(np.quantile(stats, 0.025)),
        "ci_high": float(np.quantile(stats, 0.975)),
        "p_value": float(min(1.0, 2.0 * min(p_left, p_right))),
    }



def _effective_sample_size(diff: np.ndarray, max_lag: int = 40) -> dict[str, float]:
    """Autocorrelation-adjusted effective sample size for the loss differential.

    Uses a conservative positive-sequence truncation: once the estimated
    autocorrelation becomes non-positive, later lags are ignored.
    """
    x = np.asarray(diff, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 5:
        return {"nominal_n": float(n), "effective_n": float(n), "inflation_factor": 1.0, "max_lag_used": 0.0}
    x = x - float(np.mean(x))
    var = float(np.dot(x, x) / n)
    if var <= _EPS:
        return {"nominal_n": float(n), "effective_n": float(n), "inflation_factor": 1.0, "max_lag_used": 0.0}
    rho_sum = 0.0
    used = 0
    for lag in range(1, min(int(max_lag), n - 1) + 1):
        rho = float(np.dot(x[:-lag], x[lag:]) / ((n - lag) * var))
        if not np.isfinite(rho) or rho <= 0.0:
            break
        rho_sum += rho
        used = lag
    inflation = max(1.0, 1.0 + 2.0 * rho_sum)
    neff = float(np.clip(n / inflation, 1.0, n))
    return {
        "nominal_n": float(n),
        "effective_n": neff,
        "inflation_factor": float(inflation),
        "max_lag_used": float(used),
    }


def _block_bootstrap_delta(
    loss_quantum: np.ndarray,
    loss_control: np.ndarray,
    block_lengths: tuple[int, ...] = (5, 10, 20, 40),
    draws: int = 900,
    seed: int = 97,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Circular block bootstrap for dependent OOS loss differentials.

    Positive delta means the classical control has higher log loss, hence the
    quantum-like model is better.  The conservative result uses the weakest
    lower confidence bound and largest p-value across requested block lengths.
    """
    q = np.asarray(loss_quantum, dtype=float)
    c = np.asarray(loss_control, dtype=float)
    n = min(len(q), len(c))
    if n < 30:
        empty = pd.DataFrame(columns=["Block Length", "Delta LL", "CI Low", "CI High", "p-value"])
        return empty, {"delta": np.nan, "ci_low": np.nan, "ci_high": np.nan, "p_value": np.nan, "block_length": np.nan}
    diff = c[:n] - q[:n]
    rows: list[dict[str, float]] = []
    for idx, b0 in enumerate(block_lengths):
        b = max(2, min(int(b0), n))
        rng = np.random.default_rng(int(seed + 101 * idx))
        stats = np.empty(int(draws), dtype=float)
        for d in range(int(draws)):
            out: list[float] = []
            while len(out) < n:
                start = int(rng.integers(0, n))
                out.extend(diff[(start + np.arange(b)) % n].tolist())
            stats[d] = float(np.mean(out[:n]))
        p_left = float(np.mean(stats <= 0.0))
        p_right = float(np.mean(stats >= 0.0))
        rows.append(
            {
                "Block Length": float(b),
                "Delta LL": float(np.mean(diff)),
                "CI Low": float(np.quantile(stats, 0.025)),
                "CI High": float(np.quantile(stats, 0.975)),
                "p-value": float(min(1.0, 2.0 * min(p_left, p_right))),
            }
        )
    table = pd.DataFrame(rows)
    # Most conservative evidence across dependence assumptions.
    weakest = table.sort_values(["CI Low", "p-value"], ascending=[True, False]).iloc[0]
    conservative = {
        "delta": float(np.mean(diff)),
        "ci_low": float(table["CI Low"].min()),
        "ci_high": float(table["CI High"].max()),
        "p_value": float(table["p-value"].max()),
        "block_length": float(weakest["Block Length"]),
    }
    return table, conservative


def _purge_audit_row(
    dates: pd.Index,
    train_end: int,
    test_start: int,
    horizon: int,
    block_end: int,
) -> dict[str, Any]:
    if train_end <= 0 or test_start >= len(dates):
        return {}
    last_feature_idx = train_end - 1
    last_realization_idx = min(last_feature_idx + int(max(1, horizon)), len(dates) - 1)
    first_test_idx = test_start
    last_feature_date = pd.Timestamp(dates[last_feature_idx])
    last_realization_date = pd.Timestamp(dates[last_realization_idx])
    first_test_date = pd.Timestamp(dates[first_test_idx])
    return {
        "Train Rows": int(train_end),
        "Purge Gap": int(max(1, horizon)),
        "Last Training Feature Date": last_feature_date,
        "Last Training Label Realization Date": last_realization_date,
        "First Test Date": first_test_date,
        "Test End Date": pd.Timestamp(dates[min(block_end - 1, len(dates) - 1)]),
        "Leakage Free": bool(last_realization_date < first_test_date),
    }


def _factor_attribution(latest_x: np.ndarray, centroid_model: dict[str, Any], feature_names: list[str]) -> pd.DataFrame:
    centroids = np.asarray(centroid_model["centroids"], dtype=float)
    p = centroid_probabilities(np.asarray(latest_x, dtype=float).reshape(1, -1), centroid_model)[0]
    dominant = int(np.argmax(p))
    x = np.asarray(latest_x, dtype=float)
    dom_dist = (x - centroids[dominant]) ** 2
    others = np.mean(np.delete((x[None, :] - centroids) ** 2, dominant, axis=0), axis=0)
    contribution = 0.5 * (others - dom_dist)
    rows = []
    for name, value, contrib in zip(feature_names, x, contribution):
        rows.append({"Factor": name, "Standardized Input": float(value), "Dominant-State Contribution": float(contrib)})
    frame = pd.DataFrame(rows)
    frame["Absolute Contribution"] = frame["Dominant-State Contribution"].abs()
    return frame.sort_values("Absolute Contribution", ascending=False).drop(columns=["Absolute Contribution"])


def _factor_concentration(attribution: pd.DataFrame) -> dict[str, float]:
    if attribution is None or attribution.empty:
        return {"hhi": np.nan, "effective_factors": np.nan, "top_share": np.nan}
    weights = np.abs(pd.to_numeric(attribution["Dominant-State Contribution"], errors="coerce").fillna(0.0).to_numpy(dtype=float))
    total = float(weights.sum())
    if total <= _EPS:
        return {"hhi": 0.0, "effective_factors": float(len(weights)), "top_share": 0.0}
    shares = weights / total
    hhi = float(np.sum(shares * shares))
    return {"hhi": hhi, "effective_factors": float(1.0 / max(hhi, _EPS)), "top_share": float(np.max(shares))}


def _factor_ablation(
    latest_x: np.ndarray,
    centroid_model: dict[str, Any],
    transition: np.ndarray,
    feature_names: list[str],
    base_quantum: np.ndarray,
    decoherence: float,
    coupling: float,
    evolution_dt: float,
) -> pd.DataFrame:
    x = np.asarray(latest_x, dtype=float).reshape(1, -1)
    base = np.asarray(base_quantum, dtype=float)
    dominant = int(np.argmax(base))
    rows: list[dict[str, Any]] = []
    for j, name in enumerate(feature_names):
        ablated = x.copy()
        ablated[0, j] = 0.0  # training-center value in standardized coordinates
        c_prob = centroid_probabilities(ablated, centroid_model)[0]
        q_prob, _, _ = quantum_density_probabilities(
            ablated,
            centroid_model,
            transition,
            decoherence=decoherence,
            coupling=coupling,
            evolution_dt=evolution_dt,
            memory=0.0,
        )
        q = q_prob[0]
        rows.append(
            {
                "Factor": name,
                "Base Dominant": REGIME_LABELS[dominant],
                "Ablated Dominant": REGIME_LABELS[int(np.argmax(q))],
                "Δ Dominant Probability": float(q[dominant] - base[dominant]),
                "L1 Probability Shift": float(np.sum(np.abs(q - base))),
                "Classical Dominant After Ablation": REGIME_LABELS[int(np.argmax(c_prob))],
            }
        )
    return pd.DataFrame(rows).sort_values("L1 Probability Shift", ascending=False).reset_index(drop=True)


def _hamiltonian_diagnostics(h: np.ndarray) -> dict[str, Any]:
    hermitian = (np.asarray(h, dtype=complex) + np.asarray(h, dtype=complex).conj().T) / 2.0
    eigvals, eigvecs = np.linalg.eigh(hermitian)
    eigvals = np.real(eigvals)
    order = np.argsort(eigvals)
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]
    gaps = np.diff(eigvals) if len(eigvals) > 1 else np.array([], dtype=float)
    return {
        "eigenvalues": eigvals,
        "eigenvectors": eigvecs,
        "spectral_gap": float(gaps[0]) if len(gaps) else np.nan,
        "minimum_gap": float(np.min(np.abs(gaps))) if len(gaps) else np.nan,
        "operator_norm": float(np.max(np.abs(eigvals))) if len(eigvals) else 0.0,
        "frobenius_norm": float(np.linalg.norm(hermitian, ord="fro")),
        "trace": float(np.trace(hermitian).real),
    }


def _class_imbalance_diagnostics(y: np.ndarray) -> pd.DataFrame:
    y = np.asarray(y, dtype=int)
    counts = np.bincount(y, minlength=len(REGIME_LABELS)).astype(float)
    total = max(float(counts.sum()), 1.0)
    prevalence = counts / total
    nonzero = counts[counts > 0]
    imbalance_ratio = float(nonzero.max() / nonzero.min()) if len(nonzero) else np.nan
    entropy = float(-np.sum(prevalence[prevalence > 0] * np.log(prevalence[prevalence > 0])) / log(len(REGIME_LABELS))) if len(REGIME_LABELS) > 1 else 0.0
    rows = [
        {"Regime": label, "Count": int(counts[i]), "Prevalence": float(prevalence[i]), "Imbalance Ratio": imbalance_ratio, "Normalized Class Entropy": entropy}
        for i, label in enumerate(REGIME_LABELS)
    ]
    return pd.DataFrame(rows)


def _transition_lead_diagnostics(predictions: pd.DataFrame, model_names: list[str], lookback: int = 10, threshold: float = 0.40) -> tuple[pd.DataFrame, pd.DataFrame]:
    if predictions is None or predictions.empty:
        return pd.DataFrame(), pd.DataFrame()
    target_codes = np.array([REGIME_LABELS.index(x) for x in predictions["Target"]], dtype=int)
    transition_idx = np.where(np.r_[False, target_codes[1:] != target_codes[:-1]])[0]
    summaries: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for name in model_names:
        leads: list[float] = []
        hits = 0
        for idx in transition_idx:
            new_code = int(target_codes[idx])
            new_label = REGIME_LABELS[new_code]
            start = max(0, idx - int(max(1, lookback)))
            prob_col = f"{name} · {new_label}"
            pred_col = f"{name} · Pred"
            detected: int | None = None
            for j in range(start, idx + 1):
                p = float(predictions.iloc[j][prob_col])
                guessed = str(predictions.iloc[j][pred_col])
                if guessed == new_label or p >= float(threshold):
                    detected = j
                    break
            if detected is not None:
                lead = float(idx - detected)
                hits += 1
                leads.append(lead)
            else:
                lead = np.nan
            if name == "Quantum Density":
                events.append(
                    {
                        "Transition Date": predictions.index[idx],
                        "New Proxy Regime": new_label,
                        "Lead Days": lead,
                        "Detected": detected is not None,
                        "Probability at Transition": float(predictions.iloc[idx][prob_col]),
                    }
                )
        summaries.append(
            {
                "Model": name,
                "Transitions": int(len(transition_idx)),
                "Detection Rate": float(hits / len(transition_idx)) if len(transition_idx) else np.nan,
                "Mean Lead Days": float(np.mean(leads)) if leads else np.nan,
                "Median Lead Days": float(np.median(leads)) if leads else np.nan,
            }
        )
    return pd.DataFrame(summaries), pd.DataFrame(events)


def _validation_level(metrics: pd.DataFrame, bootstrap: dict[str, float], best_classical: str) -> dict[str, Any]:
    q = metrics.loc[metrics["Model"] == "Quantum Density"].iloc[0]
    prior = metrics.loc[metrics["Model"] == "Historical Prior"].iloc[0]
    classical = metrics.loc[metrics["Model"] == best_classical].iloc[0]
    beats_prior = float(q["OOS Log Loss"]) < float(prior["OOS Log Loss"]) and float(q["Brier Score"]) < float(prior["Brier Score"])
    beats_classical = float(q["OOS Log Loss"]) < float(classical["OOS Log Loss"])
    robust = bool(np.isfinite(float(bootstrap.get("ci_low", np.nan))) and float(bootstrap.get("ci_low", np.nan)) > 0 and float(bootstrap.get("p_value", 1.0)) < 0.05)
    if not beats_prior:
        return {"level": 0, "label": "FAILS NAIVE BASELINE", "detail": "Quantum Density does not beat the point-in-time Historical Prior on both proper scoring rules."}
    if not beats_classical:
        return {"level": 1, "label": "BEATS NAIVE BASELINE", "detail": "The model clears the point-in-time prior, but not the strongest learned classical control."}
    if not robust:
        return {"level": 2, "label": "BEATS CLASSICAL MODEL", "detail": "Observed OOS log-loss edge versus the strongest learned classical control is not yet statistically robust."}
    return {"level": 3, "label": "DEPENDENCY-ROBUST OOS EDGE", "detail": "The observed OOS log-loss edge remains positive under the conservative 5/10/20/40-day circular block-bootstrap diagnostic. Economic significance remains untested."}


def _scaler_fit(x: np.ndarray, method: str = "standard") -> tuple[np.ndarray, np.ndarray]:
    arr = np.asarray(x, dtype=float)
    if str(method).lower().startswith("robust"):
        center = np.nanmedian(arr, axis=0)
        q25 = np.nanquantile(arr, 0.25, axis=0)
        q75 = np.nanquantile(arr, 0.75, axis=0)
        scale = (q75 - q25) / 1.349
        scale = np.where(np.isfinite(scale) & (scale > 1e-8), scale, np.nanstd(arr, axis=0, ddof=1))
        scale = np.where(np.isfinite(scale) & (scale > 1e-8), scale, 1.0)
        center = np.where(np.isfinite(center), center, 0.0)
        return center, scale
    return _standardize_fit(arr)


def _scaler_apply(x: np.ndarray, center: np.ndarray, scale: np.ndarray, winsor_z: float = 8.0) -> np.ndarray:
    z = (np.asarray(x, dtype=float) - center) / scale
    limit = float(np.clip(winsor_z, 2.0, 12.0))
    return np.clip(np.nan_to_num(z, nan=0.0, posinf=limit, neginf=-limit), -limit, limit)



# ============================================================
# QUANTUM REGIME ENGINE V2.2.1 — PURGED OOS + DEPENDENCY-AWARE VALIDATION
# ============================================================

def apply_regime_hysteresis(
    labels: pd.Series,
    confirmation_days: int = 3,
    min_dwell: int = 5,
) -> pd.Series:
    """Causal persistence filter on the evaluation-label timeline.

    The raw label at t is already a forward evaluation construct.  This filter
    only uses the current/past raw-label sequence to reduce label chattering;
    it is never fed into the point-in-time feature matrix.
    """
    src = pd.Series(labels, copy=True)
    out = pd.Series(index=src.index, dtype=object)
    confirm = max(1, int(confirmation_days))
    dwell_floor = max(1, int(min_dwell))
    current: str | None = None
    current_dwell = 0
    candidate: str | None = None
    candidate_count = 0
    for i, value in enumerate(src.astype(object).tolist()):
        label = str(value) if value in REGIME_LABELS else None
        if label is None:
            out.iloc[i] = np.nan
            continue
        if current is None:
            current = label
            current_dwell = 1
            candidate = None
            candidate_count = 0
            out.iloc[i] = current
            continue
        if label == current:
            current_dwell += 1
            candidate = None
            candidate_count = 0
            out.iloc[i] = current
            continue
        if candidate == label:
            candidate_count += 1
        else:
            candidate = label
            candidate_count = 1
        if current_dwell >= dwell_floor and candidate_count >= confirm:
            current = label
            current_dwell = 1
            candidate = None
            candidate_count = 0
        else:
            current_dwell += 1
        out.iloc[i] = current
    return out


def _dwell_lengths(labels: pd.Series) -> list[int]:
    vals = [str(x) for x in pd.Series(labels).dropna().tolist() if str(x) in REGIME_LABELS]
    if not vals:
        return []
    runs: list[int] = []
    run = 1
    for prev, cur in zip(vals[:-1], vals[1:]):
        if cur == prev:
            run += 1
        else:
            runs.append(run)
            run = 1
    runs.append(run)
    return runs


def target_integrity_metrics(
    labels: pd.Series,
    horizon: int,
    margin: pd.Series | None = None,
) -> dict[str, Any]:
    series = pd.Series(labels).dropna()
    series = series[series.astype(str).isin(REGIME_LABELS)]
    n = int(len(series))
    if n < 2:
        return {"observations": n, "status": "INSUFFICIENT"}
    vals = series.astype(str).to_numpy()
    transitions = int(np.sum(vals[1:] != vals[:-1]))
    transition_rate = transitions / max(n - 1, 1)
    dwells = _dwell_lengths(series)
    counts = np.array([(vals == label).sum() for label in REGIME_LABELS], dtype=float)
    prevalence = counts / max(float(counts.sum()), 1.0)
    nz = prevalence[prevalence > 0]
    entropy = float(-np.sum(nz * np.log(nz)) / log(len(REGIME_LABELS))) if len(nz) else 0.0
    dominant_share = float(prevalence.max()) if len(prevalence) else np.nan
    margin_median = np.nan
    low_margin_share = np.nan
    if margin is not None:
        m = pd.to_numeric(pd.Series(margin).reindex(series.index), errors="coerce").dropna()
        if not m.empty:
            margin_median = float(m.median())
            # A dimensionless score-gap below 0.35 is treated as ambiguous.
            low_margin_share = float((m < 0.35).mean())

    transition_gate = "PASS" if transition_rate <= 0.12 else "WARN" if transition_rate <= 0.22 else "FAIL"
    dwell_target = max(3.0, min(12.0, float(max(int(horizon), 1)) / 2.0))
    median_dwell = float(np.median(dwells)) if dwells else np.nan
    dwell_gate = "PASS" if median_dwell >= dwell_target else "WARN" if median_dwell >= max(2.0, dwell_target * 0.6) else "FAIL"
    entropy_gate = "PASS" if entropy >= 0.75 else "WARN" if entropy >= 0.60 else "FAIL"
    margin_gate = "PASS"
    if np.isfinite(low_margin_share):
        margin_gate = "PASS" if low_margin_share <= 0.35 else "WARN" if low_margin_share <= 0.50 else "FAIL"
    gates = [transition_gate, dwell_gate, entropy_gate, margin_gate]
    status = "FAIL" if "FAIL" in gates else "WARN" if "WARN" in gates else "PASS"
    return {
        "observations": n,
        "transitions": transitions,
        "transition_rate": float(transition_rate),
        "persistence": float(1.0 - transition_rate),
        "mean_dwell": float(np.mean(dwells)) if dwells else np.nan,
        "median_dwell": median_dwell,
        "p10_dwell": float(np.quantile(dwells, 0.10)) if dwells else np.nan,
        "max_dwell": float(np.max(dwells)) if dwells else np.nan,
        "class_entropy": entropy,
        "dominant_share": dominant_share,
        "forward_window_overlap": float(max(0.0, 1.0 - 1.0 / max(int(horizon), 1))),
        "independent_window_fraction": float(1.0 / max(int(horizon), 1)),
        "median_score_margin": margin_median,
        "low_margin_share": low_margin_share,
        "transition_gate": transition_gate,
        "dwell_gate": dwell_gate,
        "entropy_gate": entropy_gate,
        "margin_gate": margin_gate,
        "status": status,
    }


def target_integrity_grid(
    market_frame: pd.DataFrame,
    horizons: Iterable[int] = (5, 10, 20, 63),
    confirmation_days: int = 3,
    min_dwell: int = 5,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for h in horizons:
        ff = prepare_regime_feature_frame(market_frame, horizon=int(h))
        if ff.empty or "target_regime" not in ff:
            continue
        raw = ff["target_regime"]
        persistent = apply_regime_hysteresis(raw, confirmation_days=confirmation_days, min_dwell=min_dwell)
        for mode, labels in (("RAW", raw), ("PERSISTENT", persistent)):
            m = target_integrity_metrics(labels, horizon=int(h), margin=ff.get("target_margin"))
            rows.append({"Horizon": int(h), "Target": mode, **m})
    return pd.DataFrame(rows)


def _live_regime_state_from_frame(
    feature_frame: pd.DataFrame,
    target_mode: str = "persistent",
    confirmation_days: int = 3,
    min_dwell: int = 5,
    scaler: str = "standard",
    winsor_z: float = 8.0,
    decoherence: float = 0.12,
    coupling: float = 0.35,
    evolution_dt: float = 0.30,
) -> dict[str, Any]:
    feature_names = [c for c in V2_FEATURE_COLUMNS if c in feature_frame.columns]
    if len(feature_names) < 6:
        return {"available": False}
    labels = feature_frame["target_regime"].copy()
    if str(target_mode).lower().startswith("persist"):
        labels = apply_regime_hysteresis(labels, confirmation_days=confirmation_days, min_dwell=min_dwell)
    work = feature_frame[feature_names].copy()
    work["target_regime"] = labels
    sample = work.dropna()
    if len(sample) < 180:
        return {"available": False}
    label_to_code = {label: i for i, label in enumerate(REGIME_LABELS)}
    y = sample["target_regime"].map(label_to_code).to_numpy(dtype=int)
    x_raw = sample[feature_names].to_numpy(dtype=float)
    center, scale = _scaler_fit(x_raw, method=scaler)
    x = _scaler_apply(x_raw, center, scale, winsor_z=winsor_z)
    centroid = fit_centroid_model(x, y, n_classes=4)
    transition = _estimate_transition_from_codes(y, n_states=4)
    latest = feature_frame[feature_names].dropna().iloc[-1].to_numpy(dtype=float).reshape(1, -1)
    latest_x = _scaler_apply(latest, center, scale, winsor_z=winsor_z)
    q, rhos, hs = quantum_density_probabilities(latest_x, centroid, transition, decoherence=decoherence, coupling=coupling, evolution_dt=evolution_dt, memory=0.0)
    c = centroid_probabilities(latest_x, centroid)[0]
    return {
        "available": True,
        "probabilities": q[0],
        "classical_probabilities": c,
        "dominant": REGIME_LABELS[int(np.argmax(q[0]))],
        "dominant_probability": float(np.max(q[0])),
        "entropy": von_neumann_entropy(rhos[-1], normalized=True),
        "purity": purity(rhos[-1]),
        "spectral_gap": _hamiltonian_diagnostics(hs[-1]).get("spectral_gap", np.nan),
        "observations": int(len(sample)),
    }


def multi_horizon_regime_stack(
    market_frame: pd.DataFrame,
    horizons: Iterable[int] = (5, 20, 63),
    target_mode: str = "persistent",
    confirmation_days: int = 3,
    min_dwell: int = 5,
    scaler: str = "standard",
    winsor_z: float = 8.0,
    decoherence: float = 0.12,
    coupling: float = 0.35,
    evolution_dt: float = 0.30,
) -> tuple[pd.DataFrame, dict[int, np.ndarray]]:
    rows: list[dict[str, Any]] = []
    prob_map: dict[int, np.ndarray] = {}
    labels_map = {5: "TACTICAL", 20: "CYCLICAL", 63: "STRUCTURAL"}
    for h in horizons:
        ff = prepare_regime_feature_frame(market_frame, horizon=int(h))
        state = _live_regime_state_from_frame(ff, target_mode=target_mode, confirmation_days=confirmation_days, min_dwell=min_dwell, scaler=scaler, winsor_z=winsor_z, decoherence=decoherence, coupling=coupling, evolution_dt=evolution_dt)
        if not state.get("available"):
            continue
        p = np.asarray(state["probabilities"], dtype=float)
        prob_map[int(h)] = p
        rows.append({
            "Layer": labels_map.get(int(h), f"{int(h)}D"),
            "Horizon": int(h),
            "Dominant Regime": state["dominant"],
            "Dominant Probability": state["dominant_probability"],
            "Entropy": state["entropy"],
            "Purity": state["purity"],
            "Spectral Gap": state["spectral_gap"],
            "Calibration Observations": state["observations"],
        })
    return pd.DataFrame(rows), prob_map


def _classwise_calibration(probs: np.ndarray, y: np.ndarray, bins: int = 10) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    probs = np.asarray(probs, dtype=float)
    y = np.asarray(y, dtype=int)
    summary: list[dict[str, Any]] = []
    curves: dict[str, pd.DataFrame] = {}
    edges = np.linspace(0.0, 1.0, int(max(3, bins)) + 1)
    n = max(len(y), 1)
    for k, label in enumerate(REGIME_LABELS):
        pk = probs[:, k]
        actual = (y == k).astype(float)
        ece = 0.0
        rows: list[dict[str, Any]] = []
        for b in range(len(edges) - 1):
            lo, hi = edges[b], edges[b + 1]
            mask = (pk >= lo) & (pk < hi if b < len(edges) - 2 else pk <= hi)
            if not mask.any():
                continue
            mp = float(np.mean(pk[mask])); freq = float(np.mean(actual[mask])); count = int(mask.sum())
            ece += count / n * abs(mp - freq)
            rows.append({"Bin Low": lo, "Bin High": hi, "Count": count, "Mean Probability": mp, "Observed Frequency": freq})
        brier = float(np.mean((pk - actual) ** 2))
        summary.append({"Regime": label, "Classwise ECE": float(ece), "Classwise Brier": brier, "Mean Probability": float(np.mean(pk)), "Observed Prevalence": float(np.mean(actual))})
        curves[label] = pd.DataFrame(rows)
    return pd.DataFrame(summary), curves


def _economic_return_metrics(net_returns: pd.Series, turnover: pd.Series, gamma: float = 5.0) -> dict[str, float]:
    r = pd.to_numeric(net_returns, errors="coerce").dropna()
    to = pd.to_numeric(turnover, errors="coerce").reindex(r.index).fillna(0.0)
    if len(r) < 20:
        return {k: np.nan for k in ["CAGR", "Ann Vol", "Sharpe", "Sortino", "Max Drawdown", "CVaR 95", "Ann Turnover", "CEQ"]}
    wealth = (1.0 + r).cumprod()
    years = len(r) / 252.0
    cagr = float(wealth.iloc[-1] ** (1.0 / max(years, _EPS)) - 1.0) if wealth.iloc[-1] > 0 else -1.0
    vol = float(r.std(ddof=1) * sqrt(252.0))
    sharpe = float(r.mean() / max(r.std(ddof=1), _EPS) * sqrt(252.0))
    downside = r[r < 0]
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else np.nan
    sortino = float(r.mean() / max(downside_std, _EPS) * sqrt(252.0)) if np.isfinite(downside_std) else np.nan
    dd = wealth / wealth.cummax() - 1.0
    q = float(r.quantile(0.05))
    cvar = float(r[r <= q].mean()) if (r <= q).any() else q
    ann_var = float(r.var(ddof=1) * 252.0)
    ceq = float(r.mean() * 252.0 - 0.5 * float(gamma) * ann_var)
    return {"CAGR": cagr, "Ann Vol": vol, "Sharpe": sharpe, "Sortino": sortino, "Max Drawdown": float(dd.min()), "CVaR 95": cvar, "Ann Turnover": float(to.mean() * 252.0), "CEQ": ceq}


def _circular_block_bootstrap_mean(diff: np.ndarray, block: int = 10, draws: int = 800, seed: int = 71) -> dict[str, float]:
    x = np.asarray(diff, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 40:
        return {"delta_ann_return": np.nan, "ci_low": np.nan, "ci_high": np.nan, "p_value": np.nan}
    b = max(2, min(int(block), n))
    rng = np.random.default_rng(seed)
    vals = np.empty(draws, dtype=float)
    for d in range(draws):
        out: list[float] = []
        while len(out) < n:
            start = int(rng.integers(0, n))
            out.extend([x[(start + j) % n] for j in range(b)])
        vals[d] = float(np.mean(out[:n]) * 252.0)
    p_left = float(np.mean(vals <= 0.0)); p_right = float(np.mean(vals >= 0.0))
    return {"delta_ann_return": float(np.mean(x) * 252.0), "ci_low": float(np.quantile(vals, 0.025)), "ci_high": float(np.quantile(vals, 0.975)), "p_value": float(min(1.0, 2.0 * min(p_left, p_right)))}


def economic_utility_benchmark(
    market_frame: pd.DataFrame,
    predictions: pd.DataFrame,
    model_names: Iterable[str],
    transaction_cost_bps: float = 5.0,
    gamma: float = 5.0,
) -> dict[str, Any]:
    if predictions is None or predictions.empty or market_frame is None or market_frame.empty:
        return {"available": False, "reason": "Prediction/price alignment unavailable."}
    prices = market_frame.copy()
    if "date" in prices.columns:
        prices["date"] = pd.to_datetime(prices["date"], errors="coerce"); prices = prices.set_index("date")
    prices.index = pd.to_datetime(prices.index, errors="coerce")
    eq_col = "PRIMARY" if "PRIMARY" in prices.columns else "SPY" if "SPY" in prices.columns else None
    needed = [eq_col, "TLT", "GLD", "HYG"]
    if eq_col is None or any(c not in prices.columns for c in needed if c is not None):
        return {"available": False, "reason": "Need PRIMARY/SPY, TLT, GLD and HYG for utility benchmark."}
    px = prices[[eq_col, "TLT", "GLD", "HYG"]].apply(pd.to_numeric, errors="coerce")
    px.columns = ["EQUITY", "TLT", "GLD", "HYG"]
    next_ret = px.pct_change(fill_method=None).shift(-1).reindex(predictions.index)
    regime_weights = np.array([
        [0.65, 0.05, 0.05, 0.25],  # Risk-On
        [0.10, 0.45, 0.30, 0.15],  # Risk-Off
        [0.25, 0.05, 0.50, 0.20],  # Inflation
        [0.10, 0.70, 0.10, 0.10],  # Deflation
    ], dtype=float)
    cost_rate = float(max(transaction_cost_bps, 0.0)) / 10000.0
    metrics_rows: list[dict[str, Any]] = []
    net_map: dict[str, pd.Series] = {}
    wealth_map: dict[str, pd.Series] = {}
    turnover_map: dict[str, pd.Series] = {}
    weight_map: dict[str, pd.DataFrame] = {}

    for name in model_names:
        cols = [f"{name} · {label}" for label in REGIME_LABELS]
        if not all(c in predictions.columns for c in cols):
            continue
        p = predictions[cols].to_numpy(dtype=float)
        weights = p @ regime_weights
        w = pd.DataFrame(weights, index=predictions.index, columns=next_ret.columns)
        turnover = 0.5 * w.diff().abs().sum(axis=1).fillna(0.0)
        gross = (w * next_ret).sum(axis=1, min_count=1)
        net = (gross - cost_rate * turnover).dropna()
        turnover = turnover.reindex(net.index).fillna(0.0)
        met = _economic_return_metrics(net, turnover, gamma=gamma)
        metrics_rows.append({"Model": name, **met, "Total Cost bps": float((cost_rate * turnover).sum() * 10000.0), "Observations": int(len(net))})
        net_map[name] = net
        wealth_map[name] = (1.0 + net).cumprod()
        turnover_map[name] = turnover
        weight_map[name] = w.reindex(net.index)

    fixed = {
        "60/40 Equity-Bond": np.array([0.60, 0.40, 0.0, 0.0]),
        "1/N Cross-Asset": np.array([0.25, 0.25, 0.25, 0.25]),
    }
    for name, ww in fixed.items():
        gross = (next_ret * ww).sum(axis=1, min_count=1).dropna()
        turnover = pd.Series(0.0, index=gross.index)
        met = _economic_return_metrics(gross, turnover, gamma=gamma)
        metrics_rows.append({"Model": name, **met, "Total Cost bps": 0.0, "Observations": int(len(gross))})
        net_map[name] = gross
        wealth_map[name] = (1.0 + gross).cumprod()
        turnover_map[name] = turnover

    metrics = pd.DataFrame(metrics_rows).sort_values("CEQ", ascending=False).reset_index(drop=True)
    control_candidates = [n for n in ["Historical Prior", "HMM · Multivariate", "Markov Switching · Return/Vol", "Classical Centroid", "60/40 Equity-Bond", "1/N Cross-Asset"] if n in net_map]
    best_control = max(control_candidates, key=lambda n: float(metrics.loc[metrics["Model"] == n, "CEQ"].iloc[0])) if control_candidates else None
    boot = {"delta_ann_return": np.nan, "ci_low": np.nan, "ci_high": np.nan, "p_value": np.nan}
    if "Quantum Density" in net_map and best_control in net_map:
        aligned = pd.concat([net_map["Quantum Density"].rename("q"), net_map[best_control].rename("c")], axis=1).dropna()
        boot = _circular_block_bootstrap_mean((aligned["q"] - aligned["c"]).to_numpy(dtype=float), block=10, draws=700, seed=71)
    return {"available": True, "metrics": metrics, "wealth": wealth_map, "returns": net_map, "turnover": turnover_map, "weights": weight_map, "best_control": best_control, "bootstrap": boot, "transaction_cost_bps": float(transaction_cost_bps), "gamma": float(gamma)}


def _transition_timing_diagnostics(predictions: pd.DataFrame, model_names: list[str], pre_window: int = 20, post_window: int = 20, threshold: float = 0.40) -> tuple[pd.DataFrame, pd.DataFrame]:
    if predictions is None or predictions.empty:
        return pd.DataFrame(), pd.DataFrame()
    target_codes = np.array([REGIME_LABELS.index(x) for x in predictions["Target"]], dtype=int)
    transition_idx = np.where(np.r_[False, target_codes[1:] != target_codes[:-1]])[0]
    summaries: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for name in model_names:
        timings: list[float] = []
        early = ontime = late = misses = 0
        for idx in transition_idx:
            new_label = REGIME_LABELS[int(target_codes[idx])]
            pcol = f"{name} · {new_label}"; predcol = f"{name} · Pred"
            condition = ((predictions[predcol].astype(str) == new_label) | (pd.to_numeric(predictions[pcol], errors="coerce") >= float(threshold))).to_numpy()
            detected: int | None = None
            # If the signal is active at the transition, use the start of the
            # active run; this avoids artificial saturation at the lookback cap.
            if condition[idx]:
                j = idx
                lower = max(0, idx - int(pre_window))
                while j > lower and condition[j - 1]:
                    j -= 1
                detected = j
            else:
                upper = min(len(condition), idx + int(post_window) + 1)
                post = np.where(condition[idx + 1:upper])[0]
                if len(post):
                    detected = idx + 1 + int(post[0])
            if detected is None:
                timing = np.nan; misses += 1; bucket = "MISSED"
            else:
                timing = float(idx - detected)  # positive early, negative late
                timings.append(timing)
                if timing > 1:
                    early += 1; bucket = "EARLY"
                elif timing >= -1:
                    ontime += 1; bucket = "ON-TIME"
                else:
                    late += 1; bucket = "LATE"
            if name == "Quantum Density":
                events.append({"Transition Date": predictions.index[idx], "New Proxy Regime": new_label, "Lead Days": timing, "Timing": bucket, "Probability at Transition": float(predictions.iloc[idx][pcol])})
        denom = max(len(transition_idx), 1)
        summaries.append({"Model": name, "Transitions": int(len(transition_idx)), "Detection Rate": float((len(transition_idx) - misses) / denom), "Early Share": float(early / denom), "On-Time Share": float(ontime / denom), "Late Share": float(late / denom), "Miss Share": float(misses / denom), "Mean Lead Days": float(np.mean(timings)) if timings else np.nan, "Median Lead Days": float(np.median(timings)) if timings else np.nan})
    return pd.DataFrame(summaries), pd.DataFrame(events)


def run_regime_benchmark(
    market_frame: pd.DataFrame,
    horizon: int = 5,
    train_fraction: float = 0.65,
    retrain_every: int = 63,
    decoherence: float = 0.12,
    coupling: float = 0.35,
    evolution_dt: float = 0.30,
    max_hmm_iter: int = 14,
    scaler: str = "standard",
    winsor_z: float = 8.0,
    target_mode: str = "persistent",
    confirmation_days: int = 3,
    min_dwell: int = 5,
    transaction_cost_bps: float = 5.0,
    economic_gamma: float = 5.0,
) -> dict[str, Any]:
    """Purged expanding-window OOS benchmark for V2.2.1 target integrity, dependency-aware validation and utility."""
    feature_frame = prepare_regime_feature_frame(market_frame, horizon=horizon)
    feature_names = [c for c in V2_FEATURE_COLUMNS if c in feature_frame.columns]
    if len(feature_names) < 6:
        return {"available": False, "reason": "Insufficient cross-asset feature coverage."}

    raw_target = feature_frame["target_regime"].copy()
    persistent_target = apply_regime_hysteresis(raw_target, confirmation_days=confirmation_days, min_dwell=min_dwell)
    selected_target = persistent_target if str(target_mode).lower().startswith("persist") else raw_target
    feature_frame["target_regime_raw"] = raw_target
    feature_frame["target_regime_persistent"] = persistent_target
    feature_frame["target_regime"] = selected_target

    raw_integrity = target_integrity_metrics(raw_target, horizon=horizon, margin=feature_frame.get("target_margin"))
    persistent_integrity = target_integrity_metrics(persistent_target, horizon=horizon, margin=feature_frame.get("target_margin"))
    selected_integrity = persistent_integrity if str(target_mode).lower().startswith("persist") else raw_integrity

    sample = feature_frame[feature_names + ["target_regime"]].dropna()
    if len(sample) < 220:
        return {"available": False, "reason": f"Need roughly 220+ aligned observations; received {len(sample)}."}

    label_to_code = {label: i for i, label in enumerate(REGIME_LABELS)}
    y_all = sample["target_regime"].map(label_to_code).to_numpy(dtype=int)
    x_all = sample[feature_names].to_numpy(dtype=float)
    dates_all = sample.index

    start = max(160, int(len(sample) * float(np.clip(train_fraction, 0.50, 0.85))))
    start = min(start, len(sample) - 40)
    if start < 120 or len(sample) - start < 30:
        return {"available": False, "reason": "OOS split is too small for controlled validation."}

    retrain_every = int(max(10, retrain_every))
    learned_models = ["HMM · Multivariate", "Markov Switching · Return/Vol", "Classical Centroid", "Quantum Density"]
    baseline_models = ["Historical Prior", "Majority Class"]
    model_names = baseline_models + learned_models
    stored_probs: dict[str, list[np.ndarray]] = {name: [] for name in model_names}
    stored_y: list[np.ndarray] = []
    stored_dates: list[pd.Index] = []
    purge_gap = int(max(1, horizon))
    purge_audit_rows: list[dict[str, Any]] = []

    for block_start in range(start, len(sample), retrain_every):
        block_end = min(block_start + retrain_every, len(sample))
        # Label Y_t requires the forward horizon through t+h.  Purge the last
        # h labelled observations before every OOS block so no training label
        # realizes inside the test interval.
        train_end = int(block_start - purge_gap)
        if train_end < 120:
            continue
        x_train_raw = x_all[:train_end]; y_train = y_all[:train_end]; x_test_raw = x_all[block_start:block_end]
        if len(x_test_raw) == 0:
            continue
        audit_row = _purge_audit_row(dates_all, train_end, block_start, purge_gap, block_end)
        if audit_row:
            purge_audit_rows.append(audit_row)
        center, scale = _scaler_fit(x_train_raw, method=scaler)
        x_train = _scaler_apply(x_train_raw, center, scale, winsor_z=winsor_z)
        x_test = _scaler_apply(x_test_raw, center, scale, winsor_z=winsor_z)

        counts = np.bincount(y_train, minlength=4).astype(float) + 0.75
        prior = counts / counts.sum(); prior_test = np.repeat(prior.reshape(1, -1), len(x_test), axis=0)
        majority = int(np.argmax(counts)); majority_p = np.full(4, 0.01, dtype=float); majority_p[majority] = 0.97
        majority_test = np.repeat(majority_p.reshape(1, -1), len(x_test), axis=0)

        hmm = fit_gaussian_hmm(x_train, n_states=4, max_iter=max_hmm_iter, persistence=0.91, seed=7)
        hmm_train_hidden = hmm_filter_probabilities(hmm, x_train); hmm_map = _best_state_mapping(hmm_train_hidden, y_train, n_states=4)
        hmm_train_mapped = _remap_probabilities(hmm_train_hidden, hmm_map, n_classes=4); hmm_temp = _fit_probability_temperature(hmm_train_mapped, y_train)
        hmm_test = _temperature_scale_probabilities(_remap_probabilities(hmm_filter_probabilities(hmm, x_test), hmm_map, n_classes=4), hmm_temp)

        reduced_idx = [feature_names.index("eq_ret_1"), feature_names.index("rv_20")]
        ms_train = x_train[:, reduced_idx]; ms_test = x_test[:, reduced_idx]
        ms = fit_gaussian_hmm(ms_train, n_states=4, max_iter=max_hmm_iter, persistence=0.94, seed=13)
        ms_train_hidden = hmm_filter_probabilities(ms, ms_train); ms_map = _best_state_mapping(ms_train_hidden, y_train, n_states=4)
        ms_train_mapped = _remap_probabilities(ms_train_hidden, ms_map, n_classes=4); ms_temp = _fit_probability_temperature(ms_train_mapped, y_train)
        ms_test_prob = _temperature_scale_probabilities(_remap_probabilities(hmm_filter_probabilities(ms, ms_test), ms_map, n_classes=4), ms_temp)

        centroid = fit_centroid_model(x_train, y_train, n_classes=4)
        classical_test = centroid_probabilities(x_test, centroid)
        transition = _estimate_transition_from_codes(y_train, n_states=4)
        quantum_test, _, _ = quantum_density_probabilities(x_test, centroid, transition, decoherence=decoherence, coupling=coupling, evolution_dt=evolution_dt)

        block_prob = {"Historical Prior": prior_test, "Majority Class": majority_test, "HMM · Multivariate": hmm_test, "Markov Switching · Return/Vol": ms_test_prob, "Classical Centroid": classical_test, "Quantum Density": quantum_test}
        for name in model_names:
            stored_probs[name].append(block_prob[name])
        stored_y.append(y_all[block_start:block_end]); stored_dates.append(dates_all[block_start:block_end])

    if not stored_y:
        return {"available": False, "reason": "No OOS blocks were produced."}

    y_oos = np.concatenate(stored_y)
    date_oos = stored_dates[0].append(stored_dates[1:]) if len(stored_dates) > 1 else stored_dates[0]
    prob_oos = {name: np.vstack(parts) for name, parts in stored_probs.items()}

    metric_rows: list[dict[str, Any]] = []; losses: dict[str, np.ndarray] = {}; per_class: dict[str, pd.DataFrame] = {}; calibration: dict[str, pd.DataFrame] = {}; confusions: dict[str, np.ndarray] = {}
    classwise_summary: dict[str, pd.DataFrame] = {}; classwise_curves: dict[str, dict[str, pd.DataFrame]] = {}
    for name in model_names:
        row, loss = _metric_row(name, prob_oos[name], y_oos, date_oos); metric_rows.append(row); losses[name] = loss
        _, cls_table, conf = _classification_diagnostics(prob_oos[name], y_oos); per_class[name] = cls_table; confusions[name] = conf
        _, cal_table = _confidence_calibration(prob_oos[name], y_oos, bins=10); calibration[name] = cal_table
        cs, curves = _classwise_calibration(prob_oos[name], y_oos, bins=10); classwise_summary[name] = cs; classwise_curves[name] = curves
    metrics = pd.DataFrame(metric_rows).sort_values("OOS Log Loss", ascending=True).reset_index(drop=True)

    learned_controls = metrics[metrics["Model"].isin(["HMM · Multivariate", "Markov Switching · Return/Vol", "Classical Centroid"])]
    best_control_name = str(learned_controls.iloc[0]["Model"])
    baseline_rows = metrics[metrics["Model"].isin(baseline_models)]; best_baseline_name = str(baseline_rows.iloc[0]["Model"])
    bootstrap_iid = _bootstrap_delta(losses["Quantum Density"], losses[best_control_name])
    bootstrap_table, bootstrap = _block_bootstrap_delta(losses["Quantum Density"], losses[best_control_name], block_lengths=(5, 10, 20, 40), draws=900, seed=97)
    bootstrap_matched_table, bootstrap_matched = _block_bootstrap_delta(losses["Quantum Density"], losses["Classical Centroid"], block_lengths=(5, 10, 20, 40), draws=900, seed=131)
    bootstrap_prior_table, bootstrap_prior = _block_bootstrap_delta(losses["Quantum Density"], losses["Historical Prior"], block_lengths=(5, 10, 20, 40), draws=900, seed=173)
    effective_sample = _effective_sample_size(losses[best_control_name] - losses["Quantum Density"], max_lag=40)

    pred = pd.DataFrame(index=date_oos); pred["Target"] = [REGIME_LABELS[i] for i in y_oos]
    for name in model_names:
        p = prob_oos[name]; pred[f"{name} · Pred"] = [REGIME_LABELS[i] for i in np.argmax(p, axis=1)]
        for i, label in enumerate(REGIME_LABELS): pred[f"{name} · {label}"] = p[:, i]

    latest_features = feature_frame[feature_names].dropna(); latest_features = latest_features if not latest_features.empty else sample[feature_names]
    center, scale = _scaler_fit(x_all, method=scaler); x_train = _scaler_apply(x_all, center, scale, winsor_z=winsor_z)
    centroid = fit_centroid_model(x_train, y_all, n_classes=4); transition = _estimate_transition_from_codes(y_all, n_states=4)
    latest_raw = latest_features.iloc[-1].to_numpy(dtype=float); latest_x = _scaler_apply(latest_raw.reshape(1, -1), center, scale, winsor_z=winsor_z)
    q_current, current_rhos, current_hs = quantum_density_probabilities(latest_x, centroid, transition, decoherence=decoherence, coupling=coupling, evolution_dt=evolution_dt, memory=0.0)
    c_current = centroid_probabilities(latest_x, centroid); current_prob = q_current[0]; current_rho = current_rhos[-1]; current_h = current_hs[-1]
    attribution = _factor_attribution(latest_x[0], centroid, feature_names); concentration = _factor_concentration(attribution); ablation = _factor_ablation(latest_x[0], centroid, transition, feature_names, current_prob, decoherence, coupling, evolution_dt)
    hdiag = _hamiltonian_diagnostics(current_h)
    timing_summary, timing_events = _transition_timing_diagnostics(pred, learned_models, pre_window=20, post_window=20, threshold=0.40)
    imbalance = _class_imbalance_diagnostics(y_oos)
    purge_pass_now = bool(purge_audit_rows and all(bool(row.get("Leakage Free", False)) for row in purge_audit_rows))
    validation = _validation_level(metrics, bootstrap, best_control_name)
    if not purge_pass_now and int(validation.get("level", 0)) >= 3:
        validation = {
            "level": 2,
            "label": "CHRONOLOGY AUDIT FAILED",
            "detail": "Predictive edge cannot be promoted to Level 3 because at least one refit block fails the forward-label chronology audit.",
        }
    economic = economic_utility_benchmark(market_frame, pred, ["Historical Prior", *learned_models], transaction_cost_bps=transaction_cost_bps, gamma=economic_gamma)

    # Level 4 is only eligible after Level 3 predictive validation AND a robust
    # positive net return difference versus the strongest economic control.
    economic_gate = {"eligible": False, "level4": False, "label": "PREDICTIVE GATE NOT CLEARED"}
    if validation.get("level", 0) >= 3 and economic.get("available"):
        eb = economic.get("bootstrap", {}); level4 = bool(np.isfinite(eb.get("ci_low", np.nan)) and float(eb.get("ci_low", np.nan)) > 0 and float(eb.get("p_value", 1.0)) < 0.05)
        economic_gate = {"eligible": True, "level4": level4, "label": "ECONOMICALLY SIGNIFICANT" if level4 else "ECONOMIC EDGE NOT ROBUST"}

    purge_audit = pd.DataFrame(purge_audit_rows)
    purge_pass = bool((not purge_audit.empty) and purge_audit["Leakage Free"].fillna(False).all())

    return {
        "available": True, "feature_frame": feature_frame, "feature_names": feature_names, "metrics": metrics, "predictions": pred, "probabilities": prob_oos, "oos_targets": y_oos, "oos_dates": date_oos,
        "best_classical": best_control_name, "best_baseline": best_baseline_name, "bootstrap": bootstrap, "bootstrap_iid": bootstrap_iid,
        "bootstrap_table": bootstrap_table, "bootstrap_matched": bootstrap_matched, "bootstrap_matched_table": bootstrap_matched_table,
        "bootstrap_prior": bootstrap_prior, "bootstrap_prior_table": bootstrap_prior_table, "effective_sample_size": effective_sample,
        "purge_gap": purge_gap, "purge_audit": purge_audit, "purge_pass": purge_pass, "validation_level": validation,
        "current_probabilities": current_prob, "current_classical_probabilities": c_current[0], "current_probability_delta": current_prob - c_current[0], "current_rho": current_rho, "current_hamiltonian": current_h, "hamiltonian_diagnostics": hdiag,
        "current_entropy": von_neumann_entropy(current_rho, normalized=True), "current_purity": purity(current_rho), "current_coherence": l1_coherence(current_rho), "current_effective_dimension": effective_dimension(current_rho), "current_dominant": REGIME_LABELS[int(np.argmax(current_prob))], "current_probability": float(np.max(current_prob)),
        "transition_matrix": transition, "factor_attribution": attribution, "factor_concentration": concentration, "factor_ablation": ablation, "per_class_metrics": per_class, "calibration": calibration, "classwise_calibration": classwise_summary, "classwise_calibration_curves": classwise_curves,
        "confusions": confusions, "confusion": confusions["Quantum Density"], "class_imbalance": imbalance, "transition_lead_summary": timing_summary, "transition_lead_events": timing_events,
        "target_integrity_raw": raw_integrity, "target_integrity_persistent": persistent_integrity, "target_integrity_selected": selected_integrity, "target_mode": str(target_mode), "confirmation_days": int(confirmation_days), "min_dwell": int(min_dwell),
        "economic_utility": economic, "economic_gate": economic_gate, "sample_observations": int(len(sample)), "oos_observations": int(len(y_oos)), "train_start_observations": int(start), "purged_initial_training_observations": int(max(0, start - purge_gap)), "horizon": int(horizon), "retrain_every": int(retrain_every), "decoherence": float(decoherence), "coupling": float(coupling), "evolution_dt": float(evolution_dt), "scaler": str(scaler), "winsor_z": float(winsor_z), "transaction_cost_bps": float(transaction_cost_bps), "economic_gamma": float(economic_gamma),
    }
