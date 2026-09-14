from src.config import Settings


def test_llm_max_tokens_default_and_environment_override(monkeypatch):
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    assert Settings.from_env(env_file="/dev/null").llm_max_tokens == 800
    monkeypatch.setenv("LLM_MAX_TOKENS", "600")
    assert Settings.from_env(env_file="/dev/null").llm_max_tokens == 600


def test_openrouter_key_uses_matching_default_endpoint(monkeypatch):
    monkeypatch.delenv('NVIDIA_API_KEY', raising=False)
    monkeypatch.delenv('LLM_BASE_URL', raising=False)
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test')
    assert Settings.from_env('/dev/null').llm_base_url == 'https://openrouter.ai/api/v1'


def test_invalid_budgets_rejected():
    import pytest
    for kwargs in ({'max_agent_steps': 0}, {'llm_plan_max_tokens': -1}, {'response_validation_retries': 2}):
        with pytest.raises(ValueError): Settings(**kwargs)


def test_client_data_controls_are_safe_by_default_and_configurable(monkeypatch):
    for name in ('BICOMP_CURRENCY_CODE', 'BICOMP_CURRENCY_SCALE', 'ENABLE_TECHNICAL_TRACE', 'ENABLE_DEBUG_UI'):
        monkeypatch.delenv(name, raising=False)
    defaults = Settings.from_env('/dev/null')
    assert defaults.bicomp_currency_code is None and defaults.bicomp_currency_scale is None
    assert not defaults.enable_technical_trace and not defaults.enable_debug_ui
    monkeypatch.setenv('BICOMP_CURRENCY_CODE', 'cop')
    monkeypatch.setenv('BICOMP_CURRENCY_SCALE', 'thousand')
    monkeypatch.setenv('ENABLE_TECHNICAL_TRACE', 'true')
    configured = Settings.from_env('/dev/null')
    assert configured.bicomp_currency_code == 'COP'
    assert configured.bicomp_currency_scale == 'thousand'
    assert configured.enable_technical_trace
