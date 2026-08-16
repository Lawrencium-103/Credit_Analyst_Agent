import os

os.environ.pop("TAVILY_API_KEY", None)
os.environ.pop("GROQ_API_KEY", None)

from credit_agent.research.search import MockProvider, SearchResult
from credit_agent.research.validate import (
    build_validation_report, classify_source, rule_judge, validate_dimension,
)
from credit_agent.research.dossier import render_dossier_md, run_research
from credit_agent.research.planner import build_plan

SAMPLE = [
    SearchResult(
        query="global sustainable drinkware market size growth forecast 2024 2025",
        title="Reusable Drinkware Market Report", url="https://mordorintelligence.com/report",
        content="The global reusable drinkware market reached USD 9.2 billion in 2023 and is "
                "forecast to grow at a CAGR of 4.8% through 2029, driven by consumer demand.",
        provider="mock",
    ),
    SearchResult(
        query="central bank interest rate outlook 2024 2025",
        title="Fed Policy Outlook", url="https://federalreserve.gov/outlook",
        content="The Federal Reserve signaled rates would remain higher for longer through 2025.",
        provider="mock",
    ),
]


def test_classify_source_tiers():
    assert classify_source("https://federalreserve.gov/x") == "high"
    assert classify_source("https://mordorintelligence.com/r") == "medium"
    assert classify_source("https://randomblog.example/x") == "low"


def test_rule_judge_relevance():
    r = SAMPLE[0]
    j = rule_judge(r.content, r.url, "demand")
    assert j.relevant is True
    assert j.confidence > 0.5


def test_run_research_with_mock_and_rule_judge():
    provider = MockProvider(SAMPLE)
    dossier = run_research("Green Solutions", "sustainable drinkware", provider=provider, llm_complete=None)
    assert dossier.findings
    assert dossier.report is not None
    assert "demand" in dossier.report.dimensions_covered or dossier.findings
    md = render_dossier_md(dossier)
    assert "Industry & Macro Research" in md
    assert "mordorintelligence.com" in md


def test_validation_report_gaps_and_sources():
    plan = build_plan("sustainable drinkware")
    dims = [q.dimension for q in plan]
    findings_by_dim = {
        "demand": validate_dimension("demand", SAMPLE[:1], rule_judge),
    }
    report = build_validation_report(dims, findings_by_dim)
    assert "demand" in report.dimensions_covered
    assert report.dimensions_gaps
    assert any("mordor" in s for s in report.sources)


def test_research_tool_without_key_returns_plan():
    from types import SimpleNamespace
    from credit_agent.agent.orchestrator import CreditAgent
    agent = CreditAgent(client=SimpleNamespace())
    out = agent._research("Green Solutions", None)
    assert out["status"] == "live_research_unavailable"
    assert out["planned_queries"]
