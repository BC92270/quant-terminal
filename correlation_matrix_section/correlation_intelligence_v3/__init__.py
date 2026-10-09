"""Institutional correlation/dependency engine for Quant Terminal V4.1.0."""

from .config import CorrelationConfig
from .engine import CorrelationEngine, AnalysisBundle

__version__ = "4.1.0"
__all__ = ["CorrelationConfig", "CorrelationEngine", "AnalysisBundle"]
