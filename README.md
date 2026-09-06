# WPP Media Intelligence Agent

Agente analítico BICOMP que interpreta preguntas con un LLM y delega todos los cálculos cuantitativos a BigQuery. La única fuente de datos es la tabla física `nexuslatam-master.NEXUS_GROUPM_BI_2.tb_data_bicompetitive`.

## Arquitectura

`Streamlit/CLI → AgentService → AnalyticalPlanner → ToolRegistry → BigQueryRepository → respuesta + evidencia`

El agente incluye memoria analítica compacta por sesión, caché TTL, métricas operativas y gráficos Plotly deterministas. Soporta inversión publicitaria, comparaciones de marcas y periodos, rankings de anunciantes y marcas, análisis por medios y vehículos, inserciones, catálogos, cobertura, series temporales y explicación de variaciones.

## Configuración

```bash
cp .env.example .env
```

Variables principales:

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

Autenticación local:

```bash
gcloud auth application-default login
gcloud config set project nexuslatam-master
```

La identidad necesita `roles/bigquery.jobUser` en el proyecto que ejecuta el job y `roles/bigquery.dataViewer` sobre el dataset, o permisos equivalentes.

## Ejecución

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

CLI:

```bash
python cli.py
```

Pruebas:

```bash
python -m pytest -q
```

## Seguridad

Solo se permite SQL `SELECT`. Las operaciones de escritura se bloquean, la tabla se compara con una allowlist y los filtros se pasan como parámetros tipados. Cada consulta realiza dry-run y respeta `BIGQUERY_MAX_BYTES_BILLED`. La evidencia incluye SQL, parámetros, filas, bytes procesados y duración.

## Esquema BICOMP

El repositorio valida cada métrica y dimensión aprobada contra el esquema real antes de consultar. Las métricas públicas son `inv_bruta`, `inv_neta`, `inv_bruta_usd`, `inv_neta_usd`, `total_insercion` y `total_duracion`. Las columnas adicionales de la tabla no se exponen automáticamente.
