from __future__ import annotations

import numpy as np

def generate_stationary_indices(rng, n_history: int, simulations: int, horizon: int, mean_block_length: int) -> np.ndarray:
    if n_history <= 0:
        raise ValueError("Historique vide pour stationary bootstrap.")
    mean_block_length = max(2, int(mean_block_length))
    restart_probability = 1.0 / mean_block_length
    indices = np.empty((simulations, horizon), dtype=np.int32)
    indices[:, 0] = rng.integers(0, n_history, size=simulations)
    for step in range(1, horizon):
        restart = rng.random(simulations) < restart_probability
        continuation = (indices[:, step - 1] + 1) % n_history
        fresh = rng.integers(0, n_history, size=simulations)
        indices[:, step] = np.where(restart, fresh, continuation)
    return indices

def historical_bootstrap_log_steps(rng, historical, simulations, horizon, target_mean_step, stress=False):
    indices = rng.integers(0, len(historical), size=(simulations, horizon))
    sampled = historical[indices]
    log_steps = sampled - float(np.mean(historical)) + target_mean_step
    if stress:
        centered = log_steps - target_mean_step
        log_steps = target_mean_step + centered * 1.25
    return log_steps

def stationary_bootstrap_log_steps(rng, historical, simulations, horizon, target_mean_step, mean_block_length, stress=False):
    indices = generate_stationary_indices(rng, len(historical), simulations, horizon, mean_block_length)
    sampled = historical[indices]
    log_steps = sampled - float(np.mean(historical)) + target_mean_step
    if stress:
        centered = log_steps - target_mean_step
        log_steps = target_mean_step + centered * 1.25
    return log_steps
