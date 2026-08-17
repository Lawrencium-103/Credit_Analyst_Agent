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
from .generic_xlsx import parse_generic_xlsx_multi
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
            periods = _reyear(periods, year)
        else:
            periods = parse_generic_xlsx_multi(path, str(year), entity)
            n = len(periods)
            flags.append(IngestionFlag(
                level="warning",
                message=f"Non-Standard-Chartered workbook ({n} period{'s' if n > 1 else ''}) — keyword extraction, human review required.",
            ))
            # generic parser already assigns correct year labels — no reyear
    elif ext == "pdf":
        periods = [parse_pdf(path, str(year), entity)]
        flags.append(IngestionFlag(
            level="warning",
            message="PDF draft — heuristic extraction only, human review required before reliance.",
        ))
        periods = _reyear(periods, year)
    else:
        raise ValueError(f"Unsupported file type: .{ext}")

    return periods, flags


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

    # Data quality flags
    all_flags.extend(_quality_flags(periods))

    return IngestionResult(
        entity_name=entity_name,
        currency=currency,
        periods=periods,
        flags=all_flags,
    )


# ── Data quality analysis ───────────────────────────────────────────────────

# Fields that are most important for credit analysis
_CRITICAL_FIELDS = [
    ("revenue", "income_statement", "Revenue"),
    ("net_income", "income_statement", "Net Income"),
    ("total_assets", "balance_sheet", "Total Assets"),
    ("total_equity", "balance_sheet", "Total Equity"),
    ("total_debt", "balance_sheet", "Total Debt"),
    ("operating_cash_flow", "cash_flow", "Operating Cash Flow"),
]

_IMPORTANT_FIELDS = [
    ("cogs", "income_statement", "Cost of Sales"),
    ("gross_profit", "income_statement", "Gross Profit"),
    ("ebitda", "income_statement", "EBITDA"),
    ("interest_expense", "income_statement", "Interest Expense"),
    ("cash_and_equivalents", "balance_sheet", "Cash & Equivalents"),
    ("current_assets", "balance_sheet", "Current Assets"),
    ("current_liabilities", "balance_sheet", "Current Liabilities"),
    ("accounts_receivable", "balance_sheet", "Accounts Receivable"),
    ("inventory", "balance_sheet", "Inventory"),
]


def _count_populated(periods: list[PeriodFinancials]) -> dict[str, int]:
    """Count how many periods have each field populated."""
    counts: dict[str, int] = {}
    for field_name, stmt_name, _ in _CRITICAL_FIELDS + _IMPORTANT_FIELDS:
        n = 0
        for p in periods:
            sub = getattr(p, stmt_name)
            if getattr(sub, field_name, None) is not None:
                n += 1
        counts[field_name] = n
    return counts


def _quality_flags(periods: list[PeriodFinancials]) -> list[IngestionFlag]:
    """Analyse extraction results and produce data quality flags."""
    flags: list[IngestionFlag] = []
    if not periods:
        flags.append(IngestionFlag(level="warning", message="No periods extracted."))
        return flags

    n = len(periods)

    # ── Missing critical fields ─────────────────────────────────────
    counts = _count_populated(periods)
    missing_critical = [
        label for field, _, label in _CRITICAL_FIELDS
        if counts.get(field, 0) == 0
    ]
    if missing_critical:
        flags.append(IngestionFlag(
            level="warning",
            message=f"Missing critical fields across all periods: {', '.join(missing_critical)}.",
        ))

    missing_important = [
        label for field, _, label in _IMPORTANT_FIELDS
        if counts.get(field, 0) == 0
    ]
    if missing_important:
        flags.append(IngestionFlag(
            level="warning",
            message=f"Missing important fields: {', '.join(missing_important)}.",
        ))

    # ── Partial coverage per period ─────────────────────────────────
    all_fields = _CRITICAL_FIELDS + _IMPORTANT_FIELDS
    for p in periods:
        filled = 0
        for field_name, stmt_name, _ in all_fields:
            sub = getattr(p, stmt_name)
            if getattr(sub, field_name, None) is not None:
                filled += 1
        pct = filled / len(all_fields)
        if pct < 0.3:
            flags.append(IngestionFlag(
                level="warning",
                message=f"Period {p.period}: only {filled}/{len(all_fields)} fields extracted — may be incomplete.",
            ))

    # ── Period-to-period consistency ────────────────────────────────
    if n >= 2:
        for field_name, stmt_name, label in _CRITICAL_FIELDS:
            vals = []
            for p in periods:
                sub = getattr(p, stmt_name)
                v = getattr(sub, field_name, None)
                if v is not None:
                    vals.append((p.period, v))
            if len(vals) >= 2:
                prev_label, prev_val = vals[0]
                for cur_label, cur_val in vals[1:]:
                    if prev_val != 0:
                        change = abs((cur_val - prev_val) / prev_val)
                        if change > 5.0:
                            flags.append(IngestionFlag(
                                level="warning",
                                message=(
                                    f"{label} changed {change:.0%} from {prev_label} "
                                    f"({prev_val:,.0f}) to {cur_label} ({cur_val:,.0f}) — verify data."
                                ),
                            ))
                    prev_label, prev_label = cur_label, cur_label
                    prev_val = cur_val

    # ── Negative equity warning ─────────────────────────────────────
    for p in periods:
        if p.balance_sheet.total_equity is not None and p.balance_sheet.total_equity < 0:
            flags.append(IngestionFlag(
                level="warning",
                message=f"Period {p.period}: negative total equity ({p.balance_sheet.total_equity:,.0f}) — ratio analysis may be unreliable.",
            ))

    return flags


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
