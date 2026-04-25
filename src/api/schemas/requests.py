"""API request schemas — all use camelCase aliases for frontend compatibility."""

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def to_camel(name: str) -> str:
    """Convert snake_case to camelCase for frontend aliasing."""
    components = name.split("_")
    return components[0] + "".join(c.title() for c in components[1:])


class CreateTemplateRequest(BaseModel):
    """Request to upload/create a new cognitive template."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    version: str = "1.0.0"
    nodes: list[dict[str, Any]] = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    author: str = "anonymous"


class UpdateTemplateRequest(BaseModel):
    """Request to update an existing template."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    name: str | None = None
    description: str | None = None
    version: str | None = None
    nodes: list[dict[str, Any]] | None = None
    tags: list[str] | None = None


class StartExecutionRequest(BaseModel):
    """Request to start a new execution run."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    template_id: str = Field(..., min_length=1)
    input_data: dict[str, Any] = Field(default_factory=dict)
    output_dir: str = Field(default="./output")


class CreateRuleFileRequest(BaseModel):
    """Request to create a new rule file."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    name: str = Field(..., min_length=1)
    content: str = Field(default="")


class UpdateRuleFileRequest(BaseModel):
    """Request to update an existing rule file."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    content: str = Field(...)


class ApprovalRequest(BaseModel):
    """Request for healing event approval/rejection."""

    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    approved_by: str = Field(default="system")
