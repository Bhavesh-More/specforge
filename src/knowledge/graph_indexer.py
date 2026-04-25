"""Knowledge graph indexer — builds an in-memory adjacency map of .md rule files."""

import json
import re
from pathlib import Path
from typing import Any

import aiofiles

from src.core.logging import get_logger

_log = get_logger(__name__)

WIKI_LINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


def _normalize_link(name: str) -> str:
    """Normalize a wiki-link target to a canonical index key.

    - Strip .md extension
    - Lowercase
    - Replace spaces with underscores
    """
    name = name.strip()
    if name.lower().endswith(".md"):
        name = name[:-3]
    return name.lower().replace(" ", "_")


class KnowledgeGraphIndexer:
    """Builds and maintains an in-memory index of wiki-links between .md rule files.

    Attributes:
        rules_dir: Path to the rules directory.
    """

    def __init__(self, rules_dir: Path) -> None:
        self._rules_dir = rules_dir
        self._index: dict[str, set[str]] = {}  # file_name → set of linked file_names
        self._reverse_index: dict[str, set[str]] = {}  # file_name → set of files linking to it

    async def build_index(self) -> None:
        """Scan all .md files in rules_dir, extract wiki-links, build adjacency indices."""
        self._index.clear()
        self._reverse_index.clear()

        self._rules_dir.mkdir(parents=True, exist_ok=True)

        md_files = [p for p in self._rules_dir.iterdir() if p.is_file() and p.suffix == ".md"]

        for path in md_files:
            file_key = _normalize_link(path.stem)
            async with aiofiles.open(path, "r", encoding="utf-8") as fh:
                content = await fh.read()

            links: set[str] = set()
            for raw_name in WIKI_LINK_PATTERN.findall(content):
                linked_key = _normalize_link(raw_name)
                links.add(linked_key)

                if linked_key not in self._reverse_index:
                    self._reverse_index[linked_key] = set()
                self._reverse_index[linked_key].add(file_key)

            self._index[file_key] = links

        _log.info(
            "graph_index_built",
            total_files=len(md_files),
            total_links=sum(len(v) for v in self._index.values()),
        )

    def get_links(self, file_name: str) -> set[str]:
        """Return all files that file_name links to (outbound edges).

        Args:
            file_name: Normalized key for the source file.

        Returns:
            Set of normalized linked file keys.
        """
        return set(self._index.get(_normalize_link(file_name), set()))

    def get_backlinks(self, file_name: str) -> set[str]:
        """Return all files that link to file_name (inbound edges).

        Args:
            file_name: Normalized key for the target file.

        Returns:
            Set of normalized file keys that link to this file.
        """
        return set(self._reverse_index.get(_normalize_link(file_name), set()))

    def get_all_files(self) -> list[str]:
        """Return all indexed file names (normalized keys)."""
        return list(self._index.keys())

    async def export_obsidian_json(self, output_path: Path) -> None:
        """Export the graph as Obsidian-compatible JSON for visualization.

        Format:
        {
          "nodes": [{"id": "file_name", "links": [to_ids...]}, ...],
          "edges": [{"source": "...", "target": "..."}, ...]
        }

        Args:
            output_path: Destination path for the JSON file.
        """
        nodes = [
            {"id": name, "links": sorted(links)}
            for name, links in self._index.items()
        ]
        edges = [
            {"source": src, "target": dst}
            for src, dsts in self._index.items()
            for dst in dsts
        ]
        payload: dict[str, Any] = {"nodes": nodes, "edges": edges}

        output_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(output_path, "w", encoding="utf-8") as fh:
            await fh.write(json.dumps(payload, indent=2))

        _log.info("obsidian_graph_exported", path=str(output_path), nodes=len(nodes), edges=len(edges))
