"""Small provider boundary with bounded calls, JSON decoding and usage metrics."""
from __future__ import annotations
import json
import re
import time
from typing import Any


class LLMGateway:
    def __init__(self, client, settings, metrics):
        self.client, self.settings, self.metrics = client, settings, metrics

    def complete(self, system: str, payload: Any, *, model=None, stage='research', json_mode=False, temperature=0.1, images=None, structured_output=False):
        limit = self.settings.llm_plan_max_tokens if json_mode else self.settings.llm_final_max_tokens
        kwargs = dict(model=model or self.settings.openrouter_model,
                      messages=[{'role': 'system', 'content': system},
                                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, default=str)}],
                      temperature=temperature, max_tokens=limit, timeout=self.settings.llm_timeout_seconds)
        if images:
            kwargs['messages'][-1]['content'] = [{'type': 'text', 'text': kwargs['messages'][-1]['content']}, *images]
        if json_mode or structured_output:
            kwargs['response_format'] = {'type': 'json_object'}
        if self.settings.llm_reasoning_effort:
            kwargs['reasoning_effort'] = self.settings.llm_reasoning_effort
        for attempt in range(2):
            start = time.perf_counter()
            self.metrics.total_llm_calls += 1
            try:
                completion = self.client.chat.completions.create(**kwargs)
                choice = completion.choices[0]
                content = choice.message.content or ''
                finish = getattr(choice, 'finish_reason', None)
                usage = getattr(completion, 'usage', None)
                self.metrics.input_tokens += int(getattr(usage, 'prompt_tokens', 0) or 0)
                self.metrics.output_tokens += int(getattr(usage, 'completion_tokens', 0) or 0)
                self.metrics.events.append({'stage': stage, 'finish_reason': finish,
                                            'latency_ms': round((time.perf_counter()-start)*1000, 2)})
                if json_mode:
                    if finish in {'length', 'max_tokens'}:
                        raise ValueError('El proveedor truncó el plan JSON.')
                    content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content.strip())
                    value = json.loads(content)
                    if not isinstance(value, dict):
                        raise ValueError('El plan debe ser un objeto JSON.')
                    return value
                return content, finish
            except Exception as exc:
                self.metrics.errors.append(f'{stage}:{type(exc).__name__}')
                # Retry only transport/server failures, not invalid plans or quota/auth.
                status = getattr(exc, 'status_code', None)
                transient = isinstance(exc, (TimeoutError, ConnectionError)) or type(exc).__name__ in {'APITimeoutError', 'APIConnectionError'} or status in {500, 502, 503, 504}
                if attempt or not transient:
                    raise
        raise RuntimeError('No se obtuvo respuesta del proveedor.')
