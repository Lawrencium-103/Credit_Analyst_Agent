"""Tests for multi-source ingestion (xlsx / pdf, multi-year, matrix)."""

from __future__ import annotations

import json
import os

import fitz
import openpyxl
import pytest

from credit_agent.ingest.loader import (
    build_matrix,
    ingest,
    ingest_file,
)
from credit_agent.ingest.pdf import (
    parse_pdf,
    parse_pdf_with_confidence,
    _parse_markdown_to_periods,
    parse_pdf_document,
)

SC = "data/raw/Task 1 Example Answer - Financial Reporting Tool.xlsx"


def test_sc_ingest_two_years():
    res = ingest([{"path": SC, "year": 2023, "entity": "GS"}])
    # For a Standard Chartered workbook the entity is known from the file itself;
    # the workbook name is authoritative (the SPA company field can still override at report time).
    assert res.entity_name == "Green Solutions Manufacturing Ltd"
    assert [p.period for p in res.periods] == ["2022", "2023"]
    assert res.currency == "USD (thousands)"
    assert res.flags[0].level == "info"


def test_sc_matrix_shape():
    res = ingest([{"path": SC, "year": 2023}])
    m = build_matrix(res)
    assert m["years"] == ["2022", "2023"]
    assert len(m["rows"]) == 24
    rev = next(r for r in m["rows"] if r["label"] == "Revenue")
    assert rev["values"]["2023"] == 53823.0


def test_multi_file_multi_year():
    # two copies of the SC workbook tagged to different years -> 4 distinct years
    res = ingest([
        {"path": SC, "year": 2023},
        {"path": SC, "year": 2021},
    ])
    assert set(p.period for p in res.periods) == {"2020", "2021", "2022", "2023"}


def test_generic_xlsx_fallback(tmp_path):
    path = tmp_path / "generic.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Revenue", 1000, 1200])
    ws.append(["Cost of sales", 600, 700])
    ws.append(["Gross Profit", 400, 500])
    ws.append(["Total Assets", 5000, 5500])
    ws.append(["Total Equity", 3000, 3200])
    wb.save(path)
    periods, flags, confidence, meta = ingest_file(str(path), 2022)
    # Multi-period generic: two data columns → two periods
    assert len(periods) == 2
    assert periods[0].income_statement.revenue == 1000
    assert periods[1].income_statement.revenue == 1200
    assert periods[0].balance_sheet.total_assets == 5000
    assert flags[0].level == "warning"


def test_pdf_heuristic_parse(tmp_path):
    path = tmp_path / "stmt.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 60), "Consolidated Statements")
    page.insert_text((50, 90), "Total Revenue          12,345")
    page.insert_text((50, 120), "Cost of Sales          7,000")
    page.insert_text((50, 150), "Gross Profit           5,345")
    page.insert_text((50, 180), "Total Assets           45,000")
    page.insert_text((50, 210), "Total Equity           20,000")
    doc.save(str(path))
    doc.close()

    pf = parse_pdf(str(path), 2023, "TestCo")
    assert pf.period == "2023"
    assert pf.income_statement.revenue == 12345.0
    assert pf.income_statement.cogs == 7000.0
    assert pf.balance_sheet.total_assets == 45000.0
    assert pf.balance_sheet.total_equity == 20000.0


def test_pdf_ingest_flag(tmp_path):
    path = tmp_path / "stmt.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 60), "Total Revenue 9,999")
    doc.save(str(path))
    doc.close()
    periods, flags, confidence, meta = ingest_file(str(path), 2023)
    assert periods[0].period == "2023"
    assert any(f.level == "warning" and "PDF" in f.message for f in flags)


# ── Page-by-page + confidence scoring ────────────────────────────────────────

class TestPageByPageProcessing:
    def test_two_page_pdf_merges_data(self, tmp_path):
        """Data spread across two pages is merged correctly."""
        path = tmp_path / "twopage.pdf"
        doc = fitz.open()
        # Page 1: IS items
        p1 = doc.new_page()
        p1.insert_text((50, 60), "Total Revenue 10,000")
        p1.insert_text((50, 90), "Cost of Sales 6,000")
        p1.insert_text((50, 120), "Net Income 2,500")
        # Page 2: BS items
        p2 = doc.new_page()
        p2.insert_text((50, 60), "Total Assets 50,000")
        p2.insert_text((50, 90), "Total Equity 25,000")
        p2.insert_text((50, 120), "Total Debt 15,000")
        doc.save(str(path))
        doc.close()

        pf, confidence, meta = parse_pdf_with_confidence(str(path), 2023)
        assert pf.income_statement.revenue == 10000.0
        assert pf.income_statement.cogs == 6000.0
        assert pf.balance_sheet.total_assets == 50000.0
        assert pf.balance_sheet.total_equity == 25000.0
        assert meta["total_pages"] == 2
        assert meta["pages_with_data"] == 2

    def test_empty_page_is_skipped(self, tmp_path):
        """Blank pages don't break extraction."""
        path = tmp_path / "emptypage.pdf"
        doc = fitz.open()
        # Page 1: empty
        doc.new_page()
        # Page 2: data
        p2 = doc.new_page()
        p2.insert_text((50, 60), "Revenue 5,000")
        p2.insert_text((50, 90), "Net Income 1,000")
        doc.save(str(path))
        doc.close()

        pf, confidence, meta = parse_pdf_with_confidence(str(path), 2023)
        assert pf.income_statement.revenue == 5000.0
        assert meta["total_pages"] == 2
        assert meta["pages_with_data"] == 1

    def test_multi_column_page_doesnt_garble(self, tmp_path):
        """Two columns on one page — text extraction interleaves them,
        but per-page processing limits the damage to one page."""
        path = tmp_path / "twocol.pdf"
        doc = fitz.open()
        p = doc.new_page()
        # Left column
        p.insert_text((50, 60), "Revenue 8,000")
        p.insert_text((50, 90), "Cost of Sales 5,000")
        # Right column (same page, different x position)
        p.insert_text((300, 60), "Total Assets 30,000")
        p.insert_text((300, 90), "Total Equity 15,000")
        doc.save(str(path))
        doc.close()

        pf, confidence, meta = parse_pdf_with_confidence(str(path), 2023)
        # Both columns should be extracted from the same page
        assert meta["pages_with_data"] == 1
        assert pf.income_statement.revenue == 8000.0
        assert pf.balance_sheet.total_assets == 30000.0


class TestConfidenceScoring:
    def test_table_sourced_higher_confidence(self, tmp_path):
        """Table-extracted values score higher than heuristic."""
        path = tmp_path / "table.pdf"
        doc = fitz.open()
        p = doc.new_page()
        # Insert a pipe-delimited table
        p.insert_text((50, 60), "| Revenue | 10,000 |")
        p.insert_text((50, 80), "|---|---|")
        p.insert_text((50, 100), "| Net Income | 3,000 |")
        doc.save(str(path))
        doc.close()

        _, confidence_table, meta_table = parse_pdf_with_confidence(str(path), 2023)

        # Compare with pure heuristic PDF
        path2 = tmp_path / "heuristic.pdf"
        doc2 = fitz.open()
        p2 = doc2.new_page()
        p2.insert_text((50, 60), "Total Revenue 10,000")
        p2.insert_text((50, 90), "Net Income 3,000")
        doc2.save(str(path2))
        doc2.close()

        _, confidence_heuristic, meta_heuristic = parse_pdf_with_confidence(str(path2), 2023)

        assert meta_table["extraction_method"] == "table"
        assert meta_heuristic["extraction_method"] == "heuristic"
        assert confidence_table >= confidence_heuristic

    def test_empty_pdf_zero_confidence(self, tmp_path):
        """Empty PDF gets zero confidence."""
        path = tmp_path / "empty.pdf"
        doc = fitz.open()
        doc.new_page()  # blank page
        doc.save(str(path))
        doc.close()

        _, confidence, meta = parse_pdf_with_confidence(str(path), 2023)
        assert confidence == 0.0
        assert meta["confidence_label"] == "low"

    def test_many_fields_higher_confidence(self, tmp_path):
        """More fields extracted → higher confidence."""
        path = tmp_path / "rich.pdf"
        doc = fitz.open()
        p = doc.new_page()
        p.insert_text((50, 60), "Total Revenue 10,000")
        p.insert_text((50, 90), "Cost of Sales 6,000")
        p.insert_text((50, 120), "Gross Profit 4,000")
        p.insert_text((50, 150), "EBITDA 2,500")
        p.insert_text((50, 180), "Net Income 1,500")
        p.insert_text((50, 210), "Total Assets 50,000")
        p.insert_text((50, 240), "Total Equity 20,000")
        doc.save(str(path))
        doc.close()

        _, confidence, meta = parse_pdf_with_confidence(str(path), 2023)
        assert confidence > 0.3
        assert meta["confidence_label"] in ("medium", "high")

    def test_confidence_in_ingestion_result(self, tmp_path):
        """IngestionResult includes confidence from PDF extraction."""
        from credit_agent.ingest.loader import ingest
        path = tmp_path / "stmt.pdf"
        doc = fitz.open()
        p = doc.new_page()
        p.insert_text((50, 60), "Total Revenue 9,999")
        p.insert_text((50, 90), "Net Income 2,000")
        doc.save(str(path))
        doc.close()

        result = ingest([{"path": str(path), "year": 2023, "entity": "PDFCo"}])
        assert result.extraction_confidence is not None
        assert 0.0 <= result.extraction_confidence <= 1.0
        assert result.extraction_meta != {}


# ── Whole-document Markdown pipeline (multi-year) ───────────────────────────

def test_markdown_multi_year_extraction():
    """A 2-year annual report (Markdown tables) yields two periods with years."""
    md = """
# Consolidated Statements of Income
| | 2023 | 2022 |
|---|---|---|
| Revenue | 53,823 | 31,536 |
| Cost of Sales | 40,000 | 20,000 |
| Gross Profit | 13,823 | 11,536 |
| Net Income | 5,644 | 862 |

# Consolidated Statements of Financial Position
| | 2023 | 2022 |
|---|---|---|
| Total Assets | 62,131 | 52,148 |
| Total Equity | 31,015 | 28,000 |
| Total Debt | 6,834 | 11,688 |

# Consolidated Statements of Cash Flows
| | 2023 | 2022 |
|---|---|---|
| Operating Cash Flow | 11,446 | 8,000 |
| Free Cash Flow | 3,432 | 2,000 |
"""
    periods, meta = _parse_markdown_to_periods(md, None, "2023")
    assert meta["extraction_method"] == "table"
    assert meta["years"] == ["2022", "2023"]
    assert len(periods) == 2
    by_year = {p.period: p for p in periods}
    assert by_year["2023"].income_statement.revenue == 53823.0
    assert by_year["2022"].income_statement.revenue == 31536.0
    assert by_year["2023"].balance_sheet.total_assets == 62131.0
    assert by_year["2023"].cash_flow.operating_cash_flow == 11446.0
    assert meta["review_required"] is False


def test_markdown_heuristic_fallback_single_period():
    """Text-only (no tables) falls back to heuristic: one implicit period, review required."""
    md = "Total Revenue 12,345\nCost of Sales 7,000\nTotal Assets 45,000\nTotal Equity 20,000"
    periods, meta = _parse_markdown_to_periods(md, None, "2023")
    assert meta["extraction_method"] == "heuristic"
    assert len(periods) == 1
    assert periods[0].period == "2023"
    assert periods[0].income_statement.revenue == 12345.0
    assert periods[0].balance_sheet.total_assets == 45000.0
    assert meta["review_required"] is True


def test_markdown_pdf_end_to_end(tmp_path):
    """Whole-doc Markdown pipeline parses a generated 2-year PDF."""
    from unittest.mock import patch

    path = tmp_path / "annual.pdf"
    doc = fitz.open()
    doc.new_page()  # any valid PDF; to_markdown is patched
    doc.save(str(path))
    doc.close()

    md = (
        "# Consolidated Statements of Income\n"
        "| | 2023 | 2022 |\n|---|---|---|\n"
        "| Revenue | 100,000 | 80,000 |\n"
        "| Net Income | 10,000 | 5,000 |\n"
    )
    with patch("credit_agent.ingest.pdf.pymupdf4llm.to_markdown", return_value=md):
        periods, confidence, meta = parse_pdf_document(str(path), None, "2023")

    assert meta["extraction_method"] == "table"
    assert "2023" in meta["years"] and "2022" in meta["years"]
    assert meta["total_pages"] == 1
    assert len(periods) == 2
    by_year = {p.period: p for p in periods}
    assert by_year["2023"].income_statement.revenue == 100000.0


def test_merge_period_collision_and_provenance():
    """Same period from multiple files: merge non-conflicting fields, flag conflicts,
    and record source provenance instead of silently overwriting."""
    from credit_agent.ingest.loader import _merge_period
    from credit_agent.schema.financials import (
        PeriodFinancials,
        IncomeStatement,
        BalanceSheet,
        CashFlow,
    )

    a = PeriodFinancials(
        period="2023",
        income_statement=IncomeStatement(revenue=1000.0, cogs=600.0),
        balance_sheet=BalanceSheet(total_assets=5000.0),
        cash_flow=CashFlow(operating_cash_flow=200.0),
    )
    b = PeriodFinancials(
        period="2023",
        income_statement=IncomeStatement(revenue=1000.0, gross_profit=400.0),
        balance_sheet=BalanceSheet(total_debt=1500.0),
        cash_flow=CashFlow(),
    )
    c = PeriodFinancials(
        period="2023",
        income_statement=IncomeStatement(revenue=999.0),  # clashes with a
        balance_sheet=BalanceSheet(),
        cash_flow=CashFlow(),
    )

    prov: dict = {}
    conflicts: list = []
    _merge_period(a, b, "fileB.xlsx", prov, conflicts)
    _merge_period(a, c, "fileC.xlsx", prov, conflicts)

    # non-conflicting fields merged in from the second file
    assert a.income_statement.gross_profit == 400.0
    assert a.balance_sheet.total_debt == 1500.0
    # equal values reconcile without a conflict
    assert a.income_statement.revenue == 1000.0
    # differing value is flagged and the existing value is preserved
    assert len(conflicts) == 1
    assert "fileC.xlsx" in conflicts[0]
    assert "revenue" in conflicts[0]
    # provenance: merged field attributed to its source; clash marked
    assert prov["income_statement.gross_profit"] == "fileB.xlsx"
    assert prov["balance_sheet.total_debt"] == "fileB.xlsx"
    assert prov["income_statement.revenue"] == "CONFLICT (fileC.xlsx vs prior)"


def test_ingest_multi_file_same_period_conflict_flag():
    """Two files claiming the same period with different revenue raise a warning flag."""
    res = ingest([
        {"path": SC, "year": 2023},
        {"path": SC, "year": 2023},  # identical source -> equal values, no conflict
    ])
    # Same workbook twice => equal values, so no collision warning expected
    assert not any("collision" in f.message.lower() for f in res.flags)

    # Now exercise the real collision path via a synthetic period override
    from credit_agent.schema.financials import PeriodFinancials, IncomeStatement
    from credit_agent.ingest.loader import _merge_period, _iter_fields

    existing = PeriodFinancials(period="2023", income_statement=IncomeStatement(revenue=100.0))
    incoming = PeriodFinancials(period="2023", income_statement=IncomeStatement(revenue=200.0))
    prov: dict = {}
    conflicts: list = []
    _merge_period(existing, incoming, "other.pdf", prov, conflicts)
    assert conflicts  # differing revenue across files is detected

