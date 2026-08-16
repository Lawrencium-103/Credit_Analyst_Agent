"""Multi-source ingestion orchestrator.

Accepts many files of mixed types (xlsx / pdf), each tagged by the user with a
fiscal year. SC-format workbooks containing multiple years are re-based so their
latest period maps to the assigned year and earlier periods decrement. Everything
is normalised into `PeriodFinancials` and merged into one `IngestionResult`.
"""

from __future__ import annotations

import openpyxl
from pydantic import BaseModel, Field

from ..schema.financials import (
    BalanceSheet,
    CashFlow,
    IncomeStatement,
    PeriodFinancials,
)
from .generic_xlsx import parse_generic_xlsx
from .pdf import parse_pdf
from ..spreading.loader import load_sc_workbook

SC_SHEETS = {"I. Profit_Loss", "I. Balance_Sheet", "I. Cashflow"}


class IngestionFlag(BaseModel):
    level: str = "info"  # info | warning
    message: str


class IngestionResult(BaseModel):
    entity_name: str = "Unknown entity"
    currency: str | None = None
    periods: list[PeriodFinancials] = Field(default_factory=list)
    flags: list[IngestionFlag] = Field(default_factory=list)


def _is_sc(path: str) -> bool:
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
        names = set(wb.sheetnames)
        wb.close()
        return SC_SHEETS.issubset(names)
    except Exception:
        return False


def _reyear(periods: list[PeriodFinancials], base_year: int) -> list[PeriodFinancials]:
    n = len(periods)
    for i, p in enumerate(periods):
        p.period = str(base_year - (n - 1) + i)
    return periods


def ingest_file(path: str, year: int, entity: str | None = None) -> tuple[list[PeriodFinancials], list[IngestionFlag]]:
    flags: list[IngestionFlag] = []
    ext = path.lower().rsplit(".", 1)[-1]
    if ext in ("xlsx", "xlsm", "xls"):
        if _is_sc(path):
            cf = load_sc_workbook(path)
            if entity:
                cf.entity_name = entity
            periods = cf.periods
            flags.append(IngestionFlag(level="info", message=f"Loaded Standard Chartered format ({len(periods)} periods)."))
        else:
            periods = [parse_generic_xlsx(path, str(year), entity)]
            flags.append(IngestionFlag(
                level="warning",
                message="Non-Standard-Chartered workbook — partial keyword extraction, human review required.",
            ))
    elif ext == "pdf":
        periods = [parse_pdf(path, str(year), entity)]
        flags.append(IngestionFlag(
            level="warning",
            message="PDF draft — heuristic extraction only, human review required before reliance.",
        ))
    else:
        raise ValueError(f"Unsupported file type: .{ext}")

    return _reyear(periods, year), flags


def ingest(items: list[dict]) -> IngestionResult:
    """items: list of {path, year, entity?}."""
    by_year: dict[str, PeriodFinancials] = {}
    all_flags: list[IngestionFlag] = []
    entity_name = "Unknown entity"
    currency: str | None = None

    for it in items:
        periods, flags = ingest_file(it["path"], int(it["year"]), it.get("entity"))
        all_flags.extend(flags)
        for p in periods:
            by_year[p.period] = p
        if it.get("entity"):
            entity_name = it["entity"]
        # capture entity/currency from an SC workbook if present
        try:
            if _is_sc(it["path"]):
                cf = load_sc_workbook(it["path"])
                if it.get("entity"):
                    cf.entity_name = it["entity"]
                entity_name = cf.entity_name
                currency = cf.currency
        except Exception:
            pass

    periods = [by_year[y] for y in sorted(by_year, key=lambda x: int(x))]
    return IngestionResult(
        entity_name=entity_name,
        currency=currency,
        periods=periods,
        flags=all_flags,
    )


_MATRIX: list[tuple[str, str, str, str]] = [
    ("Income Statement", "Revenue", "income_statement", "revenue"),
    ("Income Statement", "Cost of Sales", "income_statement", "cogs"),
    ("Income Statement", "Gross Profit", "income_statement", "gross_profit"),
    ("Income Statement", "Operating Expenses", "income_statement", "operating_expenses"),
    ("Income Statement", "EBITDA", "income_statement", "ebitda"),
    ("Income Statement", "Depreciation & Amortisation", "income_statement", "depreciation_amortization"),
    ("Income Statement", "EBIT", "income_statement", "ebit"),
    ("Income Statement", "Interest Expense", "income_statement", "interest_expense"),
    ("Income Statement", "Pre-tax Income", "income_statement", "pretax_income"),
    ("Income Statement", "Tax Expense", "income_statement", "tax_expense"),
    ("Income Statement", "Net Income", "income_statement", "net_income"),
    ("Balance Sheet", "Cash & Equivalents", "balance_sheet", "cash_and_equivalents"),
    ("Balance Sheet", "Accounts Receivable", "balance_sheet", "accounts_receivable"),
    ("Balance Sheet", "Inventory", "balance_sheet", "inventory"),
    ("Balance Sheet", "Current Assets", "balance_sheet", "current_assets"),
    ("Balance Sheet", "Total Assets", "balance_sheet", "total_assets"),
    ("Balance Sheet", "Accounts Payable", "balance_sheet", "accounts_payable"),
    ("Balance Sheet", "Current Liabilities", "balance_sheet", "current_liabilities"),
    ("Balance Sheet", "Total Liabilities", "balance_sheet", "total_liabilities"),
    ("Balance Sheet", "Total Debt", "balance_sheet", "total_debt"),
    ("Balance Sheet", "Total Equity", "balance_sheet", "total_equity"),
    ("Cash Flow", "Operating Cash Flow", "cash_flow", "operating_cash_flow"),
    ("Cash Flow", "Capital Expenditures", "cash_flow", "capital_expenditures"),
    ("Cash Flow", "Free Cash Flow", "cash_flow", "free_cash_flow"),
]


def build_matrix(result: IngestionResult) -> dict:
    years = [p.period for p in result.periods]
    rows = []
    for group, label, stmt, field in _MATRIX:
        values = {}
        for p in result.periods:
            sub = getattr(p, stmt)
            values[p.period] = getattr(sub, field)
        rows.append({"group": group, "label": label, "values": values})
    return {"years": years, "rows": rows}
