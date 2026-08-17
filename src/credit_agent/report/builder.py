"""Credit assessment report assembler.

Turns the deterministic analysis, live research, standards scoping and (optional)
LLM assessment into a structured document model of typed blocks. The same block
list is rendered to PDF (reportlab), Word (python-docx) and HTML preview, so the
branding and content stay consistent across formats.
"""

from __future__ import annotations

from datetime import datetime

from .cam import _fmt_num, _fmt_ratio

BRANDING = {
    "name": "Lawrence Oladeji",
    "title": "The Agent Build for Credit Analyst",
    "email": "oladeji.lawrence@gmail.com",
}

RECOMMENDATION_BY_BAND = {
    "AAA": "APPROVE",
    "AA": "APPROVE",
    "A": "APPROVE WITH CONDITIONS",
    "BBB": "APPROVE WITH CONDITIONS",
    "BB": "DECLINE / RESTRUCTURE",
    "B": "DECLINE",
    "CCC": "DECLINE",
    "CC": "DECLINE",
    "C": "DECLINE",
    "D": "DECLINE",
}


def _fmt(v):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def _banner_color(rec: str) -> str:
    r = (rec or "").upper()
    if "DECLINE" in r:
        return "red"
    if "CONDITION" in r or "RESTRUCTURE" in r or "MONITOR" in r:
        return "amber"
    if "APPROVE" in r:
        return "green"
    return "amber"


def _growth(a, b):
    if a in (None, 0) or b is None:
        return None
    return (b - a) / abs(a)


def assemble_report(
    analyst_name: str,
    company_name: str,
    purpose: str,
    analysis: dict,
    figures: dict | None = None,
    research_markdown: str | None = None,
    research_report: dict | None = None,
    standards_assessment: dict | None = None,
    llm_assessment_markdown: str | None = None,
) -> dict:
    blocks: list[dict] = []
    rating = analysis.get("risk_rating", {})
    band = rating.get("band", "n/a")
    rec = RECOMMENDATION_BY_BAND.get(band, "APPROVE WITH CONDITIONS")
    color = _banner_color(rec)

    periods = analysis.get("periods", [])
    currency = (figures or {}).get("currency") or analysis.get("currency")
    kpis = analysis.get("kpis", {})
    traj = analysis.get("ratio_trajectories", {})
    ratios_by_key = {r.get("key") or _slug(r["label"]): r for r in analysis.get("ratios", [])}

    def rv(key):
        r = ratios_by_key.get(key)
        return r["value"] if r and r.get("value") is not None else None

    def ru(key):
        r = ratios_by_key.get(key)
        return r.get("unit") if r else None

    def traj_of(key):
        return traj.get(key, {}).get("trajectory", "stable")

    def kvals(key):
        return kpis.get(key, {}).get("values", [])

    def kyoy(key):
        return kpis.get(key, {}).get("yoy_growth", [])

    # ===================================================================== #
    # PAGE 1 — Computed financial metrics (all years aligned, no narrative)
    # ===================================================================== #
    blocks.append({"kind": "h1", "text": "Computed Financial Metrics"})
    blocks.append({"kind": "p", "text":
        f"Every figure below is computed deterministically from the submitted financial "
        f"statements for {company_name}. Amounts are in {currency or 'reporting currency'}. "
        f"Periods reviewed: {', '.join(periods) if periods else 'n/a'}."})

    # Key absolute figures, one column per fiscal year
    blocks.append({"kind": "h2", "text": "Key figures"})
    kpi_specs = [
        ("revenue", "Revenue"),
        ("ebitda", "EBITDA"),
        ("net_income", "Net income"),
        ("total_assets", "Total assets"),
        ("total_debt", "Total debt"),
        ("total_equity", "Total equity"),
        ("operating_cash_flow", "Operating cash flow"),
        ("free_cash_flow", "Free cash flow"),
        ("cash_and_equivalents", "Cash & equivalents"),
    ]
    krows = []
    for key, label in kpi_specs:
        vals = kvals(key)
        if not vals or not any(v is not None for v in vals):
            continue
        krows.append([label] + [(_fmt_num(v, currency) if v is not None else "n/a") for v in vals])
    if krows:
        blocks.append({"kind": "table",
                       "headers": ["Metric"] + (periods or ["Value"]),
                       "rows": krows})

    # Financial ratios, one column per fiscal year
    blocks.append({"kind": "h2", "text": "Financial ratios"})
    rrows = []
    for r in analysis.get("ratios", []):
        key = r.get("key") or _slug(r["label"])
        t = traj.get(key, {})
        vals = t.get("values", [])
        cells = [(_fmt_ratio(v, r.get("unit")) if v is not None else "n/a") for v in vals]
        while len(cells) < len(periods):
            cells.append("n/a")
        cells = cells[:len(periods)] if periods else cells
        rrows.append([r["label"]] + cells + [t.get("trajectory") or "—"])
    if rrows:
        blocks.append({"kind": "table",
                       "headers": ["Ratio"] + periods + ["Trajectory"],
                       "rows": rrows})

    # Covenants (computed)
    if analysis.get("covenants"):
        blocks.append({"kind": "h2", "text": "Covenant compliance"})
        crow = [[c["name"],
                 _fmt_ratio(c.get("actual"), "x") if c.get("actual") is not None else "n/a",
                 c["threshold"], c["status"].upper()]
                for c in analysis["covenants"]]
        blocks.append({"kind": "table",
                       "headers": ["Covenant", "Actual", "Threshold", "Status"], "rows": crow})

    # Stress (computed)
    if analysis.get("stress_scenarios"):
        blocks.append({"kind": "h2", "text": "Stress testing"})
        srow = []
        for s in analysis["stress_scenarios"]:
            breach = ", ".join(s.get("breached_covenants", [])) or "none"
            srow.append([s["scenario"], f"{s['base_rating']} → {s['stressed_rating']}",
                         f"{s['rating_downgrade']} notch", breach])
        blocks.append({"kind": "table",
                       "headers": ["Scenario", "Rating migration", "Downgrade", "Breaches"], "rows": srow})

    # ===================================================================== #
    # PAGE BREAK → PAGE 2 — Credit brief (narrative report)
    # ===================================================================== #
    blocks.append({"kind": "pagebreak"})
    blocks.append({"kind": "h1", "text": "Credit Brief"})

    # Engagement
    if purpose:
        blocks.append({"kind": "p", "text":
            f"{company_name} is reviewed to answer the following engagement question: "
            f"“{purpose}”."})
    else:
        blocks.append({"kind": "p", "text":
            f"{company_name} is reviewed as part of the annual credit assessment."})
    blocks.append({"kind": "p", "text":
        f"The internal risk rating is {band} (composite score {rating.get('composite_score')}, "
        f"implied probability of default {rating.get('pd_estimate')}). All quantitative figures "
        f"are computed from the statements; qualitative context is drawn from live industry "
        f"research where available."})

    # Performance narrative
    rev_vals = kvals("revenue")
    if rev_vals and any(v is not None for v in rev_vals) and periods:
        first_rev = next((v for v in rev_vals if v is not None), None)
        last_rev = next((v for v in reversed(rev_vals) if v is not None), None)
        if len(periods) >= 2 and kyoy("revenue") and kyoy("revenue")[-1] is not None:
            growth = f"{kyoy('revenue')[-1]*100:+.1f}% year-on-year in {periods[-1]}"
        elif len(periods) >= 3 and kpis.get("revenue", {}).get("cagr") is not None:
            growth = f"{kpis['revenue']['cagr']*100:.1f}% CAGR over {periods[0]}–{periods[-1]}"
        else:
            growth = "a movement versus the prior period"
        em = rv("ebitda_margin")
        nm = rv("net_margin")
        margin_bits = []
        if em is not None:
            margin_bits.append(f"EBITDA margin {_fmt_ratio(em, ru('ebitda_margin') or '%')}")
        if nm is not None:
            margin_bits.append(f"net margin {_fmt_ratio(nm, ru('net_margin') or '%')}")
        margin_txt = (" with " + " and ".join(margin_bits)) if margin_bits else ""
        mword = {"improving": "strengthening", "deteriorating": "eroding"}.get(
            traj_of("gross_margin"), "stable")
        blocks.append({"kind": "h2", "text": "Financial performance"})
        blocks.append({"kind": "p", "text":
            f"Revenue reached {_fmt_num(last_rev, currency)} ({currency}) in {periods[-1]}, "
            f"{growth}, up from {_fmt_num(first_rev, currency)} in {periods[0]}. "
            f"Profitability is {mword}{margin_txt}."})

    # Position & leverage narrative
    ta, td, te = kvals("total_assets"), kvals("total_debt"), kvals("total_equity")
    lev, ic = rv("debt_to_equity"), rv("interest_coverage")
    if ta and any(v is not None for v in ta):
        last_ta = next((v for v in reversed(ta) if v is not None), None)
        last_td = next((v for v in reversed(td) if v is not None), None)
        last_te = next((v for v in reversed(te) if v is not None), None)
        lev_word = ("elevated" if (lev or 0) > 2 else "moderate" if (lev or 0) > 1 else "conservative")
        pos_txt = (
            f"As at {periods[-1]}, total assets of {_fmt_num(last_ta, currency)} are funded by "
            f"total debt of {_fmt_num(last_td, currency)} and total equity of {_fmt_num(last_te, currency)}. "
            f"Gearing (debt/equity) of "
            f"{_fmt_ratio(lev, ru('debt_to_equity') or 'x') if lev is not None else 'n/a'} is {lev_word}")
        if ic is not None:
            pos_txt += (f", and interest coverage of {_fmt_ratio(ic, ru('interest_coverage') or 'x')} "
                        f"{'comfortably services finance costs.' if ic >= 3 else 'leaves limited cushion above finance costs.'}")
        blocks.append({"kind": "h2", "text": "Financial position & leverage"})
        blocks.append({"kind": "p", "text": pos_txt})

    # Cash narrative
    ocf, fcf, cash = kvals("operating_cash_flow"), kvals("free_cash_flow"), kvals("cash_and_equivalents")
    if ocf and any(v is not None for v in ocf):
        last_ocf = next((v for v in reversed(ocf) if v is not None), None)
        last_fcf = next((v for v in reversed(fcf) if v is not None), None)
        last_cash = next((v for v in reversed(cash) if v is not None), None)
        cash_word = "supports" if (last_fcf or 0) >= 0 else "strains"
        cf_txt = (
            f"Operating cash flow of {_fmt_num(last_ocf, currency)} and free cash flow of "
            f"{_fmt_num(last_fcf, currency)} in {periods[-1]} {cash_word} debt service and "
            f"capital expenditure.")
        if last_cash is not None:
            cf_txt += f" Cash and equivalents of {_fmt_num(last_cash, currency)} provide liquidity headroom."
        blocks.append({"kind": "h2", "text": "Cash generation & liquidity"})
        blocks.append({"kind": "p", "text": cf_txt})

    # Strengths / watch items
    strengths, weaknesses = [], []
    for cat, score in rating.get("category_scores", {}).items():
        if score is not None:
            if score >= 4.0:
                strengths.append(f"Strong {cat} profile (score {score}/5).")
            elif score < 3.0:
                weaknesses.append(f"Weak {cat} profile (score {score}/5).")
    for slug, rt in traj.items():
        label = ratios_by_key.get(slug, {}).get("label", slug)
        if rt.get("trajectory") == "deteriorating":
            weaknesses.append(f"{label} is deteriorating.")
        elif rt.get("trajectory") == "improving":
            strengths.append(f"{label} is improving.")
    if strengths:
        blocks.append({"kind": "h2", "text": "Key strengths"})
        blocks.append({"kind": "bullets", "items": strengths})
    if weaknesses:
        blocks.append({"kind": "h2", "text": "Watch items & weaknesses"})
        blocks.append({"kind": "bullets", "items": weaknesses})

    # Industry & macro research
    if research_markdown or research_report:
        blocks.append({"kind": "h2", "text": "Industry & macro context"})
        if research_report:
            rep = research_report
            blocks.append({"kind": "p", "text":
                f"Live research drew on {len(rep.get('sources', []))} sources at "
                f"{rep.get('overall_confidence', 0):.2f} validation confidence. "
                f"Sector: {rep.get('sector', 'n/a')}."})
            for f in rep.get("findings", [])[:8]:
                blocks.append({"kind": "bullets", "items": [f"{f.get('claim', '')} [{f.get('source_url', '')}]"]})
        elif research_markdown:
            blocks.append({"kind": "p", "text": research_markdown[:3000]})

    # Standards compliance
    if standards_assessment:
        sa = standards_assessment
        blocks.append({"kind": "h2", "text": "Industry standard compliance"})
        blocks.append({"kind": "p", "text":
            f"Weighted compliance {sa.get('compliance_score', 0)*100:.0f}% "
            f"(coverage {sa.get('coverage', 0)*100:.0f}%). "
            + ("The obligor meets industry standard." if sa.get("meets_standard") else
               "Breaches observed: " + ", ".join(sa.get("breaches", [])) + ".")})

    # Optional LLM agent assessment
    if llm_assessment_markdown:
        blocks.append({"kind": "h2", "text": "Analyst agent assessment"})
        for line in llm_assessment_markdown.split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                blocks.append({"kind": "h3", "text": line.lstrip("# ").strip()})
            elif line.startswith("- "):
                blocks.append({"kind": "bullets", "items": [line[2:].strip()]})
            else:
                blocks.append({"kind": "p", "text": line})

    # Color-coded recommendation banner
    blocks.append({"kind": "banner", "level": color, "band": band,
                   "text": f"Recommendation: {rec}",
                   "detail": (f"Internal rating {band} · implied PD {rating.get('pd_estimate')} · "
                              f"composite {rating.get('composite_score')}")})

    # Conclusion
    blocks.append({"kind": "h2", "text": "Conclusion"})
    blocks.append({"kind": "p", "text":
        f"On the available evidence {company_name} presents a {band}-rated credit profile. "
        f"The recommendation is {rec}, subject to the monitoring conditions below."})
    if analysis.get("scenario_definitions"):
        blocks.append({"kind": "bullets", "items":
            ["Monitor covenant headroom quarterly.",
             "Track liquidity and capex intensity against operating cash generation.",
             "Refresh industry research at each review cycle."]})

    return {
        "cover": {
            "analyst_name": analyst_name or BRANDING["name"],
            "company_name": company_name,
            "purpose": purpose,
            "generated_at": datetime.now().strftime("%d %B %Y"),
            "rating_band": band,
        },
        "blocks": blocks,
        "branding": BRANDING,
    }


def _slug(label: str) -> str:
    return label.lower().replace(" ", "_").replace("/", "_").replace("(", "").replace(")", "")
