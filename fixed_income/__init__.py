"""Institutional fixed-income analytics package.

The package contains pure calculation engines and operational services.
Streamlit remains an adapter layer in fixed_income_credit.py.
"""

from .contracts import (
    BasisPoints,
    DataClassification,
    DataPoint,
    Money,
    Percent,
    ValidationIssue,
    ValidationReport,
)

__all__ = [
    "BasisPoints",
    "DataClassification",
    "DataPoint",
    "Money",
    "Percent",
    "ValidationIssue",
    "ValidationReport",
]

__version__ = "1.0.0"
