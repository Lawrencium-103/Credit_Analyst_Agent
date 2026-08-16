import math

from credit_agent import (
    CompanyFinancials,
    PeriodFinancials,
    compute_ratios,
    rate,
)
from credit_agent.schema.financials import IncomeStatement
from examples.sample_financials import GREEN_SOLUTIONS


def _approx(a, b, tol=1e-6):
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=tol)


def test_current_ratio_fy2023():
    cf = GREEN_SOLUTIONS
    ratios = compute_ratios(cf.latest(), cf.prior())
    cr = ratios.get("current_ratio")
    assert cr.value is not None
    assert _approx(cr.value, 130.0 / 82.0)


def test_debt_to_equity_fy2023():
    ratios = compute_ratios(GREEN_SOLUTIONS.latest(), GREEN_SOLUTIONS.prior())
    dte = ratios.get("debt_to_equity")
    assert _approx(dte.value, 95.0 / 130.0)
    assert dte.within_healthy_band is True


def test_derivation_gross_profit():
    p = PeriodFinancials(
        period="T", income_statement=IncomeStatement(revenue=100.0, cogs=60.0),
    )
    ratios = compute_ratios(p)
    gm = ratios.get("gross_margin")
    assert _approx(gm.value, 0.4)


def test_risk_rating_band():
    cf = GREEN_SOLUTIONS
    ratios = compute_ratios(cf.latest(), cf.prior())
    rating = rate(ratios)
    assert rating.band.value in {"A", "AA", "AAA", "BBB"}
    assert 0.0 < rating.pd_estimate <= 1.0
    assert rating.composite_score > 0


def test_returns_none_on_missing_inputs():
    p = PeriodFinancials(period="X")
    ratios = compute_ratios(p)
    assert ratios.get("current_ratio").value is None
