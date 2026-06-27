from __future__ import annotations

from dataclasses import replace
from typing import Protocol
from uuid import uuid4

from materialhack_memory.models import (
    AgentLoopContext,
    ChangeSet,
    ConditionSet,
    DesignObjective,
    DesignRun,
    EvaluationResult,
    HumanInput,
    LoopRecord,
    LoopReflection,
    LoopStatus,
    ProteinCandidate,
)


class MemoryRepositoryError(RuntimeError):
    pass


class RunNotFound(MemoryRepositoryError):
    pass


class LoopNotFound(MemoryRepositoryError):
    pass


class InvalidLoopOperation(MemoryRepositoryError):
    pass


class MemoryRepository(Protocol):
    """Storage contract to implement with TuringDB later."""

    def create_run(
        self,
        *,
        objective: DesignObjective,
        seed_candidate: ProteinCandidate,
        conditions: ConditionSet,
        seed_evaluations: tuple[EvaluationResult, ...] = (),
        seed_reflection: LoopReflection | None = None,
        run_id: str | None = None,
        loop_id: str | None = None,
        metadata: dict | None = None,
    ) -> DesignRun:
        ...

    def append_loop(
        self,
        *,
        run_id: str,
        candidate: ProteinCandidate,
        change_set: ChangeSet,
        evaluations: tuple[EvaluationResult, ...] = (),
        reflection: LoopReflection | None = None,
        parent_loop_id: str | None = None,
        human_inputs: tuple[HumanInput, ...] = (),
        loop_id: str | None = None,
        branch_label: str | None = None,
        metadata: dict | None = None,
        make_active: bool = True,
    ) -> LoopRecord:
        ...

    def rollback_to_loop(self, *, run_id: str, loop_id: str, actor: str, reason: str) -> LoopRecord:
        ...

    def record_human_input(self, *, run_id: str, loop_id: str, human_input: HumanInput) -> LoopRecord:
        ...

    def get_active_context(self, run_id: str) -> AgentLoopContext:
        ...

    def extract_sequence(self, *, run_id: str, loop_id: str | None = None) -> str:
        ...


class InMemoryProteinMemoryRepository:
    """Reference implementation for tests and local agent-loop development."""

    def __init__(self) -> None:
        self._runs: dict[str, DesignRun] = {}
        self._loops: dict[str, dict[str, LoopRecord]] = {}

    def create_run(
        self,
        *,
        objective: DesignObjective,
        seed_candidate: ProteinCandidate,
        conditions: ConditionSet,
        seed_evaluations: tuple[EvaluationResult, ...] = (),
        seed_reflection: LoopReflection | None = None,
        run_id: str | None = None,
        loop_id: str | None = None,
        metadata: dict | None = None,
    ) -> DesignRun:
        run_id = run_id or self._new_id("run")
        loop_id = loop_id or self._new_id("loop")
        if run_id in self._runs:
            raise InvalidLoopOperation(f"Run already exists: {run_id}")

        seed_loop = LoopRecord(
            run_id=run_id,
            loop_id=loop_id,
            index=0,
            parent_loop_id=None,
            candidate=seed_candidate,
            conditions=conditions,
            evaluations=seed_evaluations,
            reflection=seed_reflection or LoopReflection(),
            status=LoopStatus.ACTIVE,
            metadata=metadata or {},
        )
        run = DesignRun(
            run_id=run_id,
            objective=objective,
            root_loop_id=loop_id,
            active_loop_id=loop_id,
            metadata=metadata or {},
        )
        self._runs[run_id] = run
        self._loops[run_id] = {loop_id: seed_loop}
        return run

    def append_loop(
        self,
        *,
        run_id: str,
        candidate: ProteinCandidate,
        change_set: ChangeSet,
        evaluations: tuple[EvaluationResult, ...] = (),
        reflection: LoopReflection | None = None,
        parent_loop_id: str | None = None,
        human_inputs: tuple[HumanInput, ...] = (),
        loop_id: str | None = None,
        branch_label: str | None = None,
        metadata: dict | None = None,
        make_active: bool = True,
    ) -> LoopRecord:
        run = self.get_run(run_id)
        parent_loop_id = parent_loop_id or run.active_loop_id
        parent = self.get_loop(run_id=run_id, loop_id=parent_loop_id)
        loop_id = loop_id or self._new_id("loop")
        if loop_id in self._loops[run_id]:
            raise InvalidLoopOperation(f"Loop already exists in run {run_id}: {loop_id}")

        loop = LoopRecord(
            run_id=run_id,
            loop_id=loop_id,
            index=parent.index + 1,
            parent_loop_id=parent_loop_id,
            candidate=candidate,
            conditions=parent.conditions,
            change_set=change_set,
            evaluations=evaluations,
            reflection=reflection or LoopReflection(),
            human_inputs=human_inputs,
            status=LoopStatus.AVAILABLE,
            branch_label=branch_label,
            metadata=metadata or {},
        )
        self._loops[run_id][loop_id] = loop

        if make_active:
            abandon_previous = parent_loop_id != run.active_loop_id
            self._activate_loop(run_id=run_id, loop_id=loop_id, abandon_previous=abandon_previous)
            return self.get_loop(run_id=run_id, loop_id=loop_id)
        return loop

    def rollback_to_loop(self, *, run_id: str, loop_id: str, actor: str, reason: str) -> LoopRecord:
        run = self.get_run(run_id)
        target = self.get_loop(run_id=run_id, loop_id=loop_id)
        old_active_id = run.active_loop_id

        if old_active_id != loop_id and self._is_ancestor(run_id, ancestor_id=loop_id, loop_id=old_active_id):
            for descendant_id in self._descendant_ids(run_id, loop_id):
                descendant = self._loops[run_id][descendant_id]
                if descendant.status not in {LoopStatus.REJECTED, LoopStatus.TERMINAL}:
                    self._loops[run_id][descendant_id] = replace(descendant, status=LoopStatus.ABANDONED)
        elif old_active_id != loop_id:
            old_active = self._loops[run_id][old_active_id]
            if old_active.status not in {LoopStatus.REJECTED, LoopStatus.TERMINAL}:
                self._loops[run_id][old_active_id] = replace(old_active, status=LoopStatus.ABANDONED)

        rollback_note = HumanInput(author=actor, note=f"Rollback selected this loop: {reason}")
        target = replace(target, human_inputs=target.human_inputs + (rollback_note,))
        self._loops[run_id][loop_id] = target
        self._activate_loop(run_id=run_id, loop_id=loop_id, abandon_previous=False)
        return self.get_loop(run_id=run_id, loop_id=loop_id)

    def record_human_input(self, *, run_id: str, loop_id: str, human_input: HumanInput) -> LoopRecord:
        loop = self.get_loop(run_id=run_id, loop_id=loop_id)
        updated = replace(loop, human_inputs=loop.human_inputs + (human_input,))
        self._loops[run_id][loop_id] = updated
        return updated

    def get_run(self, run_id: str) -> DesignRun:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise RunNotFound(run_id) from exc

    def get_loop(self, *, run_id: str, loop_id: str) -> LoopRecord:
        self.get_run(run_id)
        try:
            return self._loops[run_id][loop_id]
        except KeyError as exc:
            raise LoopNotFound(f"{run_id}:{loop_id}") from exc

    def list_loops(self, run_id: str) -> tuple[LoopRecord, ...]:
        self.get_run(run_id)
        return tuple(sorted(self._loops[run_id].values(), key=lambda loop: (loop.index, loop.created_at)))

    def get_lineage(self, *, run_id: str, loop_id: str) -> tuple[LoopRecord, ...]:
        lineage: list[LoopRecord] = []
        current = self.get_loop(run_id=run_id, loop_id=loop_id)
        while True:
            lineage.append(current)
            if current.parent_loop_id is None:
                break
            current = self.get_loop(run_id=run_id, loop_id=current.parent_loop_id)
        return tuple(reversed(lineage))

    def get_active_context(self, run_id: str) -> AgentLoopContext:
        run = self.get_run(run_id)
        active = self.get_loop(run_id=run_id, loop_id=run.active_loop_id)
        lineage = self.get_lineage(run_id=run_id, loop_id=active.loop_id)
        previous_change_sets = tuple(loop.change_set for loop in lineage if loop.change_set is not None)
        human_inputs: list[HumanInput] = []
        for loop in lineage:
            human_inputs.extend(loop.human_inputs)

        return AgentLoopContext(
            run_id=run_id,
            active_loop_id=active.loop_id,
            parent_loop_id=active.parent_loop_id,
            loop_index=active.index,
            sequence=active.candidate.sequence,
            conditions=active.conditions,
            objective=run.objective,
            latest_metrics=active.latest_metric_map(),
            lineage_loop_ids=tuple(loop.loop_id for loop in lineage),
            previous_change_sets=previous_change_sets,
            evaluations=active.evaluations,
            reflection=active.reflection,
            human_inputs=tuple(human_inputs),
        )

    def extract_sequence(self, *, run_id: str, loop_id: str | None = None) -> str:
        run = self.get_run(run_id)
        loop = self.get_loop(run_id=run_id, loop_id=loop_id or run.active_loop_id)
        return loop.candidate.sequence

    def _activate_loop(self, *, run_id: str, loop_id: str, abandon_previous: bool) -> None:
        run = self.get_run(run_id)
        current_active_id = run.active_loop_id
        if current_active_id != loop_id:
            current = self._loops[run_id][current_active_id]
            if current.status == LoopStatus.ACTIVE:
                self._loops[run_id][current_active_id] = replace(
                    current,
                    status=LoopStatus.ABANDONED if abandon_previous else LoopStatus.AVAILABLE,
                )

        target = self.get_loop(run_id=run_id, loop_id=loop_id)
        self._loops[run_id][loop_id] = replace(target, status=LoopStatus.ACTIVE)
        self._runs[run_id] = replace(run, active_loop_id=loop_id)

    def _descendant_ids(self, run_id: str, loop_id: str) -> tuple[str, ...]:
        descendants: list[str] = []
        children = [loop for loop in self._loops[run_id].values() if loop.parent_loop_id == loop_id]
        for child in children:
            descendants.append(child.loop_id)
            descendants.extend(self._descendant_ids(run_id, child.loop_id))
        return tuple(descendants)

    def _is_ancestor(self, run_id: str, *, ancestor_id: str, loop_id: str) -> bool:
        current = self.get_loop(run_id=run_id, loop_id=loop_id)
        while current.parent_loop_id is not None:
            if current.parent_loop_id == ancestor_id:
                return True
            current = self.get_loop(run_id=run_id, loop_id=current.parent_loop_id)
        return False

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"


class TuringDbMemoryRepository:
    """Placeholder adapter boundary for the future TuringDB-backed repository.

    The methods should persist the same records as append-only checkpoints/events in
    TuringDB. Keep rollback as a head-pointer update plus status event; do not delete
    historical loops.
    """

    def __init__(self, client: object) -> None:
        self.client = client

    def __getattr__(self, name: str) -> object:
        raise NotImplementedError(
            "TuringDB persistence is intentionally not implemented yet. "
            "Use InMemoryProteinMemoryRepository for the current abstraction and "
            "implement this adapter against the same MemoryRepository contract."
        )
