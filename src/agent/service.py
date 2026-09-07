"""Single iterative LLM/tool orchestration service used by every interface."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any

from src.agent.cache import QueryResultCache
from src.agent.memory import AnalyticalMemory
from src.agent.observability import ConversationMetrics
from src.agent.planner import AnalyticalPlan, AnalyticalPlanner, InvalidToolPlanError
from src.agent.prompts import SYSTEM_PROMPT
from src.config import Settings
from src.tools.registry import ToolRegistry


def _extract_user_text(content: Any) -> str:
    """Extract text for planning without modifying multimodal content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block["text"] for block in content
            if isinstance(block, dict) and block.get("type") == "text"
            and isinstance(block.get("text"), str) and block["text"]
        )
    return ""


def _summarize_partial_evidence(evidence: list[dict[str, Any]]) -> str:
    """Summarize successful results locally, preserving values and query context."""
    lines = ["No pude completar el análisis: alcancé el límite de pasos. "
             "Estos son los resultados parciales obtenidos:"]
    fields = ("metric", "dimension", "brand", "brand_a", "brand_b", "filters", "period",
              "period_a", "period_b", "current_period", "previous_period", "value",
              "value_a", "value_b", "difference", "difference_pct", "current_value",
              "previous_value", "change", "change_pct", "start", "end", "row_count")
    for item in evidence:
        result = item["result"]
        if result.get("success") is not True:
            continue
        details = {key: result[key] for key in fields if key in result and result[key] is not None}
        for key in ("rows", "drivers", "values"):
            if isinstance(result.get(key), list):
                details[key] = result[key][:5]
                if len(result[key]) > 5:
                    details[f"{key}_nota"] = f"Muestra de 5 de {len(result[key])} elementos."
        summary = json.dumps(details, ensure_ascii=False, default=str) if details else "Consulta exitosa sin valores resumibles."
        lines.append(f"- {item['tool']}: {summary}")
    return "\n".join(lines)


class AgentMaxStepsError(RuntimeError):
    """Raised when steps are exhausted without successful evidence."""


class RepeatedToolCallError(RuntimeError):
    """Raised when a model repeats an identical call within one run."""


@dataclass
class AgentResult:
    answer: str
    evidence: list[dict[str, Any]]
    steps: int
    plan: dict[str, Any]
    chart_specs: list[dict[str, Any]]
    metrics: dict[str, Any]
    is_partial: bool = False


class AgentService:
    def __init__(self, *, client: Any, settings: Settings, registry: ToolRegistry, system_prompt: str = SYSTEM_PROMPT,
                 memory: AnalyticalMemory | None = None, cache: QueryResultCache | None = None,
                 metrics: ConversationMetrics | None = None):
        self.client = client
        self.settings = settings
        self.registry = registry
        self.system_prompt = system_prompt
        self.memory = memory or AnalyticalMemory()
        self.cache = cache or QueryResultCache(settings.query_cache_ttl_seconds)
        self.metrics = metrics or ConversationMetrics()
        self.planner = AnalyticalPlanner({item["function"]["name"] for item in registry.schemas})

    def run(self, messages: list[dict[str, Any]], *, model: str | None = None, temperature: float = 0.1) -> AgentResult:
        started = time.perf_counter()
        conversation = list(messages)
        if not conversation or conversation[0].get("role") != "system":
            conversation.insert(0, {"role": "system", "content": self.system_prompt})
        question = next((_extract_user_text(item.get("content")) for item in reversed(conversation)
                         if isinstance(item, dict) and item.get("role") == "user"), "")
        plan: AnalyticalPlan = self.planner.plan(question, self.memory.context())
        conversation.append({"role": "system", "content": "PLAN ANALÍTICO INTERNO VALIDADO (no mostrar al usuario): " + json.dumps(plan.as_dict(), ensure_ascii=False) +
                             "\nMEMORIA ANALÍTICA RESUMIDA: " + json.dumps(self.memory.context(), ensure_ascii=False)})
        evidence: list[dict[str, Any]] = []
        chart_specs: list[dict[str, Any]] = []
        calls_seen: set[str] = set()
        for step in range(1, self.settings.max_agent_steps + 1):
            self.metrics.total_llm_calls += 1
            has_successful_evidence = any(item["result"].get("success") is True for item in evidence)
            tool_choice: Any = "auto"
            if step == 1 and plan.steps:
                tool_choice = {"type": "function", "function": {"name": plan.steps[0].tool}}
            elif has_successful_evidence and "integrate.api.nvidia.com" in str(getattr(self.client, "base_url", "")):
                # NVIDIA's hosted GPT-OSS endpoint can repeat the forced tool call
                # after receiving its result. At this point the validated plan has
                # successful evidence, so require the model to produce the final narrative.
                tool_choice = "none"
            completion = self.client.chat.completions.create(model=model or self.settings.openrouter_model, messages=conversation,
                tools=self.registry.schemas, tool_choice=tool_choice, temperature=temperature,
                max_tokens=self.settings.llm_max_tokens)
            message = completion.choices[0].message
            if not message.tool_calls:
                if plan.steps and not has_successful_evidence:
                    conversation.append(message)
                    conversation.append({"role": "system", "content": "El plan requiere evidencia cuantitativa. No respondas todavía: ejecuta una tool registrada apropiada antes de concluir."})
                    continue
                self.metrics.total_latency_ms += round((time.perf_counter() - started) * 1000, 2)
                return AgentResult(message.content or "No fue posible producir una respuesta.", evidence, step, plan.as_dict(), chart_specs, self.metrics.as_dict())
            conversation.append(message)
            for call in message.tool_calls:
                cache_hit = False
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                    if not isinstance(arguments, dict):
                        raise ValueError("Los argumentos deben ser un objeto JSON.")
                except (json.JSONDecodeError, ValueError) as exc:
                    result = {"success": False, "error": f"Argumentos inválidos: {exc}"}
                    arguments = {}
                else:
                    call_key = QueryResultCache.key(call.function.name, arguments)
                    if call_key in calls_seen:
                        self.metrics.errors.append("repeated_tool_call")
                        raise RepeatedToolCallError(f"Tool repetida con argumentos idénticos: {call.function.name}")
                    calls_seen.add(call_key)
                    self.metrics.total_tool_calls += 1
                    cached = self.cache.get(call.function.name, arguments)
                    if cached is not None:
                        result = cached
                        cache_hit = True
                        self.metrics.cache_hits += 1
                    else:
                        result = self.registry.execute(call.function.name, arguments)
                        cache_hit = False
                        self.cache.put(call.function.name, arguments, result)
                    self.memory.update_from_result(call.function.name, arguments, result)
                record = {
                    "tool": call.function.name,
                    "arguments": arguments,
                    "source": result.get("source", self.registry.repository.source),
                    "metric": result.get("metric"),
                    "filters": result.get("filters"),
                    "row_count": result.get("row_count"),
                    "result": result,
                    "step": step,
                    "cache_hit": cache_hit,
                }
                if isinstance(result.get("evidence"), dict):
                    record.update(result["evidence"])
                evidence.append(record)
                query_evidence = result.get("evidence")
                evidences = query_evidence if isinstance(query_evidence, list) else [query_evidence]
                record["queries"] = [item for item in evidences if isinstance(item, dict)]
                for query in (item for item in evidences if isinstance(item, dict)):
                    bytes_processed = int(query.get("bytes_processed", 0) or 0)
                    if not record["cache_hit"]:
                        self.metrics.bigquery_bytes_processed += bytes_processed
                    if result.get("source") == "bigquery" and not record["cache_hit"]:
                        self.metrics.bigquery_queries += 1
                if result.get("success") is False:
                    self.metrics.errors.append(str(result.get("error", "tool_error")))
                from src.visualization import build_chart_spec
                chart = build_chart_spec(call.function.name, result)
                if chart:
                    chart_specs.append(chart)
                conversation.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False, default=str)})
        self.metrics.errors.append("max_steps")
        # Include results from the last step, which were not present at loop entry.
        has_successful_evidence = any(item["result"].get("success") is True for item in evidence)
        if has_successful_evidence:
            self.metrics.total_latency_ms += round((time.perf_counter() - started) * 1000, 2)
            return AgentResult(
                answer=_summarize_partial_evidence(evidence), evidence=evidence,
                steps=self.settings.max_agent_steps, plan=plan.as_dict(),
                chart_specs=chart_specs, metrics=self.metrics.as_dict(), is_partial=True,
            )
        raise AgentMaxStepsError(f"El agente excedió el máximo de {self.settings.max_agent_steps} pasos.")
