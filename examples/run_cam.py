"""Demo: produce a full preliminary Credit Approval Memo from the SC workbook."""

from credit_agent.report.cam import build_memo, render_markdown
from credit_agent.spreading.loader import load_sc_workbook

WORKBOOK = "data/raw/Task 1 Example Answer - Financial Reporting Tool.xlsx"


def run_cam() -> None:
    company = load_sc_workbook(WORKBOOK)
    memo = build_memo(company)
    print(render_markdown(memo))


if __name__ == "__main__":
    run_cam()
