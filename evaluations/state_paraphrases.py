"""Unseen phrasings with independent expectations; all named entities are catalogued."""
from pathlib import Path
import argparse
import json
from evaluations.conversation_state import run_conversation
from evaluations.state_evaluator import assess_record

GROUPS = [
 [('Ordena las marcas por cuánto aumentaron, no por su tamaño.', {'intent': 'ranking_change', 'capability': 'rank_change'}),
  ('Hazlo ahora en términos porcentuales.', {'intent': 'ranking_change', 'capability': 'rank_change'}),
  ('Retrocede una ventana de comparación.', {'intent': 'ranking_change', 'capability': 'rank_change'}),
  ('Muéstrame el intervalo previo a ese.', {'intent': 'ranking_change', 'capability': 'rank_change'}),
  ('¿En cuáles marcas se está acelerando más el aumento?', {'intent': 'ranking_acceleration', 'capability': 'rank_acceleration'})],
 [('Revisa la inversión de Renault en 2024 con sus tendencias y distribución.', {'intent': 'open_analysis', 'contains_filters': {'marca': 'RENAULT'}}),
  ('Acota ese estudio a radio.', {'intent': 'open_analysis', 'contains_filters': {'marca': 'RENAULT'}}),
  ('Despliega la composición entre todos los medios.', {'intent': 'composition', 'removed_filters': ['medio', 'medio_agrupado']}),
  ('Quiero los formatos, pero únicamente dentro de radio.', {'intent': 'composition', 'dimension': 'formato'}),
  ('Cambia la marca del estudio por Ford.', {'intent': 'composition', 'contains_filters': {'marca': 'FORD'}, 'dimension': 'formato'})],
 [('Para Toyota durante 2024, localiza la semana con más inversión.', {'intent': 'temporal_extrema', 'capability': 'peak', 'contains_filters': {'marca': 'TOYOTA'}}),
  ('Consulta la semana inmediatamente previa a ese máximo.', {'intent': 'lookup', 'contains_filters': {'marca': 'TOYOTA'}}),
  ('En todo 2023, identifica el valle mensual de Toyota.', {'intent': 'temporal_extrema', 'capability': 'peak'}),
  ('¿Y el mínimo por semana de ese mismo año?', {'intent': 'temporal_extrema', 'capability': 'peak'}),
  ('Ubica ahora el mes de mayor inversión de Ford en 2024.', {'intent': 'temporal_extrema', 'capability': 'peak', 'contains_filters': {'marca': 'FORD'}})],
 [('Contrasta la inversión de Renault de 2024 frente a 2023.', {'intent': 'period_comparison', 'capability': 'comparison'}),
  ('Explora qué eje permite entender mejor esa diferencia.', {'intent': 'diagnostic_search', 'capability': 'dimension_search'}),
  ('Aplica la misma investigación a Toyota.', {'intent': 'diagnostic_search', 'capability': 'dimension_search', 'contains_filters': {'marca': 'TOYOTA'}}),
  ('Haz ese diagnóstico para 2023 respecto a 2022.', {'intent': 'diagnostic_search', 'capability': 'dimension_search'}),
  ('Separa las contribuciones por medio.', {'intent': 'diagnostic', 'capability': 'comparison', 'dimension': 'medio'})],
 [('Dame el total de inversión de Ford durante 2024.', {'intent': 'lookup', 'contains_filters': {'marca': 'FORD'}}),
  ('Repite el cálculo para Toyota.', {'intent': 'lookup', 'contains_filters': {'marca': 'TOYOTA'}}),
  ('¿Qué cuota del mercado reúnen las dos marcas anteriores?', {'intent': 'joint_share', 'capability': 'joint_share', 'entities': ['FORD', 'TOYOTA']}),
  ('Añade Renault a ese conjunto y calcula su participación agregada.', {'intent': 'joint_share', 'capability': 'joint_share', 'entities': ['FORD', 'TOYOTA', 'RENAULT']}),
  ('Conserva las tres y llévalo al año 2023.', {'intent': 'joint_share', 'capability': 'joint_share', 'entities': ['FORD', 'TOYOTA', 'RENAULT']})],
 [('Clasifica los anunciantes por inversión en televisión en 2024.', {'intent': 'ranking', 'dimension': 'anunciante'}),
  ('¿Cómo queda ese listado en el año previo?', {'intent': 'ranking', 'dimension': 'anunciante'}),
  ('¿Qué anunciantes sufrieron la mayor reducción en 2024 frente a 2023?', {'intent': 'ranking_change', 'capability': 'rank_change', 'dimension': 'anunciante'}),
  ('Muestra las marcas que más incrementaron porcentualmente en 2023 frente a 2022.', {'intent': 'ranking_change', 'capability': 'rank_change', 'dimension': 'marca'}),
  ('Ahora ordena las empresas por volumen de inversión en prensa en 2024.', {'intent': 'ranking', 'dimension': 'anunciante'})],
]


# Calendar and measure expectations are independent of the emitted plan. They
# close false positives where the capability was right but its focus/basis was not.
def year(number):
    return {'start': f'{number}-01-01', 'end': f'{number}-12-31'}


for i, (focus, reference, basis) in enumerate([
    ('07', '06', 'absolute'), ('07', '06', 'percent'), ('06', '05', 'percent'),
    ('05', '04', 'percent'), ('05', '04', 'percent')]):
    days = {'07': 31, '06': 30, '05': 31, '04': 30}
    GROUPS[0][i][1].update(filters={}, dimensions=['marca'],
        requested_period={'start': f'2026-{focus}-01', 'end': f'2026-{focus}-{days[focus]}'},
        comparison_period={'start': f'2026-{reference}-01', 'end': f'2026-{reference}-{days[reference]}'},
        contains_analysis={'change_basis': basis})
for i, (_, expected) in enumerate(GROUPS[1]):
    expected.update(requested_period=year(2024), comparison_period={},
        filters={'marca': 'FORD' if i == 4 else 'RENAULT', **({'medio': 'RADIO'} if i in {1, 3, 4} else {})})
GROUPS[1][1][1]['preserve_fields'] = ['dimensions', 'analysis']
for i, (_, expected) in enumerate(GROUPS[2]):
    expected.update(requested_period=year(2023 if i in {2, 3} else 2024), comparison_period={},
                    filters={'marca': 'FORD' if i == 4 else 'TOYOTA'})
GROUPS[2][1][1]['requested_period'] = {'start': '2024-03-25', 'end': '2024-03-31'}
for i, (_, expected) in enumerate(GROUPS[3]):
    expected.update(requested_period=year(2023 if i >= 3 else 2024),
        comparison_period=year(2022 if i >= 3 else 2023), filters={'marca': 'TOYOTA' if i >= 2 else 'RENAULT'})
for i, (_, expected) in enumerate(GROUPS[4]):
    expected.update(requested_period=year(2023 if i == 4 else 2024), comparison_period={},
                    filters={'marca': ['FORD', 'TOYOTA'][i]} if i < 2 else {})
for i, (_, expected) in enumerate(GROUPS[5]):
    expected.update(requested_period=year(2023 if i in {1, 3} else 2024),
        comparison_period=year(2022 if i == 3 else 2023) if i in {2, 3} else {},
        filters={'medio_agrupado': ['TV ABIERTA', 'TV CABLE']} if i < 2 else {'medio': 'PRENSA'} if i == 4 else {})
GROUPS[5][2][1]['contains_analysis'] = {'direction': 'asc', 'change_basis': 'absolute'}
GROUPS[5][3][1]['contains_analysis'] = {'direction': 'desc', 'change_basis': 'percent'}


def run(output, groups=None):
    output = Path(output)
    catalog = json.loads(Path('evaluations/conversation_state/catalogs.json').read_text())
    assert {'RENAULT', 'FORD', 'TOYOTA'} <= set(catalog['marca']['values'])
    all_records = []
    for i, group in enumerate(GROUPS, 1):
        if groups is not None and i not in groups: continue
        result = run_conversation([q for q, _ in group], output / f'group-{i}', f'paraphrase-{i}')
        for record, (_, expected) in zip(result['records'], group):
            record['expected'] = expected
            record['assessment'] = assess_record(record, expected)
            all_records.append(record)
    summary = {'cases': len(all_records), 'passed': sum(r['assessment']['passed'] for r in all_records), 'records': all_records}
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str)+'\n')
    print(json.dumps({'cases': summary['cases'], 'passed': summary['passed']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true'); parser.add_argument('--output', required=True)
    parser.add_argument('--groups', help='Comma-separated group numbers; preserves each full conversation.')
    args = parser.parse_args()
    if not args.live: parser.error('Requires --live.')
    run(args.output, [int(v) for v in args.groups.split(',')] if args.groups else None)
