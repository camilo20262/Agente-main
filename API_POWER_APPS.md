# API REST para Power Apps y Power BI

La API reutiliza `build_agent_service()` y `AgentService.run()`; no reemplaza ni
modifica la aplicación Streamlit.

## Ejecución local

```bash
cd /Users/camilo/Downloads/Agente-main
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

Endpoints locales:

- Salud: `http://localhost:8000/health`
- Chat: `http://localhost:8000/api/v1/chat`
- Documentación interactiva: `http://localhost:8000/docs`
- OpenAPI generado por FastAPI: `http://localhost:8000/openapi.json`

Prueba de salud:

```bash
curl --request GET http://localhost:8000/health
```

Prueba del agente:

```bash
curl --request POST \
  --url http://localhost:8000/api/v1/chat \
  --header 'Content-Type: application/json' \
  --data '{
    "pregunta": "¿Cuál fue la inversión de Audi?",
    "contexto": {
      "marca": "AUDI",
      "pais": "COLOMBIA",
      "anio": "2025",
      "medio": "DIGITAL"
    }
  }'
```

Respuesta esperada:

```json
{
  "respuesta": "Texto generado por el agente con base en la evidencia disponible.",
  "parcial": false
}
```

`parcial=true` indica que el agente no pudo completar todas las verificaciones o
que la evidencia disponible fue insuficiente.

## Contrato para Power Automate

- URL: `https://HOST_PUBLICADO/api/v1/chat`
- Método: `POST`
- Header: `Content-Type: application/json`
- Autenticación: la definida para el despliegue; no enviar claves NVIDIA o GCP.
- Body:

```json
{
  "pregunta": "texto del usuario",
  "contexto": {
    "marca": "",
    "pais": "",
    "anio": "",
    "medio": "",
    "inversion": ""
  }
}
```

- Response:

```json
{
  "respuesta": "texto generado",
  "parcial": false
}
```

Flujo sugerido:

1. Crear un flujo instantáneo con el disparador **Power Apps (V2)**.
2. Declarar entradas de texto para pregunta, marca, país, año, medio e inversión.
3. Agregar la acción HTTP con el método, URL, header y body anteriores.
4. Agregar **Parse JSON** sobre el body de la respuesta con este esquema:

```json
{
  "type": "object",
  "properties": {
    "respuesta": {"type": "string"},
    "parcial": {"type": "boolean"}
  },
  "required": ["respuesta", "parcial"]
}
```

5. Agregar **Respond to a PowerApp or flow** y devolver ambos campos.
6. Invocar el flujo desde Power Apps y mostrar `respuesta` en el componente de chat.

Los Custom Connectors de Power Platform requieren actualmente una definición
Swagger/OpenAPI 2.0. FastAPI publica OpenAPI 3.1, por lo que `/openapi.json` sirve
para inspección y pruebas, pero no debe importarse directamente. Para un Custom
Connector, se debe definir la operación desde el asistente o convertir y revisar
una copia Swagger 2.0. La ruta Power Automate + HTTP no requiere esa conversión.

## Exposición temporal con ngrok

Con la API local ejecutándose en el puerto 8000:

```bash
ngrok config add-authtoken TU_TOKEN_NGROK
ngrok http 8000
```

Usar temporalmente la URL HTTPS mostrada por ngrok, seguida por
`/api/v1/chat`. No utilizar este túnel como despliegue productivo ni compartirlo
sin un mecanismo de autenticación.

## Despliegue en Google Cloud Run

El `Dockerfile` escucha en `0.0.0.0` y usa el puerto que Cloud Run inyecta en
`PORT`. El `.dockerignore` evita copiar `.env`, el entorno virtual y el historial
Git a la imagen.

### 1. Configurar el proyecto y APIs

```bash
gcloud auth login
gcloud config set project nexuslatam-master
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

### 2. Crear una identidad de ejecución

```bash
gcloud iam service-accounts create wpp-media-agent-api \
  --display-name='WPP Media Agent API'
```

Conceder a esa cuenta únicamente:

- `roles/bigquery.jobUser` sobre el proyecto que ejecuta las consultas.
- `roles/bigquery.dataViewer` sobre el dataset BICOMP.
- `roles/secretmanager.secretAccessor` únicamente sobre el secreto NVIDIA.

La cuenta será la identidad ADC de `google-cloud-bigquery`; no se debe copiar un
archivo JSON de credenciales a la imagen.

### 3. Guardar la clave NVIDIA en Secret Manager

Primera creación:

```bash
gcloud secrets create nvidia-api-key --replication-policy=automatic
gcloud secrets versions add nvidia-api-key --data-file=-
```

El segundo comando lee la clave desde la entrada estándar. Pegar la nueva clave,
finalizar con `Ctrl-D` y no reutilizar una clave que haya sido expuesta.

### 4. Desplegar desde el código fuente

```bash
gcloud run deploy wpp-media-agent-api \
  --source . \
  --region us-central1 \
  --service-account wpp-media-agent-api@nexuslatam-master.iam.gserviceaccount.com \
  --set-secrets NVIDIA_API_KEY=nvidia-api-key:latest \
  --set-env-vars NVIDIA_MODEL=nvidia/nemotron-3-super-120b-a12b,LLM_BASE_URL=https://integrate.api.nvidia.com/v1,GCP_PROJECT_ID=nexuslatam-master,BIGQUERY_DATASET=NEXUS_GROUPM_BI_2,BIGQUERY_BICOMP_TABLE=tb_data_bicompetitive,BIGQUERY_LOCATION=US,BIGQUERY_MAX_BYTES_BILLED=1000000000 \
  --timeout 300 \
  --no-allow-unauthenticated
```

El despliegue privado es la opción recomendada. Power Automate no podrá llamar
directamente una URL privada de Cloud Run sin un mecanismo que emita una identidad
aceptada por Google. Para producción, colocar delante una puerta de enlace/API
management compatible con la autenticación elegida en Power Platform, o añadir
autenticación de aplicación antes de permitir invocaciones públicas.

`--allow-unauthenticated` hace pública la API y no debe utilizarse con datos de
negocio mientras la aplicación no valide a sus consumidores.

## CORS y secretos

CORS está deshabilitado por defecto. Power Automate y los Custom Connectors realizan
llamadas servidor a servidor y normalmente no necesitan CORS. Para un cliente web
directo se puede configurar una lista explícita:

```env
CORS_ALLOWED_ORIGINS=https://app.contoso.com,https://otro-origen.example
```

No utilizar `*` en producción. La respuesta pública del chat contiene únicamente
`respuesta` y `parcial`; no incluye prompts, SQL, evidencia ni credenciales.

Referencias oficiales:

- [Desplegar Cloud Run desde código fuente](https://docs.cloud.google.com/run/docs/deploying-source-code)
- [Contrato de contenedores de Cloud Run](https://docs.cloud.google.com/run/docs/container-contract)
- [Secretos en Cloud Run](https://docs.cloud.google.com/run/docs/configuring/services/secrets)
- [Custom Connectors de Power Platform](https://learn.microsoft.com/en-us/connectors/custom-connectors/)
- [Inicio rápido de ngrok](https://ngrok.com/docs/start)
