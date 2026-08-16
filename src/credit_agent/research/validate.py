"""Validation and grounding.

Every retrieved snippet is judged for relevance, source quality and recency, and
each accepted finding must carry a source URL. Cross-source agreement raises
confidence; conflicts are flagged rather than asserted. The result is a
validation report that tells the analyst exactly how much to trust each claim —
the mechanism that prevents mismatched or unsourced assertions from reaching a
credit memo.
"""

from __future__ import annotations

from pydantic import BaseModel
from urllib.parse import urlparse

HIGH_TIER = (
    ".gov", "edu", "imf.org", "oecd.org", "worldbank.org", "bis.org",
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "economist.com",
    "federalreserve.gov", "ecb.europa.eu", "bankofengland.co.uk", "imf.org",
)
MEDIUM_TIER = (
    "mordorintelligence.com", "grandviewresearch.com", "statista.com",
    "ibisworld.com", "marketresearch.com", "forbes.com", "cnbc.com",
    "britannica.com", "prnewswire.com", "businesswire.com", "nasdaq.com",
)

DIMENSION_KEYWORDS = {
    "demand": ["market", "growth", "cagr", "demand", "size", "forecast", "drinkware", "bottle"],
    "trends": ["trend", "sustainab", "esg", "reusable", "consumer", "eco"],
    "input_costs": ["steel", "alumin", "commodity", "price", "cost", "input", "metal"],
    "competitive": ["competit", "market share", "landscape", "player", "rival", "brand"],
    "macro": ["consumer", "spending", "gdp", "outlook", "economy", "discretionary"],
    "regulation": ["ban", "plastic", "regulat", "policy", "law", "compliance", "single-use"],
    "rates": ["rate", "fed", "interest", "monetary", "central bank", "inflation"],
}


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def classify_source(url: str) -> str:
    dom = _domain(url)
    for h in HIGH_TIER:
        if dom.endswith(h):
            return "high"
    for m in MEDIUM_TIER:
        if dom.endswith(m):
            return "medium"
    return "low"


def _recency_factor(published_date: str | None) -> float:
    if not published_date:
        return 0.85
    import re
    m = re.search(r"(20\d{2})", published_date)
    if not m:
        return 0.85
    year = int(m.group(1))
    from datetime import datetime
    cur = datetime.now().year
    age = cur - year
    if age <= 1:
        return 1.0
    if age == 2:
        return 0.8
    if age == 3:
        return 0.6
    return 0.4


def _tier_score(tier: str) -> float:
    return {"high": 1.0, "medium": 0.75, "low": 0.5}[tier]


class Judgment(BaseModel):
    relevant: bool
    claim: str = ""
    confidence: float = 0.0
    reason: str = ""


def rule_judge(content: str, url: str, dimension: str) -> Judgment:
    text = (content or "").lower()
    kws = DIMENSION_KEYWORDS.get(dimension, [])
    hits = sum(1 for k in kws if k in text)
    relevant = hits >= 2
    tier = classify_source(url)
    recency = _recency_factor(None)
    conf = 0.0
    if relevant:
        conf = round(min(1.0, _tier_score(tier) * 0.7 + min(hits, 5) / 10 + recency * 0.2), 2)
    snippet = (content or "").strip().replace("\n", " ")
    claim = (snippet[:240] + "…") if len(snippet) > 240 else snippet
    return Judgment(relevant=relevant, claim=claim, confidence=conf,
                    reason=f"keyword_hits={hits}, tier={tier}")


def llm_judge(content: str, url: str, dimension: str, complete) -> Judgment:
    prompt = (
        f"You are validating a source for a credit-analysis research dossier.\n"
        f"Research dimension: {dimension}\nSource URL: {url}\nSource text:\n\"\"\"\n{content[:2500]}\n\"\"\"\n\n"
        f"Respond strictly in this format:\n"
        f"RELEVANT: YES|NO\nCONFIDENCE: 0.0-1.0\nCLAIM: <one precise sentence stating the factual claim, including any figure and its date/source>\n"
        f"If not relevant, set RELEVANT: NO and leave CLAIM empty."
    )
    try:
        resp = complete([{"role": "user", "content": prompt}])
        text = resp.strip()
        relevant = "RELEVANT: YES" in text.upper()
        conf = 0.5
        import re
        cm = re.search(r"CONFIDENCE:\s*([0-9.]+)", text)
        if cm:
            conf = max(0.0, min(1.0, float(cm.group(1))))
        claim = ""
        cm2 = re.search(r"CLAIM:\s*(.+)", text, re.DOTALL)
        if cm2:
            claim = cm2.group(1).strip().split("\n")[0]
        return Judgment(relevant=relevant, claim=claim, confidence=round(conf, 2), reason="llm")
    except Exception:
        return rule_judge(content, url, dimension)


class Finding(BaseModel):
    dimension: str
    claim: str
    source_url: str
    source_title: str = ""
    published_date: str | None = None
    confidence: float
    tier: str
    conflict: bool = False


class ValidationReport(BaseModel):
    dimensions_covered: list[str] = []
    dimensions_gaps: list[str] = []
    conflicts: list[str] = []
    low_confidence_count: int = 0
    sources: list[str] = []
    overall_confidence: float = 0.0
    summary: str = ""


def validate_dimension(dimension: str, results, judge) -> list[Finding]:
    findings = []
    for r in results:
        j = judge(r.content, r.url, dimension)
        if not j.relevant or not j.claim:
            continue
        findings.append(Finding(
            dimension=dimension, claim=j.claim, source_url=r.url,
            source_title=r.title, published_date=r.published_date,
            confidence=j.confidence, tier=classify_source(r.url),
        ))
    findings.sort(key=lambda f: f.confidence, reverse=True)
    return findings


def build_validation_report(plan_dims: list[str], findings_by_dim: dict[str, list[Finding]]) -> ValidationReport:
    covered, gaps, conflicts, sources, low = [], [], [], set(), 0
    for dim in plan_dims:
        fs = findings_by_dim.get(dim, [])
        if fs and fs[0].confidence >= 0.5:
            covered.append(dim)
        else:
            gaps.append(dim)
        for f in fs:
            sources.add(f.source_url)
            if f.confidence < 0.5:
                low += 1
        if len(fs) >= 2:
            top = fs[0]
            others = [f for f in fs[1:] if f.source_url != top.source_url]
            if others and _conflicting(top.claim, others[0].claim):
                conflicts.append(dim)
                for f in fs:
                    f.conflict = True
    over = round(sum(f.confidence for fs in findings_by_dim.values() for f in fs) /
                 max(1, sum(len(fs) for fs in findings_by_dim.values())), 2)
    return ValidationReport(
        dimensions_covered=covered, dimensions_gaps=gaps, conflicts=conflicts,
        low_confidence_count=low, sources=sorted(sources),
        overall_confidence=over,
        summary=f"{len(covered)}/{len(plan_dims)} dimensions covered; "
                f"{len(conflicts)} conflict(s); {low} low-confidence finding(s).",
    )


def _conflicting(a: str, b: str) -> bool:
    import re
    nums_a = set(re.findall(r"\d+(?:\.\d+)?%?", a))
    nums_b = set(re.findall(r"\d+(?:\.\d+)?%?", b))
    if nums_a and nums_b and not (nums_a & nums_b):
        return True
    return False
