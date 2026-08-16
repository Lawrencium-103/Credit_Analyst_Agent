from credit_agent.analysis.stress import PRESET_SCENARIOS, apply_stress, run_stress
from credit_agent.spreading.loader import load_sc_workbook

WORKBOOK = "data/raw/Task 1 Example Answer - Financial Reporting Tool.xlsx"


def test_apply_stress_reducers_earnings():
    company = load_sc_workbook(str(WORKBOOK))
    base = company.latest()
    stress = apply_stress(base, PRESET_SCENARIOS[0])
    assert stress.income_statement.revenue < base.income_statement.revenue
    assert stress.income_statement.ebitda is not None
    assert stress.income_statement.ebitda < base.income_statement.ebitda


def test_run_stress_returns_scenarios():
    company = load_sc_workbook(str(WORKBOOK))
    results = run_stress(company.latest(), company.prior())
    assert len(results) == len(PRESET_SCENARIOS)
    severe = results[-1]
    assert severe.stressed_rating != severe.base_rating or severe.rating_downgrade >= 0


def test_severe_scenario_downgrades():
    company = load_sc_workbook(str(WORKBOOK))
    results = run_stress(company.latest(), company.prior())
    assert results[-1].rating_downgrade >= 1
