"""Research dossier assembly.

Runs the full pipeline: plan sector-aware queries, retrieve via the configured
provider, validate/ground each result, and produce a cited dossier plus a
validation report. The dossier is what the credit agent reads for its industry
section — every sentence traceable to a source, with explicit confidence and
any gaps/conflicts surfaced.
"""

from __future__ import annotations

import datetime
from typing import Callable

from ..research.planner import build_plan
from ..research.search import SearchProvider, get_provider
from ..research.validate import (
    Finding,
    ValidationReport,
    build_validation_report,
    llm_judge,
    rule_judge,
    validate_dimension,
)
from pydantic import BaseModel


_DIMENSION_TOPIC = {
    "demand": "general", "trends": "general", "input_costs": "news",
    "competitive": "general", "macro": "news", "regulation": "news", "rates": "news",
}


class ResearchDossier(BaseModel):
    client_name: str
    sector: str
    findings: list[Finding] = []
    report: ValidationReport | None = None
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "client_name": self.client_name, "sector": self.sector,
            "findings": [f.model_dump() for f in self.findings],
            "report": self.report.model_dump() if self.report else None,
            "generated_at": self.generated_at,
        }


def run_research(
    client_name: str,
    sector: str | None = None,
    provider: SearchProvider | None = None,
    llm_complete: Callable[[list[dict]], str] | None = None,
    days: int = 540,
) -> ResearchDossier:
    sector = sector or "sustainable drinkware / reusable beverage containers"
    plan = build_plan(sector)
    provider = provider or get_provider("tavily")
    judge = (lambda c, u, d: llm_judge(c, u, d, llm_complete)) if llm_complete else rule_judge

    findings_by_dim: dict[str, list[Finding]] = {}
    for q in plan:
        results = provider.search(q.query, n=5, topic=_DIMENSION_TOPIC.get(q.dimension, "general"), days=days)
        found = validate_dimension(q.dimension, results, judge)
        findings_by_dim.setdefault(q.dimension, []).extend(found)

    flat = [f for fs in findings_by_dim.values() for f in fs]
    report = build_validation_report([q.dimension for q in plan], findings_by_dim)
    return ResearchDossier(
        client_name=client_name, sector=sector, findings=flat,
        report=report, generated_at=datetime.datetime.now().isoformat(timespec="seconds"),
    )


def render_dossier_md(d: ResearchDossier) -> str:
    lines = [f"# Industry & Macro Research — {d.client_name}", ""]
    lines.append(f"**Sector:** {d.sector}  ")
    if d.report:
        lines.append(f"**Validation:** {d.report.summary}  ")
        lines.append(f"**Overall confidence:** {d.report.overall_confidence}  ")
        if d.report.dimensions_gaps:
            lines.append(f"**Coverage gaps:** {', '.join(d.report.dimensions_gaps)}")
        if d.report.conflicts:
            lines.append(f"**Conflicts flagged:** {', '.join(d.report.conflicts)} (verify before relying)")
        lines.append("")
    by_dim: dict[str, list[Finding]] = {}
    for f in d.findings:
        by_dim.setdefault(f.dimension, []).append(f)
    for dim, fs in by_dim.items():
        lines.append(f"## {dim.replace('_', ' ').title()}")
        for f in fs:
            flag = " ⚠ conflict" if f.conflict else ""
            lines.append(f"- ({f.confidence}) {f.claim} — [{f.source_title or f.source_url}]({f.source_url}){flag}")
        lines.append("")
    if d.report and d.report.sources:
        lines.append("## Sources")
        for s in d.report.sources:
            lines.append(f"- {s}")
        lines.append("")
    return "\n".join(lines)
