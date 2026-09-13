# Auditoría independiente integral del agente BI

Fecha de corte: 2026-09-13  
Repositorio auditado: `Agente-main`  
Commit observado: `4db2706` (`main`, alineado con `origin/main` al iniciar la auditoría)  
Naturaleza del trabajo: diagnóstico estático y dinámico; no se modificó código, configuración ni datos.

## 1. Veredicto ejecutivo en cinco líneas

1. El agente tiene una arquitectura razonable y una base de pruebas locales amplia: la ejecución literal de `pytest` terminó con **351 pruebas aprobadas**, pero esto no equivale a validación productiva.
2. El riesgo funcional más importante es la composición de filtros al cambiar el eje de análisis: todavía puede producir una única categoría con **100 %** cuando el usuario pidió una distribución.
3. El benchmark publicado no mide generalización independiente: sus casos fueron inspeccionados o incorporados durante iteraciones y mezcla resultados de ejecuciones y revisiones distintas.
4. La coherencia numérica básica es buena y texto y gráfico consumen actualmente los mismos campos; aun así, faltan pruebas integradas que garanticen esa coherencia en la presentación final.
5. La preparación productiva queda en **45/100**, limitada por dos puertas críticas: ausencia de un conjunto ciego estable y ausencia de autenticación/autorización en la aplicación.

## 2. Los tres problemas principales

### 2.1. Cambio de eje sin eliminación determinista de filtros incompatibles — crítico

El cambio de dimensión depende de que el LLM clasifique correctamente la operación como `breakdown`. Solo en ese caso `compile_transition` retira el filtro cuyo nombre coincide exactamente con la nueva dimensión. No hay una comprobación posterior a la consulta que rechace una composición degenerada de una sola fila.

Evidencia:

- `src/agent/transitions.py:89-98`: la eliminación del filtro ocurre solo para `operation == "breakdown"`.
- `src/agent/planner.py:93-107`: el reconocimiento determinista de agrupaciones explícitas cubre un patrón lingüístico estrecho.
- `src/agent/sufficiency.py:22-28`: una composición se considera suficiente con cualquier conjunto no vacío de filas.
- `evaluations/results/default_paraphrases/group-2/paraphrase-2-03.json`: el plan preserva `marca=Renault` y `medio=RADIO`; el resultado contiene una sola fila, RADIO, con 100 %.
- `medio` y `medio_agrupado` se tratan como nombres diferentes en ejecución, mientras que el oráculo de evaluación sí incorpora equivalencias especiales.

Impacto: una respuesta puede ser formalmente válida, numéricamente autoconsistente y semánticamente equivocada. Es especialmente peligrosa porque el 100 % luce convincente.

### 2.2. Evaluación contaminada y no reproducible como medida de generalización — crítico

No existe hoy un caso certificable como ciego. Los documentos describen que los casos adicionales y las paráfrasis fueron inspeccionados y usados para fortalecer el evaluador y añadir regresiones. Además, el reporte agregado selecciona el resultado más reciente de cada pregunta entre diferentes ejecuciones, por lo que el `46/46` no representa una corrida congelada de una versión única.

Evidencia:

- `BENCHMARK_AGENTE_BI.md:13`: los ocho casos adicionales se introducen después de correcciones y se inspeccionan.
- `BENCHMARK_AGENTE_BI.md:27`: se fortaleció el evaluador a partir de los resultados observados.
- `CONVERSATION_STATE_AUDIT.md:174`: las treinta paráfrasis fueron inspeccionadas y convertidas en regresiones.
- `evaluations/report.py:25-44`: el reporte conserva el resultado más reciente por pregunta a través de directorios de corridas.
- `evaluations/manual_review.json`: contiene 110 decisiones/manualizaciones; no hay un manifiesto sellado que demuestre qué casos permanecieron sin observar.

Impacto: las tasas publicadas son útiles como regresión interna, pero no sostienen afirmaciones de generalización ni una decisión de salida a producción.

### 2.3. Seguridad y operación insuficientes para producción — crítico

La capa de datos sí incorpora defensas útiles —consultas parametrizadas, allowlist de SQL, dry run y límite de bytes—, pero la aplicación no implementa autenticación, autorización, aislamiento por tenant ni control de visibilidad de trazas. La interfaz puede mostrar SQL, resultados y excepciones al usuario.

Evidencia:

- `src/data/sql_guard.py:12-31`: validación sintáctica y allowlist de SQL de solo lectura.
- `src/data/bigquery_repository.py:65-94`: parámetros, dry run y límite de bytes procesados.
- `app.py:787-792`, `app.py:867-892` y `app.py:952-972`: la traza está habilitada por defecto y expone detalles de ejecución.
- `app.py:986`: una excepción sin procesar puede mostrarse en la interfaz.
- No se encontró middleware o flujo de autenticación/autorización ni filtros obligatorios de tenant en el repositorio.

Impacto: aun con consultas seguras, la aplicación no ofrece garantías suficientes sobre quién puede consultar qué datos ni qué información operativa queda expuesta.

## 3. Inventario y mapa técnico

### 3.1. Resumen del repositorio

Se identificaron **1.085 archivos** Python, YAML, JSON o Markdown como insumos de la auditoría, excluyendo este informe nuevo. La cifra está dominada por artefactos de evaluación:

| Familia | Archivos | Líneas aproximadas | Función | Estado |
|---|---:|---:|---|---|
| Código Python de raíz, `src/` y `evaluations/` | 47 | 5.842 | Aplicación, agente, acceso a datos, evaluación | Activo, con deuda localizada |
| Pruebas Python en `tests/` | 19 | 2.163 | Regresión unitaria/local | Activo |
| Documentación Markdown de raíz | 5 | 945 | Uso, benchmark y auditorías previas | Parcialmente desactualizada |
| Configuración semántica YAML | 4 | 122 | Reglas, dimensiones, métricas y sinónimos | Parcialmente declarativa |
| JSON en `evaluations/results/` | 404 | 357.020 | Resultados históricos | Artefactos, no configuración |
| JSON en `evaluations/conversation_state/` | 604 | 2.323.735 | Estado y corridas históricas | Artefactos, no configuración |
| Otros JSON de evaluación | 2 | 107 | Casos de entrada de benchmark | Activos; ya no son ciegos |

Los conteos de líneas son físicos, no SLOC, y sirven para dimensionar el repositorio; los JSON históricos no deben interpretarse como superficie de código.

### 3.2. Mapa de dependencias

```text
app.py / cli.py
        |
        v
     agent.py
        |
        v
AgentService -------------------------------------------------+
 |          |             |              |                    |
 v          v             v              v                    v
planner  transitions  analysis_context  execution/cache  finalization
 |          |             |              |                    |
 +------ semantic YAML    periods         v                    +--> facts
                                      tool registry            +--> validator
                                           |                   +--> charts
                                           v
                               BigQueryRepository / comparative
                                           |
                                           +--> SQL guard
                                           +--> calculations

evaluations/* --> agent público, validadores y oráculos propios
tests/*       --> módulos anteriores y dobles de repositorio/LLM
```

No se detectaron ciclos de importación de producción. Sí existe acoplamiento lateral en pruebas: algunos módulos importan fixtures desde otros archivos de prueba.

### 3.3. Inventario de código de producción

| Archivo o módulo | Líneas | Usuarios/dependencias principales | Estado y observaciones | Severidad |
|---|---:|---|---|---|
| `agent.py` | 37 | CLI, app, evaluaciones | Fachada pública; conserva globales y wrappers de compatibilidad | Baja |
| `app.py` | 986 | Streamlit, agente, adjuntos | Monolito UI; ejecución bloqueante, traza visible, excepción cruda | Alta |
| `cli.py` | 29 | `agent.py` | Entrada simple | Baja |
| `src/config.py` | 149 | App, LLM, repositorio | Configuración central; opciones declaradas no siempre consumidas | Media |
| `src/agent/service.py` | 362 | Fachada principal | Orquestador grande; concentra estado, pasos, recuperación y salida | Media |
| `src/agent/planner.py` | 243 | Servicio, semántica, LLM | Híbrido determinista/LLM; regex estrecha; oculta wrappers legacy | Alta |
| `src/agent/response_validator.py` | 228 | Finalización/evaluación | Buen control de afirmaciones; no valida intención global | Media |
| `src/agent/facts.py` | 161 | Finalización | Normaliza hechos desde resultados | Activo |
| `src/agent/transitions.py` | 151 | Servicio | Regla crítica de herencia/eliminación de filtros | Alta |
| `src/agent/prompts.py` | 151 | Planner/finalización | Contratos en lenguaje natural; sensibles al proveedor | Media |
| `src/agent/memory.py` | 133 | Servicio | Estado conversacional; `last_successful_scope` se escribe pero no decide | Media |
| `src/agent/periods.py` | 124 | Contexto/planificador | Resolución temporal determinista | Activo |
| `src/agent/requirements.py` | 111 | Planner | Requisitos de operación | Activo |
| `src/agent/finalization.py` | 110 | Servicio | Construcción de respuesta; import no usado y lógica duplicada | Baja |
| `src/agent/analysis_context.py` | 107 | Servicio | Contexto de análisis y filtros | Activo |
| `src/agent/request_review.py` | 67 | Servicio opcional | Revisión LLM deshabilitada por defecto por regresiones | Media |
| `src/agent/execution.py` | 63 | Servicio, registro | Despacho y manejo básico de herramientas | Activo |
| `src/agent/llm.py` | 54 | Planner/finalizador | Gateway con timeout por llamada; sin presupuesto total | Alta |
| `src/agent/cache.py` | 45 | Ejecutor | Caché local | Activo |
| `src/agent/sufficiency.py` | 40 | Servicio | Criterios demasiado permisivos para composición | Alta |
| `src/agent/observability.py` | 21 | Servicio/UI | Trazas locales, sin telemetría productiva | Media |
| `src/agent/attachments.py` | 19 | UI | Modelo de adjuntos | Activo |
| `src/data/bigquery_repository.py` | 835 | Registro/herramientas | Núcleo SQL grande; buenas defensas, alta concentración | Alta |
| `src/data/comparative.py` | 130 | Repositorio | Comparaciones y contribuciones | Activo |
| `src/data/sql_guard.py` | 31 | Repositorio | Defensa útil de solo lectura | Activo |
| `src/data/repository.py` | 22 | Tipado | Protocolo más estrecho que el uso real del registro | Media |
| `src/analytics/calculations.py` | 78 | Repositorio | Cálculo local determinista | Activo |
| `src/tools/registry.py` | 264 | Ejecutor, repositorio | 24 herramientas; wrappers legacy duplican rutas genéricas | Media |
| `src/visualization/charts.py` | 58 | Servicio/UI | Construye gráficos desde los mismos resultados que los hechos | Media |
| `src/semantic/*.py` | 92 | Planner/configuración | Carga de catálogo; parte de la semántica queda solo en prompts | Media |

Los archivos `__init__.py` restantes son exportadores mínimos y no presentan hallazgos materiales.

### 3.4. Configuración semántica

| Archivo | Líneas | Consumidores | Hallazgo | Severidad |
|---|---:|---|---|---|
| `src/semantic/business_rules.yaml` | 47 | Cargador, prompts, evaluación | `filter_groups` y varias reglas no tienen enforcement determinista | Alta |
| `src/semantic/dimensions.yaml` | 48 | Catálogo/planner | Allowlist útil; equivalencias de familia insuficientes en runtime | Alta |
| `src/semantic/metrics.yaml` | 23 | Catálogo/planner | Unidad/descripción se usan; `default_aggregation` no gobierna el SQL | Media |
| `src/semantic/synonyms.yaml` | 4 | Contexto LLM | Sinónimo `inversion` no es dimensión consumible por el parser explícito | Baja |

Reglas declaradas pero no plenamente ejecutables:

- `filter_groups`: aparece en contexto/prompts y oráculos, pero no existe un normalizador determinista de familias antes de consultar.
- `comparisons.require_compatible_periods`: el código aplica compatibilidad por su propia lógica, no desde la bandera.
- `bicomp.default_aggregation` y `metrics.default_aggregation`: se cargan o prueban, pero el repositorio conserva agregaciones codificadas.
- `domain_label`: no se encontró uso operativo.

Esto crea una diferencia importante entre “configuración documentada” y “política efectivamente aplicada”.

### 3.5. Evaluación y documentación

| Archivo | Líneas | Propósito | Estado/hallazgo | Severidad |
|---|---:|---|---|---|
| `evaluations/benchmark.py` | 151 | Ejecutar benchmark | Útil para regresión; no congela entorno externo completo | Media |
| `evaluations/report.py` | 152 | Agregar resultados | Mezcla el último resultado por pregunta entre corridas | Alta |
| `evaluations/build_state_audit.py` | 152 | Construir auditoría de estado | Artefacto de análisis | Baja |
| `evaluations/state_paraphrases.py` | 101 | Paráfrasis | Etiqueta “unseen” ya no describe su estado real | Alta |
| `evaluations/state_evaluator.py` | 95 | Evaluación de estado | Oráculo contiene equivalencias no implementadas en runtime | Alta |
| `evaluations/verify_state.py` | 84 | Verificación | Herramienta local | Baja |
| `evaluations/conversation_state.py` | 80 | Casos conversacionales | Base útil, ya observada durante desarrollo | Media |
| `evaluations/state_numeric_reference.py` | 54 | Referencias numéricas | Referencias históricas, no reconsulta de fuente | Media |
| `evaluations/state_expectations.py` | 47 | Oráculo esperado | Más estricto que ciertas reglas productivas | Alta |
| `evaluations/state_report.py` | 46 | Reporte | Presentación de métricas internas | Baja |
| `evaluations/evaluator.py` | 40 | Evaluador general | Cobertura semántica parcial | Media |
| `README.md` | 185 | Uso/arquitectura | Reconoce simulación; algunas garantías se expresan con exceso | Media |
| `BENCHMARK_AGENTE_BI.md` | 178 | Resultados | Mezcla versiones/corridas; conteo antiguo de pruebas | Alta |
| `AUDITORIA_AGENTE_BI_FINAL.md` | 261 | Auditoría anterior | Honesta en varias limitaciones, pero optimista en producción | Media |
| `CONVERSATION_STATE_AUDIT.md` | 217 | Auditoría de estado | Expone contaminación y 351 pruebas correctamente | Activo |
| `CAMBIOS_ARQUITECTURA_AGENT.md` | 104 | Historial | Documento de cambios | Baja |

### 3.6. Código redundante, inactivo o de compatibilidad

- `_summarize_partial_evidence` en `service.py` no tiene llamadas internas.
- `AgentMaxStepsError` y `RepeatedToolCallError` se conservan como superficie pública, pero no se lanzan internamente.
- `finalization.py` importa `compact_evidence` sin usarlo.
- `Settings.llm_max_tokens` se carga y se prueba, pero el gateway utiliza límites separados de plan y respuesta final.
- Los globales y wrappers de `agent.py` no tienen consumidores internos de producción; pueden ser API de compatibilidad externa.
- `last_successful_scope` se guarda, pero no se usa en decisiones posteriores.
- Hay lógica de presentación duplicada entre `facts.py` y `finalization.py`, con etiquetas distintas para valores ausentes.
- El registro conserva wrappers legacy además de herramientas genéricas; el planner oculta ocho de ellos, pero siguen aumentando la superficie.

No se clasifica automáticamente todo lo anterior como eliminable: antes de retirarlo se debe confirmar compatibilidad con consumidores externos no presentes en el repositorio.

## 4. Comprobaciones específicas

### 4.1. ¿Texto y gráfico usan métricas o campos distintos?

**Conclusión: la implementación actual no confirma esa hipótesis.** Para cada clase de resultado, ambos parten de las mismas filas y los mismos campos:

| Operación | Texto/hechos | Gráfico | Campo compartido |
|---|---|---|---|
| Ranking/composición | `facts.py:87-96` | `charts.py:36-43` | `value` |
| Comparación | `facts.py:55-61` | `charts.py:24-31` | `value_a`, `value_b` |
| Drivers | `facts.py:97-101` | `charts.py:32-35` | `contribution` |
| Serie temporal | Filas del resultado | Filas del resultado | período y `value` |

Además, el ranking SQL produce `SUM(metric) AS value` (`bigquery_repository.py:350-386`) y `render_plotly` no aplica reescalado (`charts.py:47-57`). Por tanto, una captura donde la última etiqueta visible del eje difiere del valor textual no demuestra por sí sola una discrepancia: Plotly puede elegir ticks automáticos que no incluyan el máximo exacto. Esto es una **inferencia plausible, no verificada**, porque las capturas originales y su artefacto ejecutable no están en el alcance.

Riesgo residual: no hay una prueba integrada que compare, para la respuesta final completa, valor textual, datos de la figura, rango, ticks y etiquetas. Las pruebas actuales validan el constructor del gráfico de manera aislada. Conviene añadir etiquetas de valor y una aserción de extremo/rango para eliminar ambigüedad visual.

### 4.2. ¿Por qué aparece una sola categoría con 100 %?

La causa reproducible no es una fórmula de porcentaje defectuosa. Es la intersección entre el nuevo eje y filtros heredados del eje anterior:

```text
Usuario pide composición por medio
          |
          v
LLM no etiqueta la operación como breakdown
          |
          v
compile_transition conserva filtro medio=RADIO
          |
          v
GROUP BY medio sobre filas ya filtradas a RADIO
          |
          v
única categoría / total filtrado = 100 %
```

El caso `default_paraphrases/group-2/paraphrase-2-03.json` materializa este camino. El plan usa `restore_scope`, conserva `marca=Renault` y `medio=RADIO`, y devuelve una fila RADIO por 3.411.864,2 con participación de 100 %.

El problema tiene dos variantes adicionales:

- La eliminación actual coincide por nombre exacto. Promover `medio` no elimina necesariamente un filtro equivalente como `medio_agrupado`.
- El evaluador contiene una equivalencia especial entre `medio_agrupado=DIGITAL` y `medio=DIGITAL`, pero la ejecución no comparte esa normalización.

Un caso BMW presente en referencias históricas no muestra este fallo: 775.378,83 sobre 1.595.350,10 equivale a aproximadamente **48,60 %**, no a 100 %. Es una referencia guardada, no una reconsulta actual a BigQuery.

### 4.3. No determinismo entre ejecuciones

Las corridas históricas muestran amplitud real aun cuando los nombres de los conjuntos sugieren el mismo objetivo. Entre los resultados registrados aparecen, por ejemplo, 4, 11, 3, 8, 4, 10, 3, 12, 9, 12, 10 y 11 conversaciones aprobadas en sucesivas iteraciones; las tandas de 30 paráfrasis avanzan por 18, 22, 22, 23 y 25. Hay también resultados 12 frente a 8 asociados al mismo fingerprint de código, pero con diálogos distintos, por lo que no constituyen una réplica controlada.

Las fuentes probables de variación son:

- planificación y revisión mediante LLM;
- cambios en casos, prompts, oráculos y código entre corridas;
- datos externos y permisos no congelados;
- caché y composición del historial;
- agregación posterior que mezcla corridas.

Metodología mínima recomendada:

1. Congelar commit, catálogo, prompts, oráculo, casos, endpoint/modelo, parámetros de muestreo, snapshot de datos, IAM y política de caché.
2. Separar estrictamente desarrollo/regresión de un conjunto ciego sellado.
3. Ejecutar al menos 30 repeticiones por conversación crítica como cribado; reportar intervalo Wilson del 95 %. Con 30 observaciones, el margen en el peor caso sigue cerca de ±18 puntos porcentuales.
4. Usar aproximadamente 100 repeticiones cuando se necesite un margen cercano a ±10 puntos en el peor caso.
5. Publicar éxito de conversación completa, éxito por turno y por operación, además de P10/P50/P90 de latencia.
6. Separar fallos semánticos de fallos de proveedor, cuota, red y datos. Nunca combinar hashes o revisiones en una única tasa sin etiquetarlos.

### 4.4. Contaminación y generalización

**Casos actualmente certificables como ciegos: 0.** Esto no significa que se haya demostrado que una persona leyó cada JSON, sino que no existe un manifiesto previo, sellado e independiente que permita probar lo contrario.

Los conjuntos `holdout` y `state_paraphrases` ya son regresiones conocidas. Conservan valor para evitar recaídas, pero no para estimar desempeño en preguntas nuevas. Para recuperar capacidad de medición se necesita:

- un generador o curador independiente;
- un hash y timestamp del conjunto antes de cualquier ejecución;
- acceso restringido a respuestas y oráculo;
- una única corrida de aceptación congelada;
- prohibición de modificar el sistema y volver a puntuar sobre el mismo conjunto;
- renovación periódica del conjunto después de abrirlo.

### 4.5. Cierre de contribuciones y particiones

**Existe tanto una advertencia como una prueba parcial, pero no un cierre completo de presentación.**

- La ruta legacy advierte que no deben sumarse particiones alternativas (`bigquery_repository.py:296`).
- `_partition_difference` calcula contribuciones sobre todas las filas y luego devuelve solo `rows[:limit]` (`bigquery_repository.py:712-732`).
- `test_data_quality.py:81-93` comprueba un caso pequeño de tres categorías: diferencia 50, suma de contribuciones 50 y porcentajes cercanos a 100 %.
- `test_bicomp_advanced.py:25-38` verifica tres dimensiones alternativas con contribución -20 cada una, precisamente un escenario donde sumarlas entre sí sería engañoso.

La brecha aparece cuando hay más drivers que el límite: lo visible puede no cerrar contra la diferencia total y no se añade un residual “otros”. Tampoco hay una invariante general con tolerancia para todas las rutas de partición. La respuesta debe mostrar `otros/no mostrado`, o declarar explícitamente que el top N no pretende cerrar.

### 4.6. Latencia y experiencia de uso

Los resultados históricos reportan mediana **11,75 s**, P95 **40,71 s**, máximo **67,36 s** y total **664,99 s**. `evaluations/report.py:115-124` calcula el P95 por nearest-rank sobre la muestra agregada más reciente por pregunta. Es una muestra heterogénea, no una prueba de carga ni un SLO.

La interfaz mantiene el turno dentro de un spinner bloqueante (`app.py:938-950`) y no transmite progreso o resultados parciales. Cada etapa LLM puede esperar hasta 60 segundos y no existe un presupuesto total de turno, por lo que una cadena de etapas puede superar ese valor.

Impacto UX:

- 10-12 s puede ser tolerable si hay progreso claro;
- 40-67 s sin progreso granular se percibe como bloqueo o fallo;
- reintentos del usuario pueden duplicar costo y carga;
- sin métricas por etapa no se distingue latencia de LLM, BigQuery, render o recuperación.

Las auditorías existentes mencionan la latencia y el proveedor como riesgos, pero no fijan una puerta de aceptación, un SLO ni pruebas bajo concurrencia.

## 5. Pruebas automatizadas

### 5.1. Ejecución literal solicitada

Se ejecutó exactamente:

```bash
.venv/bin/python -m pytest -q
```

Resultado literal relevante:

```text
........................................................................ [ 20%]
........................................................................ [ 41%]
........................................................................ [ 61%]
........................................................................ [ 82%]
...............................................................          [100%]
=============================== warnings summary ===============================
tests/test_ui_attachments.py::test_repeated_charts_across_turns_and_new_conversation
  /Users/camilo/Downloads/Agente-main/.venv/lib/python3.14/site-packages/PyPDF2/__init__.py:21: DeprecationWarning: PyPDF2 is deprecated. Please move to the pypdf library instead.
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
351 passed, 1 warning in 4.75s
```

Tiempo de pared observado por el envoltorio de ejecución: 5,319 s. La advertencia exige migrar de `PyPDF2` a `pypdf`, pero no afecta el resultado de esta corrida.

### 5.2. Distribución de casos

| Archivo | Casos |
|---|---:|
| `test_agent_service.py` | 39 |
| `test_analysis_context.py` | 19 |
| `test_analytics.py` | 5 |
| `test_bicomp_advanced.py` | 6 |
| `test_bicomp_repository.py` | 8 |
| `test_config.py` | 3 |
| `test_conversation_state.py` | 67 |
| `test_data_quality.py` | 17 |
| `test_evaluations.py` | 2 |
| `test_facts.py` | 12 |
| `test_memory_cache.py` | 8 |
| `test_periods.py` | 11 |
| `test_planner.py` | 82 |
| `test_registry.py` | 28 |
| `test_response_validator.py` | 26 |
| `test_semantic.py` | 1 |
| `test_sql_guard.py` | 10 |
| `test_ui_attachments.py` | 3 |
| `test_visualization.py` | 4 |
| **Total** | **351** |

### 5.3. Calidad y realismo

- **187/351** casos pertenecen a archivos que sustituyen explícitamente al menos una frontera externa mediante fake, mock o monkeypatch. El número describe archivos/casos con dobles, no implica que cada aserción sea superficial.
- Los **164 restantes** ejercitan lógica local real con datos sintéticos y sin I/O externo.
- **0/351** realizan una integración real verificable con NVIDIA o BigQuery. El propio README declara que las pruebas son simuladas.
- Los 82 casos del planner reciben salidas ya interpretadas o gateways controlados; no miden la capacidad real del modelo para interpretar lenguaje abierto.
- Al menos tres casos son principalmente estructurales/de carga: conteo del registro, nombres de herramientas y carga de semántica. Cargar una propiedad no demuestra que gobierne la ejecución.
- No se encontró `pytest-cov` ni `coverage` en el entorno, por lo que **no se reporta ni se estima cobertura de líneas**.

La suite es valiosa para lógica determinista, contratos y regresiones rápidas. Su tiempo total de menos de cinco segundos confirma que no prueba latencia, concurrencia ni servicios remotos reales.

### 5.4. Regresiones que faltan

- Cambio de eje posterior a la ejecución con normalización de familias `medio`/`medio_agrupado` y rechazo de composición degenerada.
- Prueba integrada de texto contra datos del gráfico, etiquetas, rango y ticks.
- Cierre de contribuciones cuando `drivers_total > limit`, con residual o advertencia comprobable.
- Interpretación real del proveedor LLM con repetición controlada y criterios estadísticos.
- Integración BigQuery sobre dataset efímero o snapshot, incluyendo cuotas, timeouts y límite de bytes.
- Autenticación, autorización, aislamiento multi-tenant y redacción de SQL/resultados/excepciones.
- Carga, concurrencia, streaming/progreso y presupuesto total de latencia.
- Adjuntos adversariales, PDF/OCR real y límites de tamaño.
- Atribución exacta cuando el mismo valor numérico aparece en varias filas o métricas.

## 6. Fortalezas y debilidades

### Fortalezas

- Separación clara entre planificación, ejecución, hechos, validación y visualización.
- Consultas parametrizadas, dry run, límite de bytes y guard SQL de solo lectura.
- Los hechos y gráficos consumen hoy la misma estructura de resultados.
- Catálogo semántico centralizado y registro explícito de herramientas.
- Suite local rápida y extensa para regresiones deterministas.
- Buen número de pruebas de periodos, SQL, estado, hechos y validación de respuestas.
- Documentación existente reconoce varias limitaciones en vez de ocultarlas.
- Artefactos históricos ricos para estudiar fallos y diseñar futuras pruebas.

### Debilidades

- Transiciones conversacionales críticas aún dependen de una etiqueta del LLM.
- Configuración semántica parcialmente decorativa: el runtime no ejecuta todas sus reglas.
- Benchmark sin aislamiento entre desarrollo, selección de casos y aceptación.
- Reporte agregado capaz de formar una “mejor corrida mosaico”.
- Sin autenticación, autorización, aislamiento de datos ni política de trazas segura.
- UI monolítica y bloqueante; no hay SLO ni observabilidad por etapa.
- Repositorio BigQuery y app concentran demasiada responsabilidad.
- No hay integración real ni ensayo de carga en la suite.
- Resultados históricos voluminosos dentro del repositorio dificultan gobernanza y revisión.
- Documentos discrepan sobre el número de pruebas y el alcance de algunas garantías.

## 7. Evaluación porcentual, reglas y confianza

### 7.1. Escala

- **90-100:** evidencia independiente y repetible; controles productivos completos.
- **75-89:** sólido, con brechas acotadas y pruebas representativas.
- **60-74:** funcional, pero con riesgos importantes o evidencia incompleta.
- **40-59:** no listo sin mitigaciones mayores.
- **0-39:** riesgo crítico o ausencia de evidencia esencial.

Cada porcentaje combina evidencia de código, pruebas, artefactos y documentación. Cuando la evidencia está contaminada, simulada o histórica, se reduce la confianza, no se convierte una ausencia de medición en un cero funcional.

### 7.2. Puntuaciones

| Eje | Peso productivo | Nota | Confianza | Fundamento |
|---|---:|---:|---|---|
| Arquitectura | 10 % | 76 % | Alta | Separación útil, sin ciclos; módulos centrales demasiado grandes |
| Correctitud funcional | 20 % | 68 % | Media-baja | Buenas regresiones, pero fallo de cambio de eje y sin conjunto ciego |
| Correctitud numérica | 15 % | 85 % | Media | Fórmulas y campos coherentes; cierre top-N y prueba integrada pendientes |
| Estado conversacional | 10 % | 68 % | Media-baja | 49/54 en últimas familias completas observadas, pero casos conocidos y variabilidad |
| Calidad de pruebas | 10 % | 70 % | Alta | 351 pasan; cobertura y fronteras reales ausentes |
| Metodología de evaluación | 10 % | 25 % | Alta | Contaminación, mezcla de corridas y cero casos ciegos certificables |
| Robustez/operación | 10 % | 55 % | Media | Timeouts y defensas parciales; sin carga, SLO ni presupuesto total |
| Presentación/UX | 5 % | 45 % | Media | Gráficos coherentes en datos, pero UI bloqueante y ambigüedad visual |
| Seguridad y gobernanza | 10 % | 48 % | Media | Buen control SQL, sin identidad/tenancy y con trazas expuestas |
| Mantenibilidad* | — | 67 % | Alta | Código legible, pero duplicación, piezas inactivas y archivos grandes |

\* Mantenibilidad se informa como diagnóstico y no se suma para evitar doble conteo con arquitectura, pruebas y operación.

La media ponderada técnica de los nueve ejes productivos es **62,8/100**. Sin embargo, se aplica una regla de puerta: un sistema no puede superar 59 mientras carezca de autenticación/autorización en una aplicación con datos empresariales, ni superar 49 mientras no exista evaluación ciega reproducible. Al concurrir ambas, la calificación de preparación productiva es **45/100**.

La métrica conversacional observada de referencia es **49/54 = 90,7 %** para `default_original` (12), `completion_additional` (12) y `default_paraphrases` (25). Su confianza como regresión es media; como estimación de generalización es muy baja, por contaminación y heterogeneidad.

## 8. Plan priorizado

### P0 — puertas antes de producción

1. Implementar una normalización determinista de familias de filtros y una regla de transición que elimine todos los filtros del eje promovido, independientemente de la etiqueta emitida por el LLM.
2. Añadir una validación posterior a la consulta: si se solicitó composición/distribución y solo queda una categoría por un filtro del mismo eje, corregir el alcance o pedir confirmación; nunca presentar silenciosamente 100 %.
3. Crear un benchmark ciego sellado. Congelar commit, modelo, parámetros, datos, IAM y oráculo; impedir reentrenar o corregir contra la misma aceptación.
4. Cambiar el agregador para producir resultados por corrida y versión, sin seleccionar el mejor resultado por pregunta entre ejecuciones.
5. Incorporar autenticación, autorización por rol/tenant, filtros obligatorios de datos y trazas seguras por defecto. Redactar SQL, resultados sensibles y excepciones.

Criterio de salida P0: cero fallos críticos en el conjunto ciego; repetibilidad con intervalo publicado; pruebas negativas de autorización; ningún SQL, resultado o stack trace expuesto a perfiles no autorizados.

### P1 — exactitud, cierre y experiencia

1. Unificar en runtime y evaluador las equivalencias `medio`/`medio_agrupado` y cualquier otra familia declarada en `filter_groups`.
2. Ejecutar realmente las reglas semánticas declaradas o eliminarlas de configuración/documentación para evitar garantías falsas.
3. Añadir cierre para top-N de drivers mediante residual “otros/no mostrado” y probar la invariante con tolerancia.
4. Añadir pruebas de contrato integradas entre hechos, texto final y figura; mostrar etiquetas exactas de valor.
5. Definir SLO de turno y presupuesto total. Instrumentar tiempos de planificación, consulta, revisión, finalización y render; mostrar progreso o streaming.
6. Crear pruebas de integración controladas para LLM y BigQuery, separadas de la suite rápida.

Criterio de salida P1: divergencia texto-gráfico igual a cero en contratos; cierre explícito de contribuciones; P95 dentro del SLO acordado y sin bloqueos silenciosos.

### P2 — mantenibilidad y gobernanza

1. Dividir `app.py` y `bigquery_repository.py` por responsabilidad.
2. Alinear `DataRepository` con el uso real, reducir wrappers legacy y confirmar consumidores externos antes de retirarlos.
3. Eliminar imports y helpers sin uso después de validar compatibilidad.
4. Consolidar la lógica de formato/presentación y el tratamiento de valores ausentes.
5. Versionar artefactos de evaluación fuera del árbol principal o establecer retención, manifiestos y metadatos de procedencia.
6. Actualizar documentación: 351 pruebas, naturaleza simulada, reglas realmente activas y límites verificables.
7. Migrar de `PyPDF2` a `pypdf` y añadir controles adversariales de adjuntos.

## 9. Límites y aspectos no verificados

- No se consultó BigQuery ni NVIDIA en vivo; por tanto, no se validaron datos actuales, permisos IAM, cuotas, costos, latencia ni estabilidad del proveedor.
- No se reejecutó el benchmark conversacional externo. Sus métricas se analizaron desde código, documentos y artefactos existentes para no introducir otra corrida no controlada.
- Las capturas originales del supuesto desacuerdo texto-gráfico no estaban disponibles; se auditó la ruta de código actual y se formuló una inferencia sobre ticks automáticos.
- No se midió cobertura de líneas o ramas porque el entorno no contiene `pytest-cov`/`coverage`; no se presenta una estimación inventada.
- No se realizó pentest, análisis de dependencias/CVE, revisión de infraestructura, despliegue, secretos remotos, logs ni políticas organizacionales.
- No se verificaron consumidores externos de las APIs públicas y wrappers legacy.
- Los conteos de líneas son físicos y los artefactos JSON pueden contener duplicados o versiones históricas.
- Las referencias numéricas históricas, incluido el ejemplo BMW, no garantizan que la fuente siga devolviendo los mismos valores.
- “Cero casos ciegos” significa cero casos con ceguera demostrable y manifiesto sellado en el repositorio, no prueba de que todos los casos hayan sido leídos individualmente.
- Esta auditoría evalúa el estado del commit indicado. Cambios locales o remotos posteriores pueden invalidar hallazgos y porcentajes.

---

**Dictamen:** el agente es una base de ingeniería prometedora y una herramienta de demostración/regresión útil, pero no debe presentarse todavía como un sistema BI autónomo validado para producción. El orden correcto es cerrar primero la semántica de transiciones, la independencia del benchmark y la seguridad de acceso; después optimizar latencia y mantenibilidad.
