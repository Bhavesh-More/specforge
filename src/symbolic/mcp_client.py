"""MCP client — validates and dispatches tool calls via the tool registry."""

from typing import Any

import jsonschema

from src.core.exceptions import MCPToolError
from src.core.logging import get_logger
from src.symbolic.tool_registry import ToolRegistry

_log = get_logger(__name__)


class MCPClient:
    """Validates and dispatches MCP tool calls.

    Attributes:
        registry: The ToolRegistry holding registered tool definitions.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    async def call_tool(self, tool_name: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """Validate inputs, execute a tool, and validate the output.

        Args:
            tool_name: Name of the registered tool to call.
            inputs: Input dict to pass to the tool.

        Returns:
            Output dict from the tool execution.

        Raises:
            MCPToolError: If input validation fails, tool is not found,
                          or output validation fails.
        """
        tool = self._registry.get_tool(tool_name)
        if tool is None:
            raise MCPToolError(
                tool_name=tool_name,
                tool_input=inputs,
                error_message=f"Tool '{tool_name}' not found",
            )

        # Validate input against input_schema
        try:
            jsonschema.validate(instance=inputs, schema=tool.input_schema)
        except jsonschema.ValidationError as exc:
            raise MCPToolError(
                tool_name=tool_name,
                tool_input=inputs,
                error_message=f"Input validation failed: {exc.message}",
            )

        # Execute tool
        try:
            output = self._registry.execute_tool(tool_name, inputs)
        except MCPToolError:
            raise
        except Exception as exc:
            raise MCPToolError(
                tool_name=tool_name,
                tool_input=inputs,
                error_message=str(exc),
            )

        # Validate output against output_schema
        try:
            jsonschema.validate(instance=output, schema=tool.output_schema)
        except jsonschema.ValidationError as exc:
            _log.warning(
                "tool_output_validation_failed",
                tool_name=tool_name,
                error=exc.message,
            )
            raise MCPToolError(
                tool_name=tool_name,
                tool_input=inputs,
                error_message=f"Output validation failed: {exc.message}",
            )

        _log.info("tool_call_success", tool_name=tool_name)
        return output
