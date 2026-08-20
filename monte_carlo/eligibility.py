from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Sequence

import numpy as np
import pandas as pd

from .config import MODEL_SAMPLE_REQUIREMENTS, MODELS

try:
    from scipy.stats import chi2
except Exception:  # pragma: no cover
    chi2 = None


_CONDITIONAL_FIT_MAP = {
    "GARCH(1,1) normal": "GARCH(1,1) normal",
    "GARCH(1,1) Student-t": "GARCH(1,1) Student-t",
    "GJR-GARCH Student-t": "GJR-GARCH Student-t",
    "Filtered historical GARCH-t": "GARCH(1,1) Student-t",
}


def _autocorrelation(values: np.ndarray, lag: int) -> float:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if lag <= 0 or x.size <= lag + 2:
        return float("nan")
    x = x - float(np.mean(x))
    denom = float(np.dot(x, x))
    if denom <= 0:
        return float("nan")
    return float(np.dot(x[lag:], x[:-lag]) / denom)


def ljung_box_p_value(values: Sequence[float], lags: int = 10) -> float:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    n = int(x.size)
    if n < 25:
        return float("nan")
    max_lag = min(max(1, int(lags)), max(1, n // 5))
    correlations = np.array([_autocorrelation(x, lag) for lag in range(1, max_lag + 1)], dtype=float)
    correlations = correlations[np.isfinite(correlations)]
    if correlations.size == 0:
        return float("nan")
    indexes = np.arange(1, correlations.size + 1, dtype=float)
    q_stat = n * (n + 2.0) * float(np.sum(correlations**2 / np.maximum(n - indexes, 1.0)))
    if chi2 is None:
        return float("nan")
    return float(chi2.sf(q_stat, correlations.size))


def _sample_gate(model: str, observations: int) -> tuple[str, list[str]]:
    hard_min, preferred = MODEL_SAMPLE_REQUIREMENTS.get(model, (120, 500))
    reasons: list[str] = []
    if observations < hard_min:
        reasons.append(f"échantillon {observations} < minimum dur {hard_min}")
        return "INELIGIBLE", reasons
    if observations < preferred:
        reasons.append(f"échantillon {observations} < cible institutionnelle {preferred}")
        return "WARNING", reasons
    return "ELIGIBLE", reasons


def evaluate_model_eligibility(
    model: str,
    base: Mapping[str, Any],
    conditional_calibrations: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    observations = int(base.get("calibration_observations", 0))
    status, reasons = _sample_gate(model, observations)
    checks: list[dict[str, Any]] = [
        {
            "Check": "Sample size",
            "Value": observations,
            "Status": status,
            "Detail": reasons[0] if reasons else "sample requirement satisfied",
        }
    ]

    result: Dict[str, Any] = {
        "model": model,
        "status": status,
        "eligible_for_aggregation": status == "ELIGIBLE",
        "research_only": status in {"WARNING", "INELIGIBLE", "FALLBACK"},
        "reasons": list(reasons),
        "checks": checks,
        "observations": observations,
        "calibration_status": "NOT_REQUIRED",
        "persistence": None,
        "degrees_of_freedom": None,
        "ljung_box_residual_p": None,
        "ljung_box_squared_p": None,
        "stability_status": "NOT_APPLICABLE",
        "fallback_expected": False,
    }

    # Static fat-tail calibration quality.
    if model == "GBM Student-t calibré":
        degrees = float(base.get("student_df", float("nan")))
        result["degrees_of_freedom"] = degrees
        if np.isfinite(degrees) and degrees <= 4.25:
            result["reasons"].append("degrés de liberté très faibles; variance de queue instable")
            status = "WARNING" if status == "ELIGIBLE" else status
        checks.append(
            {
                "Check": "Static Student-t df",
                "Value": degrees,
                "Status": "WARNING" if np.isfinite(degrees) and degrees <= 4.25 else "PASS",
                "Detail": "method-of-moments tail calibration",
            }
        )

    fit_name = _CONDITIONAL_FIT_MAP.get(model)
    if fit_name is not None:
        fit = dict(conditional_calibrations.get(fit_name, {}))
        result["calibration_status"] = str(fit.get("status", "FAILED"))
        result["persistence"] = fit.get("persistence")
        params = fit.get("parameters", {}) if isinstance(fit.get("parameters"), Mapping) else {}
        result["degrees_of_freedom"] = params.get("degrees_of_freedom")

        if not fit.get("ok"):
            status = "FALLBACK"
            result["fallback_expected"] = True
            result["reasons"].append(str(fit.get("warning") or "conditional calibration unavailable"))
            checks.append(
                {
                    "Check": "Conditional calibration",
                    "Value": fit.get("status", "FAILED"),
                    "Status": "FALLBACK",
                    "Detail": fit.get("warning", "fit unavailable"),
                }
            )
        else:
            persistence = float(fit.get("persistence", float("nan")))
            if np.isfinite(persistence):
                if persistence >= 0.9995:
                    status = "INELIGIBLE"
                    result["reasons"].append("persistence non stationnaire ou à la frontière")
                elif persistence >= 0.985:
                    if status == "ELIGIBLE":
                        status = "WARNING"
                    result["reasons"].append("persistence très élevée")
            checks.append(
                {
                    "Check": "Persistence",
                    "Value": persistence,
                    "Status": "INELIGIBLE" if np.isfinite(persistence) and persistence >= 0.9995 else ("WARNING" if np.isfinite(persistence) and persistence >= 0.985 else "PASS"),
                    "Detail": "alpha + beta (+ gamma/2 for GJR)",
                }
            )

            degrees = params.get("degrees_of_freedom")
            if degrees is not None and np.isfinite(float(degrees)):
                degrees = float(degrees)
                if degrees <= 2.25:
                    status = "INELIGIBLE"
                    result["reasons"].append("Student-t df proche de 2: variance mal identifiée")
                elif degrees <= 4.0:
                    if status == "ELIGIBLE":
                        status = "WARNING"
                    result["reasons"].append("Student-t df faible; queue très sensible")
                checks.append(
                    {
                        "Check": "Student-t degrees of freedom",
                        "Value": degrees,
                        "Status": "INELIGIBLE" if degrees <= 2.25 else ("WARNING" if degrees <= 4.0 else "PASS"),
                        "Detail": "finite-variance boundary at df > 2",
                    }
                )

            standardized = np.asarray(fit.get("standardized_residuals", []), dtype=float)
            residual_p = ljung_box_p_value(standardized, lags=10)
            squared_p = ljung_box_p_value(standardized**2, lags=10)
            result["ljung_box_residual_p"] = residual_p
            result["ljung_box_squared_p"] = squared_p
            if np.isfinite(residual_p) and residual_p < 0.01:
                if status == "ELIGIBLE":
                    status = "WARNING"
                result["reasons"].append("autocorrélation résiduelle détectée")
            if np.isfinite(squared_p) and squared_p < 0.01:
                if status == "ELIGIBLE":
                    status = "WARNING"
                result["reasons"].append("ARCH résiduel après calibration")
            checks.extend(
                [
                    {
                        "Check": "Ljung-Box residuals",
                        "Value": residual_p,
                        "Status": "WARNING" if np.isfinite(residual_p) and residual_p < 0.01 else "PASS",
                        "Detail": "p-value at 10 lags",
                    },
                    {
                        "Check": "Ljung-Box squared residuals",
                        "Value": squared_p,
                        "Status": "WARNING" if np.isfinite(squared_p) and squared_p < 0.01 else "PASS",
                        "Detail": "remaining conditional heteroskedasticity",
                    },
                ]
            )

            stability = fit.get("stability", {}) if isinstance(fit.get("stability"), Mapping) else {}
            stability_status = str(stability.get("status", "NOT_RUN"))
            result["stability_status"] = stability_status
            if stability_status == "WARNING":
                if status == "ELIGIBLE":
                    status = "WARNING"
                result["reasons"].append(str(stability.get("warning") or "paramètres instables entre fenêtres"))
            elif stability_status == "FAILED":
                if status == "ELIGIBLE":
                    status = "WARNING"
                result["reasons"].append("diagnostic de stabilité indisponible")
            checks.append(
                {
                    "Check": "Parameter stability",
                    "Value": stability_status,
                    "Status": stability_status if stability_status in {"PASS", "WARNING", "FAILED"} else "INFO",
                    "Detail": stability.get("warning", "full sample versus trailing sub-sample"),
                }
            )

    result["status"] = status
    result["eligible_for_aggregation"] = status == "ELIGIBLE"
    result["research_only"] = status != "ELIGIBLE"
    result["reasons"] = list(dict.fromkeys(str(reason) for reason in result["reasons"] if reason))
    return result


def build_model_eligibility(
    base: Mapping[str, Any],
    conditional_calibrations: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    return {
        model: evaluate_model_eligibility(model, base, conditional_calibrations)
        for model in MODELS
    }


def model_eligibility_table(eligibility: Mapping[str, Mapping[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model in MODELS:
        item = eligibility.get(model, {})
        rows.append(
            {
                "Model": model,
                "Eligibility": item.get("status", "INELIGIBLE"),
                "N": item.get("observations", 0),
                "Calibration": item.get("calibration_status", "NOT_REQUIRED"),
                "Persistence": item.get("persistence"),
                "Nu": item.get("degrees_of_freedom"),
                "LB residual p": item.get("ljung_box_residual_p"),
                "LB squared p": item.get("ljung_box_squared_p"),
                "Stability": item.get("stability_status", "NOT_APPLICABLE"),
                "Aggregation": "INCLUDED" if item.get("eligible_for_aggregation") else "EXCLUDED",
                "Reasons": "; ".join(item.get("reasons", [])),
            }
        )
    return pd.DataFrame(rows)
