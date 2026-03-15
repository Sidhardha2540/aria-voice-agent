"""
Shared test fixtures.
"""
import pytest

from agent.database.manager import DatabaseManager


@pytest.fixture
def db_manager():
    """Fresh DatabaseManager for tests. Call startup() before use if testing DB."""
    return DatabaseManager()
