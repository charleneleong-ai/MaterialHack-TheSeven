# MaterialHack Agent App

This folder is the integration package for the runnable agentic protein-design
system. It composes the current branch work without changing branch ownership:

- WF-style pre-loop seed sourcing, scoring, ranking, and selection.
- `memory/` durable seed-selection and loop memory, including `loop_0`.
- `loop_runner/` post-`loop_0` optimization orchestration.
- Future adapter slots for real Boltz, TRS screening, and verifier tools.

## Do We Have Enough?

Yes, for an offline working agent loop. The repository now has enough structure
to run a complete stubbed system:

```text
objective
  -> pre-loop seed candidates
  -> seed ranking and selection
  -> memory SeedCandidatePool + SeedSelectionDecision
  -> durable loop_0
  -> loop_runner optimization loops
  -> memory visualization snapshot
```

The remaining production gaps are adapter implementations, not orchestration
shape:

- TRS-backed screening adapter from the `TRS` branch.
- Real verifier/high-fidelity oracle.
- Real Boltz generation/evaluation adapter.
- Durable TuringDB-backed repository configuration for deployed runs.

## Run Locally

From the repository root:

```bash
PYTHONPATH=memory/src:loop_runner/src:app/src \
python3 -m materialhack_agent \
  "design a protein that binds Zn2+ at pH 5 and can polymerize" \
  --seed-count 5 \
  --loops 2
```

The command runs without model credentials. Stub outputs are explicitly marked
as stubs in memory metadata and evaluator names.

## Package Layout

- `src/materialhack_agent/seed_flow.py` owns the WF-to-memory pre-loop handoff.
- `src/materialhack_agent/application.py` composes seed flow and loop runner.
- `src/materialhack_agent/cli.py` exposes a runnable command.
- `tests/` validates the end-to-end handoff and loop execution.
