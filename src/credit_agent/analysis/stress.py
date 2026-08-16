"""Stress testing.

Applies earnings-based shocks to the latest period and re-runs the full rating
pipeline to show how the credit profile degrades under adverse scenarios. This is
the forward-looking, IFRS 9 / Basel-aligned piece of a credit review: a loan that
is investment grade today must remain acceptable under downside stress.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..ratios.calculator import RatioSet, compute_ratios
from ..risk.rating import RiskRating, rate
from ..schema.financials import PeriodFinancials


@dataclass
class StressShock:
    name: str
    description: str
    revenue_delta: float = 0.0
    gross_margin_delta: float = 0.0
    interest_rate_delta: float = 0.0
    opex_delta: float = 0.0


PRESET_SCENARIOS: list[StressShock] = [
    StressShock(
        name="Demand contraction", description="Revenue -15%, gross margin -300bps",
        revenue_delta=-0.15, gross_margin_delta=-0.03,
    ),
    StressShock(
        name="Interest rate shock", description="Cost of debt +200bps",
        interest_rate_delta=0.02,
    ),
    StressShock(
        name="Combined downturn", description="Revenue -20%, margin -300bps, rates +200bps",
        revenue_delta=-0.20, gross_margin_delta=-0.03, interest_rate_delta=0.02,
    ),
    StressShock(
        name="Severe recession", description="Revenue -30%, margin -500bps, rates +300bps",
        revenue_delta=-0.30, gross_margin_delta=-0.05, interest_rate_delta=0.03,
    ),
]


@dataclass
class StressResult:
    scenario: str
    description: str
    base_rating: str
    stressed_rating: str
    base_pd: float
    stressed_pd: float
    rating_downgrade: int
    key_ratios_base: dict
    key_ratios_stressed: dict
    breached_covenants: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario, "description": self.description,
            "base_rating": self.base_rating, "stressed_rating": self.stressed_rating,
            "base_pd": self.base_pd, "stressed_pd": self.stressed_pd,
            "rating_downgrade": self.rating_downgrade,
            "key_ratios_base": self.key_ratios_base,
            "key_ratios_stressed": self.key_ratios_stressed,
            "breached_covenants": self.breached_covenants,
        }


def apply_stress(base: PeriodFinancials, shock: StressShock) -> PeriodFinancials:
    is_ = base.income_statement
    bs = base.balance_sheet

    revenue = (is_.revenue or 0) * (1 + shock.revenue_delta)
    base_gm = (is_.gross_profit or 0) / (is_.revenue or 1)
    gm = base_gm + shock.gross_margin_delta
    gross_profit = revenue * gm
    cogs = revenue - gross_profit
    opex = (is_.operating_expenses or 0) * (1 + shock.opex_delta)
    ebit = gross_profit - opex
    ebitda = (ebit or 0) + (is_.depreciation_amortization or 0)

    cost_of_debt = 0.0
    if (is_.interest_expense or 0) and (bs.total_debt or 0):
        cost_of_debt = (is_.interest_expense or 0) / (bs.total_debt or 1)
    interest_expense = (is_.interest_expense or 0) + shock.interest_rate_delta * (bs.total_debt or 0)

    pretax = ebit - interest_expense - (is_.interest_income or 0)
    tax_rate = 0.0
    if (is_.pretax_income or 0) != 0:
        tax_rate = (is_.tax_expense or 0) / (is_.pretax_income or 1)
    tax = max(pretax * tax_rate, 0)
    net_income = pretax - tax

    from ..schema.financials import BalanceSheet, CashFlow, IncomeStatement
    stressed_is = IncomeStatement(
        revenue=revenue, cogs=cogs, gross_profit=gross_profit,
        operating_expenses=opex, ebitda=ebitda,
        depreciation_amortization=is_.depreciation_amortization, ebit=ebit,
        interest_expense=interest_expense, interest_income=is_.interest_income,
        pretax_income=pretax, tax_expense=tax, net_income=net_income,
    )
    stressed_bs = BalanceSheet(
        cash_and_equivalents=bs.cash_and_equivalents, marketable_securities=bs.marketable_securities,
        accounts_receivable=bs.accounts_receivable, inventory=bs.inventory,
        current_assets=bs.current_assets, total_assets=bs.total_assets,
        accounts_payable=bs.accounts_payable, current_liabilities=bs.current_liabilities,
        total_liabilities=bs.total_liabilities, short_term_debt=bs.short_term_debt,
        long_term_debt=bs.long_term_debt, total_debt=bs.total_debt,
        total_equity=bs.total_equity, retained_earnings=bs.retained_earnings,
    )
    stressed_cf = CashFlow(
        operating_cash_flow=base.cash_flow.operating_cash_flow,
        capital_expenditures=base.cash_flow.capital_expenditures,
        free_cash_flow=base.cash_flow.free_cash_flow,
    )
    return PeriodFinancials(period=f"{base.period}_stressed", income_statement=stressed_is,
                            balance_sheet=stressed_bs, cash_flow=stressed_cf)


_RATING_ORDER = ["D", "CC", "CCC", "B", "BB", "BBB", "A", "AA", "AAA"]


def run_stress(base: PeriodFinancials, prior: PeriodFinancials | None,
               scenarios: list[StressShock] | None = None) -> list[StressResult]:
    scenarios = scenarios or PRESET_SCENARIOS
    base_ratios: RatioSet = compute_ratios(base, prior)
    base_rating: RiskRating = rate(base_ratios)

    key_keys = ["ebitda_margin", "leverage_metric", "ebitda_net_interest_cover", "current_ratio", "net_leverage"]
    results: list[StressResult] = []
    for shock in scenarios:
        stressed = apply_stress(base, shock)
        s_ratios = compute_ratios(stressed, prior)
        s_rating = rate(s_ratios)
        base_idx = _RATING_ORDER.index(base_rating.band.value)
        s_idx = _RATING_ORDER.index(s_rating.band.value)
        breached = [
            "Maximum Leverage" if (s_ratios.get("leverage_metric").value or 0) > 4 else "",
            "Minimum Interest Cover" if (s_ratios.get("ebitda_net_interest_cover").value or 0) < 3 else "",
            "Maximum Net Leverage" if (s_ratios.get("net_leverage").value or 99) > 3 else "",
        ]
        breached = [b for b in breached if b]
        results.append(StressResult(
            scenario=shock.name, description=shock.description,
            base_rating=base_rating.band.value, stressed_rating=s_rating.band.value,
            base_pd=base_rating.pd_estimate, stressed_pd=s_rating.pd_estimate,
            rating_downgrade=base_idx - s_idx,
            key_ratios_base={k: base_ratios.get(k).value for k in key_keys},
            key_ratios_stressed={k: s_ratios.get(k).value for k in key_keys},
            breached_covenants=breached,
        ))
    return results
