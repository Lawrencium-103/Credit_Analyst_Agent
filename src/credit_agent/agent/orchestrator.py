"""Agent orchestration layer.

A tool-calling loop where the LLM (Groq) acts as the credit analyst. It never
computes numbers itself — it calls read-only tools backed by the deterministic
engine, then submits a structured, citation-grounded credit assessment. The loop
is provider-agnostic: any OpenAI-compatible `client` works, which makes the
agent testable with a mock.
"""

from __future__ import annotations

import json
from typing import Any

from .llm import DEFAULT_MODEL, get_client
from .tools import analysis_bundle, stress_bundle
from ..research.dossier import render_dossier_md, run_research
from ..research.search import get_provider

SYSTEM_PROMPT = """You are a Senior Credit Analyst in the Banking & Coverage team at \
Standard Chartered completing the annual credit review of a client.

MANDATORY WORKFLOW (follow exactly):
1. Call run_credit_analysis(path) to retrieve the verified ratios, risk rating, \
KPI trends and covenant results.
2. Call get_stress_scenarios(path) to retrieve the downside stress tests.
3. Call conduct_industry_research(client_name) to retrieve validated, sourced sector/macro research.
4. Only after ALL three tools have returned, call submit_assessment with your write-up.

RULES:
- You NEVER compute or estimate figures. Every number you cite MUST appear in a \
tool result. Do NOT invent percentages, amounts, or scenarios.
- When referencing stress, cite the exact scenario name from get_stress_scenarios \
(e.g. "Combined downturn drives the rating to AA and breaches the leverage covenant") \
and only the figures it reports.
- For the industry section, rely ONLY on conduct_industry_research output and cite the \
provided sources. Do not invent macro/sector facts.
- If conduct_industry_research returns status 'live_research_unavailable', you MUST NOT \
state any specific market sizes, growth rates, commodity prices or macro statistics. \
Follow its 'constraint' instruction verbatim and withhold all sector metrics.
- Be balanced and candid: genuine strengths AND real risks / watch items.
- Write in a professional analyst voice for a credit committee memo.
- Choose a clear recommendation (APPROVE / APPROVE WITH CONDITIONS / DECLINE) and \
list concrete conditions precedent or monitoring."""


def _tool_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "run_credit_analysis",
                "description": "Run the full deterministic credit analysis on the client workbook: ratios, risk rating, KPI trends, covenant compliance. Returns verified figures only.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the workbook."},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_stress_scenarios",
                "description": "Retrieve downside stress-test results (demand, rates, combined, severe) with rating migration and covenant breaches.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the workbook."},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "conduct_industry_research",
                "description": "Run validated, sourced industry & macro research for the client's sector (demand, input costs, competition, regulation, rates). Returns a cited dossier with a validation/confidence report.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "client_name": {"type": "string"},
                        "sector": {"type": "string", "description": "Optional sector override."},
                    },
                    "required": ["client_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit_assessment",
                "description": "Submit the final structured credit assessment. Call this once all needed analysis is gathered.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "executive_summary": {"type": "string", "description": "2-4 sentence overview of creditworthiness and recommendation."},
                        "credit_strengths": {"type": "array", "items": {"type": "string"}, "description": "Bullet-style strengths, each citing a figure."},
                        "key_risks": {"type": "array", "items": {"type": "string"}, "description": "Bullet-style risks / watch items, each citing a figure."},
                        "industry_considerations": {"type": "array", "items": {"type": "string"}},
                        "management_assessment": {"type": "string", "description": "Qualitative view on management and business model."},
                        "recommendation": {"type": "string", "description": "Clear APPROVE / APPROVE WITH CONDITIONS / DECLINE stance with rationale."},
                        "conditions": {"type": "array", "items": {"type": "string"}, "description": "Conditions precedent / monitoring requirements if applicable."},
                    },
                    "required": [
                        "executive_summary", "credit_strengths", "key_risks",
                        "industry_considerations", "management_assessment",
                        "recommendation", "conditions",
                    ],
                },
            },
        },
    ]


class CreditAgent:
    def __init__(self, client=None, model: str = DEFAULT_MODEL, api_key: str | None = None):
        self.client = client or get_client(api_key)
        self.model = model
        self.tools = _tool_schemas()
        self.max_iterations = 6

    def _complete(self, messages: list[dict]) -> Any:
        import time
        last_err = None
        for attempt in range(3):
            try:
                return self.client.chat.completions.create(
                    model=self.model, messages=messages, tools=self.tools,
                    tool_choice="auto", parallel_tool_calls=False,
                )
            except Exception as e:  # Groq occasionally emits a legacy tool tag and 400s; retry
                last_err = e
                time.sleep(1.0 * (attempt + 1))
        raise last_err

    def _llm_text(self, messages: list[dict]) -> str:
        resp = self.client.chat.completions.create(model=self.model, messages=messages)
        return (resp.choices[0].message.content or "").strip()

    def _dispatch(self, name: str, args: dict, path: str) -> dict:
        if name == "run_credit_analysis":
            return analysis_bundle(args.get("path", path))
        if name == "get_stress_scenarios":
            return stress_bundle(args.get("path", path))
        if name == "conduct_industry_research":
            return self._research(args.get("client_name", ""), args.get("sector"))
        if name == "submit_assessment":
            for k in ("credit_strengths", "key_risks", "industry_considerations", "conditions"):
                if k in args:
                    args[k] = _as_list(args[k])
            return args
        return {"error": f"unknown tool {name}"}

    def _research(self, client_name: str, sector: str | None, use_llm_judge: bool = False) -> dict:
        try:
            provider = get_provider("tavily")
        except RuntimeError:
            provider = None
        if provider is None:
            from ..research.planner import build_plan
            plan = build_plan(sector)
            return {
                "status": "live_research_unavailable",
                "constraint": (
                    "Live web research was NOT executed in this session. You MUST NOT state any "
                    "specific market sizes, CAGR/growth rates, commodity prices, competitor shares "
                    "or macro statistics. Write the Industry Considerations section exactly as: "
                    "'Sector and macro research was not run in this session (no search API "
                    "configured); specific industry metrics are withheld to avoid unsourced "
                    "claims. The recommendation therefore rests on the quantitative financial "
                    "analysis and stress tests alone.' Do not add any numeric sector claims."
                ),
                "planned_queries": [q.query for q in plan],
            }
        dossier = run_research(
            client_name, sector, provider=provider,
            llm_complete=self._llm_text if use_llm_judge else None,
        )
        return {"dossier_markdown": render_dossier_md(dossier), "report": dossier.report.model_dump()}

    def analyze(self, path: str) -> dict:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Complete the credit assessment for the client in the workbook at '{path}'. "
                f"Use the tools to gather verified analysis, then submit your assessment."
            )},
        ]
        for _ in range(self.max_iterations):
            resp = self._complete(messages)
            msg = resp.choices[0].message
            if not msg.tool_calls:
                messages.append({"role": "assistant", "content": msg.content or ""})
                continue
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            })
            for tc in msg.tool_calls:
                args = json.loads(tc.function.arguments)
                result = self._dispatch(tc.function.name, args, path)
                if tc.function.name == "submit_assessment":
                    return {"assessment": result, "messages": messages}
                messages.append({
                    "role": "tool", "tool_call_id": tc.id,
                    "content": json.dumps(result, default=str),
                })
        return {"assessment": {"error": "agent did not submit an assessment"}, "messages": messages}


def _as_list(v) -> list:
    """Coerce model outputs to a list.

    Some LLM providers return a JSON array as a *string* (e.g. '["a", "b"]')
    rather than a native array. Iterating that string would yield one
    character per bullet, so we parse it back into a list here.
    """
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("["):
            try:
                import json

                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except Exception:
                pass
        return [s] if s else []
    return [str(v)]


def render_assessment(agent_output: dict) -> str:
    a = agent_output.get("assessment", {})
    if "error" in a:
        return f"[Agent error] {a['error']}"
    lines = []
    lines.append("## Analyst Assessment (LLM)")
    lines.append("")
    lines.append(a.get("executive_summary", ""))
    lines.append("")
    lines.append("### Strengths")
    for s in _as_list(a.get("credit_strengths")):
        lines.append(f"- {s}")
    lines.append("")
    lines.append("### Key Risks / Watch Items")
    for r in _as_list(a.get("key_risks")):
        lines.append(f"- {r}")
    lines.append("")
    lines.append("### Industry Considerations")
    for i in _as_list(a.get("industry_considerations")):
        lines.append(f"- {i}")
    lines.append("")
    lines.append("### Management & Business Model")
    lines.append(a.get("management_assessment", ""))
    lines.append("")
    lines.append("### Recommendation")
    lines.append(a.get("recommendation", ""))
    if _as_list(a.get("conditions")):
        lines.append("")
        lines.append("**Conditions / Monitoring:**")
        for c in _as_list(a.get("conditions")):
            lines.append(f"- {c}")
    lines.append("")
    return "\n".join(lines)
