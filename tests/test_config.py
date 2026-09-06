from src.config import Settings


def test_llm_max_tokens_default_and_environment_override(monkeypatch):
    monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
    assert Settings.from_env(env_file="/dev/null").llm_max_tokens == 800
    monkeypatch.setenv("LLM_MAX_TOKENS", "600")
    assert Settings.from_env(env_file="/dev/null").llm_max_tokens == 600
