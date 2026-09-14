import os
import base64
import io

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

from pypdf import PdfReader
from PIL import Image, ImageGrab

from agent import (
    AGENT_SYSTEM_PROMPT,
    build_agent_service,
)
from src.visualization import render_plotly
from src.agent.attachments import image_data_url, document_context
from src.config import get_settings

st.set_page_config(
    page_title="WPP Media Intelligence",
    page_icon="assets/wpp-media-brand.png",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@600;700;800&display=swap');

        :root {
            --ink: #111820;
            --muted: #586670;
            --line: #DDE9E8;
            --surface: #FFFFFF;
            --canvas: #F4FAF9;
            --primary: #00CDB8;
            --primary-dark: #006F75;
            --primary-soft: #E3FBF7;
            --wpp-blue: #6278F4;
            --wpp-cyan: #00D8D0;
            --wpp-lime: #72F000;
            --mint: #00B99E;
            --text-color: #111820;
            --primary-color: #00CDB8;
            color-scheme: light;
        }

        html, body, [class*="css"] {
            font-family: 'DM Sans', sans-serif;
        }

        html, body {
            background: var(--canvas) !important;
            color: var(--ink) !important;
        }

        [data-testid="stHeader"] {
            background: var(--canvas) !important;
            color: var(--ink) !important;
        }

        .stApp {
            background:
                radial-gradient(circle at 78% -10%, rgba(0, 216, 208, .15), transparent 30rem),
                radial-gradient(circle at 48% 18%, rgba(114, 240, 0, .06), transparent 24rem),
                var(--canvas);
            color: var(--ink);
        }

        [data-testid="stMain"],
        [data-testid="stMainBlockContainer"],
        [data-testid="stBottomBlockContainer"] {
            background-color: transparent !important;
            color: var(--ink) !important;
        }

        [data-testid="stBottom"] {
            background: linear-gradient(
                180deg,
                rgba(244,250,249,0) 0%,
                rgba(244,250,249,.96) 30%,
                var(--canvas) 100%
            ) !important;
        }

        [data-testid="stBottom"] > div {
            background-color: transparent !important;
            color: var(--ink) !important;
        }

        [data-testid="stMain"] p,
        [data-testid="stMain"] li,
        [data-testid="stMain"] span:not(.status-pill):not(.dot),
        [data-testid="stMain"] label,
        [data-testid="stMain"] td,
        [data-testid="stMain"] th,
        [data-testid="stMain"] h1,
        [data-testid="stMain"] h2,
        [data-testid="stMain"] h3,
        [data-testid="stMain"] h4,
        [data-testid="stMain"] strong {
            color: var(--ink);
        }

        [data-testid="stMain"] a {
            color: var(--primary-dark);
        }

        .block-container {
            max-width: 1180px;
            padding-top: 2.2rem;
            padding-bottom: 7rem;
        }

        @media print {
            section[data-testid="stSidebar"],
            [data-testid="stHeader"],
            [data-testid="stBottom"] {
                display: none !important;
            }

            [data-testid="stAppViewContainer"],
            [data-testid="stMain"],
            [data-testid="stMainBlockContainer"],
            .block-container {
                width: 100% !important;
                max-width: 100% !important;
                margin: 0 !important;
                padding-left: 0.2in !important;
                padding-right: 0.2in !important;
                overflow: visible !important;
            }

            [data-testid="stPlotlyChart"] {
                width: 100% !important;
                max-width: 100% !important;
                break-inside: avoid;
            }
        }

        h1, h2, h3 {
            font-family: 'Manrope', sans-serif !important;
            letter-spacing: -0.035em;
        }

        section[data-testid="stSidebar"] {
            background:
                radial-gradient(circle at 15% 0%, rgba(98,120,244,.24), transparent 16rem),
                #101820;
            border-right: 0;
        }

        section[data-testid="stSidebar"] * {
            color: #F4FFFD;
        }

        section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
        section[data-testid="stSidebar"] .stCaption {
            color: #AFC3C2 !important;
        }

        section[data-testid="stSidebar"] hr {
            border-color: rgba(255,255,255,.1);
        }

        .brand-lockup {
            padding: .55rem 0 1.15rem;
        }

        section[data-testid="stSidebar"] [data-testid="stImage"] img {
            border-radius: 15px;
            border: 1px solid rgba(255,255,255,.12);
            box-shadow: 0 12px 30px rgba(0,0,0,.22);
            margin: .35rem 0 .55rem;
        }

        .brand-mark {
            display: inline-flex;
            width: 42px;
            height: 42px;
            align-items: center;
            justify-content: center;
            border-radius: 13px;
            background: linear-gradient(135deg, var(--wpp-blue), var(--wpp-cyan) 68%, var(--wpp-lime));
            box-shadow: 0 10px 28px rgba(0,205,184,.28);
            font-size: 1.15rem;
            margin-bottom: .85rem;
        }

        .brand-name {
            font: 700 1.1rem 'Manrope', sans-serif;
            letter-spacing: -.02em;
        }

        .brand-subtitle {
            color: #AFC3C2;
            font-size: .78rem;
            margin-top: .25rem;
        }

        .hero {
            position: relative;
            overflow: hidden;
            padding: 1.2rem 1.65rem;
            border: 1px solid rgba(0,205,184,.2);
            border-radius: 26px;
            background:
                radial-gradient(circle at 72% 15%, rgba(114,240,0,.72), transparent 18%),
                radial-gradient(circle at 58% 75%, rgba(0,216,208,.85), transparent 28%),
                linear-gradient(120deg, #374FCE 0%, #647DF5 38%, #57D9D0 100%);
            box-shadow: 0 24px 70px rgba(30,105,126,.18);
            color: white;
            margin-bottom: .75rem;
        }

        .hero:after {
            content: '';
            position: absolute;
            width: 220px;
            height: 220px;
            right: -55px;
            top: -115px;
            border: 38px solid rgba(255,255,255,.08);
            border-radius: 50%;
        }

        .eyebrow {
            display: inline-flex;
            align-items: center;
            gap: .45rem;
            padding: .28rem .58rem;
            border: 1px solid rgba(255,255,255,.18);
            border-radius: 999px;
            background: rgba(255,255,255,.09);
            color: #F4FFFD;
            font-size: .72rem;
            font-weight: 700;
            letter-spacing: .08em;
            text-transform: uppercase;
        }

        .hero h1 {
            max-width: 720px;
            margin: .62rem 0 .25rem;
            color: white;
            font-size: clamp(1.55rem, 3vw, 2.3rem);
            line-height: 1.04;
        }

        .hero p {
            max-width: 690px;
            margin: 0;
            color: #F2FFFD;
            font-size: .9rem;
            line-height: 1.45;
        }

        .workspace-status {
            display: flex;
            align-items: center;
            min-height: 44px;
            gap: .4rem;
            padding: 0 .2rem;
            color: var(--muted);
            font-size: .8rem;
        }

        .workspace-status strong {
            color: var(--ink) !important;
        }

        .workspace-dot {
            width: 9px;
            height: 9px;
            border-radius: 50%;
            background: var(--primary);
            box-shadow: 0 0 0 5px rgba(0,205,184,.13);
            animation: workspace-pulse 2s ease-in-out infinite;
        }

        @keyframes workspace-pulse {
            0%, 100% { box-shadow: 0 0 0 4px rgba(0,205,184,.11); }
            50% { box-shadow: 0 0 0 7px rgba(0,205,184,.02); }
        }

        .status-row {
            display: flex;
            flex-wrap: wrap;
            gap: .55rem;
            margin-top: 1.45rem;
        }

        .status-pill {
            padding: .38rem .68rem;
            border-radius: 999px;
            background: rgba(255,255,255,.1);
            color: #F4FFFD;
            font-size: .76rem;
            font-weight: 600;
        }

        .status-pill .dot {
            display: inline-block;
            width: 7px;
            height: 7px;
            margin-right: .35rem;
            border-radius: 50%;
            background: var(--wpp-lime);
            box-shadow: 0 0 0 4px rgba(114,240,0,.15);
        }

        .section-label {
            margin: 1.45rem 0 .7rem;
            color: var(--muted);
            font-size: .74rem;
            font-weight: 700;
            letter-spacing: .09em;
            text-transform: uppercase;
        }

        .capability-card {
            min-height: 142px;
            padding: 1.25rem;
            border: 1px solid var(--line);
            border-radius: 18px;
            background: rgba(255,255,255,.82);
            box-shadow: 0 8px 30px rgba(13,83,83,.055);
        }

        .capability-icon {
            font-size: 1.2rem;
            margin-bottom: .7rem;
        }

        .capability-title {
            color: var(--ink);
            font: 700 .95rem 'Manrope', sans-serif;
            margin-bottom: .35rem;
        }

        .capability-text {
            color: var(--muted);
            font-size: .82rem;
            line-height: 1.55;
        }

        div[data-testid="stButton"] > button {
            min-height: 46px;
            border: 1px solid var(--line);
            border-radius: 999px;
            background: rgba(255,255,255,.9);
            color: var(--ink);
            font-weight: 600;
            box-shadow: 0 5px 18px rgba(30,22,66,.04);
            transition: all .18s ease;
        }

        div[data-testid="stButton"] > button p,
        div[data-testid="stButton"] > button span {
            color: var(--ink) !important;
        }

        div[data-testid="stButton"] > button:hover {
            border-color: var(--primary);
            background: var(--primary-soft);
            color: var(--primary-dark);
            transform: translateY(-1px);
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button {
            border-color: rgba(255,255,255,.13);
            background: rgba(255,255,255,.07);
            color: white;
            box-shadow: none;
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {
            border-color: rgba(255,255,255,.25);
            background: rgba(255,255,255,.12);
        }

        section[data-testid="stSidebar"] div[data-testid="stButton"] > button p,
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button span {
            color: white !important;
        }

        [data-testid="stChatMessage"] {
            padding: 1.1rem 1.2rem;
            margin: .7rem 0;
            border: 1px solid var(--line);
            border-radius: 18px;
            background: rgba(255,255,255,.88);
            box-shadow: 0 8px 26px rgba(13,83,83,.05);
            color: var(--ink) !important;
        }

        [data-testid="stChatMessage"] p,
        [data-testid="stChatMessage"] li,
        [data-testid="stChatMessage"] td,
        [data-testid="stChatMessage"] th,
        [data-testid="stChatMessage"] strong {
            color: var(--ink) !important;
        }

        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
            background: var(--primary-soft);
            border-color: #BEEDE7;
        }

        [data-testid="stChatInput"] {
            border: 2px solid #8DDDD4;
            border-radius: 19px;
            background: white;
            box-shadow: 0 16px 50px rgba(13,83,83,.18);
        }

        [data-testid="stChatInput"] > div,
        [data-testid="stChatInput"] [data-baseweb="textarea"],
        [data-testid="stChatInput"] [data-baseweb="base-input"] {
            background: #FFFFFF !important;
            color: var(--ink) !important;
        }

        [data-testid="stChatInput"] textarea {
            background: #FFFFFF !important;
            color: var(--ink) !important;
            -webkit-text-fill-color: var(--ink) !important;
            caret-color: var(--primary-dark) !important;
            opacity: 1 !important;
        }

        [data-testid="stChatInput"] textarea::placeholder {
            color: #66747D !important;
            -webkit-text-fill-color: #66747D !important;
            opacity: 1;
        }

        [data-testid="stChatInput"] button {
            background: linear-gradient(135deg, var(--wpp-blue), var(--wpp-cyan)) !important;
            color: white !important;
        }

        [data-testid="stChatInput"] svg {
            fill: white !important;
            color: white !important;
        }

        [data-testid="stExpander"] {
            border: 1px solid var(--line);
            border-radius: 13px;
            background: #FAF9FC;
        }

        [data-testid="stExpander"] summary p,
        [data-testid="stExpander"] [data-testid="stMarkdownContainer"] {
            color: var(--ink) !important;
        }

        [data-baseweb="popover"] > div,
        [data-baseweb="popover"] [role="dialog"] {
            background: #FFFFFF !important;
            color: var(--ink) !important;
        }

        [data-baseweb="popover"] p,
        [data-baseweb="popover"] label,
        [data-baseweb="popover"] span {
            color: var(--ink) !important;
        }

        [data-baseweb="popover"] [data-baseweb="select"] > div {
            background: #F4F8F8 !important;
            color: var(--ink) !important;
        }

        section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
            background: #16232C !important;
            border: 1px dashed #4E686D !important;
        }

        section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] p,
        section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] small,
        section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] span {
            color: #EAF7F5 !important;
            -webkit-text-fill-color: #EAF7F5 !important;
        }

        section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
            background: #24343E !important;
            border-color: #607980 !important;
        }

        section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button p,
        section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button span {
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }

        [data-testid="stDataFrame"],
        [data-testid="stTable"] {
            color: var(--ink) !important;
        }

        section[data-testid="stSidebar"] [data-baseweb="slider"] [role="slider"] {
            background-color: var(--wpp-cyan) !important;
            border-color: var(--wpp-cyan) !important;
        }

        section[data-testid="stSidebar"] [data-baseweb="checkbox"] > div:first-child {
            background-color: var(--wpp-cyan) !important;
            border-color: var(--wpp-cyan) !important;
        }

        .privacy-note {
            margin-top: .8rem;
            text-align: center;
            color: #8A8698;
            font-size: .72rem;
        }

        .privacy-note .ready-dot {
            display: inline-block;
            width: 7px;
            height: 7px;
            margin-right: .35rem;
            border-radius: 50%;
            background: var(--primary);
        }

        [data-testid="stPopover"] button {
            border-radius: 12px !important;
        }

        [data-baseweb="popover"] [data-baseweb="slider"] [role="slider"] {
            background-color: var(--wpp-cyan) !important;
            border-color: var(--wpp-cyan) !important;
        }

        @media (max-width: 760px) {
            .block-container { padding-top: 1rem; }
            .hero { padding: 1.6rem 1.35rem; border-radius: 20px; }
            .hero h1 { font-size: 2rem; }
        }
    </style>
""", unsafe_allow_html=True)

load_dotenv()

settings = get_settings()
configured_model = settings.openrouter_model
configured_models = [item.strip() for item in os.getenv("NVIDIA_MODELS", "").split(",") if item.strip()]
available_models = list(dict.fromkeys([configured_model, *configured_models]))
model_labels = {}
if not settings.openrouter_api_key:
    st.error("No se encontró la API key del proveedor configurado.")
    st.stop()
client = OpenAI(base_url=settings.llm_base_url, api_key=settings.openrouter_api_key,
                timeout=settings.llm_timeout_seconds, max_retries=0)

# =========================================================
# SYSTEM PROMPT
# =========================================================
#
# Se reutiliza el prompt de agent.py (reglas de negocio,
# mean vs sum, interpretación de fechas, etc.) y se le
# agregan las reglas específicas de esta interfaz
# (análisis de capturas de Power BI y PDFs de contexto).

SYSTEM_PROMPT = AGENT_SYSTEM_PROMPT

# =========================================================
# FUNCIONES AUXILIARES
# =========================================================

def extraer_texto_pdf(archivo_pdf):
    try:
        pdf_reader = PdfReader(archivo_pdf)
        return "\n".join([p.extract_text() or "" for p in pdf_reader.pages])
    except Exception as e:
        st.error(f"Error al leer el PDF: {e}")
        return None


def imagen_a_base64(imagen_file):
    return image_data_url(imagen_file).split(',', 1)[1]


def obtener_imagen_portapapeles():
    try:
        img = ImageGrab.grabclipboard()
        if isinstance(img, Image.Image):
            return img
        return None
    except Exception:
        return None


def responder(mensajes, modelo, temperatura):
    """
    Llama al LLM con las herramientas BICOMP habilitadas.
    Las ejecuta contra BigQuery y devuelve la evidencia al modelo
    para producir la respuesta final.

    Devuelve (respuesta_texto, lista_de_consultas_ejecutadas)
    para que la interfaz pueda mostrar de forma transparente
    qué datos reales respaldan la respuesta.
    """

    result = st.session_state.agent_service.run(
        list(mensajes), model=modelo, temperature=temperatura,
        attachments=[st.session_state.pdf_contexto] if st.session_state.get("pdf_contexto") else []
    )
    consultas = [
        {
            "herramienta": item["tool"],
            "argumentos": item["arguments"],
            "resultado": item["result"],
            "source": item.get("source"),
            "sql": item.get("sql"),
            "query_parameters": item.get("query_parameters"),
            "rows": item.get("rows"),
            "bytes_processed": item.get("bytes_processed"),
            "duration_ms": item.get("duration_ms"),
            "metric": item.get("metric"),
            "filters": item.get("filters"),
            "row_count": item.get("row_count"),
            "queries": item.get("queries", []),
            "cache_hit": item.get("cache_hit"), "purpose": item.get("purpose"),
            "step": item.get("step"), "historical": item.get("historical", False),
        }
        for item in result.evidence
    ]
    return result.answer, consultas, result.chart_specs, result.metrics, result.plan


# =========================================================
# ESTADO
# =========================================================

if "image_upload_generation" not in st.session_state:
    st.session_state.image_upload_generation = 0
if "clipboard_images" not in st.session_state:
    st.session_state.clipboard_images = []
if "upload_generation" not in st.session_state:
    st.session_state.upload_generation = 0
if "pdf_contexto" not in st.session_state:
    st.session_state.pdf_contexto = None
if "pdf_hash" not in st.session_state:
    st.session_state.pdf_hash = None

if "mensajes" not in st.session_state:
    st.session_state.mensajes = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
if "imagenes_cargadas" not in st.session_state:
    st.session_state.imagenes_cargadas = []
if "consultas_por_turno" not in st.session_state:
    # Guarda, por índice de mensaje del asistente, qué consultas
    # reales respaldaron esa respuesta (para el panel de transparencia)
    st.session_state.consultas_por_turno = {}
if "pdf_contexto_nombre" not in st.session_state:
    st.session_state.pdf_contexto_nombre = None
if "graficas_por_turno" not in st.session_state:
    st.session_state.graficas_por_turno = {}
if "metricas_agente" not in st.session_state:
    st.session_state.metricas_agente = {}
if "planes_por_turno" not in st.session_state:
    st.session_state.planes_por_turno = {}
if "agent_service" not in st.session_state:
    st.session_state.agent_service = build_agent_service(client)

# =========================================================
# SIDEBAR
# =========================================================

with st.sidebar:
    st.image(
        "assets/wpp-media-brand.png",
        width="stretch"
    )
    st.markdown(
        '<div class="brand-subtitle">Media Intelligence · Inversión publicitaria</div>',
        unsafe_allow_html=True
    )

    if st.button("Nueva conversación", icon="🔄", use_container_width=True, type="primary"):
        st.session_state.mensajes = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        st.session_state.imagenes_cargadas = []
        st.session_state.clipboard_images = []
        st.session_state.consultas_por_turno = {}
        st.session_state.graficas_por_turno = {}
        st.session_state.metricas_agente = {}
        st.session_state.planes_por_turno = {}
        st.session_state.agent_service = build_agent_service(client)
        st.session_state.pdf_contexto_nombre = None
        st.session_state.pdf_contexto = None
        st.session_state.pdf_hash = None
        st.session_state.upload_generation += 1
        st.rerun()

    st.divider()
    st.caption("FUENTES DE CONTEXTO")
    st.subheader("Archivos de análisis")
    st.caption("Añade capturas o documentos para complementar tus preguntas.")

    archivos_imagen = st.file_uploader(
        "Capturas de Power BI",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key=f"images-{st.session_state.upload_generation}-{st.session_state.image_upload_generation}"
    )

    st.session_state.imagenes_cargadas = list(archivos_imagen or []) + st.session_state.clipboard_images
    if archivos_imagen:
        st.success(f"{len(archivos_imagen)} gráfica(s) conectada(s)", icon="✅")

    # A remote Streamlit server cannot read the user's browser clipboard.
    if os.getenv("ENABLE_LOCAL_CLIPBOARD") == "1":
        st.caption("Portapapeles del equipo que ejecuta la aplicación (modo local).")
        if st.button("Pegar captura local", icon="📋", use_container_width=True):
            img_clip = obtener_imagen_portapapeles()
            if img_clip:
                st.session_state.clipboard_images = [img_clip]
                st.session_state.imagenes_cargadas = list(archivos_imagen or []) + [img_clip]
            else:
                st.info("No hay una imagen disponible en el portapapeles local.")

    if st.session_state.imagenes_cargadas:
        st.caption("ARCHIVOS ACTIVOS")
        for img_file in st.session_state.imagenes_cargadas:
            nombre_imagen = getattr(img_file, "name", "Captura pegada")
            st.markdown(f"🖼️ &nbsp; {nombre_imagen}")

        with st.expander("Ver vista previa"):
            for img_file in st.session_state.imagenes_cargadas:
                try:
                    st.image(
                        img_file,
                        caption=getattr(img_file, "name", "Captura pegada"),
                        use_container_width=True
                    )
                except TypeError:
                    st.image(img_file, use_column_width=True)

        if st.button("🗑 Quitar imágenes", use_container_width=True):
            st.session_state.imagenes_cargadas = []
            st.session_state.clipboard_images = []
            st.session_state.image_upload_generation += 1
            st.rerun()

    st.divider()
    st.subheader("Documento de contexto")
    archivo_pdf = st.file_uploader("PDF opcional", type=["pdf"], key=f"pdf-{st.session_state.upload_generation}")
    if archivo_pdf:
        import hashlib
        digest = hashlib.sha256(archivo_pdf.getvalue()).hexdigest()
        if st.session_state.pdf_hash != digest:
            texto_pdf = extraer_texto_pdf(archivo_pdf)
            st.session_state.pdf_contexto = document_context(archivo_pdf.name, archivo_pdf.getvalue(), texto_pdf) if texto_pdf else None
            st.session_state.pdf_hash = digest
        if st.session_state.pdf_contexto:
            st.success(archivo_pdf.name, icon="📄")
            if st.session_state.pdf_contexto["truncated"]:
                st.caption("Se utilizará un extracto del documento por su extensión.")
    else:
        st.session_state.pdf_contexto = None
        st.session_state.pdf_hash = None

# =========================================================
# HEADER
# =========================================================

st.markdown("""
    <div class="hero">
        <div class="eyebrow">✦ WPP Media Intelligence</div>
        <h1>Pregunta. Compara. Decide.</h1>
        <p>Tu copiloto de inversión publicitaria, conectado a datos verificables.</p>
    </div>
""", unsafe_allow_html=True)

estado_col, ajustes_col = st.columns([4, 1])

with estado_col:
    st.markdown("""
        <div class="workspace-status">
            <span class="workspace-dot"></span>
            <strong>Fuente BICOMP configurada</strong>
            <span>· BICOMP y evidencia activa</span>
        </div>
    """, unsafe_allow_html=True)

with ajustes_col:
    with st.popover("Ajustes del chat", icon="⚙️", use_container_width=True):
        modelo = st.selectbox(
            "Modelo",
            available_models,
            index=0,
            format_func=lambda model_id: model_labels.get(model_id, model_id),
            help="Modelo usado para interpretar y redactar. La disponibilidad depende del proveedor.",
        )

        temperatura = st.slider(
            "Precisión creativa",
            0.0,
            1.0,
            0.2,
            0.1
        )

        mostrar_consultas = st.checkbox(
            "Mostrar trazabilidad",
            value=False,
            help="Muestra los filtros y resultados reales usados en cada respuesta."
        )
        modo_debug = st.checkbox("Modo debug", value=False, help="Muestra plan interno validado y métricas operativas.")

pregunta_sugerida = None
hay_conversacion = any(
    mensaje.get("role") in ("user", "assistant")
    for mensaje in st.session_state.mensajes
    if isinstance(mensaje, dict)
)

if not hay_conversacion:
    st.markdown('<div class="section-label">Empieza con una pregunta</div>', unsafe_allow_html=True)

    sugerencia_1, sugerencia_2 = st.columns(2)

    with sugerencia_1:
        if st.button(
            "Top 10 anunciantes por inversión neta",
            icon="🏆",
            use_container_width=True
        ):
            pregunta_sugerida = "Top 10 anunciantes por inversión neta"

        if st.button(
            "¿Cuánto invirtió Volvo este año?",
            icon="🕘",
            use_container_width=True
        ):
            pregunta_sugerida = "¿Cuánto invirtió Volvo este año?"

    with sugerencia_2:
        if st.button(
            "Compara Volvo con Renault",
            icon="📊",
            use_container_width=True
        ):
            pregunta_sugerida = "Compara Volvo con Renault"

        if st.button(
            "¿Cómo evolucionó la inversión de Volvo?",
            icon="📈",
            use_container_width=True
        ):
            pregunta_sugerida = "¿Cómo evolucionó la inversión de Volvo?"

# =========================================================
# HISTORIAL
# =========================================================

if hay_conversacion:
    st.markdown('<div class="section-label">Conversación</div>', unsafe_allow_html=True)

for indice, mensaje in enumerate(st.session_state.mensajes):

    if mensaje["role"] == "system":
        continue

    avatar = "🧑" if mensaje["role"] == "user" else "🤖"

    with st.chat_message(mensaje["role"], avatar=avatar):

        if isinstance(mensaje["content"], list):
            for part in mensaje["content"]:
                if part["type"] == "text":
                    st.markdown(part["text"])
                elif part["type"] == "image_url":
                    st.image(part["image_url"]["url"], width=300)
        else:
            st.markdown(mensaje["content"])

        if mensaje["role"] == "assistant":
            for chart_index, chart_spec in enumerate(st.session_state.graficas_por_turno.get(indice, [])):
                st.plotly_chart(render_plotly(chart_spec), use_container_width=True, key=f"chart-{indice}-{chart_index}")

        # Panel de transparencia: qué consultas reales respaldan
        # esta respuesta puntual del asistente.
        if mensaje["role"] == "assistant" and mostrar_consultas:

            consultas = st.session_state.consultas_por_turno.get(indice)

            if consultas:
                with st.expander("🔍 Ver evidencia del análisis"):
                    for c in consultas:
                        st.markdown(f"**Herramienta:** `{c['herramienta']}`")
                        st.caption(f"Dominio: {c['resultado'].get('domain', c.get('source'))} · Métrica: {c.get('metric') or 'n/a'} · Filas: {c.get('row_count')}")
                        st.markdown("**Argumentos**")
                        st.json(c["argumentos"])
                        st.caption(f"Consulta: {c.get('step')} · Caché: {bool(c.get('cache_hit'))} · {c.get('purpose') or ''}")
                        if c.get("bytes_processed") is not None:
                            st.caption(f"Bytes: {c['bytes_processed']:,} · Duración: {c.get('duration_ms')} ms")
                        if c.get("sql"):
                            with st.expander("Ver SQL y parámetros"):
                                st.code(c["sql"], language="sql")
                                st.json(c.get("query_parameters") or {})
                        elif c.get("queries"):
                            with st.expander("Ver SQL y parámetros"):
                                for query_index, query in enumerate(c["queries"], start=1):
                                    st.caption(f"Consulta {query_index} · {query.get('bytes_processed', 0):,} bytes · {query.get('duration_ms')} ms")
                                    st.code(query.get("sql", ""), language="sql")
                                    st.json(query.get("query_parameters") or {})
                        st.markdown("**Resultado:**")
                        st.json(c["resultado"])
                if modo_debug:
                    with st.expander("🛠 Debug del agente"):
                        st.json({"plan": st.session_state.planes_por_turno.get(indice), "metrics": st.session_state.metricas_agente})

# =========================================================
# INPUT
# =========================================================

pregunta_escrita = st.chat_input(
    "Pregunta por inversión, marcas, anunciantes, medios o periodos…"
)

pregunta = pregunta_sugerida or pregunta_escrita

st.markdown(
    '<div class="privacy-note"><span class="ready-dot"></span>'
    'Listo · Conexión verificada al consultar · Trazabilidad disponible</div>',
    unsafe_allow_html=True
)

if pregunta:

    if st.session_state.imagenes_cargadas:
        contenido_usuario = [{"type": "text", "text": pregunta}]
        for img_file in st.session_state.imagenes_cargadas:
            b64 = imagen_a_base64(img_file)
            contenido_usuario.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"}
            })
        mensaje_usuario = {"role": "user", "content": contenido_usuario}
        with st.chat_message("user", avatar="🧑"):
            st.markdown(pregunta)
            for img_file in st.session_state.imagenes_cargadas:
                try:
                    st.image(img_file, width=300)
                except Exception:
                    pass
    else:
        mensaje_usuario = {"role": "user", "content": pregunta}
        with st.chat_message("user", avatar="🧑"):
            st.markdown(pregunta)

    st.session_state.mensajes.append(mensaje_usuario)

    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner("Consultando datos y pensando... ⚡"):
            try:
                respuesta, consultas, graficas, metricas, plan = responder(
                    st.session_state.mensajes,
                    modelo,
                    temperatura
                )

                st.markdown(respuesta)

                for chart_index, chart_spec in enumerate(graficas):
                    st.plotly_chart(render_plotly(chart_spec), use_container_width=True, key=f"chart-{len(st.session_state.mensajes)}-{chart_index}")

                if consultas and mostrar_consultas:
                    with st.expander("🔍 Ver evidencia del análisis"):
                        for c in consultas:
                            st.markdown(f"**Herramienta:** `{c['herramienta']}`")
                            st.caption(f"Dominio: {c['resultado'].get('domain', c.get('source'))} · Métrica: {c.get('metric') or 'n/a'} · Filas: {c.get('row_count')}")
                            st.json(c["argumentos"])
                            st.caption(f"Consulta: {c.get('step')} · Caché: {bool(c.get('cache_hit'))} · {c.get('purpose') or ''}")
                            if c.get("bytes_processed") is not None:
                                st.caption(f"Bytes: {c['bytes_processed']:,} · Duración: {c.get('duration_ms')} ms")
                            if c.get("sql"):
                                with st.expander("Ver SQL y parámetros"):
                                    st.code(c["sql"], language="sql")
                                    st.json(c.get("query_parameters") or {})
                            elif c.get("queries"):
                                with st.expander("Ver SQL y parámetros"):
                                    for query_index, query in enumerate(c["queries"], start=1):
                                        st.caption(f"Consulta {query_index} · {query.get('bytes_processed', 0):,} bytes · {query.get('duration_ms')} ms")
                                        st.code(query.get("sql", ""), language="sql")
                                        st.json(query.get("query_parameters") or {})
                            st.markdown("**Resultado:**")
                            st.json(c["resultado"])

                st.session_state.mensajes.append(
                    {"role": "assistant", "content": respuesta}
                )

                if consultas or graficas or plan:
                    indice_nuevo_mensaje = len(st.session_state.mensajes) - 1
                    st.session_state.consultas_por_turno[indice_nuevo_mensaje] = consultas
                    st.session_state.graficas_por_turno[indice_nuevo_mensaje] = graficas
                    st.session_state.planes_por_turno[indice_nuevo_mensaje] = plan
                st.session_state.metricas_agente = metricas

            except Exception as e:
                st.error(f"❌ Error: {e}")
