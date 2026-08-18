"""Research planning.

Generates the set of search queries a credit analyst needs: demand, input-cost
exposure, competitive position, macro, ESG/regulation and rates. Queries are
sector-templated via the ``{sector}`` token so retrieval stays specific to
whatever obligor is being assessed — the module is sector-agnostic and never
assumes a particular industry. Precise queries in -> relevant sources out.
"""

from __future__ import annotations

from pydantic import BaseModel

DEFAULT_SECTOR = "the client's industry"


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
        "{sector} industry trends consumer ESG regulatory tailwinds 2024",
        "Understand structural tailwinds (sustainability, regulation, shifting demand).",
        "Qualitative/quantitative evidence of shifting demand and regulatory context.",
    ),
    "input_costs": (
        "{sector} key input cost commodity price trend 2024 2025",
        "Monitor input-cost exposure and the client's ability to pass costs through to margin.",
        "Recent price moves for key inputs with timeframe.",
    ),
    "competitive": (
        "{sector} competitive landscape leading companies market share",
        "Evaluate the client's relative position versus established and low-cost producers.",
        "Competitor set, concentration, and any share-shift evidence.",
    ),
    "macro": (
        "{sector} end-market demand macro outlook 2024 2025",
        "End-market demand is macro-sensitive; assess the spending/cycle outlook.",
        "Consumer/business confidence and spending outlook from reputable sources.",
    ),
    "regulation": (
        "{sector} regulation policy 2024 2025",
        "Regulation can be a key credit catalyst or risk for the client's thesis.",
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
