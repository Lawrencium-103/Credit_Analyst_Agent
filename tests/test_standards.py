"""Tests for industry-standard compliance scoring."""

from __future__ import annotations

from credit_agent.analysis.standards import DEFAULT_STANDARDS, evaluate_standards


def test_all_pass():
    ratios = {
        "current_ratio": 1.5, "ebitda_net_interest_cover": 5.0, "leverage_metric": 2.0,
        "net_leverage": 1.0, "ebitda_margin": 0.15, "operating_margin": 0.12,
        "debt_to_equity": 0.5, "return_on_equity": 0.20,
    }
    a = evaluate_standards(ratios)
    assert a["compliance_score"] == 1.0
    assert a["meets_standard"] is True
    assert a["breaches"] == []


def test_breach_detected():
    ratios = {
        "current_ratio": 0.8, "ebitda_net_interest_cover": 5.0, "leverage_metric": 2.0,
        "net_leverage": 1.0, "ebitda_margin": 0.15, "operating_margin": 0.12,
        "debt_to_equity": 0.5, "return_on_equity": 0.20,
    }
    a = evaluate_standards(ratios)
    assert a["compliance_score"] < 1.0
    assert "Current Ratio" in a["breaches"]
    assert a["meets_standard"] is False


def test_missing_ratio_is_no_data_not_fail():
    ratios = {"current_ratio": 1.5}
    a = evaluate_standards(ratios)
    assert a["coverage"] < 1.0
    nodata = [e for e in a["evaluated"] if e["status"] == "no_data"]
    assert len(nodata) > 0


def test_custom_standards():
    custom = {"name": "Tight", "thresholds": [
        {"key": "ebitda_margin", "label": "EBITDA Margin", "operator": ">=", "value": 0.20, "weight": 1.0}]}
    a = evaluate_standards({"ebitda_margin": 0.05}, custom)
    assert a["breaches"] == ["EBITDA Margin"]
    # default still flags a sub-threshold margin
    assert evaluate_standards({"ebitda_margin": 0.05}, DEFAULT_STANDARDS)["breaches"]
