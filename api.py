"""FastAPI adapter for the existing media intelligence agent."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent import build_agent_service


logger = logging.getLogger(__name__)


class PowerBIContext(BaseModel):
    """Filters supplied by Power BI through Power Apps."""

    model_config = ConfigDict(extra="forbid")

    marca: str | None = Field(default=None, max_length=200)
    pais: str | None = Field(default=None, max_length=200)
    anio: str | None = Field(default=None, max_length=20)
    medio: str | None = Field(default=None, max_length=200)
    inversion: str | None = Field(default=None, max_length=200)

    @field_validator("*", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pregunta: str = Field(min_length=1, max_length=8_000)
    contexto: PowerBIContext = Field(default_factory=PowerBIContext)

    @field_validator("pregunta")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("La pregunta no puede estar vacía.")
        return value


class ChatResponse(BaseModel):
    respuesta: str
    parcial: bool


class HealthResponse(BaseModel):
    status: str


def build_context_prompt(
    contexto: PowerBIContext | Mapping[str, Any] | None,
) -> str:
    """Render Power BI filters as user-provided context for AgentService."""

    if contexto is None:
        return ""
    values = (
        contexto.model_dump() if isinstance(contexto, PowerBIContext) else dict(contexto)
    )
    labels = (
        ("marca", "Marca"),
        ("pais", "País"),
        ("anio", "Año"),
        ("medio", "Medio"),
        ("inversion", "Inversión"),
    )
    lines = [f"{label}: {values.get(field)}" for field, label in labels if values.get(field)]
    if not lines:
        return ""
    return "El usuario está analizando:\n" + "\n".join(lines)


def _configured_cors_origins() -> list[str]:
    return [
        origin.strip()
        for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]


app = FastAPI(
    title="WPP Media Intelligence API",
    version="1.0.0",
    description="API REST para consultar el AgentService analítico existente.",
)

cors_origins = _configured_cors_origins()
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness endpoint; it intentionally performs no paid external calls."""

    return HealthResponse(status="ok")


@app.post("/api/v1/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    """Execute one stateless agent turn using optional Power BI context."""

    context_prompt = build_context_prompt(request.contexto)
    content = request.pregunta
    if context_prompt:
        content = f"{content}\n\n{context_prompt}"

    try:
        # One service per request prevents analytical memory from leaking between users.
        result = build_agent_service().run([{"role": "user", "content": content}])
    except Exception as exc:
        logger.exception("No fue posible procesar la solicitud del agente: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio del agente no está disponible temporalmente.",
        ) from exc

    return ChatResponse(respuesta=result.answer, parcial=result.is_partial)
