"""Self-healing orchestration — FailureTracker + TeacherClient + RulePatcher."""

from pathlib import Path

import aiofiles

from src.core.logging import get_logger
from src.healing.failure_detector import FailureTracker
from src.healing.teacher_client import TeacherClient
from src.healing.rule_patcher import RulePatcher
from src.models.cognitive_template import DAGNode
from src.models.healing import HealingEvent, HealingTrigger
from src.cache.redis_client import RedisClient

_log = get_logger(__name__)


# Redis key for healing events index
HEALING_INDEX_KEY = "specforge:healing_events:index"


def _healing_event_key(event_id: str) -> str:
    return f"specforge:healing_event:{event_id}"

_log = get_logger(__name__)


class SelfHealingOrchestrator:
    """Coordinates failure detection, teacher diagnosis, and rule patching.

    Attributes:
        tracker: FailureTracker instance.
        teacher: TeacherClient instance.
        patcher: RulePatcher instance.
        rules_dir: Path to the rules directory.
        require_approval: If True, patches are stored but not applied until human-approved.
    """

    def __init__(
        self,
        tracker: FailureTracker,
        teacher: TeacherClient,
        patcher: RulePatcher,
        rules_dir: Path,
        require_approval: bool = False,
    ) -> None:
        self._tracker = tracker
        self._teacher = teacher
        self._patcher = patcher
        self._rules_dir = rules_dir
        self._require_approval = require_approval

    async def process_node_failure(
        self,
        template_id: str,
        node: DAGNode,
        raw_output: str,
        error: str,
        run_id: str,
    ) -> HealingEvent | None:
        """Process a node failure end-to-end: track, diagnose, patch.

        Args:
            template_id: ID of the template being executed.
            node: The DAGNode that failed.
            raw_output: Raw output from the failed attempt.
            error: Error message string.
            run_id: Run ID for context.

        Returns:
            A HealingEvent if healing was triggered; None if not yet at threshold.
        """
        # Record failure and check threshold
        threshold_reached = self._tracker.record_failure(
            template_id=template_id,
            node_id=node.node_id,
            raw_output=raw_output,
            error=error,
        )

        if not threshold_reached:
            _log.info(
                "healing_not_yet_triggered",
                node_id=node.node_id,
                template_id=template_id,
            )
            return None

        _log.warning(
            "healing_triggered",
            node_id=node.node_id,
            template_id=template_id,
            run_id=run_id,
        )

        # Collect failure examples
        failure_examples = self._tracker.get_failure_examples(
            template_id=template_id,
            node_id=node.node_id,
        )

        # Load original rule file contents used by this node
        original_contents: dict[str, str] = {}
        for file_name in node.bento_config.rule_files:
            name = file_name if file_name.endswith(".md") else f"{file_name}.md"
            path = self._rules_dir / name
            if path.is_file():
                async with aiofiles.open(path, "r", encoding="utf-8") as fh:
                    original_contents[file_name] = await fh.read()

        # Ask teacher model for each rule file
        patches: list = []
        schema = node.focus_prompt.output_schema

        for file_name, original_content in original_contents.items():
            try:
                prescription = await self._teacher.diagnose_and_prescribe(
                    node=node,
                    rule_file_name=file_name,
                    original_rule_content=original_content,
                    failure_examples=failure_examples,
                    schema=schema,
                )
            except Exception as exc:
                _log.error(
                    "teacher_diagnosis_failed",
                    node_id=node.node_id,
                    file_name=file_name,
                    error=str(exc),
                )
                continue

            changes_summary = "|".join(prescription.get("changes_made", []))

            patch = await self._patcher.apply_patch(
                rule_file_name=file_name,
                new_content=prescription["rewritten_content"],
                changes_summary=changes_summary,
                backup=True,
            )
            patches.append(patch)

        # Build HealingEvent
        event = HealingEvent(
            triggered_at=None,  # default_factory fills
            trigger=HealingTrigger.CONSECUTIVE_FAILURES,
            node_id=node.node_id,
            template_id=template_id,
            failure_count=len(failure_examples),
            failure_examples=failure_examples,
            teacher_model_used="llama3.1:8b",
            patches=patches,
            applied=not self._require_approval,
            applied_at=None if self._require_approval else None,
        )

        _log.info(
            "healing_event_created",
            event_id=event.event_id,
            node_id=node.node_id,
            patches_applied=len(patches),
            requires_approval=self._require_approval,
        )

        # Store event in Redis for dashboard stats
        await _store_event_in_redis(event)

        return event


async def _store_event_in_redis(event: HealingEvent) -> None:
    """Store healing event in Redis for dashboard stats."""
    try:
        redis = RedisClient.from_url("redis://localhost:6379")
        await redis.set(_healing_event_key(event.event_id), event.model_dump_json())
        await redis.sadd(HEALING_INDEX_KEY, event.event_id)
    except Exception as e:
        _log.warning("redis_store_healing_failed", error=str(e))
