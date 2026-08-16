"""Illustrative multi-year financials for Green Solutions Manufacturing Ltd.

These figures are synthetic but internally consistent, intended for exercising
the analysis engine and as a placeholder until the real simulation statements
are supplied. All values are in USD millions.
"""

from credit_agent.schema.financials import (
    BalanceSheet,
    CashFlow,
    CompanyFinancials,
    IncomeStatement,
    PeriodFinancials,
)

GREEN_SOLUTIONS = CompanyFinancials(
    entity_name="Green Solutions Manufacturing Ltd",
    currency="USD",
    periods=[
        PeriodFinancials(
            period="FY2021",
            income_statement=IncomeStatement(
                revenue=180.0, cogs=108.0, gross_profit=72.0, operating_expenses=36.0,
                ebitda=42.0, depreciation_amortization=12.0, ebit=30.0,
                interest_expense=6.0, pretax_income=24.0, tax_expense=6.0, net_income=18.0,
            ),
            balance_sheet=BalanceSheet(
                cash_and_equivalents=20.0, accounts_receivable=28.0, inventory=34.0,
                current_assets=95.0, total_assets=210.0, accounts_payable=22.0,
                current_liabilities=60.0, total_liabilities=120.0, short_term_debt=15.0,
                long_term_debt=55.0, total_debt=70.0, total_equity=90.0, retained_earnings=48.0,
            ),
            cash_flow=CashFlow(
                operating_cash_flow=38.0, capital_expenditures=18.0, free_cash_flow=20.0,
                investing_cash_flow=-19.0, financing_cash_flow=-8.0, dividends_paid=4.0,
            ),
        ),
        PeriodFinancials(
            period="FY2022",
            income_statement=IncomeStatement(
                revenue=216.0, cogs=126.0, gross_profit=90.0, operating_expenses=42.0,
                ebitda=52.0, depreciation_amortization=14.0, ebit=38.0,
                interest_expense=7.0, pretax_income=31.0, tax_expense=8.0, net_income=23.0,
            ),
            balance_sheet=BalanceSheet(
                cash_and_equivalents=24.0, accounts_receivable=33.0, inventory=40.0,
                current_assets=112.0, total_assets=250.0, accounts_payable=26.0,
                current_liabilities=70.0, total_liabilities=140.0, short_term_debt=18.0,
                long_term_debt=62.0, total_debt=80.0, total_equity=110.0, retained_earnings=71.0,
            ),
            cash_flow=CashFlow(
                operating_cash_flow=46.0, capital_expenditures=22.0, free_cash_flow=24.0,
                investing_cash_flow=-24.0, financing_cash_flow=-6.0, dividends_paid=5.0,
            ),
        ),
        PeriodFinancials(
            period="FY2023",
            income_statement=IncomeStatement(
                revenue=250.0, cogs=143.0, gross_profit=107.0, operating_expenses=48.0,
                ebitda=62.0, depreciation_amortization=16.0, ebit=46.0,
                interest_expense=8.0, pretax_income=38.0, tax_expense=10.0, net_income=28.0,
            ),
            balance_sheet=BalanceSheet(
                cash_and_equivalents=30.0, accounts_receivable=38.0, inventory=46.0,
                current_assets=130.0, total_assets=295.0, accounts_payable=30.0,
                current_liabilities=82.0, total_liabilities=165.0, short_term_debt=20.0,
                long_term_debt=75.0, total_debt=95.0, total_equity=130.0, retained_earnings=99.0,
            ),
            cash_flow=CashFlow(
                operating_cash_flow=55.0, capital_expenditures=26.0, free_cash_flow=29.0,
                investing_cash_flow=-30.0, financing_cash_flow=-8.0, dividends_paid=6.0,
            ),
        ),
    ],
)
