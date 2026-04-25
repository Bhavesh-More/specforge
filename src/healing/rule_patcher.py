"""Rule file patcher — applies teacher-prescribed patches to rule files on disk."""

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from src.core.logging import get_logger
from src.models.healing import RuleFilePatch

_log = get_logger(__name__)


class RulePatcher:
    """Applies, reverts, and tracks patches to rule .md files.

    Attributes:
        rules_dir: Path to the directory containing rule .md files.
    """

    def __init__(self, rules_dir: Path) -> None:
        self._rules_dir = rules_dir

    async def apply_patch(
        self,
        rule_file_name: str,
        new_content: str,
        changes_summary: str,
        backup: bool = True,
    ) -> RuleFilePatch:
        """Apply a rewritten rule file to disk, optionally creating a timestamped backup.

        Args:
            rule_file_name: Base name of the rule file to patch.
            new_content: The new markdown content to write.
            changes_summary: Human-readable summary of changes made.
            backup: If True, save the current content to a timestamped .bak file first.

        Returns:
            A RuleFilePatch model describing the change.
        """
        name = rule_file_name if rule_file_name.endswith(".md") else f"{rule_file_name}.md"
        path = self._rules_dir / name

        original_content = ""
        if path.is_file():
            if backup:
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                backup_path = self._rules_dir / f"{name}.bak.{timestamp}"
                shutil.copy2(path, backup_path)
                _log.info(
                    "rule_backup_created",
                    original=str(path),
                    backup=str(backup_path),
                )
            async with aiofiles.open(path, "r", encoding="utf-8") as fh:
                original_content = await fh.read()
        else:
            _log.warning("rule_file_not_found_for_patch", path=str(path))

        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
            await fh.write(new_content)

        _log.info(
            "rule_patch_applied",
            rule_file=name,
            changes=changes_summary,
        )

        return RuleFilePatch(
            file_name=name,
            original_content=original_content,
            patched_content=new_content,
            changes_summary=changes_summary,
            semantic_weights_applied=changes_summary.split("|")
            if "|" in changes_summary
            else [changes_summary],
        )

    async def get_patch_history(self, rule_file_name: str) -> list[Path]:
        """Return sorted list of backup files for a given rule file.

        Args:
            rule_file_name: Base name of the rule file.

        Returns:
            List of backup Path objects, sorted newest-first.
        """
        name = rule_file_name if rule_file_name.endswith(".md") else f"{rule_file_name}.md"
        backups = sorted(
            (p for p in self._rules_dir.iterdir() if p.name.startswith(f"{name}.bak.")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return backups

    async def revert_patch(self, rule_file_name: str, backup_path: Path) -> bool:
        """Restore a rule file from a timestamped backup.

        Args:
            rule_file_name: Base name of the rule file.
            backup_path: Path to the specific .bak.* file to restore.

        Returns:
            True if the restore succeeded; False if the backup file did not exist.
        """
        name = rule_file_name if rule_file_name.endswith(".md") else f"{rule_file_name}.md"
        target = self._rules_dir / name

        if not backup_path.is_file():
            _log.error("revert_backup_not_found", backup=str(backup_path))
            return False

        shutil.copy2(backup_path, target)
        _log.info("rule_patch_reverted", rule_file=name, backup=str(backup_path))
        return True
