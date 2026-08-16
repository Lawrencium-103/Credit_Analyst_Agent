"""Research package: search, planning, validation and dossier assembly."""

from .search import MockProvider, SearchProvider, SearchResult, TavilyProvider, get_provider
from .planner import ResearchQuery, build_plan
from .validate import (
    Finding,
    Judgment,
    ValidationReport,
    build_validation_report,
    classify_source,
    llm_judge,
    rule_judge,
    validate_dimension,
)
from .dossier import ResearchDossier, render_dossier_md, run_research

__all__ = [
    "MockProvider", "SearchProvider", "SearchResult", "TavilyProvider", "get_provider",
    "ResearchQuery", "build_plan",
    "Finding", "Judgment", "ValidationReport", "build_validation_report",
    "classify_source", "llm_judge", "rule_judge", "validate_dimension",
    "ResearchDossier", "render_dossier_md", "run_research",
]
