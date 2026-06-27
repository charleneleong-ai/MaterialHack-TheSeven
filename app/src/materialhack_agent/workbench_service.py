from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from materialhack_loop_runner import LoopRunnerResult
from materialhack_memory import CandidateOrigin, LoopRecord, MemoryRepository, MetricGoal, to_jsonable

from materialhack_agent.novacore import NOVACORE_AGENT_NAME, build_novacore_runner
from materialhack_agent.observable_memory import ObservableInMemoryProteinMemoryRepository
from materialhack_agent.seed_flow import (
    ParsedObjective,
    SeedFlowConfig,
    create_seeded_run,
    parse_objective,
)
from materialhack_agent.workbench_events import EventHub, utc_now_iso


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class WorkbenchJob:
    job_id: str
    run_id: str
    action: str
    status: JobState = JobState.QUEUED
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    result: dict | None = None

    def to_payload(self) -> dict:
        return to_jsonable(self)


@dataclass(frozen=True)
class ObjectiveParameters:
    target: str
    ph: float
    functions: tuple[str, ...]
    length: int
    seed_count: int = 5
    seed_sources: tuple[str, ...] = ("ccdc_csd", "de_novo")
    target_score: float = 0.8
    loop_count: int = 2
    optimization_targets: tuple[MetricGoal, ...] = (
        MetricGoal(
            name="trs_total",
            target=0.8,
            comparator="gte",
            weight=1.0,
            description="TRS total screening score.",
        ),
        MetricGoal(
            name="plddt",
            target=0.7,
            comparator="gte",
            weight=0.5,
            description="Boltz confidence score.",
        ),
    )


@dataclass
class WorkbenchService:
    event_hub: EventHub = field(default_factory=EventHub)

    def __post_init__(self) -> None:
        self.memory: MemoryRepository = ObservableInMemoryProteinMemoryRepository(self.event_hub)
        self._jobs: dict[str, WorkbenchJob] = {}
        self._lock = threading.RLock()

    def parse_objective_parameters(self, objective: str) -> ObjectiveParameters:
        parsed = parse_objective(objective)
        return ObjectiveParameters(
            target=parsed.target,
            ph=parsed.ph,
            functions=parsed.functions,
            length=parsed.length,
        )

    def create_run(
        self,
        *,
        objective: str,
        target: str,
        ph: float,
        functions: Iterable[str],
        length: int,
        seed_count: int,
        seed_sources: Iterable[str],
        target_score: float,
        loop_count: int,
        optimization_targets: Iterable[MetricGoal] | None = None,
        run_mode: str = "seed_and_loop",
        rng_seed: int = 7,
    ) -> tuple[str, str]:
        if loop_count < 0:
            raise ValueError("loop_count must be greater than or equal to zero")
        if run_mode not in {"seed_and_loop", "seed_only"}:
            raise ValueError("run_mode must be seed_and_loop or seed_only")

        requested_loop_count = loop_count if run_mode == "seed_and_loop" else 0
        goals = tuple(optimization_targets or ()) or self._default_optimization_targets(target_score)

        parsed = ParsedObjective(
            target=target,
            ph=ph,
            functions=tuple(function for function in functions if function),
            length=length,
        )
        config = SeedFlowConfig(
            seed_count=seed_count,
            target_score=target_score,
            max_loops=requested_loop_count,
            rng_seed=rng_seed,
            seed_sources=self._candidate_origins(seed_sources),
            optimization_goals=goals,
            ccdc_ligand_zip_path=str(self._ligand_archive_path()),
        )
        seed_flow = create_seeded_run(self.memory, objective, config=config, parsed=parsed)
        run_id = seed_flow.run.run_id
        job = self._create_job(run_id=run_id, action="create_run")

        self.event_hub.publish(
            "run_started",
            run_id=run_id,
            job_id=job.job_id,
            loop_id=seed_flow.run.root_loop_id,
            data={
                "objective": objective,
                "seed_pool_id": seed_flow.pool.pool_id,
                "selected_seed_candidate_id": seed_flow.selected_seed.seed_candidate_id,
                "requested_loops": requested_loop_count,
                "run_mode": run_mode,
                "agent": NOVACORE_AGENT_NAME,
                "optimization_targets": goals,
            },
        )
        self.event_hub.publish(
            "loop_finalized",
            run_id=run_id,
            job_id=job.job_id,
            loop_id=seed_flow.run.root_loop_id,
            data={
                "status": "active",
                "index": 0,
                "latest_metrics": self.memory.get_loop(
                    run_id=run_id,
                    loop_id=seed_flow.run.root_loop_id,
                ).latest_metric_map(),
            },
        )
        self._start_loop_job(job, loop_count=requested_loop_count, start_loop_id=None)
        return run_id, job.job_id

    def run_loops(self, *, run_id: str, loop_count: int, start_loop_id: str | None = None) -> str:
        if loop_count < 0:
            raise ValueError("loop_count must be greater than or equal to zero")
        self.memory.get_run(run_id)
        if start_loop_id is not None:
            self.memory.get_loop(run_id=run_id, loop_id=start_loop_id)
        job = self._create_job(run_id=run_id, action="run_loops")
        self.event_hub.publish(
            "run_started",
            run_id=run_id,
            job_id=job.job_id,
            loop_id=start_loop_id,
            data={"requested_loops": loop_count, "start_loop_id": start_loop_id},
        )
        self._start_loop_job(job, loop_count=loop_count, start_loop_id=start_loop_id)
        return job.job_id

    def rollback(self, *, run_id: str, loop_id: str, actor: str, reason: str) -> LoopRecord:
        return self.memory.rollback_to_loop(run_id=run_id, loop_id=loop_id, actor=actor, reason=reason)

    def get_job(self, job_id: str) -> WorkbenchJob:
        with self._lock:
            return self._jobs[job_id]

    def list_jobs(self) -> tuple[WorkbenchJob, ...]:
        with self._lock:
            return tuple(self._jobs.values())

    def _create_job(self, *, run_id: str, action: str) -> WorkbenchJob:
        job = WorkbenchJob(job_id=f"job_{uuid4().hex}", run_id=run_id, action=action)
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def _start_loop_job(self, job: WorkbenchJob, *, loop_count: int, start_loop_id: str | None) -> None:
        thread = threading.Thread(
            target=self._run_loop_job,
            args=(job.job_id, loop_count, start_loop_id),
            daemon=True,
        )
        thread.start()

    def _run_loop_job(self, job_id: str, loop_count: int, start_loop_id: str | None) -> None:
        job = self.get_job(job_id)
        self._mark_job(job_id, status=JobState.RUNNING, started_at=utc_now_iso())
        try:
            result: LoopRunnerResult | None = None
            if loop_count > 0:
                runner = build_novacore_runner(memory=self.memory)
                if start_loop_id:
                    result = runner.continue_from_loop(job.run_id, start_loop_id, loop_count=loop_count)
                else:
                    result = runner.run_for_loops(job.run_id, loop_count)
            result_payload = result.__dict__ if result is not None else {"loops_completed": 0}
            self._mark_job(
                job_id,
                status=JobState.SUCCEEDED,
                completed_at=utc_now_iso(),
                result=to_jsonable(result_payload),
            )
            self.event_hub.publish(
                "run_finished",
                run_id=job.run_id,
                job_id=job_id,
                data={"result": result_payload},
            )
        except Exception as exc:
            self._mark_job(
                job_id,
                status=JobState.FAILED,
                completed_at=utc_now_iso(),
                error=str(exc),
            )
            self.event_hub.publish(
                "run_failed",
                run_id=job.run_id,
                job_id=job_id,
                data={"error": str(exc), "error_type": type(exc).__name__},
            )

    def _mark_job(self, job_id: str, **updates) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in updates.items():
                setattr(job, key, value)

    @staticmethod
    def _candidate_origins(seed_sources: Iterable[str]) -> tuple[CandidateOrigin, ...]:
        mapping = {
            "ccdc_csd": CandidateOrigin.CCDC_CSD,
            "de_novo": CandidateOrigin.DE_NOVO,
        }
        origins = tuple(mapping[source] for source in seed_sources if source in mapping)
        if not origins:
            raise ValueError("seed_sources must include ccdc_csd, de_novo, or both")
        return origins

    @staticmethod
    def _default_optimization_targets(target_score: float) -> tuple[MetricGoal, ...]:
        return (
            MetricGoal(
                name="trs_total",
                target=target_score,
                comparator="gte",
                weight=1.0,
                description="TRS total screening score.",
            ),
            MetricGoal(
                name="plddt",
                target=0.7,
                comparator="gte",
                weight=0.5,
                description="Boltz confidence score.",
            ),
        )

    @staticmethod
    def _ligand_archive_path() -> Path:
        return Path(__file__).resolve().parents[3] / "ligands_10000.zip"
