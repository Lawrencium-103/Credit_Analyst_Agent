"""Ratio and risk-rating definitions with interpretation metadata.

This module is the analytical "knowledge base" the agent reasons over. Each
ratio carries its formula, direction of favour, and a healthy reference band so
that downstream narrative generation can explain *why* a value matters.
"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel


class RatioCategory(str, Enum):
    LIQUIDITY = "liquidity"
    LEVERAGE = "leverage"
    COVERAGE = "coverage"
    PROFITABILITY = "profitability"
    EFFICIENCY = "efficiency"
    SOLVENCY = "solvency"


class Direction(str, Enum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class RatioDefinition(BaseModel):
    key: str
    label: str
    category: RatioCategory
    formula: str
    direction: Direction
    healthy_min: float | None = None
    healthy_max: float | None = None
    unit: str = "x"
    description: str = ""


RATIO_DEFINITIONS: dict[str, RatioDefinition] = {
    "current_ratio": RatioDefinition(
        key="current_ratio", label="Current Ratio", category=RatioCategory.LIQUIDITY,
        formula="current_assets / current_liabilities", direction=Direction.HIGHER_IS_BETTER,
        healthy_min=1.5, healthy_max=3.0,
        description="Ability to cover short-term obligations with short-term assets.",
    ),
    "quick_ratio": RatioDefinition(
        key="quick_ratio", label="Quick Ratio", category=RatioCategory.LIQUIDITY,
        formula="(current_assets - inventory) / current_liabilities", direction=Direction.HIGHER_IS_BETTER,
        healthy_min=1.0,
        description="Liquidity excluding slower-moving inventory.",
    ),
    "cash_ratio": RatioDefinition(
        key="cash_ratio", label="Cash Ratio", category=RatioCategory.LIQUIDITY,
        formula="(cash_and_equivalents + marketable_securities) / current_liabilities",
        direction=Direction.HIGHER_IS_BETTER, healthy_min=0.2,
        description="Most conservative liquidity measure.",
    ),
    "debt_to_equity": RatioDefinition(
        key="debt_to_equity", label="Debt / Equity", category=RatioCategory.LEVERAGE,
        formula="total_debt / total_equity", direction=Direction.LOWER_IS_BETTER,
        healthy_max=2.0,
        description="Capital structure leverage relative to shareholder funds.",
    ),
    "debt_to_assets": RatioDefinition(
        key="debt_to_assets", label="Debt / Assets", category=RatioCategory.LEVERAGE,
        formula="total_debt / total_assets", direction=Direction.LOWER_IS_BETTER,
        healthy_max=0.6,
        description="Share of assets financed by debt.",
    ),
    "equity_ratio": RatioDefinition(
        key="equity_ratio", label="Equity Ratio", category=RatioCategory.SOLVENCY,
        formula="total_equity / total_assets", direction=Direction.HIGHER_IS_BETTER,
        healthy_min=0.4,
        description="Loss-absorption capacity of equity.",
    ),
    "interest_coverage": RatioDefinition(
        key="interest_coverage", label="Interest Coverage (EBIT)", category=RatioCategory.COVERAGE,
        formula="ebit / interest_expense", direction=Direction.HIGHER_IS_BETTER,
        healthy_min=3.0,
        description="Earnings available to service interest.",
    ),
    "ebitda_interest_coverage": RatioDefinition(
        key="ebitda_interest_coverage", label="EBITDA Interest Coverage", category=RatioCategory.COVERAGE,
        formula="ebitda / interest_expense", direction=Direction.HIGHER_IS_BETTER,
        healthy_min=4.0,
        description="Cash-based ability to service interest.",
    ),
    "gross_margin": RatioDefinition(
        key="gross_margin", label="Gross Margin", category=RatioCategory.PROFITABILITY,
        formula="gross_profit / revenue", direction=Direction.HIGHER_IS_BETTER,
        unit="%", description="Core production profitability.",
    ),
    "operating_margin": RatioDefinition(
        key="operating_margin", label="Operating Margin", category=RatioCategory.PROFITABILITY,
        formula="ebit / revenue", direction=Direction.HIGHER_IS_BETTER, unit="%",
        description="Profitability before financing and tax.",
    ),
    "net_margin": RatioDefinition(
        key="net_margin", label="Net Margin", category=RatioCategory.PROFITABILITY,
        formula="net_income / revenue", direction=Direction.HIGHER_IS_BETTER, unit="%",
        description="Bottom-line profitability.",
    ),
    "ebitda_margin": RatioDefinition(
        key="ebitda_margin", label="EBITDA Margin", category=RatioCategory.PROFITABILITY,
        formula="ebitda / revenue", direction=Direction.HIGHER_IS_BETTER, unit="%",
        description="Cash-generating profitability.",
    ),
    "return_on_assets": RatioDefinition(
        key="return_on_assets", label="Return on Assets", category=RatioCategory.PROFITABILITY,
        formula="net_income / total_assets", direction=Direction.HIGHER_IS_BETTER, unit="%",
        description="Efficiency of asset use.",
    ),
    "return_on_equity": RatioDefinition(
        key="return_on_equity", label="Return on Equity", category=RatioCategory.PROFITABILITY,
        formula="net_income / total_equity", direction=Direction.HIGHER_IS_BETTER, unit="%",
        description="Return generated for shareholders.",
    ),
    "asset_turnover": RatioDefinition(
        key="asset_turnover", label="Asset Turnover", category=RatioCategory.EFFICIENCY,
        formula="revenue / total_assets", direction=Direction.HIGHER_IS_BETTER,
        healthy_min=0.5,
        description="Revenue generated per unit of assets.",
    ),
    "inventory_turnover": RatioDefinition(
        key="inventory_turnover", label="Inventory Turnover", category=RatioCategory.EFFICIENCY,
        formula="cogs / inventory", direction=Direction.HIGHER_IS_BETTER,
        healthy_min=4.0,
        description="Speed of converting inventory to sales.",
    ),
    "receivables_turnover": RatioDefinition(
        key="receivables_turnover", label="Receivables Turnover", category=RatioCategory.EFFICIENCY,
        formula="revenue / accounts_receivable", direction=Direction.HIGHER_IS_BETTER,
        healthy_min=6.0,
        description="Efficiency of collections.",
    ),
    "days_sales_outstanding": RatioDefinition(
        key="days_sales_outstanding", label="Days Sales Outstanding", category=RatioCategory.EFFICIENCY,
        formula="365 / receivables_turnover", direction=Direction.LOWER_IS_BETTER, unit="days",
        healthy_max=60,
        description="Average collection period.",
    ),
    "days_inventory_outstanding": RatioDefinition(
        key="days_inventory_outstanding", label="Days Inventory Outstanding", category=RatioCategory.EFFICIENCY,
        formula="365 / inventory_turnover", direction=Direction.LOWER_IS_BETTER, unit="days",
        healthy_max=90,
        description="Average time inventory is held.",
    ),
    "cash_conversion_cycle": RatioDefinition(
        key="cash_conversion_cycle", label="Cash Conversion Cycle", category=RatioCategory.EFFICIENCY,
        formula="dso + dio - dpo", direction=Direction.LOWER_IS_BETTER, unit="days",
        healthy_max=60,
        description="Net days cash is tied up in operations.",
    ),
    "free_cash_flow_margin": RatioDefinition(
        key="free_cash_flow_margin", label="FCF Margin", category=RatioCategory.PROFITABILITY,
        formula="free_cash_flow / revenue", direction=Direction.HIGHER_IS_BETTER, unit="%",
        healthy_min=0.05,
        description="Discretionary cash generated after capex.",
    ),
    "operating_cash_flow_ratio": RatioDefinition(
        key="operating_cash_flow_ratio", label="Operating Cash Flow / Current Liabilities",
        category=RatioCategory.LIQUIDITY,
        formula="operating_cash_flow / current_liabilities", direction=Direction.HIGHER_IS_BETTER,
        healthy_min=0.4, description="Cash generation versus short-term obligations.",
    ),
    "ebitda_net_interest_cover": RatioDefinition(
        key="ebitda_net_interest_cover", label="EBITDA Net Interest Cover", category=RatioCategory.COVERAGE,
        formula="ebitda / net_interest_expense", direction=Direction.HIGHER_IS_BETTER,
        healthy_min=3.0,
        description="EBITDA divided by net interest expense (interest exp minus interest income).",
    ),
    "leverage_metric": RatioDefinition(
        key="leverage_metric", label="Leverage Metric (Debt/EBITDA)", category=RatioCategory.LEVERAGE,
        formula="total_debt / ebitda", direction=Direction.LOWER_IS_BETTER,
        healthy_max=4.0,
        description="Total debt relative to EBITDA, the headline leverage gauge.",
    ),
    "net_leverage": RatioDefinition(
        key="net_leverage", label="Net Leverage ((Debt-Cash)/EBITDA)", category=RatioCategory.LEVERAGE,
        formula="(total_debt - cash - marketable_securities) / ebitda", direction=Direction.LOWER_IS_BETTER,
        healthy_max=3.0,
        description="Leverage net of surplus cash and marketable securities.",
    ),
    "cf_to_capex": RatioDefinition(
        key="cf_to_capex", label="CF/CapEx", category=RatioCategory.EFFICIENCY,
        formula="operating_cash_flow / capital_expenditures", direction=Direction.HIGHER_IS_BETTER,
        healthy_min=1.0,
        description="Operating cash generated per unit of capital expenditure.",
    ),
}
