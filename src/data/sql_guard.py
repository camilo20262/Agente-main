"""Parse BigQuery SQL and validate every physical source before execution."""
from __future__ import annotations
from sqlglot import parse, exp
from sqlglot.errors import ParseError
from sqlglot.optimizer.scope import traverse_scope


class UnsafeQueryError(ValueError):
    """SQL is not a single read-only query over authorized tables."""


def validate_read_only_sql(sql: str, allowed_tables: set[str] | None = None) -> str:
    try:
        statements = parse(sql, read='bigquery')
    except ParseError as exc:
        raise UnsafeQueryError('SQL inválido.') from exc
    if len(statements) != 1 or not isinstance(statements[0], exp.Query):
        raise UnsafeQueryError('Solo se permite una consulta SELECT.')
    tree = statements[0]
    if any(isinstance(node, (exp.DDL, exp.DML, exp.Command, exp.Into)) for node in tree.walk()):
        raise UnsafeQueryError('La consulta contiene una operación no permitida.')
    if any(isinstance(node, exp.Anonymous) and node.name.upper() == 'EXTERNAL_QUERY' for node in tree.walk()):
        raise UnsafeQueryError('No se permiten fuentes externas a la allowlist.')
    if allowed_tables is not None:
        for scope in traverse_scope(tree):
            for _, source in scope.selected_sources.values():
                if isinstance(source, exp.Table):
                    name = '.'.join(part.name for part in source.parts)
                    if name not in allowed_tables:
                        raise UnsafeQueryError('Tabla no autorizada: ' + name)
    return sql.strip().rstrip(';')
