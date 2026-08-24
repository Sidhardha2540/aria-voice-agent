from agent.observability.health import (
    check_required_secret,
    overall_status,
)


def test_check_required_secret_rejects_placeholder_values():
    result = check_required_secret("openai", "your_openai_key")

    assert result["status"] == "missing_key"
    assert "OPENAI" in result["detail"]


def test_check_required_secret_accepts_realistic_values():
    assert check_required_secret("openai", "sk-live-123") == {"status": "ok"}


def test_overall_status_classifies_degraded_and_unhealthy():
    assert overall_status({"database": {"status": "ok"}}) == "healthy"
    assert overall_status({"database": {"status": "not_initialized"}}) == "degraded"
    assert (
        overall_status(
            {
                "database": {"status": "ok"},
                "openai": {"status": "missing_key"},
            }
        )
        == "unhealthy"
    )
