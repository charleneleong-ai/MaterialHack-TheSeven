# Boltz Model Usage Contract

This document defines how the agentic protein-design system should use Boltz
models and Boltz-style artifacts across the existing branches.

It is intentionally additive. It does not replace the `WF` pipeline, the memory
repository, the `TRS` scorer, or the local loop-runner contracts. It defines the
interfaces those pieces should share when real Boltz implementations replace the
current stubs.

## Branch Review Basis

This contract is based on the current local and remote branch definitions:

- `origin/WF` defines the LangGraph prototype and the node API reference. Its
  `boltzgen_generate` node already uses a CIF-first candidate bundle with
  sequence, structure path, metrics, and design metadata.
- `origin/main` includes the memory package. Memory stores Boltz references in
  `ProteinCandidate.boltz_artifacts` and accepts Boltz evaluations through
  `EvaluationResult(kind=EvaluationKind.BOLTZ)`.
- `origin/TRS` defines a structure scoring tool for protein-metal binding. TRS
  should run after Boltz writes structures and should be recorded as screening
  or verifier evidence, not as a Boltz model output.
- The local `loop-runner` worktree defines post-`loop_0` adapter boundaries:
  `CandidateGenerator`, `BoltzEvaluator`, `ScreeningPipeline`, `Verifier`, and
  `ReflectionWriter`.
- `origin/codex/add-agents-coordination` and `AGENTS.md` define the branch
  ownership boundary between WF's temporary pre-loop ranking and memory's
  durable loop ledger.

## Model Roles

Use Boltz models in three separate roles. Do not collapse these into one opaque
"model score" because each role has different storage and decision semantics.

| Role | Agent step | Output owner | Memory representation |
| --- | --- | --- | --- |
| Candidate generation | Generate or refine candidate structures from a compiled design spec, template, constraints, or sequence. | `WF` before `loop_0`; runner after `loop_0`. | Selected candidate sequence plus `ArtifactRef` entries for generated structures and input specs. |
| Structure/confidence evaluation | Predict structure quality and confidence for one selected candidate. | Boltz adapter. | `EvaluationResult(kind=BOLTZ)` and/or `ProteinCandidate.boltz_artifacts`. |
| Downstream screening feature source | Provide structures and confidence fields for screeners such as TRS, binding-site checks, or verifier tools. | Screening/verifier adapters. | `EvaluationResult(kind=SCREENING)` or `EvaluationResult(kind=VERIFIER)`, with artifacts pointing back to the Boltz structures they consumed. |

The LLM can interpret Boltz outputs, choose the next experiment, and write
reflections. It must not fabricate Boltz metrics, overwrite model outputs, or
mark a loop complete without persisted Boltz evidence.

## Canonical Artifact Contract

The canonical structure artifact is mmCIF.

Boltz adapters must write or reference mmCIF files as the durable structure
source of truth. PDB may be exported for human convenience, but downstream
agents should not depend on PDB as the canonical format.

Each candidate bundle should preserve the `WF` branch shape:

```python
{
    "id": "cand-78055",
    "structure_path": "workbench/candidates/iter2/cand-78055.cif",
    "sequence": "ACDE...",
    "metrics": {
        "plddt": 0.82,
        "ptm": 0.71,
        "iptm": 0.64,
        "pae_mean": 5.9
    },
    "design_metadata": {
        "target": "ZN2+",
        "binding_site_residues": [11, 35, 39],
        "sampling_seed": 1843221090
    }
}
```

The mmCIF should include an `_atom_site` loop. Per-residue confidence should be
recoverable from `B_iso_or_equiv` as `pLDDT * 100` when the model provides that
signal. Downstream screening tools should read confidence and coordinates from
the structure artifact instead of trusting only in-memory Python fields.

## Memory Mapping

For every selected candidate, store artifacts and metrics through memory's
existing types.

Use `ProteinCandidate.structure_artifacts` for generally useful structures:

```python
ArtifactRef(
    uri="workbench/candidates/iter2/cand-78055.cif",
    kind="structure",
    format="mmcif",
    sha256="<optional artifact hash>",
    metadata={"source": "boltz", "candidate_id": "cand-78055"},
)
```

Use `ProteinCandidate.boltz_artifacts` for Boltz-specific files:

```python
ArtifactRef(
    uri="workbench/candidates/iter2/cand-78055.metrics.json",
    kind="boltz_metrics",
    format="json",
    metadata={
        "model_name": "boltz",
        "model_version": "<runtime version>",
        "sampling_seed": 1843221090,
        "input_spec_hash": "<optional hash>",
    },
)
```

Use `EvaluationResult(kind=EvaluationKind.BOLTZ)` for loop metrics:

```python
EvaluationResult(
    kind=EvaluationKind.BOLTZ,
    evaluator_name="boltz",
    evaluator_version="<runtime version>",
    metrics=(
        MetricValue(name="plddt", value=0.82, higher_is_better=True),
        MetricValue(name="ptm", value=0.71, higher_is_better=True),
        MetricValue(name="iptm", value=0.64, higher_is_better=True),
        MetricValue(name="pae_mean", value=5.9, unit="angstrom", higher_is_better=False),
    ),
    artifacts=(...),
)
```

`finalize_loop(...)` should continue to require a Boltz evaluation or Boltz
artifact. A loop with only chat text saying "Boltz passed" is incomplete.

## Pre-Loop Seed Selection

Before `loop_0`, WF can generate and rank many temporary candidates. That batch
is not an optimization loop yet.

The handoff into durable memory is:

1. WF sources or generates candidate seeds.
2. Boltz generation/evaluation writes CIF and metrics artifacts for each seed
   when available.
3. Screening and verifier adapters rank the seed pool.
4. Memory records every considered seed in `SeedCandidatePool`.
5. Memory records the selected seed in `SeedSelectionDecision`.
6. Memory creates the run with `create_run_from_seed_selection(...)`; the
   selected seed becomes `loop_0`.

Non-selected seeds should retain Boltz artifacts and evaluation summaries so the
agent can restart from them later.

## Optimization Loop Usage

After `loop_0`, each finalized loop represents exactly one selected candidate.

The runner may ask a Boltz adapter to sample multiple internal candidates for a
single planned change, but only one candidate becomes the loop record. If a
batch was sampled, store the selected candidate as the loop candidate and attach
batch-level artifacts or metadata for audit. Do not create a loop record that
contains several competing optimization candidates.

The post-`loop_0` order is:

1. Read `AgentLoopContext` from memory.
2. Plan one `ChangeSet`.
3. Generate or update the candidate sequence/constraints.
4. Run Boltz generation or structure evaluation.
5. Append the pending loop with the selected `ProteinCandidate`.
6. Attach `EvaluationKind.BOLTZ`.
7. Run screening adapters, including TRS when the target asks about metal-driven
   structural reorganization.
8. Attach `EvaluationKind.SCREENING`.
9. Run the verifier.
10. Attach `EvaluationKind.VERIFIER`.
11. Write `LoopReflection`.
12. Call `finalize_loop(...)`.

If Boltz fails after the pending loop exists, keep the loop pending, attach
diagnostic human input or an error evaluation when possible, and stop rather
than advancing to the next loop.

## TRS Relationship

TRS is not a Boltz model. It is a screening/explanation tool that consumes
structure artifacts.

Use TRS after Boltz when:

- the target involves protein-metal binding,
- the objective asks for conformational or topological reorganization,
- a human asks why a metal-binding structure was ranked highly,
- the verifier needs an interpretable structure-change feature.

Record TRS output as `EvaluationKind.SCREENING` unless it is explicitly promoted
to the final verifier. Include component metrics such as coordination number,
path-length change, Laplacian change, and total TRS score.

## Stop And Decision Semantics

Boltz metrics are evidence, not the final stop condition by themselves.

The runner should stop when memory goals are satisfied or the loop budget is
exhausted. Goals may include Boltz metrics, screening metrics, verifier metrics,
or human-approved criteria. The LLM may recommend stopping, but the controller
must check `DesignObjective.goals_satisfied_by(...)` or the configured loop
budget before ending a run.

## Reproducibility Requirements

Every Boltz call should record enough metadata to reproduce or audit the output:

- model name and version,
- command or adapter name,
- input spec or config artifact,
- sampling seed,
- candidate id,
- run id and loop id when known,
- created artifact URIs,
- artifact hash when practical,
- runtime failure details when a call fails.

The same metadata should be available to the frontend through memory
visualization payloads via loop artifacts, evaluations, and metric maps.

## Open Integration Decisions

These details are intentionally left for the implementation branches:

- exact Boltz package, checkpoint, and runtime command,
- GPU or service execution environment,
- ligand, cofactor, and multichain input schema,
- persistent artifact storage location,
- whether affinity-like Boltz outputs should be a verifier metric or only a
  screening metric,
- how batch-level pre-loop artifacts are pruned or archived after seed
  selection.
