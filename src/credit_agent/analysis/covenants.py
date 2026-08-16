"""Covenant monitoring.

Evaluates a facility's covenant package against the computed ratios for the
latest period. Covenants reference a ratio key from the engine and a threshold
with a direction. This generalises to any term-sheet covenant set.
"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel

from ..ratios.calculator import RatioSet


class Operator(str, Enum):
    GTE = ">="
    LTE = "<="


class CovenantStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_AVAILABLE = "N/A"


class Covenant(BaseModel):
    name: str
    description: str
    metric_key: str
    operator: Operator
    threshold: float
    source: str = "typical"


class CovenantResult(BaseModel):
    name: str
    description: str
    metric_key: str
    operator: str
    threshold: float
    actual: float | None
    status: CovenantStatus
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name, "description": self.description,
            "metric_key": self.metric_key,
            "operator": self.operator, "threshold": self.threshold,
            "actual": self.actual, "status": self.status.value, "detail": self.detail,
        }


DEFAULT_COVENANTS: list[Covenant] = [
    Covenant(name="Minimum Liquidity", description="Current ratio must not fall below 1.20x",
             metric_key="current_ratio", operator=Operator.GTE, threshold=1.20),
    Covenant(name="Maximum Leverage", description="Total debt / EBITDA must not exceed 4.00x",
             metric_key="leverage_metric", operator=Operator.LTE, threshold=4.00),
    Covenant(name="Minimum Interest Cover", description="EBITDA interest cover must be at least 3.00x",
             metric_key="ebitda_net_interest_cover", operator=Operator.GTE, threshold=3.00),
    Covenant(name="Maximum Net Leverage", description="Net debt / EBITDA must not exceed 3.00x",
             metric_key="net_leverage", operator=Operator.LTE, threshold=3.00),
    Covenant(name="Maximum Gearing", description="Debt / equity must not exceed 2.00x",
             metric_key="debt_to_equity", operator=Operator.LTE, threshold=2.00),
]


def evaluate_covenants(ratios: RatioSet, covenants: list[Covenant] | None = None) -> list[CovenantResult]:
    covenants = covenants or DEFAULT_COVENANTS
    results: list[CovenantResult] = []
    for cov in covenants:
        r = ratios.get(cov.metric_key)
        actual = r.value if r else None
        if actual is None:
            results.append(CovenantResult(
                name=cov.name, description=cov.description, metric_key=cov.metric_key,
                operator=cov.operator.value, threshold=cov.threshold, actual=None,
                status=CovenantStatus.NOT_AVAILABLE, detail="Metric not computable from available data",
            ))
            continue
        if cov.operator == Operator.GTE:
            ok = actual >= cov.threshold
        else:
            ok = actual <= cov.threshold
        results.append(CovenantResult(
            name=cov.name, description=cov.description, metric_key=cov.metric_key,
            operator=cov.operator.value, threshold=cov.threshold, actual=actual,
            status=CovenantStatus.PASS if ok else CovenantStatus.FAIL,
            detail=f"{actual:.2f} {cov.operator.value} {cov.threshold:.2f}",
        ))
    return results
