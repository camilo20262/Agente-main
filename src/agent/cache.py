"""Short-lived per-session cache for successful tool results."""

from __future__ import annotations

import json
import time
from typing import Any


class QueryResultCache:
    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}

    @staticmethod
    def key(tool_name: str, arguments: dict[str, Any]) -> str:
        return tool_name + ":" + json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))

    def get(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        key = self.key(tool_name, arguments)
        item = self._items.get(key)
        if item is None:
            return None
        created, result = item
        if time.monotonic() - created > self.ttl_seconds:
            self._items.pop(key, None)
            return None
        return result

    def put(self, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        if result.get("success") is not False and "error" not in result:
            self._items[self.key(tool_name, arguments)] = (time.monotonic(), result)

    def clear(self) -> None:
        self._items.clear()
