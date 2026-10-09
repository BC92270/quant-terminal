"""Quant Terminal Correlation Matrix section — V4.1.0.

Architecture:
    correlation_matrix_section/
        correlation_intelligence_v3/   # institutional robust core V4.1.0
        dependency_intelligence/       # multi-force attribution layer V4.1.0

Existing app code can keep exactly:
    from correlation_matrix import render_correlation_intelligence_v1
"""
from correlation_matrix_section.correlation_intelligence_v3.ui import (
    render_correlation_intelligence_v1,
    render_correlation_intelligence_v2,
    render_correlation_intelligence_v3,
)

render_correlation_intelligence_v31 = render_correlation_intelligence_v3
render_correlation_intelligence_v311 = render_correlation_intelligence_v3
render_correlation_intelligence_v4 = render_correlation_intelligence_v3
render_correlation_intelligence_v401 = render_correlation_intelligence_v3
render_correlation_intelligence_v402 = render_correlation_intelligence_v3
render_correlation_intelligence_v410 = render_correlation_intelligence_v3

__all__ = [
    "render_correlation_intelligence_v1",
    "render_correlation_intelligence_v2",
    "render_correlation_intelligence_v3",
    "render_correlation_intelligence_v31",
    "render_correlation_intelligence_v311",
    "render_correlation_intelligence_v4",
    "render_correlation_intelligence_v401",
    "render_correlation_intelligence_v402",
    "render_correlation_intelligence_v410",
]
