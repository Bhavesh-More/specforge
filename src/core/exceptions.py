"""Domain exceptions for SpecForge."""


class SpecForgeError(Exception):
    """Base exception for all SpecForge domain errors.

    Attributes:
        message: Human-readable error description.
        code: Unique error code string for programmatic handling.
        context: Arbitrary context dict with additional debug info.
    """

    def __init__(
        self,
        message: str,
        code: str,
        context: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.context = context or {}


class TemplateNotFoundError(SpecForgeError):
    """Raised when a .ct.json template file cannot be found on disk."""

    def __init__(
        self,
        template_path: str,
        context: dict | None = None,
    ) -> None:
        super().__init__(
            message=f"Template not found: {template_path}",
            code="TEMPLATE_NOT_FOUND",
            context=context,
        )


class TemplateValidationError(SpecForgeError):
    """Raised when a template DAG is structurally invalid.

    Detects: cycles, missing node references, invalid dependencies.
    """

    def __init__(
        self,
        errors: list[str],
        template_path: str | None = None,
        context: dict | None = None,
    ) -> None:
        super().__init__(
            message=f"Template validation failed: {'; '.join(errors)}",
            code="TEMPLATE_VALIDATION_ERROR",
            context=context,
        )
        self.errors = errors
        self.template_path = template_path


class NodeExecutionError(SpecForgeError):
    """Raised when an atomic node exhausts all retry attempts.

    Attributes:
        node_id: ID of the node that failed.
        attempt_count: Total attempts made before failure.
        last_output: Raw output from the final attempt (truncated).
    """

    def __init__(
        self,
        node_id: str,
        attempt_count: int,
        last_output: str = "",
        context: dict | None = None,
    ) -> None:
        super().__init__(
            message=f"Node '{node_id}' failed after {attempt_count} attempts",
            code="NODE_EXECUTION_ERROR",
            context=context,
        )
        self.node_id = node_id
        self.attempt_count = attempt_count
        self.last_output = last_output


class SchemaValidationError(SpecForgeError):
    """Raised when a node's output fails JSON Schema validation.

    Attributes:
        node_id: ID of the node that produced invalid output.
        validation_errors: List of jsonschema ValidationError messages.
        raw_output: The raw output string that failed validation.
    """

    def __init__(
        self,
        node_id: str,
        validation_errors: list[str],
        raw_output: str = "",
        context: dict | None = None,
    ) -> None:
        super().__init__(
            message=f"Schema validation failed for node '{node_id}': {'; '.join(validation_errors)}",
            code="SCHEMA_VALIDATION_ERROR",
            context=context,
        )
        self.node_id = node_id
        self.validation_errors = validation_errors
        self.raw_output = raw_output


class KnowledgeGraphError(SpecForgeError):
    """Raised when knowledge graph operations fail.

    Covers: traversal, indexing, link resolution, cycle detection.
    """

    def __init__(
        self,
        message: str,
        context: dict | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="KNOWLEDGE_GRAPH_ERROR",
            context=context,
        )


class HealingError(SpecForgeError):
    """Raised when the self-healing loop fails to produce a fix."""

    def __init__(
        self,
        node_id: str,
        failure_reason: str,
        context: dict | None = None,
    ) -> None:
        super().__init__(
            message=f"Self-healing failed for node '{node_id}': {failure_reason}",
            code="HEALING_ERROR",
            context=context,
        )
        self.node_id = node_id
        self.failure_reason = failure_reason


class OllamaConnectionError(SpecForgeError):
    """Raised when Ollama is unreachable or returns an unexpected error."""

    def __init__(
        self,
        base_url: str,
        original_exc: Exception | None = None,
        context: dict | None = None,
    ) -> None:
        super().__init__(
            message=f"Cannot connect to Ollama at {base_url}",
            code="OLLAMA_CONNECTION_ERROR",
            context=context,
        )
        self.base_url = base_url
        self.original_exc = original_exc


class MCPToolError(SpecForgeError):
    """Raised when an MCP tool call returns an error.

    Attributes:
        tool_name: Name of the MCP tool that failed.
        tool_input: Input payload sent to the tool.
    """

    def __init__(
        self,
        tool_name: str,
        tool_input: dict,
        error_message: str = "",
        context: dict | None = None,
    ) -> None:
        super().__init__(
            message=f"MCP tool '{tool_name}' failed: {error_message}",
            code="MCP_TOOL_ERROR",
            context=context,
        )
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.error_message = error_message
