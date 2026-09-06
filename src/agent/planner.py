"""Deterministic analytical planner constrained by the live Tool Registry."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import unicodedata
from typing import Any


class InvalidToolPlanError(ValueError):
    """Raised when a plan references a tool that is not registered."""


@dataclass(frozen=True)
class PlanStep:
    tool: str
    purpose: str


@dataclass(frozen=True)
class AnalyticalPlan:
    intent: str
    domains: list[str]
    steps: list[PlanStep]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class AnalyticalPlanner:
    """Build a small, safe plan to guide—not replace—the LLM tool loop."""

    def __init__(self, allowed_tools: set[str]):
        self.allowed_tools = allowed_tools

    def plan(self, question: str, memory: dict[str, Any] | None = None) -> AnalyticalPlan:
        text = "".join(char for char in unicodedata.normalize("NFD", question.lower()) if unicodedata.category(char) != "Mn")
        attachment = any(word in text for word in ("imagen", "captura", "pdf", "documento"))
        bicomp = any(word in text for word in ("invers", "invirti", "anunciante", "marca", "bicomp", "publicitaria", "insercion", "medio", "vehiculo", "volvo", "renault", "chevrolet"))
        domains = (["bicomp"] if bicomp else []) + (["attachments"] if attachment else [])
        is_follow_up = bool(re.search(r"\b(ahora|también|tambien|solo|mismo|misma)\b", text))
        if not domains and is_follow_up and memory and memory.get("last_domain"):
            domains = [memory["last_domain"]]
            bicomp = memory["last_domain"] == "bicomp"

        # FIX: previously this block forced domains = ["bicomp"] whenever
        # nothing matched, which meant every out-of-domain question (small
        # talk, "what's today's date", etc.) was treated as a BICOMP metric
        # query and forced a tool call downstream in AgentService. Now, if
        # nothing matched a real domain, we return a plan with no steps so
        # the LLM is free to answer directly without invoking any tool.
        if not domains:
            return AnalyticalPlan(intent="out_of_domain", domains=["none"], steps=[])

        steps: list[PlanStep] = []
        month_mentions = sum(text.count(month) for month in ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"))
        if attachment and not bicomp:
            intent = "attachment_analysis"
        elif bicomp and re.search(r"por que|explica|cayo|cambio|variacion|perdio", text):
            steps.append(PlanStep("explicar_variacion_bicomp", "comparar periodos y encontrar drivers por dimensión"))
            intent = "variation_explanation"
        elif bicomp and ("periodo" in text or (month_mentions >= 2 and ("contra" in text or "compara" in text))):
            steps.append(PlanStep("comparar_periodos_bicomp", "comparar ventanas temporales equivalentes"))
            intent = "period_comparison"
        elif bicomp and ("vs" in text or "contra" in text or "compara" in text):
            steps.append(PlanStep("comparar_marcas", "comparar entidades con cálculo determinista"))
            intent = "competitive_analysis"
        elif bicomp and any(word in text for word in ("evoluci", "tendencia", "mensual", "gráfic", "grafic")):
            steps.append(PlanStep("serie_temporal_bicomp", "obtener serie temporal para análisis y visualización"))
            intent = "time_series_analysis"
        elif bicomp and any(word in text for word in ("cobertura", "qué fechas", "que fechas")):
            steps.append(PlanStep("obtener_cobertura_bicomp", "consultar cobertura y esquema de la fuente"))
            intent = "coverage"
        elif bicomp and any(word in text for word in ("lista", "disponibles", "catálogo", "catalogo")):
            steps.append(PlanStep("obtener_catalogo_bicomp", "recuperar valores válidos de una dimensión"))
            intent = "catalog"
        elif bicomp and ("insercion" in text or "inserción" in text) and not any(word in text for word in ("por medio", "ranking", "top")):
            steps.append(PlanStep("consultar_inserciones_bicomp", "calcular volumen de inserciones"))
            intent = "insertions"
        elif bicomp and "vehicul" in text:
            steps.append(PlanStep("analizar_vehiculos", "desglosar la métrica por vehículo"))
            intent = "vehicle_analysis"
        elif bicomp and "medio" in text and any(word in text for word in ("analiza", "distribu", "por medio")):
            steps.append(PlanStep("analizar_medios", "desglosar la métrica por medio"))
            intent = "media_analysis"
        elif bicomp and any(word in text for word in (
            "region", "sector", "holding", "agencia", "ciudad", "categoria", "subsector",
            "central", "pais", "producto", "soporte", "franja", "genero", "tipo_pauta",
            "marca_agrupada", "anunciante_agrupado",
        )):
            # NEW: routes to the generic ranking_por_dimension tool for any
            # dimension not already covered by a dedicated branch above
            # (anunciante, marca, medio, vehiculo). Without this, questions
            # like "inversión por región" fell through to the generic
            # consultar_inversion_publicitaria fallback, which only returns a
            # total with no breakdown, causing the model to spend its full
            # step budget guessing at other tools and hit AgentMaxStepsError.
            steps.append(PlanStep("ranking_por_dimension", "desglosar la métrica por la dimensión mencionada"))
            intent = "dimension_breakdown"
        elif bicomp and any(word in text for word in ("ranking", "top", "lider")):
            tool = "ranking_anunciantes" if "anunciante" in text else "ranking_marcas"
            steps.append(PlanStep(tool, "ordenar inversión mediante BigQuery"))
            intent = "ranking"
        elif bicomp:
            remembered_brands = (memory or {}).get("last_entities", {}).get("brands", [])
            tool = "comparar_marcas" if is_follow_up and len(remembered_brands) >= 2 else "consultar_inversion_publicitaria"
            steps.append(PlanStep(tool, "reutilizar contexto y calcular la métrica solicitada en BigQuery"))
            intent = "metric_query"
        else:
            # FIX: this used to unconditionally append
            # consultar_inversion_publicitaria as a safety net. That was only
            # ever safe because bicomp was always forced True by the removed
            # fallback above. Now this branch is reachable only when domains
            # came from memory (e.g. domains == ["attachments"] via a
            # follow-up) and bicomp is genuinely False here — so we must not
            # force a BICOMP tool call in that case either.
            intent = "unhandled_domain"
        self.validate(AnalyticalPlan(intent, domains, steps))
        return AnalyticalPlan(intent, domains, steps)

    def validate(self, plan: AnalyticalPlan) -> None:
        invalid = [step.tool for step in plan.steps if step.tool not in self.allowed_tools]
        if invalid:
            raise InvalidToolPlanError("El plan contiene tools no registradas: " + ", ".join(invalid))