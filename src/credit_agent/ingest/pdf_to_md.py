"""PDF → Markdown converter.

Uses pymupdf4llm to convert PDFs to Markdown, preserving table structure.
This gives us a clean intermediate representation that is easier to parse
than raw PDF text — Markdown tables are structured and predictable.
"""

from __future__ import annotations

import pymupdf4llm
import pymupdf


def pdf_to_markdown(path: str) -> str:
    """Convert a PDF file to Markdown text.

    Returns Markdown with tables preserved as pipe-delimited rows.
    Falls back to basic text extraction if pymupdf4llm fails.
    """
    try:
        md = pymupdf4llm.to_markdown(path)
        if md and md.strip():
            return md
    except Exception:
        pass

    # Fallback: basic text extraction via PyMuPDF
    doc = pymupdf.open(path)
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    return text


def parse_markdown_tables(md: str) -> list[list[list[str]]]:
    """Extract all Markdown tables as lists of rows, each row a list of cell strings.

    Returns a list of tables. Each table is a list of rows.
    Each row is a list of stripped cell values.
    """
    tables: list[list[list[str]]] = []
    current_table: list[list[str]] = []

    for line in md.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            # Check if separator row (e.g. |---|---|---|)
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if all(set(c) <= set("-: ") for c in cells):
                # Separator row — skip but mark that we're in a table
                continue
            current_table.append(cells)
        else:
            if current_table and len(current_table) >= 2:
                tables.append(current_table)
            current_table = []

    if current_table and len(current_table) >= 2:
        tables.append(current_table)

    return tables


def find_financial_table(md: str) -> list[list[str]] | None:
    """Find the most likely financial data table in a Markdown document.

    Heuristic: the table with the most numeric-looking cells.
    """
    tables = parse_markdown_tables(md)
    if not tables:
        return None

    def numeric_ratio(table: list[list[str]]) -> float:
        total, numeric = 0, 0
        for row in table:
            for cell in row[1:]:  # skip label column
                total += 1
                cleaned = cell.replace(",", "").replace("(", "").replace(")", "").replace("$", "").replace("%", "").strip()
                try:
                    float(cleaned)
                    numeric += 1
                except ValueError:
                    pass
        return numeric / max(total, 1)

    return max(tables, key=numeric_ratio)


def extract_line_items_from_table(table: list[list[str]]) -> dict[str, float | None]:
    """Extract line item → value mappings from a Markdown table.

    Assumes first column is labels and subsequent columns are values.
    Uses the last value column (most recent period).
    """
    if not table or len(table[0]) < 2:
        return {}

    result: dict[str, float | None] = {}
    for row in table:
        label = row[0].strip().lower()
        if not label:
            continue
        # Use the last value column (most recent period)
        raw = row[-1].strip()
        cleaned = raw.replace(",", "").replace("(", "-").replace(")", "").replace("$", "").replace("%", "").strip()
        try:
            result[label] = float(cleaned)
        except ValueError:
            result[label] = None

    return result
