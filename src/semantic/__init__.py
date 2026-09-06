"""Semantic business configuration loaded once per process."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@lru_cache(maxsize=1)
def load_semantic_layer() -> dict[str, Any]:
    root = Path(__file__).parent
    result: dict[str, Any] = {}
    for name in ("metrics", "dimensions", "synonyms", "business_rules"):
        with (root / f"{name}.yaml").open(encoding="utf-8") as handle:
            result[name] = yaml.safe_load(handle) or {}
    return result
