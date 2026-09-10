"""Single iterative LLM/tool orchestration service used by every interface."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import time
from typing import Any

from src.agent.cache import QueryResultCache
from src.agent.memory import AnalyticalMemory
from src.agent.observability import ConversationMetrics
from src.agent.planner import AnalyticalPlan, AnalyticalPlanner, InvalidToolPlanError
from src.agent.prompts import FINAL_RESPONSE_PROMPT, SYSTEM_PROMPT
from src.agent.response_validator import compact_evidence, validate_answer
from src.config import Settings
from src.tools.registry import ToolRegistry


def _extract_user_text(content: Any) -> str:
    """Extract text for planning without modifying multimodal content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
            and block["text"]
        )
    return ""


def _summarize_partial_evidence(
    evidence: list[dict[str, Any]],
    *,
    reason: str = "alcancé el límite de pasos",
) -> str:
    """Summarize successful results locally, preserving values and query context."""
    lines = [
        f"No pude completar el análisis: {reason}. "
        "Estos son los resultados parciales obtenidos:"
    ]
    fields = (
        "metric",
        "dimension",
        "brand",
        "brand_a",
        "brand_b",
        "filters",
        "period",
        "period_a",
        "period_b",
        "current_period",
        "previous_period",
        "value",
        "value_a",
        "value_b",
        "difference",
        "difference_pct",
        "current_value",
        "previous_value",
        "change",
        "change_pct",
        "start",
        "end",
        "row_count",
    )

    for item in evidence:
        result = item["result"]
        if result.get("success") is not True:
            continue

        details = {
            key: result[key]
            for key in fields
            if key in result and result[key] is not None
        }

        for key in ("rows", "drivers", "values"):
            if isinstance(result.get(key), list):
                details[key] = result[key][:5]
                if len(result[key]) > 5:
                    details[f"{key}_nota"] = (
                        f"Muestra de 5 de {len(result[key])} elementos."
                    )

        summary = (
            json.dumps(details, ensure_ascii=False, default=str)
            if details
            else "Consulta exitosa sin valores resumibles."
        )

        if item.get("historical"):
            lines.append(
                f"- Evidencia histórica de la pregunta "
                f"{item['origin_question']!r} — {item['tool']}: {summary}"
            )
        else:
            lines.append(f"- {item['tool']}: {summary}")

    if any(item.get("historical") for item in evidence):
        lines.insert(
            1,
            "No obtuve evidencia exitosa para la pregunta actual. "
            "Los datos siguientes proceden de una pregunta anterior y "
            "no responden la consulta actual.",
        )

    return "\n".join(lines)


class AgentMaxStepsError(RuntimeError):
    """Raised when steps are exhausted without successful evidence."""


class RepeatedToolCallError(RuntimeError):
    """Legacy exception kept for compatibility with existing imports/tests."""


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
    def __init__(
        self,
        *,
        client: Any,
        settings: Settings,
        registry: ToolRegistry,
        system_prompt: str = SYSTEM_PROMPT,
        memory: AnalyticalMemory | None = None,
        cache: QueryResultCache | None = None,
        metrics: ConversationMetrics | None = None,
    ):
        self.client = client
        self.settings = settings
        self.registry = registry
        self.system_prompt = system_prompt
        self.memory = memory or AnalyticalMemory()
        self.cache = cache or QueryResultCache(settings.query_cache_ttl_seconds)
        self.metrics = metrics or ConversationMetrics()
        self._historical_evidence: list[dict[str, Any]] = []
        self._historical_charts: list[dict[str, Any]] = []

        self.planner = AnalyticalPlanner(
            {item["function"]["name"] for item in registry.schemas}
        )

    def _remember_evidence(
        self,
        evidence: list[dict[str, Any]],
        chart_specs: list[dict[str, Any]],
        question: str,
    ) -> None:
        successful = [
            item
            for item in evidence
            if item["result"].get("success") is True
            and not item.get("historical")
        ]

        if successful:
            self._historical_evidence = deepcopy(successful)

            for item in self._historical_evidence:
                item.update(
                    historical=True,
                    origin_question=question,
                )

            self._historical_charts = deepcopy(chart_specs)

            for chart in self._historical_charts:
                chart["title"] = (
                    f"Histórico ({question}): "
                    f"{chart.get('title', 'Resultado anterior')}"
                )

    def _partial_result(
        self,
        evidence: list[dict[str, Any]],
        plan: AnalyticalPlan,
        chart_specs: list[dict[str, Any]],
        steps: int,
        started: float,
        question: str,
        *,
        reason: str = "alcancé el límite de pasos",
    ) -> AgentResult:
        self.metrics.total_latency_ms += round(
            (time.perf_counter() - started) * 1000,
            2,
        )

        self._remember_evidence(
            evidence,
            chart_specs,
            question,
        )

        return AgentResult(
            answer=_summarize_partial_evidence(
                evidence,
                reason=reason,
            ),
            evidence=evidence,
            steps=steps,
            plan=plan.as_dict(),
            chart_specs=chart_specs,
            metrics=self.metrics.as_dict(),
            is_partial=True,
        )

    def _generate_final_answer(
        self,
        *,
        question: str,
        evidence: list[dict[str, Any]],
        model: str | None,
        temperature: float,
        reason: str,
        repair_issues: list[str] | None = None,
    ) -> tuple[str | None, str | None]:
        """Generate a compact, tool-free final narrative."""
        compact = compact_evidence(evidence)

        user_payload = (
            "PREGUNTA ORIGINAL:\n"
            f"{question}\n\n"
            "EVIDENCIA COMPACTA CALCULADA POR BIGQUERY/PYTHON:\n"
            + json.dumps(
                compact,
                ensure_ascii=False,
                default=str,
            )
            + "\n\n"
            f"MOTIVO DE CIERRE: {reason}"
        )

        if repair_issues:
            user_payload += (
                "\n\nLA RESPUESTA ANTERIOR NO PASÓ LA VALIDACIÓN. "
                "Reescríbela completa desde cero y corrige específicamente "
                "estos problemas:\n- "
                + "\n- ".join(repair_issues)
                + "\nNo menciones el proceso de validación al usuario."
            )

        self.metrics.total_llm_calls += 1

        completion = self.client.chat.completions.create(
            model=model or self.settings.openrouter_model,
            messages=[
                {
                    "role": "system",
                    "content": FINAL_RESPONSE_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_payload,
                },
            ],
            temperature=temperature,
            max_tokens=self.settings.llm_final_max_tokens,
        )

        choice = completion.choices[0]
        message = choice.message
        finish_reason = getattr(
            choice,
            "finish_reason",
            None,
        )

        return message.content, finish_reason

    def _finalize_answer(
        self,
        *,
        question: str,
        evidence: list[dict[str, Any]],
        model: str | None,
        temperature: float,
        reason: str,
    ) -> tuple[str, tuple[str, ...]]:
        """Generate, validate and optionally repair the final narrative."""
        answer, finish_reason = self._generate_final_answer(
            question=question,
            evidence=evidence,
            model=model,
            temperature=temperature,
            reason=reason,
        )

        answer = answer or "No fue posible producir una respuesta."

        validation = validate_answer(
            answer,
            evidence,
            finish_reason=finish_reason,
        )

        retries = max(
            0,
            self.settings.response_validation_retries,
        )

        for _ in range(retries):
            if validation.valid:
                break

            self.metrics.errors.extend(
                f"response_validation:{issue}"
                for issue in validation.issues
            )

            repaired, repaired_finish_reason = self._generate_final_answer(
                question=question,
                evidence=evidence,
                model=model,
                temperature=temperature,
                reason="corrección de la respuesta final",
                repair_issues=list(validation.issues),
            )

            if repaired:
                answer = repaired

            validation = validate_answer(
                answer,
                evidence,
                finish_reason=repaired_finish_reason,
            )

        if not validation.valid:
            self.metrics.errors.extend(
                f"response_validation_unresolved:{issue}"
                for issue in validation.issues
            )

        return answer, validation.issues

    def run(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        temperature: float = 0.1,
    ) -> AgentResult:
        started = time.perf_counter()
        conversation = list(messages)

        if not conversation or conversation[0].get("role") != "system":
            conversation.insert(
                0,
                {
                    "role": "system",
                    "content": self.system_prompt,
                },
            )

        question = next(
            (
                _extract_user_text(item.get("content"))
                for item in reversed(conversation)
                if isinstance(item, dict)
                and item.get("role") == "user"
            ),
            "",
        )

        plan: AnalyticalPlan = self.planner.plan(
            question,
            self.memory.context(),
        )

        conversation.append(
            {
                "role": "system",
                "content": (
                    "PLAN ANALÍTICO INTERNO VALIDADO (no mostrar al usuario): "
                    + json.dumps(plan.as_dict(), ensure_ascii=False)
                    + "\nMEMORIA ANALÍTICA RESUMIDA: "
                    + json.dumps(
                        self.memory.context(),
                        ensure_ascii=False,
                    )
                ),
            }
        )

        evidence: list[dict[str, Any]] = []
        chart_specs: list[dict[str, Any]] = []
        calls_seen: set[str] = set()

        registered_tools = {
            item["function"]["name"]
            for item in self.registry.schemas
        }

        for step in range(
            1,
            self.settings.max_agent_steps + 1,
        ):
            self.metrics.total_llm_calls += 1

            has_successful_evidence = any(
                item["result"].get("success") is True
                for item in evidence
            )

            # La primera herramienta puede seguir viniendo forzada por el planner.
            # A partir del segundo paso, el modelo decide si necesita otra tool
            # o si ya tiene suficiente evidencia para responder.
            tool_choice: Any = "auto"

            if step == 1 and plan.steps:
                tool_choice = {
                    "type": "function",
                    "function": {
                        "name": plan.steps[0].tool
                    },
                }

            completion = self.client.chat.completions.create(
                model=model or self.settings.openrouter_model,
                messages=conversation,
                tools=self.registry.schemas,
                tool_choice=tool_choice,
                temperature=temperature,
                max_tokens=self.settings.llm_max_tokens,
            )

            choice = completion.choices[0]
            message = choice.message
            finish_reason = getattr(choice, "finish_reason", None)

            # Si el modelo ya no pide herramientas, usamos esa decisión como
            # señal de que terminó la investigación. Si ya hay evidencia,
            # generamos una narrativa final compacta, validada y con mayor presupuesto.
            if not message.tool_calls:
                if plan.steps and not has_successful_evidence:
                    conversation.append(message)
                    conversation.append(
                        {
                            "role": "system",
                            "content": (
                                "El plan requiere evidencia cuantitativa. "
                                "No respondas todavía: ejecuta una tool "
                                "registrada apropiada antes de concluir."
                            ),
                        }
                    )
                    continue

                if has_successful_evidence:
                    try:
                        answer, validation_issues = self._finalize_answer(
                            question=question,
                            evidence=evidence,
                            model=model,
                            temperature=temperature,
                            reason=(
                                "el modelo concluyó que ya existe "
                                "evidencia suficiente"
                            ),
                        )
                    except Exception as exc:
                        self.metrics.errors.append(
                            f"final_answer_error: {exc}"
                        )
                        answer = (
                            message.content
                            or _summarize_partial_evidence(
                                evidence,
                                reason="falló la generación final",
                            )
                        )
                        validation_issues = ("final_generation_failed",)
                else:
                    answer = (
                        message.content
                        or "No fue posible producir una respuesta."
                    )
                    validation_issues = ()

                self.metrics.total_latency_ms += round(
                    (time.perf_counter() - started) * 1000,
                    2,
                )

                self._remember_evidence(
                    evidence,
                    chart_specs,
                    question,
                )

                return AgentResult(
                    answer=answer,
                    evidence=evidence,
                    steps=step,
                    plan=plan.as_dict(),
                    chart_specs=chart_specs,
                    metrics=self.metrics.as_dict(),
                    is_partial=bool(validation_issues),
                )

            conversation.append(message)

            for call in message.tool_calls:
                cache_hit = False

                # Recompute inside the batch: an earlier call may just have succeeded.
                has_successful_evidence = any(
                    item["result"].get("success") is True
                    for item in evidence
                )

                fallback_evidence = (
                    evidence
                    if has_successful_evidence
                    else evidence + deepcopy(self._historical_evidence)
                )

                fallback_charts = (
                    chart_specs
                    if has_successful_evidence
                    else deepcopy(self._historical_charts)
                )

                has_fallback_evidence = (
                    has_successful_evidence
                    or bool(self._historical_evidence)
                )

                if call.function.name not in registered_tools:
                    self.metrics.errors.append("unknown_tool")

                    if has_fallback_evidence:
                        return self._partial_result(
                            fallback_evidence,
                            plan,
                            fallback_charts,
                            step,
                            started,
                            question,
                            reason=(
                                "el modelo solicitó una herramienta "
                                "no registrada"
                            ),
                        )

                try:
                    arguments = json.loads(
                        call.function.arguments or "{}"
                    )

                    if not isinstance(arguments, dict):
                        raise ValueError(
                            "Los argumentos deben ser un objeto JSON."
                        )

                except (json.JSONDecodeError, ValueError) as exc:
                    result = {
                        "success": False,
                        "error": f"Argumentos inválidos: {exc}",
                    }
                    arguments = {}

                else:
                    call_key = QueryResultCache.key(
                        call.function.name,
                        arguments,
                    )

                    # CAMBIO:
                    # Una llamada repetida ya no aborta todo el análisis.
                    # Se devuelve feedback al modelo para que use la evidencia
                    # existente, cambie de herramienta o finalice.
                    if call_key in calls_seen:
                        self.metrics.errors.append(
                            "repeated_tool_call"
                        )

                        duplicate_result = {
                            "success": False,
                            "source": self.registry.repository.source,
                            "duplicate": True,
                            "error": (
                                "Esta consulta ya fue ejecutada con "
                                "exactamente los mismos argumentos durante "
                                "este análisis. No la repitas. Usa la "
                                "evidencia ya obtenida, selecciona otra "
                                "herramienta que aporte información nueva "
                                "o genera la respuesta final."
                            ),
                        }

                        conversation.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": json.dumps(
                                    duplicate_result,
                                    ensure_ascii=False,
                                    default=str,
                                ),
                            }
                        )

                        continue

                    calls_seen.add(call_key)
                    self.metrics.total_tool_calls += 1

                    cached = self.cache.get(
                        call.function.name,
                        arguments,
                    )

                    if cached is not None:
                        result = cached
                        cache_hit = True
                        self.metrics.cache_hits += 1

                    else:
                        result = self.registry.execute(
                            call.function.name,
                            arguments,
                        )
                        cache_hit = False

                        # CAMBIO:
                        # Solo guardamos resultados exitosos.
                        # Errores de validación/argumentos no contaminan caché.
                        if result.get("success") is True:
                            self.cache.put(
                                call.function.name,
                                arguments,
                                result,
                            )

                    self.memory.update_from_result(
                        call.function.name,
                        arguments,
                        result,
                    )

                record = {
                    "tool": call.function.name,
                    "arguments": arguments,
                    "source": result.get(
                        "source",
                        self.registry.repository.source,
                    ),
                    "metric": result.get("metric"),
                    "filters": result.get("filters"),
                    "row_count": result.get("row_count"),
                    "result": result,
                    "step": step,
                    "cache_hit": cache_hit,
                }

                if isinstance(
                    result.get("evidence"),
                    dict,
                ):
                    record.update(
                        result["evidence"]
                    )

                evidence.append(record)

                query_evidence = result.get("evidence")
                evidences = (
                    query_evidence
                    if isinstance(query_evidence, list)
                    else [query_evidence]
                )

                record["queries"] = [
                    item
                    for item in evidences
                    if isinstance(item, dict)
                ]

                for query in (
                    item
                    for item in evidences
                    if isinstance(item, dict)
                ):
                    bytes_processed = int(
                        query.get(
                            "bytes_processed",
                            0,
                        )
                        or 0
                    )

                    if not record["cache_hit"]:
                        self.metrics.bigquery_bytes_processed += (
                            bytes_processed
                        )

                    if (
                        result.get("source") == "bigquery"
                        and not record["cache_hit"]
                    ):
                        self.metrics.bigquery_queries += 1

                if result.get("success") is False:
                    self.metrics.errors.append(
                        str(
                            result.get(
                                "error",
                                "tool_error",
                            )
                        )
                    )

                from src.visualization import build_chart_spec

                chart = build_chart_spec(
                    call.function.name,
                    result,
                )

                if chart:
                    chart_specs.append(chart)

                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(
                            result,
                            ensure_ascii=False,
                            default=str,
                        ),
                    }
                )

        # Se agotó el presupuesto de investigación.
        self.metrics.errors.append("max_steps")

        has_successful_evidence = any(
            item["result"].get("success") is True
            for item in evidence
        )

        # CAMBIO:
        # Si ya existe evidencia útil, no devolvemos inmediatamente
        # "No pude completar". Forzamos una última llamada SIN herramientas
        # para que el modelo produzca la narrativa de hallazgos.
        if has_successful_evidence:
            conversation.append(
                {
                    "role": "system",
                    "content": (
                        "Has alcanzado el presupuesto máximo de "
                        "investigación. No realices más consultas ni "
                        "solicites herramientas. Genera ahora la respuesta "
                        "final usando exclusivamente la evidencia obtenida. "
                        "Prioriza los hallazgos más relevantes, sus drivers, "
                        "interpretación e hipótesis cuando estén respaldadas. "
                        "Distingue claramente hechos de hipótesis. "
                        "No inventes cifras ni completes datos faltantes."
                    ),
                }
            )

            try:
                final_answer, validation_issues = self._finalize_answer(
                    question=question,
                    evidence=evidence,
                    model=model,
                    temperature=temperature,
                    reason="se alcanzó el presupuesto máximo de investigación",
                )

                if final_answer:
                    self.metrics.total_latency_ms += round(
                        (
                            time.perf_counter()
                            - started
                        )
                        * 1000,
                        2,
                    )

                    self._remember_evidence(
                        evidence,
                        chart_specs,
                        question,
                    )

                    return AgentResult(
                        answer=final_answer,
                        evidence=evidence,
                        steps=self.settings.max_agent_steps,
                        plan=plan.as_dict(),
                        chart_specs=chart_specs,
                        metrics=self.metrics.as_dict(),
                        is_partial=bool(validation_issues),
                    )

            except Exception as exc:
                self.metrics.errors.append(
                    f"final_answer_error: {exc}"
                )

            # Fallback únicamente si la última generación de narrativa falla.
            return self._partial_result(
                evidence,
                plan,
                chart_specs,
                self.settings.max_agent_steps,
                started,
                question,
                reason=(
                    "alcancé el límite de pasos y no fue posible "
                    "generar la narrativa final"
                ),
            )

        raise AgentMaxStepsError(
            f"El agente excedió el máximo de "
            f"{self.settings.max_agent_steps} pasos."
        )
