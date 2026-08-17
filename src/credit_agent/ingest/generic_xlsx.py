"""Generic xlsx parser (non-Standard-Chartered statements).

Best-effort: scans every sheet for known labels and reads ALL numeric data
columns. Period headers are auto-detected from the first row (or first row
containing year-like values). Multiple periods are returned when multiple
data columns are found.

Output is flagged low-confidence for human review.
"""

from __future__ import annotations

import re

import openpyxl

from ..schema.financials import BalanceSheet, CashFlow, IncomeStatement, PeriodFinancials
from .number_parser import parse_number

# ── Extended keyword list (field → ordered list of substring matches) ────────
# Longer/more-specific phrases first to avoid false positives (e.g. "total
# revenue" before bare "revenue").
_KEYWORDS: list[tuple[str, list[str]]] = [
    # Income statement
    ("revenue", [
        "total revenue", "net revenue", "total net revenue",
        "net sales", "revenue from operations", "turnover",
        "revenue", "sales",
    ]),
    ("cogs", [
        "cost of goods sold", "cost of products sold",
        "cost of sales", "cost of revenue", "cogs",
    ]),
    ("gross_profit", ["gross profit", "gross income"]),
    ("operating_expenses", [
        "total operating expenses", "selling general and administrative",
        "selling, general and administrative", "selling & administrative",
        "operating expenses", "total opex", "opex",
        "administrative expenses", "selling expenses",
    ]),
    ("ebitda", ["ebitda"]),
    ("depreciation_amortization", [
        "depreciation and amortisation", "depreciation and amortization",
        "depreciation & amortisation", "depreciation & amortization",
        "depreciation, amortisation and impairment",
        "depreciation", "amortisation", "amortization",
    ]),
    ("ebit", [
        "operating profit", "operating income",
        "income from operations", "profit from operations",
        "earnings before interest and tax", "ebit",
    ]),
    ("interest_expense", [
        "finance costs", "finance expense", "interest expense",
        "interest and finance costs", "net finance costs",
    ]),
    ("interest_income", [
        "interest income", "interest earned", "finance income",
    ]),
    ("pretax_income", [
        "profit before taxation", "profit before tax",
        "income before income taxes", "income before tax",
        "earnings before tax", "pretax income", "pbt",
    ]),
    ("tax_expense", [
        "income tax expense", "tax expense",
        "taxation", "income taxes",
    ]),
    ("net_income", [
        "net profit", "net income", "profit for the period",
        "profit attributable to", "profit after tax",
        "earnings per share", "pat", "net earnings",
    ]),
    # Balance sheet
    ("cash_and_equivalents", [
        "cash and cash equivalents", "cash at bank",
        "cash and short-term deposits",
    ]),
    ("marketable_securities", [
        "short-term investments", "marketable securities",
        "trading securities", "financial assets at fair value",
    ]),
    ("accounts_receivable", [
        "trade receivables", "accounts receivable",
        "receivables, net", "trade and other receivables",
        "trade and other receivables",
    ]),
    ("inventory", ["inventories", "inventory"]),
    ("current_assets", ["total current assets", "current assets"]),
    ("total_assets", ["total assets"]),
    ("accounts_payable", [
        "trade payables", "accounts payable",
        "trade and other payables", "payables",
    ]),
    ("current_liabilities", [
        "total current liabilities", "current liabilities",
    ]),
    ("total_liabilities", ["total liabilities"]),
    ("short_term_debt", [
        "short-term borrowings", "current portion of long-term debt",
        "short-term debt", "current maturities of debt",
        "short-term borrowings and current",
    ]),
    ("long_term_debt", [
        "long-term borrowings", "long-term debt",
        "non-current liabilities", "long-term borrowings and lease",
    ]),
    ("total_debt", [
        "total borrowings", "total debt",
        "total financial liabilities",
    ]),
    ("total_equity", [
        "total shareholders equity", "shareholders equity",
        "stockholders equity", "total equity",
        "equity attributable to", "total stockholders",
    ]),
    ("retained_earnings", [
        "retained earnings", "accumulated deficit",
        "retained earnings (accumulated deficit)",
    ]),
    # Cash flow
    ("operating_cash_flow", [
        "net cash from operating activities",
        "cash generated from operations",
        "cash flow from operating activities",
        "net cash provided by operating activities",
        "operating cash flow",
    ]),
    ("capital_expenditures", [
        "purchase of property and equipment",
        "purchases of property and equipment",
        "acquisition of property, plant",
        "additions to property, plant",
        "capital expenditure", "capex",
    ]),
    ("free_cash_flow", ["free cash flow", "free cashflow"]),
    ("investing_cash_flow", [
        "net cash used in investing activities",
        "cash flow from investing activities",
        "investing cash flow",
    ]),
    ("financing_cash_flow", [
        "net cash used in financing activities",
        "cash flow from financing activities",
        "financing cash flow",
    ]),
    ("dividends_paid", [
        "dividends paid", "dividends paid to shareholders",
        "dividends declared",
    ]),
]

# Year-like patterns for header detection
_YEAR_RE = re.compile(r"(?:FY\s*)?(?:20)?(\d{2})(?:\s*[/\-\u2013]\s*(?:FY\s*)?(?:20)?(\d{2}))?")
_DATE_RE = re.compile(r"\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?")
_FULL_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def _is_period_header(val) -> bool:
    """Return True if a cell value looks like a period header (year/date).

    The ENTIRE value must match — substrings of larger numbers are rejected.
    """
    if val is None:
        return False
    s = str(val).strip()
    if not s:
        return False
    # Full year: 2023, 2023-12-31
    if _FULL_YEAR_RE.fullmatch(s):
        return True
    # Date: 2023/12/31
    if _DATE_RE.fullmatch(s):
        return True
    # Short year: FY23, FY2023
    if re.fullmatch(r"(?:FY\s*)?(?:20)?\d{2}", s, re.IGNORECASE):
        return True
    # Year range: 23/24, 22-23, 2022-2023
    if re.fullmatch(r"(?:20)?\d{2}\s*[/\-\u2013]\s*(?:20)?\d{2}", s):
        return True
    return False


def _extract_year_label(val) -> str | None:
    """Extract a clean year label from a period header cell.

    Only matches if the ENTIRE value looks like a year/date (no partial matches
    on financial numbers like 1000 or 1234567).
    """
    if val is None:
        return None
    s = str(val).strip()

    # Full year: 2023
    if _FULL_YEAR_RE.fullmatch(s):
        return s[:4]

    # Full date: 2023-12-31, 2023/12/31
    m = _DATE_RE.fullmatch(s)
    if m:
        ym = _FULL_YEAR_RE.search(s)
        if ym:
            return ym.group(0)[:4]

    # Short year: FY23
    m = re.fullmatch(r"(?:FY\s*)?(?:20)?(\d{2})", s, re.IGNORECASE)
    if m:
        y1 = int(m.group(1))
        yr = 2000 + y1 if y1 < 100 else y1
        return str(yr)

    # Year range: 23/24, 22-23 → use end year
    m = re.fullmatch(r"(?:20)?(\d{2})\s*[/\-\u2013]\s*(?:20)?(\d{2})", s)
    if m:
        y2 = int(m.group(2))
        yr2 = 2000 + y2 if y2 < 100 else y2
        return str(yr2)

    return None


def _detect_data_columns(ws) -> list[int]:
    """Detect which columns contain numeric data by scanning a sample of rows.

    Returns list of 1-indexed column numbers (excluding column A / 1 which
    is assumed to be labels).
    """
    numeric_cols: dict[int, int] = {}  # col → count of numeric cells
    sample_rows = min(ws.max_row or 1, 30)

    for row in range(1, sample_rows + 1):
        for col in range(2, (ws.max_column or 2) + 1):
            val = ws.cell(row=row, column=col).value
            if val is None:
                continue
            parsed = parse_number(val)
            if parsed is not None:
                numeric_cols[col] = numeric_cols.get(col, 0) + 1

    # A column is "data" if it has at least 2 numeric cells in the sample
    return [col for col, count in sorted(numeric_cols.items()) if count >= 2]


def _detect_period_headers(ws, data_cols: list[int]) -> dict[int, str]:
    """Scan the first few rows to find period labels for each data column.

    Returns {col_index: year_label}.
    """
    # Scan first 5 rows for header-like values
    for row in range(1, min(6, (ws.max_row or 1) + 1)):
        candidates: dict[int, str] = {}
        for col in data_cols:
            val = ws.cell(row=row, column=col).value
            year = _extract_year_label(val)
            if year:
                candidates[col] = year
        # If we found headers for at least half the data columns, use them
        if len(candidates) >= max(1, len(data_cols) // 2):
            return candidates

    return {}


def _match_field(label: str) -> str | None:
    """Match a row label to a canonical field name.

    Uses longest-match-first: finds the keyword with the most characters
    that appears in the label, then returns its field. This prevents bare
    'sales' from matching before 'cost of sales'.
    """
    label_l = label.lower()
    best_field = None
    best_len = 0
    for field, keywords in _KEYWORDS:
        for kw in keywords:
            if kw in label_l and len(kw) > best_len:
                best_field = field
                best_len = len(kw)
    return best_field


def _to_period_dict(
    found: dict[str, float | None],
) -> tuple[dict[str, float | None], dict[str, float | None], dict[str, float | None]]:
    """Split a flat field dict into IS / BS / CF dicts."""
    is_fields = {k: v for k, v in found.items() if k in IncomeStatement.model_fields}
    bs_fields = {k: v for k, v in found.items() if k in BalanceSheet.model_fields}
    cf_fields = {k: v for k, v in found.items() if k in CashFlow.model_fields}
    return is_fields, bs_fields, cf_fields


def parse_generic_xlsx(path: str, year: str, entity: str | None = None) -> PeriodFinancials:
    """Parse a generic xlsx into a single PeriodFinancials (backward compat)."""
    periods = parse_generic_xlsx_multi(path, year, entity)
    return periods[0] if periods else PeriodFinancials(
        period=str(year),
        income_statement=IncomeStatement(),
        balance_sheet=BalanceSheet(),
        cash_flow=CashFlow(),
    )


def parse_generic_xlsx_multi(
    path: str, year: str, entity: str | None = None
) -> list[PeriodFinancials]:
    """Parse a generic xlsx into one or more PeriodFinancials objects.

    Reads ALL data columns and auto-detects period headers. Falls back to
    a single period (column B only) if no headers are detected.
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    all_period_data: dict[str, dict[str, float | None]] = {}  # year → {field: value}

    for ws in wb.worksheets:
        if ws.max_row is None or ws.max_row < 1:
            continue

        data_cols = _detect_data_columns(ws)
        if not data_cols:
            continue

        # Detect period headers
        headers = _detect_period_headers(ws, data_cols)

        # Build column→year mapping
        col_year: dict[int, str] = {}
        for col in data_cols:
            if col in headers:
                col_year[col] = headers[col]
            else:
                # No header for this column — use the base year offset
                # If we have N data columns and a base year, assign backwards
                idx = data_cols.index(col)
                try:
                    base = int(year)
                    col_year[col] = str(base - (len(data_cols) - 1) + idx)
                except (ValueError, TypeError):
                    col_year[col] = str(year)

        # Initialize period dicts
        for yr in col_year.values():
            if yr not in all_period_data:
                all_period_data[yr] = {}

        # Scan rows for label + value
        for row in range(1, ws.max_row + 1):
            label_cell = ws.cell(row=row, column=1).value
            if not label_cell:
                continue

            field = _match_field(str(label_cell))
            if not field:
                continue

            # Skip if already found with a non-None value
            for yr in col_year.values():
                if field in all_period_data[yr] and all_period_data[yr][field] is not None:
                    break
            else:
                # Read value from each data column
                for col in data_cols:
                    yr = col_year[col]
                    if field in all_period_data[yr] and all_period_data[yr][field] is not None:
                        continue
                    val = parse_number(ws.cell(row=row, column=col).value)
                    if val is not None:
                        all_period_data[yr][field] = val

    wb.close()

    # Build PeriodFinancials for each year
    periods: list[PeriodFinancials] = []
    for yr in sorted(all_period_data.keys()):
        data = all_period_data[yr]
        is_f, bs_f, cf_f = _to_period_dict(data)
        periods.append(PeriodFinancials(
            period=str(yr),
            income_statement=IncomeStatement(**is_f),
            balance_sheet=BalanceSheet(**bs_f),
            cash_flow=CashFlow(**cf_f),
        ))

    # If no periods were created, return a single empty one
    if not periods:
        periods = [PeriodFinancials(
            period=str(year),
            income_statement=IncomeStatement(),
            balance_sheet=BalanceSheet(),
            cash_flow=CashFlow(),
        )]

    return periods
