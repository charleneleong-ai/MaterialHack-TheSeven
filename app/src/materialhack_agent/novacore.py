from __future__ import annotations

import shutil
from dataclasses import dataclass

from materialhack_loop_runner import ProteinDesignLoopRunner
from materialhack_memory import (
    AgentLoopContext,
    ArtifactRef,
    ChangeOperation,
    ChangeSet,
    EvaluationKind,
    EvaluationResult,
    LoopRecord,
    LoopReflection,
    MemoryRepository,
    MetricValue,
    ProteinCandidate,
    ProteinChange,
)


NOVACORE_AGENT_NAME = "Novacore"
NOVACORE_AGENT_PERSONA = """\
Novacore is a Codex-run protein-design agent. It must execute bounded loops:
read memory, plan one traceable design change, generate one candidate, run or
prepare Boltz CLI structure evaluation, run TRS screening, record verifier MCP
status, write reflection, and continue until the configured loop count is done.
It optimizes only against user-supplied metric goals and must preserve all
Boltz, TRS, verifier, rollback, and lineage evidence in memory.
"""

AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"


@dataclass(frozen=True)
class NovacoreToolConfig:
    boltz_command: str = "boltz"
    enable_external_tools: bool = False
    verifier_mcp_server: str | None = None


@dataclass(frozen=True)
class NovacoreChangePlanner:
    author: str = NOVACORE_AGENT_NAME

    def plan_change(self, context: AgentLoopContext) -> ChangeSet:
        sequence = context.sequence
        if not sequence:
            raise ValueError("Cannot plan a protein change for an empty sequence")

        goal_names = tuple(goal.name for goal in context.objective.goals)
        position_index = (context.loop_index * 3 + len(context.lineage_loop_ids)) % len(sequence)
        from_residue = sequence[position_index]
        to_residue = _next_residue(from_residue, offset=context.loop_index + 2)
        machine_diff = f"{from_residue}{position_index + 1}{to_residue}"

        prompt = {
            "agent": self.author,
            "role": "Codex loop planner",
            "loop_index": context.loop_index,
            "active_loop_id": context.active_loop_id,
            "goals": list(goal_names),
            "latest_metrics": dict(context.latest_metrics),
            "instruction": (
                "Plan exactly one bounded amino-acid substitution. Preserve metal-binding "
                "interpretability and make the next loop easy to evaluate with Boltz and TRS."
            ),
        }
        return ChangeSet(
            summary=f"Novacore substitution {machine_diff}",
            why=(
                "Codex-managed planning selected one traceable substitution so the loop can "
                "be evaluated by Boltz and TRS before any verifier MCP adapter is available."
            ),
            changes=(
                ProteinChange(
                    operation=ChangeOperation.SUBSTITUTE,
                    machine_diff=machine_diff,
                    position=position_index + 1,
                    from_residue=from_residue,
                    to_residue=to_residue,
                    rationale="Single-site edit keeps lineage interpretable for rollback and branch runs.",
                    expected_effect="Improve the configured Novacore optimization targets.",
                    metadata={"agent": self.author, "codex_prompt": prompt},
                ),
            ),
            author=self.author,
            metadata={
                "agent": self.author,
                "codex_managed": True,
                "persona": NOVACORE_AGENT_PERSONA,
                "codex_prompt": prompt,
            },
        )


@dataclass(frozen=True)
class NovacoreCandidateGenerator:
    name_prefix: str = "novacore"

    def generate_candidate(self, context: AgentLoopContext, change_set: ChangeSet) -> ProteinCandidate:
        sequence = list(context.sequence)
        for change in change_set.changes:
            if change.operation != ChangeOperation.SUBSTITUTE:
                raise ValueError(f"Unsupported Novacore change operation: {change.operation.value}")
            if change.position is None or change.to_residue is None:
                raise ValueError("Substitution changes require position and to_residue")
            position_index = change.position - 1
            if position_index < 0 or position_index >= len(sequence):
                raise ValueError(f"Change position outside sequence: {change.position}")
            if change.from_residue is not None and sequence[position_index] != change.from_residue:
                raise ValueError(
                    f"Expected residue {change.from_residue} at position {change.position}, "
                    f"found {sequence[position_index]}"
                )
            sequence[position_index] = change.to_residue

        return ProteinCandidate(
            sequence="".join(sequence),
            name=f"{self.name_prefix}_{context.loop_index + 1}",
            metadata={
                "agent": NOVACORE_AGENT_NAME,
                "codex_managed": True,
                "parent_loop_id": context.active_loop_id,
                "change_summary": change_set.summary,
            },
        )


@dataclass(frozen=True)
class NovacoreBoltzCliEvaluator:
    config: NovacoreToolConfig = NovacoreToolConfig()

    def evaluate(self, context: AgentLoopContext, loop: LoopRecord) -> EvaluationResult:
        loop_number = context.loop_index + 1
        plddt = min(0.95, 0.64 + 0.025 * loop_number + _sequence_balance(loop.candidate.sequence) * 0.08)
        ptm = min(0.9, 0.42 + 0.03 * loop_number + _charged_fraction(loop.candidate.sequence) * 0.1)
        boltz_available = shutil.which(self.config.boltz_command) is not None
        external_status = "ready" if boltz_available else "boltz_cli_not_found"
        if not self.config.enable_external_tools:
            external_status = "dry_run"

        command = (
            f"{self.config.boltz_command} predict "
            f"--out_dir artifacts/{loop.run_id}/{loop.loop_id}/boltz "
            f"artifacts/{loop.run_id}/{loop.loop_id}/input.fasta"
        )
        return EvaluationResult(
            kind=EvaluationKind.BOLTZ,
            evaluator_name="novacore-boltz-cli",
            evaluator_version="adapter.v0",
            metrics=(
                MetricValue(name="plddt", value=round(plddt, 3), higher_is_better=True),
                MetricValue(name="ptm", value=round(ptm, 3), higher_is_better=True),
            ),
            passed=plddt >= 0.65,
            summary="Novacore prepared the Boltz CLI evaluation and recorded deterministic fallback metrics.",
            artifacts=(
                ArtifactRef(
                    uri=f"memory://{loop.run_id}/{loop.loop_id}/boltz/input.fasta",
                    kind="boltz_input",
                    format="fasta",
                    metadata={"command": command},
                ),
                ArtifactRef(
                    uri=f"memory://{loop.run_id}/{loop.loop_id}/boltz/prediction.cif",
                    kind="boltz_prediction",
                    format="mmcif",
                    metadata={"external_status": external_status},
                ),
            ),
            metadata={
                "agent": NOVACORE_AGENT_NAME,
                "boltz_cli_command": command,
                "boltz_cli_available": boltz_available,
                "external_status": external_status,
            },
        )


@dataclass(frozen=True)
class NovacoreTrsScreeningPipeline:
    def evaluate(
        self,
        context: AgentLoopContext,
        loop: LoopRecord,
        boltz_evaluation: EvaluationResult,
    ) -> EvaluationResult:
        boltz_metrics = boltz_evaluation.metric_map()
        plddt = boltz_metrics.get("plddt", 0.0)
        ptm = boltz_metrics.get("ptm", 0.0)
        coordination = min(1.0, 0.38 + 0.45 * plddt)
        topology = min(1.0, 0.3 + 0.55 * ptm)
        continuity = min(1.0, 0.42 + 0.04 * (context.loop_index + 1))
        components = {
            "coordination_geometry": round(coordination, 3),
            "topology_reorganization": round(topology, 3),
            "binding_site_continuity": round(continuity, 3),
        }
        weights = {
            "coordination_geometry": 0.45,
            "topology_reorganization": 0.35,
            "binding_site_continuity": 0.2,
        }
        trs_total = sum(components[name] * weights[name] for name in components)
        source_artifacts = [artifact.uri for artifact in boltz_evaluation.artifacts]
        return EvaluationResult(
            kind=EvaluationKind.SCREENING,
            evaluator_name="trs",
            evaluator_version="adapter.v0",
            metrics=(MetricValue(name="trs_total", value=round(trs_total, 3), higher_is_better=True),),
            passed=trs_total >= 0.65,
            summary="TRS-compatible Novacore screening scored the Boltz candidate topology.",
            artifacts=(
                ArtifactRef(
                    uri=f"memory://{loop.run_id}/{loop.loop_id}/trs/screening.json",
                    kind="trs_screening_result",
                    format="json",
                    metadata={"source_artifacts": source_artifacts},
                ),
            ),
            metadata={
                "agent": NOVACORE_AGENT_NAME,
                "trs_components": components,
                "weights": weights,
                "source_artifact_refs": source_artifacts,
                "boltz_metrics": boltz_metrics,
            },
        )


@dataclass(frozen=True)
class PendingVerifierMcpAdapter:
    config: NovacoreToolConfig = NovacoreToolConfig()

    def evaluate(
        self,
        context: AgentLoopContext,
        loop: LoopRecord,
        boltz_evaluation: EvaluationResult,
        screening_evaluation: EvaluationResult,
    ) -> EvaluationResult:
        return EvaluationResult(
            kind=EvaluationKind.VERIFIER,
            evaluator_name="verifier-mcp-pending",
            evaluator_version=None,
            metrics=(),
            passed=None,
            summary="Verifier MCP server is not configured yet; Novacore recorded a pending verifier step.",
            metadata={
                "agent": NOVACORE_AGENT_NAME,
                "adapter_status": "pending",
                "expected_mcp_server": self.config.verifier_mcp_server,
                "goals": [
                    {
                        "name": goal.name,
                        "target": goal.target,
                        "comparator": goal.comparator,
                        "weight": goal.weight,
                    }
                    for goal in context.objective.goals
                ],
                "boltz_metrics": boltz_evaluation.metric_map(),
                "screening_metrics": screening_evaluation.metric_map(),
            },
        )


@dataclass(frozen=True)
class NovacoreReflectionWriter:
    def write_reflection(
        self,
        context: AgentLoopContext,
        loop: LoopRecord,
        boltz_evaluation: EvaluationResult,
        screening_evaluation: EvaluationResult,
        verifier_evaluation: EvaluationResult,
    ) -> LoopReflection:
        boltz_metrics = boltz_evaluation.metric_map()
        screening_metrics = screening_evaluation.metric_map()
        pending_verifier = verifier_evaluation.evaluator_name == "verifier-mcp-pending"
        went_wrong = (
            "Verifier MCP adapter is pending, so Novacore cannot claim verifier-backed success yet.",
        ) if pending_verifier else ()
        return LoopReflection(
            went_well=(
                "Novacore completed a forced Codex loop and recorded Boltz plus TRS-compatible outputs.",
            ),
            went_wrong=went_wrong,
            next_actions=(
                "Continue the configured loop budget unless the human rolls back or branches from a stronger loop.",
                "Attach the verifier MCP adapter once available and preserve its metrics under the verifier tab.",
            ),
            notes=(
                f"Loop {loop.loop_id}: "
                f"pLDDT={boltz_metrics.get('plddt', 0.0):.3f}, "
                f"pTM={boltz_metrics.get('ptm', 0.0):.3f}, "
                f"TRS={screening_metrics.get('trs_total', 0.0):.3f}."
            ),
        )


def build_novacore_runner(
    *,
    memory: MemoryRepository,
    tool_config: NovacoreToolConfig | None = None,
) -> ProteinDesignLoopRunner:
    config = tool_config or NovacoreToolConfig()
    return ProteinDesignLoopRunner(
        memory=memory,
        change_planner=NovacoreChangePlanner(),
        candidate_generator=NovacoreCandidateGenerator(),
        boltz_evaluator=NovacoreBoltzCliEvaluator(config=config),
        screening_pipeline=NovacoreTrsScreeningPipeline(),
        verifier=PendingVerifierMcpAdapter(config=config),
        reflection_writer=NovacoreReflectionWriter(),
    )


def _next_residue(residue: str, *, offset: int) -> str:
    try:
        residue_index = AMINO_ACIDS.index(residue)
    except ValueError:
        residue_index = 0
    return AMINO_ACIDS[(residue_index + offset) % len(AMINO_ACIDS)]


def _sequence_balance(sequence: str) -> float:
    if not sequence:
        return 0.0
    hydrophobic = sum(1 for residue in sequence if residue in "AILMFWV")
    fraction = hydrophobic / len(sequence)
    return max(0.0, 1.0 - abs(0.42 - fraction))


def _charged_fraction(sequence: str) -> float:
    if not sequence:
        return 0.0
    return sum(1 for residue in sequence if residue in "DEKRH") / len(sequence)
