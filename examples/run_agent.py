"""Demo: run the LLM credit agent over the SC workbook and produce an enriched memo."""

import sys
from pathlib import Path

from credit_agent.agent.orchestrator import CreditAgent, render_assessment
from credit_agent.report.cam import build_memo, render_markdown
from credit_agent.spreading.loader import load_sc_workbook

WORKBOOK = "data/raw/Task 1 Example Answer - Financial Reporting Tool.xlsx"
OUT_DIR = Path("output")


def run_agent() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    company = load_sc_workbook(WORKBOOK)
    base_memo = build_memo(company)
    base_md = render_markdown(base_memo)

    agent = CreditAgent()
    output = agent.analyze(WORKBOOK)
    assessment_md = render_assessment(output)

    full = base_md + "\n\n" + "=" * 70 + "\n\n" + assessment_md
    (OUT_DIR / "credit_memo.md").write_text(full, encoding="utf-8")

    # Print safely (avoid Windows console codec crashes on glyphs like >=).
    try:
        print(full)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(full.encode("utf-8", "replace") + b"\n")
    print(f"\n[written] {OUT_DIR / 'credit_memo.md'}")


if __name__ == "__main__":
    run_agent()
