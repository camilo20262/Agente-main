# WPP Media Intelligence Agent

Agente analítico BICOMP que interpreta preguntas con un LLM y delega todos los cálculos cuantitativos a BigQuery. La única fuente de datos es la tabla física `nexuslatam-master.NEXUS_GROUPM_BI_2.tb_data_bicompetitive`.

## Arquitectura

```
Streamlit/CLI → AgentService → AnalyticalPlanner → ToolRegistry → BigQueryRepository → respuesta + evidencia
```

El agente incluye memoria analítica compacta por sesión, caché TTL, métricas operativas y gráficos Plotly deterministas. Soporta inversión publicitaria, comparaciones de marcas y periodos, rankings de anunciantes y marcas, ranking genérico por cualquier dimensión (región, sector, holding, ciudad, agencia, etc.), análisis por medios y vehículos, inserciones, catálogos, cobertura, series temporales y explicación de variaciones.

**Robustez del agente:**
- Los argumentos de cada herramienta se validan contra su JSON Schema antes de ejecutar (tipos, campos requeridos, enums, formatos de fecha, y rechazo de propiedades no declaradas). Un argumento mal formado nunca ejecuta una consulta real.
- El planner reconoce preguntas de seguimiento que cambian solo el periodo o la dimensión (por ejemplo "¿y en marzo?" o "y para 2026" después de una consulta previa) sin perder el contexto de marca/métrica ya establecido.
- Si el agente agota los pasos permitidos o el modelo repite/inventa una herramienta, el sistema no falla con un error crudo: devuelve una respuesta parcial con la evidencia real obtenida hasta ese punto (marcada explícitamente como incompleta), recuperando incluso evidencia de una pregunta anterior en la misma sesión cuando aplica, siempre identificada como histórica.
- La memoria de la conversación solo se actualiza con resultados confirmados como exitosos, nunca con intentos fallidos.

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
