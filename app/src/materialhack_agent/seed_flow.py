from __future__ import annotations

import random
import re
from dataclasses import dataclass

from materialhack_memory import (
    ArtifactRef,
    CandidateOrigin,
    ConditionSet,
    DesignObjective,
    DesignRun,
    EvaluationKind,
    EvaluationResult,
    MemoryRepository,
    MetricGoal,
    MetricValue,
    SeedCandidate,
    SeedCandidatePool,
    SeedSelectionDecision,
)


AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"


@dataclass(frozen=True)
class ParsedObjective:
    target: str
    ph: float
    functions: tuple[str, ...]
    length: int


@dataclass(frozen=True)
class SeedFlowConfig:
    seed_count: int = 5
    target_score: float = 0.8
    max_loops: int | None = 2
    rng_seed: int = 7
    created_by: str = "WF"


@dataclass(frozen=True)
class SeedFlowResult:
    objective: DesignObjective
    conditions: ConditionSet
    pool: SeedCandidatePool
    decision: SeedSelectionDecision
    selected_seed: SeedCandidate
    run: DesignRun


def create_seeded_run(
    repository: MemoryRepository,
    objective_text: str,
    *,
    config: SeedFlowConfig | None = None,
) -> SeedFlowResult:
    """Run the WF-owned pre-loop handoff and create durable `loop_0`."""

    config = config or SeedFlowConfig()
    if config.seed_count <= 0:
        raise ValueError("seed_count must be greater than zero")

    parsed = parse_objective(objective_text)
    objective = to_design_objective(
        objective_text,
        parsed=parsed,
        target_score=config.target_score,
        max_loops=config.max_loops,
    )
    conditions = to_conditions(parsed)
    candidates = generate_seed_candidates(parsed, config=config)
    ranked_seed_candidate_ids = rank_seed_candidates(candidates)

    pool = repository.create_seed_pool(
        objective=objective,
        conditions=conditions,
        candidates=candidates,
        created_by=config.created_by,
        metadata={
            "source": "materialhack_agent.seed_flow",
            "stub": True,
            "rng_seed": config.rng_seed,
        },
    )
    selected_seed_candidate_id = ranked_seed_candidate_ids[0]
    decision = repository.record_seed_selection_decision(
        pool_id=pool.pool_id,
        selected_seed_candidate_id=selected_seed_candidate_id,
        rationale=(
            "Selected the top ranked WF pre-loop seed by verifier_score, then "
            "screen_score and plddt as deterministic tie breakers."
        ),
        selected_by=config.created_by,
        selection_method="stubbed_screening_verifier_rank",
        ranked_seed_candidate_ids=ranked_seed_candidate_ids,
        metadata={
            "stub": True,
            "ranking_metric_order": ["verifier_score", "screen_score", "plddt"],
        },
    )
    run = repository.create_run_from_seed_selection(decision_id=decision.decision_id)
    selected_seed = repository.get_seed_candidate(
        pool_id=pool.pool_id,
        seed_candidate_id=selected_seed_candidate_id,
    )

    return SeedFlowResult(
        objective=objective,
        conditions=conditions,
        pool=pool,
        decision=decision,
        selected_seed=selected_seed,
        run=run,
    )


def parse_objective(objective_text: str) -> ParsedObjective:
    text = objective_text.lower()
    ph_match = re.search(r"ph\s*([\d.]+)", text)
    ph = float(ph_match.group(1)) if ph_match else 7.0

    length_match = re.search(r"(\d+)\s*(?:aa|residues?|amino acids?)", text)
    length = int(length_match.group(1)) if length_match else 60

    target = _parse_target(text)
    functions = tuple(
        function
        for marker, function in _FUNCTION_KEYWORDS.items()
        if marker in text
    ) or ("bind",)

    return ParsedObjective(target=target, ph=ph, functions=functions, length=length)


def to_design_objective(
    objective_text: str,
    *,
    parsed: ParsedObjective,
    target_score: float,
    max_loops: int | None,
) -> DesignObjective:
    return DesignObjective(
        description=objective_text,
        goals=(
            MetricGoal(
                name="verifier_score",
                target=target_score,
                comparator="gte",
                description="High-fidelity verifier score for the active design loop.",
            ),
        ),
        max_loops=max_loops,
        custom={
            "target": parsed.target,
            "ph": parsed.ph,
            "functions": list(parsed.functions),
            "length": parsed.length,
        },
    )


def to_conditions(parsed: ParsedObjective) -> ConditionSet:
    return ConditionSet.common(
        binding_target=parsed.target,
        ph=parsed.ph,
        custom={
            "functions": list(parsed.functions),
            "requested_length": parsed.length,
        },
    )


def generate_seed_candidates(parsed: ParsedObjective, *, config: SeedFlowConfig) -> tuple[SeedCandidate, ...]:
    rng = random.Random(config.rng_seed)
    candidates: list[SeedCandidate] = []
    for index in range(config.seed_count):
        seed_id = f"seed_{index + 1:03d}"
        origin = CandidateOrigin.CCDC_CSD if index % 2 == 0 else CandidateOrigin.DE_NOVO
        length = max(20, parsed.length + rng.randint(-5, 5))
        sequence = _generate_sequence(rng, length)
        plddt = round(rng.uniform(0.55, 0.92), 3)
        ptm = round(rng.uniform(0.35, 0.88), 3)
        screen_score = round(0.55 * plddt + 0.45 * ptm, 3)
        verifier_score = round(min(0.95, 0.25 + 0.5 * screen_score + rng.uniform(0.0, 0.18)), 3)

        candidates.append(
            SeedCandidate(
                seed_candidate_id=seed_id,
                sequence=sequence,
                origin=origin,
                source_database="CCDC/CSD" if origin == CandidateOrigin.CCDC_CSD else None,
                source_id=f"CSD-STUB-{index + 1:04d}" if origin == CandidateOrigin.CCDC_CSD else None,
                name=f"{parsed.target}_seed_{index + 1}",
                structure_artifacts=(
                    ArtifactRef(
                        uri=f"memory://preloop/{seed_id}/structure.cif",
                        kind="candidate_structure",
                        format="mmcif",
                        metadata={"stub": True},
                    ),
                ),
                boltz_artifacts=(
                    ArtifactRef(
                        uri=f"memory://preloop/{seed_id}/boltz_metrics.json",
                        kind="boltz_metrics",
                        format="json",
                        metadata={"stub": True},
                    ),
                ),
                evaluations=(
                    EvaluationResult(
                        kind=EvaluationKind.BOLTZ,
                        evaluator_name="wf-preloop-boltz-stub",
                        evaluator_version="stub.v1",
                        metrics=(
                            MetricValue(name="plddt", value=plddt, higher_is_better=True),
                            MetricValue(name="ptm", value=ptm, higher_is_better=True),
                        ),
                        passed=plddt >= 0.55,
                        summary="Deterministic pre-loop Boltz placeholder; replace with real Boltz adapter.",
                        artifacts=(
                            ArtifactRef(
                                uri=f"memory://preloop/{seed_id}/boltz_result.json",
                                kind="boltz_result",
                                format="json",
                                metadata={"stub": True},
                            ),
                        ),
                        metadata={"stub": True},
                    ),
                    EvaluationResult(
                        kind=EvaluationKind.SCREENING,
                        evaluator_name="wf-preloop-screening-stub",
                        evaluator_version="stub.v1",
                        metrics=(MetricValue(name="screen_score", value=screen_score, higher_is_better=True),),
                        passed=screen_score >= 0.5,
                        summary="Deterministic seed screening placeholder.",
                        metadata={"stub": True},
                    ),
                    EvaluationResult(
                        kind=EvaluationKind.VERIFIER,
                        evaluator_name="wf-preloop-verifier-stub",
                        evaluator_version="stub.v1",
                        metrics=(MetricValue(name="verifier_score", value=verifier_score, higher_is_better=True),),
                        passed=False,
                        summary="Deterministic seed verifier placeholder.",
                        metadata={"stub": True},
                    ),
                ),
                metadata={
                    "target": parsed.target,
                    "ph": parsed.ph,
                    "functions": list(parsed.functions),
                    "stub": True,
                },
            )
        )
    return tuple(candidates)


def rank_seed_candidates(candidates: tuple[SeedCandidate, ...]) -> tuple[str, ...]:
    ranked = sorted(
        candidates,
        key=lambda candidate: (
            _metric(candidate, "verifier_score"),
            _metric(candidate, "screen_score"),
            _metric(candidate, "plddt"),
        ),
        reverse=True,
    )
    return tuple(candidate.seed_candidate_id for candidate in ranked)


_KNOWN_TARGETS = [
    "zn2+",
    "ca2+",
    "mg2+",
    "fe2+",
    "fe3+",
    "cu2+",
    "ni2+",
    "mn2+",
    "atp",
    "adp",
    "dna",
    "rna",
    "lipid",
    "collagen",
    "heparin",
]

_FUNCTION_KEYWORDS = {
    "bind": "bind",
    "polymeriz": "polymerize",
    "catalyz": "catalyze",
    "cleave": "cleave",
    "fold": "fold",
    "fluoresc": "fluoresce",
    "transport": "transport",
    "inhibit": "inhibit",
    "stabiliz": "stabilize",
    "dimeriz": "dimerize",
    "aggregat": "aggregate",
    "sens": "sense",
}


def _parse_target(text: str) -> str:
    target = next((item.upper() for item in _KNOWN_TARGETS if item in text), None)
    if target is not None:
        return target

    bind_match = re.search(r"binds?\s+(?:to\s+)?([a-z0-9+\-]+)", text)
    return bind_match.group(1).upper() if bind_match else "unknown"


def _generate_sequence(rng: random.Random, length: int) -> str:
    return "".join(rng.choice(AMINO_ACIDS) for _ in range(length))


def _metric(candidate: SeedCandidate, name: str) -> float:
    for evaluation in candidate.evaluations:
        metric_map = evaluation.metric_map()
        if name in metric_map:
            return metric_map[name]
    return 0.0

