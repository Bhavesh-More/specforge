"""Template registry — load, save, cache, and version Cognitive Templates."""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import aiofiles

from src.core.exceptions import TemplateNotFoundError
from src.core.logging import get_logger
from src.models.cognitive_template import CognitiveTemplate

_log = get_logger(__name__)

# Module-level singleton reference
_registry: "TemplateRegistry | None" = None


def get_registry(templates_dir: Path) -> "TemplateRegistry":
    """Return a cached TemplateRegistry singleton for the given templates directory.

    Args:
        templates_dir: Path to the directory containing .ct.json template files.
    """
    global _registry
    if _registry is None:
        _registry = TemplateRegistry(templates_dir=templates_dir)
    return _registry


class TemplateRegistry:
    """Manages loading, saving, caching, and versioning of Cognitive Templates.

    All file I/O is async via aiofiles. All operations are logged.

    Attributes:
        templates_dir: Path to the directory containing .ct.json files.
    """

    def __init__(self, templates_dir: Path) -> None:
        self._templates_dir = templates_dir
        self._cache: dict[str, CognitiveTemplate] = {}

    # ─── Load ──────────────────────────────────────────────────────────────────

    async def load(self, template_id_or_name: str) -> CognitiveTemplate:
        """Load a template by ID or name, using in-memory cache first.

        Checks cache, then disk. Files are matched by template_id (exact) or
        name (exact, case-insensitive). The loaded template is cached.

        Args:
            template_id_or_name: template_id UUID or template name string.

        Returns:
            The matched CognitiveTemplate instance.

        Raises:
            TemplateNotFoundError: No matching .ct.json file found on disk.
        """
        # Cache hit
        if template_id_or_name in self._cache:
            _log.debug("template_cache_hit", key=template_id_or_name)
            return self._cache[template_id_or_name]

        _log.debug("template_cache_miss", key=template_id_or_name)

        requested_key = template_id_or_name.strip()

        # Scan directory for matching file
        found_path: Path | None = None
        for entry in self._iter_ct_files():
            if entry.name.endswith(".ct.json"):
                async with aiofiles.open(entry, "r", encoding="utf-8") as fh:
                    raw = await fh.read()
                try:
                    top = json.loads(raw)
                    tid = top.get("template_id", "") or entry.stem
                    tname = top.get("name", "")
                except json.JSONDecodeError:
                    continue

                file_key = entry.name[:-8]  # strip trailing ".ct.json"

                if (
                    tid == requested_key
                    or tname.lower() == requested_key.lower()
                    or file_key.lower() == requested_key.lower()
                ):
                    found_path = entry
                    break

        if found_path is None:
            _log.warning("template_not_found", key=template_id_or_name)
            raise TemplateNotFoundError(
                template_path=template_id_or_name,
                context={"operation": "load"},
            )

        # Load and validate
        template = CognitiveTemplate.load_from_file(found_path)
        if not template.template_id:
            template = template.model_copy(update={"template_id": found_path.stem})
        self._cache[template.template_id] = template
        if template.name.lower() not in self._cache:
            self._cache[template.name.lower()] = template

        _log.info("template_loaded", template_id=template.template_id, name=template.name)
        return template

    # ─── Save ─────────────────────────────────────────────────────────────────

    async def save(
        self,
        template: CognitiveTemplate,
        overwrite: bool = False,
    ) -> Path:
        """Serialize and save a CognitiveTemplate to a .ct.json file.

        File is saved as ``{templates_dir}/{template_id}.ct.json``.

        Args:
            template: The CognitiveTemplate to serialize and save.
            overwrite: If False, refuse to overwrite an existing file.

        Returns:
            Path to the saved file.

        Raises:
            FileExistsError: overwrite=False and file already exists.
        """
        dest = self._templates_dir / f"{template.template_id}.ct.json"

        if dest.exists() and not overwrite:
            raise FileExistsError(f"Template file already exists: {dest}")

        dest.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(dest, "w", encoding="utf-8") as fh:
            await fh.write(template.model_dump_json(indent=2))

        self._cache[template.template_id] = template
        if template.name not in self._cache:
            self._cache[template.name.lower()] = template

        _log.info(
            "template_saved",
            template_id=template.template_id,
            name=template.name,
            path=str(dest),
        )
        return dest

    # ─── List ─────────────────────────────────────────────────────────────────

    async def list_templates(self) -> list[dict[str, Any]]:
        """Return lightweight metadata for all .ct.json files in templates_dir.

        Does NOT load full templates — reads only top-level fields from each JSON.
        Useful for directory browsers without full deserialization cost.

        Returns:
            List of dicts with keys: template_id, name, version, description, tags.
        """
        results: list[dict[str, Any]] = []
        for entry in self._iter_ct_files():
            async with aiofiles.open(entry, "r", encoding="utf-8") as fh:
                raw = await fh.read()
            try:
                top = json.loads(raw)
                results.append({
                    "template_id": top.get("template_id", "") or entry.stem,
                    "name": top.get("name", ""),
                    "version": top.get("version", ""),
                    "description": top.get("description", ""),
                    "tags": top.get("tags", []),
                })
            except json.JSONDecodeError:
                _log.warning("skipping_invalid_template_file", path=str(entry))

        _log.debug("template_list_returned", count=len(results))
        return results

    # ─── Delete ───────────────────────────────────────────────────────────────

    async def delete(self, template_id: str) -> bool:
        """Delete a template file and evict it from cache.

        Args:
            template_id: The UUID of the template to delete.

        Returns:
            True if the file was deleted, False if it was not found on disk.
        """
        # Evict from cache regardless
        cached = self._cache.pop(template_id, None)
        if cached is not None:
            self._cache.pop(cached.name, None)

        # Find and delete file
        for entry in self._templates_dir.iterdir():
            if entry.name.endswith(".ct.json") and entry.stem == template_id:
                entry.unlink()
                _log.info("template_deleted", template_id=template_id)
                return True

        _log.warning("template_delete_not_found", template_id=template_id)
        return False

    # ─── Cache ─────────────────────────────────────────────────────────────────

    def invalidate_cache(self, template_id: str | None = None) -> None:
        """Evict one template or the entire in-memory cache.

        Args:
            template_id: If provided, evict only this template_id.
                        If None, clear the entire cache.
        """
        if template_id is None:
            self._cache.clear()
            _log.info("template_cache_cleared")
        else:
            cached = self._cache.pop(template_id, None)
            if cached is not None:
                self._cache.pop(cached.name, None)
            _log.info("template_cache_evicted", template_id=template_id)

    # ─── Internals ─────────────────────────────────────────────────────────────

    def _iter_ct_files(self):
        """Yield Path objects for all .ct.json files in templates_dir."""
        self._templates_dir.mkdir(parents=True, exist_ok=True)

        for entry in self._templates_dir.iterdir():
            if entry.is_file() and entry.name.endswith(".ct.json"):
                yield entry
