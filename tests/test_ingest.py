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
from credit_agent.ingest.pdf import parse_pdf, parse_pdf_with_confidence

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
