"""Analysis package: trends and covenant monitoring."""

from .trend import analyze_ratio_trends, analyze_trends
from .covenants import (
    Covenant,
    CovenantResult,
    CovenantStatus,
    DEFAULT_COVENANTS,
    Operator,
    evaluate_covenants,
)
from .stress import PRESET_SCENARIOS, StressResult, StressShock, apply_stress, run_stress

__all__ = [
    "analyze_ratio_trends",
    "analyze_trends",
    "Covenant",
    "CovenantResult",
    "CovenantStatus",
    "DEFAULT_COVENANTS",
    "Operator",
    "evaluate_covenants",
    "PRESET_SCENARIOS",
    "StressResult",
    "StressShock",
    "apply_stress",
    "run_stress",
]
