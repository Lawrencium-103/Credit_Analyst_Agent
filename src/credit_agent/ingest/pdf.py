"""Heuristic PDF financial-statement parser.

PDFs are not a structured format, so this is a *draft* extractor: it pulls the
most common line items via label/number heuristics and flags the whole period as
low-confidence so a human spreads it properly. It never invents precision it
cannot find.
"""

from __future__ import annotations

import re

import fitz

from ..schema.financials import BalanceSheet, CashFlow, IncomeStatement, PeriodFinancials

_NUMBER_RE = re.compile(
    r"\(?-?\$?\s*[\d,]+(?:\.\d+)?\)?|\(?-?\$?\s*\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?",
    re.IGNORECASE,
)

_LABEL_MAP = [
    ("revenue", ["total revenue", "net revenue", "revenue", "net sales", "sales"]),
    ("cogs", ["cost of sales", "cost of revenue", "cogs"]),
    ("gross_profit", ["gross profit", "gross margin"]),
    ("operating_expenses", ["operating expenses", "total operating expenses", "opex"]),
    ("ebitda", ["ebitda"]),
    ("depreciation_amortization", ["depreciation and amortization", "depreciation & amortization", "d&a"]),
    ("ebit", ["operating income", "income from operations", "ebit", "operating profit"]),
    ("interest_expense", ["interest expense"]),
    ("pretax_income", ["income before tax", "profit before tax", "pretax income"]),
    ("tax_expense", ["income tax expense", "tax expense"]),
    ("net_income", ["net income", "profit after tax", "net profit", "pat"]),
    ("cash_and_equivalents", ["cash and cash equivalents", "cash"]),
    ("accounts_receivable", ["accounts receivable", "trade receivables"]),
    ("inventory", ["inventory", "inventories"]),
    ("current_assets", ["total current assets", "current assets"]),
    ("total_assets", ["total assets"]),
    ("accounts_payable", ["accounts payable", "trade payables"]),
    ("current_liabilities", ["total current liabilities", "current liabilities"]),
    ("total_liabilities", ["total liabilities"]),
    ("total_debt", ["total debt", "total borrowings"]),
    ("total_equity", ["total equity", "shareholders equity", "stockholders equity"]),
    ("operating_cash_flow", ["net cash from operating activities", "cash flow from operations", "operating cash flow"]),
    ("capital_expenditures", ["capital expenditures", "purchase of property", "capex"]),
    ("free_cash_flow", ["free cash flow", "free cashflow"]),
]


def _clean_number(raw: str) -> float | None:
    if not raw:
        return None
    neg = raw.strip().startswith("(") or raw.strip().startswith("-")
    digits = re.sub(r"[^\d.]", "", raw)
    try:
        val = float(digits)
    except ValueError:
        return None
    if raw.strip().endswith(")") and not raw.strip().startswith("("):
        neg = True
    return -val if neg else val


def _first_number_after(text: str, pos: int) -> float | None:
    window = text[pos : pos + 240]
    for m in _NUMBER_RE.finditer(window):
        val = _clean_number(m.group(0))
        if val is not None:
            return val
    return None


def parse_pdf(path: str, year: str, entity: str | None = None) -> PeriodFinancials:
    doc = fitz.open(path)
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    text_lower = text.lower()

    found: dict[str, float | None] = {}
    for field, keywords in _LABEL_MAP:
        for kw in keywords:
            idx = text_lower.find(kw)
            if idx != -1:
                val = _first_number_after(text, idx + len(kw))
                if val is not None:
                    found[field] = val
                    break

    return PeriodFinancials(
        period=str(year),
        income_statement=IncomeStatement(**{k: v for k, v in found.items() if k in IncomeStatement.model_fields}),
        balance_sheet=BalanceSheet(**{k: v for k, v in found.items() if k in BalanceSheet.model_fields}),
        cash_flow=CashFlow(**{k: v for k, v in found.items() if k in CashFlow.model_fields}),
    )
