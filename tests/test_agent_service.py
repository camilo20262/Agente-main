from types import SimpleNamespace

import pytest

from src.agent.service import AgentService
from src.agent.service import RepeatedToolCallError
from src.config import Settings


class FakeRegistry:
    schemas = [{"type": "function", "function": {"name": "consultar_inversion_publicitaria", "parameters": {"type": "object"}}}]
    repository = SimpleNamespace(source="mock")
    def execute(self, name, arguments): return {"success": True, "source": "mock", "value": 8.72}


class FakeCompletions:
    def __init__(self): self.calls = 0
    def create(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            function = SimpleNamespace(name="consultar_inversion_publicitaria", arguments='{"filtros":{"marca":"VOLVO"}}')
            message = SimpleNamespace(content=None, tool_calls=[SimpleNamespace(id="call-1", function=function)])
        else:
            assert kwargs["tools"]
            assert any(getattr(m, "tool_calls", None) for m in kwargs["messages"] if not isinstance(m, dict))
            message = SimpleNamespace(content="Volvo registró inversión.", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_agent_iterates_and_keeps_tools_available():
    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    result = AgentService(client=client, settings=Settings(max_agent_steps=3), registry=FakeRegistry()).run([{"role": "user", "content": "inversión"}])
    assert result.answer == "Volvo registró inversión."
    assert result.is_partial is False
    assert result.steps == 2
    assert result.evidence[0]["tool"] == "consultar_inversion_publicitaria"


class RepeatingCompletions:
    def create(self, **kwargs):
        function = SimpleNamespace(name="consultar_inversion_publicitaria", arguments='{"filtros":{"marca":"VOLVO"}}')
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[SimpleNamespace(id="same", function=function)]))])


def test_repeated_identical_tool_call_is_stopped():
    client = SimpleNamespace(chat=SimpleNamespace(completions=RepeatingCompletions()))
    service = AgentService(client=client, settings=Settings(max_agent_steps=3), registry=FakeRegistry())
    try:
        service.run([{"role": "user", "content": "inversión"}])
    except RepeatedToolCallError as exc:
        assert "consultar_inversion_publicitaria" in str(exc)
    else:
        raise AssertionError("Expected repeated call prevention")


class MultiStepCompletions:
    def __init__(self): self.calls = 0
    def create(self, **kwargs):
        self.calls += 1
        if self.calls <= 2:
            function = SimpleNamespace(name="consultar_inversion_publicitaria", arguments='{"filtros":{"marca":"%s"}}' % ("VOLVO" if self.calls == 1 else "RENAULT"))
            message = SimpleNamespace(content=None, tool_calls=[SimpleNamespace(id=f"call-{self.calls}", function=function)])
        else:
            message = SimpleNamespace(content="Comparación terminada.", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_agent_executes_multiple_distinct_steps():
    completions = MultiStepCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    result = AgentService(client=client, settings=Settings(max_agent_steps=4), registry=FakeRegistry()).run([{"role": "user", "content": "inversión"}])
    assert result.steps == 3
    assert [item["arguments"]["filtros"]["marca"] for item in result.evidence] == ["VOLVO", "RENAULT"]


@pytest.mark.parametrize("premature_answer", [False, True])
def test_nvidia_allows_recovery_until_successful_evidence(premature_answer):
    class RecoveringRegistry(FakeRegistry):
        def execute(self, name, arguments):
            if arguments["filtros"]["marca"] == "VOLVO":
                return {"success": False, "error": "Consulta fallida"}
            return super().execute(name, arguments)

    class RecoveringCompletions:
        def __init__(self):
            self.choices = []

        def create(self, **kwargs):
            self.choices.append(kwargs["tool_choice"])
            step = len(self.choices)
            recovery_step = 3 if premature_answer else 2
            if step == 1 or step == recovery_step:
                if step == recovery_step:
                    assert kwargs["tool_choice"] == "auto"
                    if premature_answer:
                        assert any(isinstance(item, dict) and "El plan requiere evidencia cuantitativa" in item.get("content", "")
                                   for item in kwargs["messages"])
                brand = "VOLVO" if step == 1 else "RENAULT"
                function = SimpleNamespace(name="consultar_inversion_publicitaria",
                    arguments='{"filtros":{"marca":"%s"}}' % brand)
                message = SimpleNamespace(content=None, tool_calls=[SimpleNamespace(id=f"call-{step}", function=function)])
            else:
                message = SimpleNamespace(content="Sin datos." if step < recovery_step else "Inversión: 8.72.", tool_calls=[])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    completions = RecoveringCompletions()
    client = SimpleNamespace(base_url="https://integrate.api.nvidia.com/v1", chat=SimpleNamespace(completions=completions))
    result = AgentService(client=client, settings=Settings(max_agent_steps=4), registry=RecoveringRegistry()).run(
        [{"role": "user", "content": "inversión"}])
    forced_tool = {"type": "function", "function": {"name": "consultar_inversion_publicitaria"}}
    assert completions.choices == [forced_tool] + ["auto"] * (2 if premature_answer else 1) + ["none"]
    assert result.answer == "Inversión: 8.72."
    assert [item["result"]["success"] for item in result.evidence] == [False, True]
    assert result.evidence[1]["result"]["value"] == 8.72


@pytest.mark.parametrize("content,expected", [
    ("inversión por región", "inversión por región"),
    ([{"type": "text", "text": "inversión por región"},
      {"type": "image_url", "image_url": {"url": "https://example.invalid/image.png"}}], "inversión por región"),
    ([{"type": "text", "text": "inversión"},
      {"type": "image_url", "image_url": {"url": "https://example.invalid/image.png"}},
      {"type": "text", "text": "por región"}], "inversión por región"),
    ([{"type": "image_url", "image_url": {"url": "https://example.invalid/image.png"}}], ""),
    ([None, "ignored", {"type": "text", "text": 123}, {"type": "text"},
      {"type": "text", "text": ""}, {"type": "other", "text": "inversión"}], ""),
    ([], ""),
    (None, ""),
    ({"text": "inversión"}, ""),
    ("", ""),
])
def test_planner_uses_latest_user_text_and_preserves_content(monkeypatch, content, expected):
    from copy import deepcopy

    class DimensionRegistry(FakeRegistry):
        schemas = [{"type": "function", "function": {"name": "ranking_por_dimension", "parameters": {"type": "object"}}}]

    latest_message = {"role": "user", "content": content}
    messages = [{"role": "user", "content": "inversión anterior"}, latest_message,
                {"role": "assistant", "content": "Mensaje posterior que no es del usuario."}]
    original_messages = deepcopy(messages)

    class DimensionCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            users = [item for item in kwargs["messages"] if isinstance(item, dict) and item.get("role") == "user"]
            assert users[-1] is latest_message
            assert users[-1]["content"] == original_messages[1]["content"]
            if expected and self.calls == 1:
                assert kwargs["tool_choice"] == {"type": "function", "function": {"name": "ranking_por_dimension"}}
                function = SimpleNamespace(name="ranking_por_dimension", arguments='{"dimension":"region"}')
                message = SimpleNamespace(content=None, tool_calls=[SimpleNamespace(id="ranking", function=function)])
            else:
                message = SimpleNamespace(content="Respuesta final.", tool_calls=[])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client = SimpleNamespace(chat=SimpleNamespace(completions=DimensionCompletions()))
    service = AgentService(client=client, settings=Settings(max_agent_steps=3), registry=DimensionRegistry())
    original_plan = service.planner.plan
    questions = []

    def capture_plan(question, memory):
        questions.append(question)
        return original_plan(question, memory)

    monkeypatch.setattr(service.planner, "plan", capture_plan)
    result = service.run(messages)
    assert questions == [expected]
    assert messages == original_messages
    if expected:
        assert result.plan["domains"] == ["bicomp"]
        assert result.plan["intent"] == "dimension_breakdown"
        assert result.plan["steps"][0]["tool"] == "ranking_por_dimension"
    else:
        assert result.plan["intent"] == "out_of_domain"
        assert result.plan["steps"] == []


@pytest.mark.parametrize("successful_step", [1, 2])
def test_max_steps_returns_partial_evidence_without_extra_llm_call(successful_step):
    class PartialRegistry(FakeRegistry):
        def __init__(self):
            self.calls = 0

        def execute(self, name, arguments):
            self.calls += 1
            if self.calls != successful_step:
                return {"success": False, "error": "No se pudo obtener el segundo dato", "value": 999}
            return {"success": True, "source": "mock", "metric": "inv_neta", "value": 0,
                    "filters": arguments["filtros"]}

    completions = MultiStepCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    result = AgentService(client=client, settings=Settings(max_agent_steps=2), registry=PartialRegistry()).run(
        [{"role": "user", "content": "inversión"}])
    assert result.is_partial is True
    assert result.steps == 2
    assert completions.calls == 2
    assert "No pude completar el análisis" in result.answer
    assert "consultar_inversion_publicitaria" in result.answer
    assert '"metric": "inv_neta"' in result.answer
    assert '"value": 0' in result.answer
    assert ("VOLVO" if successful_step == 1 else "RENAULT") in result.answer
    assert "999" not in result.answer
    assert len(result.evidence) == 2
    assert result.metrics["errors"][-1] == "max_steps"
    assert result.metrics["total_llm_calls"] == 2
    assert result.plan["domains"] == ["bicomp"]


def test_max_steps_preserves_ranking_chart_and_limits_summary_rows():
    from src.tools.registry import RegisteredTool, ToolRegistry

    rows = [{"dimension": f"REGION_{i}", "value": i} for i in range(7)]
    registry = ToolRegistry(SimpleNamespace(source="mock"))
    registry._tools["ranking_por_dimension"] = RegisteredTool(
        "ranking_por_dimension", "Ranking", {"type": "object"},
        lambda arguments: {"success": True, "metric": "inv_neta", "dimension": "region", "rows": rows})

    class RankingCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            assert self.calls == 1
            function = SimpleNamespace(name="ranking_por_dimension", arguments='{"dimension":"region"}')
            message = SimpleNamespace(content=None, tool_calls=[SimpleNamespace(id="ranking", function=function)])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    completions = RankingCompletions()
    service = AgentService(client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
                           settings=Settings(max_agent_steps=1), registry=registry)
    result = service.run([{"role": "user", "content": "inversión por región"}])
    assert result.is_partial is True
    assert '"dimension": "region"' in result.answer
    assert "REGION_4" in result.answer
    assert "REGION_5" not in result.answer
    assert "Muestra de 5 de 7" in result.answer
    assert result.evidence[0]["result"]["rows"] == rows
    assert result.chart_specs[0]["data"] == rows


def test_max_steps_without_success_still_raises():
    from src.agent.service import AgentMaxStepsError

    class FailingRegistry(FakeRegistry):
        def execute(self, name, arguments):
            return {"success": False, "error": "Consulta fallida"}

    completions = MultiStepCompletions()
    service = AgentService(client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
                           settings=Settings(max_agent_steps=2), registry=FailingRegistry())
    with pytest.raises(AgentMaxStepsError):
        service.run([{"role": "user", "content": "inversión"}])
    assert completions.calls == 2
    assert service.metrics.errors[-1] == "max_steps"
