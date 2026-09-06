"""Conservative read-only SQL validation for BigQuery."""

from __future__ import annotations

import re


class UnsafeQueryError(ValueError):
    """Raised when SQL violates the read-only policy."""


FORBIDDEN = ("INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "MERGE", "TRUNCATE")


def validate_read_only_sql(sql: str, allowed_tables: set[str] | None = None) -> str:
    normalized = re.sub(r"/\*.*?\*/|--[^\n]*", " ", sql, flags=re.DOTALL).strip()
    if not re.match(r"^(WITH\b[\s\S]+?\bSELECT\b|SELECT\b)", normalized, re.IGNORECASE):
        raise UnsafeQueryError("Solo se permiten consultas SELECT.")
    if any(re.search(rf"\b{word}\b", normalized, re.IGNORECASE) for word in FORBIDDEN):
        raise UnsafeQueryError("La consulta contiene una operación no permitida.")
    if ";" in normalized.rstrip(";"):
        raise UnsafeQueryError("No se permiten múltiples sentencias SQL.")
    if allowed_tables is not None:
        # Backticks also quote column names in BigQuery. Only FROM/JOIN
        # identifiers represent data sources that need allowlist validation.
        referenced = set(re.findall(r"\b(?:FROM|JOIN)\s+`([^`]+)`", normalized, re.IGNORECASE))
        unknown = referenced - allowed_tables
        if unknown:
            raise UnsafeQueryError("Tabla no autorizada: " + ", ".join(sorted(unknown)))
    return normalized
