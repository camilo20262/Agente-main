"""Short-lived per-session cache for successful tool results."""

from __future__ import annotations

import json
import time
from copy import deepcopy
from typing import Any


class QueryResultCache:
    def __init__(self, ttl_seconds: int = 300, max_items: int = 128):
        if ttl_seconds < 0 or max_items < 1:
            raise ValueError('TTL debe ser no negativo y la capacidad al menos uno.')
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
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
        return deepcopy(result)

    def put(self, tool_name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
        if result.get("success") is True and "error" not in result and self.ttl_seconds > 0:
            now = time.monotonic()
            self._items = {key: item for key, item in self._items.items() if now - item[0] < self.ttl_seconds}
            key = self.key(tool_name, arguments)
            self._items.pop(key, None)
            while len(self._items) >= self.max_items:
                self._items.pop(next(iter(self._items)))
            self._items[key] = (now, deepcopy(result))

    def clear(self) -> None:
        self._items.clear()
