from types import SimpleNamespace

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
