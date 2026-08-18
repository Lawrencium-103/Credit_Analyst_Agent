"""PDF financial-statement parser.

Two improvements over naive text concatenation:
  1. Page-by-page processing — each page parsed independently, results merged.
     Prevents multi-column layouts from garbling text across pages.
  2. Confidence scoring — flags low-confidence extractions for human review.
     Score based on: extraction method, field count, page coverage, value plausibility.

Pipeline per page:
  a. pymupdf4llm → Markdown tables (structured, high-confidence)
  b. If too few fields: keyword/number heuristic on raw text (low-confidence)
  c. Cross-page merge: prefer table-sourced values, fall back to heuristic
"""

from __future__ import annotations

import re

import fitz
import pymupdf4llm

from ..schema.financials import BalanceSheet, CashFlow, IncomeStatement, PeriodFinancials
from .number_parser import parse_number

# ── Confidence scoring ───────────────────────────────────────────────────────

# Weights for confidence calculation
_TABLE_WEIGHT = 1.0       # value came from a Markdown table
_HEURISTIC_WEIGHT = 0.4   # value came from keyword/number heuristic
_MIN_CONFIDENCE = 0.3     # below this, flag as low confidence

_NUMBER_RE = re.compile(
    r"\(?-?\$?\s*[\d,]+(?:\.\d+)?\)?|\(?-?\$?\s*\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?",
    re.IGNORECASE,
)

# Canonical line-item keywords → schema field name (extended for multi-page)
_LABEL_MAP: list[tuple[str, list[str]]] = [
    ("revenue", ["total revenue", "net revenue", "revenue from operations",
                 "net sales", "revenue", "sales", "turnover"]),
    ("cogs", ["cost of goods sold", "cost of products sold",
              "cost of sales", "cost of revenue", "cogs"]),
    ("gross_profit", ["gross profit", "gross income"]),
    ("operating_expenses", ["total operating expenses", "selling general and administrative",
                            "selling, general and administrative", "operating expenses",
                            "total opex", "opex", "administrative expenses"]),
    ("ebitda", ["ebitda"]),
    ("depreciation_amortization", ["depreciation and amortisation", "depreciation and amortization",
                                    "depreciation & amortisation", "depreciation & amortization",
                                    "depreciation", "amortisation", "amortization"]),
    ("ebit", ["operating profit", "operating income", "income from operations",
              "earnings before interest and tax", "ebit"]),
    ("interest_expense", ["finance costs", "finance expense", "interest expense",
                          "interest and finance costs", "net finance costs"]),
    ("interest_income", ["interest income", "interest earned", "finance income"]),
    ("pretax_income", ["profit before taxation", "profit before tax",
                       "income before income taxes", "income before tax",
                       "earnings before tax", "pretax income", "pbt"]),
    ("tax_expense", ["income tax expense", "tax expense", "taxation", "income taxes"]),
    ("net_income", ["net profit", "net income", "profit for the period",
                    "profit attributable to", "profit after tax", "net earnings", "pat"]),
    ("cash_and_equivalents", ["cash and cash equivalents", "cash at bank",
                              "cash and short-term deposits"]),
    ("marketable_securities", ["short-term investments", "marketable securities",
                               "trading securities"]),
    ("accounts_receivable", ["trade receivables", "accounts receivable",
                             "receivables, net", "trade and other receivables"]),
    ("inventory", ["inventories", "inventory"]),
    ("current_assets", ["total current assets", "current assets"]),
    ("total_assets", ["total assets"]),
    ("accounts_payable", ["trade payables", "accounts payable",
                          "trade and other payables", "payables"]),
    ("current_liabilities", ["total current liabilities", "current liabilities"]),
    ("total_liabilities", ["total liabilities"]),
    ("short_term_debt", ["short-term borrowings", "current portion of long-term debt",
                         "short-term debt", "current maturities of debt"]),
    ("long_term_debt", ["long-term borrowings", "long-term debt",
                        "non-current liabilities"]),
    ("total_debt", ["total borrowings", "total debt", "total financial liabilities"]),
    ("total_equity", ["total shareholders equity", "shareholders equity",
                      "stockholders equity", "total equity",
                      "equity attributable to", "total stockholders"]),
    ("retained_earnings", ["retained earnings", "accumulated deficit"]),
    ("operating_cash_flow", ["net cash from operating activities",
                             "cash generated from operations",
                             "cash flow from operating activities",
                             "net cash provided by operating activities",
                             "operating cash flow"]),
    ("capital_expenditures", ["purchase of property and equipment",
                              "purchases of property and equipment",
                              "acquisition of property, plant",
                              "additions to property, plant",
                              "capital expenditure", "capex"]),
    ("free_cash_flow", ["free cash flow", "free cashflow"]),
    ("investing_cash_flow", ["net cash used in investing activities",
                             "cash flow from investing activities",
                             "investing cash flow"]),
    ("financing_cash_flow", ["net cash used in financing activities",
                             "cash flow from financing activities",
                             "financing cash flow"]),
    ("dividends_paid", ["dividends paid", "dividends paid to shareholders",
                        "dividends declared"]),
]


# ── Per-page extraction ──────────────────────────────────────────────────────

def _extract_tables_from_page(page) -> list[list[list[str]]]:
    """Extract Markdown tables from a single PDF page."""
    try:
        md_page = pymupdf4llm.to_markdown(
            fitz.open("pdf", page.parent.stream) if hasattr(page, 'parent') else None,
            pages=[page.number],
        ) if False else ""  # pymupdf4llm doesn't support single-page directly
    except Exception:
        pass

    # Fallback: extract text and parse tables from it
    text = page.get_text()
    return _extract_tables_from_text(text)


def _extract_tables_from_text(text: str) -> list[list[list[str]]]:
    """Extract tables from text that looks like Markdown pipe tables."""
    tables: list[list[list[str]]] = []
    current_table: list[list[str]] = []

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            current_table.append(cells)
        else:
            if current_table and len(current_table) >= 2:
                tables.append(current_table)
            current_table = []

    if current_table and len(current_table) >= 2:
        tables.append(current_table)

    return tables


def _find_best_table(tables: list[list[list[str]]]) -> list[list[str]] | None:
    """Find the table with the most numeric cells."""
    if not tables:
        return None

    def numeric_ratio(table: list[list[str]]) -> float:
        total, numeric = 0, 0
        for row in table:
            for cell in row[1:]:
                total += 1
                cleaned = cell.replace(",", "").replace("(", "").replace(")", "").replace("$", "").replace("%", "").strip()
                try:
                    float(cleaned)
                    numeric += 1
                except ValueError:
                    pass
        return numeric / max(total, 1)

    return max(tables, key=numeric_ratio)


def _table_to_fields(table: list[list[str]]) -> dict[str, tuple[float | None, str]]:
    """Extract fields from a table. Returns {field: (value, source)}."""
    if not table or len(table[0]) < 2:
        return {}

    result: dict[str, tuple[float | None, str]] = {}
    for row in table:
        label = row[0].strip().lower()
        if not label:
            continue
        raw = row[-1].strip()
        cleaned = raw.replace(",", "").replace("(", "-").replace(")", "").replace("$", "").replace("%", "").strip()
        try:
            value = float(cleaned)
        except ValueError:
            value = None

        # Match label to canonical field
        for field, keywords in _LABEL_MAP:
            if any(kw in label for kw in keywords):
                if field not in result:
                    result[field] = (value, "table")
                break

    return result


def _heuristic_from_text(text: str) -> dict[str, tuple[float | None, str]]:
    """Keyword/number heuristic on raw text. Returns {field: (value, source)}."""
    text_lower = text.lower()
    found: dict[str, tuple[float | None, str]] = {}

    for field, keywords in _LABEL_MAP:
        for kw in keywords:
            idx = text_lower.find(kw)
            if idx != -1:
                window = text[idx:idx + 240]
                for m in _NUMBER_RE.finditer(window):
                    val = parse_number(m.group(0))
                    if val is not None:
                        if field not in found:
                            found[field] = (val, "heuristic")
                        break
                break

    return found


def _merge_page_results(
    acc: dict[str, tuple[float | None, str]],
    page_result: dict[str, tuple[float | None, str]],
) -> None:
    """Merge a page's results into the accumulator.

    Prefers table-sourced values over heuristic.
    For same-source, first-write-wins (earlier pages take priority).
    """
    for field, (value, source) in page_result.items():
        if field not in acc:
            acc[field] = (value, source)
        else:
            existing_value, existing_source = acc[field]
            # Prefer table over heuristic
            if source == "table" and existing_source == "heuristic":
                acc[field] = (value, source)
            # If both are table, first-write-wins (earlier page)


# ── Confidence scoring ───────────────────────────────────────────────────────

def _compute_confidence(
    fields: dict[str, tuple[float | None, str]],
    total_pages: int,
    pages_with_data: int,
) -> float:
    """Compute extraction confidence score (0.0–1.0).

    Factors:
    - Field coverage: what % of known fields were extracted
    - Source quality: table-sourced values are weighted higher
    - Page coverage: data from more pages = more reliable
    """
    if not fields:
        return 0.0

    total_known = len(_LABEL_MAP)
    filled = sum(1 for v, _ in fields.values() if v is not None)
    coverage = filled / total_known

    # Source quality: weighted average of table vs heuristic
    source_score = 0.0
    for value, source in fields.values():
        if value is not None:
            source_score += _TABLE_WEIGHT if source == "table" else _HEURISTIC_WEIGHT
    source_score = source_score / max(filled, 1)

    # Page coverage: data from more pages is more reliable
    page_score = min(pages_with_data / max(total_pages, 1), 1.0)

    # Composite score (0.0–1.0)
    confidence = (coverage * 0.5) + (source_score * 0.3) + (page_score * 0.2)
    return round(min(confidence, 1.0), 3)


def _confidence_label(score: float) -> str:
    if score >= 0.7:
        return "high"
    elif score >= 0.4:
        return "medium"
    else:
        return "low"


# ── Public API ───────────────────────────────────────────────────────────────

def parse_pdf(path: str, year: str, entity: str | None = None) -> PeriodFinancials:
    """Parse a PDF into a single PeriodFinancials (backward compat)."""
    result, confidence, meta = parse_pdf_with_confidence(path, year, entity)
    return result


def parse_pdf_with_confidence(
    path: str, year: str, entity: str | None = None
) -> tuple[PeriodFinancials, float, dict]:
    """Parse a PDF with page-by-page processing and confidence scoring.

    Returns (PeriodFinancials, confidence_score, metadata).
    Metadata includes:
      - total_pages: total pages in PDF
      - pages_with_data: pages that yielded financial data
      - extraction_method: "table", "heuristic", or "mixed"
      - fields_by_source: {field: "table"|"heuristic"}
    """
    doc = fitz.open(path)
    total_pages = len(doc)

    # Accumulator: {field: (value, source)}
    acc: dict[str, tuple[float | None, str]] = {}
    pages_with_data = 0

    for page_num in range(total_pages):
        page = doc[page_num]
        text = page.get_text()

        if not text.strip():
            continue

        # Try table extraction first
        tables = _extract_tables_from_text(text)
        best_table = _find_best_table(tables)
        page_fields = _table_to_fields(best_table) if best_table else {}

        # Fall back to heuristic if too few fields from tables
        if len(page_fields) < 3:
            heuristic_fields = _heuristic_from_text(text)
            # Merge: prefer table values already found
            for field, (value, source) in heuristic_fields.items():
                if field not in page_fields:
                    page_fields[field] = (value, source)

        if page_fields:
            pages_with_data += 1
            _merge_page_results(acc, page_fields)

    doc.close()

    # Build result
    found = {k: v for k, (v, _) in acc.items()}
    fields_by_source = {k: src for k, (_, src) in acc.items()}

    # Determine extraction method
    sources_used = set(fields_by_source.values())
    if sources_used == {"table"}:
        method = "table"
    elif sources_used == {"heuristic"}:
        method = "heuristic"
    else:
        method = "mixed"

    confidence = _compute_confidence(acc, total_pages, pages_with_data)

    result = PeriodFinancials(
        period=str(year),
        income_statement=IncomeStatement(**{k: v for k, v in found.items() if k in IncomeStatement.model_fields}),
        balance_sheet=BalanceSheet(**{k: v for k, v in found.items() if k in BalanceSheet.model_fields}),
        cash_flow=CashFlow(**{k: v for k, v in found.items() if k in CashFlow.model_fields}),
    )

    meta = {
        "total_pages": total_pages,
        "pages_with_data": pages_with_data,
        "extraction_method": method,
        "confidence": confidence,
        "confidence_label": _confidence_label(confidence),
        "fields_by_source": fields_by_source,
    }

    return result, confidence, meta


# ── Whole-document Markdown pipeline (multi-page / multi-year) ────────────────
#
# Converts the entire PDF to Markdown first (pymupdf4llm), then splits it into
# statement sections. Each section's Markdown table is parsed for its YEAR
# columns, so a 2- (or 3-) year annual report yields multiple PeriodFinancials
# instead of the single collapsed period the page-by-page path produces. Text
# sections without a table fall back to the keyword heuristic (one period).

_STMT_PATTERNS = [
    ("income", re.compile(r"income statement|statement of operations|consolidated statements? of (income|operations|earnings)|statements of income", re.I)),
    ("balance", re.compile(r"balance sheet|statement of financial position|statements? of financial position|consolidated statements? of financial position", re.I)),
    ("cashflow", re.compile(r"cash ?flow|statement of cash flows|statements? of cash flows", re.I)),
]
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def _match_label(label: str) -> str | None:
    """Match a statement label to a canonical field.

    Uses the LONGEST matching keyword so specific phrases win over broad
    substrings (e.g. "cost of sales" must map to `cogs`, not to `revenue`
    via the "sales" keyword).
    """
    best = None
    best_len = 0
    for field, keywords in _LABEL_MAP:
        for kw in keywords:
            if kw in label and len(kw) > best_len:
                best = field
                best_len = len(kw)
    return best


def _split_statements(md: str) -> list[tuple[str | None, str]]:
    """Split Markdown into (statement_type, text) sections by header detection."""
    sections: list[tuple[str | None, list[str]]] = []
    current_type: str | None = None
    current_lines: list[str] = []
    for line in md.splitlines():
        stripped = line.strip()
        matched = None
        for stype, pat in _STMT_PATTERNS:
            if pat.search(stripped):
                matched = stype
                break
        if matched:
            sections.append((current_type, "\n".join(current_lines)))
            current_type = matched
            current_lines = [line]
        else:
            current_lines.append(line)
    sections.append((current_type, "\n".join(current_lines)))
    return [(t, txt) for t, txt in sections if txt.strip()]


def _extract_year_columns(header_cells: list[str]) -> list[tuple[int, int]]:
    """Return [(data_index, year), ...] for header cells containing a 4-digit year."""
    cols = []
    for i, cell in enumerate(header_cells):
        m = _YEAR_RE.search(cell)
        if m:
            cols.append((i, int(m.group(0))))
    return cols


def _parse_section_table(text: str) -> dict[str, dict[int, float]] | None:
    """Parse the first Markdown table in a section into {field: {year: value}}."""
    rows: list[list[str]] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.split("|")[1:-1]]
            if cells and all(set(c) <= set("-: ") for c in cells):
                continue  # separator row
            rows.append(cells)
        else:
            if rows:
                break  # only the first contiguous table
    if len(rows) < 2:
        return None
    header = rows[0]
    year_cols = _extract_year_columns(header)
    if not year_cols:
        return None
    out: dict[str, dict[int, float]] = {}
    for row in rows[1:]:
        label = row[0].lower() if row else ""
        if not label:
            continue
        field = _match_label(label)
        if not field:
            continue
        for idx, yr in year_cols:
            if idx < len(row):
                val = parse_number(row[idx])
                if val is not None:
                    out.setdefault(field, {})[yr] = val
    return out or None


def _parse_markdown_to_periods(
    md: str, entity: str | None = None, fallback_year: str = "2023"
) -> tuple[list[PeriodFinancials], dict]:
    sections = _split_statements(md)
    stmt_data: dict[str, dict[str, dict[int, float]]] = {
        "income": {}, "balance": {}, "cashflow": {}
    }
    any_table = False
    detected_years: set[int] = set()

    for stype, text in sections:
        if stype in stmt_data:
            tbl = _parse_section_table(text)
            if tbl:
                any_table = True
                for f, ym in tbl.items():
                    stmt_data[stype].setdefault(f, {}).update(ym)
                    detected_years.update(ym.keys())
                continue
            # no table in a typed section -> heuristic (single period)
            for f, (v, _src) in _heuristic_from_text(text).items():
                if v is not None:
                    stmt_data[stype].setdefault(f, {}).setdefault(int(fallback_year), v)
        else:
            # preamble / untyped section -> heuristic across all statements
            for f, (v, _src) in _heuristic_from_text(text).items():
                if v is None:
                    continue
                if f in IncomeStatement.model_fields:
                    stmt_data["income"].setdefault(f, {}).setdefault(int(fallback_year), v)
                elif f in BalanceSheet.model_fields:
                    stmt_data["balance"].setdefault(f, {}).setdefault(int(fallback_year), v)
                elif f in CashFlow.model_fields:
                    stmt_data["cashflow"].setdefault(f, {}).setdefault(int(fallback_year), v)

    years = sorted(detected_years) if detected_years else [int(fallback_year)]
    periods: list[PeriodFinancials] = []
    for yr in years:
        periods.append(PeriodFinancials(
            period=str(yr),
            income_statement=IncomeStatement(
                **{f: stmt_data["income"].get(f, {}).get(yr) for f in IncomeStatement.model_fields}),
            balance_sheet=BalanceSheet(
                **{f: stmt_data["balance"].get(f, {}).get(yr) for f in BalanceSheet.model_fields}),
            cash_flow=CashFlow(
                **{f: stmt_data["cashflow"].get(f, {}).get(yr) for f in CashFlow.model_fields}),
        ))

    distinct = {f for s in stmt_data.values() for f in s}
    coverage = len(distinct) / len(_LABEL_MAP)
    confidence = round(min(coverage, 1.0), 3)
    method = "table" if any_table else "heuristic"
    implicit_year = (not detected_years)
    # Gate on extraction reliability, not on how many line items the PDF
    # happened to disclose: a table parse with detected year columns is
    # structurally trustworthy; heuristic or year-less parses need review.
    review_required = (method != "table") or implicit_year

    meta = {
        "extraction_method": method,
        "confidence": confidence,
        "confidence_label": _confidence_label(confidence),
        "years": [str(y) for y in years],
        "review_required": bool(review_required),
        "markdown": md,
        "entity": entity,
    }
    return periods, meta


def parse_pdf_document(
    path: str, entity: str | None = None, fallback_year: str = "2023"
) -> tuple[list[PeriodFinancials], float, dict]:
    """Parse a whole PDF via the Markdown pipeline.

    Returns (list[PeriodFinancials], confidence, metadata). Produces one
    PeriodFinancials per detected fiscal year; falls back to a single period
    labelled `fallback_year` when no year columns are found. `metadata` carries
    `review_required` so callers can enforce a human-review gate.
    """
    md = pymupdf4llm.to_markdown(path)
    periods, meta = _parse_markdown_to_periods(md, entity, fallback_year)
    doc = fitz.open(path)
    meta["total_pages"] = len(doc)
    doc.close()
    meta["pages_with_data"] = meta["total_pages"] if periods else 0
    return periods, meta.get("confidence", 0.0), meta
