"""Models for SpecForge cloud-quality execution."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


QualityMode = Literal["standard", "enhanced", "cloud"]


class QualityConfig(BaseModel):
    """Template-level quality controls."""

    mode: QualityMode = "standard"
    use_memory: bool = True
    teacher_on_success: bool = False
    final_audit: bool = False
    max_revision_rounds: int = Field(default=0, ge=0, le=3)
    important_node_types: list[str] = Field(
        default_factory=lambda: ["deep_reason", "adversarial", "lookahead"]
    )
    important_node_ids: list[str] = Field(default_factory=list)
    min_quality_score: float = Field(default=0.78, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _normalize(self) -> "QualityConfig":
        return self.normalized_for_mode()

    def normalized_for_mode(self) -> "QualityConfig":
        """Return a copy with mode-derived switches applied."""
        if self.mode == "standard":
            self.teacher_on_success = False
            self.final_audit = False
            self.max_revision_rounds = 0
        elif self.mode == "enhanced":
            self.use_memory = True
            self.teacher_on_success = False
            self.final_audit = True
            self.max_revision_rounds = 0
        elif self.mode == "cloud":
            self.use_memory = True
            self.teacher_on_success = True
            self.final_audit = True
            self.max_revision_rounds = max(self.max_revision_rounds, 1)
        return self


class MemoryRecord(BaseModel):
    """One persistent quality memory item."""

    id: str
    template_id: str
    template_name: str | None = None
    node_id: str | None = None
    node_type: str | None = None
    run_id: str | None = None
    task_text: str
    input_hash: str
    record_type: Literal[
        "success", "failure", "teacher_critique", "final_output", "domain_insight"
    ]
    content: dict[str, Any]
    quality_score: float | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: str


class RetrievedMemory(BaseModel):
    """A memory plus retrieval score and explanation."""

    record: MemoryRecord
    similarity: float
    reason: str


class TeacherCritique(BaseModel):
    """Teacher model critique for a successful local output."""

    quality_score: float = Field(default=0.5, ge=0.0, le=1.0)
    missing_details: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    consistency_issues: list[str] = Field(default_factory=list)
    improvement_instructions: list[str] = Field(default_factory=list)
    should_revise: bool = False
    concise_summary: str = ""


class QualityRevisionResult(BaseModel):
    """Result of optional teacher-guided local revision."""

    used_revision: bool
    original_output: str
    revised_output: str | None = None
    critique: TeacherCritique | None = None
    quality_score: float | None = None
    reason: str


class FinalAuditResult(BaseModel):
    """Result of final cross-node audit and optional rewrite."""

    audited_output: dict[str, Any]
    used_audit_rewrite: bool
    audit_notes: list[str] = Field(default_factory=list)
    quality_score: float | None = None
