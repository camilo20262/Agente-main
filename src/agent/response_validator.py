"""Compact evidence and deterministic, high-value output checks (not a semantic judge)."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import math
import re
from typing import Any
from src.analytics.calculations import number


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    issues: tuple[str, ...]


METADATA = {'sql', 'query_parameters', 'bytes_processed', 'duration_ms', 'query_metadata', 'evidence',
            'job_id', 'source_rows', 'row_count', 'valid_values', 'project', 'dataset', 'table', 'schema'}


def json_safe(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def compact_evidence(evidence, *, ranking_rows=10, series_rows=24, failed_tools=3):
    compact, failures = [], 0
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items() if k not in METADATA}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return json_safe(value)
    for item in evidence:
        result = item.get('result', {})
        if result.get('success') is not True:
            if failures < failed_tools:
                compact.append({'tool': item.get('tool'), 'success': False, 'error_type': result.get('error_type'), 'error': result.get('error')})
            failures += 1
            continue
        entry = {'id': item.get('id'), 'tool': item.get('tool'), **clean(result)}
        if item.get('historical'):
            entry.update(historical=True, origin_question=item.get('origin_question'))
        for key in ('rows', 'drivers', 'values'):
            rows = entry.get(key)
            if not isinstance(rows, list):
                continue
            keep = series_rows if key == 'rows' and result.get('granularity') else ranking_rows
            if len(rows) > keep:
                # Keep the latest window AND full-series statistics/peak, with an explicit omission marker.
                entry[key] = rows[-keep:] if result.get('granularity') else rows[:keep]
                entry[key + '_truncated'] = {'shown': keep, 'total': len(rows)}
        if 'schema' in result:
            entry['fields'] = list(result['schema'])
        compact.append(entry)
    return compact


NUMERIC = re.compile(r'(?<![\w])(-?\d+(?:[.,]\d+)*)(?:\s*(mil millones|millones|millón|millon|mil|[MK])\b)?', re.I)
PERCENT = re.compile(r'(?<![\w.,])(-?\d+(?:[.,]\d+)*)\s*(?:%|por ciento)', re.I)
MONTHS = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre')


def parse_display(raw):
    if ',' in raw and '.' in raw:
        raw = raw.replace('.', '').replace(',', '.') if raw.rfind(',') > raw.rfind('.') else raw.replace(',', '')
    elif raw.count('.') > 1 or raw.count(',') > 1:
        raw = raw.replace('.', '').replace(',', '')
    elif re.fullmatch(r'-?[1-9]\d{0,2}\.\d{3}', raw):
        raw = raw.replace('.', '')
    else:
        raw = raw.replace(',', '.')
    return float(raw)


def evidence_numbers(evidence, percentages=False):
    values = []
    def visit(value, key=''):
        if isinstance(value, dict):
            for k, v in value.items():
                if k not in METADATA:
                    visit(v, k)
        elif isinstance(value, list):
            for v in value:
                visit(v, key)
        elif number(value) is not None and (not percentages or key.endswith('_pct') or key.endswith('_percentage')):
            values.append(float(value))
    for item in evidence:
        if item.get('result', {}).get('success') is True and not item.get('historical'):
            visit(item['result'])
    return values


def _supported(displayed, candidates, raw, multiplier=1):
    decimals = len(re.split('[.,]', raw)[-1]) if '.' in raw or ',' in raw else 0
    if re.fullmatch(r'-?[1-9]\d{0,2}\.\d{3}', raw):
        decimals = 0
    tolerance = (0.5 * 10 ** -decimals) * multiplier + 1e-8
    return any(abs(displayed - candidate) <= tolerance for candidate in candidates)


def _evidence_strings(value):
    if isinstance(value, dict):
        return [s for k, v in value.items() if k not in METADATA for s in _evidence_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _evidence_strings(v)]
    return [value] if isinstance(value, str) else []


def _percentage_supported(match, text, candidates):
    raw = match[1]
    value = parse_display(raw) if ',' in raw and '.' in raw else float(raw.replace(',', '.'))
    if _supported(value, candidates, raw):
        return True
    clause = re.split(r'[;\n]', text[max(0, match.start()-65):match.end()])[ -1]
    # A fall of 12% is the ordinary verbal rendering of a signed -12% change.
    if value > 0 and re.search(r'cay[oó]|baj[oó]|disminu|ca[ií]da|reducci[oó]n|menos|inferior', clause, re.I):
        return _supported(-value, candidates, raw)
    return False


def validate_answer(answer: str, evidence: list[dict[str, Any]], *, finish_reason=None,
                    intent='open_analysis') -> ValidationResult:
    issues = []
    text = (answer or '').strip()
    if not text:
        return ValidationResult(False, ('respuesta_vacia',))
    if finish_reason in {'length', 'max_tokens'}:
        issues.append('respuesta_truncada_por_proveedor')
    if text[-1] not in '.!?)]}\"\'»' or re.search(r'\b(y|de|con|para|porque|que|el|la)\s*[.!]?$', text, re.I):
        issues.append('respuesta_parece_cortada')
    if text.count('**') % 2:
        issues.append('markdown_negrita_incompleta')
    if text.count('```') % 2:
        issues.append('bloque_codigo_incompleto')
    if re.search(r'\[[^\]]*$', text) or re.search(r'\]\([^)]*$', text):
        issues.append('markdown_enlace_incompleto')
    if re.search(r'(?m)^\s*\|.*\|\s*$', text):
        issues.append('tabla_markdown_no_permitida')
    successful = [i['result'] for i in evidence if i.get('result', {}).get('success') is True and not i.get('historical')]
    if intent not in {'out_of_domain', 'attachment_analysis', 'clarification'}:
        pcts = evidence_numbers(evidence, percentages=True)
        for match in PERCENT.finditer(text):
            if not _percentage_supported(match, text, pcts):
                issues.append('porcentaje_no_respaldado:' + match[0])
        numbers = evidence_numbers(evidence)
        # Exclude ISO dates, numbering, percentages and dates mentioned in actual scope/evidence.
        scrubbed = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '', text)
        scrubbed = PERCENT.sub('', scrubbed)
        strings = _evidence_strings(successful)
        # Digits inside exact source labels (e.g. a numbered brand) are not amounts.
        labels = [s for s in strings if re.search(r'\d', s) and re.search(r'[A-Za-zÁÉÍÓÚáéíóú]', s)
                  and not re.fullmatch(r'\d{4}-\d{2}-\d{2}.*', s)]
        for label in sorted(set(labels), key=len, reverse=True):
            scrubbed = re.sub(re.escape(label), '', scrubbed, flags=re.I)
        for source in strings:
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', source):
                day, month = int(source[8:10]), MONTHS[int(source[5:7])-1]
                scrubbed = re.sub(rf'\b{day}\s+de\s+{month}\b', '', scrubbed, flags=re.I)
        scrubbed = re.sub(r'(?m)^\s*(?:\*\*)?\d+[.)]\s*', '', scrubbed)
        known_years = set(re.findall(r'\b(?:19|20)\d{2}\b', str(compact_evidence(evidence))))
        for match in NUMERIC.finditer(scrubbed):
            raw, unit = match[1], (match[2] or '').lower()
            if raw in known_years and not unit:
                continue
            multiplier = {'mil millones': 1e9, 'millones': 1e6, 'millón': 1e6, 'millon': 1e6, 'm': 1e6, 'mil': 1e3, 'k': 1e3}.get(unit, 1)
            value = parse_display(raw) * multiplier
            if not _supported(value, numbers, raw, multiplier):
                clause = re.split(r'[;\n]', scrubbed[max(0, match.start()-60):match.end()])[-1]
                decrease = re.search(r'rest[oó]|cay[oó]|baj[oó]|disminu|ca[ií]da|reducci[oó]n|menos|inferior', clause, re.I)
                if not (value > 0 and decrease and _supported(-value, numbers, raw, multiplier)):
                    issues.append('cifra_no_respaldada:' + match[0])
        has_insertions = any(r.get('metric') == 'total_insercion' for r in successful)
        if re.search(r'\d[\d\s.,]*\s+inserciones\b', text, re.I) and not has_insertions:
            issues.append('row_count_presentado_como_inserciones')
    factual, in_hypothesis = [], False
    hypotheses = []
    for line in text.splitlines():
        if re.match(r'^\s*(?:#{1,6}\s*|\*\*)?hip[oó]tesis\b', line, re.I):
            in_hypothesis = True
        elif re.match(r'^\s*#{1,6}\s+', line):
            in_hypothesis = False
        (hypotheses if in_hypothesis else factual).append(line)
    factual = '\n'.join(factual)
    if intent == 'out_of_domain' and not evidence:
        # General explanations can discuss possible causes and seasonal patterns;
        # there is no observed business event to attribute without evidence.
        factual = ''
    causal = r'black\s*friday|navidad|lanzamiento|promoci[oó]n|branding|awareness|performance|audiencias? de alto poder adquisitivo|objetivo de campa[nñ]a|para llegar a.*audiencia|se debe a una campa[nñ]a'
    for line in factual.splitlines():
        if re.search(causal, line, re.I) and not re.search(r'no (?:se puede|permite|hay evidencia|demuestra)|sin evidencia|no es posible', line, re.I):
            # An explicitly queried dimension label is a fact, not necessarily a causal claim.
            labels = [str(r.get('dimension', '')).lower() for result in successful for r in result.get('rows', [])]
            if not any(label and label in line.lower() and re.search(causal, label, re.I) for label in labels):
                issues.append('causa_no_demostrada_fuera_de_hipotesis')
    temporal_rows = [r for result in successful if result.get('granularity') for r in result.get('rows', [])]
    months = {str(r.get('period', ''))[:7] for r in temporal_rows}
    if len(months) < 24:
        for line in factual.splitlines():
            if re.search(r'\bestacional(?:idad|es)?\b', line, re.I) and not re.search(r'no.*estacional|sin.*estacional', line, re.I):
                issues.append('estacionalidad_sin_ciclos_comparables')
    if re.search(r'driver:\s*no identificado', text, re.I):
        issues.append('driver_vacio_debe_omitirse')
    for result in successful:
        if result.get('is_partial'):
            annual_lines = [line for line in text.splitlines() if not re.search(r'\bno\b|sin |no equivale', line, re.I)]
            if re.search(r'total anual|a[nñ]o completo|total del a[nñ]o', '\n'.join(annual_lines), re.I):
                issues.append('periodo_parcial_presentado_como_anual')
            cutoff = result.get('effective_period', {}).get('end') or result.get('available_period', {}).get('end')
            if cutoff:
                month_name = MONTHS[int(cutoff[5:7])-1]
                if cutoff not in text and month_name not in text.lower():
                    issues.append('falta_fecha_de_corte')
    # Direction checks are limited to a single unambiguous comparison.
    comparisons = [r for r in successful if r.get('difference') is not None and number(r.get('difference')) is not None]
    if len(comparisons) == 1 and not comparisons[0].get('drivers'):
        delta = comparisons[0]['difference']
        if (delta < 0 and re.search(r'\b(aument[oó]|creci[oó]|subi[oó])\b', factual, re.I)) or (delta > 0 and re.search(r'\b(cay[oó]|baj[oó]|disminuy[oó])\b', factual, re.I)):
            issues.append('direccion_contradice_comparacion')
    return ValidationResult(not issues, tuple(dict.fromkeys(issues)))
