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
- `tests/test_memory_repository.py` validates seed-selection handoff, seed
  loops, derived loops, rollback, abandoned branches, and branching from an
  earlier loop.

## Loop Model

Each run stores:

- the run objective and target scores
- the active loop head
- the seed loop
- the seed-selection decision, when the run starts from WF's pre-loop candidate
  ranking flow
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

## Loop Finalization Contract

Optimization loops are created as pending records. The agent or runner must
complete the memory record before the loop can become active.

Required order:

```text
read active AgentLoopContext
    -> propose exactly one ChangeSet
    -> append pending LoopRecord
    -> attach Boltz output
    -> attach screening result
    -> attach verifier result
    -> attach LoopReflection
    -> finalize_loop(...)
    -> only then continue
```

By default, `finalize_loop(...)` requires:

- candidate sequence
- parent loop id for non-seed loops
- change set
- change rationale
- Boltz evaluation or Boltz artifact reference
- screening evaluation
- verifier evaluation
- reflection
- next actions

The repository returns a `LoopCompletenessReport` from
`validate_loop_complete(...)`. `finalize_loop(...)` raises `LoopIncomplete` if
anything required is missing. Rollback cannot select a pending loop.

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

## Seed-Selection Handoff

The `memory` branch does not choose the starting seed. WF owns temporary
pre-loop sourcing, screening, verifying, ranking, and selection. Memory owns the
durable record of that decision and enough evidence to revisit alternate seeds
later.

The handoff flow is:

```text
WF temporary pre-loop flow
    -> SeedCandidatePool
    -> SeedSelectionDecision
    -> create_run_from_seed_selection(...)
    -> loop_0
```

The memory API stores:

- every seed candidate WF considered
- CCDC/CSD or de novo provenance
- structure and Boltz artifact references
- screening and verifier evaluations per seed
- selected seed candidate id
- ranking order supplied by WF
- selection rationale
- human override flag, when applicable

Example:

```python
from materialhack_memory import (
    CandidateOrigin,
    EvaluationKind,
    EvaluationResult,
    MetricValue,
    SeedCandidate,
)

pool = repo.create_seed_pool(
    objective=objective,
    conditions=conditions,
    candidates=(
        SeedCandidate(
            seed_candidate_id="seed_b",
            sequence="ACDEFGHIKLMNPQRSTVWY",
            origin=CandidateOrigin.CCDC_CSD,
            source_database="CCDC/CSD",
            source_id="CSD-0002",
            evaluations=(
                EvaluationResult(
                    kind=EvaluationKind.VERIFIER,
                    evaluator_name="wf-verifier",
                    metrics=(MetricValue(name="binding_score", value=0.79),),
                ),
            ),
        ),
    ),
)

decision = repo.record_seed_selection_decision(
    pool_id=pool.pool_id,
    selected_seed_candidate_id="seed_b",
    rationale="WF selected this seed because it had the best verifier profile.",
    selected_by="WF",
    ranked_seed_candidate_ids=("seed_b",),
)

run = repo.create_run_from_seed_selection(decision_id=decision.decision_id)
context = repo.get_active_context(run.run_id)
seed_rationale = context.seed_selection_decision.rationale
```

## TuringDB Storage Backend

`InMemoryProteinMemoryRepository` is the reference implementation for tests and
local development. `TuringDbMemoryRepository` uses the same contract and stores
each memory record as a JSON payload in a TuringDB graph.

Install the optional SDK dependency when using the TuringDB backend:

```bash
pip install -e "memory[turingdb]"
```

Example:

```python
from materialhack_memory import TuringDbMemoryRepository

repo = TuringDbMemoryRepository(
    graph_name="materialhack_memory",
    client_kwargs={
        # Pass the TuringDB SDK connection options for your environment here.
        # For example, embedded/local/server options from the TuringDB SDK.
    },
)
```

You can also pass an already-created TuringDB client:

```python
repo = TuringDbMemoryRepository(client=turing_client)
```

The adapter:

- creates or opens the configured graph
- cold-loads existing memory records on initialization
- writes seed pools, seed decisions, runs, loops, evaluations, reflections, and
  rollback status changes to TuringDB
- uses TuringDB changes with `COMMIT` and `CHANGE SUBMIT` for persisted writes
- keeps rollback semantic history by updating active-head/status records instead
  of deleting loops

## Frontend Visualization Contract

The memory package does not choose the frontend stack. It exposes JSON-ready
read models so a future frontend can show what the agent did and let humans
comment on any loop.

Use `get_run_visualization(...)` to render a run:

```python
snapshot = repo.get_run_visualization(run_id)
payload = snapshot.to_frontend_payload()
```

The snapshot includes:

- graph nodes for every loop
- graph edges from parent loop to child loop
- active/root loop ids
- loop status, branchability, branch labels, and sequence previews
- latest metrics, evaluation kinds, change summaries, and change diffs
- human comments and requested changes
- pending-loop completeness reports
- seed-selection rationale, when available

Use `add_loop_comment(...)` to attach human advice to a loop:

```python
repo.add_loop_comment(
    run_id=run_id,
    loop_id="loop_4",
    author="human",
    note="Continue from here but avoid shrinking the binding pocket.",
    requested_changes=("Preserve the loop_4 aromatic contact.",),
)
```

Use `get_loop_context(...)` when a human wants to branch from a specific loop:

```python
context = repo.get_loop_context(run_id=run_id, loop_id="loop_4")
```

That context includes the selected loop sequence, lineage, metrics, feedback,
and human advice. A runner can then create a new pending loop with
`append_loop(parent_loop_id="loop_4", ...)`.

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

The TuringDB unit tests use a fake client that exercises the SDK call shape
without requiring a running TuringDB instance.
