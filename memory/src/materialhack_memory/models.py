from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from types import UnionType
from typing import Any, Mapping, Union, get_args, get_origin, get_type_hints


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
    PENDING = "pending"
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
class SeedCandidate:
    """Pre-loop seed candidate handed over by WF's temporary selection flow."""

    seed_candidate_id: str
    sequence: str
    origin: CandidateOrigin
    source_database: str | None = None
    source_id: str | None = None
    name: str | None = None
    structure_artifacts: tuple[ArtifactRef, ...] = ()
    boltz_artifacts: tuple[ArtifactRef, ...] = ()
    evaluations: tuple[EvaluationResult, ...] = ()
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_protein_candidate(self) -> ProteinCandidate:
        metadata = {
            **dict(self.metadata),
            "seed_candidate_id": self.seed_candidate_id,
        }
        if self.source_database is not None:
            metadata["seed_source_database"] = self.source_database
        if self.source_id is not None:
            metadata["seed_source_id"] = self.source_id
        return ProteinCandidate(
            sequence=self.sequence,
            origin=self.origin,
            name=self.name,
            structure_artifacts=self.structure_artifacts,
            boltz_artifacts=self.boltz_artifacts,
            metadata=metadata,
        )


@dataclass(frozen=True)
class SeedCandidatePool:
    """Durable record of pre-loop seed candidates considered by WF."""

    pool_id: str
    objective: DesignObjective
    conditions: ConditionSet
    candidates: tuple[SeedCandidate, ...] = ()
    created_by: str = "WF"
    created_at: str = field(default_factory=utc_now_iso)
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class SeedSelectionDecision:
    """WF's selected seed and rationale, persisted before creating loop_0."""

    decision_id: str
    pool_id: str
    selected_seed_candidate_id: str
    rationale: str
    selected_by: str = "WF"
    selection_method: str = "screening_verifier_rank"
    ranked_seed_candidate_ids: tuple[str, ...] = ()
    human_override: bool = False
    created_at: str = field(default_factory=utc_now_iso)
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
class LoopCompletenessRequirements:
    """Required memory fields before an optimization loop can be finalized."""

    require_change_set: bool = True
    require_change_rationale: bool = True
    require_boltz: bool = True
    require_screening: bool = True
    require_verifier: bool = True
    require_reflection: bool = True
    require_next_actions: bool = True

    @classmethod
    def optimization_loop(cls) -> "LoopCompletenessRequirements":
        return cls()

    @classmethod
    def seed_loop(cls) -> "LoopCompletenessRequirements":
        return cls(require_change_set=False, require_change_rationale=False)


@dataclass(frozen=True)
class LoopCompletenessReport:
    loop_id: str
    is_complete: bool
    missing_requirements: tuple[str, ...] = ()


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
    seed_selection_decision: SeedSelectionDecision | None = None
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
    seed_selection_decision: SeedSelectionDecision | None = None

    def to_agent_payload(self) -> dict[str, JsonValue]:
        return to_jsonable(self)


@dataclass(frozen=True)
class LoopGraphEdge:
    parent_loop_id: str
    child_loop_id: str


@dataclass(frozen=True)
class LoopGraphNode:
    """Compact loop summary for graph/timeline visualization."""

    loop_id: str
    parent_loop_id: str | None
    index: int
    status: LoopStatus
    is_active: bool
    can_branch_from: bool
    branch_label: str | None
    sequence_length: int
    sequence_preview: str
    change_summary: str | None
    change_rationale: str | None
    change_diffs: tuple[str, ...]
    latest_metrics: Mapping[str, float]
    evaluation_kinds: tuple[EvaluationKind, ...]
    human_input_count: int
    human_inputs: tuple[HumanInput, ...]
    reflection: LoopReflection
    completeness: LoopCompletenessReport | None
    created_at: str


@dataclass(frozen=True)
class RunVisualizationSnapshot:
    """Frontend-ready graph snapshot of a design run."""

    run_id: str
    root_loop_id: str
    active_loop_id: str
    objective: DesignObjective
    conditions: ConditionSet
    nodes: tuple[LoopGraphNode, ...]
    edges: tuple[LoopGraphEdge, ...]
    seed_selection_decision: SeedSelectionDecision | None = None
    created_at: str = field(default_factory=utc_now_iso)

    def to_frontend_payload(self) -> dict[str, JsonValue]:
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


def from_jsonable(cls: type[Any], value: JsonValue) -> Any:
    """Rebuild a memory dataclass from JSON/TuringDB storage values."""

    return _decode_jsonable(cls, value)


def _decode_jsonable(annotation: Any, value: Any) -> Any:
    if value is None:
        return None

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin in {Union, UnionType}:
        non_none_args = [item for item in args if item is not type(None)]
        last_error: Exception | None = None
        for item in non_none_args:
            try:
                return _decode_jsonable(item, value)
            except (TypeError, ValueError) as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        return value

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation(value)

    if isinstance(annotation, type) and is_dataclass(annotation):
        if not isinstance(value, Mapping):
            raise TypeError(f"Expected mapping for {annotation.__name__}")
        type_hints = get_type_hints(annotation)
        decoded = {}
        for item in fields(annotation):
            if item.name in value:
                decoded[item.name] = _decode_jsonable(type_hints[item.name], value[item.name])
        return annotation(**decoded)

    if origin is tuple:
        item_type = args[0] if args else Any
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode_jsonable(item_type, item) for item in value)
        return tuple(_decode_jsonable(item_type, item) for item_type, item in zip(args, value))

    if origin is list:
        item_type = args[0] if args else Any
        return [_decode_jsonable(item_type, item) for item in value]

    if origin is dict or origin is Mapping:
        return dict(value)

    if annotation in {str, int, float, bool}:
        return annotation(value)

    return value
