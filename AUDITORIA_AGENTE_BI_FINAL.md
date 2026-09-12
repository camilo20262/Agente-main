> Revisión histórica de la arquitectura anterior. La auditoría posterior de memoria, transiciones y capacidades está en [CONVERSATION_STATE_AUDIT.md](CONVERSATION_STATE_AUDIT.md).

# Auditoría final del agente BI

Fecha de revisión: 11 de septiembre de 2026. Revisión de código, pruebas automatizadas, ejecución real contra NVIDIA y BigQuery y conversaciones completas. Repositorio de partida: `aac4976`. El alcance comprende los entrypoints, UI, agente, registro, repositorio, semántica, cálculo, caché, memoria, visualización, configuración y evaluaciones.

## 1. Resumen ejecutivo

El agente tiene una arquitectura más controlable y auditable: interpretación mediante LLM, alcance central, operaciones de seguimiento explícitas, investigación acotada y matemática ejecutada por SQL/Python. El lookup obligatorio de BMW en 2025 se ha resuelto realmente con una llamada de planificación y un job de consulta BigQuery. No fue necesario aumentar el límite de ocho pasos.

Resultado de cierre: **284 tests aprobados; 46/46 preguntas con PASS en su último intento bajo los criterios aplicados; nueve contrastes numéricos independientes aprobados.** La conversación obligatoria completa terminó con siete turnos aprobados en `elliptical_retest`. El resultado de 46 preguntas reúne varias versiones/corridas; no equivale a una única corrida completa sobre la versión final. Los fallos anteriores permanecen visibles.

Las pruebas reales detectaron problemas que los mocks no habían expuesto: marca confundida con anunciante; referencias temporales desplazadas dos veces; pérdida de filtros presentes solo en herramientas; pérdida de profundidad al cambiar el año; composición usada para responder una variación; porcentajes calculados por el narrador; y rechazo incorrecto de cifras que formaban parte de etiquetas o fechas. Las correcciones se acompañaron de regresiones y nuevas ejecuciones.

**Dictamen:** apto para evaluación interna supervisada, con controles y evidencia verificables. Un benchmark finito y un validador heurístico no justifican afirmar que comprende correctamente cualquier pregunta. El pase a producción depende de los riesgos P0 de esta auditoría y del resultado observado en la última corrida, documentado sin ocultar fallos en [BENCHMARK_AGENTE_BI.md](BENCHMARK_AGENTE_BI.md).

## 2. Arquitectura final

Flujo efectivo:

1. CLI o Streamlit envían pregunta, conversación y adjuntos al mismo `AgentService`.
2. El gateway solicita un plan JSON. El modelo declara intención, operación conversacional, filtros, periodo simbólico, dimensiones, preguntas analíticas y pasos.
3. `transitions.py` compila esa operación sin inspeccionar el texto de la pregunta; `AnalyticalPlanner` valida el resultado frente al contrato y modelo semántico.
4. `AnalysisContext` resuelve el calendario y alcance. Cobertura se obtiene desde caché o BigQuery cuando hace falta anclar un periodo relativo.
5. `ToolExecutor` normaliza aliases, aplica el alcance, valida, evita duplicados y utiliza caché de éxitos.
6. El registro despacha herramientas parametrizadas. BigQuery agrega; Python calcula métricas derivadas. SQL completo queda disponible en la evidencia.
7. Se conserva memoria del alcance y estrategia. Las perspectivas ya resueltas y el presupuesto permiten detener; el LLM puede proponer una siguiente consulta justificada.
8. Lookup se presenta de forma determinística. Para otras respuestas, Python prepara hechos identificados; el LLM selecciona hechos e interpreta; Python compone la respuesta.
9. Se valida el texto completo. Como máximo hay una reparación sin herramientas; un segundo rechazo produce respuesta parcial segura.
10. Los gráficos se generan a partir de resultados exitosos y conservan entidad, métrica y periodo cuando están disponibles.

Véase el diagrama y las decisiones detalladas en [CAMBIOS_ARQUITECTURA_AGENT.md](CAMBIOS_ARQUITECTURA_AGENT.md).

## 3. Cambios por archivo

| Archivo | Qué cambió y qué problema resuelve |
|---|---|
| `agent.py` | Servicio y repositorio independientes por sesión; fachada pública conservada. Evita mezclar métricas y caché entre conversaciones. |
| `cli.py` | Manejo de fallos por turno; mantiene la conversación operativa. |
| `app.py` | Prompt único, configuración compartida, claves de charts por turno, adjuntos y limpieza de sesión. Corrige duplicación de gráficos, PDF obsoleto y MIME inconsistente. |
| `src/config.py`, `.env.example` | Validación de límites, presupuesto narrativo separado, timeouts, visión, historial y endpoint coherente con la key configurada. |
| `src/agent/planner.py` | Plan estructurado, presupuestos e invariantes semánticas; deja de depender de reconocimiento de preguntas conocidas. |
| `src/agent/transitions.py` | Conserva objetivo/estrategia al cambiar periodo o entidad; convierte el desglose de una comparación en drivers; delimita el pico conocido. |
| `src/agent/analysis_context.py` | Unifica alcance, filtros y referencias; impide ampliaciones y desplazamientos dobles de fechas relativas. |
| `src/agent/periods.py` | Resolución de fechas, cobertura y equivalencia de periodos, incluidos bisiestos y meses de diferente duración. |
| `src/agent/service.py` | Orquestación acotada, recuperación limitada y preservación de evidencia ante fallos opcionales. |
| `src/agent/execution.py` | Límite común de ejecución, aliases, caché, duplicados y trazas. |
| `src/agent/sufficiency.py` | Comprueba capacidades de resultados; metadatos solos no bastan para una cifra o comparación. |
| `src/agent/llm.py` | Gateway con etapas separadas, JSON, tokens, timeout y un reintento para errores transitorios admitidos. |
| `src/agent/prompts.py` | Roles separados y contrato de operaciones; hipótesis, cobertura, matemática y narrativa mediante IDs de hechos. |
| `src/agent/facts.py` | Frases numéricas calculadas, con procedencia; limita hechos y omite prosa cuantitativa redundante del modelo. |
| `src/agent/finalization.py` | Finalización sin consultas, reparación completa única y fallback determinístico. |
| `src/agent/response_validator.py` | Grounding, porcentajes, fechas, magnitudes de caídas, cierre del output, cobertura y varias clases de causalidad no demostrada. |
| `src/agent/memory.py` | Conserva alcance base, estrategia, referencias, entidades comparadas y pico; no sustituye el alcance por el último drilldown. |
| `src/agent/cache.py` | TTL, capacidad, copias independientes y solo resultados exitosos. |
| `src/agent/observability.py` | Tokens y eventos de planificación, investigación, ejecución, validación y parada. |
| `src/analytics/calculations.py` | Comparaciones, shares, concentración, dispersión, cambios observados, picos y anomalías. |
| `src/data/bigquery_repository.py` | Cobertura eficiente, denominadores completos, normalización, drivers genéricos, ratios, catálogos y comparación de entidades. |
| `src/data/sql_guard.py` | Parseo de SQL con AST, rechazo de múltiples sentencias/escritura y validación de fuentes físicas. |
| `src/tools/registry.py` | Contratos y aliases estrictos, errores clasificados, capacidades nuevas y compatibilidad con wrappers anteriores. |
| `src/semantic/business_rules.yaml`, `dimensions.yaml` | Default de entidad y distinción marca/anunciante explícitos. |
| `src/visualization/charts.py` | Títulos con contexto, tipos de comparación/serie/ranking y contribuciones por partición. |
| `evaluations/benchmark.py`, `evaluator.py`, `report.py`, `holdout_cases.json` | Ejecución real optativa, simulación, casos adicionales y reporte reproducible que conserva el último resultado y los falsos positivos manuales. |
| `tests/` | Regresiones de los fallos observados y cobertura funcional adicional. |
| `requirements.txt`, `README.md` | Dependencia sqlglot y documentación operativa actualizada. |

## 4. Estado inicial comprobado

El baseline registró **132 tests: 106 aprobados y 26 fallidos**, en 1,49 segundos. La pregunta real «¿Cuánto invirtió BMW en 2025?» falló en la primera llamada al proveedor con HTTP 500, sin consultas BigQuery. Evidencia: [baseline.json](evaluations/results/baseline.json).

El límite de ocho pasos aparecía como condición de salida de una conversación de herramientas en vez de existir un criterio suficiente por intención. Se mezclaban interpretación, investigación y redacción; había contratos divergentes entre aliases, pruebas y herramientas, recuperación poco controlada, y memoria vulnerable al alcance del último resultado. No todos los fallos iniciales eran errores del motor: algunas expectativas de tests correspondían al contrato antiguo. Se migraron esas expectativas conservando las propiedades de seguridad y comportamiento que debían probar.

## 5. Problemas solucionados

| Severidad | Problema | Evidencia de la corrección |
|---|---|---|
| CRÍTICO | Lookup podía investigar hasta el fusible de ocho pasos. | Presupuesto lookup=1; tests por varias entidades y llamadas reales de una consulta. |
| CRÍTICO | Comparar año completo con acumulado parcial y atribuir crecimiento. | Ventanas equivalentes calculadas; tests YTD/bisiestos y consultas reales enero-julio. |
| CRÍTICO | Narrativa introducía shares y sumas no calculados. | Hechos determinísticos, selección por ID, omisión de prosa cuantitativa y rechazo de porcentajes nuevos. |
| ALTO | Scope/memoria perdían filtros que sí llegaban a BigQuery. | Filtros comunes elevados al alcance; memoria base y regresión. |
| ALTO | Cambiar el año cambiaba la intención y profundidad. | Operación declarada por LLM y reutilización de su estrategia anterior. |
| ALTO | Desglose de una variación respondido como mix. | Compilación de breakdown a drivers de la referencia conservada. |
| ALTO | Referencia `previous_year` podía desplazarse dos veces. | Resolución central y tests de comparación simbólica/inherencia. |
| ALTO | Error opcional destruía resultados y memoria útiles. | Finalización de evidencia suficiente y preservación del fallo en la traza. |
| ALTO | Cifras asociadas a marca y anunciante eran intercambiadas. | Regla semántica de entidad por defecto y validación de tipo explícito/heredado. |
| ALTO | Resultado vacío/NULL confundido con cero o éxito. | Resultados sin métrica numérica no son éxitos cuantitativos; ratios indefinidos se reportan. |
| MEDIO | Aliases descartados o filtros conflictivos ignorados. | Normalización segura y rechazo de conflictos/propiedades no declaradas. |
| MEDIO | Denominador de ranking reducido a Top N. | Window functions antes de LIMIT y tests de universo completo. |
| MEDIO | Etiquetas con dígitos, fechas y porcentajes de cuatro cifras daban falsos rechazos. | Parser de presentación y tests contra casos reales. |
| MEDIO | Duplicados y fallos de infraestructura generaban intentos repetidos. | Deduplicación por llamada normalizada, corrección única y parada clasificada. |
| MEDIO | Gráficos repetidos y adjuntos persistentes en UI. | AppTest con dos turnos, rerun y conversación nueva; PNG real y PDF por hash. |
| BAJO | Títulos sin alcance y métricas de operación incompletas. | Contexto en charts y contadores/trazas por turno. |

La revisión final añadió correcciones de clases de error que habían pasado el evaluador inicial:

- Rankings dentro de grupos: nueva herramienta genérica con dos dimensiones, denominador por grupo y validación de dimensiones explícitas. El planner rechaza una agrupación omitida y permite una reparación del plan antes de consultar.
- Participación conjunta: el hecho conserva valor, denominador y porcentaje; no basta con que la herramienta calcule el resultado si la respuesta lo omite.
- Ratios: etiqueta y unidad derivadas; un cociente no se presenta como el monto de la métrica del numerador.
- Datos ausentes: definición común de etiquetas en SQL/Python, incluidos N/D y ND; aviso de calidad obligatorio cuando hay participación desconocida. No se ofrecen esas filas como líderes del catálogo factual si existe un resumen de calidad.
- Aritmética verbal: se elimina prosa opcional con fracciones o múltiplos escritos en palabras, además de dígitos. Esto incluye el falso positivo real «más de una sexta parte» para 15,69 %.
- Inspección de pico: conserva el mes calculado y evalúa sus desgloses como diagnóstico, sin exigir una nueva serie para considerarlos suficientes.
- Corrección de una consulta innecesaria: si el modelo decide explícitamente detenerse y las capacidades de la evidencia ya satisfacen la intención, se omite el paso y se conserva el fallo original en la traza.
- Drivers: cada hecho identifica sus entidades o periodos; no depende de que el narrador seleccione además una definición de A/B.
- Seguimiento temporal: se rechaza un año literal que cambia el foco heredado sin estar solicitado; el benchmark verifica orientación de actual/referencia en los siguientes turnos.
- Referencias opcionales: un objeto vacío se normaliza como ausencia, y cambiar únicamente la entidad conserva la referencia del diagnóstico reutilizado.
- Suficiencia: el análisis abierto también pasa la comprobación final de perspectivas. Un total más un ranking aislado no basta para declararlo completo.
- Explicaciones conceptuales: pueden mencionar causas posibles y patrones estacionales sin presentarlos como observaciones de una entidad real; se mantienen las validaciones de formato y respuesta vacía.
- Seguimientos elípticos: una conjunción seguida únicamente de una entidad identificada en el plan no autoriza comparar dos entidades. Se rechaza esa operación y se pide reparar el plan, manteniendo el objetivo previo. La comprobación no descubre nombres ni elige herramientas.

Una corrección de clase no prueba que el LLM nunca volverá a producir un plan inválido. El límite importante es que el sistema valide, conserve evidencia y no presente un resultado engañoso como éxito.

## 6. Problemas que permanecen

- La interpretación semántica sigue dependiendo del modelo. El compilador preserva operaciones declaradas, pero no puede demostrar que la operación que eligió el LLM corresponde siempre a la intención humana.
- El validador comprueba pertenencia numérica y varias formas de causalidad; **no prueba universalmente que cada cifra se atribuya a la entidad, periodo y frase correctos**. La selección de hechos reduce ese riesgo; la interpretación cualitativa aún necesita evaluación humana.
- La narrativa puede perder parte de la interpretación si el proveedor insiste en insertar cálculos en campos cualitativos. Se conserva el hecho calculado y se omite esa prosa, en vez de aprobar un cálculo nuevo.
- En algunas respuestas el resumen queda sin prosa introductoria, aparecen títulos genéricos «Hallazgo» o se repite evidencia temporal. La investigación puede cubrir más dimensiones de las que el narrador finalmente selecciona. La calidad editorial todavía necesita una evaluación específica.
- El pipeline conserva compatibilidad con texto plano del proveedor; ese camino usa validación, pero no la selección explícita de IDs. No debe confundirse con una garantía formal de salida estructurada.
- Catálogos con etiquetas semánticas duplicadas y dimensiones con mucha información ausente requieren gobierno del dato. No se fusionan automáticamente.
- Cobertura MIN/MAX de tabla no demuestra completitud diaria, carga completa por entidad ni ausencia real de inversión en días sin filas.
- Los errores 429, 500, latencia y disponibilidad del proveedor se observaron realmente. Hay límites y fallbacks; no se ha implementado un coordinador de cuota global ni alta disponibilidad.
- El wrapper genérico legado `explicar_variacion` conserva su restricción a marca; las capacidades nuevas permiten drivers genéricos y entre entidades. No se debe anunciar que todos los métodos históricos tienen idéntica capacidad.
- No se midió cobertura de líneas: el entorno no tenía `coverage`/`pytest-cov`. Se reportan casos y comportamiento, no un porcentaje inventado.
- `PyPDF2` emite aviso de deprecación. PDFs escaneados no tienen OCR en esta implementación; visión solo se habilita explícitamente.
- La UI mantiene historial para presentación. El input del modelo está acotado, pero no se ha realizado una prueba de carga de sesiones extremadamente largas ni un estudio de consumo de memoria multiusuario.
- La redacción selecciona hallazgos y no siempre enumera todo el Top N solicitado. El ranking completo devuelto queda en la evidencia; el catálogo factual usa hasta diez filas y el ranking segmentado limita el resultado a 500 filas con aviso de truncamiento. Conviene ofrecer exportación o paginación explícita para pedidos exhaustivos.
- La validación de agrupación explícita reconoce nombres/sinónimos del modelo semántico y una construcción acotada «por [cada] dimensión». No es un parser general de lenguaje natural ni garantiza detectar toda paráfrasis omitida.
- El guard de seguimiento elíptico reconoce una gramática pequeña sobre entidades que ya identificó el LLM. No cubre todas las maneras de cambiar de entidad. Las paráfrasis y las decisiones semánticas fuera de ese contrato siguen siendo un riesgo P0 de evaluación.
- No hay gráfico específico del ranking segmentado; la evidencia y narrativa conservan el grupo. El soporte gráfico anterior se mantiene.

Los resultados concretos que sigan fallando están identificados por pregunta y artefacto en el benchmark. No se descartan del denominador ni se cuentan fallbacks como análisis completos.

## 7. Planner y generalización

El contrato admite lookup, ranking, tendencia, composición, comparación de entidades, comparación temporal, diagnóstico, análisis abierto, anomalías, catálogos, cobertura, adjuntos, aclaración e interacciones conceptuales. Usa dimensiones y métricas cargadas desde YAML, verificadas después frente al esquema real.

No hay ramas sobre las marcas o años del benchmark en el backend. La validación de nombres de dimensiones, operaciones e interfaces sí es determinística: es un contrato, no una lista de preguntas conocidas. Las herramientas de compatibilidad permanecen registradas; el catálogo que ve el planner prioriza capacidades genéricas para evitar competencia entre wrappers equivalentes.

Una limitación relevante es que clasificar correctamente una intención no prueba seleccionar la investigación óptima. Por eso el benchmark revisa también entidades, periodos, herramientas, profundidad y tipos de evidencia en seguimientos.

## 8. Grounding

Las agregaciones, shares, diferencias, ratios, contribuciones y picos vienen de SQL/Python. La evidencia compacta de investigación excluye SQL y metadatos voluminosos. La etapa narrativa recibe frases numéricas con IDs y alcance. Los IDs desconocidos y JSON incompleto se rechazan.

Se permite presentar valores redondeados. Se distinguen porcentajes y cantidades; un porcentaje sin evidencia porcentual falla. Una disminución puede expresarse verbalmente como magnitud positiva si existe evidencia de la diferencia negativa. Dígitos dentro de etiquetas exactas no se interpretan como cantidades.

Las hipótesis tienen sección y método de validación; el validador controla varias causas comerciales frecuentes. No es un detector completo de toda causalidad implícita ni un juez universal del lenguaje natural.

## 9. Capa de datos

Fuente comprobada: `nexuslatam-master.NEXUS_GROUPM_BI_2.tb_data_bicompetitive`. El baseline consultó el esquema físico y registró 776.552 filas, con cobertura de **2019-01-01 a 2026-07-31**. El modelo semántico expone 24 dimensiones y seis métricas, no todas las columnas físicas indiscriminadamente.

- SQL parametrizado para valores; identificadores admitidos solo por semántica y esquema.
- Parseo AST, una consulta SELECT, fuentes permitidas y bloqueo de operaciones de escritura/fuente EXTERNAL_QUERY.
- Dry-run y máximo de bytes antes del job real. El contador de BigQuery mide jobs de consulta ejecutados, no incluye el dry-run ni la lectura de metadatos del esquema.
- Agregación completa antes de LIMIT; shares no se calculan sobre la muestra mostrada.
- TRIM/UPPER en texto sin homologar aliases semánticos.
- Estadística sobre periodos observados, sin imputar automáticamente cero. Picos descriptivos no demuestran estacionalidad; MAD requiere observaciones y dispersión suficientes.
- Drivers calculados con categorías completas antes de limitar la salida. Particiones de dimensiones distintas no se suman entre sí.
- Comparaciones temporales se alinean; comparaciones entre entidades usan el mismo intervalo. Referencia temporal e identidad de entidad son conceptos separados.

## 10. Contexto conversacional

La memoria conserva métricas, filtros, periodo solicitado, referencia, dimensiones, intención, entidades comparadas, estrategia y pico. La estrategia inicial se reutiliza si el usuario cambia solo periodo/entidad y el plan nuevo contradice el objetivo previo. Los argumentos del alcance antiguo se retiran antes de ejecutarla en el nuevo contexto.

Se probaron conversaciones completas, no turnos independientes que simulan contexto. El benchmark comprueba la continuidad de entidad y año, el desglose de una variación, la pareja comparada y el mes pico calculado. Las trazas de cada ronda permiten ver regresiones y correcciones.

## 11. Terminación

La salida normal ocurre al completar evidencia planificada o suficiente para la intención. Los diagnósticos con comparación/contribuciones pueden terminar con una herramienta. El LLM puede ampliar un análisis abierto, pero cada paso necesita propósito y presupuesto. Un duplicado no dispara otra consulta; un error corregible tiene como máximo una corrección. La respuesta textual también identifica explícitamente un análisis parcial cuando una investigación incompleta tiene evidencia utilizable.

No se aumentó el fusible de ocho pasos. Un fallo opcional puede quedar registrado sin invalidar el análisis principal si la evidencia ya es suficiente. Si falta evidencia requerida, se marca parcial.

## 12. Validación del output

Se comprueba respuesta vacía, terminación del proveedor, frase aparentemente incompleta, Markdown abierto, tablas no deseadas, cifras/porcentajes sin evidencia, cobertura parcial, varias causas no demostradas y afirmaciones de estacionalidad insuficiente. La reparación reescribe toda la respuesta, recibe el rechazo anterior y no vuelve a consultar datos.

Los hechos numéricos se insertan desde Python. La prosa opcional cuantitativa se omite; la cualitativa se conserva y valida. Un fallback es explícitamente parcial y no se cuenta como un análisis aprobado en el benchmark.

## 13. Performance y costo

El lookup real simple llegó a una llamada al LLM y un job BigQuery. Rankings/mix habitualmente requieren un job y una llamada de redacción adicional. Comparaciones y drivers pueden ejecutar varios jobs dentro de una herramienta; pasos y jobs no son equivalentes.

Se registran latencia, tokens de entrada/salida, intentos de proveedor, jobs, bytes y caché. Los datos de cada ronda están en los JSON; el resumen estadístico final está en el benchmark. No se convierte ese consumo a dinero sin conocer tarifas y contrato aplicables. El efecto de caché de BigQuery se conserva, incluidos cero bytes cuando el proveedor del job lo reporta.

## 14. Visualizaciones y UI

Gráficos determinísticos a partir de evidencia exitosa, con periodo efectivo y entidad cuando están disponibles. Comparaciones, series, ranking y contribuciones tienen presentaciones distintas. Las claves incluyen turno e índice para evitar colisión en reruns.

AppTest ejecutó dos turnos con el mismo gráfico, rerenderizado y nueva conversación. Se verificó limpieza de PDF/portapapeles y estado gráfico. No se realizó un estudio de usabilidad ni una prueba visual exhaustiva en todos los tamaños de pantalla. Los adjuntos se tratan como datos, sin insertarlos como instrucciones de sistema.

## 15. Tests

Baseline: 132 casos, 106 aprobados y 26 fallidos. Suite final: **284 aprobados, cero fallidos, un aviso de deprecación**, en 2,97 segundos. El inventario aumenta en 152 casos frente al baseline; se añadieron regresiones y se migraron tests al contrato nuevo. Incluye unitarios, integración simulada del servicio y ejecución de UI con AppTest. Comprobación de dependencias, parseo de 54 archivos Python y revisión de whitespace aprobadas; detalles en [final_verification.json](evaluations/results/final_verification.json).

Cobertura funcional: planner, operaciones de seguimiento, herencia, aliases, filtros conflictivos, SQL, nulos, cobertura, YTD, bisiestos, ventanas equivalentes, shares, ranks, picos, anomalías, contribuciones, ratios, repetición, fallos, reparación, grounding, finalización, tokens/historial, gráficos y adjuntos. No se eliminaron escenarios válidos para conseguir verde; se reemplazaron supuestos del contrato antiguo por verificaciones del comportamiento nuevo y se agregaron regresiones.

Aviso conocido: deprecación de PyPDF2. No hay porcentaje de cobertura de líneas disponible.

## 16. Benchmark real

El runner llama al servicio real con el modelo configurado y BigQuery operativo. Incluye 28 preguntas independientes, dos conversaciones y ocho preguntas adicionales, para **46 preguntas distintas**. Cuatro preguntas se generan a partir de dimensiones semánticas disponibles. Comprende datos ausentes, dimensión incompleta, ambigüedad, conceptos sin consulta, ranking, mix, ratio, YTD, anomalías y seguimientos. Se hicieron múltiples rondas y repeticiones; no se contabilizan intentos repetidos como preguntas nuevas.

La corrida completa `acceptance` registró 43/46 automáticamente, pero la lectura de respuestas detectó otros once defectos: su resultado combinado fue 32/46. Se preservan esos falsos positivos y sus correcciones en `manual_review.json`. El resultado vigente se calcula con el último intento de cada pregunta y su procedencia, sin escoger el mejor histórico. Las repeticiones posteriores no constituyen otra corrida completa de 46 sobre una misma versión.

SQL independiente contrastó nueve valores de totales, YTD, variaciones, inserciones y ratio: nueve aprobados. No se verificaron todas las cifras del corpus mediante una segunda implementación independiente.

Las últimas salidas de esos casos se volvieron a contrastar contra la misma instantánea SQL: [numeric_latest_recheck.json](evaluations/results/numeric_latest_recheck.json), nueve coincidencias. Es una comprobación offline contra esa referencia, no una segunda consulta nueva a la fuente.

La última modificación del renderer se comprobó además con evidencia real preservada, sin nuevas llamadas: [narrative_recheck.json](evaluations/results/narrative_recheck.json). La comprobación de profundidad de análisis abiertos se aplicó a las trazas reales en [open_depth_recheck.json](evaluations/results/open_depth_recheck.json). Estas comprobaciones offline se distinguen de una nueva ejecución del proveedor.

El [benchmark detallado](BENCHMARK_AGENTE_BI.md) contiene por caso pregunta, intención, herramientas, pasos, jobs, llamadas al modelo, resultado y PASS/FAIL. También conserva todas las rondas anteriores y sus errores. Las aclaraciones válidas por categorías inexistentes no se confunden con un valor de inversión; los fallbacks quedan como FAIL salvo el caso que explícitamente prueba ausencia de datos.

## 17. Riesgos técnicos actuales

La estabilidad del proveedor, las cuotas, la interpretación de operaciones ambiguas y las atribuciones cualitativas son los riesgos principales. Hay protección mecánica ante salidas inválidas, pero no una garantía universal de razonamiento. La aplicación del repositorio no implementa autorización por usuario/cliente; no se evaluaron los controles externos del despliegue ni su configuración IAM.

Los artefactos de evaluación contienen cifras y SQL de negocio, además de respuestas rechazadas. Deben mantener el control de acceso correspondiente a la fuente. No contienen deliberadamente keys ni tokens de autenticación.

## 18. Deuda técnica

El repositorio BigQuery sigue concentrando consultas y wrappers históricos; un siguiente refactor podría separar constructores de consultas y contratos de resultados tipados. La configuración semántica necesita un contrato de moneda/unidades más explícito. El guard SQL es defensa adicional sobre consultas construidas, no una interfaz de SQL libre ofrecida al modelo.

Conviene sustituir PyPDF2, decidir retención de historial/UI, formalizar observabilidad externa y agregar datasets pequeños de referencia con resultados esperados independientes. El generador de hechos debe seguir mejorando brevedad y orden sin perder trazabilidad.

## 19. Recomendaciones

**P0, antes de producción:** verificar autorización de usuarios y alcance de datos en el despliegue; aprobar con el dueño de datos unidades, integridad y semántica de categorías; exigir evaluación humana de atribuciones y del benchmark adversarial con el modelo que se publicará; fijar el umbral de fallos aceptable y la política de resultados parciales.

**P1:** evaluación recurrente de conversaciones y paráfrasis, control de cuota global, métricas exportables y alertas, contrato tipado de resultados, pruebas de carga de sesiones, monitoreo de cobertura/completitud y revisión de todos los wrappers antiguos frente a capacidades nuevas.

**P2:** evaluación de modelos alternativos con el mismo corpus, OCR opcional, recuperación documental por fragmentos, visualizaciones adicionales y análisis temporal más sofisticado cuando la cobertura y la pregunta lo justifiquen.

## 20. Evaluación final

Escala de juicio técnico, no una medición estadística ni una promesa de generalización universal. Los resultados reales del benchmark pesan más que el número de tests.

| Eje | Nota / 10 | Justificación |
|---|---:|---|
| Arquitectura | 8 | Responsabilidades separadas y alcance central; persisten wrappers y repositorio voluminoso. |
| Generalización | 7 | Dimensiones/operaciones genéricas, sin casos por entidad; depende de interpretación del modelo. |
| Razonamiento analítico | 7 | Comparaciones, drivers, picos y profundidad dinámica; no garantiza investigación óptima. |
| Grounding | 8 | Hechos con IDs y validación; falta demostración semántica completa de atribuciones. |
| Confiabilidad numérica | 9 | Matemática en SQL/Python y pruebas de equivalencia/denominadores; sujeta a calidad de fuente y unidades. |
| Contexto | 7 | Alcance, estrategia y referencias explícitos; la ambigüedad todavía requiere pruebas continuas. |
| Tool selection | 7 | Capacidades genéricas y validación; el modelo puede elegir pasos redundantes o insuficientes. |
| Terminación | 9 | Presupuestos, deduplicación y reparación limitada; errores externos aún pueden producir parcial. |
| Calidad de respuesta | 6 | Hechos trazables y salidas completas; persisten títulos genéricos, repetición y resúmenes sin prosa al omitir cálculos del modelo. |
| Performance | 7 | Lookup barato y caché; análisis complejos dependen de latencia/cuota del proveedor. |
| Mantenibilidad | 8 | Componentes y regresiones más claros; conviene tipar contratos y separar consultas históricas. |
| Preparación para producción | 6 | Evaluación interna viable; autorización de despliegue, calidad del dato, carga y evaluación semántica requieren cierre P0. |

## 21. Roadmap

1. Revisar el benchmark final y cada FAIL con su plan/evidencia; repetir conversaciones con paráfrasis sin cambiar las entidades de prueba como única táctica.
2. Acordar semántica de unidades, cobertura y ausencias con responsables del dato; establecer cómo se comunica dato parcial.
3. Ejecutar evaluación humana con preguntas no usadas durante este trabajo y el modelo/endpoint finales; medir precisión por intención y operación.
4. Completar controles P0 del entorno de despliegue y ensayar cuotas, latencia, sesiones largas y fallos del proveedor.
5. Incorporar benchmark recurrente, dataset de referencia, alertas y mantenimiento de contratos antes de extender capacidades.

La auditoría no equipara «tests verdes» con «sistema infalible». Entrega código, evidencia reproducible y límites concretos para decidir el siguiente paso.
