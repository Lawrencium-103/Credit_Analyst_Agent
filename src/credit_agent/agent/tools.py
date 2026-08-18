"""Analysis bundle: the verified, deterministic facts the LLM reasons over.

Every number here is computed by the auditable engine (never by the model), so
the agent can write narrative with confidence and cite these figures. This is
the boundary that keeps the agent accurate: LLM = judgement, code = arithmetic.
"""

from __future__ import annotations

import json

from ..analysis.covenants import evaluate_covenants
from ..analysis.stress import PRESET_SCENARIOS, run_stress
from ..analysis.trend import analyze_ratio_trends, analyze_trends
from ..ratios.calculator import compute_ratios
from ..risk.rating import rate
from ..spreading.loader import load_sc_workbook


def _round(v, n=4):
    return round(v, n) if isinstance(v, float) else v


def analysis_bundle(path: str) -> dict:
    return analysis_bundle_from_company(load_sc_workbook(path))


def extract_figures(company) -> dict:
    """Pull headline absolute figures (latest + prior) for narrative reporting."""
    latest, prior = company.latest(), company.prior()

    def g(p, stmt, field):
        return getattr(getattr(p, stmt), field) if p else None

    def snap(p):
        if not p:
            return {}
        return {
            "revenue": g(p, "income_statement", "revenue"),
            "ebitda": g(p, "income_statement", "ebitda"),
            "net_income": g(p, "income_statement", "net_income"),
            "total_assets": g(p, "balance_sheet", "total_assets"),
            "total_debt": g(p, "balance_sheet", "total_debt"),
            "total_equity": g(p, "balance_sheet", "total_equity"),
            "cash": g(p, "balance_sheet", "cash_and_equivalents"),
            "ocf": g(p, "cash_flow", "operating_cash_flow"),
            "fcf": g(p, "cash_flow", "free_cash_flow"),
        }

    return {
        "currency": company.currency,
        "periods": [p.period for p in company.periods],
        "latest_period": latest.period if latest else None,
        "prior_period": prior.period if prior else None,
        "latest": snap(latest),
        "prior": snap(prior),
    }


def analysis_bundle_from_company(company) -> dict:
    latest = company.latest()
    prior = company.prior()
    ratios = compute_ratios(latest, prior)
    rating = rate(ratios)
    covenants = evaluate_covenants(ratios)
    trends = analyze_trends(company)
    ratio_trends = analyze_ratio_trends(company)
    stress = run_stress(latest, prior)

    ratio_rows = []
    for r in ratios.results:
        if r.value is None:
            continue
        ratio_rows.append({
            "label": r.label, "key": r.key, "category": r.category, "value": _round(r.value),
            "unit": r.unit, "within_healthy_band": r.within_healthy_band,
        })

    kpi_rows = {}
    for key, t in trends.items():
        kpi_rows[key] = {
            "values": [_round(v) for v in t.values],
            "yoy_growth": [_round(g) if g is not None else None for g in t.yoy_growth],
            "cagr": _round(t.cagr) if t.cagr is not None else None,
        }

    ratio_trajectories = {
        k: {"trajectory": rt.trajectory, "values": [_round(v) for v in rt.values]}
        for k, rt in ratio_trends.items()
    }

    covenant_rows = [{
        "name": c.name, "description": c.description,
        "actual": _round(c.actual), "threshold": f"{c.operator} {c.threshold}",
        "status": c.status.value,
    } for c in covenants]

    stress_rows = [{
        "scenario": s.scenario, "description": s.description,
        "base_rating": s.base_rating, "stressed_rating": s.stressed_rating,
        "rating_downgrade": s.rating_downgrade,
        "base_pd": _round(s.base_pd, 5), "stressed_pd": _round(s.stressed_pd, 5),
        "breached_covenants": s.breached_covenants,
    } for s in stress]

    return {
        "entity_name": company.entity_name,
        "currency": company.currency,
        "periods": [p.period for p in company.periods],
        "latest_period": latest.period,
        "ratios": ratio_rows,
        "risk_rating": {
            "band": rating.band.value, "composite_score": rating.composite_score,
            "pd_estimate": rating.pd_estimate,
            "category_scores": {c.category: c.score for c in rating.category_scores},
        },
        "kpis": kpi_rows,
        "ratio_trajectories": ratio_trajectories,
        "covenants": covenant_rows,
        "stress_scenarios": stress_rows,
        "scenario_definitions": [
            {"name": s.name, "description": s.description} for s in PRESET_SCENARIOS
        ],
    }


def stress_bundle(path: str) -> dict:
    company = load_sc_workbook(path)
    stress = run_stress(company.latest(), company.prior())
    out = []
    for s in stress:
        out.append({
            "scenario": s.scenario, "description": s.description,
            "base_rating": s.base_rating, "stressed_rating": s.stressed_rating,
            "rating_downgrade": s.rating_downgrade,
            "base_pd": s.base_pd, "stressed_pd": s.stressed_pd,
            "key_ratios_base": {k: _round(v) for k, v in s.key_ratios_base.items()},
            "key_ratios_stressed": {k: _round(v) for k, v in s.key_ratios_stressed.items()},
            "breached_covenants": s.breached_covenants,
        })
    return {"stress_scenarios": out}


def industry_context(client_name: str, sector: str | None = None) -> dict:
    sector = sector or (client_name or "the subject industry")
    return {
        "client_name": client_name,
        "sector": sector,
        "note": (
            "Qualitative industry research is provided here. In production this tool "
            "queries live macro/industry sources (e.g. central-bank data, sector reports) "
            "and retrieves peer comps. The agent should treat the following as context to "
            "weigh in its assessment."
        ),
        "considerations": [
            "Demand cyclicality and exposure to the relevant macro/credit cycle.",
            "Input-cost, pricing-power and margin sensitivity to cost inflation.",
            "Capital-intensity and capex requirements relative to cash generation.",
            "Competitive landscape, market structure and concentration risk.",
        ],
    }


def bundle_to_json(path: str) -> str:
    return json.dumps(analysis_bundle(path), default=str)
