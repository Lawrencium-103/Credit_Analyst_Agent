"""Trend and trajectory analysis across periods.

Produces year-over-year growth, CAGR for key performance indicators, and a
direction assessment for every ratio (improving / deteriorating / stable) using
each ratio's defined favourable direction. This is the quantitative backbone of
the "trend vs prior" narrative a credit analyst writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ratios.calculator import RatioSet, compute_ratios
from ..schema.financials import CompanyFinancials
from ..ratios.definitions import RATIO_DEFINITIONS, Direction


KPI_ACCESSORS = [
    ("revenue", "Income Statement", lambda p: p.income_statement.revenue),
    ("gross_profit", "Income Statement", lambda p: p.income_statement.gross_profit),
    ("ebitda", "Income Statement", lambda p: p.income_statement.ebitda),
    ("operating_profit", "Income Statement", lambda p: p.income_statement.ebit),
    ("net_income", "Income Statement", lambda p: p.income_statement.net_income),
    ("total_assets", "Balance Sheet", lambda p: p.balance_sheet.total_assets),
    ("total_equity", "Balance Sheet", lambda p: p.balance_sheet.total_equity),
    ("total_debt", "Balance Sheet", lambda p: p.balance_sheet.total_debt),
    ("cash_and_equivalents", "Balance Sheet", lambda p: p.balance_sheet.cash_and_equivalents),
    ("operating_cash_flow", "Cash Flow", lambda p: p.cash_flow.operating_cash_flow),
    ("free_cash_flow", "Cash Flow", lambda p: p.cash_flow.free_cash_flow),
    ("capital_expenditures", "Cash Flow", lambda p: p.cash_flow.capital_expenditures),
]


@dataclass
class MetricTrend:
    key: str
    label: str
    category: str
    values: list[float | None]
    periods: list[str]
    yoy_growth: list[float | None] = field(default_factory=list)
    cagr: float | None = None

    def to_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "category": self.category,
            "values": self.values, "periods": self.periods,
            "yoy_growth": self.yoy_growth, "cagr": self.cagr,
        }


def analyze_trends(company: CompanyFinancials) -> dict[str, MetricTrend]:
    out: dict[str, MetricTrend] = {}
    for key, cat, accessor in KPI_ACCESSORS:
        values = [accessor(p) for p in company.periods]
        if all(v is None for v in values):
            continue
        yoy: list[float | None] = [None]
        for i in range(1, len(values)):
            prev, cur = values[i - 1], values[i]
            if prev not in (None, 0) and cur is not None:
                yoy.append((cur - prev) / abs(prev))
            else:
                yoy.append(None)
        cagr = None
        first, last = values[0], values[-1]
        n = len(values)
        if n >= 2 and first not in (None, 0) and last is not None and last > 0 and first > 0:
            cagr = (last / first) ** (1 / (n - 1)) - 1
        out[key] = MetricTrend(
            key=key, label=key.replace("_", " ").title(), category=cat,
            values=values, periods=[p.period for p in company.periods],
            yoy_growth=yoy, cagr=cagr,
        )
    return out


@dataclass
class RatioTrend:
    key: str
    label: str
    category: str
    direction: str
    values: list[float | None]
    periods: list[str]
    trajectory: str

    def to_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "category": self.category,
            "direction": self.direction, "values": self.values,
            "periods": self.periods, "trajectory": self.trajectory,
        }


def _trajectory(values: list[float | None], direction: Direction) -> str:
    nums = [v for v in values if v is not None]
    if len(nums) < 2:
        return "stable"
    first, last = nums[0], nums[-1]
    if first == last:
        return "stable"
    improving_if_higher = direction == Direction.HIGHER_IS_BETTER
    improved = (last > first) if improving_if_higher else (last < first)
    if abs(last - first) / abs(first) < 0.05:
        return "stable"
    return "improving" if improved else "deteriorating"


def analyze_ratio_trends(company: CompanyFinancials) -> dict[str, RatioTrend]:
    series: dict[str, list[float | None]] = {}
    periods = [p.period for p in company.periods]
    for i, p in enumerate(company.periods):
        prior = company.periods[i - 1] if i > 0 else None
        ratios = compute_ratios(p, prior)
        for r in ratios.results:
            series.setdefault(r.key, []).append(r.value)
    out: dict[str, RatioTrend] = {}
    for key, definition in RATIO_DEFINITIONS.items():
        if key not in series:
            continue
        out[key] = RatioTrend(
            key=key, label=definition.label, category=definition.category.value,
            direction=definition.direction.value, values=series[key], periods=periods,
            trajectory=_trajectory(series[key], definition.direction),
        )
    return out
