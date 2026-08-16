"""Industry-standard compliance scoring.

Compares the obligor's computed ratios against a stored benchmark (the editable
"Industry Standard" in the product UI). Produces a weighted pass/fail assessment
so "acceptable credit" is driven by a configurable policy rather than hard-coded
thresholds. Pure, deterministic, auditable.
"""

from __future__ import annotations

from typing import Any

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

_OPS = {
    ">=": lambda v, t: v >= t,
    ">": lambda v, t: v > t,
    "<=": lambda v, t: v <= t,
    "<": lambda v, t: v < t,
}


def evaluate_standards(
    ratios: dict[str, float | None],
    standards: dict | None = None,
) -> dict[str, Any]:
    standards = standards or DEFAULT_STANDARDS
    evaluated = []
    total_w = 0.0
    passed_w = 0.0
    breaches = []

    for th in standards.get("thresholds", []):
        key = th["key"]
        value = ratios.get(key)
        op = _OPS.get(th["operator"])
        if value is None or op is None:
            status = "no_data"
        elif op(value, th["value"]):
            status = "pass"
            passed_w += float(th.get("weight", 1.0))
        else:
            status = "fail"
            breaches.append(th["label"])
        total_w += float(th.get("weight", 1.0))
        evaluated.append({
            "key": key,
            "label": th["label"],
            "operator": th["operator"],
            "threshold": th["value"],
            "value": value,
            "weight": th.get("weight", 1.0),
            "status": status,
        })

    compliance = round(passed_w / total_w, 3) if total_w else 0.0
    coverage = round(sum(1 for e in evaluated if e["status"] != "no_data") / len(evaluated), 3) if evaluated else 0.0

    return {
        "name": standards.get("name", "Industry standard"),
        "evaluated": evaluated,
        "compliance_score": compliance,
        "coverage": coverage,
        "breaches": breaches,
        "meets_standard": compliance >= 0.8 and not breaches,
    }
