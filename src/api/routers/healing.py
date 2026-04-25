"""Healing router — view and approve/reject self-healing events."""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.dependencies import get_knowledge_manager
from src.api.schemas.requests import ApprovalRequest
from src.api.schemas.responses import (
    HealingEventDetail,
    HealingEventSummary,
    PaginatedListResponse,
)
from src.core.logging import get_logger
from src.healing.rule_patcher import RulePatcher

_log = get_logger(__name__)

router = APIRouter()

# In-memory event store (replace with Redis/DB in production)
_events_store: dict[str, dict] = {}


def _store_event(event_id: str, data: dict) -> None:
    _events_store[event_id] = data


def _load_event(event_id: str) -> dict | None:
    return _events_store.get(event_id)


@router.get("/healing/events", response_model=PaginatedListResponse)
async def list_healing_events() -> PaginatedListResponse:
    """List the 20 most recent healing events."""
    events = sorted(
        _events_store.values(),
        key=lambda e: e.get("triggered_at", ""),
        reverse=True,
    )[:20]

    items = [
        HealingEventSummary(
            event_id=e["event_id"],
            triggered_at=e["triggered_at"],
            trigger=e["trigger"],
            node_id=e["node_id"],
            template_id=e["template_id"],
            failure_count=e["failure_count"],
            applied=e["applied"],
            approved_by=e.get("approved_by"),
        )
        for e in events
    ]
    return PaginatedListResponse(items=items, total=len(items))


@router.get("/healing/events/{event_id}", response_model=HealingEventDetail)
async def get_healing_event(event_id: str) -> HealingEventDetail:
    """Get full healing event details including patches."""
    event = _load_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Healing event not found")

    return HealingEventDetail(
        event_id=event["event_id"],
        triggered_at=event["triggered_at"],
        trigger=event["trigger"],
        node_id=event["node_id"],
        template_id=event["template_id"],
        failure_count=event["failure_count"],
        failure_examples=event["failure_examples"],
        teacher_model_used=event["teacher_model_used"],
        patches=[
            {
                "file_name": p["file_name"],
                "original_content": p["original_content"],
                "patched_content": p["patched_content"],
                "changes_summary": p["changes_summary"],
                "semantic_weights_applied": p["semantic_weights_applied"],
            }
            for p in event.get("patches", [])
        ],
        applied=event["applied"],
        applied_at=event.get("applied_at"),
        approved_by=event.get("approved_by"),
    )


@router.post("/healing/events/{event_id}/approve")
async def approve_healing_event(
    event_id: str,
    req: ApprovalRequest,
) -> dict[str, str]:
    """Apply the healing patches (for require_approval mode)."""
    event = _load_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Healing event not found")

    if event["applied"]:
        raise HTTPException(status_code=409, detail="Patches already applied")

    # Apply patches
    from pathlib import Path

    patcher = RulePatcher(rules_dir=Path("rules"))
    for patch_data in event.get("patches", []):
        await patcher.apply_patch(
            rule_file_name=patch_data["file_name"],
            new_content=patch_data["patched_content"],
            changes_summary=patch_data["changes_summary"],
            backup=True,
        )

    event["applied"] = True
    event["applied_at"] = datetime.now(timezone.utc).isoformat()
    event["approved_by"] = req.approved_by
    _store_event(event_id, event)

    _log.info("healing_event_approved", event_id=event_id, approved_by=req.approved_by)
    return {"status": "approved", "event_id": event_id}


@router.post("/healing/events/{event_id}/reject")
async def reject_healing_event(
    event_id: str,
    req: ApprovalRequest,
) -> dict[str, str]:
    """Reject a healing event (do not apply patches)."""
    event = _load_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Healing event not found")

    event["applied"] = False
    event["approved_by"] = req.approved_by
    _store_event(event_id, event)

    _log.info("healing_event_rejected", event_id=event_id, rejected_by=req.approved_by)
    return {"status": "rejected", "event_id": event_id}


@router.get("/healing/rule-history/{file_name}")
async def get_rule_history(file_name: str) -> dict[str, list[str]]:
    """List backup files for a rule file."""
    from pathlib import Path

    patcher = RulePatcher(rules_dir=Path("rules"))
    backups = await patcher.get_patch_history(file_name)
    return {"backups": [str(p) for p in backups]}
