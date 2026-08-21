from __future__ import annotations

from typing import Any


def evaluate_alerts(alerts: list[dict[str, Any]], metrics: dict[str, Any], ticker: str) -> list[dict[str, Any]]:
    triggered: list[dict[str, Any]] = []
    operators = {
        ">": lambda left, right: left > right,
        ">=": lambda left, right: left >= right,
        "<": lambda left, right: left < right,
        "<=": lambda left, right: left <= right,
        "==": lambda left, right: left == right,
    }
    for alert in alerts:
        if not alert.get("enabled", True):
            continue
        target = str(alert.get("ticker") or "").upper()
        if target and target != ticker.upper():
            continue
        metric = str(alert.get("metric") or "")
        operator = operators.get(str(alert.get("operator") or ""))
        if metric not in metrics or operator is None:
            continue
        try:
            if operator(float(metrics[metric]), float(alert.get("threshold"))):
                triggered.append({**alert, "observed": metrics[metric], "ticker": ticker.upper()})
        except (TypeError, ValueError):
            continue
    return triggered
