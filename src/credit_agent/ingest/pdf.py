"""PDF financial-statement parser.

Uses a two-stage approach:
  1. PDF → Markdown → table extraction (structured, high-confidence)
  2. Fallback: keyword/number heuristics on raw text (low-confidence)

The Markdown stage handles well-formatted PDFs with tables. The heuristic
stage catches unstructured PDFs where tables aren't preserved.
"""

from __future__ import annotations

import re

import fitz

from ..schema.financials import BalanceSheet, CashFlow, IncomeStatement, PeriodFinancials
from .pdf_to_md import extract_line_items_from_table, find_financial_table, pdf_to_markdown
from .number_parser import parse_number

_NUMBER_RE = re.compile(
    r"\(?-?\$?\s*[\d,]+(?:\.\d+)?\)?|\(?-?\$?\s*\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?",
    re.IGNORECASE,
)

# Canonical line-item keywords → schema field name
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
    return parse_number(raw)


def _first_number_after(text: str, pos: int) -> float | None:
    window = text[pos : pos + 240]
    for m in _NUMBER_RE.finditer(window):
        val = _clean_number(m.group(0))
        if val is not None:
            return val
    return None


def _parse_heuristic(text: str) -> dict[str, float | None]:
    """Keyword/number heuristic — low confidence, used as fallback."""
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
    return found


def _parse_markdown(md: str) -> dict[str, float | None]:
    """Parse Markdown tables for line items — structured, higher confidence."""
    table = find_financial_table(md)
    if not table:
        return {}
    raw = extract_line_items_from_table(table)

    # Map raw labels to canonical field names
    result: dict[str, float | None] = {}
    for field, keywords in _LABEL_MAP:
        for label, value in raw.items():
            if any(kw in label for kw in keywords):
                result[field] = value
                break

    return result


def parse_pdf(path: str, year: str, entity: str | None = None) -> PeriodFinancials:
    """Parse a PDF into a PeriodFinancials object.

    Tries Markdown table extraction first (structured, high-confidence),
    then falls back to keyword/number heuristics (low-confidence).
    """
    # Stage 1: PDF → Markdown → table extraction
    md = pdf_to_markdown(path)
    found = _parse_markdown(md)

    # Stage 2: Fallback to heuristic if Markdown found too little
    if len(found) < 3:
        doc = fitz.open(path)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        found = _parse_heuristic(text)

    return PeriodFinancials(
        period=str(year),
        income_statement=IncomeStatement(**{k: v for k, v in found.items() if k in IncomeStatement.model_fields}),
        balance_sheet=BalanceSheet(**{k: v for k, v in found.items() if k in BalanceSheet.model_fields}),
        cash_flow=CashFlow(**{k: v for k, v in found.items() if k in CashFlow.model_fields}),
    )
