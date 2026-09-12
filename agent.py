"""Backward-compatible facade for the modular agent architecture."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from src.agent.prompts import SYSTEM_PROMPT as AGENT_SYSTEM_PROMPT
from src.agent.service import AgentService
from src.config import get_settings
from src.data.repository import create_repository
from src.tools.registry import ToolRegistry


_settings = get_settings()
_repository = create_repository(_settings)
_registry = ToolRegistry(_repository)
TOOLS = _registry.schemas
MODELO = _settings.openrouter_model


def ejecutar_herramienta(nombre: str, argumentos: dict[str, Any]) -> dict[str, Any]:
    return _registry.execute(nombre, argumentos)


def build_agent_service(client: Any | None = None, **service_kwargs: Any) -> AgentService:
    if client is None:
        if not _settings.openrouter_api_key:
            raise ValueError("No se encontró NVIDIA_API_KEY.")
        client = OpenAI(base_url=_settings.llm_base_url, api_key=_settings.openrouter_api_key, timeout=_settings.llm_timeout_seconds, max_retries=0)
    return AgentService(client=client, settings=_settings, registry=ToolRegistry(create_repository(_settings)), **service_kwargs)


def preguntar(pregunta: str) -> str:
    messages: list[dict[str, Any]] = [{"role": "user", "content": pregunta}]
    return build_agent_service().run(messages).answer
