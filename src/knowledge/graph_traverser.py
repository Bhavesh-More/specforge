"""Knowledge graph traverser — BFS traversal with depth and token budget constraints."""

import re
from collections import deque
from pathlib import Path
from typing import Any

import aiofiles

from src.core.logging import get_logger
from src.knowledge.graph_indexer import KnowledgeGraphIndexer

_log = get_logger(__name__)

WIKI_LINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


def _estimate_tokens(text: str) -> int:
    """Approximate token count: characters / 4."""
    return len(text) // 4


class KnowledgeGraphTraverser:
    """BFS traversal of wiki-linked rule files with depth and token budget limits.

    Attributes:
        indexer: KnowledgeGraphIndexer instance.
        rules_dir: Path to the rules directory.
        token_budget: Max total tokens across all loaded files.
        max_depth: Max recursion depth for wiki-link following.
    """

    def __init__(
        self,
        indexer: KnowledgeGraphIndexer,
        rules_dir: Path,
        token_budget: int = 1500,
        max_depth: int = 2,
    ) -> None:
        self._indexer = indexer
        self._rules_dir = rules_dir
        self._token_budget = token_budget
        self._max_depth = max_depth

    async def traverse(self, start_files: list[str]) -> dict[str, Any]:
        """BFS traversal from start_files following wiki-links.

        Args:
            start_files: List of starting file names (normalized keys or raw).

        Returns:
            A dict with keys:
            - files: {file_name: content}
            - traversal_order: [file_name, ...]
            - total_tokens: int
            - depth_reached: int
            - budget_hit: bool
            - links_followed: [(from, to), ...]
        """
        files: dict[str, str] = {}
        traversal_order: list[str] = []
        links_followed: list[tuple[str, str]] = []
        visited: set[str] = set()
        total_tokens = 0
        budget_hit = False
        max_depth_reached = 0

        # Normalize start files
        start_keys = {self._normalize_key(f) for f in start_files}

        # BFS queue: (file_key, depth)
        queue: deque[tuple[str, int]] = deque()
        for key in start_keys:
            if key not in visited:
                visited.add(key)
                queue.append((key, 0))

        while queue:
            current_key, depth = queue.popleft()
            max_depth_reached = max(max_depth_reached, depth)

            if depth > self._max_depth:
                continue

            # Load file content
            content = await self._load_file(current_key)
            if content is None:
                continue

            tokens = _estimate_tokens(content)

            # Enforce token budget
            if total_tokens + tokens > self._token_budget:
                budget_hit = True
                _log.warning(
                    "traversal_token_budget_exceeded",
                    current_key=current_key,
                    total_tokens=total_tokens,
                    chunk_tokens=tokens,
                )
                break

            files[current_key] = content
            traversal_order.append(current_key)
            total_tokens += tokens

            # Find linked files via wiki-link pattern in content
            for raw_link in WIKI_LINK_PATTERN.findall(content):
                linked_key = self._normalize_key(raw_link)
                links_followed.append((current_key, linked_key))

                if linked_key not in visited:
                    visited.add(linked_key)
                    queue.append((linked_key, depth + 1))

        return {
            "files": files,
            "traversal_order": traversal_order,
            "total_tokens": total_tokens,
            "depth_reached": max_depth_reached,
            "budget_hit": budget_hit,
            "links_followed": links_followed,
        }

    # ─── Internals ─────────────────────────────────────────────────────────────

    def _normalize_key(self, name: str) -> str:
        """Normalize a wiki-link target to canonical index key."""
        name = name.strip()
        if name.lower().endswith(".md"):
            name = name[:-3]
        return name.lower().replace(" ", "_")

    async def _load_file(self, file_key: str) -> str | None:
        """Load a .md file from rules_dir by normalized key."""
        # Try both with and without .md suffix
        candidates = [
            self._rules_dir / f"{file_key}.md",
            self._rules_dir / file_key,
        ]
        for path in candidates:
            if path.is_file():
                async with aiofiles.open(path, "r", encoding="utf-8") as fh:
                    return await fh.read()
        _log.warning("traverser_file_not_found", file_key=file_key)
        return None
