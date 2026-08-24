"""
Shared test fixtures.
"""
import os

import pytest

# Settings are instantiated at module import time in agent.config. Provide
# deterministic non-placeholder secrets so tests do not depend on a local .env.
os.environ.setdefault("DEEPGRAM_API_KEY", "dg_test_secret")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-secret")
os.environ.setdefault("CARTESIA_API_KEY", "cartesia-test-secret")

from agent.database.manager import DatabaseManager


@pytest.fixture
def db_manager():
    """Fresh DatabaseManager for tests. Call startup() before use if testing DB."""
    return DatabaseManager()
