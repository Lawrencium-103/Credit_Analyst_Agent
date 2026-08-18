"""Deterministic ratio computation.

All calculations are performed in pure Python with no LLM involvement so the
numbers are exact and auditable. Missing line items are derived where a unique
relationship exists (e.g. gross_profit = revenue - cogs). Ratios that cannot be
computed because of missing inputs return `None` rather than raising, so the
analyst sees gaps instead of silent errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..schema.financials import PeriodFinancials
from .definitions import RATIO_DEFINITIONS


def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den in (None, 0):
        return None
    return num / den


def _derive(period: PeriodFinancials) -> PeriodFinancials:
    """Fill in line items that can be uniquely derived from others."""
    is_ = period.income_statement
    bs = period.balance_sheet
    cf = period.cash_flow

    if is_.gross_profit is None and is_.revenue is not None and is_.cogs is not None:
        is_.gross_profit = is_.revenue - is_.cogs
    if is_.ebitda is None and is_.ebit is not None and is_.depreciation_amortization is not None:
        is_.ebitda = is_.ebit + is_.depreciation_amortization
    if is_.ebit is None and is_.ebitda is not None and is_.depreciation_amortization is not None:
        is_.ebit = is_.ebitda - is_.depreciation_amortization
    if cf.free_cash_flow is None and cf.operating_cash_flow is not None and cf.capital_expenditures is not None:
        cf.free_cash_flow = cf.operating_cash_flow - cf.capital_expenditures
    return period


@dataclass
class RatioResult:
    key: str
    label: str
    category: str
    value: float | None
    formula: str
    unit: str = "x"
    healthy_min: float | None = None
    healthy_max: float | None = None
    within_healthy_band: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "category": self.category,
            "value": self.value,
            "formula": self.formula,
            "unit": self.unit,
            "healthy_min": self.healthy_min,
            "healthy_max": self.healthy_max,
            "within_healthy_band": self.within_healthy_band,
        }


@dataclass
class RatioSet:
    period: str
    results: list[RatioResult] = field(default_factory=list)

    def get(self, key: str) -> RatioResult | None:
        for r in self.results:
            if r.key == key:
                return r
        return None

    def as_dict(self) -> dict[str, Any]:
        return {r.key: r.value for r in self.results}

    def by_category(self) -> dict[str, list[RatioResult]]:
        out: dict[str, list[RatioResult]] = {}
        for r in self.results:
            out.setdefault(r.category, []).append(r)
        return out


def compute_ratios(current: PeriodFinancials, prior: PeriodFinancials | None = None) -> RatioSet:
    current = _derive(current)
    is_ = current.income_statement
    bs = current.balance_sheet
    cf = current.cash_flow

    avg_bs = None
    if prior is not None:
        prior = _derive(prior)
        def _avg(a: float | None, b: float | None) -> float | None:
            return None if a is None or b is None else (a + b) / 2
        avg_bs = type(bs)(
            accounts_receivable=_avg(bs.accounts_receivable, prior.balance_sheet.accounts_receivable),
            inventory=_avg(bs.inventory, prior.balance_sheet.inventory),
            total_assets=_avg(bs.total_assets, prior.balance_sheet.total_assets),
            total_equity=_avg(bs.total_equity, prior.balance_sheet.total_equity),
        )

    rev = is_.revenue
    ar = avg_bs.accounts_receivable if avg_bs else bs.accounts_receivable
    inv = avg_bs.inventory if avg_bs else bs.inventory
    ap = bs.accounts_payable
    cogs = is_.cogs

    net_interest_expense = None
    if is_.interest_expense is not None or is_.interest_income is not None:
        net_interest_expense = abs((is_.interest_expense or 0) - (is_.interest_income or 0)) or None

    receivables_turnover = _safe_div(rev, ar)
    inventory_turnover = _safe_div(cogs, inv)
    dpo_turnover = _safe_div(cogs, ap) if ap not in (None, 0) else None
    dso = _safe_div(365, receivables_turnover)
    dio = _safe_div(365, inventory_turnover)
    dpo = _safe_div(365, dpo_turnover)

    values: dict[str, float | None] = {
        "current_ratio": _safe_div(bs.current_assets, bs.current_liabilities),
        "quick_ratio": _safe_div((bs.current_assets or 0) - (bs.inventory or 0), bs.current_liabilities),
        "cash_ratio": _safe_div((bs.cash_and_equivalents or 0) + (bs.marketable_securities or 0), bs.current_liabilities),
        "debt_to_equity": _safe_div(bs.total_debt, bs.total_equity),
        "debt_to_assets": _safe_div(bs.total_debt, bs.total_assets),
        "equity_ratio": _safe_div(bs.total_equity, bs.total_assets),
        "interest_coverage": _safe_div(is_.ebit, is_.interest_expense),
        "ebitda_interest_coverage": _safe_div(is_.ebitda, is_.interest_expense),
        "gross_margin": _safe_div(is_.gross_profit, rev),
        "operating_margin": _safe_div(is_.ebit, rev),
        "net_margin": _safe_div(is_.net_income, rev),
        "ebitda_margin": _safe_div(is_.ebitda, rev),
        "return_on_assets": _safe_div(is_.net_income, avg_bs.total_assets if avg_bs else bs.total_assets),
        "return_on_equity": _safe_div(is_.net_income, avg_bs.total_equity if avg_bs else bs.total_equity),
        "asset_turnover": _safe_div(rev, avg_bs.total_assets if avg_bs else bs.total_assets),
        "inventory_turnover": inventory_turnover,
        "receivables_turnover": receivables_turnover,
        "days_sales_outstanding": dso,
        "days_inventory_outstanding": dio,
        "cash_conversion_cycle": (dso or 0) + (dio or 0) - (dpo or 0) if (dso is not None or dio is not None or dpo is not None) else None,
        "operating_cash_flow_ratio": _safe_div(cf.operating_cash_flow, bs.current_liabilities),
        "free_cash_flow_margin": _safe_div(cf.free_cash_flow, rev),
        "ebitda_net_interest_cover": _safe_div(is_.ebitda, net_interest_expense),
        "leverage_metric": _safe_div(bs.total_debt, is_.ebitda),
        "net_leverage": _safe_div(
            (bs.total_debt or 0) - (bs.cash_and_equivalents or 0) - (bs.marketable_securities or 0),
            is_.ebitda,
        ),
        "cf_to_capex": _safe_div(cf.operating_cash_flow, -(cf.capital_expenditures or 0))
        if cf.capital_expenditures else None,
    }

    # Bank-specific ratios (only when bank line items are present). These live in
    # the BANK category, which the corporate rating does not weight, so they never
    # distort a non-bank score. They simply surface for bank obligors.
    has_bank = (
        bs.loans_and_advances is not None
        or bs.customer_deposits is not None
        or is_.net_interest_income is not None
    )
    if has_bank:
        assets = avg_bs.total_assets if avg_bs else bs.total_assets
        values["net_interest_margin"] = _safe_div(is_.net_interest_income, assets)
        values["loan_to_deposit"] = _safe_div(bs.loans_and_advances, bs.customer_deposits)
        values["npl_ratio"] = _safe_div(bs.non_performing_loans, bs.loans_and_advances)
        top_line = is_.revenue or is_.net_interest_income
        values["cost_to_income"] = _safe_div(is_.operating_expenses, top_line)

    results: list[RatioResult] = []
    for key, definition in RATIO_DEFINITIONS.items():
        val = values.get(key)
        within = None
        if val is not None:
            lo, hi = definition.healthy_min, definition.healthy_max
            if lo is not None and hi is not None:
                within = lo <= val <= hi
            elif lo is not None:
                within = val >= lo
            elif hi is not None:
                within = val <= hi
        results.append(RatioResult(
            key=key, label=definition.label, category=definition.category.value,
            value=val, formula=definition.formula, unit=definition.unit,
            healthy_min=definition.healthy_min, healthy_max=definition.healthy_max,
            within_healthy_band=within,
        ))

    return RatioSet(period=current.period, results=results)
