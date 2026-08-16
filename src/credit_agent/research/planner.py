"""Research planning.

Generates the set of search queries a credit analyst needs: demand, input-cost
exposure, competitive position, macro, ESG/regulation and rates. Queries are
sector-templated so retrieval is specific (e.g. "stainless steel price trend"
for a drinkware manufacturer) rather than vague. This is the first guard against
mismatched information: precise queries in -> relevant sources out.
"""

from __future__ import annotations

from pydantic import BaseModel

DEFAULT_SECTOR = "sustainable drinkware / reusable beverage containers"


class ResearchQuery(BaseModel):
    dimension: str
    query: str
    rationale: str
    expected_evidence: str


_TEMPLATES: dict[str, tuple[str, str, str]] = {
    "demand": (
        "global {sector} market size growth forecast 2024 2025",
        "Assess volume/demand trajectory and growth expectations for the client's end market.",
        "Market size, CAGR, demand growth figures with a source and date.",
    ),
    "trends": (
        "sustainable drinkware consumer trends ESG reusable bottles 2024",
        "Understand structural tailwinds (sustainability, regulation of single-use plastics).",
        "Qualitative/quantitative evidence of shifting consumer and regulatory demand.",
    ),
    "input_costs": (
        "stainless steel aluminum commodity price trend 2024 beverage packaging",
        "Drinkware is input-cost exposed; monitor pass-through ability and margin risk.",
        "Recent price moves for key inputs (steel/aluminium) with timeframe.",
    ),
    "competitive": (
        "reusable drinkware competitive landscape leading manufacturers market share",
        "Evaluate the client's relative position versus established and low-cost producers.",
        "Competitor set, concentration, and any share-shift evidence.",
    ),
    "macro": (
        "consumer discretionary spending outlook 2024 2025",
        "Demand for drinkware is consumer-discretionary; macro sensitivity matters.",
        "Consumer confidence / spending outlook statements from reputable sources.",
    ),
    "regulation": (
        "single-use plastic ban regulation reusable drinkware policy 2024",
        "Regulation is a key credit catalyst for the sustainable-drinkware thesis.",
        "Specific regulations, geographies and effective dates.",
    ),
    "rates": (
        "central bank interest rate outlook 2024 2025",
        "Rate path drives the client's funding cost and debt-service capacity.",
        "Policy-rate expectations from a credible monetary authority or bank research.",
    ),
}


def build_plan(sector: str | None = None, dimensions: list[str] | None = None) -> list[ResearchQuery]:
    sector = sector or DEFAULT_SECTOR
    dims = dimensions or list(_TEMPLATES.keys())
    plan = []
    for dim in dims:
        tmpl = _TEMPLATES.get(dim)
        if not tmpl:
            continue
        q, rationale, evidence = tmpl
        plan.append(ResearchQuery(
            dimension=dim, query=q.format(sector=sector),
            rationale=rationale, expected_evidence=evidence,
        ))
    return plan
