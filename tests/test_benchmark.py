from pathlib import Path

from credit_agent.benchmark.harness import summarize

WORKBOOK = Path(__file__).resolve().parents[1] / "data" / "raw" / "Task 1 Example Answer - Financial Reporting Tool.xlsx"


def test_workbook_exists():
    assert WORKBOOK.exists(), "Place the SC example-answer workbook in data/raw/"


def test_benchmark_reproduces_sc_answer():
    result = summarize(str(WORKBOOK))
    assert result["all_passed"], f"Benchmark failed: {result['details']}"
    assert result["passed"] == result["total"]
