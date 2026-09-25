from types import SimpleNamespace

from fastapi.testclient import TestClient

import api


client = TestClient(api.app)


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_build_context_prompt_omits_empty_values():
    context = api.PowerBIContext(
        marca=" AUDI ", pais="COLOMBIA", anio="2025", medio="", inversion=None
    )

    assert api.build_context_prompt(context) == (
        "El usuario está analizando:\n"
        "Marca: AUDI\n"
        "País: COLOMBIA\n"
        "Año: 2025"
    )


def test_chat_maps_agent_result_and_adds_context(monkeypatch):
    captured = {}

    class FakeService:
        def run(self, messages):
            captured["messages"] = messages
            return SimpleNamespace(answer="Respuesta verificada", is_partial=False)

    monkeypatch.setattr(api, "build_agent_service", lambda: FakeService())

    response = client.post(
        "/api/v1/chat",
        json={
            "pregunta": "¿Cuál fue la inversión de Audi?",
            "contexto": {
                "marca": "AUDI",
                "pais": "COLOMBIA",
                "anio": "2025",
                "medio": "DIGITAL",
            },
        },
    )

    assert response.status_code == 200
    assert response.json() == {"respuesta": "Respuesta verificada", "parcial": False}
    assert captured["messages"] == [
        {
            "role": "user",
            "content": (
                "¿Cuál fue la inversión de Audi?\n\n"
                "El usuario está analizando:\n"
                "Marca: AUDI\n"
                "País: COLOMBIA\n"
                "Año: 2025\n"
                "Medio: DIGITAL"
            ),
        }
    ]


def test_chat_returns_generic_service_error(monkeypatch):
    class BrokenService:
        def run(self, messages):
            raise RuntimeError("sensitive provider detail")

    monkeypatch.setattr(api, "build_agent_service", lambda: BrokenService())

    response = client.post(
        "/api/v1/chat",
        json={"pregunta": "Pregunta válida", "contexto": {}},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "El servicio del agente no está disponible temporalmente."
    }
    assert "sensitive" not in response.text
