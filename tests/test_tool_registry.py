from __future__ import annotations

from ai.tool_registry import (
    execute_tool,
    get_tool_declarations,
    get_tool_executor,
    list_registered_tools,
)


def test_calculator_returns_exact_arithmetic_result() -> None:
    result = execute_tool("calculate", {"expression": "(1250 * 4) - 500"})
    assert result["ok"] is True
    assert result["result"] == 4500


def test_calculator_supports_safe_math_functions() -> None:
    result = execute_tool("calculate", {"expression": "round(sqrt(81) + pi, 2)"})
    assert result["ok"] is True
    assert result["result"] == 12.14


def test_calculator_rejects_python_execution() -> None:
    result = execute_tool(
        "calculate",
        {"expression": '__import__("os").getcwd()'},
    )
    assert result["ok"] is False


def test_unknown_tool_is_rejected() -> None:
    result = execute_tool("run_shell", {"command": "whoami"})
    assert result["ok"] is False
    assert result["error"] == "unknown_tool"


def test_tool_declarations_have_trusted_handlers() -> None:
    declared = {tool["name"] for tool in get_tool_declarations()}
    handlers = set(get_tool_executor())
    listed = {tool["name"] for tool in list_registered_tools()}
    assert declared == handlers == listed
    assert declared == {"calculate", "search_web", "get_current_datetime"}


def test_datetime_tool_returns_nairobi_and_utc() -> None:
    result = execute_tool("get_current_datetime")
    assert result["ok"] is True
    assert result["timezone"] == "Africa/Nairobi"
    assert result["local_datetime"].endswith("+03:00")
    assert result["utc_datetime"].endswith("+00:00")
