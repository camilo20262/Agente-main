"""Build the reviewable audit from immutable runs and independent reassessments."""
import json
import re
from pathlib import Path
from evaluations.state_report import reports, ROOT


def build():
    history = reports()
    by_name = {r['round']: r for r in history}
    def latest(names):
        return next((by_name[n] for n in names if n in by_name), None)
    original = latest(['default_original', 'release_original', 'contract_original', 'reviewed_original', 'verification_original', 'acceptance_original', 'final_original', 'iteration4'])
    additional = latest(['completion_additional', 'default_additional', 'release_additional', 'guarded_additional', 'contract_additional', 'reviewed_additional', 'verification_additional', 'acceptance_additional', 'final_additional', 'additional4'])
    baseline = by_name['baseline']
    paraphrases = latest(['default_paraphrases', 'release_paraphrases', 'contract_paraphrases', 'paraphrases2'])
    verification_path = ROOT / 'verification.json'
    verification = json.loads(verification_path.read_text()) if verification_path.exists() else {}
    test_output = (verification.get('checks') or [{}])[0].get('output', '')
    count = re.search(r'(\d+) passed', test_output)
    test_note = f"**{count[1]} pruebas aprobadas**, incluidas {int(count[1])-284} nuevas" if count else 'consultar el artefacto de verificación'
    lines = ['# Auditoría del estado conversacional', '', 'Fecha: 12 de septiembre de 2026.', '',
        'Esta revisión reproduce la conversación nueva de doce turnos y corrige clases de error en intención, calendario, alcance y evidencia. Las ejecuciones usan una instancia del servicio y un historial ordenado por conversación. Se preservan los fallos y se evalúan los turnos contra expectativas externas al plan del modelo.', '',
        '## Resultado y límites', '',
        f"- Baseline original: **{baseline['passed']}/12** turnos conformes al evaluador de estado.",
        f"- Última conversación original completa, `{original['round']}`: **{original['passed']}/12**.",
        f"- Última conversación adicional completa, `{additional['round']}`: **{additional['passed']}/12**.",
        f"- Última batería completa de paráfrasis, `{paraphrases['round']}`: **{paraphrases['passed']}/30** con el evaluador reforzado.",
        f'- Suite local: {test_note}. Se conservan los 284 casos anteriores; resultado y comandos en [verification.json](evaluations/conversation_state/verification.json).',
        '- Se ejecutaron baterías completas de 30 paráfrasis en seis conversaciones, con entidades verificadas en el catálogo. Las repeticiones posteriores conservan conversaciones completas por grupo; no sustituyen los fallos originales.',
        '- Un PASS acredita los contratos comprobados, no comprensión universal ni causalidad. Hay variación entre llamadas al proveedor y limitaciones de calidad de la fuente.', '',
        'La suite anterior de 46 preguntas permanece como registro histórico en [BENCHMARK_AGENTE_BI.md](BENCHMARK_AGENTE_BI.md). Su resultado no cubría estas nuevas conversaciones. No se suman ambas suites para afirmar una tasa global.', '',
        '## Causas raíz y correcciones', '',
        '| Clase | Causa comprobada | Corrección y límite |', '|---|---|---|',
        '| A. Crecimiento frente a tamaño | El planner podía devolver ranking de inversión; la suficiencia aceptaba filas. | `ranking_change` exige dos ventanas y cambios calculados; `ranking_acceleration`, tres. Orden absoluto por defecto, porcentual explícito con bases no positivas excluidas. Se declara el criterio. |',
        '| B. Referencia temporal | El mes anterior se anclaba al corte global; operaciones y referencias heredadas podían desplazar dos veces o reemplazar una fecha explícita. | Anclas `focus`, `reference`, `peak`, `available`; calendario determinístico; el desplazamiento mueve el foco una vez. Una referencia explícita precede a la memoria. Un mes actual anclado al foco conserva ese mes, aunque los filtros se reemplacen. |',
        '| C. Diagnóstico abierto | No existía comparación obligatoria de candidatos; calidad de datos de un ranking podía acreditar un diagnóstico. | Selección de hasta tres familias no redundantes del YAML; particiones completas, mínimo dos útiles y puntuación de concentración del cambio absoluto. Se conservan candidatos declarados válidos. No se interpreta como causa ni como varianza explicada. |',
        '| D. Filtro convertido en eje | Unión de filtros heredados; además, `breakdown` forzaba herencia incluso con `scope_mode=replace`. | Promoción elimina solo el filtro del eje; otros filtros sobreviven. Un desglose independiente respeta reemplazo. Restaurar con un eje declarado también promueve ese filtro. |',
        '| E. Extremos | Se exigía un pico conocido para descubrirlo, confundiendo descubrimiento e inspección. | Una serie calcula máximo/mínimo, empates y granularidad. Inspeccionar un extremo conocido usa su intervalo; consultar el periodo previo no lo redescubre. |',
        '| F. Turnos fallidos | La memoria solo avanzaba tras éxito y el siguiente año heredaba una consulta antigua. | Alcance solicitado, último éxito, alcance de evidencia confirmada y estrategia separados. La validación de vocabulario y la revisión LLM fallidas también conservan el alcance estructuralmente válido; no acreditan evidencia. |',
        '| G. Conjuntos | Referentes incompletos prevalecían sobre valores explícitos; una entidad ausente podía producir un share parcial presentado como completo. | Entidades tipadas de una dimensión, conjunto explícito prioritario, agregación única contra universo completo. Si falta una entidad se devuelve no-data/aclaración, sin aprobar participación conjunta. |',
        '| H. Anunciante y medio | `TELEVISION` no era una etiqueta exacta; un filtro digital heredado podía coexistir con televisión. | Se conserva `anunciante`; las categorías pequeñas se validan contra catálogos reales. Televisión genérica usa la agrupación configurada de `medio_agrupado`; no se fusionan etiquetas. |', '',
        'No se introdujeron rutas por nombres comerciales, años o preguntas literales en el compilador, calendario o capacidades. El planner conserva una validación lingüística acotada de etiquetas/sinónimos de agrupación y del seguimiento elíptico; no es un parser universal. Las entidades del corpus están solo en evaluación y datos de referencia.', '',
        '## Operaciones de alcance', '',
        '| Operación | Hereda | Cambia o elimina |', '|---|---|---|',
        '| `new_analysis` | Calendario solo si se declara `inherit` o un ancla de foco. | Filtros y objetivo propios mediante `replace`. |',
        '| `filter_scope` | Intención, ejes, criterio, calendario, profundidad y estrategia previa. | Agrega/restringe filtros; los argumentos de alcance viejos se retiran de la estrategia reutilizada. |',
        '| `change_entity` | Métrica, dimensiones y estrategia. | Reemplaza entidad. Conserva referencia si no se declaró otra; no borra fechas explícitas. |',
        '| `change_period` | Entidad, métrica, dimensiones y objetivo. | Reemplaza foco; comparación solo si forma parte del objetivo. |',
        '| `shift_period` | Objetivo y filtros. | Desplaza ventana respecto del foco/referencia/extremo; deriva la referencia comparativa cuando corresponde. |',
        '| `breakdown` | Entidad, métrica y calendario según modo. | Promueve eje y elimina su filtro. Si hereda comparación, calcula contribuciones. |',
        '| `compare_periods` / `compare_entities` | Alcance compatible. | Declara referencia temporal o pareja tipada; elimina filtro que restringiría indebidamente esa pareja. |',
        '| `explain_difference` | Foco de una diferencia vigente. | Selecciona contribuciones temporales o entre entidades; no desplaza de nuevo el foco por rutina. |',
        '| `discover_extreme` / `inspect_peak` | Alcance solicitado / extremo confirmado. | Descubre en serie completa / investiga intervalo ya calculado. |',
        '| `joint_entities` | Periodo y filtros ajenos al numerador. | Conjunto tipado y eliminación del filtro de su dimensión para preservar el denominador. |',
        '| `restore_scope` | Último alcance de la entidad localizada en historial. | Recupera el último objetivo y estrategia de la entidad. Un nuevo desglose combinado exige analysis.restore_with_breakdown=true. Historial finito. |', '',
        '## Evidencia, matemática y presupuesto', '',
        '`requirements.py` separa objetivo, capacidad y herramienta. `sufficiency.py` exige el tipo de evidencia: niveles no acreditan crecimiento, totales no acreditan picos y un mix no acredita drivers. El evaluador añade expectativas independientes de dimensión, filtros, periodos, referencia y entidades.', '',
        'Crecimiento: diferencia entre agregados completos de dos ventanas equivalentes; aceleración: diferencia entre cambios de tres ventanas. Una categoría sin filas en una ventana con datos se trata como cero, y esa suposición se informa. No se acredita completitud individual de entidades.', '',
        'Diagnóstico: puntuación = contribución absoluta de las tres categorías informadas principales / contribución absoluta de toda la partición. Penaliza implícitamente cambios con etiqueta ausente. Solo compara las dimensiones evaluadas; granularidad y cardinalidad afectan la puntuación. No es causalidad ni selección estadística de variables. Se evalúan hasta tres dimensiones y dos agregaciones por dimensión; no se trunca la partición antes de calcular la puntuación.', '',
        'El registro tiene 24 herramientas. Las nuevas capacidades usan una llamada de herramienta, pero crecimiento requiere dos jobs de agregación, aceleración tres y diagnóstico hasta seis, además de metadatos cuando no están en caché. El límite de ocho pasos no aumentó. Una corrección de argumentos y una reparación narrativa siguen acotadas. Los catálogos de `medio` y `medio_agrupado` pueden agregar dos consultas de metadatos por caché fría.', '',
        'Los hechos numéricos de crecimiento, extremos y conjuntos se renderizan determinísticamente. El narrador de diagnósticos selecciona hechos y redacta interpretación cualitativa. Los rankings conservan hasta diez filas factuales aunque el narrador seleccione menos. La validación de números no demuestra que toda interpretación cualitativa sea correcta.', '',
        '## Revisión semántica antes de consultar', '',
        'Las primeras repeticiones mostraron errores de intención con JSON válido pese a las invariantes. Se incorporó `request_review.py`: una revisión breve del mensaje actual, propuesta y memoria compacta, sin catálogo de herramientas ni SQL. Puede corregir intención, operación y alcance; el compilador vuelve a validar el contrato. Se ejecuta como máximo una revisión lógica por turno analítico de texto; no agrega consultas de datos y se omite en imágenes/respuestas conceptuales. Es experimental y está desactivada por defecto (`PLAN_SEMANTIC_REVIEW=false`). Al activarla añade una llamada LLM, además de la planificación. En `guarded_additional`, turno 10, convirtió un año completo correctamente interpretado en octubre de ese año; esa regresión no permite recomendarla como ruta normal. La reparación de plan sigue limitada a una. No sustituye el evaluador externo ni garantiza corrección semántica universal.', '',
        'Las pruebas simuladas preexistentes inyectan planes ya interpretados y desactivan explícitamente esa revisión para conservar sus secuencias de respuestas. Hay pruebas específicas del paso de revisión y sus límites, además de conversaciones reales con la revisión habilitada. Esta distinción evita presentar un mock como validación del modelo.', '',
        '## Memoria, fallos y trazabilidad', '',
        '`last_requested_scope` es el foco de seguimiento; `last_successful_scope` identifica un turno completado; `last_confirmed_evidence_scope` identifica el alcance con evidencia utilizable; `last_analysis_strategy` conserva las perspectivas solicitadas. Un resultado parcial puede tener evidencia confirmada sin completar la intención. Si el foco se resuelve pero la comparación se refiere al mismo periodo, se rechaza la consulta y se conservan intención, entidad y foco con unresolved_fields=[comparison_period]. Esa referencia no se acredita ni se ejecuta; el seguimiento puede resolverla. Si tampoco existe foco válido, se marca también requested_period como pendiente.', '',
        'Si el proveedor falla antes de producir un alcance válido, solo se puede conservar el mensaje/interpretación pendiente y el historial. No se inventa un alcance estructurado. Persistir un plan y su contexto se hace como pareja para evitar mezclar un segundo plan rechazado con el contexto de un intento anterior.', '',
        'Las corridas intermedias se hicieron durante iteraciones de código: sus hashes describen los archivos al iniciar cada conversación, y no certifican módulos previamente importados por un proceso largo. Las baterías `default_*` y `completion_additional` usan la configuración final sin revisor. `default_original` y `default_additional` se iniciaron antes del último ajuste que permite términos de entidad configurados en YAML (por ejemplo, empresa); ese ajuste tiene una regresión específica y no cambia los enunciados de esas dos secuencias. `default_paraphrases` se inicia con ese ajuste incorporado. Después se añadió la conservación de campos válidos cuando la referencia comparativa es irresoluble; `completion_additional` y la suite local verifican ese último cambio. El manifiesto de verificación registra los archivos finales.', '',
        'Las trazas registran memoria antes/después, plan crudo, transición compilada, alcance heredado/resuelto, mutaciones, requisitos, capacidades, consultas, argumentos, SQL, parámetros, jobs, suficiencia, validación y motivo de parada. Están en [evaluations/conversation_state](evaluations/conversation_state). No se incorporan cifras fallidas a la respuesta.', '',
        '## Conversación original: antes y después', '',
        '| Turno y pregunta | Baseline | Última ejecución completa |', '|---|---|---|']
    for before, after in zip(baseline['records'], original['records']):
        lines.append(f"| {before['id']}: {before['question']} | {'PASS' if before['passed'] else 'FAIL: '+', '.join(before['issues'])} | {'PASS' if after['passed'] else 'FAIL: '+', '.join(after['issues'])} |")
    lines += ['', f"[Baseline completo](evaluations/conversation_state/baseline/summary.json) · [Después: {original['round']}](evaluations/conversation_state/{original['round']}/summary.json). Cada archivo incluye la respuesta literal y evidencia; no se reconstruyen respuestas favorables para el informe.", '',
        '## Conversación adicional', '', '| Turno y pregunta | Intención | Foco / referencia | Resultado |', '|---|---|---|---|']
    for r in additional['records']:
        scope = r['scope']; a=scope.get('requested_period',{}); b=scope.get('comparison_period',{})
        lines.append(f"| {r['id']}: {r['question']} | {r['intent']} | {a.get('start','—')} a {a.get('end','—')} / {b.get('start','—')} a {b.get('end','—')} | {'PASS' if r['passed'] else 'FAIL: '+', '.join(r['issues'])} |")
    lines += ['', f"[Conversación adicional completa](evaluations/conversation_state/{additional['round']}/summary.json). Un desglose tras análisis abierto puede conservar `open_analysis` si elimina el filtro del eje y entrega la distribución; se admite esa alternativa sin aceptar filtros indebidos.", '',
        '## Historial de esta auditoría', '', '| Ejecución completa | Casos | PASS | FAIL | Revisión LLM observada |', '|---|---:|---:|---:|---|']
    for r in history:
        lines.append(f"| [{r['round']}](evaluations/conversation_state/{r['round']}/summary.json) | {r['cases']} | {r['passed']} | {r['cases']-r['passed']} | {'Sí' if r['semantic_review_observed'] else 'No'} |")
    lines += ['', '## Casos no conformes en las últimas baterías completas', '',
        'Se muestran todos los fallos de las últimas secuencias, sin sustituirlos por éxitos de otras corridas. Los artefactos distinguen errores de interpretación, falta de datos y fallos de transporte.', '',
        '| Batería y turno | Solicitud | Contratos incumplidos | Motivo de parada |', '|---|---|---|---|']
    for run in [original, additional, paraphrases]:
        for r in run['records']:
            if not r['passed']:
                lines.append(f"| {run['round']} / {r['id']} | {r['question']} | {', '.join(r['issues'])} | {str(r['stop_reason'])[:180]} |")
    lines += ['',
        'En `default_paraphrases` hubo cinco casos no conformes: el desglose entre todos los medios conservó RADIO; la semana anterior al máximo no tenía filas; dos rankings conservaron televisión donde el oráculo exige un universo sin medio; y prensa terminó consultando REVISTAS después de una reparación de catálogo. En los dos rankings, omitir el medio admite más de una lectura conversacional: el FAIL expresa la política de reinicio adoptada por este oráculo, y no prueba un error aritmético. La clasificación de prensa y la promoción del filtro sí requieren mayor robustez de interpretación. La falta de filas de la semana está confirmada por SQL independiente.', '',
        'Estos resultados no acreditan aceptación estable de todas las clases en lenguaje libre. Se completaron implementación, regresiones, reproducción y auditoría; quedan riesgos P0 de interpretación documentados. Repetir hasta obtener una corrida favorable no sustituye resolverlos ni validar una política de alcance con usuarios.']
    lines += ['', 'Las revisiones actuales están en `review.json`; las evaluaciones originales permanecen en sus JSON. Se normaliza mayúsculas/espacios al evaluar entidades. El eje temporal puede aparecer como `fecha` o mediante granularidad. La equivalencia de DIGITAL entre dos columnas se admite solo en el evaluador para ese valor confirmado; no reescribe consultas. La revisión más estricta comprueba además fechas, referencias, criterio absoluto/porcentual y conservación de ejes al filtrar. Esto detectó falsos positivos de las primeras calificaciones de paráfrasis; los JSON originales siguen intactos. Estas diferencias del contrato de evaluación están documentadas y no ocultan fallos de alcance.', '',
        'La corrida `final_paraphrases` quedó interrumpida durante la pausa del usuario; conserva sus turnos terminados y `interrupted.json`. No cuenta como una corrida completa de treinta casos ni como PASS de turnos no ejecutados.', '',
        '## Paráfrasis y controles del evaluador', '',
        'Los treinta enunciados exactos y sus expectativas están en [state_paraphrases.py](evaluations/state_paraphrases.py). Se probaron crecimiento absoluto/porcentual, aceleración, dos desplazamientos consecutivos, radio y desglose, cambio de marca, máximo semanal, mínimo mensual/semanal, diagnóstico sin eje, cambio de fechas, dos y tres marcas, anunciantes, televisión y prensa. Renault, Ford y Toyota se verificaron en [catalogs.json](evaluations/conversation_state/catalogs.json). Tras inspeccionar resultados, estos casos pasan a ser regresiones; no se presentan como validación ciega.', '',
        'El evaluador rechaza siete controles: crecimiento con niveles, desglose restringido a su propio filtro, seguimiento con alcance antiguo, share sin agregado de universo, pico sin serie, comparación sin referencia y anunciante como marca. Tiene siete controles positivos correspondientes, para comprobar que no rechaza todo indiscriminadamente.', '',
        '## Comprobación numérica independiente', '',
        '[SQL y resultados de referencia](evaluations/conversation_state/numeric_reference.json), sin reutilizar las funciones analíticas del agente:', '',
        '| Comprobación | Resultado SQL |', '|---|---|',
        '| Crecimiento julio frente a junio de 2026 | RICH FIT TIPS: actual 1.067.799; referencia 0; cambio absoluto 1.067.799. La base cero no produce porcentaje definido. |',
        '| Máximo mensual de BMW en 2025 | Noviembre: 489.740,9467873. |',
        '| BMW + Volvo, televisión configurada, 2026 disponible | 528.525,21 / 36.852.874,73 = 1,4341492051 %. |',
        '| BMW + Volvo, todos los medios, octubre de 2025 | 633.367,4628929 / 37.729.909,64622802 = 1,6786879927 %. |',
        '| BMW, octubre de 2025 | 155.884,1239124. |',
        '| Toyota, semana anterior al máximo observado de abril de 2024 | 25–31 de marzo: cero filas, SUM nulo. El no-data de esa paráfrasis es consistente con la fuente, no inversión cero inventada. |', '',
        'La fuente conserva cobertura global hasta 2026-07-31. El calendario no certifica frecuencia diaria ni completitud de cada entidad. Las cifras son de la métrica de origen, sin convertir moneda.', '',
        '## Archivos modificados en esta revisión', '',
        '| Archivo | Responsabilidad |', '|---|---|',
        '| `src/agent/requirements.py` | Contratos analíticos, resolución de conjuntos y compilación a capacidades. |',
        '| `src/agent/planner.py`, `prompts.py`, `request_review.py`, `src/config.py` | Intenciones y operaciones estructuradas, validación semántica y reparación acotada. |',
        '| `src/agent/transitions.py`, `analysis_context.py`, `periods.py` | Promoción, restauración, prioridad de referencias y anclas temporales. |',
        '| `src/agent/memory.py`, `service.py` | Separación solicitud/evidencia, memoria de fallos, catálogos y observabilidad. |',
        '| `src/agent/sufficiency.py` | Requisitos de evidencia por capacidad. |',
        '| `src/data/comparative.py`, `bigquery_repository.py` | Crecimiento, aceleración, extremos, candidatos completos y conjuntos con valores ausentes. |',
        '| `src/tools/registry.py`, `src/semantic/business_rules.yaml` | Nuevas herramientas y políticas de criterio, familias y vocabulario. |',
        '| `src/agent/facts.py`, `finalization.py` | Hechos de cambio/extremos/conjuntos y filas de ranking preservadas. |',
        '| `tests/test_conversation_state.py` | Secuencias completas, errores, anclas, conjuntos, particiones y controles del evaluador. |',
        '| `evaluations/state_*.py`, `conversation_state.py`, `build_state_audit.py` | Ejecución optativa, expectativas independientes, referencia SQL e informe reproducible. |',
        '| `README.md`, `CAMBIOS_ARQUITECTURA_AGENT.md`, `BENCHMARK_AGENTE_BI.md` | Comportamiento actual y evolución histórica. |', '',
        '## Fallos observados, riesgos y prioridades', '',
        '**P0 — interpretación y validación de uso real.** El proveedor puede declarar una operación equivocada, omitir entidades o volver a una fecha anterior aun devolviendo JSON válido. Las invariantes corrigen contradicciones estructurales comprobadas, pero no comprenden cualquier frase. Mantener revisión humana de decisiones de negocio y evaluar conversaciones nuevas antes de considerar el sistema autónomo. No confundir un PASS de esta suite con autorización de acceso por usuario ni validación de monedas/definiciones de la fuente.', '',
        '**P1 — robustez y costo.** Persisten fallos de transporte/timeout del proveedor y dependencia de etiquetas reales. Una dimensión casi vacía puede no aportar una segunda partición útil; en ese caso la salida es parcial. El historial de doce alcances y ocho entidades no resuelve referencias ilimitadas. Catálogos, cobertura y particiones agregan costo aunque haya una sola tool. El ranking por cambio asume cero para categorías ausentes de una ventana, y los extremos solo consideran observaciones presentes. Se necesita observabilidad operativa de latencia y presupuesto además de límites de pasos.', '',
        '**P2 — evaluación y presentación.** Ampliar casos ciegos con nuevas entidades, idiomas, calendarios y métricas. Medir concordancia humana de interpretación y utilidad de los diagnósticos. La puntuación de concentración depende de la granularidad de la dimensión; comparar dimensiones no equivale a seleccionar causas. Mejorar la concisión de los análisis abiertos sin perder hechos ni cobertura. Los gráficos anteriores se conservan; las capacidades nuevas de cambio/extremos aún no tienen una visualización dedicada.', '',
        'No se hicieron commits, despliegues ni cambios de permisos. Los cambios preexistentes del repositorio y los artefactos históricos se conservaron.', '']
    Path('CONVERSATION_STATE_AUDIT.md').write_text('\n'.join(lines))
    benchmark = Path('BENCHMARK_AGENTE_BI.md')
    text = benchmark.read_text()
    marker = '\n<!-- CONVERSATION_STATE_AUDIT_UPDATE -->'
    text = text.split(marker)[0]
    if not text.startswith('> Registro histórico'):
        text = '> Registro histórico de la batería anterior. La revisión conversacional posterior está al final y en [CONVERSATION_STATE_AUDIT.md](CONVERSATION_STATE_AUDIT.md). Los 46/46 de esta sección no cubren las nuevas conversaciones.\n\n' + text
    table = '\n'.join(f"| {r['round']} | {r['cases']} | {r['passed']} | {r['cases']-r['passed']} |" for r in history)
    text += marker + f'''

## Revisión conversacional posterior — 12 de septiembre de 2026

Baseline de la conversación nueva: **{baseline['passed']}/12**. Última original completa: **{original['passed']}/12** (`{original['round']}`); última adicional completa: **{additional['passed']}/12** (`{additional['round']}`). Se evalúa cada conversación como secuencia; no se arma una secuencia de doce PASS escogiendo turnos de corridas distintas.

| Corrida | Casos | PASS revisado | FAIL revisado |
|---|---:|---:|---:|
{table}

Los puntajes revisados usan el mismo evaluador externo de estado, reforzado con calendario, criterio y conservación de ejes; los puntajes originales más permisivos permanecen en sus JSON. Se conservan evaluaciones y fallos originales. Las baterías completas contienen las treinta paráfrasis; repeticiones parciales por grupos se identifican por su número real de casos. `final_paraphrases` fue interrumpida tras la pausa y no cuenta como batería completa.

La suite, el desglose por turno, los siete controles negativos/positivos y los riesgos están en [la auditoría de estado](CONVERSATION_STATE_AUDIT.md). Las seis consultas SQL adicionales están en [numeric_reference.json](evaluations/conversation_state/numeric_reference.json); confirman también la ausencia de filas en una semana, sin convertirla en cero inversión. [Historial de revisión](evaluations/conversation_state/review_history.json).
'''
    benchmark.write_text(text)


if __name__ == '__main__': build()
