"""Conversation-local operational metrics."""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ConversationMetrics:
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    bigquery_bytes_processed: int = 0
    bigquery_queries: int = 0
    total_latency_ms: float = 0
    errors: list[str] = field(default_factory=list)
    cache_hits: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
