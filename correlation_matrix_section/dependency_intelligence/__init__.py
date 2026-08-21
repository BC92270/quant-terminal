"""Multi-force dependency attribution layer for Correlation Matrix."""

from .config import DependencyConfig
from .engine import DependencyIntelligence, PairDependencyAnalysis
from .registry import force_registry

__version__ = "4.0.2"
__all__ = ["DependencyConfig", "DependencyIntelligence", "PairDependencyAnalysis", "force_registry"]
