"""Tests for direct .md / .txt / .json ingestion (parallel to the PDF pipeline)."""
import json
import tempfile
from pathlib import Path

import pytest

from credit_agent.ingest.loader import ingest_file


def _write(name: str, text: str) -> str:
    p = Path(tempfile.gettempdir()) / name
    p.write_text(text, encoding="utf-8")
    return str(p)


MD = """## Income Statement

| Item | 2023 | 2024 |
| --- | --- | --- |
| Revenue | 1,000 | 1,200 |
| Cost of Sales | 600 | 700 |
| EBITDA | 250 | 300 |
| Net Income | 120 | 150 |

## Balance Sheet

| Item | 2023 | 2024 |
| --- | --- | --- |
| Total Assets | 5,000 | 5,500 |
| Total Equity | 2,000 | 2,200 |
| Total Debt | 1,500 | 1,600 |
"""


def test_markdown_multiyear():
    periods, flags, conf, meta = ingest_file(_write("t.md", MD), 2024, "MD Co")
    assert {p.period for p in periods} == {"2023", "2024"}
    by24 = next(p for p in periods if p.period == "2024")
    assert by24.income_statement.revenue == 1200.0
    assert by24.balance_sheet.total_assets == 5500.0
    # "Cost of Sales" must map to cogs, not revenue (longest-keyword match)
    assert by24.income_statement.cogs == 700.0


def test_json_periods():
    payload = {"periods": [{"period": "2024", "Revenue": 1200, "Total Assets": 5500, "Net Income": 150}]}
    periods, flags, conf, meta = ingest_file(_write("t.json", json.dumps(payload)), 2024, "JSON Co")
    assert len(periods) == 1
    assert periods[0].income_statement.revenue == 1200.0
    assert periods[0].balance_sheet.total_assets == 5500.0


def test_unsupported_type_rejected():
    with pytest.raises(ValueError):
        ingest_file(_write("t.csv", "a,b\n1,2"), 2024)


BANK_MD = """## Income Statement

| Item | 2023 | 2024 |
| --- | --- | --- |
| Interest Income | 800,000 | 950,000 |
| Net Interest Income | 500,000 | 600,000 |
| Operating Expenses | 200,000 | 220,000 |
| Net Income | 190,000 | 240,000 |

## Balance Sheet

| Item | 2023 | 2024 |
| --- | --- | --- |
| Loans and Advances to Customers | 4,000,000 | 4,800,000 |
| Customer Deposits | 5,000,000 | 5,900,000 |
| Total Assets | 7,000,000 | 8,200,000 |
| Total Equity | 900,000 | 1,100,000 |
| Non-Performing Loans | 120,000 | 150,000 |
"""


def test_bank_statement_detected():
    periods, flags, conf, meta = ingest_file(_write("bank.md", BANK_MD), 2024, "Bank Co")
    assert meta["is_bank"] is True
    by24 = next(p for p in periods if p.period == "2024")
    # "Interest Income" must map to revenue, not be missed
    assert by24.income_statement.revenue == 950000.0
    assert by24.balance_sheet.loans_and_advances == 4800000.0
    assert by24.balance_sheet.customer_deposits == 5900000.0
    assert by24.balance_sheet.non_performing_loans == 150000.0
    assert any("Bank" in f.message for f in flags)
