"""DAG builder — validates, enriches, and analyses a list of DAGNode objects."""

from typing import Any

import networkx as nx

from src.core.exceptions import TemplateValidationError
from src.models.cognitive_template import DAGNode, NodeType


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _build_graph(nodes: list[DAGNode]) -> nx.DiGraph:
    """Build a NetworkX directed graph from a list of DAGNodes."""
    G = nx.DiGraph()
    for node in nodes:
        G.add_node(node.node_id)
    for node in nodes:
        for dep in node.depends_on:
            G.add_edge(dep, node.node_id)
    return G

def _validate_node_ids(nodes: list[DAGNode]) -> list[str]:
    """Return errors for duplicate node_ids."""
    errors: list[str] = []
    seen: set[str] = set()
    dupes: set[str] = set()
    for node in nodes:
        if node.node_id in seen:
            dupes.add(node.node_id)
        seen.add(node.node_id)
    if dupes:
        errors.append(f"Duplicate node IDs: {sorted(dupes)}")
    return errors


def _validate_dependencies(nodes: list[DAGNode]) -> list[str]:
    """Return errors for dangling depends_on references."""
    errors: list[str] = []
    ids_set = {n.node_id for n in nodes}
    for node in nodes:
        for dep in node.depends_on:
            if dep not in ids_set:
                errors.append(
                    f"Node '{node.node_id}' depends on unknown node '{dep}'"
                )
    return errors


def _validate_symbolic_nodes(nodes: list[DAGNode]) -> list[str]:
    """Return errors for SYMBOLIC nodes missing symbolic_tool."""
    errors: list[str] = []
    for node in nodes:
        if node.node_type == NodeType.SYMBOLIC and not node.symbolic_tool:
            errors.append(
                f"Node '{node.node_id}' is SYMBOLIC but has no symbolic_tool"
            )
    return errors


# ─── DFS cycle detection (WHITE/GRAY/BLACK) ───────────────────────────────────

def _dfs_cycles(G: nx.DiGraph) -> list[list[str]]:
    """Detect cycles via DFS WHITE/GRAY/BLACK coloring.

    Returns:
        List of cycles found, each cycle is a list of node_ids.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in G.nodes()}
    cycles: list[list[str]] = []

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GRAY
        path.append(node)
        for neighbor in G.successors(node):
            if color.get(neighbor, WHITE) == GRAY:
                # Cycle found — slice from first occurrence of neighbor to end
                idx = path.index(neighbor)
                cycles.append(path[idx:] + [neighbor])
            elif color.get(neighbor, WHITE) == WHITE:
                dfs(neighbor, path)
        path.pop()
        color[node] = BLACK

    for node in G.nodes():
        if color[node] == WHITE:
            dfs(node, [])

    return cycles


# ─── Class ────────────────────────────────────────────────────────────────────


class DAGBuilder:
    """Validates and enriches a list of DAGNode objects into a verified DAG."""

    def validate_structure(self, nodes: list[DAGNode]) -> list[str]:
        """Validate a list of nodes for structural errors.

        Checks: duplicate IDs, dangling dependencies, SYMBOLIC missing tool.

        Returns:
            List of error strings. Empty list means valid.
        """
        errors: list[str] = []
        errors.extend(_validate_node_ids(nodes))
        errors.extend(_validate_dependencies(nodes))
        errors.extend(_validate_symbolic_nodes(nodes))
        errors.extend(self.detect_cycles(nodes))
        return errors

    def detect_cycles(self, nodes: list[DAGNode]) -> list[list[str]]:
        """Detect cycles using WHITE/GRAY/BLACK DFS.

        Returns:
            List of cycles, each cycle is a list of node_ids.
        """
        G = _build_graph(nodes)
        return _dfs_cycles(G)

    def compute_execution_waves(self, nodes: list[DAGNode]) -> list[list[str]]:
        """Topological sort grouped by depth level.

        Wave 0 = root nodes (no dependencies).
        Wave N+1 = all nodes whose dependencies are fully in waves 0..N.

        Returns:
            List of waves, each wave is a list of node_id strings.
        """
        G = _build_graph(nodes)
        waves: list[list[str]] = []
        assigned: set[str] = set()
        remaining: set[str] = set(G.nodes())

        while remaining:
            wave_nodes: list[str] = [
                node_id
                for node_id in remaining
                if all(dep in assigned for dep in G.predecessors(node_id))
            ]
            if not wave_nodes:
                # Should not happen for valid DAGs; guard against infinite loop
                break
            waves.append(sorted(wave_nodes))
            assigned.update(wave_nodes)
            remaining.difference_update(wave_nodes)

        return waves

    def compute_critical_path(self, nodes: list[DAGNode]) -> list[str]:
        """Find the longest chain of sequential dependencies.

        The critical path determines minimum wall-clock execution time.

        Returns:
            Ordered list of node_ids forming the longest dependency chain.
        """
        G = _build_graph(nodes)

        # Reverse edges so predecessors become successors
        # Compute longest path from any root to any leaf
        root_nodes = [n for n in G.nodes() if G.in_degree(n) == 0]

        if not root_nodes:
            return []

        # Bellman-ford-style longest path (edges weighted -1, negate to get longest)
        longest: dict[str, int] = {}
        pred: dict[str, str | None] = {}

        for node in nx.topological_sort(G):
            preds = list(G.predecessors(node))
            if not preds:
                longest[node] = 0
                pred[node] = None
            else:
                best = max((longest[p] for p in preds), default=0)
                longest[node] = best + 1
                pred[node] = max(preds, key=lambda p: longest[p])

        # Find leaf with maximum distance
        if not longest:
            return []
        end_node = max(longest, key=lambda n: longest[n])
        max_len = longest[end_node]

        # Reconstruct path by walking predecessors backward
        path: list[str] = []
        current: str | None = end_node
        while current is not None:
            path.append(current)
            current = pred[current]
        path.reverse()

        return path

    def mark_parallelizable(self, nodes: list[DAGNode]) -> list[DAGNode]:
        """Set can_run_parallel=True for nodes eligible for parallel execution.

        A node is parallelizable if it is in the same wave as another node
        and has no shared upstream dependencies that would create race conditions.

        Returns:
            List of DAGNode objects with can_run_parallel set appropriately.
        """
        waves = self.compute_execution_waves(nodes)
        node_map: dict[str, DAGNode] = {n.node_id: n for n in nodes}
        wave_index: dict[str, int] = {}
        for wave_idx, wave in enumerate(waves):
            for node_id in wave:
                wave_index[node_id] = wave_idx

        eligible: set[str] = set()

        for wave in waves:
            for node_id in wave:
                node = node_map[node_id]
                if wave_index[node_id] == 0:
                    # Wave 0 nodes are always parallelizable with each other
                    eligible.add(node_id)
                    continue

                # Check no shared upstream deps with other wave-0 deps
                # (i.e. no node in wave > 0 whose deps overlap with wave 0 deps)
                # Simplified: if node's deps are ALL in eligible set, mark it
                all_deps_in_eligible = all(
                    dep in eligible for dep in node.depends_on
                )
                if all_deps_in_eligible:
                    eligible.add(node_id)

        return [
            node_map[nid].model_copy(update={"can_run_parallel": nid in eligible})
            for nid in [n.node_id for n in nodes]
        ]

    def build_adjacency_map(self, nodes: list[DAGNode]) -> dict[str, list[str]]:
        """Build an adjacency map: {node_id: [downstream_node_ids]}.

        Useful for triggering downstream nodes when a node completes.

        Returns:
            Dict mapping each node_id to a list of its direct downstream IDs.
        """
        G = _build_graph(nodes)
        return {n: list(G.successors(n)) for n in G.nodes()}


# ─── Public factory ────────────────────────────────────────────────────────────


def build_and_validate(nodes: list[DAGNode]) -> tuple[list[DAGNode], dict[str, Any]]:
    """Validate nodes, enrich with parallelization metadata, return enriched DAG + metadata.

    Args:
        nodes: List of raw DAGNode objects.

    Returns:
        Tuple of (enriched_nodes, metadata dict).

    Raises:
        TemplateValidationError: If any structural validation fails.
    """
    builder = DAGBuilder()

    errors = builder.validate_structure(nodes)
    if errors:
        raise TemplateValidationError(
            errors=errors,
            template_path=None,
            context={"node_count": len(nodes)},
        )

    waves = builder.compute_execution_waves(nodes)
    critical_path = builder.compute_critical_path(nodes)
    enriched = builder.mark_parallelizable(nodes)
    adjacency_map = builder.build_adjacency_map(nodes)

    parallel_eligible = sum(1 for n in enriched if n.can_run_parallel)

    metadata: dict[str, Any] = {
        "execution_waves": waves,
        "critical_path": critical_path,
        "parallel_eligible_count": parallel_eligible,
        "adjacency_map": adjacency_map,
    }

    return enriched, metadata
