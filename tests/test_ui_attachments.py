import base64
import io
from types import SimpleNamespace as NS
from unittest.mock import Mock
from PIL import Image
from streamlit.testing.v1 import AppTest
from src.agent.attachments import document_context, image_data_url
from src.agent.observability import ConversationMetrics


def test_image_bytes_match_declared_png_and_size_bound():
    buffer = io.BytesIO()
    Image.new('RGB', (3000, 1000), 'blue').save(buffer, format='JPEG')
    url = image_data_url(buffer)
    assert url.startswith('data:image/png;base64,')
    converted = Image.open(io.BytesIO(base64.b64decode(url.split(',', 1)[1])))
    assert converted.format == 'PNG' and converted.size == (2048, 683)


def test_document_identity_is_content_based_and_truncation_explicit():
    a = document_context('same.pdf', b'first', 'x'*50, max_chars=20)
    b = document_context('same.pdf', b'second', 'second')
    assert a['sha256'] != b['sha256'] and a['truncated'] and len(a['text']) == 20
    assert a['untrusted_document'] and not b['truncated']


def test_repeated_charts_across_turns_and_new_conversation(monkeypatch):
    import agent
    spec = {'type': 'ranking', 'title': 'Ejemplo', 'data': [{'dimension': 'A', 'value': 100}], 'x': 'value', 'y': 'dimension'}
    result = NS(answer='Resultado verificado.', evidence=[], chart_specs=[spec], metrics=ConversationMetrics().as_dict(), plan={})
    fake = NS(run=Mock(return_value=result))
    builder = Mock(return_value=fake)
    monkeypatch.setattr(agent, 'build_agent_service', builder)
    monkeypatch.setenv('NVIDIA_API_KEY', 'test-ui-key')
    at = AppTest.from_file(str(__import__('pathlib').Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=15).run()
    assert not at.exception
    at.chat_input[0].set_value('Pregunta uno.').run()
    at.chat_input[0].set_value('Pregunta dos.').run()
    at.run()
    assert not at.exception and not at.error
    assert len(at.get('plotly_chart')) == 2
    at.session_state['pdf_contexto'] = {'name': 'document.pdf'}
    at.session_state['clipboard_images'] = [Image.new('RGB', (2, 2))]
    generation = at.session_state['upload_generation']
    next(b for b in at.button if b.label == 'Nueva conversación').click().run()
    assert not at.exception
    assert at.session_state['pdf_contexto'] is None
    assert at.session_state['clipboard_images'] == []
    assert at.session_state['upload_generation'] == generation + 1
    assert at.session_state['graficas_por_turno'] == {}
