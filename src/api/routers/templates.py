"""Templates router — CRUD for cognitive templates."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from src.api.dependencies import get_template_registry
from src.api.schemas.requests import CreateTemplateRequest, UpdateTemplateRequest
from src.api.schemas.responses import (
    ExecutionOrderResponse,
    PaginatedListResponse,
    TemplateDetail,
    TemplateSummary,
)
from src.compiler.template_registry import TemplateRegistry
from src.compiler.dag_builder import DAGBuilder
from src.core.exceptions import TemplateNotFoundError, TemplateValidationError
from src.models.cognitive_template import CognitiveTemplate

router = APIRouter()


@router.get("/templates", response_model=PaginatedListResponse)
async def list_templates(
    registry: TemplateRegistry = Depends(get_template_registry),
) -> PaginatedListResponse:
    """List all cognitive templates (lightweight metadata only)."""
    raw = await registry.list_templates()
    items = [
        TemplateSummary(
            template_id=t["template_id"],
            name=t["name"],
            version=t["version"],
            description=t["description"],
            tags=t.get("tags", []),
        )
        for t in raw
    ]
    return PaginatedListResponse(items=items, total=len(items))


@router.get("/templates/{template_id}", response_model=TemplateDetail)
async def get_template(
    template_id: str,
    registry: TemplateRegistry = Depends(get_template_registry),
) -> TemplateDetail:
    """Get full template JSON by ID."""
    try:
        template = await registry.load(template_id)
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")

    return TemplateDetail(
        template_id=template.template_id,
        name=template.name,
        description=template.description,
        version=template.version,
        schema_version=template.schema_version,
        nodes=[n.model_dump(mode="json") for n in template.nodes],
        created_at=template.created_at,
        updated_at=template.updated_at,
        tags=template.tags,
        author=template.author,
    )


@router.post("/templates", response_model=TemplateDetail, status_code=status.HTTP_201_CREATED)
async def create_template(
    req: CreateTemplateRequest,
    registry: TemplateRegistry = Depends(get_template_registry),
) -> TemplateDetail:
    """Upload and validate a new cognitive template."""
    import uuid

    template_data = {
        "template_id": str(uuid.uuid4()),
        "name": req.name,
        "description": req.description,
        "version": req.version,
        "schema_version": "1.0.0",
        "nodes": req.nodes,
        "tags": req.tags,
        "author": req.author,
    }

    try:
        template = CognitiveTemplate.model_validate(template_data)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc.errors()))

    try:
        await registry.save(template, overwrite=False)
    except FileExistsError:
        raise HTTPException(status_code=409, detail="Template with this ID already exists")

    return TemplateDetail(
        template_id=template.template_id,
        name=template.name,
        description=template.description,
        version=template.version,
        schema_version=template.schema_version,
        nodes=[n.model_dump(mode="json") for n in template.nodes],
        created_at=template.created_at,
        updated_at=template.updated_at,
        tags=template.tags,
        author=template.author,
    )


@router.put("/templates/{template_id}", response_model=TemplateDetail)
async def update_template(
    template_id: str,
    req: UpdateTemplateRequest,
    registry: TemplateRegistry = Depends(get_template_registry),
) -> TemplateDetail:
    """Update an existing cognitive template."""
    try:
        template = await registry.load(template_id)
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")

    update_data = req.model_dump(exclude_unset=True)
    merged = template.model_copy(update=update_data)

    try:
        await registry.save(merged, overwrite=True)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to save template")

    return TemplateDetail(
        template_id=merged.template_id,
        name=merged.name,
        description=merged.description,
        version=merged.version,
        schema_version=merged.schema_version,
        nodes=[n.model_dump(mode="json") for n in merged.nodes],
        created_at=merged.created_at,
        updated_at=merged.updated_at,
        tags=merged.tags,
        author=merged.author,
    )


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: str,
    registry: TemplateRegistry = Depends(get_template_registry),
) -> None:
    """Delete a cognitive template."""
    deleted = await registry.delete(template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")


@router.get("/templates/{template_id}/validate")
async def validate_template(
    template_id: str,
    registry: TemplateRegistry = Depends(get_template_registry),
) -> dict[str, Any]:
    """Validate DAG structure without executing."""
    try:
        template = await registry.load(template_id)
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")

    builder = DAGBuilder()
    errors = builder.validate_structure(template.nodes)

    if errors:
        return {"valid": False, "errors": errors}

    return {"valid": True, "errors": []}


@router.get("/templates/{template_id}/execution-order", response_model=ExecutionOrderResponse)
async def get_execution_order(
    template_id: str,
    registry: TemplateRegistry = Depends(get_template_registry),
) -> ExecutionOrderResponse:
    """Return execution waves for a template."""
    try:
        template = await registry.load(template_id)
    except TemplateNotFoundError:
        raise HTTPException(status_code=404, detail="Template not found")

    waves = template.get_execution_order()
    return ExecutionOrderResponse(template_id=template_id, waves=waves)
