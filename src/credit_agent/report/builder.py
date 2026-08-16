"""Credit assessment report assembler.

Turns the deterministic analysis, live research, standards scoping and (optional)
LLM assessment into a structured document model of typed blocks. The same block
list is rendered to PDF (reportlab), Word (python-docx) and HTML preview, so the
branding and content stay consistent across formats.
"""

from __future__ import annotations

from datetime import datetime

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

    # --- 1. Client & engagement
    blocks.append({"kind": "h2", "text": "1. Client & Engagement"})
    intro = (
        f"{company_name} is reviewed as part of the annual credit assessment. "
        f"The internal risk rating is {band} (composite {rating.get('composite_score')}, "
        f"implied PD {rating.get('pd_estimate')})."
    )
    blocks.append({"kind": "p", "text": intro})
    if purpose:
        blocks.append({"kind": "p", "text": f"Engagement question: {purpose}"})

    # --- 2. Quantitative analysis
    blocks.append({"kind": "h2", "text": "2. Quantitative Analysis"})
    if figures and figures.get("latest"):
        lt, pr = figures["latest"], figures.get("prior") or {}
        rev_g = _growth(pr.get("revenue"), lt.get("revenue"))
        blocks.append({"kind": "h3", "text": "2.1 Financial performance"})
        perf = []
        if rev_g is not None:
            perf.append(f"Revenue of {_fmt(lt['revenue'])} {figures.get('currency')} "
                        f"({'+' if rev_g >= 0 else ''}{rev_g*100:.1f}% YoY).")
        for k, label in [("ebitda", "EBITDA"), ("net_income", "Net income")]:
            if lt.get(k) is not None:
                perf.append(f"{label} of {_fmt(lt[k])} {figures.get('currency')}.")
        blocks.append({"kind": "bullets", "items": perf})
        blocks.append({"kind": "h3", "text": "2.2 Financial position & cash flows"})
        pos = []
        if lt.get("total_assets") is not None:
            pos.append(f"Total assets {_fmt(lt['total_assets'])}; total debt {_fmt(lt['total_debt'])}; "
                       f"total equity {_fmt(lt['total_equity'])}.")
        if lt.get("ocf") is not None:
            pos.append(f"Operating cash flow {_fmt(lt['ocf'])}; free cash flow {_fmt(lt.get('fcf'))}.")
        if lt.get("cash") is not None:
            pos.append(f"Cash & equivalents {_fmt(lt['cash'])}.")
        blocks.append({"kind": "bullets", "items": pos})

    # 2.3 Key ratios table
    blocks.append({"kind": "h3", "text": "2.3 Key financial ratios"})
    traj = analysis.get("ratio_trajectories", {})
    rows = []
    for r in analysis.get("ratios", []):
        label = r["label"]
        t = traj.get(_slug(r["label"]), {})
        vals = t.get("values", [])
        direction = t.get("trajectory", "")
        rows.append([label, _fmt(r["value"]) + (" " + r.get("unit", "")).strip(),
                     direction or "—"])
    blocks.append({"kind": "table", "headers": ["Ratio", "Latest", "Trajectory"],
                   "rows": rows})

    # --- 3. Covenants
    if analysis.get("covenants"):
        blocks.append({"kind": "h2", "text": "3. Covenant Compliance"})
        crow = [[c["name"], _fmt(c.get("actual")), c["threshold"], c["status"].upper()]
                for c in analysis["covenants"]]
        blocks.append({"kind": "table",
                       "headers": ["Covenant", "Actual", "Threshold", "Status"], "rows": crow})

    # --- 4. Stress
    if analysis.get("stress_scenarios"):
        blocks.append({"kind": "h2", "text": "4. Stress Testing"})
        srow = []
        for s in analysis["stress_scenarios"]:
            breach = ", ".join(s.get("breached_covenants", [])) or "none"
            srow.append([s["scenario"], f"{s['base_rating']} → {s['stressed_rating']}",
                         f"{s['rating_downgrade']} notch", breach])
        blocks.append({"kind": "table",
                       "headers": ["Scenario", "Rating migration", "Downgrade", "Breaches"], "rows": srow})

    # --- 5. Industry & macro research
    if research_markdown or research_report:
        blocks.append({"kind": "h2", "text": "5. Industry & Macro Research"})
        if research_report:
            rep = research_report
            blocks.append({"kind": "p", "text":
                f"Validation confidence {rep.get('overall_confidence', 0):.2f} across "
                f"{len(rep.get('sources', []))} sources. Sector: {rep.get('sector', 'n/a')}."})
            for f in rep.get("findings", [])[:10]:
                blocks.append({"kind": "bullets", "items": [f"{f.get('claim', '')} "
                                                           f"[{f.get('source_url', '')}]"]})
            if rep.get("conflicts"):
                blocks.append({"kind": "p", "text":
                    "Conflicts flagged for verification: " + ", ".join(rep["conflicts"]) + "."})
        elif research_markdown:
            blocks.append({"kind": "p", "text": research_markdown[:4000]})

    # --- 6. Standards compliance
    if standards_assessment:
        blocks.append({"kind": "h2", "text": "6. Industry Standard Compliance"})
        sa = standards_assessment
        blocks.append({"kind": "p", "text":
            f"Weighted compliance {sa.get('compliance_score', 0)*100:.0f}% "
            f"(coverage {sa.get('coverage', 0)*100:.0f}%). "
            + ("Meets industry standard." if sa.get("meets_standard") else
               "Breaches: " + ", ".join(sa.get("breaches", [])) + ".")})

    # --- 7. Assessment & answer to the question
    blocks.append({"kind": "h2", "text": "7. Assessment & Answer to the Engagement Question"})
    if purpose:
        blocks.append({"kind": "p", "text": f"Question: {purpose}"})
    if llm_assessment_markdown:
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
    else:
        blocks.append({"kind": "p", "text":
            f"On the available evidence the obligor carries a {band} risk rating with "
            f"covenant compliance and resilient stress performance. The recommendation is "
            f"{rec}. Detailed strengths, risks and conditions are itemised below."})
        cs = rating.get("category_scores", {})
        if cs:
            blocks.append({"kind": "bullets", "items":
                [f"{k.replace('_',' ').title()} score {v}/5" for k, v in cs.items()]})

    # --- 8. Recommendation
    blocks.append({"kind": "h2", "text": "8. Recommendation"})
    blocks.append({"kind": "p", "text": f"Recommendation: {rec}."})
    if analysis.get("scenario_definitions"):
        blocks.append({"kind": "bullets", "items":
            ["Monitor covenant headroom quarterly.",
             "Track liquidity and capex intensity against operating cash generation.",
             "Refresh industry research at each review cycle."]})

    # --- 9. Conclusion
    blocks.append({"kind": "h2", "text": "9. Conclusion"})
    blocks.append({"kind": "p", "text":
        f"{company_name} presents a {band}-rated credit profile. The recommendation is "
        f"{rec}, subject to the monitoring conditions above."})

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
