"""FastAPI product layer.

Exposes the full credit-agent pipeline over HTTP so the tool is usable as a
product rather than a library. The app is organised as a multi-page experience:
  - /api/ingest          multi-file (xlsx/pdf), multi-year spreading
  - /api/analyze/*       deterministic CAM, ratios, stress, covenants
  - /api/research*       sourced industry & macro research (+ analyst notes)
  - /api/standards       editable industry-standard benchmark store

The deterministic engine always runs; the LLM assessment and research are
optional and degrade gracefully when no API key is configured.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agent.orchestrator import CreditAgent, render_assessment
from ..agent.tools import analysis_bundle, stress_bundle
from ..report.cam import build_memo, render_markdown
from ..research.dossier import render_dossier_md, run_research
from ..research.planner import build_plan
from ..research.search import get_provider
from ..spreading.loader import load_sc_workbook
from ..ingest.loader import ingest, build_matrix
from ..ratios.calculator import compute_ratios
from ..schema.financials import CompanyFinancials, PeriodFinancials
from ..analysis.standards import DEFAULT_STANDARDS, evaluate_standards
from ..agent.tools import analysis_bundle_from_company, extract_figures
from ..agent.orchestrator import CreditAgent, render_assessment
from ..report.builder import assemble_report
from ..report.export import export_docx, export_html, export_pdf
from ..research.dossier import render_dossier_md, run_research
from ..research.search import get_provider

HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[3]
UPLOAD_DIR = ROOT / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
STANDARDS_PATH = ROOT / "data" / "standards.json"

app = FastAPI(title="Credit Analyst Agent", version="0.2.0")

app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")


def _llm_available() -> bool:
    return bool(
        os.environ.get("GROQ_API_KEY")
        or os.environ.get("NVIDIA_API_KEYS")
        or os.environ.get("NVIDIA_API_KEY")
    )


def _load_standards() -> dict:
    if STANDARDS_PATH.exists():
        try:
            return json.loads(STANDARDS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return DEFAULT_STANDARDS
    return DEFAULT_STANDARDS


def _ratios_map_from_periods(periods: list[dict]) -> dict[str, float | None]:
    """Compute latest-period ratios from ingested PeriodFinancials dicts."""
    if not periods:
        return {}
    objs = [PeriodFinancials(**p) for p in periods]
    prior = objs[-2] if len(objs) >= 2 else objs[-1]
    out = compute_ratios(objs[-1], prior)
    return {r.key: r.value for r in out.results}


# --------------------------------------------------------------------------- #
# Deterministic analysis endpoints
# --------------------------------------------------------------------------- #
class AnalyzePath(BaseModel):
    path: str
    run_agent: bool = True


def _result_for(path: str, run_agent: bool) -> dict:
    company = load_sc_workbook(path)
    memo = build_memo(company)
    bundle = analysis_bundle(path)
    stress = stress_bundle(path)
    out = {
        "entity_name": company.entity_name,
        "currency": company.currency,
        "rating": bundle["risk_rating"]["band"],
        "memo_markdown": render_markdown(memo),
        "ratios": bundle["ratios"],
        "stress": stress["stress_scenarios"],
        "covenants": bundle["covenants"],
        "assessment_markdown": None,
    }
    if run_agent and _llm_available():
        try:
            agent = CreditAgent()
            agent_out = agent.analyze(path)
            out["assessment_markdown"] = render_assessment(agent_out)
        except Exception as e:  # Never let the LLM step break the core deliverable
            out["assessment_markdown"] = f"*Assessment unavailable: {e}*"
    return out


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTMLResponse(
        (HERE / "index.html").read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/analyze/path")
def analyze_path(req: AnalyzePath):
    if not Path(req.path).exists():
        return JSONResponse(status_code=400, content={"error": "file not found"})
    return _result_for(req.path, req.run_agent)


@app.post("/api/analyze/upload")
def analyze_upload(file: UploadFile = File(...), run_agent: bool = True):
    suffix = Path(file.filename or "client.xlsx").suffix or ".xlsx"
    dest = UPLOAD_DIR / f"{os.urandom(4).hex()}{suffix}"
    with dest.open("wb") as f:
        f.write(file.file.read())
    return _result_for(str(dest), run_agent)


# --------------------------------------------------------------------------- #
# Ingestion endpoint (multi-file, multi-type, multi-year)
# --------------------------------------------------------------------------- #
@app.post("/api/ingest")
async def ingest_endpoint(
    files: list[UploadFile] = File(...),
    meta: str = Form(...),
):
    try:
        meta_list = json.loads(meta)
    except Exception:
        return JSONResponse(status_code=400, content={"error": "meta must be JSON array"})

    saved = []
    for i, f in enumerate(files):
        suffix = Path(f.filename or f"file{i}.bin").suffix or ".bin"
        dest = UPLOAD_DIR / f"{os.urandom(6).hex()}{suffix}"
        with dest.open("wb") as fh:
            fh.write(await f.read())
        saved.append({"path": str(dest), "year": int(meta_list[i]["year"]),
                      "entity": meta_list[i].get("entity")})

    try:
        result = ingest(saved)
    except Exception as e:
        return JSONResponse(status_code=422, content={"error": str(e)})

    ratios_map = _ratios_map_from_periods([p.model_dump() for p in result.periods])
    assessment = evaluate_standards(ratios_map, _load_standards())

    return {
        "entity_name": result.entity_name,
        "currency": result.currency,
        "periods": [p.model_dump() for p in result.periods],
        "matrix": build_matrix(result),
        "flags": [f.model_dump() for f in result.flags],
        "standards_assessment": assessment,
    }


class StandardsAssessReq(BaseModel):
    ratios: dict[str, float | None]
    standards: dict | None = None


@app.post("/api/standards/assess")
def standards_assess(req: StandardsAssessReq):
    return evaluate_standards(req.ratios, req.standards or _load_standards())


# --------------------------------------------------------------------------- #
# Branded report endpoint
# --------------------------------------------------------------------------- #
class ReportReq(BaseModel):
    analyst_name: str | None = None
    company_name: str = "Client"
    purpose: str | None = None
    workbook_path: str | None = None
    periods: list[dict] | None = None
    sector: str | None = None
    run_agent: bool = False


def _company_from_req(req: ReportReq):
    if req.workbook_path and Path(req.workbook_path).exists():
        return load_sc_workbook(req.workbook_path)
    if req.periods:
        objs = [PeriodFinancials(**p) for p in req.periods]
        return CompanyFinancials(entity_name=req.company_name, currency="USD (thousands)", periods=objs)
    raise ValueError("Provide workbook_path or periods.")


@app.post("/api/report")
def build_report(req: ReportReq):
    try:
        company = _company_from_req(req)
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    analysis = analysis_bundle_from_company(company)
    figures = extract_figures(company)
    ratios_map = {r.key: r.value for r in compute_ratios(company.latest(), company.prior()).results}
    standards = evaluate_standards(ratios_map, _load_standards())

    research_md = None
    research_report = None
    try:
        provider = get_provider("tavily")
        dossier = run_research(req.company_name, req.sector, provider=provider, llm_complete=None)
        research_md = render_dossier_md(dossier)
        research_report = dossier.report.model_dump()
    except RuntimeError:
        pass

    llm_md = None
    if req.run_agent and req.workbook_path and Path(req.workbook_path).exists():
        try:
            agent = CreditAgent()
            llm_md = render_assessment(agent.analyze(req.workbook_path))
        except Exception:
            llm_md = None

    report = assemble_report(
        analyst_name=req.analyst_name,
        company_name=req.company_name,
        purpose=req.purpose,
        analysis=analysis,
        figures=figures,
        research_markdown=research_md,
        research_report=research_report,
        standards_assessment=standards,
        llm_assessment_markdown=llm_md,
    )
    import base64
    return {
        "cover": report["cover"],
        "html": export_html(report),
        "pdf_base64": base64.b64encode(export_pdf(report)).decode("ascii"),
        "docx_base64": base64.b64encode(export_docx(report)).decode("ascii"),
    }


# --------------------------------------------------------------------------- #
# Live AI agent memo endpoint
# --------------------------------------------------------------------------- #
class AgentReq(BaseModel):
    path: str | None = None
    entity: str | None = None


_AGENT_TASKS: dict[str, dict] = {}


def _run_agent_task(task_id: str, path: str, entity: str | None) -> None:
    try:
        agent = CreditAgent()
        out = agent.analyze(path)
        a = out.get("assessment", {})
        md = render_assessment(out)
        import re

        urls = re.findall(r"https?://[^\s)\]\"'<>]+", md)
        seen = set()
        sources = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                sources.append(u)
        _AGENT_TASKS[task_id] = {
            "status": "done",
            "result": {
                "markdown": md,
                "recommendation": a.get("recommendation"),
                "entity": entity or "Client",
                "sources": sources[:12],
            },
        }
    except Exception as e:  # Never let the LLM step crash the API
        _AGENT_TASKS[task_id] = {"status": "error", "error": str(e)}


@app.post("/api/agent")
def api_agent(req: AgentReq):
    if not _llm_available():
        return JSONResponse(
            status_code=400,
            content={"error": "No LLM key configured (set GROQ_API_KEY or NVIDIA_API_KEYS)."},
        )
    path = req.path or str(ROOT / "data" / "raw" / "Task 1 Example Answer - Financial Reporting Tool.xlsx")
    if not Path(path).exists():
        return JSONResponse(status_code=400, content={"error": "workbook not found"})
    task_id = uuid.uuid4().hex
    _AGENT_TASKS[task_id] = {"status": "running"}
    threading.Thread(target=_run_agent_task, args=(task_id, path, req.entity), daemon=True).start()
    return {"task_id": task_id, "status": "running"}


@app.get("/api/agent/{task_id}")
def agent_status(task_id: str):
    task = _AGENT_TASKS.get(task_id)
    if task is None:
        return JSONResponse(status_code=404, content={"status": "not_found"})
    return task


# --------------------------------------------------------------------------- #
# Research endpoints (notes-aware)
# --------------------------------------------------------------------------- #
class ResearchReq(BaseModel):
    sector: str | None = None
    entity: str | None = None
    user_notes: str | None = None
    macro_assumptions: str | None = None
    path: str | None = None


@app.post("/api/research")
def research_json(req: ResearchReq):
    sector = req.sector
    if not sector and req.path and Path(req.path).exists():
        try:
            sector = load_sc_workbook(req.path).entity_name
        except Exception:
            sector = None
    sector = sector or "sustainable drinkware / reusable beverage containers"
    try:
        provider = get_provider("tavily")
        dossier = run_research(req.entity or "Client", sector, provider=provider, llm_complete=None)
        md = render_dossier_md(dossier)
    except RuntimeError:
        return {
            "client_name": req.entity,
            "sector": sector,
            "dossier_markdown": "",
            "report": None,
            "note": "TAVILY_API_KEY not configured — live sourced research is disabled.",
        }

    notes_md = ""
    if req.user_notes:
        notes_md += f"\n## Analyst-provided context\n{req.user_notes}\n"
    if req.macro_assumptions:
        notes_md += f"\n## Macro assumptions supplied\n{req.macro_assumptions}\n"

    return {
        "client_name": req.entity,
        "sector": sector,
        "dossier_markdown": md + notes_md,
        "report": dossier.report.model_dump(),
        "user_notes_included": bool(req.user_notes or req.macro_assumptions),
    }


@app.post("/api/research/path")
def research_path(req: ResearchReq):
    if not req.path or not Path(req.path).exists():
        return JSONResponse(status_code=400, content={"error": "file not found"})
    return research_json(req)


# --------------------------------------------------------------------------- #
# Industry-standard benchmark store
# --------------------------------------------------------------------------- #
DEFAULT_STANDARDS = {
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


@app.get("/api/standards")
def get_standards():
    if STANDARDS_PATH.exists():
        return json.loads(STANDARDS_PATH.read_text(encoding="utf-8"))
    return DEFAULT_STANDARDS


@app.post("/api/standards")
def post_standards(payload: dict):
    STANDARDS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"ok": True}


def main() -> None:
    import uvicorn

    uvicorn.run("credit_agent.api.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
