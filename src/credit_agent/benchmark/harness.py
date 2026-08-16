"""Benchmark harness.

Loads the Standard Chartered example-answer workbook, runs the agent's
deterministic engine over it, and compares the computed ratios against the
ratios disclosed in the workbook's `O. Report` sheet. This is the quantitative
acceptance test: the agent must reproduce the human/SC answer within tolerance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..ratios.calculator import compute_ratios
from ..spreading.loader import load_sc_benchmark, load_sc_workbook

TOLERANCE_REL = 0.02


@dataclass
class Comparison:
    key: str
    expected: float
    actual: float
    rel_diff: float
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "expected": round(self.expected, 6),
            "actual": round(self.actual, 6), "rel_diff": round(self.rel_diff, 5),
            "passed": self.passed,
        }


def run_benchmark(path: str) -> dict[str, list[Comparison]]:
    company = load_sc_workbook(path)
    benchmark = load_sc_benchmark(path)
    results: dict[str, list[Comparison]] = {}

    for i, period in enumerate(company.periods):
        prior = company.periods[i - 1] if i > 0 else None
        ratios = compute_ratios(period, prior)
        expected = benchmark[period.period]
        comps: list[Comparison] = []
        for key, exp_val in expected.items():
            act = ratios.get(key)
            act_val = act.value if act else None
            if act_val is None:
                comps.append(Comparison(key, exp_val, 0.0, 1.0, False))
                continue
            rel = abs(act_val - exp_val) / abs(exp_val) if exp_val != 0 else abs(act_val)
            comps.append(Comparison(key, exp_val, act_val, rel, rel <= TOLERANCE_REL))
        results[period.period] = comps
    return results


def summarize(path: str) -> dict[str, Any]:
    results = run_benchmark(path)
    total = 0
    passed = 0
    for period, comps in results.items():
        for c in comps:
            total += 1
            passed += 1 if c.passed else 0
    return {
        "path": path,
        "total": total,
        "passed": passed,
        "all_passed": total == passed,
        "details": {p: [c.to_dict() for c in comps] for p, comps in results.items()},
    }


if __name__ == "__main__":
    import json
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "data/raw/Task 1 Example Answer - Financial Reporting Tool.xlsx"
    print(json.dumps(summarize(target), indent=2))
