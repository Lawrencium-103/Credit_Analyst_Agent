"""FastAPI product layer (local dev + backward-compatible API).

This is the long-running server used for local development. In production the
same logic is served by Vercel's serverless Python functions (see ``api/``).
All behaviour lives in :mod:`credit_agent.api.logic` so the two stay in sync.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from ..api.logic import (
    DEFAULT_STANDARDS,
    assess_standards,
    build_report_file,
    build_report_response,
    dashboard_bundle,
    ingest_and_analyze,
    research_response,
    run_agent_response,
)
from ..agent.orchestrator import CreditAgent, render_assessment
from ..agent.tools import analysis_bundle
from ..report.cam import build_memo, render_markdown
from ..spreading.loader import load_sc_workbook

ROOT = Path(os.getcwd()).resolve()
PUBLIC = ROOT / "public"
_APP_HTML = Path(__file__).resolve().parent / "static" / "app.html"
_DASH_HTML = Path(__file__).resolve().parent / "static" / "dashboard.html"
# Serverless filesystems (e.g. Vercel) are read-only outside /tmp, so uploads
# always land in the temp dir — valid for both local dev and serverless.
UPLOAD_DIR = Path(tempfile.gettempdir()) / "credit_agent_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
STANDARDS_PATH = ROOT / "data" / "standards.json"

app = FastAPI(title="Credit Analyst Agent", version="0.3.1")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    for p in (_APP_HTML, PUBLIC / "app.html", PUBLIC / "index.html"):
        if p.exists():
            html = p.read_text(encoding="utf-8")
            return HTMLResponse(html, headers={"Cache-Control": "no-store"})
    return HTMLResponse("<h1>Not found</h1>", status_code=404)


@app.get("/marked.min.js")
def marked_js():
    return FileResponse(str(PUBLIC / "marked.min.js"), media_type="application/javascript")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page() -> str:
    if _DASH_HTML.exists():
        html = _DASH_HTML.read_text(encoding="utf-8")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})
    return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #
@app.post("/api/ingest")
async def ingest_endpoint(
    files: list[UploadFile] = File(...),
    meta: str = Form(...),
    standards: str | None = Form(None),
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
        std = json.loads(standards) if standards else None
        result = ingest_and_analyze(saved, std)
    except Exception as e:
        return JSONResponse(status_code=422, content={"error": str(e)})
    return result


class StandardsAssessReq(BaseModel):
    ratios: dict
    standards: dict | None = None


@app.post("/api/standards/assess")
def standards_assess(req: StandardsAssessReq):
    return assess_standards(req.ratios, req.standards)


@app.get("/api/standards")
def get_standards():
    if STANDARDS_PATH.exists():
        return json.loads(STANDARDS_PATH.read_text(encoding="utf-8"))
    return DEFAULT_STANDARDS


@app.post("/api/standards")
def post_standards(payload: dict):
    # Serverless filesystems are read-only; standards live client-side (localStorage).
    # Best-effort persistence for local dev only.
    try:
        STANDARDS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Branded report
# --------------------------------------------------------------------------- #
class ReportReq(BaseModel):
    analyst_name: str | None = None
    company_name: str = "Client"
    purpose: str | None = None
    workbook_path: str | None = None
    periods: list[dict] | None = None
    sector: str | None = None
    standards: dict | None = None
    run_agent: bool = False


@app.post("/api/report")
def build_report(req: ReportReq):
    body = req.model_dump()
    out = build_report_response(body)
    if "error" in out:
        return JSONResponse(status_code=400, content=out)
    return out


class DashboardReq(BaseModel):
    analyst_name: str | None = None
    company_name: str = "Client"
    purpose: str | None = None
    workbook_path: str | None = None
    periods: list[dict] | None = None
    sector: str | None = None
    company_background: str | None = None
    standards: dict | None = None
    run_research: bool = True


@app.post("/api/dashboard")
def dashboard_json(req: DashboardReq):
    out = dashboard_bundle(req.model_dump())
    if "error" in out:
        return JSONResponse(status_code=400, content=out)
    return out


@app.post("/api/report/download")
def download_report(req: ReportReq, format: str = "pdf"):
    body = req.model_dump()
    if format not in ("pdf", "docx"):
        return JSONResponse(status_code=400, content={"error": "format must be pdf or docx"})
    data = build_report_file(body, format)
    if data is None:
        return JSONResponse(status_code=400, content={"error": "failed to generate file"})
    media = "application/pdf" if format == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return StreamingResponse(
        iter([data]),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="credit_assessment.{format}"'},
    )


# --------------------------------------------------------------------------- #
# Live AI agent memo (synchronous)
# --------------------------------------------------------------------------- #
class AgentReq(BaseModel):
    path: str | None = None
    entity: str | None = None


@app.post("/api/agent")
def api_agent(req: AgentReq):
    out = run_agent_response(req.model_dump())
    if "error" in out:
        return JSONResponse(status_code=400, content=out)
    return out


@app.get("/api/agent/{task_id}")
def agent_status(task_id: str):
    return JSONResponse(status_code=404, content={"status": "not_found"})


# --------------------------------------------------------------------------- #
# Research
# --------------------------------------------------------------------------- #
class ResearchReq(BaseModel):
    sector: str | None = None
    entity: str | None = None
    user_notes: str | None = None
    macro_assumptions: str | None = None
    path: str | None = None


@app.post("/api/research")
def research_json(req: ResearchReq):
    return research_response(req.model_dump())


# --------------------------------------------------------------------------- #
# Legacy analyze endpoints (workbook path)
# --------------------------------------------------------------------------- #
class AnalyzePath(BaseModel):
    path: str
    run_agent: bool = True


@app.post("/api/analyze/path")
def analyze_path(req: AnalyzePath):
    if not Path(req.path).exists():
        return JSONResponse(status_code=400, content={"error": "file not found"})
    company = load_sc_workbook(req.path)
    memo = build_memo(company)
    bundle = analysis_bundle(req.path)
    out = {
        "entity_name": company.entity_name,
        "currency": company.currency,
        "rating": bundle["risk_rating"]["band"],
        "memo_markdown": render_markdown(memo),
        "ratios": bundle["ratios"],
        "covenants": bundle["covenants"],
        "assessment_markdown": None,
    }
    if req.run_agent:
        try:
            agent = CreditAgent()
            out["assessment_markdown"] = render_assessment(agent.analyze(req.path))
        except Exception as e:
            out["assessment_markdown"] = f"*Assessment unavailable: {e}*"
    return out


@app.post("/api/analyze/upload")
async def analyze_upload(file: UploadFile = File(...)):
    suffix = Path(file.filename or "client.xlsx").suffix or ".xlsx"
    dest = UPLOAD_DIR / f"{os.urandom(4).hex()}{suffix}"
    with dest.open("wb") as f:
        f.write(await file.read())
    return analyze_path(AnalyzePath(path=str(dest)))


def main() -> None:
    import uvicorn

    uvicorn.run("credit_agent.api.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
