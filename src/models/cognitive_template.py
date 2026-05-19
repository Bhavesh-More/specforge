"""Core data models for SpecForge Cognitive Templates (.ct.json)."""

import enum
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import networkx as nx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from src.core.constants import TEMPLATE_SCHEMA_VERSION
from src.core.exceptions import TemplateValidationError


# ─── Enums ────────────────────────────────────────────────────────────────────


class NodeType(str, enum.Enum):
    """Classification of DAG node types."""

    STANDARD = "standard"
    SYMBOLIC = "symbolic"
    ADVERSARIAL = "adversarial"
    LOOKAHEAD = "lookahead"
    PARALLEL = "parallel"


class ExecutionTier(str, enum.Enum):
    """Execution depth tier assigned per node."""

    FAST = "fast"
    REPAIR = "repair"
    DEEP = "deep"


# ─── Pydantic Models ──────────────────────────────────────────────────────────


class FocusPrompt(BaseModel):
    """Prompt configuration for a specialist LLM node.

    Attributes:
        system_prompt: The specialist identity prompt injected as system role.
        user_template: User prompt template with ``{variable}`` interpolation.
        output_schema: JSON Schema dict for validating the node's raw output.
        required_variables: List of variable names that must exist in context.
        max_tokens: Hard cap on generation tokens (default 512).
        temperature: Sampling temperature (default 0.3).
    """

    model_config = ConfigDict(extra="forbid")

    system_prompt: str = Field(..., min_length=1)
    user_template: str = Field(..., min_length=1)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    required_variables: list[str] = Field(default_factory=list)
    max_tokens: int = Field(default=512, ge=1, le=32768)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)


class BentoBoxConfig(BaseModel):
    """Bento Box context assembly configuration for a node.

    Attributes:
        rule_files: List of .md rule file base names to inject (no path prefix).
        follow_links: Whether to follow [[wiki-links]] when assembling context.
        max_depth: Max wiki-link traversal depth (default 2).
        token_budget: Max tokens for assembled context (default 1500).
        pressure_annealing: Optional SPA (Self-Paced Annealing) config dict with warn_threshold, inject_threshold, etc.
    """

    model_config = ConfigDict(extra="forbid")

    rule_files: list[str] = Field(default_factory=list)
    follow_links: bool = True
    max_depth: int = Field(default=2, ge=0, le=10)
    token_budget: int = Field(default=1500, ge=128, le=128000)
    pressure_annealing: dict[str, Any] | None = None


class DAGNode(BaseModel):
    """A single executable node within a Cognitive Template DAG.

    Attributes:
        node_id: Unique identifier (lowercase alphanumeric + underscores, 3-50 chars).
        name: Human-readable display name.
        description: Description of what this node does.
        node_type: Classification of the node type (default STANDARD).
        focus_prompt: Prompt configuration for this node.
        bento_config: Bento Box context assembly config.
        depends_on: List of node_ids this node waits for before running.
        can_run_parallel: True if this node has no sequential dependencies.
        max_retries: Max retry attempts on failure (default 3).
        symbolic_tool: MCP tool name, required for SYMBOLIC nodes only.
        output_key: Key name for storing this node's result in global state dict.
    """

    model_config = ConfigDict(extra="forbid")

    node_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,48}[a-z0-9]$|^[a-z]$")]
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    node_type: NodeType = NodeType.STANDARD
    focus_prompt: FocusPrompt = Field(default_factory=FocusPrompt)
    bento_config: BentoBoxConfig = Field(default_factory=BentoBoxConfig)
    depends_on: list[str] = Field(default_factory=list)
    can_run_parallel: bool = False
    max_retries: int = Field(default=3, ge=0, le=10)
    symbolic_tool: str | None = None
    output_key: str = Field(..., min_length=1)

    @field_validator("node_id")
    @classmethod
    def _validate_node_id_chars(cls, v: str) -> str:
        """Reject uppercase, dots, hyphens, and other non-alphanumeric symbols."""
        if not re.match(r"^[a-z][a-z0-9_]{1,48}[a-z0-9]$|^[a-z]$", v):
            raise ValueError(
                "node_id must be lowercase alphanumeric/underscores, "
                "3-50 chars, starts with letter"
            )
        return v

    @model_validator(mode="after")
    def _validate_symbolic_has_tool(self) -> "DAGNode":
        """SYMBOLIC nodes must declare a symbolic_tool."""
        if self.node_type == NodeType.SYMBOLIC and not self.symbolic_tool:
            raise ValueError(
                f"Node '{self.node_id}' is SYMBOLIC but has no symbolic_tool"
            )
        return self


class CognitiveTemplate(BaseModel):
    """A complete cognitive template describing a reasoning pipeline as a DAG.

    Attributes:
        template_id: Stable UUID4 identifier for this template.
        name: Human-readable name.
        description: Brief description of what this template automates.
        version: Semver version string (validated).
        schema_version: Must match TEMPLATE_SCHEMA_VERSION constant.
        nodes: Ordered list of DAG nodes (minimum 1).
        created_at: UTC timestamp of creation.
        updated_at: UTC timestamp of last modification.
        tags: Arbitrary string tags for filtering/searching.
        author: Author identifier (default 'anonymous').
        result_weaver: Optional result template for final output formatting.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        json_encoders={datetime: lambda v: v.isoformat()},
    )

    template_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    version: str = "1.0.0"
    schema_version: str = TEMPLATE_SCHEMA_VERSION
    nodes: list[DAGNode] = Field(..., min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tags: list[str] = Field(default_factory=list)
    author: str = "anonymous"
    result_weaver: dict[str, Any] | None = None

    @field_validator("version")
    @classmethod
    def _validate_semver(cls, v: str) -> str:
        """Ensure version is valid semver (major.minor.patch)."""
        if not re.match(r"^\d+\.\d+\.\d+$", v):
            raise ValueError("version must be valid semver (e.g. '1.0.0')")
        return v

    @model_validator(mode="after")
    def _validate_dag_structure(self) -> "CognitiveTemplate":
        """Validate DAG: no duplicate IDs, no dangling deps, no cycles."""
        errors: list[str] = []

        # a) No duplicate node IDs
        node_ids = [n.node_id for n in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            dupes = set(id for id in node_ids if node_ids.count(id) > 1)
            errors.append(f"Duplicate node IDs: {sorted(dupes)}")

        # b) All depends_on references must exist
        all_ids_set = set(node_ids)
        for node in self.nodes:
            for dep in node.depends_on:
                if dep not in all_ids_set:
                    errors.append(
                        f"Node '{node.node_id}' depends on unknown node '{dep}'"
                    )

        # c) Cycle detection via NetworkX
        G = nx.DiGraph()
        for node in self.nodes:
            G.add_node(node.node_id)
        for node in self.nodes:
            for dep in node.depends_on:
                G.add_edge(dep, node.node_id)

        if not nx.is_directed_acyclic_graph(G):
            cycles = list(nx.simple_cycles(G))
            errors.append(f"Cycle detected in DAG: {cycles}")

        if errors:
            raise TemplateValidationError(
                errors=errors,
                template_path=None,
                context={"template_id": self.template_id},
            )

        return self

    # ─── Execution order (topological waves) ──────────────────────────────────

    def get_execution_order(self) -> list[list[str]]:
        """Return nodes grouped into execution waves (topological sort).

        Wave 0: nodes with no dependencies (all can run in parallel).
        Wave 1: nodes whose dependencies are fully contained in wave 0.
        Wave 2: nodes whose dependencies are fully contained in prior waves.
        And so on until all nodes are assigned.

        Returns:
            List of waves, each wave is a list of node_id strings.
        """
        G = nx.DiGraph()
        for node in self.nodes:
            G.add_node(node.node_id)
        for node in self.nodes:
            for dep in node.depends_on:
                G.add_edge(dep, node.node_id)

        waves: list[list[str]] = []
        remaining = set(G.nodes())
        assigned: set[str] = set()

        while remaining:
            # Find all nodes whose dependencies are all in `assigned`
            wave_nodes = [
                node_id
                for node_id in remaining
                if all(dep in assigned for dep in G.predecessors(node_id))
            ]

            if not wave_nodes:
                # Should not happen if DAG is valid; guard against infinite loop
                raise TemplateValidationError(
                    errors=[f"Could not assign remaining nodes to waves: {remaining}"],
                    template_path=None,
                    context={"template_id": self.template_id},
                )

            waves.append(sorted(wave_nodes))
            assigned.update(wave_nodes)
            remaining.difference_update(wave_nodes)

        return waves

    # ─── Serialization ────────────────────────────────────────────────────────

    @classmethod
    def load_from_file(cls, path: Path) -> "CognitiveTemplate":
        """Load a CognitiveTemplate from a .ct.json file on disk.

        Args:
            path: Path to the .ct.json file.

        Returns:
            A CognitiveTemplate instance parsed from the file.

        Raises:
            TemplateNotFoundError: File does not exist.
            TemplateValidationError: File is valid JSON but fails schema validation.
        """
        if not path.exists():
            from src.core.exceptions import TemplateNotFoundError

            raise TemplateNotFoundError(
                template_path=str(path),
                context={"operation": "load_from_file"},
            )

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise TemplateValidationError(
                errors=[f"Invalid JSON: {exc.msg} at line {exc.lineno}"],
                template_path=str(path),
                context={"operation": "load_from_file"},
            ) from exc

        try:
            return cls.model_validate(raw)
        except Exception as exc:
            raise TemplateValidationError(
                errors=[str(exc)],
                template_path=str(path),
                context={"operation": "load_from_file"},
            ) from exc

    def save_to_file(self, path: Path) -> None:
        """Serialize this template to a .ct.json file.

        Args:
            path: Destination path (including filename).
        """
        path.write_text(
            self.model_dump_json(indent=2, mode="json"),
            encoding="utf-8",
        )
