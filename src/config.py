"""Centralized, side-effect free application configuration."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str | None = None
    openrouter_model: str = "nvidia/nemotron-3-super-120b-a12b"
    llm_base_url: str = "https://integrate.api.nvidia.com/v1"
    gcp_project_id: str | None = "nexuslatam-master"
    bigquery_dataset: str | None = "NEXUS_GROUPM_BI_2"
    bigquery_bicomp_table: str | None = "tb_data_bicompetitive"
    bigquery_location: str = "US"
    bigquery_max_bytes_billed: int = 1_000_000_000

    max_agent_steps: int = 8
    llm_max_tokens: int = 800

    # Presupuesto exclusivo para la narrativa final.
    llm_final_max_tokens: int = 1800

    # Un reintento de reparación si la respuesta final no pasa validación.
    response_validation_retries: int = 1

    query_cache_ttl_seconds: int = 300
    llm_plan_max_tokens: int = 2200
    llm_timeout_seconds: int = 60
    bigquery_timeout_seconds: int = 45
    llm_reasoning_effort: str | None = "none"
    plan_semantic_review: bool = False
    history_max_messages: int = 12
    history_max_chars: int = 16000
    vision_models: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("max_agent_steps", "llm_max_tokens", "llm_final_max_tokens", "llm_plan_max_tokens",
                     "llm_timeout_seconds", "bigquery_timeout_seconds", "bigquery_max_bytes_billed",
                     "history_max_messages", "history_max_chars"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} debe ser positivo.")
        if self.query_cache_ttl_seconds < 0 or not 0 <= self.response_validation_retries <= 1:
            raise ValueError("TTL debe ser no negativo y se permite como máximo una reparación final.")

    @classmethod
    def from_env(
        cls,
        env_file: str | Path | None = None,
    ) -> "Settings":
        load_dotenv(dotenv_path=env_file)

        return cls(
            openrouter_api_key=(
                os.getenv("NVIDIA_API_KEY")
                or os.getenv("OPENROUTER_API_KEY")
            ),
            openrouter_model=(
                os.getenv("NVIDIA_MODEL")
                or os.getenv(
                    "OPENROUTER_MODEL",
                    "nvidia/nemotron-3-super-120b-a12b",
                )
            ),
            llm_base_url=os.getenv(
                "LLM_BASE_URL",
                "https://openrouter.ai/api/v1" if os.getenv("OPENROUTER_API_KEY") and not os.getenv("NVIDIA_API_KEY") else "https://integrate.api.nvidia.com/v1",
            ),
            gcp_project_id=os.getenv(
                "GCP_PROJECT_ID",
                "nexuslatam-master",
            ),
            bigquery_dataset=os.getenv(
                "BIGQUERY_DATASET",
                "NEXUS_GROUPM_BI_2",
            ),
            bigquery_bicomp_table=os.getenv(
                "BIGQUERY_BICOMP_TABLE",
                "tb_data_bicompetitive",
            ),
            bigquery_location=os.getenv(
                "BIGQUERY_LOCATION",
                "US",
            ),
            bigquery_max_bytes_billed=int(
                os.getenv(
                    "BIGQUERY_MAX_BYTES_BILLED",
                    "1000000000",
                )
            ),
            max_agent_steps=int(
                os.getenv("MAX_AGENT_STEPS", "8")
            ),
            llm_max_tokens=int(
                os.getenv("LLM_MAX_TOKENS", "800")
            ),
            llm_final_max_tokens=int(
                os.getenv(
                    "LLM_FINAL_MAX_TOKENS",
                    "1800",
                )
            ),
            response_validation_retries=int(
                os.getenv(
                    "RESPONSE_VALIDATION_RETRIES",
                    "1",
                )
            ),
            query_cache_ttl_seconds=int(
                os.getenv(
                    "QUERY_CACHE_TTL_SECONDS",
                    "300",
                )
            ),
            llm_plan_max_tokens=int(os.getenv("LLM_PLAN_MAX_TOKENS", "2200")),
            llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
            bigquery_timeout_seconds=int(os.getenv("BIGQUERY_TIMEOUT_SECONDS", "45")),
            llm_reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "none") or None,
            vision_models=tuple(v.strip() for v in os.getenv("LLM_VISION_MODELS", "").split(",") if v.strip()),
            plan_semantic_review=os.getenv("PLAN_SEMANTIC_REVIEW", "false").lower() == "true",
            history_max_messages=int(os.getenv("HISTORY_MAX_MESSAGES", "12")),
            history_max_chars=int(os.getenv("HISTORY_MAX_CHARS", "16000")),
        )

    def validate_bigquery(self) -> None:
        missing = [
            name
            for name, value in {
                "GCP_PROJECT_ID": self.gcp_project_id,
                "BIGQUERY_DATASET": self.bigquery_dataset,
                "BIGQUERY_BICOMP_TABLE": self.bigquery_bicomp_table,
            }.items()
            if not value
        ]

        if missing:
            raise ValueError(
                "Configuración BigQuery incompleta: "
                + ", ".join(missing)
            )


def get_settings() -> Settings:
    return Settings.from_env()
