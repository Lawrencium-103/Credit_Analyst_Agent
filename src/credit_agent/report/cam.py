"""Credit Approval Memo (CAM) generation.

Assembles a structured preliminary credit report from the validated analytics:
trends, ratio analysis, risk rating and covenant compliance. The narrative is
generated deterministically from the data so the memo is usable without an LLM;
the orchestration layer later enriches it with qualitative judgement.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..analysis.covenants import CovenantResult, evaluate_covenants
from ..analysis.trend import analyze_ratio_trends, analyze_trends
from ..ratios.calculator import RatioSet, compute_ratios
from ..risk.rating import RatingBand, RiskRating, rate
from ..schema.financials import CompanyFinancials


def _fmt_num(v: float | None, currency: str | None = None) -> str:
    if v is None:
        return "n/a"
    if currency and "thousand" in currency.lower():
        return f"{v:,.0f}"
    return f"{v:,.2f}"


def _fmt_ratio(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit == "%":
        return f"{value * 100:.1f}%"
    if unit == "days":
        return f"{value:.0f} days"
    return f"{value:.2f}x"


class RatioRow(BaseModel):
    label: str
    category: str
    latest: str
    prior: str
    trajectory: str


class CovenantRow(BaseModel):
    name: str
    description: str
    actual: str
    threshold: str
    status: str


class CreditMemo(BaseModel):
    entity_name: str
    currency: str | None = None
    periods: list[str] = Field(default_factory=list)
    executive_summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    financial_performance: list[str] = Field(default_factory=list)
    financial_position: list[str] = Field(default_factory=list)
    cash_flows: list[str] = Field(default_factory=list)
    ratio_table: list[RatioRow] = Field(default_factory=list)
    rating_band: str = ""
    pd_estimate: float | None = None
    composite_score: float | None = None
    category_scores: dict[str, float] = Field(default_factory=dict)
    covenants: list[CovenantRow] = Field(default_factory=list)
    covenant_breach: bool = False
    recommendation: str = ""


def build_memo(company: CompanyFinancials, covenants=None) -> CreditMemo:
    periods = company.periods
    latest = periods[-1]
    prior = periods[-2] if len(periods) >= 2 else None

    latest_ratios: RatioSet = compute_ratios(latest, prior)
    prior_ratios: RatioSet | None = compute_ratios(prior, periods[-3] if len(periods) >= 3 else None) if prior else None
    rating: RiskRating = rate(latest_ratios)

    kpi_trends = analyze_trends(company)
    ratio_trends = analyze_ratio_trends(company)
    covenant_results = evaluate_covenants(latest_ratios, covenants)

    memo = CreditMemo(
        entity_name=company.entity_name, currency=company.currency,
        periods=[p.period for p in periods],
        rating_band=rating.band.value, pd_estimate=rating.pd_estimate,
        composite_score=rating.composite_score,
        category_scores={c.category: c.score for c in rating.category_scores},
    )

    rev_t = kpi_trends.get("revenue")
    ebitda_t = kpi_trends.get("ebitda")
    multi_year = len(periods) >= 3
    if rev_t and rev_t.cagr is not None:
        if multi_year:
            growth = f"{rev_t.cagr * 100:.1f}% CAGR over {periods[0].period}-{latest.period}"
        else:
            growth = f"{rev_t.yoy_growth[-1] * 100:.1f}% year-on-year in {latest.period}"
        memo.financial_performance.append(
            f"Revenue {growth}, from {_fmt_num(rev_t.values[0], company.currency)} "
            f"to {_fmt_num(rev_t.values[-1], company.currency)} ({company.currency or 'ccy'})."
        )
    if ebitda_t and ebitda_t.cagr is not None:
        if multi_year:
            growth = f"{ebitda_t.cagr * 100:.1f}% CAGR"
        else:
            growth = f"{ebitda_t.yoy_growth[-1] * 100:.1f}% year-on-year"
        memo.financial_performance.append(
            f"EBITDA expanded by {growth}, signalling improving operating leverage."
        )
    gm = latest_ratios.get("gross_margin")
    em = latest_ratios.get("ebitda_margin")
    if gm and em:
        memo.financial_performance.append(
            f"Margins strengthened: gross {_fmt_ratio(gm.value, gm.unit)} and EBITDA margin {_fmt_ratio(em.value, em.unit)}."
        )

    ta = kpi_trends.get("total_assets")
    td = kpi_trends.get("total_debt")
    te = kpi_trends.get("total_equity")
    if ta and ta.values[-1] is not None and ta.values[0] is not None:
        memo.financial_position.append(
            f"Total assets grew to {_fmt_num(ta.values[-1], company.currency)} "
            f"(from {_fmt_num(ta.values[0], company.currency)})."
        )
    if td and te:
        lev = latest_ratios.get("debt_to_equity")
        memo.financial_position.append(
            f"Gearing (debt/equity) at {_fmt_ratio(lev.value, lev.unit)} with total debt "
            f"{_fmt_num(td.values[-1], company.currency)} against equity {_fmt_num(te.values[-1], company.currency)}."
        )

    ocf = kpi_trends.get("operating_cash_flow")
    fcf = kpi_trends.get("free_cash_flow")
    if ocf and ocf.values[-1] is not None:
        memo.cash_flows.append(
            f"Operating cash flow of {_fmt_num(ocf.values[-1], company.currency)} in {latest.period}."
        )
    if fcf and fcf.values[-1] is not None:
        memo.cash_flows.append(
            f"Free cash flow of {_fmt_num(fcf.values[-1], company.currency)} supports debt service and capex."
        )

    for r in latest_ratios.results:
        if r.value is None:
            continue
        prior_val = prior_ratios.get(r.key).value if prior_ratios else None
        prior_str = _fmt_ratio(prior_val, r.unit) if prior_val is not None else "-"
        memo.ratio_table.append(RatioRow(
            label=r.label, category=r.category,
            latest=_fmt_ratio(r.value, r.unit), prior=prior_str,
            trajectory=ratio_trends.get(r.key, _null_trend()).trajectory,
        ))

    for cat_score in rating.category_scores:
        if cat_score.score is not None and cat_score.score >= 4.0:
            memo.strengths.append(f"Strong {cat_score.category} profile (score {cat_score.score:.1f}/5).")
        elif cat_score.score is not None and cat_score.score < 3.0:
            memo.weaknesses.append(f"Weak {cat_score.category} profile (score {cat_score.score:.1f}/5).")
    for key, rt in ratio_trends.items():
        if rt.trajectory == "deteriorating":
            memo.weaknesses.append(f"{rt.label} is deteriorating ({_direction_word(rt)}).")
        elif rt.trajectory == "improving":
            memo.strengths.append(f"{rt.label} is improving ({_direction_word(rt)}).")

    for cr in covenant_results:
        memo.covenants.append(CovenantRow(
            name=cr.name, description=cr.description,
            actual=_fmt_ratio(cr.actual, "x") if cr.actual is not None else "n/a",
            threshold=f"{cr.operator} {cr.threshold:.2f}x",
            status=cr.status.value,
        ))
        if cr.status.value == "FAIL":
            memo.covenant_breach = True

    memo.executive_summary = (
        f"{company.entity_name} carries an internal risk rating of {rating.band.value} "
        f"(composite {rating.composite_score:.2f}, implied PD {rating.pd_estimate * 100:.2f}%). "
        f"The client exhibits {'a breach in covenant compliance' if memo.covenant_breach else 'covenant compliance'}. "
        f"Credit fundamentals are {'strong' if rating.band in (RatingBand.AAA, RatingBand.AA, RatingBand.A) else 'adequate'} "
        f"and support continuation of the banking relationship subject to the conditions below."
    )
    memo.recommendation = _recommendation(rating, memo.covenant_breach)
    return memo


def _null_trend():
    from ..analysis.trend import RatioTrend
    return RatioTrend(key="", label="", category="", direction="", values=[], periods=[], trajectory="stable")


def _direction_word(rt) -> str:
    return "up" if rt.trajectory == "improving" else ("down" if rt.trajectory == "deteriorating" else "flat")


def _recommendation(rating: RiskRating, breach: bool) -> str:
    if breach:
        return ("Recommendation: APPROVE with conditions. Covenant breach must be cured or waived; "
                "propose a remediation plan and closer monitoring until restored.")
    if rating.band in (RatingBand.AAA, RatingBand.AA, RatingBand.A, RatingBand.BBB):
        return ("Recommendation: APPROVE. Credit profile is investment grade; proceed with the annual "
                "review and facility renewal on standard terms, maintaining quarterly monitoring.")
    return ("Recommendation: APPROVE with heightened monitoring. Sub-investment-grade indicators require "
            "tighter covenants, periodic review and possibly risk pricing adjustment.")


def render_markdown(memo: CreditMemo) -> str:
    lines: list[str] = []
    lines.append(f"# Credit Approval Memo — Preliminary Review")
    lines.append(f"**Client:** {memo.entity_name}  ")
    lines.append(f"**Currency:** {memo.currency or 'n/a'}  ")
    lines.append(f"**Periods analysed:** {', '.join(memo.periods)}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(memo.executive_summary)
    lines.append("")
    lines.append("## Risk Rating")
    lines.append("")
    lines.append(f"- **Internal rating:** {memo.rating_band}")
    lines.append(f"- **Composite score:** {memo.composite_score}")
    lines.append(f"- **Implied PD:** {memo.pd_estimate * 100:.2f}%")
    for cat, score in memo.category_scores.items():
        lines.append(f"- **{cat.title()}:** {score}")
    lines.append("")
    lines.append("## Key Strengths")
    for s in memo.strengths:
        lines.append(f"- {s}")
    if not memo.strengths:
        lines.append("- None identified.")
    lines.append("")
    lines.append("## Key Weaknesses / Watch Items")
    for w in memo.weaknesses:
        lines.append(f"- {w}")
    if not memo.weaknesses:
        lines.append("- None identified.")
    lines.append("")
    lines.append("## Financial Performance")
    for s in memo.financial_performance:
        lines.append(f"- {s}")
    lines.append("")
    lines.append("## Financial Position")
    for s in memo.financial_position:
        lines.append(f"- {s}")
    lines.append("")
    lines.append("## Cash Flows")
    for s in memo.cash_flows:
        lines.append(f"- {s}")
    lines.append("")
    lines.append("## Ratio Analysis")
    lines.append("")
    lines.append("| Ratio | Latest | Prior | Trajectory |")
    lines.append("| --- | --- | --- | --- |")
    for row in memo.ratio_table:
        lines.append(f"| {row.label} | {row.latest} | {row.prior} | {row.trajectory} |")
    lines.append("")
    lines.append("## Covenant Compliance")
    lines.append("")
    lines.append("| Covenant | Actual | Threshold | Status |")
    lines.append("| --- | --- | --- | --- |")
    for c in memo.covenants:
        lines.append(f"| {c.name} | {c.actual} | {c.threshold} | {c.status} |")
    lines.append("")
    lines.append("## Recommendation")
    lines.append("")
    lines.append(memo.recommendation)
    lines.append("")
    return "\n".join(lines)
