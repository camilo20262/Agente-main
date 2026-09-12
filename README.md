# WPP Media Intelligence Agent

Agente analítico BICOMP que interpreta preguntas con un LLM y delega los cálculos cuantitativos a BigQuery y Python. La única fuente de datos es la tabla física `nexuslatam-master.NEXUS_GROUPM_BI_2.tb_data_bicompetitive`.

## Arquitectura

```
Streamlit/CLI → AgentService → AnalyticalPlanner → ToolRegistry → BigQueryRepository → respuesta + evidencia
```

El agente incluye memoria analítica compacta por sesión, caché TTL, métricas operativas y gráficos Plotly deterministas. Soporta inversión publicitaria, comparaciones de marcas y periodos, rankings de anunciantes y marcas, ranking genérico por cualquier dimensión (región, sector, holding, ciudad, agencia, etc.), análisis por medios y vehículos, inserciones, catálogos, cobertura, series temporales y explicación de variaciones.

**Robustez del agente:**
- Los argumentos de cada herramienta se validan contra su JSON Schema antes de ejecutar (tipos, campos requeridos, enums, formatos de fecha, y rechazo de propiedades no declaradas). Un argumento mal formado nunca ejecuta una consulta real.
- El planner reconoce preguntas de seguimiento que cambian solo el periodo o la dimensión (por ejemplo "¿y en marzo?" o "y para 2026" después de una consulta previa) sin perder el contexto de marca/métrica ya establecido.
- Si el agente agota los pasos permitidos o el modelo repite/inventa una herramienta, el sistema no falla con un error crudo: devuelve una respuesta parcial con la evidencia real obtenida hasta ese punto (marcada explícitamente como incompleta), sin presentar evidencia histórica como si respondiera una consulta nueva.
- La memoria separa el último alcance solicitado del último análisis exitoso y de la evidencia confirmada. Un fallo conserva la solicitud para el siguiente turno; sus cifras nunca se consideran evidencia.

## Requisitos previos

- Python 3.11 o superior.
- Acceso a un proyecto de Google Cloud con BigQuery habilitado y visibilidad sobre el dataset BICOMP.
- Una API key de NVIDIA (o el proveedor LLM compatible con OpenAI que se configure).
- Git instalado.

## Paso a paso para ejecutar en una computadora nueva

### 1. Clonar el repositorio

```bash
git clone https://github.com/camilo20262/Agente-main.git
cd Agente-main
```

### 2. Crear y activar el entorno virtual

```bash
python3 -m venv .venv
source .venv/bin/activate        # En Windows: .venv\Scripts\activate
```

### 3. Instalar dependencias

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Configurar variables de entorno

```bash
cp .env.example .env
```

Edita `.env` con tus valores reales. Variables principales:

```env
NVIDIA_API_KEY=
NVIDIA_MODEL=nvidia/nemotron-3-super-120b-a12b
NVIDIA_MODELS=nvidia/nemotron-3-super-120b-a12b,nvidia/nemotron-3.5-lightning-30b-a3b,deepseek-ai/deepseek-v4-flash-0731,nvidia/nemotron-3-ultra-550b-a55b
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
GCP_PROJECT_ID=nexuslatam-master
BIGQUERY_DATASET=NEXUS_GROUPM_BI_2
BIGQUERY_BICOMP_TABLE=tb_data_bicompetitive
BIGQUERY_LOCATION=US
BIGQUERY_MAX_BYTES_BILLED=1000000000
```

### 5. Autenticarse con Google Cloud

```bash
gcloud auth application-default login
gcloud config set project nexuslatam-master
```

La identidad usada necesita `roles/bigquery.jobUser` sobre el proyecto que ejecuta el job y `roles/bigquery.dataViewer` sobre el dataset (o permisos equivalentes). Si `gcloud` no está instalado, instala el [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) primero.

### 6. Configurar git (solo la primera vez en esta computadora)

```bash
git config --global user.name "Tu Nombre"
git config --global user.email "tu-correo@ejemplo.com"
```

### 7. Verificar que todo funciona

```bash
python -m pytest -q
```

Debería mostrar todos los tests en verde antes de continuar (no requiere credenciales de BigQuery ni NVIDIA — son pruebas con datos simulados).

### 8. Ejecutar el agente

**Interfaz web (Streamlit):**
```bash
streamlit run app.py
```
Se abre automáticamente en el navegador, normalmente en `http://localhost:8501`.

**Interfaz de línea de comandos:**
```bash
python cli.py
```
Escribe `salir`, `exit` o `quit` para terminar la sesión.

## Seguridad

Solo se permite SQL `SELECT`. Las operaciones de escritura se bloquean, la tabla se compara con una allowlist y los filtros se pasan como parámetros tipados. Cada consulta realiza dry-run y respeta `BIGQUERY_MAX_BYTES_BILLED`. La evidencia incluye SQL, parámetros, filas, bytes procesados y duración.

Los argumentos de cada herramienta se validan estrictamente contra su schema declarado (incluyendo rechazo de propiedades no declaradas) antes de que cualquier handler se ejecute, evitando que un argumento mal formado o mal ubicado se ignore en silencio y produzca una consulta sin los filtros solicitados.

## Esquema BICOMP

El repositorio valida cada métrica y dimensión aprobada contra el esquema real antes de consultar. Las métricas públicas son `inv_bruta`, `inv_neta`, `inv_bruta_usd`, `inv_neta_usd`, `total_insercion` y `total_duracion`. Las columnas adicionales de la tabla no se exponen automáticamente.

## Pruebas

```bash
python -m pytest -q
```

La suite cubre el registro de herramientas, el planificador, la memoria analítica, la caché, el guard de SQL, la capa semántica, la visualización y el servicio de orquestación completo (incluyendo recuperación ante fallos, contenido multimodal y respuestas parciales), usando datos y clientes simulados — no requiere conexión real a BigQuery ni a NVIDIA para ejecutarse.


## Auditoría y benchmark

El planner recibe intención, alcance, calendario simbólico y capacidades semánticas.
`AnalysisContext` resuelve fechas y valida el alcance antes de ejecutar. La narrativa
selecciona hechos numéricos preparados por Python; el validador controla porcentajes,
cobertura, terminación y varias clases de afirmaciones sin respaldo. La validación
no equivale a una demostración semántica completa.

- [Auditoría final](AUDITORIA_AGENTE_BI_FINAL.md)
- [Benchmark real y fallos](BENCHMARK_AGENTE_BI.md)
- [Decisiones de arquitectura](CAMBIOS_ARQUITECTURA_AGENT.md)

Para repetir el benchmark contra **el proveedor y BigQuery reales**:

```bash
python -m evaluations.benchmark --live --output evaluations/results/retest --workers 1
```

Cada JSON conserva pregunta, plan, filtros, SQL, respuesta, validaciones, uso y veredicto.
`--ids conversation-01` ejecuta la conversación completa para conservar contexto.
Los artefactos contienen datos de negocio y deben conservar el mismo control de acceso
que la fuente. El benchmark es optativo y no se ejecuta al lanzar pytest.

Variables adicionales (ver también `.env.example`):

```env
LLM_PLAN_MAX_TOKENS=2200
LLM_FINAL_MAX_TOKENS=1800
LLM_REASONING_EFFORT=none
LLM_TIMEOUT_SECONDS=60
BIGQUERY_TIMEOUT_SECONDS=45
RESPONSE_VALIDATION_RETRIES=1
HISTORY_MAX_MESSAGES=12
HISTORY_MAX_CHARS=16000
LLM_VISION_MODELS=
ENABLE_LOCAL_CLIPBOARD=0
```

Habilita visión únicamente para modelos cuya capacidad hayas confirmado. Sin visión
configurada, el agente explica esa limitación antes de procesar una imagen. Los PDF
se extraen como texto limitado y se adjuntan como datos, sin promoverlos a instrucciones.
El portapapeles opcional pertenece al equipo que ejecuta Streamlit.


## Estado conversacional y capacidades de cambio

La revisión del 12 de septiembre está en [CONVERSATION_STATE_AUDIT.md](CONVERSATION_STATE_AUDIT.md), con fallos históricos y comprobaciones por turno. El registro expone 24 herramientas. Crecimiento y aceleración, extremos temporales, diagnóstico de dimensiones y participación conjunta tienen contratos de evidencia separados de los rankings por nivel.

Las nuevas conversaciones reales se ejecutan explícitamente y consumen llamadas al proveedor y BigQuery:

```bash
.venv/bin/python -m evaluations.conversation_state --live --output evaluations/conversation_state/nueva_original
.venv/bin/python -m evaluations.conversation_state --live --conversation additional --output evaluations/conversation_state/nueva_adicional
.venv/bin/python -m evaluations.state_paraphrases --live --output evaluations/conversation_state/nuevas_parafrasis
.venv/bin/python -m evaluations.state_report
```

Los catálogos pequeños configurados se validan contra la fuente y usan caché. Televisión genérica corresponde a los valores exactos de `filter_groups.television`; no se fusionan etiquetas de la tabla. Un diagnóstico compara como máximo tres dimensiones no redundantes, con dos agregaciones por dimensión, y necesita al menos dos particiones útiles. Su puntuación indica concentración del cambio contable, no causalidad.

`PLAN_SEMANTIC_REVIEW=false` es el valor por defecto. La revisión LLM adicional de intención y alcance es experimental: las pruebas reales mostraron correcciones útiles y también cambios de periodo equivocados. Puede activarse con `true` para evaluación controlada; añade una llamada LLM sin herramientas y conserva una sola reparación de plan. Sus resultados se registran por separado.
