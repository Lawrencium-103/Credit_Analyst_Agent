"""Generic xlsx parser (non-Standard-Chartered statements).

Best-effort: scans every sheet for known labels and reads the first numeric
column. Output is flagged low-confidence for human review.
"""

from __future__ import annotations

import openpyxl

from ..schema.financials import BalanceSheet, CashFlow, IncomeStatement, PeriodFinancials

_KEYWORDS = [
    ("revenue", ["revenue", "net sales", "total revenue", "turnover"]),
    ("cogs", ["cost of sales", "cost of revenue", "cogs"]),
    ("gross_profit", ["gross profit"]),
    ("operating_expenses", ["operating expenses", "opex"]),
    ("ebitda", ["ebitda"]),
    ("depreciation_amortization", ["depreciation and amortization", "depreciation"]),
    ("ebit", ["operating income", "ebit", "income from operations"]),
    ("interest_expense", ["interest expense"]),
    ("pretax_income", ["profit before tax", "income before tax"]),
    ("tax_expense", ["tax expense", "income tax"]),
    ("net_income", ["net income", "profit after tax", "net profit"]),
    ("cash_and_equivalents", ["cash and cash equivalents", "cash"]),
    ("accounts_receivable", ["accounts receivable"]),
    ("inventory", ["inventory", "inventories"]),
    ("current_assets", ["current assets"]),
    ("total_assets", ["total assets"]),
    ("accounts_payable", ["accounts payable"]),
    ("current_liabilities", ["current liabilities"]),
    ("total_liabilities", ["total liabilities"]),
    ("total_debt", ["total debt", "total borrowings"]),
    ("total_equity", ["total equity", "shareholders equity"]),
    ("operating_cash_flow", ["cash flow from operating", "net cash from operating", "operating cash flow"]),
    ("capital_expenditures", ["capital expenditure", "capex", "purchase of property"]),
    ("free_cash_flow", ["free cash flow"]),
]


def _to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_generic_xlsx(path: str, year: str, entity: str | None = None) -> PeriodFinancials:
    wb = openpyxl.load_workbook(path, data_only=True)
    found: dict[str, float | None] = {}

    for ws in wb.worksheets:
        for row in range(1, ws.max_row + 1):
            label = ws.cell(row=row, column=1).value
            if not label:
                continue
            label_l = str(label).lower()
            for field, kws in _KEYWORDS:
                if field in found and found[field] is not None:
                    continue
                for kw in kws:
                    if kw in label_l:
                        val = _to_float(ws.cell(row=row, column=2).value)
                        if val is None:
                            val = _to_float(ws.cell(row=row, column=3).value)
                        if val is not None:
                            found[field] = val
                        break

    return PeriodFinancials(
        period=str(year),
        income_statement=IncomeStatement(**{k: v for k, v in found.items() if k in IncomeStatement.model_fields}),
        balance_sheet=BalanceSheet(**{k: v for k, v in found.items() if k in BalanceSheet.model_fields}),
        cash_flow=CashFlow(**{k: v for k, v in found.items() if k in CashFlow.model_fields}),
    )
