import pytest
from pydantic import ValidationError

from agent.config import Settings, is_configured_secret


VALID_ENV = {
    "DEEPGRAM_API_KEY": "dg_live_123",
    "OPENAI_API_KEY": "sk-live-123",
    "CARTESIA_API_KEY": "cartesia-live-123",
}


def test_is_configured_secret_rejects_empty_and_placeholder_values():
    assert not is_configured_secret("")
    assert not is_configured_secret("your_openai_key")
    assert not is_configured_secret("replace_me")
    assert is_configured_secret("sk-live-123")


def test_settings_reject_copied_env_example_placeholders(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "your_deepgram_key")
    monkeypatch.setenv("OPENAI_API_KEY", VALID_ENV["OPENAI_API_KEY"])
    monkeypatch.setenv("CARTESIA_API_KEY", VALID_ENV["CARTESIA_API_KEY"])

    with pytest.raises(ValidationError):
        Settings()


def test_settings_accept_realistic_required_keys(monkeypatch):
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)

    settings = Settings()

    assert settings.deepgram_api_key == VALID_ENV["DEEPGRAM_API_KEY"]
    assert settings.openai_api_key == VALID_ENV["OPENAI_API_KEY"]
    assert settings.cartesia_api_key == VALID_ENV["CARTESIA_API_KEY"]
