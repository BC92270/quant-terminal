"""Institutional correlation/dependency engine for Quant Terminal V3.1.1."""

from .config import CorrelationConfig
from .engine import CorrelationEngine, AnalysisBundle

__version__ = "3.1.1"
__all__ = ["CorrelationConfig", "CorrelationEngine", "AnalysisBundle"]
