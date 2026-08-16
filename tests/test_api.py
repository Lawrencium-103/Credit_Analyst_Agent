"""Smoke tests for the HTTP product layer."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from credit_agent.api.app import app


def test_index_has_all_views():
    c = TestClient(app)
    html = c.get("/").text
    for view in ("ingest", "extract", "research", "standards", "report", "memo"):
        assert f'data-view="{view}"' in html


def test_agent_requires_llm_key():
    # Ensure no LLM key is set for this assertion
    saved = {k: os.environ.pop(k, None) for k in ("GROQ_API_KEY", "NVIDIA_API_KEYS", "NVIDIA_API_KEY")}
    try:
        c = TestClient(app)
        r = c.post("/api/agent", json={"entity": "Client"})
        assert r.status_code == 400
        assert "LLM key" in r.json()["error"]
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_research_no_key_returns_note_not_blueprint():
    saved = os.environ.pop("TAVILY_API_KEY", None)
    try:
        c = TestClient(app)
        r = c.post("/api/research", json={"entity": "Client", "sector": "drinkware"})
        assert r.status_code == 200
        d = r.json()
        assert "planned_queries" not in d
        assert "note" in d
    finally:
        if saved is not None:
            os.environ["TAVILY_API_KEY"] = saved


def test_agent_status_not_found():
    c = TestClient(app)
    r = c.get("/api/agent/does-not-exist")
    assert r.status_code == 404


def test_report_endpoint_runs():
    c = TestClient(app)
    r = c.post("/api/report", json={"analyst_name": "Test", "company_name": "Client",
                                    "workbook_path": "data/raw/Task 1 Example Answer - Financial Reporting Tool.xlsx"})
    assert r.status_code == 200
    d = r.json()
    assert "cover" in d and "html" in d
    assert "Lawrence Oladeji" in d["html"] or "Credit Assessment" in d["html"]


def test_report_download_pdf():
    c = TestClient(app)
    r = c.post("/api/report/download?format=pdf", json={
        "analyst_name": "Test", "company_name": "Client",
        "workbook_path": "data/raw/Task 1 Example Answer - Financial Reporting Tool.xlsx",
    })
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"
