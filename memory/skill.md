# Memory Skill

This file defines how the protein-design agent must use the memory system.
It is a repo-agent protocol, not a Codex skill.

The agent must treat memory as a required workflow gate. It may not advance to a
new optimization loop, mark work complete, or branch from a loop unless the
memory repository has the required records for that state.

## Repository

Use the configured `MemoryRepository` implementation for the runtime:

- Use `TuringDbMemoryRepository` for durable runs.
- Use `InMemoryProteinMemoryRepository` only for local tests, demos, or
  disconnected development.

Never bypass the repository by writing directly to files, process state, or
frontend-only state.

## Seed-Selection Handoff

WF owns temporary pre-loop sourcing, screening, verifying, ranking, and seed
selection. Memory owns the durable record of what WF decided.

After WF selects the seed, write memory in this order:

1. Create a `SeedCandidatePool` with every seed candidate WF considered.
2. Include each seed candidate's sequence, provenance, artifacts, and any
   screening/verifier evaluations.
3. Record a `SeedSelectionDecision`.
4. Include the selected candidate id, ranked candidate ids, selection method,
   rationale, and human override flag when applicable.
5. Create the run with `create_run_from_seed_selection(...)`.
6. Treat the selected seed as `loop_0`.

The agent must not discard non-selected seeds. They are evidence for future
restart, audit, or branch decisions.

## Optimization Loop Protocol

For every optimization loop after `loop_0`, perform exactly one candidate change
set per loop.

Required order:

1. Read context with `get_active_context(run_id)` or `get_loop_context(...)`.
2. Propose exactly one `ChangeSet`.
3. Record why the change was made in `ChangeSet.why`.
4. Record machine-readable changes such as `F5Y`, insertion, deletion, or
   structural edits.
5. Append the new candidate with `append_loop(...)`.
6. Keep the new loop pending until all required outputs are attached.
7. Attach Boltz output with `attach_evaluation(...)` or store Boltz artifact
   references on the candidate.
8. Attach screening output with `attach_evaluation(...)`.
9. Attach verifier output with `attach_evaluation(...)`.
10. Attach `LoopReflection` with what went well, what did not go well, and what
    to try next.
11. Call `finalize_loop(...)`.
12. Continue only if finalization succeeds.

Screening and verifier must run at the end of every optimization loop. They are
not only pre-loop seed-selection steps.

## Finalization Gate

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

If `finalize_loop(...)` raises `LoopIncomplete`, the agent must repair the
memory record before continuing. It should inspect
`validate_loop_complete(...).missing_requirements`, write the missing records,
and retry finalization.

The agent must not mark a pending loop as active outside `finalize_loop(...)`.

## Reflection Requirements

Each completed optimization loop must include a `LoopReflection`:

- `went_well`: concrete improvements or useful signals.
- `went_wrong`: regressions, uncertainty, invalid assumptions, or failed
  hypotheses.
- `next_actions`: specific next changes or experiments.
- `notes`: optional supporting context.

Reflections must be based on the loop's Boltz, screening, verifier, and human
feedback. Do not write empty or generic reflection fields.

## Human Comments And Advice

When a human comments on a loop, record it with `add_loop_comment(...)` or
`record_human_input(...)`.

Human input can include:

- interpretation of a result
- requested changes
- warnings about a design direction
- approval to branch from a loop
- rejection or rollback rationale

The agent must read human input from `AgentLoopContext.human_inputs` before
planning a derived loop.

## Branching From A Loop

When a human or agent chooses a previous loop as a branch point:

1. Load that loop's context with `get_loop_context(run_id=..., loop_id=...)`.
2. Read the sequence, lineage, metrics, reflection, and human inputs.
3. Create the next loop with `append_loop(parent_loop_id=selected_loop_id, ...)`.
4. Follow the normal optimization loop protocol.
5. Finalize before making the new loop active.

Do not erase later loops when branching. Previous future loops should remain
queryable as available or abandoned branches.

## Rollback

Rollback moves the active head; it does not delete history.

Use `rollback_to_loop(...)` when a human or agent decides a previous loop should
become active again. The rollback reason must be explicit.

The agent must not roll back to a pending loop. Pending loops must be finalized,
rejected, or ignored before they can be used as branch targets.

## Visualization

The frontend should use `get_run_visualization(run_id)` to display:

- loop graph nodes and parent-child edges
- active loop
- seed-selection rationale
- branch labels and abandoned branches
- status for each loop
- latest metrics
- change diffs and rationale
- human comments and requested changes
- pending-loop completeness issues

If the frontend lets a human add advice, it must persist that advice with
`add_loop_comment(...)` before launching a new loop from that point.

## Failure Handling

If any model, screening step, verifier step, or artifact step fails:

1. Keep the loop pending unless enough evidence exists to finalize it.
2. Attach any available diagnostic evaluation or human input.
3. Record the failure in reflection if the loop can be finalized.
4. Do not continue to the next loop until the current loop is finalized or an
   explicit rollback/branch decision is recorded.

## Prohibited Behavior

The agent must not:

- keep loop state only in chat history or process memory
- skip screening or verifier at the end of an optimization loop
- create multiple optimization candidates inside one loop record
- mark incomplete loops active
- overwrite or delete abandoned branches
- ignore human comments when branching from a loop
- mutate historical records outside repository methods
- continue after `finalize_loop(...)` fails
