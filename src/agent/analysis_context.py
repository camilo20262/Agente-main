"""Validated scope shared by planning, execution, memory and finalization."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any
from src.agent.periods import resolve_period, iso


class UnresolvedComparisonError(ValueError):
    def __init__(self, context):
        super().__init__('La comparación requiere un periodo actual explícito y otro distinto; corrige period y comparison_period en el plan completo.')
        self.requested_context = context


@dataclass
class AnalysisContext:
    metric: str = 'inv_neta'
    filters: dict[str, Any] = field(default_factory=dict)
    requested_period: dict[str, str] = field(default_factory=dict)
    comparison_period: dict[str, str] = field(default_factory=dict)
    dimensions: list[str] = field(default_factory=list)
    intent: str = 'lookup'
    analysis: dict[str, Any] = field(default_factory=dict)
    operation: str = 'new_analysis'
    observed_period: dict[str, str] = field(default_factory=dict)
    available_period: dict[str, str] = field(default_factory=dict)
    unresolved_fields: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if not self.unresolved_fields:
            result.pop('unresolved_fields')
        return result

    @classmethod
    def resolve(cls, payload, memory, *, today: date, available=None) -> 'AnalysisContext':
        previous = memory.get('analysis_context') or {}
        inherit = payload.get('scope_mode') == 'inherit'
        filters = deepcopy(previous.get('filters', memory.get('last_filters', {}))) if inherit else {}
        for key in payload.get('remove_filters', []):
            filters.pop(key, None)
        filters.update(payload.get('filters') or {})
        metric = payload.get('metric') or (previous.get('metric', memory.get('last_metric')) if inherit else None) or 'inv_neta'
        period_inherits = inherit or (payload.get('period') or {}).get('kind') == 'inherit'
        prior_period = previous.get('requested_period', memory.get('last_period', {})) if period_inherits else {}
        anchor = (payload.get('period') or {}).get('anchor')
        if anchor == 'focus':
            prior_period = previous.get('requested_period', memory.get('last_period', {}))
        elif anchor == 'reference':
            prior_period = previous.get('comparison_period', {})
        elif anchor == 'peak':
            prior_period = resolve_period({'kind': 'peak'}, today=today, peak=memory.get('last_peak'))
        elif anchor == 'available':
            prior_period = {}
        requested = resolve_period(payload.get('period'), today=today, available=available,
                                   previous=prior_period, peak=memory.get('last_peak'))
        comparison_spec = payload.get('comparison_period')
        comparison_base = previous.get('comparison_period', {}) if (comparison_spec or {}).get('kind') == 'inherit' else requested
        comparison = resolve_period(comparison_spec, today=today, available=available,
                                    previous=comparison_base) if comparison_spec else {}
        if inherit and 'comparison_period' not in payload and payload['intent'] in {'diagnostic', 'period_comparison'}:
            comparison = deepcopy(previous.get('comparison_period', {}))
        context = cls(metric, filters, requested, comparison, payload.get('dimensions', []), payload['intent'], analysis=deepcopy(payload.get('analysis', {})), operation=payload.get('operation', 'new_analysis'), available_period=available or {})
        if comparison and (not requested or comparison == requested):
            context.comparison_period = {}
            context.unresolved_fields = ['comparison_period'] + ([] if requested else ['requested_period'])
            raise UnresolvedComparisonError(context)
        return context

    def bind(self, arguments: dict[str, Any], properties: dict[str, Any]) -> dict[str, Any]:
        """Fill omissions and reject silent widening or metric changes during research."""
        args = deepcopy(arguments)
        if 'metrica' in properties:
            if args.get('metrica', self.metric) != self.metric:
                raise ValueError('La herramienta cambia la métrica del alcance.')
            args['metrica'] = self.metric
        if 'filtros' in properties:
            filters = deepcopy(self.filters)
            for key, value in args.get('filtros', {}).items():
                if key in filters:
                    original = filters[key] if isinstance(filters[key], list) else [filters[key]]
                    narrowed = value if isinstance(value, list) else [value]
                    canonical = lambda values: {str(v).strip().upper() for v in values}
                    if not canonical(narrowed) <= canonical(original):
                        raise ValueError(f'La consulta cambia el filtro {key} fuera del alcance.')
                filters[key] = value
            args['filtros'] = filters
        for name, key in (('fecha_inicio', 'start'), ('fecha_fin', 'end')):
            if name in properties and self.requested_period.get(key):
                args.setdefault(name, self.requested_period[key])
        if self.requested_period and args.get('fecha_inicio') and args.get('fecha_fin'):
            if iso(args['fecha_inicio']) < iso(self.requested_period['start']) or iso(args['fecha_fin']) > iso(self.requested_period['end']):
                raise ValueError('La profundización sale del periodo solicitado.')
        for a, b in (('periodo_a', 'periodo_b'), ('periodo_actual', 'periodo_anterior')):
            if a in properties:
                for name, authoritative in ((a, self.requested_period), (b, self.comparison_period)):
                    supplied = args.get(name)
                    if supplied and supplied != authoritative:
                        resolved = resolve_period(supplied, today=iso(self.available_period['end']) if self.available_period.get('end') else date.today(),
                                                  available=self.available_period, previous=self.requested_period if name == b else authoritative)
                        if resolved != authoritative:
                            raise ValueError('Los periodos de la herramienta cambian la orientación o alcance de comparación.')
                    args[name] = deepcopy(authoritative)
                if not args[a] or not args[b]:
                    raise ValueError('Faltan periodos explícitos para comparar.')
        return args
