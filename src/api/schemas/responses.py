"""API response schemas — all use camelCase aliases for frontend compatibility."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.api.schemas.requests import to_camel


class TemplateSummary(BaseModel):
    """Lightweight template metadata for list responses."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    template_id: str
    name: str
    version: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class TemplateDetail(BaseModel):
    """Full template detail response."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    template_id: str
    name: str
    description: str
    version: str
    schema_version: str
    nodes: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    tags: list[str]
    author: str


class ExecutionOrderResponse(BaseModel):
    """Execution waves for a template."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    template_id: str
    waves: list[list[str]]


class ExecutionSummary(BaseModel):
    """Lightweight execution run metadata."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    run_id: str
    template_id: str
    template_name: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    total_execution_time_ms: float | None = None


class ExecutionDetail(BaseModel):
    """Full execution run detail response."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    run_id: str
    template_id: str
    template_name: str
    status: str
    input_data: dict[str, Any]
    node_results: dict[str, Any]
    global_state: dict[str, Any]
    final_output: dict[str, Any] | None = None
    started_at: datetime
    completed_at: datetime | None = None
    total_execution_time_ms: float | None = None
    error_message: str | None = None
    state_file_path: str | None = None


class RuleFileResponse(BaseModel):
    """Rule file content response."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    name: str
    content: str
    size_bytes: int = 0


class GraphStatsResponse(BaseModel):
    """Knowledge graph statistics."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    total_files: int
    total_links: int
    most_linked: list[tuple[str, int]]
    isolated_files: list[str]
    adjacency_map: dict[str, list[str]]


class HealingEventSummary(BaseModel):
    """Lightweight healing event metadata."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    event_id: str
    triggered_at: datetime
    trigger: str
    node_id: str
    template_id: str
    failure_count: int
    applied: bool
    approved_by: str | None = None


class HealingEventDetail(BaseModel):
    """Full healing event detail."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    event_id: str
    triggered_at: datetime
    trigger: str
    node_id: str
    template_id: str
    failure_count: int
    failure_examples: list[str]
    teacher_model_used: str
    patches: list[dict[str, Any]]
    applied: bool
    applied_at: datetime | None = None
    approved_by: str | None = None


class PaginatedListResponse(BaseModel):
    """Generic paginated list wrapper."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    items: list[Any] = Field(default_factory=list)
    total: int = 0


class ErrorResponse(BaseModel):
    """Standard error response format."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    code: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
