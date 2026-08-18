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

# Real-life ways credit assessments commonly miss risk. These are methodology prompts
# for the analyst to verify — never assertions about a specific client. Advisory only.
_BLIND_SPOTS = [
    "Concentration risk — a single customer, supplier, region or channel >20% of revenue/inputs "
    "can trigger sudden default if that counterparty shifts or distresses; verify top-5 shares.",
    "Related-party & off-balance-sheet — guarantees, letters of credit, contingent liabilities and "
    "related-party deals rarely appear in the statements; confirm via filings and director disclosures.",
    "Hidden leverage — operating leases, pensions, factoring or shareholder loans can sit "
    "off-balance-sheet, so true leverage may exceed reported debt/equity; restate before judging.",
    "Covenant blind spots — covenants outside the modelled set (springing, incurrence, guarantee) or "
    "headroom that looks ample until one bad quarter; re-test against stress.",
    "Rate & FX mismatch — floating-rate debt reprices higher in a tightening cycle and FX mismatched "
    "to revenue can flip coverage; check the debt book's currency and basis.",
    "Input-cost & commodity exposure — a key input can reprice faster than price can be passed through; "
    "map gross-margin sensitivity to input costs.",
    "Geopolitical & trade policy — sanctions, tariffs or export-licence changes in a dependent market "
    "can erase revenue overnight; map geographic revenue and supply.",
    "Operational & cyber disruption — single-site manufacturing, single-source supply or a cyber "
    "incident can halt cash generation for quarters; assess continuity and redundancy.",
    "Competitive shock — a rival merger, new entrant or substitute can compress margins or steal "
    "share; track competitor moves and channel shift.",
    "Event & fraud risk — financial-statement manipulation, key-person/succession gaps or a one-off "
    "shock are rarely in the numbers until they hit; corroborate with non-financial signals.",
    "ESG & regulatory — new environmental, labour or packaging regulation (and greenwashing backlash) "
    "can impose sudden cost or block market access; monitor the regulatory pipeline.",
    "Demand cyclicality — revenue tied to discretionary or capex-cycle demand can collapse in a "
    "downturn before leverage adjusts; stress the demand side, not just the balance sheet.",
]


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
    sector: str | None = None,
    company_background: str | None = None,
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

    # Engagement + Executive Summary
    def _last(vals):
        if not vals:
            return None
        for v in reversed(vals):
            if v is not None:
                return v
        return None

    def _yoy(key):
        g = kyoy(key)
        return g[-1] if g else None

    def _kpi_bullet(key, label, note=None):
        last = _last(kvals(key))
        if last is None:
            return None
        g = _yoy(key)
        txt = f"{label}: {_fmt_num(last, currency)}"
        if g is not None:
            txt += f" ({g*100:+.0f}% YoY)"
        if note:
            txt += f" — {note}"
        return txt

    # Strengths / weaknesses (feed Risk Assessment + Actionable Insights)
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

    if purpose:
        blocks.append({"kind": "p", "text":
            f"{company_name} is reviewed to answer the following engagement question: "
            f"“{purpose}”."})
    else:
        blocks.append({"kind": "p", "text":
            f"{company_name} is reviewed as part of the annual credit assessment."})

    last_rev = _last(kvals("revenue")); rev_g = _yoy("revenue")
    em = rv("ebitda_margin"); nm = rv("net_margin")
    exec_bits = []
    if last_rev is not None:
        bit = f"revenue of {_fmt_num(last_rev, currency)} ({currency})"
        if rev_g is not None:
            bit += f", up {rev_g*100:+.1f}% year-on-year"
        exec_bits.append(bit)
    mbits = []
    if em is not None:
        mbits.append(f"EBITDA margin {_fmt_ratio(em, ru('ebitda_margin') or '%')}")
    if nm is not None:
        mbits.append(f"net margin {_fmt_ratio(nm, ru('net_margin') or '%')}")
    if mbits:
        exec_bits.append(" and ".join(mbits))
    sector_txt = f" in the {sector} sector" if sector else ""
    exec_txt = (
        f"{company_name}{sector_txt} is assessed as a {band}-rated credit "
        f"(composite {rating.get('composite_score')}, implied PD {rating.get('pd_estimate')}). "
    )
    if exec_bits:
        exec_txt += "The latest period shows " + "; ".join(exec_bits) + ". "
    exec_txt += f"The recommendation is {rec}, subject to the conditions set out below."
    blocks.append({"kind": "h2", "text": "Executive Summary"})
    blocks.append({"kind": "p", "text": exec_txt})
    blocks.append({"kind": "p", "text":
        f"All quantitative figures are computed from the statements for {', '.join(periods) or 'n/a'}; "
        f"qualitative context is drawn from live industry research where available."})

    # Company overview (user-supplied context; rendered verbatim, never invented)
    if company_background and company_background.strip():
        blocks.append({"kind": "h2", "text": "Company Overview"})
        blocks.append({"kind": "p", "text": company_background.strip()})

    # ---- Financial Analysis ----
    blocks.append({"kind": "h2", "text": "Financial Analysis"})

    blocks.append({"kind": "h3", "text": "Revenue and Profitability"})
    rp = []
    for key in ("revenue", "ebitda", "operating_profit", "net_income"):
        b = _kpi_bullet(key, key.replace("_", " ").title())
        if b:
            rp.append(b)
    if em is not None:
        rp.append(f"EBITDA margin: {_fmt_ratio(em, ru('ebitda_margin') or '%')} ({traj_of('ebitda_margin')}).")
    if nm is not None:
        rp.append(f"Net margin: {_fmt_ratio(nm, ru('net_margin') or '%')} ({traj_of('net_margin')}).")
    if rp:
        blocks.append({"kind": "bullets", "items": rp})

    blocks.append({"kind": "h3", "text": "Assets and Liabilities"})
    cash_g = _yoy("cash_and_equivalents"); capex_g = _yoy("capital_expenditures")
    cash_note = None
    if cash_g is not None and cash_g < 0 and capex_g is not None and capex_g > 0:
        cash_note = "reflecting higher capital expenditure and debt repayment; monitor liquidity"
    al = []
    for key, lbl in (("total_assets", "Total Assets"), ("inventory", "Inventory"),
                     ("cash_and_equivalents", "Cash & equivalents"),
                     ("total_liabilities", "Total Liabilities"),
                     ("total_equity", "Net Worth (Total Equity)")):
        b = _kpi_bullet(key, lbl, note=cash_note if key == "cash_and_equivalents" else None)
        if b:
            al.append(b)
    if al:
        blocks.append({"kind": "bullets", "items": al})

    blocks.append({"kind": "h3", "text": "Cash Flow"})
    cf = []
    for key in ("operating_cash_flow", "capital_expenditures", "free_cash_flow"):
        b = _kpi_bullet(key, key.replace("_", " ").title())
        if b:
            cf.append(b)
    if cf:
        blocks.append({"kind": "bullets", "items": cf})

    # ---- Key Financial Ratios ----
    blocks.append({"kind": "h2", "text": "Key Financial Ratios"})
    blocks.append({"kind": "h3", "text": "Profitability Ratios"})
    prof = []
    for k in ("gross_margin", "ebitda_margin", "operating_margin", "net_margin"):
        v = rv(k)
        if v is not None:
            prof.append(f"{ratios_by_key.get(k, {}).get('label', k)}: "
                        f"{_fmt_ratio(v, ru(k) or '%')} ({traj_of(k)}).")
    if prof:
        blocks.append({"kind": "bullets", "items": prof})

    blocks.append({"kind": "h3", "text": "Leverage and Liquidity Ratios"})
    ll = []
    for k in ("interest_coverage", "ebitda_interest_cover", "current_ratio", "quick_ratio",
              "cash_ratio", "debt_to_equity", "leverage_metric", "net_leverage", "cf_capex"):
        v = rv(k)
        if v is not None:
            ll.append(f"{ratios_by_key.get(k, {}).get('label', k)}: "
                      f"{_fmt_ratio(v, ru(k) or 'x')} ({traj_of(k)}).")
    if ll:
        blocks.append({"kind": "bullets", "items": ll})

    # ---- Key strengths ----
    if strengths:
        blocks.append({"kind": "h2", "text": "Key Strengths"})
        blocks.append({"kind": "bullets", "items": strengths})

    # ---- Risk Assessment ----
    blocks.append({"kind": "h2", "text": "Risk Assessment"})
    blocks.append({"kind": "h3", "text": "Key Financial Risks"})
    risks = []
    liq = [k for k in ("current_ratio", "quick_ratio", "cash_ratio")
           if traj.get(k, {}).get("trajectory") == "deteriorating"]
    if liq:
        risks.append(
            "Liquidity Risk: current/quick/cash ratios are softening, reducing the cushion to "
            "meet short-term obligations; monitor cash and working capital closely.")
    cfk = rv("cf_capex")
    capex_up = (_yoy("capital_expenditures") or 0) > 0
    if (cfk is not None and traj.get("cf_capex", {}).get("trajectory") == "deteriorating") or capex_up:
        risks.append(
            "Capital Expenditure Risk: capital expenditure is elevated relative to operating cash "
            "flow, straining free cash flow; ensure investment is aligned with cash generation.")
    if traj.get("net_leverage", {}).get("trajectory") == "deteriorating" or (rv("leverage_metric") or 0) > 4:
        risks.append(
            "Leverage Risk: leverage has increased (notably via a lower cash balance); maintain "
            "discipline as EBITDA normalises.")
    invg = _yoy("inventory")
    if invg is not None and invg > 0.2:
        risks.append(
            f"Inventory Risk: inventory rose {invg*100:+.0f}% YoY; manage stock efficiently to "
            f"avoid overstocking and holding costs.")
    if not risks:
        risks.append("No elevated financial risks are identified on the available trends; the profile is stable to improving.")
    for i, r in enumerate(risks, 1):
        blocks.append({"kind": "p", "text": f"{i}. {r}"})

    # ---- Actionable Insights ----
    blocks.append({"kind": "h2", "text": "Actionable Insights"})
    actions = []
    if any(("liquidity" in r.lower() or "current" in r.lower()) for r in weaknesses):
        actions.append("Enhance liquidity management — rebuild cash reserves and optimise current-asset utilisation.")
    if capex_up or (cfk is not None and cfk < 0):
        actions.append("Monitor capital expenditure against operating cash flow to preserve financial stability.")
    if any("leverage" in r.lower() for r in risks + weaknesses):
        actions.append("Maintain leverage discipline — protect profitability and a healthy cash balance.")
    if invg is not None and invg > 0.2:
        actions.append("Streamline inventory processes to align with sales growth and minimise holding costs.")
    tight = [c for c in analysis.get("covenants", [])
             if str(c.get("status", "")).upper() in ("WATCH", "BREACH", "FAIL")]
    if tight:
        actions.append("Monitor covenant headroom: " + ", ".join(c["name"] for c in tight) + ".")
    if analysis.get("stress_scenarios"):
        actions.append("Re-test under stress scenarios each cycle; track rating migration and any covenant breaches.")
    actions.append("Refresh industry and macro research at every review.")
    if not actions:
        actions.append("Maintain quarterly monitoring of covenants, liquidity and capex intensity.")
    for i, a in enumerate(actions, 1):
        blocks.append({"kind": "p", "text": f"{i}. {a}"})

    # Adjacent Analysis (blind-spot scan) — advisory only, never alters judgement
    blocks.append({"kind": "h2", "text": "Adjacent Analysis (Blind-spot Scan)"})
    blocks.append({"kind": "p", "text":
        "Advisory only — these external signals and structural prompts do not alter the "
        "internal rating or recommendation. They are prompts for the analyst to investigate "
        "further before relying on this assessment."})

    # Sourced external signals (if live research ran)
    blocks.append({"kind": "h3", "text": "External signals (sourced)"})
    if research_report and research_report.get("findings"):
        adj = []
        for f in research_report.get("findings", [])[:6]:
            claim = (f.get("claim") or "").strip()
            url = f.get("source_url") or ""
            if claim:
                adj.append(f"{claim} [{url}]" if url else claim)
        if adj:
            blocks.append({"kind": "bullets", "items": adj})
    else:
        blocks.append({"kind": "p", "text":
            "No live research was performed, so no external signals are listed. Enable industry "
            "research to surface competitor, geopolitical and regulatory signals specific to this obligor."})

    # Curated blind-spot framework — how risk is commonly missed in real life
    blocks.append({"kind": "h3", "text": "Blind-spot checklist (verify against this obligor)"})
    blocks.append({"kind": "p", "text":
        "Common ways credit assessments miss risk — prompts to investigate, not findings about this client:"})
    blocks.append({"kind": "bullets", "items": _BLIND_SPOTS})

    # Industry & macro research (narrative context)
    if research_markdown or research_report:
        blocks.append({"kind": "h2", "text": "Industry & Macro Context"})
        if research_report:
            rep = research_report
            blocks.append({"kind": "p", "text":
                f"Live research drew on {len(rep.get('sources', []))} sources at "
                f"{rep.get('overall_confidence', 0):.2f} validation confidence. "
                f"Sector: {rep.get('sector', 'n/a')}."})
            if research_markdown:
                blocks.append({"kind": "p", "text": research_markdown[:2000]})
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
