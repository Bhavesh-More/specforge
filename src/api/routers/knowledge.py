"""Knowledge graph router — CRUD for rule files + graph statistics."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from src.api.dependencies import get_knowledge_manager
from src.api.schemas.requests import CreateRuleFileRequest, UpdateRuleFileRequest
from src.api.schemas.responses import (
    GraphStatsResponse,
    PaginatedListResponse,
    RuleFileResponse,
)
from src.core.logging import get_logger
from src.knowledge.graph_manager import KnowledgeGraphManager

_log = get_logger(__name__)

router = APIRouter()


@router.get("/knowledge/files", response_model=PaginatedListResponse)
async def list_rule_files(
    kg: KnowledgeGraphManager = Depends(get_knowledge_manager),
) -> PaginatedListResponse:
    """List all rule files in the knowledge graph."""
    await kg.initialize()
    stats = await kg.get_graph_stats()
    files = stats.get("isolated_files", []) + [
        f for f in kg._indexer.get_all_files()
    ]
    items = [
        RuleFileResponse(name=f, content="", size_bytes=0) for f in sorted(set(files))
    ]
    return PaginatedListResponse(items=items, total=len(items))


@router.get("/knowledge/files/{file_name}", response_model=RuleFileResponse)
async def get_rule_file(
    file_name: str,
    kg: KnowledgeGraphManager = Depends(get_knowledge_manager),
) -> RuleFileResponse:
    """Get the content of a specific rule file."""
    from pathlib import Path

    path = kg._rules_dir / (file_name if file_name.endswith(".md") else f"{file_name}.md")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Rule file not found")

    content = path.read_text(encoding="utf-8")
    return RuleFileResponse(name=file_name, content=content, size_bytes=len(content))


@router.post("/knowledge/files", response_model=RuleFileResponse, status_code=status.HTTP_201_CREATED)
async def create_rule_file(
    req: CreateRuleFileRequest,
    kg: KnowledgeGraphManager = Depends(get_knowledge_manager),
) -> RuleFileResponse:
    """Create a new rule file."""
    path = await kg.create_rule_file(req.name, req.content)
    name = path.name
    return RuleFileResponse(name=name, content=req.content, size_bytes=len(req.content))


@router.put("/knowledge/files/{file_name}", response_model=RuleFileResponse)
async def update_rule_file(
    file_name: str,
    req: UpdateRuleFileRequest,
    kg: KnowledgeGraphManager = Depends(get_knowledge_manager),
) -> RuleFileResponse:
    """Update an existing rule file."""
    await kg.update_rule_file(file_name, req.content)
    return RuleFileResponse(name=file_name, content=req.content, size_bytes=len(req.content))


@router.delete("/knowledge/files/{file_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule_file(
    file_name: str,
    kg: KnowledgeGraphManager = Depends(get_knowledge_manager),
) -> None:
    """Delete a rule file."""
    from pathlib import Path

    path = kg._rules_dir / (file_name if file_name.endswith(".md") else f"{file_name}.md")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Rule file not found")
    path.unlink()
    await kg.initialize()  # Rebuild index after deletion


@router.get("/knowledge/graph", response_model=GraphStatsResponse)
async def get_graph_stats(
    kg: KnowledgeGraphManager = Depends(get_knowledge_manager),
) -> GraphStatsResponse:
    """Return graph statistics and adjacency map."""
    await kg.initialize()
    stats = await kg.get_graph_stats()
    return GraphStatsResponse(
        total_files=stats["total_files"],
        total_links=stats["total_links"],
        most_linked=stats["most_linked"],
        isolated_files=stats["isolated_files"],
        adjacency_map=kg._indexer._index,
    )


@router.post("/knowledge/rebuild")
async def rebuild_graph(
    kg: KnowledgeGraphManager = Depends(get_knowledge_manager),
) -> dict[str, str]:
    """Trigger a full knowledge graph index rebuild."""
    await kg.initialize()
    return {"status": "rebuilt"}
