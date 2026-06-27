# Agent and Branch Coordination

This repository has multiple collaborators working on different parts of the
protein-design agent. Keep branch ownership explicit so work can be merged
without accidentally overwriting another collaborator's direction.

## Branch Ownership

| Branch | Owner | Scope | Status |
| --- | --- | --- | --- |
| `main` | Team | Stable shared base | Keep minimal until branches are reviewed and merged. |
| `memory` | M-priv (Michael) | Durable memory abstraction for protein-design runs, loop records, rollback, branching, and future TuringDB integration. | Active, but pre-loop seed-selection memory is on standby pending Issue #1 discussion. |
| `WF` | WenruiFan | LangGraph agentic protein-design pipeline, temporary in-state candidate flow, stubbed generation/screening/verifier nodes. | Separate branch to integrate after memory boundaries are agreed. |

Update this table when a collaborator takes ownership of a new branch or when a
branch changes scope.

## Current Memory Scope

The `memory` branch owns the durable memory contract:

- `loop_0` is the selected seed candidate for an optimization run.
- `loop_1...n` are one-candidate optimization checkpoints.
- Each loop stores sequence, artifacts, changes, rationale, evaluations,
  reflection, human input, parent lineage, and lifecycle status.
- Rollback changes the active loop head and preserves later loops as abandoned
  branches.
- TuringDB should be attached behind the repository interface after the memory
  abstraction is stable.

## Standby Item

Issue #1 tracks pre-loop seed-selection memory:

https://github.com/wenruifan/MaterialHack-TheSeven/issues/1

Keep this on standby until the team decides whether the `WF` branch should own
the temporary pre-loop candidate pool, whether the memory branch should persist
that pool directly, or whether the responsibility should be split.

Expected boundary if split:

- `WF` branch can provide temporary working memory for sourcing, screening, and
  ranking candidate seeds.
- `memory` branch should persist the selected seed decision and enough evidence
  to restart from alternate seeds later.

## Coordination Rules

- Do not change another branch's owned scope without discussing it first.
- Prefer additive integration points over rewrites while branches are separate.
- Keep issue links in commits or PR descriptions when work implements a tracked
  design decision.
- If a branch starts depending on another branch's API, document the expected
  interface in this file or the relevant README before wiring it in.
