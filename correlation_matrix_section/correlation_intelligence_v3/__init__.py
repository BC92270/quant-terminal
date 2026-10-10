"""Institutional correlation/dependency engine for Quant Terminal V5.0.0."""

from .config import CorrelationConfig
from .engine import CorrelationEngine, AnalysisBundle

__version__ = "5.0.0"
__all__ = ["CorrelationConfig", "CorrelationEngine", "AnalysisBundle"]
