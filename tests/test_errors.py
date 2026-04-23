"""Tests for error boundaries: safe_int, safe_str, safe_tool_call."""
import asyncio

from agent.core.errors import safe_int, safe_str, safe_tool_call, TOOL_ERROR_RESPONSES


def test_safe_int_valid():
    assert safe_int(2) == 2
    assert safe_int(2.0) == 2
    assert safe_int("2") == 2
    assert safe_int(" 3 ") == 3


def test_safe_int_word_numbers():
    assert safe_int("one") == 1
    assert safe_int("two") == 2
    assert safe_int("ten") == 10


def test_safe_int_invalid_returns_default():
    assert safe_int(None, 0) == 0
    assert safe_int("nope", 5) == 5
    assert safe_int("", 99) == 99


def test_safe_str():
    assert safe_str("hello") == "hello"
    assert safe_str("  trim  ") == "trim"
    assert safe_str(None, "default") == "default"
    assert safe_str(42) == "42"


def test_safe_tool_call_returns_on_success():
    async def _run():
        async def ok_handler(params):
            await params.result_callback("OK")

        class Params:
            def __init__(self):
                self.result_callback_called = None

            async def result_callback(self, msg):
                self.result_callback_called = msg

        params = Params()
        await safe_tool_call("check_availability", ok_handler, params, "test-session")
        assert params.result_callback_called == "OK"

    asyncio.run(_run())


def test_safe_tool_call_returns_spoken_error_on_failure():
    async def _run():
        async def fail_handler(params):
            raise ValueError("bad")

        class Params:
            def __init__(self):
                self.result_callback_called = None

            async def result_callback(self, msg):
                self.result_callback_called = msg

        params = Params()
        await safe_tool_call("check_availability", fail_handler, params, "test-session")
        assert params.result_callback_called == TOOL_ERROR_RESPONSES["check_availability"]

    asyncio.run(_run())
