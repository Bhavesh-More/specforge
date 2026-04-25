"""Tool registry — built-in MCP tools for deterministic symbolic operations."""

import ast
import json
from datetime import datetime
from typing import Any

from src.core.exceptions import MCPToolError
from src.core.logging import get_logger

_log = get_logger(__name__)


class MCPTool:
    """A registered MCP tool with schema and implementation metadata."""

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        handler: callable,
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.output_schema = output_schema
        self._handler = handler


class ToolRegistry:
    """Registry of built-in MCP tools for deterministic symbolic operations."""

    def __init__(self) -> None:
        self._tools: dict[str, MCPTool] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        """Register all built-in deterministic tools."""
        self._tools["python_eval"] = MCPTool(
            name="python_eval",
            description="Safely evaluate a Python math expression (no arbitrary code).",
            input_schema={
                "type": "object",
                "required": ["expression"],
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "A Python math/arithmetic expression using +, -, *, /, **, (), int literals, float literals. No imports, no variables, no function calls.",
                    }
                },
            },
            output_schema={
                "type": "object",
                "required": ["result"],
                "properties": {
                    "result": {"type": ["number", "string"]},
                    "error": {"type": ["string", "null"]},
                },
            },
            handler=self._handle_python_eval,
        )

        self._tools["count_items"] = MCPTool(
            name="count_items",
            description="Count items in a list.",
            input_schema={
                "type": "object",
                "required": ["items"],
                "properties": {
                    "items": {"type": "array"},
                },
            },
            output_schema={
                "type": "object",
                "required": ["count"],
                "properties": {
                    "count": {"type": "integer"},
                },
            },
            handler=self._handle_count_items,
        )

        self._tools["date_diff_days"] = MCPTool(
            name="date_diff_days",
            description="Calculate the number of days between two ISO format dates.",
            input_schema={
                "type": "object",
                "required": ["date_a", "date_b"],
                "properties": {
                    "date_a": {"type": "string", "description": "ISO 8601 date string."},
                    "date_b": {"type": "string", "description": "ISO 8601 date string."},
                },
            },
            output_schema={
                "type": "object",
                "required": ["days", "direction"],
                "properties": {
                    "days": {"type": "integer"},
                    "direction": {"type": "string", "enum": ["future", "past"]},
                },
            },
            handler=self._handle_date_diff_days,
        )

        self._tools["validate_json_schema"] = MCPTool(
            name="validate_json_schema",
            description="Validate a JSON string against a JSON Schema.",
            input_schema={
                "type": "object",
                "required": ["json_string", "schema"],
                "properties": {
                    "json_string": {"type": "string"},
                    "schema": {"type": "object"},
                },
            },
            output_schema={
                "type": "object",
                "required": ["valid", "errors"],
                "properties": {
                    "valid": {"type": "boolean"},
                    "errors": {"type": "array", "items": {"type": "string"}},
                },
            },
            handler=self._handle_validate_json_schema,
        )

    # ─── Handlers ──────────────────────────────────────────────────────────────

    def _handle_python_eval(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Safely evaluate a math expression using ast.literal_eval.

        Only permits arithmetic operators, numbers, and parentheses.
        """
        expression = inputs["expression"]

        # Reject anything that isn't a safe arithmetic expression
        try:
            # Parse with ast — reject if any operators other than + - * / ** // % are found
            tree = ast.parse(expression, mode="eval")
            for node in ast.walk(tree):
                if isinstance(node, (ast.BinOp, ast.UnaryOp, ast.Compare)):
                    if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)):
                        raise MCPToolError(tool_name="python_eval", tool_input=inputs, error_message=f"Unsafe operator: {type(node.op).__name__}")
                elif isinstance(node, ast.Call):
                    raise MCPToolError(tool_name="python_eval", tool_input=inputs, error_message="Function calls not permitted")
            result = eval(expression, {"__builtins__": {}}, {})  # safe eval via ast gate above
            return {"result": result, "error": None}
        except Exception as exc:
            return {"result": None, "error": str(exc)}

    def _handle_count_items(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Count items in a list."""
        items = inputs.get("items", [])
        return {"count": len(items)}

    def _handle_date_diff_days(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Calculate days between two ISO dates."""
        date_a = datetime.fromisoformat(inputs["date_a"].replace("Z", "+00:00"))
        date_b = datetime.fromisoformat(inputs["date_b"].replace("Z", "+00:00"))
        delta = date_b - date_a
        days = abs(delta.days)
        direction = "future" if delta.days > 0 else "past"
        return {"days": days, "direction": direction}

    def _handle_validate_json_schema(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Validate a JSON string against a schema."""
        import jsonschema

        json_string = inputs["json_string"]
        schema = inputs["schema"]
        errors: list[str] = []

        try:
            parsed = json.loads(json_string)
        except json.JSONDecodeError as exc:
            return {"valid": False, "errors": [f"JSON parse error: {exc.msg}"]}

        try:
            jsonschema.validate(instance=parsed, schema=schema)
            return {"valid": True, "errors": []}
        except jsonschema.ValidationError as exc:
            return {"valid": False, "errors": [exc.message]}

    # ─── Public API ────────────────────────────────────────────────────────────

    def get_tool(self, name: str) -> MCPTool | None:
        """Return a tool by name, or None if not registered."""
        return self._tools.get(name)

    def list_tools(self) -> list[MCPTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def execute_tool(self, name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute a registered tool by name.

        Args:
            name: Tool name.
            inputs: Input dict validated against the tool's input schema.

        Returns:
            Output dict from the tool handler.

        Raises:
            MCPToolError: If the tool is not found or execution fails.
        """
        tool = self._tools.get(name)
        if tool is None:
            raise MCPToolError(
                tool_name=name,
                tool_input=inputs,
                error_message=f"Tool '{name}' not found in registry",
            )

        try:
            return tool._handler(inputs)
        except MCPToolError:
            raise
        except Exception as exc:
            _log.error("tool_execution_error", tool_name=name, error=str(exc))
            raise MCPToolError(
                tool_name=name,
                tool_input=inputs,
                error_message=str(exc),
            )
