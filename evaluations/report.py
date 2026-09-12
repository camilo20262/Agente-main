"""Build the audit report from preserved live runs, without calling external services."""
from __future__ import annotations

import json
import math
from pathlib import Path
from statistics import median
from types import SimpleNamespace

from evaluations.benchmark import assess, cases


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'evaluations/results'


def read(path):
    return json.loads(path.read_text())


def cell(value):
    return str(value).replace('|', '/').replace('\n', ' ')


def main():
    runs = sorted(((p.parent.name, read(p)) for p in RESULTS.glob('*/summary.json')),
                  key=lambda item: item[1]['started_at'])
    metadata = {c['id']: c for group in cases() + read(ROOT / 'evaluations/holdout_cases.json') for c in group}
    latest = {}
    for name, run in runs:
        for record in run['records']:
            latest[record['id']] = (name, record)
    reviews_path = RESULTS / 'manual_review.json'
    reviews = read(reviews_path) if reviews_path.exists() else {}
    records = []
    for case_id, (name, original) in sorted(latest.items()):
        record = dict(original)
        result = SimpleNamespace(**record['result'])
        verdict = assess({**record, **metadata.get(case_id, {})}, result)
        manual = reviews.get(name + '/' + case_id, {})
        issues = list(dict.fromkeys(verdict['issues'] + manual.get('issues', [])))
        record.update(run=name, issues=issues, status='FAIL' if issues else 'PASS',
                      automatic_status=verdict['status'], manual_review=manual)
        records.append(record)
    passed = sum(r['status'] == 'PASS' for r in records)
    acceptance = next((run for name, run in runs if name == 'acceptance'), None)
    report = ['# Benchmark real del agente BI', '',
        'Fecha: 11 de septiembre de 2026. Ejecuciones del servicio real con el proveedor NVIDIA '
        'configurado y la tabla BigQuery autorizada. Los JSON incluyen plan, argumentos, SQL, '
        'evidencia, respuesta, errores, contadores y latencia. No se usan respuestas simuladas en esta batería.', '',
        '## Resultado y alcance', '',
        f'**Último resultado por pregunta: {passed}/{len(records)} PASS y {len(records)-passed} FAIL.** '
        'Se toma siempre el intento más reciente, aunque sea peor que uno anterior; no se selecciona el mejor.', '']
    if acceptance:
        report += [f'La corrida completa `acceptance` comenzó en `{acceptance["started_at"]}`; '
                   f'huella SHA-256 del código Python de `src`: `{acceptance["source_fingerprint"]}`. '
                   'Las correcciones posteriores, si existen, aparecen como repeticiones separadas con su propia procedencia.', '']
    report += ['El corpus contiene 28 preguntas independientes, una conversación obligatoria de siete turnos, '
        'otra de tres turnos sobre el mes pico y ocho preguntas adicionales con dimensiones/métricas diferentes. '
        'Cuatro rankings se generan a partir del modelo semántico. Las ocho preguntas adicionales se introdujeron '
        'después de las primeras correcciones; tras inspeccionarlas se convirtieron en regresiones y ya no son '
        'un conjunto ciego independiente.', '',
        '**PASS significa que supera los criterios del evaluador y las objeciones manuales registradas.** '
        'No certifica toda atribución cualitativa ni comprensión universal. Las aclaraciones correctas ante '
        'categorías ambiguas y la ausencia controlada de una marca inventada tienen criterios propios. '
        'Un fallback de un análisis con datos se cuenta como FAIL.', '',
        '## Verificación automatizada y numérica', '']
    verification_path = RESULTS / 'final_verification.json'
    if verification_path.exists():
        verification = read(verification_path)
        report += [f'Suite: **{verification["pytest"]["passed"]} aprobados, '
                   f'{verification["pytest"]["failed"]} fallidos**, '
                   f'{verification["pytest"]["warnings"]} aviso de deprecación de PyPDF2. '
                   'Baseline: 106 aprobados y 26 fallidos sobre 132 casos. '
                   f'El inventario final aumenta en {verification["pytest"]["passed"]-132} casos; '
                   'incluye regresiones nuevas y pruebas migradas al contrato vigente. '
                   '[Verificación del entorno y código](evaluations/results/final_verification.json).', '']
    reference = read(RESULTS / 'numeric_reference.json')
    report += [f'**{sum(c["passed"] for c in reference["checks"])}/{len(reference["checks"])} '
        'contrastes numéricos independientes aprobados.** SQL de referencia sin LLM verificó totales, '
        'ventanas enero-julio, variación, inserciones y ratio. '
        '[SQL, valores y contrastes](evaluations/results/numeric_reference.json).', '',
        'BMW como marca en 2025: 1.595.350,10 de inversión neta. Volvo enero-julio de 2026: '
        '1.490.266,32 frente a 1.426.721,81 en enero-julio de 2025, variación calculada +4,45 %. '
        'Compararlo con todo 2025 daría una lectura incompatible. La cobertura global observada '
        'es 2019-01-01 a 2026-07-31 y no certifica completitud diaria.', '',
        '## Historial de iteraciones', '',
        'Los puntajes históricos son los guardados originalmente. **El evaluador se fortaleció durante '
        'el trabajo; esos porcentajes no son directamente comparables.** En particular, `release` '
        'registró 36/38, pero omitía comprobar la segunda dimensión de cuatro rankings: con ese '
        'criterio serían 32/38. `holdout` registró 8/8, pero una respuesta omitía el porcentaje '
        'conjunto solicitado: con ese criterio serían 7/8. Se corrigieron tanto producto como evaluación. '
        'Los artefactos originales se conservan. `reasoning_probe` se ejecutó antes de corregir errores '
        'de calendario y no demuestra que un modo de razonamiento sea superior a otro.', '',
        '| Corrida | Casos | PASS original | FAIL original | Evidencia |',
        '|---|---:|---:|---:|---|']
    for name, run in runs:
        report.append(f'| {name} | {run["count"]} | {run["passed"]} | {run["failed"]} | '
                      f'[JSON](evaluations/results/{name}/summary.json) |')
    report += ['', '## Preguntas y últimos resultados', '',
        'BQ cuenta jobs ejecutados; una herramienta puede requerir varios. LLM incluye planificación, '
        'investigación, redacción y reparaciones. El número de pasos incluye intentos fallidos. '
        'La intención es la detectada; un seguimiento puede conservar un diagnóstico previo aunque '
        'su redacción aislada parezca pedir composición.', '',
        '| ID / pregunta | Intención | Herramientas | Pasos | BQ | LLM | Resultado / procedencia |',
        '|---|---|---|---:|---:|---:|---|']
    for r in records:
        result = r['result']; turn = result['metrics'].get('turn', {})
        tools = ', '.join(dict.fromkeys(e['tool'] for e in result['evidence'])) or 'ninguna'
        link = f'evaluations/results/{r["run"]}/{r["id"]}.json'
        outcome = r['status'] + (': ' + ', '.join(r['issues']) if r['issues'] else '')
        report.append(f'| {r["id"]}: {cell(r["question"])} | {result["plan"].get("intent")} | '
                      f'{tools} | {result["steps"]} | {turn.get("bigquery_queries", 0)} | '
                      f'{turn.get("total_llm_calls", 0)} | [{cell(outcome)}]({link}) ({r["run"]}) |')
    report += ['', '## Latencia y consumo observados', '',
        'Estadística del último intento por pregunta, incluyendo fallos, aclaraciones y caché. '
        'P95 usa el rango más próximo superior. Son observaciones del endpoint y entorno concretos, '
        'no un SLA ni una medición de carga concurrente de producción.', '',
        '| Medida | Total | Mediana | P95 | Máximo |', '|---|---:|---:|---:|---:|']
    for title, key in [('Latencia (s)', 'elapsed_s'), ('Pasos', 'steps'), ('Jobs BigQuery', 'bigquery_queries'), ('Llamadas LLM', 'total_llm_calls')]:
        values = sorted(r['elapsed_s'] if key == 'elapsed_s' else r['result']['steps'] if key == 'steps'
                        else r['result']['metrics'].get('turn', {}).get(key, 0) for r in records)
        report.append(f'| {title} | {sum(values):.2f} | {median(values):.2f} | '
                      f'{values[math.ceil(.95*len(values))-1]:.2f} | {max(values):.2f} |')
    report += ['', 'Los tokens y bytes por job quedan en cada JSON. No se estiman costos monetarios sin '
        'tarifas/contrato aplicables. Los ceros de bytes reportados por caché no se sustituyen por estimaciones.', '',
        '## Fallos pendientes y revisión de respuestas', '']
    failed = [r for r in records if r['status'] == 'FAIL']
    if failed:
        report += [f'- **{r["id"]}** ({r["run"]}): ' + ', '.join(r['issues']) + '. '
                   + r['manual_review'].get('note', 'Consultar plan, respuesta y eventos en el JSON enlazado.') for r in failed]
    else:
        report += ['No quedan fallos bajo los criterios aplicados en estos últimos intentos. '
                   'Las regresiones observadas entre rondas impiden interpretar ese resultado como garantía universal.']
    report += ['', 'La inspección de código y respuestas está recogida en '
        '[AUDITORIA_AGENTE_BI_FINAL.md](AUDITORIA_AGENTE_BI_FINAL.md). '
        'El alcance exacto de las revisiones manuales, si existen, está en '
        '[manual_review.json](evaluations/results/manual_review.json).', '',
        '## Reproducción', '', '```sh', '.venv/bin/python -m pytest -q',
        '.venv/bin/python -m evaluations.benchmark --live --cases evaluations/results/acceptance_cases.json --output evaluations/results/new_run --workers 2',
        '.venv/bin/python -m evaluations.report', '```', '',
        'La segunda orden realiza llamadas reales y requiere credenciales válidas del entorno. '
        'Usar un directorio nuevo conserva el historial. Los resultados contienen datos de negocio y SQL, '
        'por lo que deben permanecer bajo controles de acceso equivalentes a la fuente.', '']
    (ROOT / 'BENCHMARK_AGENTE_BI.md').write_text('\n'.join(report))
    (RESULTS / 'latest_assessment.json').write_text(json.dumps({'count': len(records), 'passed': passed,
        'failed': len(records)-passed, 'records': [{k: r[k] for k in ('id', 'run', 'status', 'issues', 'automatic_status', 'manual_review')} for r in records]}, ensure_ascii=False, indent=2) + '\n')
    print(f'Report generated: {passed}/{len(records)} PASS.')


if __name__ == '__main__':
    main()
