from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from materialhack_loop_runner import LoopRunnerResult
from materialhack_memory import (
    InMemoryProteinMemoryRepository,
    MemoryRepository,
    RunVisualizationSnapshot,
)

from materialhack_agent.novacore import build_novacore_runner
from materialhack_agent.seed_flow import SeedFlowConfig, SeedFlowResult, create_seeded_run


@dataclass(frozen=True)
class AgentAppResult:
    seed_flow: SeedFlowResult
    runner_result: LoopRunnerResult | None
    snapshot: RunVisualizationSnapshot

    @property
    def run_id(self) -> str:
        return self.seed_flow.run.run_id


@dataclass
class MaterialHackAgentApp:
    """Runnable Novacore composition of seed flow, durable memory, and loop runner."""

    memory: MemoryRepository | None = None

    def __post_init__(self) -> None:
        if self.memory is None:
            self.memory = InMemoryProteinMemoryRepository()

    def run(
        self,
        objective: str,
        *,
        seed_count: int = 5,
        loop_count: int = 2,
        target_score: float = 0.8,
        max_loops: int | None = None,
        rng_seed: int = 7,
    ) -> AgentAppResult:
        if loop_count < 0:
            raise ValueError("loop_count must be greater than or equal to zero")

        config = SeedFlowConfig(
            seed_count=seed_count,
            target_score=target_score,
            max_loops=max_loops if max_loops is not None else loop_count,
            rng_seed=rng_seed,
            ccdc_ligand_zip_path=str(Path(__file__).resolve().parents[3] / "ligands_10000.zip"),
        )
        seed_flow = create_seeded_run(self.memory, objective, config=config)

        runner_result: LoopRunnerResult | None = None
        if loop_count:
            runner = build_novacore_runner(memory=self.memory)
            runner_result = runner.run_for_loops(seed_flow.run.run_id, loop_count)

        snapshot = self.memory.get_run_visualization(seed_flow.run.run_id)
        return AgentAppResult(
            seed_flow=seed_flow,
            runner_result=runner_result,
            snapshot=snapshot,
        )
