"""Canonical, accounting-standard-agnostic financial schema.

All monetary values are stored as floats in the reporting currency. `None`
represents a line item that was not disclosed. The schema intentionally uses
generic line items so that statements prepared under IFRS, US GAAP or local
GAAP can be normalised into a single representation before analysis.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class IncomeStatement(BaseModel):
    revenue: float | None = None
    cogs: float | None = None
    gross_profit: float | None = None
    operating_expenses: float | None = None
    ebitda: float | None = None
    depreciation_amortization: float | None = None
    ebit: float | None = None
    interest_expense: float | None = None
    interest_income: float | None = None
    pretax_income: float | None = None
    tax_expense: float | None = None
    net_income: float | None = None


class BalanceSheet(BaseModel):
    cash_and_equivalents: float | None = None
    marketable_securities: float | None = None
    accounts_receivable: float | None = None
    inventory: float | None = None
    current_assets: float | None = None
    total_assets: float | None = None
    accounts_payable: float | None = None
    current_liabilities: float | None = None
    total_liabilities: float | None = None
    short_term_debt: float | None = None
    long_term_debt: float | None = None
    total_debt: float | None = None
    total_equity: float | None = None
    retained_earnings: float | None = None


class CashFlow(BaseModel):
    operating_cash_flow: float | None = None
    capital_expenditures: float | None = None
    free_cash_flow: float | None = None
    investing_cash_flow: float | None = None
    financing_cash_flow: float | None = None
    dividends_paid: float | None = None


class PeriodFinancials(BaseModel):
    period: str = Field(..., description="Reporting period label, e.g. 'FY2023' or '2023-12-31'.")
    currency: str | None = None
    income_statement: IncomeStatement = IncomeStatement()
    balance_sheet: BalanceSheet = BalanceSheet()
    cash_flow: CashFlow = CashFlow()


class CompanyFinancials(BaseModel):
    entity_name: str
    currency: str | None = None
    periods: list[PeriodFinancials] = Field(default_factory=list)

    def by_period(self, period: str) -> PeriodFinancials | None:
        for p in self.periods:
            if p.period == period:
                return p
        return None

    def latest(self) -> PeriodFinancials | None:
        return self.periods[-1] if self.periods else None

    def prior(self) -> PeriodFinancials | None:
        return self.periods[-2] if len(self.periods) >= 2 else None
