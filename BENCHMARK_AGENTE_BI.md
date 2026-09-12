> Registro histórico de la batería anterior. La revisión conversacional posterior está al final y en [CONVERSATION_STATE_AUDIT.md](CONVERSATION_STATE_AUDIT.md). Los 46/46 de esta sección no cubren las nuevas conversaciones.

# Benchmark real del agente BI

Fecha: 11 de septiembre de 2026. Ejecuciones del servicio real con el proveedor NVIDIA configurado y la tabla BigQuery autorizada. Los JSON incluyen plan, argumentos, SQL, evidencia, respuesta, errores, contadores y latencia. No se usan respuestas simuladas en esta batería.

## Resultado y alcance

**Último resultado por pregunta: 46/46 PASS y 0 FAIL.** Se toma siempre el intento más reciente, aunque sea peor que uno anterior; no se selecciona el mejor.

La corrida completa `acceptance` comenzó en `2026-09-11T12:45:39.923426+00:00`; huella SHA-256 del código Python de `src`: `a6d07d977362ec02ad43ef2b999d63acd1d452c361caf67b4f9a50690b280bfe`. Las correcciones posteriores, si existen, aparecen como repeticiones separadas con su propia procedencia.

El corpus contiene 28 preguntas independientes, una conversación obligatoria de siete turnos, otra de tres turnos sobre el mes pico y ocho preguntas adicionales con dimensiones/métricas diferentes. Cuatro rankings se generan a partir del modelo semántico. Las ocho preguntas adicionales se introdujeron después de las primeras correcciones; tras inspeccionarlas se convirtieron en regresiones y ya no son un conjunto ciego independiente.

**PASS significa que supera los criterios del evaluador y las objeciones manuales registradas.** No certifica toda atribución cualitativa ni comprensión universal. Las aclaraciones correctas ante categorías ambiguas y la ausencia controlada de una marca inventada tienen criterios propios. Un fallback de un análisis con datos se cuenta como FAIL.

## Verificación automatizada y numérica

Suite: **284 aprobados, 0 fallidos**, 1 aviso de deprecación de PyPDF2. Baseline: 106 aprobados y 26 fallidos sobre 132 casos. El inventario final aumenta en 152 casos; incluye regresiones nuevas y pruebas migradas al contrato vigente. [Verificación del entorno y código](evaluations/results/final_verification.json).

**9/9 contrastes numéricos independientes aprobados.** SQL de referencia sin LLM verificó totales, ventanas enero-julio, variación, inserciones y ratio. [SQL, valores y contrastes](evaluations/results/numeric_reference.json).

BMW como marca en 2025: 1.595.350,10 de inversión neta. Volvo enero-julio de 2026: 1.490.266,32 frente a 1.426.721,81 en enero-julio de 2025, variación calculada +4,45 %. Compararlo con todo 2025 daría una lectura incompatible. La cobertura global observada es 2019-01-01 a 2026-07-31 y no certifica completitud diaria.

## Historial de iteraciones

Los puntajes históricos son los guardados originalmente. **El evaluador se fortaleció durante el trabajo; esos porcentajes no son directamente comparables.** En particular, `release` registró 36/38, pero omitía comprobar la segunda dimensión de cuatro rankings: con ese criterio serían 32/38. `holdout` registró 8/8, pero una respuesta omitía el porcentaje conjunto solicitado: con ese criterio serían 7/8. Se corrigieron tanto producto como evaluación. Los artefactos originales se conservan. `reasoning_probe` se ejecutó antes de corregir errores de calendario y no demuestra que un modo de razonamiento sea superior a otro.

| Corrida | Casos | PASS original | FAIL original | Evidencia |
|---|---:|---:|---:|---|
| iteration1 | 38 | 16 | 22 | [JSON](evaluations/results/iteration1/summary.json) |
| iteration2 | 38 | 30 | 8 | [JSON](evaluations/results/iteration2/summary.json) |
| iteration3 | 38 | 19 | 19 | [JSON](evaluations/results/iteration3/summary.json) |
| reasoning_probe | 3 | 0 | 3 | [JSON](evaluations/results/reasoning_probe/summary.json) |
| iteration4_probe | 14 | 5 | 9 | [JSON](evaluations/results/iteration4_probe/summary.json) |
| ytd_probe | 1 | 0 | 1 | [JSON](evaluations/results/ytd_probe/summary.json) |
| final | 38 | 31 | 7 | [JSON](evaluations/results/final/summary.json) |
| final_retest | 12 | 5 | 7 | [JSON](evaluations/results/final_retest/summary.json) |
| conversation_retest | 10 | 9 | 1 | [JSON](evaluations/results/conversation_retest/summary.json) |
| release | 38 | 36 | 2 | [JSON](evaluations/results/release/summary.json) |
| release_conversations | 10 | 7 | 3 | [JSON](evaluations/results/release_conversations/summary.json) |
| grouped_retest | 4 | 3 | 1 | [JSON](evaluations/results/grouped_retest/summary.json) |
| holdout | 8 | 8 | 0 | [JSON](evaluations/results/holdout/summary.json) |
| final_stability | 11 | 9 | 2 | [JSON](evaluations/results/final_stability/summary.json) |
| acceptance | 46 | 43 | 3 | [JSON](evaluations/results/acceptance/summary.json) |
| acceptance_retest | 15 | 15 | 0 | [JSON](evaluations/results/acceptance_retest/summary.json) |
| final_review | 13 | 11 | 2 | [JSON](evaluations/results/final_review/summary.json) |
| final_scope | 8 | 7 | 1 | [JSON](evaluations/results/final_scope/summary.json) |
| final_context | 7 | 3 | 4 | [JSON](evaluations/results/final_context/summary.json) |
| completion | 7 | 7 | 0 | [JSON](evaluations/results/completion/summary.json) |
| verified | 7 | 6 | 1 | [JSON](evaluations/results/verified/summary.json) |
| elliptical_retest | 7 | 7 | 0 | [JSON](evaluations/results/elliptical_retest/summary.json) |

## Preguntas y últimos resultados

BQ cuenta jobs ejecutados; una herramienta puede requerir varios. LLM incluye planificación, investigación, redacción y reparaciones. El número de pasos incluye intentos fallidos. La intención es la detectada; un seguimiento puede conservar un diagnóstico previo aunque su redacción aislada parezca pedir composición.

| ID / pregunta | Intención | Herramientas | Pasos | BQ | LLM | Resultado / procedencia |
|---|---|---|---:|---:|---:|---|
| conversation-01: Analízame Volvo en 2025. | open_analysis | consultar_inversion_publicitaria, ranking_por_dimension, serie_temporal_bicomp | 3 | 3 | 3 | [PASS](evaluations/results/elliptical_retest/conversation-01.json) (elliptical_retest) |
| conversation-02: ¿Y en 2026? | open_analysis | consultar_inversion_publicitaria, ranking_por_dimension, serie_temporal_bicomp | 3 | 3 | 3 | [PASS](evaluations/results/elliptical_retest/conversation-02.json) (elliptical_retest) |
| conversation-03: ¿Ha bajado? | period_comparison | comparar_periodos_bicomp | 1 | 2 | 2 | [PASS](evaluations/results/elliptical_retest/conversation-03.json) (elliptical_retest) |
| conversation-04: ¿En qué medios? | diagnostic | analizar_drivers_bicomp | 1 | 2 | 2 | [PASS](evaluations/results/elliptical_retest/conversation-04.json) (elliptical_retest) |
| conversation-05: ¿Y BMW? | diagnostic | analizar_drivers_bicomp | 1 | 2 | 3 | [PASS](evaluations/results/elliptical_retest/conversation-05.json) (elliptical_retest) |
| conversation-06: Compara ambos. | diagnostic | explicar_diferencia_entidades_bicomp | 1 | 2 | 2 | [PASS](evaluations/results/elliptical_retest/conversation-06.json) (elliptical_retest) |
| conversation-07: ¿Qué explica la diferencia? | diagnostic | explicar_diferencia_entidades_bicomp | 1 | 0 | 4 | [PASS](evaluations/results/elliptical_retest/conversation-07.json) (elliptical_retest) |
| holdout-01: Reporta los cinco holdings con más inserciones durante 2024. | ranking | ranking_por_dimension | 1 | 1 | 2 | [PASS](evaluations/results/acceptance_retest/holdout-01.json) (acceptance_retest) |
| holdout-02: ¿Qué ciudades lideraron la inversión bruta en 2023? Muestra las cinco primeras. | ranking | ranking_por_dimension | 1 | 1 | 2 | [PASS](evaluations/results/acceptance_retest/holdout-02.json) (acceptance_retest) |
| holdout-03: Ordena los vehículos por duración publicitaria total de 2024, top cinco. | ranking | ranking_por_dimension | 1 | 1 | 2 | [PASS](evaluations/results/acceptance/holdout-03.json) (acceptance) |
| holdout-04: ¿Qué porcentaje conjunto de la inversión neta corresponde a RADIO y PRENSA en 2025? | composition | consultar_participacion_bicomp | 1 | 1 | 2 | [PASS](evaluations/results/acceptance/holdout-04.json) (acceptance) |
| holdout-05: Calcula el cociente de inversión bruta sobre inversión neta en 2024. | lookup | calcular_ratio_bicomp | 1 | 1 | 1 | [PASS](evaluations/results/acceptance_retest/holdout-05.json) (acceptance_retest) |
| holdout-06: ¿Cuál es la cobertura temporal real disponible en la fuente? | coverage | obtener_cobertura_bicomp | 1 | 1 | 3 | [PASS](evaluations/results/acceptance/holdout-06.json) (acceptance) |
| holdout-07: Compara las inserciones de marzo de 2024 frente a marzo de 2023, usando el mismo mes. | period_comparison | comparar_periodos_bicomp | 1 | 3 | 3 | [PASS](evaluations/results/acceptance/holdout-07.json) (acceptance) |
| holdout-08: ¿Cuánto invirtió la marca FUNCTIONAL ROOM en 2025? | lookup | consultar_inversion_publicitaria | 1 | 1 | 1 | [PASS](evaluations/results/acceptance/holdout-08.json) (acceptance) |
| independent-01: ¿Cuánto invirtió BMW en 2025? | lookup | consultar_inversion_publicitaria | 1 | 1 | 1 | [PASS](evaluations/results/acceptance/independent-01.json) (acceptance) |
| independent-02: ¿Cuánto invirtió Volvo? | lookup | consultar_inversion_publicitaria | 1 | 1 | 1 | [PASS](evaluations/results/acceptance/independent-02.json) (acceptance) |
| independent-03: ¿Cuál fue la inversión neta de la marca Volvo en marzo de 2025? | lookup | consultar_inversion_publicitaria | 1 | 1 | 1 | [PASS](evaluations/results/acceptance/independent-03.json) (acceptance) |
| independent-04: ¿Qué marcas invirtieron más en 2025? | ranking | ranking_por_dimension | 1 | 1 | 2 | [PASS](evaluations/results/acceptance/independent-04.json) (acceptance) |
| independent-05: Top 10 anunciantes en digital durante 2025. | ranking | ranking_por_dimension | 1 | 1 | 2 | [PASS](evaluations/results/acceptance_retest/independent-05.json) (acceptance_retest) |
| independent-06: ¿Cómo viene evolucionando Volvo durante los últimos seis meses disponibles? | trend | serie_temporal_bicomp | 1 | 2 | 3 | [PASS](evaluations/results/acceptance/independent-06.json) (acceptance) |
| independent-07: ¿Cuál es el mix de medios de BMW en 2025? | composition | ranking_por_dimension | 1 | 1 | 2 | [PASS](evaluations/results/acceptance/independent-07.json) (acceptance) |
| independent-08: ¿Cómo se distribuyó la inversión por formato en 2025? | composition | ranking_por_dimension | 1 | 1 | 2 | [PASS](evaluations/results/acceptance_retest/independent-08.json) (acceptance_retest) |
| independent-09: Compara Volvo con BMW en 2025. | comparison | comparar_entidades_bicomp | 1 | 2 | 2 | [PASS](evaluations/results/acceptance/independent-09.json) (acceptance) |
| independent-10: Compara Digital vs TV para Volvo en 2025. | comparison | comparar_entidades_bicomp | 1 | 3 | 2 | [PASS](evaluations/results/acceptance/independent-10.json) (acceptance) |
| independent-11: ¿Subió la inversión de Volvo en 2026 frente a 2025? Usa ventanas equivalentes. | period_comparison | comparar_periodos_bicomp | 1 | 3 | 2 | [PASS](evaluations/results/acceptance/independent-11.json) (acceptance) |
| independent-12: Compara la inversión YTD de BMW frente al mismo periodo del año anterior. | period_comparison | comparar_periodos_bicomp | 1 | 3 | 2 | [PASS](evaluations/results/acceptance/independent-12.json) (acceptance) |
| independent-13: ¿Qué medios explican el cambio de la inversión de Volvo en 2026 frente a 2025? | diagnostic | analizar_drivers_bicomp | 1 | 3 | 2 | [PASS](evaluations/results/final_review/independent-13.json) (final_review) |
| independent-14: Analiza el sector automotriz en 2025. | open_analysis | consultar_inversion_publicitaria, ranking_por_dimension, serie_temporal_bicomp | 5 | 4 | 5 | [PASS](evaluations/results/acceptance/independent-14.json) (acceptance) |
| independent-15: Encuentra los principales hallazgos de inversión de este año. | open_analysis | consultar_inversion_publicitaria, ranking_por_dimension, serie_temporal_bicomp | 4 | 4 | 6 | [PASS](evaluations/results/acceptance_retest/independent-15.json) (acceptance_retest) |
| independent-16: ¿Hay algún pico anormal en la inversión mensual de BMW durante 2025? | anomaly | analizar_anomalias_bicomp | 1 | 1 | 4 | [PASS](evaluations/results/acceptance/independent-16.json) (acceptance) |
| independent-17: ¿Cómo vamos? | out_of_domain | ninguna | 0 | 0 | 1 | [PASS](evaluations/results/acceptance/independent-17.json) (acceptance) |
| independent-18: Hola. | out_of_domain | ninguna | 0 | 0 | 1 | [PASS](evaluations/results/acceptance/independent-18.json) (acceptance) |
| independent-19: Explícame qué significa share. | out_of_domain | ninguna | 0 | 0 | 1 | [PASS](evaluations/results/acceptance/independent-19.json) (acceptance) |
| independent-20: ¿Cómo interpretarías un pico de inversión? | out_of_domain | ninguna | 0 | 0 | 1 | [PASS](evaluations/results/final_scope/independent-20.json) (final_scope) |
| independent-21: Analiza la calidad de la dimensión formato para Volvo en 2025: no interpretes NULL ni N/A como formatos reales. | diagnostic | ranking_por_dimension, obtener_valores_dimension_bicomp, serie_temporal_bicomp | 3 | 3 | 2 | [PASS](evaluations/results/acceptance_retest/independent-21.json) (acceptance_retest) |
| independent-22: ¿Cuánto invirtió la marca MARCA_INEXISTENTE_AUDITORIA en 2025? | lookup | consultar_inversion_publicitaria | 1 | 1 | 1 | [PASS](evaluations/results/acceptance/independent-22.json) (acceptance) |
| independent-23: ¿Cuántas inserciones tuvo BMW en 2025? | lookup | consultar_inversion_publicitaria | 1 | 1 | 1 | [PASS](evaluations/results/acceptance/independent-23.json) (acceptance) |
| independent-24: Calcula el coste por inserción de BMW en 2025 usando inversión neta. | lookup | calcular_ratio_bicomp | 1 | 1 | 1 | [PASS](evaluations/results/acceptance_retest/independent-24.json) (acceptance_retest) |
| independent-25: Muestra las cinco categorías con mayor inversión neta USD por ciudad en 2025. | ranking | ranking_segmentado_bicomp | 1 | 1 | 2 | [PASS](evaluations/results/acceptance/independent-25.json) (acceptance) |
| independent-26: Muestra las cinco categorías con mayor inversión neta USD por region en 2025. | ranking | ranking_segmentado_bicomp | 1 | 1 | 2 | [PASS](evaluations/results/acceptance/independent-26.json) (acceptance) |
| independent-27: Muestra las cinco categorías con mayor inversión neta USD por sector en 2025. | ranking | ranking_segmentado_bicomp | 1 | 1 | 3 | [PASS](evaluations/results/acceptance/independent-27.json) (acceptance) |
| independent-28: Muestra las cinco categorías con mayor inversión neta USD por agencia en 2025. | ranking | ranking_segmentado_bicomp | 1 | 1 | 3 | [PASS](evaluations/results/final_review/independent-28.json) (final_review) |
| peak-followup-01: Analízame BMW en 2025. | open_analysis | consultar_inversion_publicitaria, ranking_por_dimension, serie_temporal_bicomp, ranking_segmentado_bicomp | 4 | 4 | 4 | [PASS](evaluations/results/final_review/peak-followup-01.json) (final_review) |
| peak-followup-02: ¿Qué pasó en el mes más fuerte? | diagnostic | consultar_inversion_publicitaria, ranking_por_dimension | 2 | 2 | 2 | [PASS](evaluations/results/final_review/peak-followup-02.json) (final_review) |
| peak-followup-03: ¿Y por medios? | diagnostic | ranking_por_dimension | 1 | 0 | 2 | [PASS](evaluations/results/final_review/peak-followup-03.json) (final_review) |

## Latencia y consumo observados

Estadística del último intento por pregunta, incluyendo fallos, aclaraciones y caché. P95 usa el rango más próximo superior. Son observaciones del endpoint y entorno concretos, no un SLA ni una medición de carga concurrente de producción.

| Medida | Total | Mediana | P95 | Máximo |
|---|---:|---:|---:|---:|
| Latencia (s) | 664.99 | 11.75 | 40.71 | 67.36 |
| Pasos | 59.00 | 1.00 | 4.00 | 5.00 |
| Jobs BigQuery | 72.00 | 1.00 | 4.00 | 4.00 |
| Llamadas LLM | 101.00 | 2.00 | 4.00 | 6.00 |

Los tokens y bytes por job quedan en cada JSON. No se estiman costos monetarios sin tarifas/contrato aplicables. Los ceros de bytes reportados por caché no se sustituyen por estimaciones.

## Fallos pendientes y revisión de respuestas

No quedan fallos bajo los criterios aplicados en estos últimos intentos. Las regresiones observadas entre rondas impiden interpretar ese resultado como garantía universal.

La inspección de código y respuestas está recogida en [AUDITORIA_AGENTE_BI_FINAL.md](AUDITORIA_AGENTE_BI_FINAL.md). El alcance exacto de las revisiones manuales, si existen, está en [manual_review.json](evaluations/results/manual_review.json).

## Reproducción

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m evaluations.benchmark --live --cases evaluations/results/acceptance_cases.json --output evaluations/results/new_run --workers 2
.venv/bin/python -m evaluations.report
```

La segunda orden realiza llamadas reales y requiere credenciales válidas del entorno. Usar un directorio nuevo conserva el historial. Los resultados contienen datos de negocio y SQL, por lo que deben permanecer bajo controles de acceso equivalentes a la fuente.

<!-- CONVERSATION_STATE_AUDIT_UPDATE -->

## Revisión conversacional posterior — 12 de septiembre de 2026

Baseline de la conversación nueva: **4/12**. Última original completa: **12/12** (`default_original`); última adicional completa: **12/12** (`completion_additional`). Se evalúa cada conversación como secuencia; no se arma una secuencia de doce PASS escogiendo turnos de corridas distintas.

| Corrida | Casos | PASS revisado | FAIL revisado |
|---|---:|---:|---:|
| baseline | 12 | 4 | 8 |
| iteration1 | 12 | 11 | 1 |
| additional1 | 12 | 3 | 9 |
| iteration2 | 12 | 8 | 4 |
| paraphrases1 | 30 | 18 | 12 |
| additional2 | 12 | 4 | 8 |
| iteration3 | 12 | 10 | 2 |
| additional3 | 12 | 3 | 9 |
| iteration4 | 12 | 12 | 0 |
| additional4 | 12 | 9 | 3 |
| paraphrases2 | 30 | 22 | 8 |
| final_additional | 12 | 12 | 0 |
| final_original | 12 | 10 | 2 |
| acceptance_original | 12 | 11 | 1 |
| acceptance_additional | 12 | 4 | 8 |
| acceptance_paraphrases | 15 | 10 | 5 |
| verification_original | 12 | 11 | 1 |
| verification_additional | 12 | 5 | 7 |
| reviewed_original | 12 | 9 | 3 |
| reviewed_additional | 12 | 7 | 5 |
| contract_additional | 12 | 4 | 8 |
| contract_original | 12 | 12 | 0 |
| contract_paraphrases | 30 | 22 | 8 |
| guarded_additional | 12 | 11 | 1 |
| release_original | 12 | 9 | 3 |
| release_paraphrases | 30 | 23 | 7 |
| default_original | 12 | 12 | 0 |
| release_additional | 12 | 9 | 3 |
| default_additional | 12 | 8 | 4 |
| default_paraphrases | 30 | 25 | 5 |
| completion_additional | 12 | 12 | 0 |

Los puntajes revisados usan el mismo evaluador externo de estado, reforzado con calendario, criterio y conservación de ejes; los puntajes originales más permisivos permanecen en sus JSON. Se conservan evaluaciones y fallos originales. Las baterías completas contienen las treinta paráfrasis; repeticiones parciales por grupos se identifican por su número real de casos. `final_paraphrases` fue interrumpida tras la pausa y no cuenta como batería completa.

La suite, el desglose por turno, los siete controles negativos/positivos y los riesgos están en [la auditoría de estado](CONVERSATION_STATE_AUDIT.md). Las seis consultas SQL adicionales están en [numeric_reference.json](evaluations/conversation_state/numeric_reference.json); confirman también la ausencia de filas en una semana, sin convertirla en cero inversión. [Historial de revisión](evaluations/conversation_state/review_history.json).
