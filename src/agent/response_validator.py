"""Deterministic validation and compaction for final analytical responses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import Any


_PERCENT_KEYS = {
    "share_pct",
    "share_of_total_pct",
    "difference_pct",
    "change_pct",
    "contribution_pct",
    "ratio_pct",
}

_RISKY_CAUSAL_PATTERNS = (
    r"\bblack\s*friday\b",
    r"\bnavidad\b",
    r"\blanzamiento\b",
    r"\bpromoci[oó]n\b",
    r"\bbranding\b",
    r"\bawareness\b",
    r"\bperformance\b",
    r"\bpara llegar a (?:la|las|los|una|un)\s+audiencia",
    r"\baudiencias? de alto poder adquisitivo\b",
    r"\bestrategia que prioriza\b",
    r"\bobjetivo de campa[nñ]a\b",
    r"\bcampa[nñ]a de fin de a[nñ]o\b",
)

_PERCENT_RE = re.compile(
    r"(?<![\w])(-?\d{1,3}(?:[.,]\d{1,3})?)\s*%",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class ValidationResult:
    """Result of deterministic answer validation."""

    valid: bool
    issues: tuple[str, ...]


def _as_json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _as_json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_as_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_as_json_safe(item) for item in value]
    return value


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "dimension",
        "period",
        "value",
        "rank",
        "share_pct",
        "share_of_total_pct",
        "difference",
        "difference_pct",
        "change",
        "change_pct",
        "current_value",
        "previous_value",
        "is_peak",
    )
    return {
        key: _as_json_safe(row[key])
        for key in keys
        if key in row and row[key] is not None
    }


def compact_evidence(
    evidence: list[dict[str, Any]],
    *,
    ranking_rows: int = 5,
    series_rows: int = 24,
    failed_tools: int = 3,
) -> list[dict[str, Any]]:
    """Keep only facts needed by the final-response model.

    SQL, bytes, latency and other execution metadata are removed.
    Temporal series retain more rows than rankings so the model can
    assess the full period without receiving the raw query payload.
    """
    compact: list[dict[str, Any]] = []
    failures = 0

    for item in evidence:
        result = item.get("result")
        if not isinstance(result, dict):
            continue

        success = result.get("success") is True

        if not success:
            if failures >= failed_tools:
                continue
            failures += 1
            compact.append(
                {
                    "tool": item.get("tool"),
                    "success": False,
                    "error": result.get("error"),
                }
            )
            continue

        entry: dict[str, Any] = {
            "tool": item.get("tool"),
            "success": True,
        }

        for key in (
            "metric",
            "aggregation",
            "dimension",
            "filters",
            "period",
            "granularity",
            "value",
            "value_a",
            "value_b",
            "difference",
            "difference_pct",
            "change",
            "change_pct",
            "current_value",
            "previous_value",
            "current_period",
            "previous_period",
            "period_a",
            "period_b",
            "brand",
            "brand_a",
            "brand_b",
            "peak",
            "start",
            "end",
        ):
            if key in result and result[key] is not None:
                entry[key] = _as_json_safe(result[key])

        rows = result.get("rows")
        if isinstance(rows, list):
            keep = (
                series_rows
                if result.get("granularity")
                else ranking_rows
            )
            entry["rows"] = [
                _compact_row(row)
                for row in rows[:keep]
                if isinstance(row, dict)
            ]
            if len(rows) > keep:
                entry["rows_truncated"] = {
                    "shown": keep,
                    "total": len(rows),
                }

        drivers = result.get("drivers")
        if isinstance(drivers, list):
            entry["drivers"] = [
                _as_json_safe(driver)
                for driver in drivers[:ranking_rows]
            ]

        compact.append(entry)

    return compact


def _walk_percentages(value: Any) -> list[float]:
    found: list[float] = []

    if isinstance(value, dict):
        for key, item in value.items():
            if (
                key in _PERCENT_KEYS
                or key.endswith("_pct")
                or key.endswith("_percentage")
            ):
                if (
                    isinstance(item, (int, float))
                    and not isinstance(item, bool)
                ):
                    found.append(float(item))
            found.extend(_walk_percentages(item))

    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_percentages(item))

    return found


def _supported_percentages(
    evidence: list[dict[str, Any]],
) -> list[float]:
    values: list[float] = []

    for item in evidence:
        result = item.get("result")
        if (
            isinstance(result, dict)
            and result.get("success") is True
        ):
            values.extend(_walk_percentages(result))

    return values


def _answer_percentages(answer: str) -> list[float]:
    values: list[float] = []

    for match in _PERCENT_RE.finditer(answer):
        raw = match.group(1).replace(",", ".")
        try:
            values.append(float(raw))
        except ValueError:
            continue

    return values


def _pct_is_supported(
    value: float,
    supported: list[float],
) -> bool:
    """Allow normal display rounding, not new arithmetic."""
    for candidate in supported:
        if abs(value - round(candidate, 1)) <= 0.051:
            return True
        if abs(value - round(candidate, 2)) <= 0.006:
            return True
        if abs(value - candidate) <= 0.001:
            return True

    return False


def _has_insertion_metric(
    evidence: list[dict[str, Any]],
) -> bool:
    for item in evidence:
        tool = str(item.get("tool") or "").lower()
        result = item.get("result")

        if not isinstance(result, dict):
            continue

        metric = str(result.get("metric") or "").lower()

        if (
            tool == "consultar_inserciones_bicomp"
            or metric == "total_insercion"
        ):
            return True

    return False


def _years_in_evidence(
    evidence: list[dict[str, Any]],
) -> set[int]:
    years: set[int] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, (date, datetime)):
            years.add(value.year)
        elif isinstance(value, str):
            for match in re.finditer(
                r"\b(20\d{2})\b",
                value,
            ):
                years.add(int(match.group(1)))

    for item in evidence:
        result = item.get("result")
        if (
            isinstance(result, dict)
            and result.get("success") is True
        ):
            visit(result.get("period"))
            visit(result.get("current_period"))
            visit(result.get("previous_period"))
            visit(result.get("period_a"))
            visit(result.get("period_b"))
            visit(result.get("rows"))

    return years


def validate_answer(
    answer: str,
    evidence: list[dict[str, Any]],
    *,
    finish_reason: str | None = None,
) -> ValidationResult:
    """Validate completion, presentation and high-value grounding rules."""
    issues: list[str] = []
    stripped = (answer or "").strip()

    if not stripped:
        issues.append("respuesta_vacia")
        return ValidationResult(False, tuple(issues))

    if finish_reason in {"length", "max_tokens"}:
        issues.append("respuesta_truncada_por_proveedor")

    if stripped[-1] not in ".!?)]}\"'":
        issues.append("respuesta_parece_cortada")

    if stripped.count("**") % 2 != 0:
        issues.append("markdown_negrita_incompleta")

    if stripped.count("```") % 2 != 0:
        issues.append("bloque_codigo_incompleto")

    if re.search(
        r"(?m)^\s*\|.*\|\s*$",
        stripped,
    ):
        issues.append("tabla_markdown_no_permitida")

    if (
        re.search(
            r"\b\d[\d\s.,]*\s+inserciones\b",
            stripped,
            re.IGNORECASE,
        )
        and not _has_insertion_metric(evidence)
    ):
        issues.append("row_count_presentado_como_inserciones")

    supported = _supported_percentages(evidence)

    if supported:
        unsupported = [
            value
            for value in _answer_percentages(stripped)
            if not _pct_is_supported(
                value,
                supported,
            )
        ]

        if unsupported:
            rendered = ", ".join(
                f"{value:g}%"
                for value in unsupported[:5]
            )
            issues.append(
                f"porcentajes_no_respaldados:{rendered}"
            )

    lower = stripped.lower()
    hypothesis_pos = lower.find("### hipótesis")

    factual_zone = (
        stripped
        if hypothesis_pos == -1
        else stripped[:hypothesis_pos]
    )

    for pattern in _RISKY_CAUSAL_PATTERNS:
        if re.search(
            pattern,
            factual_zone,
            re.IGNORECASE,
        ):
            issues.append(
                "causa_no_demostrada_fuera_de_hipotesis"
            )
            break

    if (
        re.search(
            r"\bestacional(?:idad|es)?\b",
            factual_zone,
            re.IGNORECASE,
        )
        and len(_years_in_evidence(evidence)) < 2
    ):
        issues.append(
            "estacionalidad_sin_ciclos_comparables"
        )

    return ValidationResult(
        valid=not issues,
        issues=tuple(issues),
    )
