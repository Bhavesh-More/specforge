"""Knowledge graph manager — high-level interface combining indexer and traverser."""

from pathlib import Path
from typing import Any

import aiofiles

from src.core.logging import get_logger
from src.knowledge.graph_indexer import KnowledgeGraphIndexer
from src.knowledge.graph_traverser import KnowledgeGraphTraverser
from src.models.cognitive_template import DAGNode

_log = get_logger(__name__)


class KnowledgeGraphManager:
    """High-level interface for knowledge graph operations.

    Combines the indexer and traverser into a single facade for managing
    rule files and assembling node context.

    Attributes:
        rules_dir: Path to the rules directory.
        token_budget: Max tokens for context assembly.
        max_depth: Max wiki-link traversal depth.
    """

    def __init__(
        self,
        rules_dir: Path,
        token_budget: int = 1500,
        max_depth: int = 2,
    ) -> None:
        self._rules_dir = rules_dir
        self._token_budget = token_budget
        self._max_depth = max_depth
        self._indexer = KnowledgeGraphIndexer(rules_dir=rules_dir)
        self._traverser = KnowledgeGraphTraverser(
            indexer=self._indexer,
            rules_dir=rules_dir,
            token_budget=token_budget,
            max_depth=max_depth,
        )

    async def initialize(self) -> None:
        """Build the knowledge graph index.

        Must be called before any traversal or context assembly.
        """
        await self._indexer.build_index()
        _log.info("knowledge_graph_manager_initialized", rules_dir=str(self._rules_dir))

    async def get_context_for_node(self, node: DAGNode) -> dict[str, Any]:
        """Assemble knowledge graph context for a specific DAGNode.

        Args:
            node: The DAGNode to build context for.

        Returns:
            A traversal result dict (same format as KnowledgeGraphTraverser.traverse()).
        """
        start_files = node.bento_config.rule_files
        return await self._traverser.traverse(start_files)

    async def create_rule_file(self, name: str, content: str) -> Path:
        """Create a new .md rule file.

        Args:
            name: File base name (with or without .md extension).
            content: Initial markdown content.

        Returns:
            Path to the created file.
        """
        file_name = name if name.endswith(".md") else f"{name}.md"
        path = self._rules_dir / file_name
        path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
            await fh.write(content)

        await self._indexer.build_index()
        _log.info("rule_file_created", name=file_name, path=str(path))
        return path

    async def update_rule_file(self, name: str, content: str) -> None:
        """Overwrite an existing rule file and rebuild the index.

        Args:
            name: File base name.
            content: New markdown content.
        """
        file_name = name if name.endswith(".md") else f"{name}.md"
        path = self._rules_dir / file_name

        async with aiofiles.open(path, "w", encoding="utf-8") as fh:
            await fh.write(content)

        await self._indexer.build_index()
        _log.info("rule_file_updated", name=file_name, path=str(path))

    async def get_graph_stats(self) -> dict[str, Any]:
        """Return summary statistics about the knowledge graph.

        Returns:
            Dict with:
            - total_files: int
            - total_links: int
            - most_linked: list of (file_name, link_count) sorted descending
            - isolated_files: list of files with no links (in or out)
        """
        all_files = self._indexer.get_all_files()
        total_links = sum(len(v) for v in self._indexer._index.values())

        # Files with most outbound links
        link_counts = sorted(
            [(f, len(links)) for f, links in self._indexer._index.items()],
            key=lambda x: x[1],
            reverse=True,
        )
        most_linked = link_counts[:10]  # top 10

        # Isolated files: no outbound and no inbound links
        isolated = [
            f for f in all_files
            if not self._indexer.get_links(f) and not self._indexer.get_backlinks(f)
        ]

        return {
            "total_files": len(all_files),
            "total_links": total_links,
            "most_linked": most_linked,
            "isolated_files": isolated,
        }
