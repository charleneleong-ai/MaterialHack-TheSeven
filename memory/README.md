# Memory System

This folder contains the memory abstraction for the agentic protein-design
system.

The first loop is the seed candidate from either CCDC/CSD-derived structure work
or de novo generation. Every later loop is one derived candidate with one
recorded change set, the rationale for that change, model outputs,
screening/verifier feedback, and the agent's reflection for the next loop.

## Design Intent

The memory should behave like an optimization ledger, not a chat log. Every loop
stores the scientific state and the decision state:

- protein sequence
- structure and Boltz artifact references
- condition payload
- machine-readable changes, such as `F5Y`
- natural-language rationale for those changes
- Boltz, screening, and verifier evaluations
- what went well
- what did not go well
- what the agent should do next
- human notes or manual instructions

Rollback does not delete loops. It moves the active head back to a selected loop
and marks the previous path as abandoned so a human or agent can branch from any
checkpoint later.

## Repository Layout

- `src/materialhack_memory/models.py` contains the typed memory records.
- `src/materialhack_memory/repository.py` contains the repository contract,
  in-memory implementation, rollback behavior, and future TuringDB adapter
  boundary.
- `tests/test_memory_repository.py` validates seed loops, derived loops,
  rollback, abandoned branches, and branching from an earlier loop.

## Loop Model

Each run stores:

- the run objective and target scores
- the active loop head
- the seed loop
- every derived loop and its parent loop
- abandoned branches kept after rollback

Each loop stores:

- `LoopRecord.candidate.sequence`
- `LoopRecord.candidate.structure_artifacts`
- `LoopRecord.candidate.boltz_artifacts`
- `LoopRecord.change_set`
- `LoopRecord.evaluations`
- `LoopRecord.reflection`
- `LoopRecord.human_inputs`
- `LoopRecord.status`

The sequence is intentionally easy to extract for Boltz or any other generation
step:

```python
sequence = repo.extract_sequence(run_id="run_123")
context = repo.get_active_context(run_id="run_123")
sequence_for_agent = context.sequence
```

## Minimal Example

```python
from materialhack_memory import (
    CandidateOrigin,
    ConditionSet,
    DesignObjective,
    InMemoryProteinMemoryRepository,
    ProteinCandidate,
)

repo = InMemoryProteinMemoryRepository()
run = repo.create_run(
    objective=DesignObjective(description="Optimize binder against target thresholds."),
    seed_candidate=ProteinCandidate(
        sequence="ACDEFGHIKLMNPQRSTVWY",
        origin=CandidateOrigin.CCDC_CSD,
    ),
    conditions=ConditionSet.common(
        binding_target="target-protein-x",
        ligand="ligand-a",
        ph=7.4,
        temperature_c=37,
        solvent="aqueous",
    ),
)

context = repo.get_active_context(run.run_id)
sequence_for_boltz_or_agent = context.sequence
```

## Fixed Loop Count vs Threshold Stop

The agent runner should sit on top of the memory repository.

The memory package already includes the state needed for both stop modes:

- `DesignObjective.max_loops`
- `DesignObjective.goals`
- `MetricGoal`
- `LoopRecord.latest_metric_map()`
- `DesignObjective.goals_satisfied_by(metrics)`
- `repo.get_active_context(run_id)`
- `repo.append_loop(...)`
- `repo.rollback_to_loop(...)`

The runner should support two execution modes:

- fixed loop count, for example run 10 more loops from `loop_4`
- threshold-driven, for example continue until `binding_score >= 0.85`

In practice, both should be used together. A threshold tells the agent what good
looks like, while a loop cap prevents an infinite run when the target is
unreachable or the verifier is noisy.

```python
objective = DesignObjective(
    description="Optimize binder under target conditions.",
    goals=(
        MetricGoal(name="binding_score", target=0.85, comparator="gte"),
        MetricGoal(name="instability_index", target=35.0, comparator="lte"),
    ),
    max_loops=20,
)
```

The controller flow should be:

```text
start from active loop
check current metrics against target thresholds
if targets are met, stop

while loop budget remains:
    read active loop context
    extract sequence, conditions, previous feedback, and human notes
    ask agent/model to propose one change set
    generate the next candidate sequence/structure
    run Boltz, screening, and verifier
    store candidate, changes, rationale, metrics, and reflection
    check new metrics against thresholds
    stop if thresholds are met
```

The next layer should probably expose an API like:

```python
class ProteinDesignLoopRunner:
    def run_until_stop(self, run_id: str):
        ...

    def run_for_loops(self, run_id: str, loop_count: int):
        ...

    def continue_from_loop(self, run_id: str, loop_id: str, loop_count: int | None = None):
        ...
```

Internally, the runner should compose separate components:

- `MemoryRepository` stores and retrieves loop state.
- `ChangePlanner` decides what change to make and why.
- `CandidateGenerator` applies or generates the next protein candidate.
- `ScreeningPipeline` runs screening models.
- `Verifier` scores whether the candidate meets target conditions.
- `ProteinDesignLoopRunner` orchestrates the full loop.

Rollback fits into this directly. If a human rolls back to `loop_3`, the
repository makes `loop_3` the active head. The next call to the runner reads
`loop_3` as the current context and branches from there, while the rejected later
loops remain stored as abandoned branches.

## Tests

Run from the repository root:

```bash
PYTHONPATH=memory/src python3 -m unittest discover -s memory/tests
```
