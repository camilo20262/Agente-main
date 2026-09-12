"""Explicit, bounded attachment data; never promoted to system instructions."""
from __future__ import annotations
import base64
import hashlib
import io
from PIL import Image


def image_data_url(file) -> str:
    image = file.copy() if isinstance(file, Image.Image) else Image.open(io.BytesIO(file.getvalue()))
    image.thumbnail((2048, 2048))
    buffer = io.BytesIO()
    image.convert('RGB').save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')


def document_context(name: str, content: bytes, text: str, *, max_chars=12000):
    return {'name': name, 'sha256': hashlib.sha256(content).hexdigest(), 'text': text[:max_chars],
            'truncated': len(text) > max_chars, 'characters': len(text), 'untrusted_document': True}
