"""Framework-agnostic core for the Credit Analyst HTTP product layer.

This module holds the request/response *logic* for every endpoint so it can be
reused by both the local FastAPI app (``app.py``) and Vercel's serverless
Python functions without duplicating behaviour. It knows nothing about ASGI,
Starlette, or the Vercel runtime — only plain Python, the project library, and
dicts/objects.

Serverless constraints handled here:
- No persistent disk: standards are accepted in the request body (the SPA
  keeps them in localStorage and forwards them), defaulting to DEFAULT_STANDARDS.
- The live agent runs *synchronously* (no background thread), because serverless
  functions cannot keep a thread alive between invocations.
"""

from __future__ import annotations

import base64
import os
import re
import tempfile
import uuid
from pathlib import Path

from ..agent.orchestrator import CreditAgent, render_assessment
from ..agent.tools import (
    analysis_bundle,
    analysis_bundle_from_company,
    extract_figures,
    stress_bundle,
)
from ..analysis.standards import evaluate_standards
from ..ingest.loader import ingest, build_matrix
from ..ratios.calculator import compute_ratios
from ..report.builder import assemble_report
from ..report.cam import build_memo, render_markdown
from ..report.export import export_docx, export_html, export_pdf
from ..research.dossier import render_dossier_md, run_research
from ..research.search import get_provider
from ..schema.financials import CompanyFinancials, PeriodFinancials
from ..spreading.loader import load_sc_workbook

# Repo-root resolvers that work both locally (cwd = project root when running
# uvicorn) and on Vercel (cwd = project root at function runtime).
ROOT = Path(os.getcwd()).resolve()


def _example_workbook() -> Path:
    return ROOT / "data" / "raw" / "Task 1 Example Answer - Financial Reporting Tool.xlsx"


DEFAULT_STANDARDS: dict = {
    "name": "Default industry standard",
    "thresholds": [
        {"key": "current_ratio", "label": "Current Ratio", "operator": ">=", "value": 1.2, "weight": 1.0},
        {"key": "ebitda_net_interest_cover", "label": "EBITDA Interest Cover", "operator": ">=", "value": 3.0, "weight": 1.0},
        {"key": "leverage_metric", "label": "Leverage (Debt/EBITDA)", "operator": "<=", "value": 4.0, "weight": 1.0},
        {"key": "net_leverage", "label": "Net Leverage", "operator": "<=", "value": 3.0, "weight": 1.0},
        {"key": "ebitda_margin", "label": "EBITDA Margin", "operator": ">=", "value": 0.10, "weight": 1.0},
        {"key": "operating_margin", "label": "Operating Margin", "operator": ">=", "value": 0.08, "weight": 1.0},
        {"key": "debt_to_equity", "label": "Debt / Equity", "operator": "<=", "value": 1.0, "weight": 1.0},
        {"key": "return_on_equity", "label": "Return on Equity", "operator": ">=", "value": 0.12, "weight": 1.0},
    ],
}


def llm_available() -> bool:
    return bool(
        os.environ.get("GROQ_API_KEY")
        or os.environ.get("NVIDIA_API_KEYS")
        or os.environ.get("NVIDIA_API_KEY")
    )


def ratios_map_from_periods(periods: list[dict]) -> dict[str, float | None]:
    if not periods:
        return {}
    objs = [PeriodFinancials(**p) for p in periods]
    prior = objs[-2] if len(objs) >= 2 else objs[-1]
    out = compute_ratios(objs[-1], prior)
    return {r.key: r.value for r in out.results}


def ingest_and_analyze(saved: list[dict], standards: dict | None = None) -> dict:
    """``saved`` is a list of {"path", "year", "entity"} dicts (temp files)."""
    result = ingest(saved)
    ratios_map = ratios_map_from_periods([p.model_dump() for p in result.periods])
    assessment = evaluate_standards(ratios_map, standards or DEFAULT_STANDARDS)
    return {
        "entity_name": result.entity_name,
        "currency": result.currency,
        "periods": [p.model_dump() for p in result.periods],
        "matrix": build_matrix(result),
        "flags": [f.model_dump() for f in result.flags],
        "standards_assessment": assessment,
    }


def assess_standards(ratios: dict, standards: dict | None = None) -> dict:
    return evaluate_standards(ratios, standards or DEFAULT_STANDARDS)


def _company_from_req(body: dict) -> CompanyFinancials:
    periods = body.get("periods")
    if periods:
        objs = [PeriodFinancials(**p) for p in periods]
        return CompanyFinancials(
            entity_name=body.get("company_name", "Client"),
            currency="USD (thousands)",
            periods=objs,
        )
    path = body.get("workbook_path")
    if path and Path(path).exists():
        return load_sc_workbook(path)
    # Fall back to the bundled example workbook (deployed with the repo).
    ex = _example_workbook()
    if ex.exists():
        return load_sc_workbook(str(ex))
    raise ValueError("Provide periods or a valid workbook_path.")


def _assemble_report(body: dict) -> dict | tuple:
    """Build the report dict from a request body. Returns dict or {"error": ...}."""
    try:
        company = _company_from_req(body)
    except Exception as e:
        return {"error": str(e)}

    analysis = analysis_bundle_from_company(company)
    figures = extract_figures(company)
    ratios_map = {r.key: r.value for r in compute_ratios(company.latest(), company.prior()).results}
    standards = assess_standards(ratios_map, body.get("standards"))

    research_md = None
    research_report = None
    try:
        provider = get_provider("tavily")
        dossier = run_research(
            body.get("company_name", "Client"),
            body.get("sector"),
            provider=provider,
            llm_complete=None,
        )
        research_md = render_dossier_md(dossier)
        research_report = dossier.report.model_dump()
    except RuntimeError:
        pass

    llm_md = None
    if body.get("run_agent"):
        try:
            path = body.get("workbook_path") or str(_example_workbook())
            if Path(path).exists():
                agent = CreditAgent()
                llm_md = render_assessment(agent.analyze(path))
        except Exception:
            llm_md = None

    return assemble_report(
        analyst_name=body.get("analyst_name"),
        company_name=body.get("company_name", "Client"),
        purpose=body.get("purpose"),
        analysis=analysis,
        figures=figures,
        research_markdown=research_md,
        research_report=research_report,
        standards_assessment=standards,
        llm_assessment_markdown=llm_md,
    )


def build_report_response(body: dict) -> dict:
    """Return HTML preview + cover only (small payload for Vercel's 4.5 MB limit)."""
    report = _assemble_report(body)
    if isinstance(report, dict) and "error" in report:
        return report
    return {
        "cover": report["cover"],
        "html": export_html(report),
    }


def build_report_file(body: dict, fmt: str) -> bytes | None:
    """Return raw PDF or DOCX bytes for a separate download endpoint."""
    report = _assemble_report(body)
    if isinstance(report, dict) and "error" in report:
        return None
    if fmt == "pdf":
        return export_pdf(report)
    if fmt == "docx":
        return export_docx(report)
    return None


def run_agent_response(body: dict) -> dict:
    """Synchronous live-agent run. Returns the final memo payload directly."""
    if not llm_available():
        return {"error": "No LLM key configured (set GROQ_API_KEY or NVIDIA_API_KEYS)."}
    path = body.get("path")
    if not path or not Path(path).exists():
        ex = _example_workbook()
        if not ex.exists():
            return {"error": "workbook not found"}
        path = str(ex)
    entity = body.get("entity") or "Client"
    try:
        agent = CreditAgent()
        out = agent.analyze(path)
        md = render_assessment(out)
        urls = re.findall(r"https?://[^\s)\]\"'<>]+", md)
        seen, sources = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u)
                sources.append(u)
        return {
            "status": "done",
            "result": {
                "markdown": md,
                "recommendation": out.get("assessment", {}).get("recommendation"),
                "entity": entity,
                "sources": sources[:12],
            },
        }
    except Exception as e:  # Never let the LLM step crash the API
        return {"status": "error", "error": str(e)}


def research_response(body: dict) -> dict:
    sector = body.get("sector")
    path = body.get("path")
    if not sector and path and Path(path).exists():
        try:
            sector = load_sc_workbook(path).entity_name
        except Exception:
            sector = None
    sector = sector or "sustainable drinkware / reusable beverage containers"
    try:
        provider = get_provider("tavily")
        dossier = run_research(
            body.get("entity") or "Client", sector, provider=provider, llm_complete=None
        )
        md = render_dossier_md(dossier)
    except RuntimeError:
        return {
            "client_name": body.get("entity"),
            "sector": sector,
            "dossier_markdown": "",
            "report": None,
            "note": "TAVILY_API_KEY not configured — live sourced research is disabled.",
        }

    notes_md = ""
    if body.get("user_notes"):
        notes_md += f"\n## Analyst-provided context\n{body['user_notes']}\n"
    if body.get("macro_assumptions"):
        notes_md += f"\n## Macro assumptions supplied\n{body['macro_assumptions']}\n"

    return {
        "client_name": body.get("entity"),
        "sector": sector,
        "dossier_markdown": md + notes_md,
        "report": dossier.report.model_dump(),
        "user_notes_included": bool(body.get("user_notes") or body.get("macro_assumptions")),
    }
