# Protein-Design Agent

A minimal, runnable **agentic protein-design workflow** — a closed-loop
*design → build → test → learn* pipeline orchestrated as a
[LangGraph](https://github.com/langchain-ai/langgraph) cyclic state machine.

The heavy ML models aren't ready yet, so they're **stubbed with seeded random
numbers** behind clean interfaces. The 4 reasoning nodes call **Claude** if
`ANTHROPIC_API_KEY` is set, and otherwise fall back to deterministic placeholder
logic — so the whole thing runs end-to-end with **one command and no API key**.

## Run

```bash
pip install -r requirements.txt
python pipeline.py "design a protein that binds Zn2+ at pH 5 and can polymerize"
```

No argument → a sensible default objective is used, so it always runs.
Set `SEED=<int>` for a different reproducible run; set `ANTHROPIC_API_KEY` to use
Claude (`claude-opus-4-8`) for the reasoning nodes instead of the offline fallback.
Pass `--score-source screen|pseudo_lab` (default `pseudo_lab`) to choose which
score the stop condition checks against `target_score` — the cheap in-silico
`screen` score, or the higher-fidelity `pseudo_lab` score:

```bash
python pipeline.py "design a protein that binds Zn2+ at pH 5" --score-source screen
```

## The 8-node loop

Nodes strictly alternate between **LLM reasoning** (the only place an LLM decides)
and **deterministic compute** (all stubbed for now).

```
            ┌──────────────────────────────────────────────────────────┐
            │                                                          (loop)
            ▼                                                            │
  (LLM)  1. objective_intake     parse objective -> typed DesignSpec    │
            │                                                            │
  (stub) 2. memory_retrieval     fake template + random match score     │
            │                                                            │
  (LLM)  3. route_strategy       template if match >= 0.5 else scratch   │
            │                                                            │
  (LLM)  4. compile_spec  <───────────────────────────────────────────┐ │
            │                    objective + template -> design spec   │ │
  (stub) 5. boltzgen_generate    N candidate structure files + metrics │ │
            │                                                          │ │
  (stub) 6. screen_score         random scores, keep top-k            │ │
            │                                                          │ │
  (stub) 7. pseudo_lab           "real-world" score (upward bias/iter)│ │
            │                                                          │ │
  (LLM)  8. diagnose_replan      done vs. continue ─── continue ──────┘ │
            │                                                            │
            └── done ── END                                              │
```

The feedback edge is `diagnose_replan → compile_spec`. The loop stops when
`pseudo_lab_score >= target_score` (default `0.8`) **or** `iteration ==
max_iterations` (default `4`).

## Where to plug in real skills

Each stub has a clear, documented signature and a stable return shape, so
swapping in a real implementation is a **one-function change** (look for the
`# TODO: replace with real skill` markers in [pipeline.py](pipeline.py)):

| Stub | Signature | Replace with |
|------|-----------|--------------|
| `memory_retrieve` | `(spec: dict) -> {"template": dict \| None, "match_score": float}` | vector search over a design memory |
| `boltzgen_generate` | `(spec: dict, workdir: Path, n: int = 8) -> list[{"id", "structure_path", "sequence", "metrics", "design_metadata"}]` | BoltzGen structure-conditioned generation |
| `screen_score` | `(candidates: list[dict]) -> list[dict]` (adds `"score"`, sorted desc) | in-silico screening / scoring model |
| `pseudo_lab` | `(candidate: dict, iteration: int) -> {"real_score": float}` | wet-lab assay / high-fidelity oracle |

See [NODE_APIS.md](NODE_APIS.md) for the full per-node API reference (every field,
type, and the `DesignState` contract) if you're implementing one of these.

The 4 reasoning nodes (`objective_intake`, `route_strategy`, `compile_spec`,
`diagnose_replan`) all route through one helper, `reason(system, user,
fallback)`, which calls Claude when a key is present and returns the deterministic
`fallback` otherwise. That helper is the only place the autonomy lives.
