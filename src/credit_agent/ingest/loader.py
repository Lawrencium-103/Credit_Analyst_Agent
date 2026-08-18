"""Multi-source ingestion orchestrator.

Accepts many files of mixed types (xlsx / pdf), each tagged by the user with a
fiscal year. SC-format workbooks containing multiple years are re-based so their
latest period maps to the assigned year and earlier periods decrement. Everything
is normalised into `PeriodFinancials` and merged into one `IngestionResult`.
"""

from __future__ import annotations

import os

import openpyxl
from pydantic import BaseModel, Field

from ..schema.financials import (
    BalanceSheet,
    CashFlow,
    IncomeStatement,
    PeriodFinancials,
)
from .generic_xlsx import parse_generic_xlsx_multi
from .pdf import _BANK_LABEL_MAP, _BANK_SIGNALS, _match_label, parse_markdown_document, parse_pdf_document
from ..spreading.loader import load_sc_workbook
from pathlib import Path

SC_SHEETS = {"I. Profit_Loss", "I. Balance_Sheet", "I. Cashflow"}


class IngestionFlag(BaseModel):
    level: str = "info"  # info | warning
    message: str


class IngestionResult(BaseModel):
    entity_name: str = "Unknown entity"
    currency: str | None = None
    periods: list[PeriodFinancials] = Field(default_factory=list)
    flags: list[IngestionFlag] = Field(default_factory=list)
    extraction_confidence: float | None = None  # 0.0–1.0, None for xlsx
    extraction_meta: dict = Field(default_factory=dict)


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


def _period_from_flat(obj: dict) -> PeriodFinancials:
    """Build a single PeriodFinancials from a flat {label: value} mapping.

    Uses the same label matcher as the PDF/Markdown pipelines so keys like
    "Net Revenue" or "Total Borrowings" land in the right schema field. Bank
    statements (keys mentioning loans/deposits/interest income) use the bank map.
    """
    keys_lower = [str(k).lower() for k in obj.keys()]
    use_bank = any(any(sig in k for sig in _BANK_SIGNALS) for k in keys_lower)
    match = (lambda lbl: _match_label(lbl, _BANK_LABEL_MAP)) if use_bank else _match_label
    inc, bal, cf = {}, {}, {}
    for k, v in obj.items():
        if v is None:
            continue
        field = match(str(k).lower())
        if not field:
            continue
        if field in IncomeStatement.model_fields:
            inc[field] = v
        elif field in BalanceSheet.model_fields:
            bal[field] = v
        elif field in CashFlow.model_fields:
            cf[field] = v
    return PeriodFinancials(
        period=str(obj.get("period") or obj.get("year") or "2023"),
        income_statement=IncomeStatement(**inc),
        balance_sheet=BalanceSheet(**bal),
        cash_flow=CashFlow(**cf),
    )


def parse_json_document(text: str, fallback_year: str = "2023") -> tuple[list[PeriodFinancials], float, dict]:
    """Parse an already-structured JSON document into periods.

    Accepts: a list of period objects, ``{"periods": [...]}``, or a single flat
    object mapping line-item labels to values. Returns the same
    ``(periods, confidence, meta)`` shape as the other parsers.
    """
    import json as _json

    data = _json.loads(text)
    if isinstance(data, dict) and "periods" in data and isinstance(data["periods"], list):
        items = data["periods"]
    elif isinstance(data, list):
        items = data
    else:
        items = [data]

    periods = []
    for it in items:
        if isinstance(it, dict):
            periods.append(_period_from_flat(it))
    if not periods:
        raise ValueError("JSON contained no parseable period objects.")

    is_bank = any(
        p.balance_sheet.loans_and_advances is not None or p.balance_sheet.customer_deposits is not None
        or p.income_statement.net_interest_income is not None
        for p in periods
    )
    filled = sum(
        1 for p in periods
        for stmt in (p.income_statement, p.balance_sheet, p.cash_flow)
        for f in type(stmt).model_fields
        if getattr(stmt, f) is not None
    )
    total = sum(len(stmt.model_fields) for stmt in (IncomeStatement, BalanceSheet, CashFlow))
    confidence = round(min(filled / max(total, 1), 1.0), 3)
    meta = {
        "extraction_method": "json",
        "confidence": confidence,
        "confidence_label": "high" if confidence >= 0.7 else ("medium" if confidence >= 0.4 else "low"),
        "years": [p.period for p in periods],
        "review_required": False,
        "is_bank": is_bank,
    }
    return periods, confidence, meta


def ingest_file(path: str, year: int, entity: str | None = None) -> tuple[list[PeriodFinancials], list[IngestionFlag], float | None, dict]:
    flags: list[IngestionFlag] = []
    ext = path.lower().rsplit(".", 1)[-1]
    confidence: float | None = None
    meta: dict = {}
    if ext in ("xlsx", "xlsm", "xls"):
        if _is_sc(path):
            cf = load_sc_workbook(path)
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
    elif ext == "pdf":
        periods, confidence, meta = parse_pdf_document(path, entity, str(year))
        label = meta.get("confidence_label", "low")
        method = meta.get("extraction_method", "unknown")
        pages = meta.get("pages_with_data", 0)
        total = meta.get("total_pages", 0)
        nper = len(periods)
        flags.append(IngestionFlag(
            level="warning" if (label != "high" or meta.get("review_required")) else "info",
            message=(
                f"PDF extraction ({label} confidence, {method} method, "
                f"{pages}/{total} pages, {nper} period(s): {', '.join(meta.get('years', [])) or 'n/a'}) "
                f"— human review required."
            )
            if meta.get("review_required") else
            f"PDF extraction ({label} confidence, {method} method, {nper} period(s)).",
        ))
    elif ext in ("md", "txt", "markdown"):
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
        periods, confidence, meta = parse_markdown_document(raw, entity, str(year))
        label = meta.get("confidence_label", "low")
        method = meta.get("extraction_method", "unknown")
        nper = len(periods)
        flags.append(IngestionFlag(
            level="warning" if (label != "high" or meta.get("review_required")) else "info",
            message=(
                f"Markdown extraction ({label} confidence, {method} method, "
                f"{nper} period(s): {', '.join(meta.get('years', [])) or 'n/a'}) "
                f"— human review required."
            )
            if meta.get("review_required") else
            f"Markdown extraction ({label} confidence, {method} method, {nper} period(s)).",
        ))
    elif ext == "json":
        raw = Path(path).read_text(encoding="utf-8", errors="ignore")
        periods, confidence, meta = parse_json_document(raw, str(year))
        label = meta.get("confidence_label", "low")
        nper = len(periods)
        flags.append(IngestionFlag(
            level="info",
            message=f"JSON extraction ({label} confidence, {nper} period(s): {', '.join(meta.get('years', [])) or 'n/a'}).",
        ))
    else:
        raise ValueError(f"Unsupported file type: .{ext}")

    if meta.get("is_bank"):
        flags.append(IngestionFlag(
            level="info",
            message=(
                "Bank / financial-institution statement detected — NIM, Loan/Deposit, "
                "NPL and Cost/Income computed; corporate leverage & coverage ratios are "
                "indicative only for banks and should not drive the rating as-is."
            ),
        ))

    return periods, flags, confidence, meta


def _iter_fields(pf: PeriodFinancials):
    for stmt_name in ("income_statement", "balance_sheet", "cash_flow"):
        sub = getattr(pf, stmt_name)
        for field_name in type(sub).model_fields:
            yield stmt_name, field_name, getattr(sub, field_name)


def _merge_period(existing, new, src, provenance, conflicts):
    """Merge `new` into `existing` field-by-field.

    Fields present in only one source are kept; fields present in both with
    equal values are reconciled; differing values are recorded as conflicts
    (the existing value is preserved) so nothing is silently overwritten.
    """
    for stmt_name, field_name, value in _iter_fields(new):
        if value is None:
            continue
        cur = getattr(getattr(existing, stmt_name), field_name)
        if cur is None:
            setattr(getattr(existing, stmt_name), field_name, value)
            provenance[f"{stmt_name}.{field_name}"] = src
        elif cur != value:
            conflicts.append(
                f"{stmt_name}.{field_name} for period {new.period}: "
                f"{src} provided {value}, prior value {cur}"
            )
            provenance[f"{stmt_name}.{field_name}"] = f"CONFLICT ({src} vs prior)"


def ingest(items: list[dict]) -> IngestionResult:
    """items: list of {path, year, entity?}."""
    by_year: dict[str, PeriodFinancials] = {}
    provenance: dict[str, dict] = {}
    all_flags: list[IngestionFlag] = []
    entity_name = "Unknown entity"
    currency: str | None = None
    overall_confidence: float | None = None
    all_meta: dict = {}
    conflicts: list[str] = []

    for it in items:
        periods, flags, confidence, meta = ingest_file(it["path"], int(it["year"]), it.get("entity"))
        all_flags.extend(flags)
        src = "SC workbook" if _is_sc(it["path"]) else os.path.basename(it["path"])
        for p in periods:
            if p.period not in by_year:
                by_year[p.period] = p
                prov = provenance.setdefault(p.period, {})
                for stmt_name, field_name, value in _iter_fields(p):
                    if value is not None:
                        prov[f"{stmt_name}.{field_name}"] = src
            else:
                # Same period supplied by more than one file. Merge
                # field-by-field instead of silently overwriting, and record
                # conflicts so the analyst can see the clash.
                existing = by_year[p.period]
                prov = provenance.setdefault(p.period, {})
                _merge_period(existing, p, src, prov, conflicts)
        if it.get("entity"):
            entity_name = it["entity"]
        # Track confidence from PDF extractions
        if confidence is not None:
            if overall_confidence is None:
                overall_confidence = confidence
            else:
                overall_confidence = min(overall_confidence, confidence)
            all_meta[it["path"]] = meta
        # capture entity/currency from an SC workbook if present
        try:
            if _is_sc(it["path"]):
                cf = load_sc_workbook(it["path"])
                entity_name = cf.entity_name
                currency = cf.currency
        except Exception:
            pass

    if conflicts:
        shown = conflicts[:8]
        more = len(conflicts) - len(shown)
        msg = (
            "Period collision across uploaded files — same period set by multiple "
            "files with differing values: " + "; ".join(shown)
        )
        if more > 0:
            msg += f"; +{more} more"
        all_flags.append(IngestionFlag(level="warning", message=msg))

    if provenance:
        all_meta["provenance"] = provenance

    periods = [by_year[y] for y in sorted(by_year, key=lambda x: int(x))]

    # Data quality flags
    all_flags.extend(_quality_flags(periods))

    return IngestionResult(
        entity_name=entity_name,
        currency=currency,
        periods=periods,
        flags=all_flags,
        extraction_confidence=overall_confidence,
        extraction_meta=all_meta,
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
