# Novacore Agent App

This folder is the integration package for the runnable agentic protein-design
system. It composes the current branch work without changing branch ownership:

- Novacore pre-loop seed sourcing from either de novo generation or local
  CCDC/CSD ligand models in `../ligands_10000.zip`, followed by scoring,
  ranking, and selection.
- `memory/` durable seed-selection and loop memory, including `loop_0`.
- `loop_runner/` post-`loop_0` optimization orchestration with Novacore
  adapters for Codex-style planning, Boltz CLI preparation, TRS screening, and
  pending verifier MCP status.

## Do We Have Enough?

Yes, for an offline working agent loop. The repository now has enough structure
to run a complete stubbed system:

```text
objective
  -> pre-loop seed candidates from de novo or local CCDC/CSD ligand models
  -> seed ranking and selection
  -> memory SeedCandidatePool + SeedSelectionDecision
  -> durable loop_0
  -> forced Novacore loop_runner optimization loops
  -> Boltz artifacts + TRS output + pending verifier record
  -> memory visualization snapshot in the Novacore UI
```

The remaining production gaps are adapter implementations, not orchestration
shape:

- Production TRS-backed screening adapter from the `TRS` branch.
- Verifier MCP server/high-fidelity oracle. Until that exists, Novacore records
  a `verifier-mcp-pending` evaluation so the UI can show the missing step.
- Real Boltz CLI execution. The current adapter records the command and
  deterministic fallback metrics unless external execution is enabled.
- Durable TuringDB-backed repository configuration for deployed runs.

## Boltz Protocol

The Boltz protocol stays at the repository root in
[`BOLTZ_MODELS.md`](../BOLTZ_MODELS.md) because it is a cross-cutting contract
for WF seed selection, memory artifact storage, TRS screening inputs, and the
post-`loop_0` runner. App adapters that call Boltz or BoltzGen should follow
that file's artifact, failure, metrics, and mmCIF conventions instead of
inventing an app-local protocol.

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

## Run Novacore

Start the API:

```bash
PYTHONPATH=../memory/src:../loop_runner/src:src \
python3 -m uvicorn materialhack_agent.workbench_api:app --port 8000
```

Start the web UI from `app/web`:

```bash
npm install
npm run dev
```

Open `http://localhost:5173`. The Vite dev server proxies `/api` to the
FastAPI process on port `8000`.

## Package Layout

- `src/materialhack_agent/seed_flow.py` owns the Novacore-to-memory pre-loop handoff.
- `src/materialhack_agent/novacore.py` owns the Novacore Codex-agent persona and loop adapters.
- `src/materialhack_agent/ligand_catalog.py` resolves local CCDC/CSD `.mol2` models from `ligands_10000.zip`.
- `src/materialhack_agent/application.py` composes seed flow and loop runner.
- `src/materialhack_agent/workbench_api.py` exposes the FastAPI workbench API.
- `src/materialhack_agent/observable_memory.py` emits workbench events from memory writes.
- `src/materialhack_agent/cli.py` exposes a runnable command.
- `web/` contains the React workbench.
- `tests/` validates the end-to-end handoff and loop execution.
