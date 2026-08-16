from pathlib import Path

from credit_agent.analysis.covenants import evaluate_covenants
from credit_agent.analysis.trend import analyze_ratio_trends, analyze_trends
from credit_agent.report.cam import build_memo, render_markdown
from credit_agent.spreading.loader import load_sc_workbook

WORKBOOK = Path(__file__).resolve().parents[1] / "data" / "raw" / "Task 1 Example Answer - Financial Reporting Tool.xlsx"


def test_trends_computed():
    company = load_sc_workbook(str(WORKBOOK))
    trends = analyze_trends(company)
    assert "revenue" in trends
    rev = trends["revenue"]
    assert rev.yoy_growth[-1] is not None
    assert rev.cagr is not None


def test_ratio_trends_have_trajectory():
    company = load_sc_workbook(str(WORKBOOK))
    rt = analyze_ratio_trends(company)
    assert rt["current_ratio"].trajectory in {"improving", "deteriorating", "stable"}


def test_covenants_evaluate():
    company = load_sc_workbook(str(WORKBOOK))
    from credit_agent.ratios.calculator import compute_ratios
    ratios = compute_ratios(company.latest(), company.prior())
    results = evaluate_covenants(ratios)
    assert results
    assert all(r.status.value in {"PASS", "FAIL", "N/A"} for r in results)


def test_cam_builds_and_renders():
    company = load_sc_workbook(str(WORKBOOK))
    memo = build_memo(company)
    md = render_markdown(memo)
    assert memo.entity_name == "Green Solutions Manufacturing Ltd"
    assert memo.rating_band
    assert "## Recommendation" in md
    assert memo.covenants
