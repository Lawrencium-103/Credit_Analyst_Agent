import json
from types import SimpleNamespace

from credit_agent.agent.orchestrator import CreditAgent, render_assessment
from credit_agent.agent.tools import analysis_bundle

WORKBOOK = "data/raw/Task 1 Example Answer - Financial Reporting Tool.xlsx"


def test_bundle_is_serializable():
    bundle = analysis_bundle(WORKBOOK)
    assert bundle["entity_name"] == "Green Solutions Manufacturing Ltd"
    assert bundle["risk_rating"]["band"]
    text = json.dumps(bundle, default=str)
    assert "ratios" in text


class _FakeToolCall:
    def __init__(self, name, args, tid):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(args))
        self.id = tid

    def model_dump(self):
        return {"id": self.id, "type": "function",
                "function": {"name": self.function.name, "arguments": self.function.arguments}}


class _FakeMessage:
    def __init__(self, content, tool_calls):
        self.content = content
        self.tool_calls = tool_calls


class _FakeClient:
    def __init__(self, scripted):
        self._scripted = scripted
        self._i = 0
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs):
        msg = self._scripted[self._i]
        self._i += 1
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_agent_loop_with_mock():
    assessment = {
        "executive_summary": "Strong credit profile.",
        "credit_strengths": ["EBITDA margin 10.3% in FY2023"],
        "key_risks": ["Capex intensity"],
        "industry_considerations": ["ESG demand tailwinds"],
        "management_assessment": "Capable management.",
        "recommendation": "APPROVE.",
        "conditions": ["Quarterly monitoring"],
    }
    scripted = [
        _FakeMessage(None, [
            _FakeToolCall("run_credit_analysis", {"path": WORKBOOK}, "c1"),
            _FakeToolCall("submit_assessment", assessment, "c2"),
        ])
    ]
    agent = CreditAgent(client=_FakeClient(scripted), model="mock")
    out = agent.analyze(WORKBOOK)
    assert out["assessment"]["recommendation"] == "APPROVE."
    rendered = render_assessment(out)
    assert "Strengths" in rendered
    assert "EBITDA margin 10.3%" in rendered
