"""Tests for the branded credit report (builder + exporters)."""

from __future__ import annotations

from credit_agent.report.builder import assemble_report, BRANDING
from credit_agent.report.export import export_docx, export_html, export_pdf

ANALYSIS = {
    "entity_name": "Green Solutions Mfg",
    "currency": "USD (thousands)",
    "periods": ["FY2022", "FY2023"],
    "latest_period": "FY2023",
    "ratios": [
        {"label": "Current Ratio", "category": "liquidity", "value": 1.38, "unit": "x", "within_healthy_band": True},
        {"label": "EBITDA Margin", "category": "profitability", "value": 0.10, "unit": "%", "within_healthy_band": True},
    ],
    "risk_rating": {"band": "AAA", "composite_score": 4.5, "pd_estimate": 0.0005,
                    "category_scores": {"leverage": 5.0, "coverage": 5.0}},
    "ratio_trajectories": {
        "current_ratio": {"values": [1.88, 1.38], "trajectory": "deteriorating"},
    },
    "covenants": [{"name": "Max Leverage", "actual": 1.2, "threshold": "<= 4.0", "status": "pass"}],
    "stress_scenarios": [{"scenario": "Combined downturn", "base_rating": "AAA",
                          "stressed_rating": "AA", "rating_downgrade": 1,
                          "breached_covenants": []}],
}

FIGURES = {
    "currency": "USD (thousands)",
    "periods": ["FY2022", "FY2023"],
    "latest_period": "FY2023", "prior_period": "FY2022",
    "latest": {"revenue": 53823, "ebitda": 5523, "net_income": 5640, "total_assets": 62131,
               "total_debt": 6834, "total_equity": 31015, "cash": 6000, "ocf": 11446, "fcf": 3432},
    "prior": {"revenue": 31536},
}

STANDARDS = {"name": "Default", "compliance_score": 1.0, "coverage": 1.0,
             "breaches": [], "meets_standard": True,
             "evaluated": [{"label": "Current Ratio", "value": 1.38, "status": "pass"}]}


def test_assemble_cover_and_blocks():
    r = assemble_report("Lawrence Oladeji", "Green Solutions Mfg", "Is it creditworthy?",
                        ANALYSIS, figures=FIGURES, standards_assessment=STANDARDS)
    assert r["cover"]["analyst_name"] == "Lawrence Oladeji"
    assert r["cover"]["company_name"] == "Green Solutions Mfg"
    assert r["cover"]["purpose"] == "Is it creditworthy?"
    assert r["branding"]["email"] == BRANDING["email"]
    kinds = [b["kind"] for b in r["blocks"]]
    assert "table" in kinds and "h2" in kinds


def test_pdf_export_valid():
    r = assemble_report("Lawrence Oladeji", "Client", "Q?", ANALYSIS, figures=FIGURES)
    pdf = export_pdf(r)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 1000


def test_docx_export_valid():
    r = assemble_report("Lawrence Oladeji", "Client", "Q?", ANALYSIS, figures=FIGURES)
    docx = export_docx(r)
    assert docx[:2] == b"PK"
    assert len(docx) > 1000


def test_html_export_contains_branding():
    r = assemble_report("Lawrence Oladeji", "Client", "Q?", ANALYSIS, figures=FIGURES)
    html = export_html(r)
    assert "Credit Assessment Report" in html
    assert "Lawrence Oladeji" in html
    assert "oladeji.lawrence@gmail.com" in html
