"""Transparent, explainable credit risk-rating model.

The model converts the computed ratio set into a 1-5 sub-score per ratio, rolls
those up into category scores, weights them into a composite score, and maps
the composite to an internal rating band with an illustrative Probability of
Default (PD). All thresholds are configurable so a bank can align the model to
its own house methodology.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..ratios.calculator import RatioSet
from ..ratios.definitions import Direction, RatioCategory


class RatingBand(str, Enum):
    AAA = "AAA"
    AA = "AA"
    A = "A"
    BBB = "BBB"
    BB = "BB"
    B = "B"
    CCC = "CCC"
    CC = "CC"
    D = "D"


_DEFAULT_WEIGHTS: dict[RatioCategory, float] = {
    RatioCategory.LEVERAGE: 0.25,
    RatioCategory.COVERAGE: 0.20,
    RatioCategory.PROFITABILITY: 0.20,
    RatioCategory.LIQUIDITY: 0.15,
    RatioCategory.SOLVENCY: 0.10,
    RatioCategory.EFFICIENCY: 0.10,
}

_BAND_TABLE: list[tuple[float, RatingBand, float]] = [
    (4.5, RatingBand.AAA, 0.0005),
    (4.0, RatingBand.AA, 0.0020),
    (3.5, RatingBand.A, 0.0060),
    (3.0, RatingBand.BBB, 0.0200),
    (2.5, RatingBand.BB, 0.0600),
    (2.0, RatingBand.B, 0.1200),
    (1.5, RatingBand.CCC, 0.2500),
    (1.0, RatingBand.CC, 0.4500),
    (0.0, RatingBand.D, 1.0000),
]


def _score_ratio(value: float | None, definition) -> float | None:
    if value is None:
        return None
    lo, hi = definition.healthy_min, definition.healthy_max
    if definition.direction == Direction.HIGHER_IS_BETTER:
        if lo is not None and hi is not None:
            if value >= hi:
                return 5.0
            if value >= lo:
                return 4.0
            if value >= 0.75 * lo:
                return 3.0
            if value >= 0.5 * lo:
                return 2.0
            return 1.0
        if lo is not None:
            if value >= lo:
                return 5.0
            if value >= 0.75 * lo:
                return 4.0
            if value >= 0.5 * lo:
                return 3.0
            if value >= 0.25 * lo:
                return 2.0
            return 1.0
    else:
        if lo is not None and hi is not None:
            if value <= lo:
                return 5.0
            if value <= hi:
                return 4.0
            if value <= 1.25 * hi:
                return 3.0
            if value <= 1.5 * hi:
                return 2.0
            return 1.0
        if hi is not None:
            if value <= hi:
                return 5.0
            if value <= 1.25 * hi:
                return 4.0
            if value <= 1.5 * hi:
                return 3.0
            if value <= 2.0 * hi:
                return 2.0
            return 1.0
    return 3.0


@dataclass
class CategoryScore:
    category: str
    score: float | None
    contributing: dict[str, float] = field(default_factory=dict)


@dataclass
class RiskRating:
    band: RatingBand
    composite_score: float
    pd_estimate: float
    category_scores: list[CategoryScore]
    commentary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "band": self.band.value,
            "composite_score": round(self.composite_score, 3),
            "pd_estimate": self.pd_estimate,
            "category_scores": [
                {"category": c.category, "score": c.score, "contributing": c.contributing}
                for c in self.category_scores
            ],
            "commentary": self.commentary,
        }


def rate(ratios: RatioSet, weights: dict[RatioCategory, float] = _DEFAULT_WEIGHTS) -> RiskRating:
    from ..ratios.definitions import RATIO_DEFINITIONS
    cat_scores: dict[str, list[float]] = {}
    contributing: dict[str, dict[str, float]] = {}
    for r in ratios.results:
        definition = RATIO_DEFINITIONS[r.key]
        s = _score_ratio(r.value, definition)
        if s is None:
            continue
        cat_scores.setdefault(r.category, []).append(s)
        contributing.setdefault(r.category, {})[r.key] = round(s, 2)

    category_scores: list[CategoryScore] = []
    weighted_sum = 0.0
    weight_total = 0.0
    for cat_enum, weight in weights.items():
        vals = cat_scores.get(cat_enum.value)
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        category_scores.append(CategoryScore(category=cat_enum.value, score=round(avg, 2), contributing=contributing.get(cat_enum.value, {})))
        weighted_sum += avg * weight
        weight_total += weight

    composite = weighted_sum / weight_total if weight_total else 0.0

    band, pd = RatingBand.D, 1.0
    for threshold, b, p in _BAND_TABLE:
        if composite >= threshold:
            band, pd = b, p
            break

    return RiskRating(
        band=band, composite_score=round(composite, 3), pd_estimate=pd,
        category_scores=category_scores,
    )
