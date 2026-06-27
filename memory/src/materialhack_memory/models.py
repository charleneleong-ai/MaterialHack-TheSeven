from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CandidateOrigin(str, Enum):
    CCDC_CSD = "ccdc_csd"
    DE_NOVO = "de_novo"
    DERIVED = "derived"
    HUMAN = "human"
    OTHER = "other"


class LoopStatus(str, Enum):
    ACTIVE = "active"
    AVAILABLE = "available"
    ABANDONED = "abandoned"
    REJECTED = "rejected"
    TERMINAL = "terminal"


class ChangeOperation(str, Enum):
    SUBSTITUTE = "substitute"
    INSERT = "insert"
    DELETE = "delete"
    STRUCTURAL_EDIT = "structural_edit"
    CONSTRAINT_EDIT = "constraint_edit"
    OTHER = "other"


class EvaluationKind(str, Enum):
    BOLTZ = "boltz"
    SCREENING = "screening"
    VERIFIER = "verifier"
    HUMAN_REVIEW = "human_review"
    OTHER = "other"


@dataclass(frozen=True)
class ArtifactRef:
    """Reference to a large artifact stored outside the memory row."""

    uri: str
    kind: str
    format: str | None = None
    sha256: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class MetricGoal:
    """Target score the agent should optimize toward."""

    name: str
    target: float
    comparator: str = "gte"
    weight: float = 1.0
    unit: str | None = None
    description: str | None = None

    def is_satisfied(self, value: float) -> bool:
        if self.comparator == "gte":
            return value >= self.target
        if self.comparator == "lte":
            return value <= self.target
        if self.comparator == "eq":
            return value == self.target
        raise ValueError(f"Unsupported comparator: {self.comparator}")


@dataclass(frozen=True)
class DesignObjective:
    """Run-level objective supplied before the optimization loop starts."""

    description: str
    goals: tuple[MetricGoal, ...] = ()
    max_loops: int | None = None
    custom: Mapping[str, JsonValue] = field(default_factory=dict)

    def goals_satisfied_by(self, metrics: Mapping[str, float]) -> bool:
        if not self.goals:
            return False
        return all(goal.name in metrics and goal.is_satisfied(metrics[goal.name]) for goal in self.goals)


@dataclass(frozen=True)
class ConditionSet:
    """Flexible condition payload until the team finalizes a stricter schema."""

    parameters: Mapping[str, JsonValue] = field(default_factory=dict)
    schema_version: str = "conditions.v0"

    @classmethod
    def common(
        cls,
        *,
        binding_target: str | None = None,
        ligand: str | None = None,
        ph: float | None = None,
        temperature_c: float | None = None,
        solvent: str | None = None,
        cofactors: tuple[str, ...] = (),
        expression_host: str | None = None,
        binding_site_constraints: Mapping[str, JsonValue] | None = None,
        stability_constraints: Mapping[str, JsonValue] | None = None,
        custom: Mapping[str, JsonValue] | None = None,
    ) -> "ConditionSet":
        parameters: dict[str, JsonValue] = {}
        optional_values: dict[str, JsonValue] = {
            "binding_target": binding_target,
            "ligand": ligand,
            "ph": ph,
            "temperature_c": temperature_c,
            "solvent": solvent,
            "expression_host": expression_host,
        }
        parameters.update({key: value for key, value in optional_values.items() if value is not None})
        if cofactors:
            parameters["cofactors"] = list(cofactors)
        if binding_site_constraints:
            parameters["binding_site_constraints"] = dict(binding_site_constraints)
        if stability_constraints:
            parameters["stability_constraints"] = dict(stability_constraints)
        if custom:
            parameters.update(custom)
        return cls(parameters=parameters)


@dataclass(frozen=True)
class ProteinCandidate:
    """Protein state at a single loop checkpoint."""

    sequence: str
    origin: CandidateOrigin = CandidateOrigin.DERIVED
    name: str | None = None
    structure_artifacts: tuple[ArtifactRef, ...] = ()
    boltz_artifacts: tuple[ArtifactRef, ...] = ()
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ProteinChange:
    """One machine-readable change plus its scientific rationale."""

    operation: ChangeOperation
    machine_diff: str
    rationale: str
    position: int | None = None
    from_residue: str | None = None
    to_residue: str | None = None
    expected_effect: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ChangeSet:
    """Exactly one proposed set of changes for a derived loop."""

    summary: str
    why: str
    changes: tuple[ProteinChange, ...]
    author: str = "agent"
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class MetricValue:
    name: str
    value: float
    unit: str | None = None
    higher_is_better: bool | None = None
    uncertainty: float | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationResult:
    """Boltz, screening, verifier, or human-review feedback for one loop."""

    kind: EvaluationKind
    evaluator_name: str
    evaluator_version: str | None = None
    metrics: tuple[MetricValue, ...] = ()
    passed: bool | None = None
    summary: str | None = None
    artifacts: tuple[ArtifactRef, ...] = ()
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

    def metric_map(self) -> dict[str, float]:
        return {metric.name: metric.value for metric in self.metrics}


@dataclass(frozen=True)
class LoopReflection:
    """Agent-readable reflection used to drive the next loop."""

    went_well: tuple[str, ...] = ()
    went_wrong: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
    notes: str | None = None


@dataclass(frozen=True)
class HumanInput:
    """Human annotation, rollback reason, or manual design instruction."""

    author: str
    note: str
    requested_changes: tuple[str, ...] = ()
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class LoopRecord:
    """Immutable protein checkpoint with mutable lifecycle status in the repository."""

    run_id: str
    loop_id: str
    index: int
    parent_loop_id: str | None
    candidate: ProteinCandidate
    conditions: ConditionSet
    change_set: ChangeSet | None = None
    evaluations: tuple[EvaluationResult, ...] = ()
    reflection: LoopReflection = field(default_factory=LoopReflection)
    human_inputs: tuple[HumanInput, ...] = ()
    status: LoopStatus = LoopStatus.AVAILABLE
    branch_label: str | None = None
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def latest_metric_map(self) -> dict[str, float]:
        metrics: dict[str, float] = {}
        for evaluation in self.evaluations:
            metrics.update(evaluation.metric_map())
        return metrics


@dataclass(frozen=True)
class DesignRun:
    run_id: str
    objective: DesignObjective
    root_loop_id: str
    active_loop_id: str
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentLoopContext:
    """Compact payload the optimizer agent reads before creating the next loop."""

    run_id: str
    active_loop_id: str
    parent_loop_id: str | None
    loop_index: int
    sequence: str
    conditions: ConditionSet
    objective: DesignObjective
    latest_metrics: Mapping[str, float]
    lineage_loop_ids: tuple[str, ...]
    previous_change_sets: tuple[ChangeSet, ...]
    evaluations: tuple[EvaluationResult, ...]
    reflection: LoopReflection
    human_inputs: tuple[HumanInput, ...]

    def to_agent_payload(self) -> dict[str, JsonValue]:
        return to_jsonable(self)


def to_jsonable(value: Any) -> JsonValue:
    """Convert memory dataclasses into values safe for JSON/TuringDB storage."""

    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: to_jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [to_jsonable(item) for item in value]
    return value
