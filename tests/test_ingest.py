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
from credit_agent.ingest.pdf import parse_pdf

SC = "data/raw/Task 1 Example Answer - Financial Reporting Tool.xlsx"


def test_sc_ingest_two_years():
    res = ingest([{"path": SC, "year": 2023, "entity": "GS"}])
    assert res.entity_name == "GS"
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
    periods, flags = ingest_file(str(path), 2022)
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
    periods, flags = ingest_file(str(path), 2023)
    assert periods[0].period == "2023"
    assert any(f.level == "warning" and "PDF" in f.message for f in flags)
