# Node API Reference

This is the contract each of the 8 graph nodes in [pipeline.py](pipeline.py) must
satisfy. Every node is a pure function `(DesignState) -> DesignState`; the node
function itself only reads/writes `DesignState` fields and calls a plain
stub/helper function that does the real work. **To implement a real node, you
only need to replace the stub/helper function — the node wrapper, graph
wiring, and `DesignState` shape stay the same.**

`DesignState` (defined in `pipeline.py:47`) is the one object threaded through
the whole graph:

| Field | Type | Set by | Notes |
|---|---|---|---|
| `objective` | `str` | CLI arg | raw user text, never mutated |
| `spec` | `dict` | `objective_intake`, `compile_spec` | the "DesignSpec" — see below |
| `strategy` | `"scratch" \| "template"` | `route_strategy` | |
| `template` | `dict \| None` | `memory_retrieval` | |
| `template_score` | `float` (`0..1`) | `memory_retrieval` | |
| `candidates` | `list[dict]` | `boltzgen_generate` | all N candidates this iteration |
| `scored` | `list[dict]` | `screen_score` | top-k of `candidates`, sorted desc by `score` |
| `best` | `dict \| None` | `screen_score` | `scored[0]` |
| `pseudo_lab_score` | `float` (`0..1`) | `pseudo_lab` | |
| `iteration` | `int` | `compile_spec` (increments) | 1-indexed |
| `max_iterations` | `int` | fixed default `4` | |
| `target_score` | `float` | fixed default `0.8` | |
| `score_source` | `"screen" \| "pseudo_lab"` | CLI arg `--score-source` | which score `diagnose_replan` checks against `target_score` |
| `workdir` | `str` | CLI arg `--workdir` | root dir candidate structure files are written under |
| `history` | `list[dict]` | `pseudo_lab` (appends) | one record per iteration |
| `done` | `bool` | `diagnose_replan` | |
| `verdict` | `str` | `diagnose_replan` | |

---

## 1. `objective_intake` (LLM reasoning) — `pipeline.py:275`

Parses free-form natural language into a typed **DesignSpec**.

- **Input:** `state.objective: str` — e.g. `"design a protein that binds Zn2+ at pH 5 and can polymerize"`. Can name *any* target/condition/function; don't assume it matches a known template.
- **Output → `state.spec`:**
  ```json
  {"target": "Zn2+", "ph": 5.0, "functions": ["bind", "polymerize"], "length": 60}
  ```
  | Key | Type | Meaning |
  |---|---|---|
  | `target` | `str` | what the protein binds/targets (ion, small molecule, protein, surface, ...) |
  | `ph` | `float` | operating pH |
  | `functions` | `list[str]` | requested functions, e.g. `bind`, `fold`, `catalyze`, `polymerize` |
  | `length` | `int` | residues, best-effort default if unspecified |
- This node calls `reason(system, user, fallback)` (`pipeline.py:73`), which calls Claude if `ANTHROPIC_API_KEY` is set, else uses `_heuristic_intake()` (regex fallback, `pipeline.py:318`). **A real implementation would likely just strengthen the system prompt / add few-shot examples — no code path needs replacing.**

## 2. `memory_retrieve` (stub) — `pipeline.py:119` — replace with: vector search over a design memory

- **Signature:** `memory_retrieve(spec: dict) -> dict`
- **Input:** the `DesignSpec` from node 1.
- **Output:**
  ```json
  {
    "template": {"id": "TMPL-3471", "motif": "EF-hand", "length": 87},
    "match_score": 0.324
  }
  ```
  | Key | Type | Meaning |
  |---|---|---|
  | `template` | `dict \| None` | nearest existing design on record, or `None` if nothing close enough |
  | `template.id` | `str` | memory-store identifier |
  | `template.motif` | `str` | structural family, e.g. `zinc-finger`, `beta-barrel` |
  | `template.length` | `int` | residue count of the template |
  | `match_score` | `float` (`0..1`) | similarity of `spec` to `template`; higher = closer match |
- Called from `memory_retrieval` node (`pipeline.py:346`), which copies the result straight into `state.template` / `state.template_score`. No reshaping needed downstream.

## 3. `route_strategy` (LLM/logic) — `pipeline.py:358`

Pure decision node, no new stub — decides `"template"` vs `"scratch"` from `state.template_score` against a fixed threshold (`0.5`).
- **Output → `state.strategy`:** `"template" | "scratch"`.

## 4. `compile_spec` (LLM reasoning) — `pipeline.py:376`

Turns the objective (+ optional template) into the spec actually handed to generation. Increments `state.iteration` first.
- **Input:** `state.objective`, `state.strategy`, `state.template`, `state.iteration`.
- **Output → `state.spec`:** same `DesignSpec` shape as node 1, plus (when `strategy == "template"`) `template_id: str` and `length` overridden from the template. This is also where iteration-specific replanning would inject feedback from the previous loop (e.g. "previous best missed binding site confidence — narrow the motif") — **not currently wired in, but `compile_spec`'s `user` payload is the right place for a colleague to add `state.history`/`state.scored` context if they want the LLM to actually use prior-iteration results.**

## 5. `boltzgen_generate` (stub) — `pipeline.py:190` — replace with: BoltzGen structure-conditioned generation

This is the one with the richest contract — mirrors BoltzGen's actual interface (mmCIF + per-design metrics), not just a sequence string.

- **Signature:** `boltzgen_generate(spec: dict, workdir: Path, n: int = 8) -> list[dict]`
- **Input:**
  - `spec`: the `DesignSpec` from node 4 (may include `target`, `ph`, `functions`, `length`, `template_id`).
  - `workdir`: `Path` to write structure files into (caller passes `workbench/candidates/iter<N>/`; the function must `mkdir(parents=True, exist_ok=True)` it).
  - `n`: number of candidates to generate.
- **Output:** `list[Candidate]`, one dict per generated design:
  ```json
  {
    "id": "cand-78055",
    "structure_path": "workbench/candidates/iter2/cand-78055.cif",
    "sequence": "NEWRVHSTANTMQRHGPTEYNCKKPPCADQQNWKEILPTI...",
    "metrics": {
      "plddt": 0.653, "ptm": 0.818, "iptm": 0.304,
      "pae_mean": 7.42, "ALA_fraction": 0.067
    },
    "design_metadata": {
      "motif": "beta-barrel",
      "binding_site_residues": [11, 35, 39],
      "target": "ZN2+",
      "sampling_seed": 1843221090
    }
  }
  ```
  | Key | Type | Meaning |
  |---|---|---|
  | `id` | `str` | unique candidate id |
  | `structure_path` | `str` | path to an **mmCIF** file (BoltzGen's real output format — not PDB; see note below) |
  | `sequence` | `str` | chain-A amino-acid sequence, cached for convenience. The structure file is the source of truth — don't make downstream code trust this over the CIF if they ever diverge |
  | `metrics.plddt` | `float` (`0..1`) | mean per-residue confidence |
  | `metrics.ptm` | `float` (`0..1`) | predicted TM-score |
  | `metrics.iptm` | `float \| None` | interface pTM, only meaningful when binding a real target (None for `target == "unknown"`) |
  | `metrics.pae_mean` | `float`, Angstroms | mean predicted aligned error |
  | `metrics.ALA_fraction` | `float` (`0..1`) | example composition stat (real BoltzGen's filtering step uses columns like this, e.g. `ALA_fraction`, to flag biased sequences) |
  | `design_metadata.motif` | `str` | structural family used/targeted |
  | `design_metadata.binding_site_residues` | `list[int]` | 1-indexed residues predicted/intended to contact the target |
  | `design_metadata.target` | `str` | echoed from spec |
  | `design_metadata.sampling_seed` | `int` | for reproducing this specific sample |

  **Structure file contract:** must be a valid mmCIF with an `_atom_site` loop (`label_asym_id` = chain, 1-indexed `label_seq_id` = residue number) and **per-residue confidence stored in `B_iso_or_equiv` as `pLDDT * 100`** — this is the same convention AlphaFold/Boltz use, and `screen_score` (node 6) reads it back via `_read_residue_bfactors()` (`pipeline.py:181`). If you swap in real BoltzGen, its native CIF output already satisfies this — no extra glue needed. **Use CIF, not PDB:** BoltzGen itself never emits PDB; PDB's fixed-width columns/chain-ID limits make it a worse fit for multi-chain/ligand complexes, so don't convert down to it.

  Helper functions worth reusing if you build a different stub/visualization: `_idealized_helix_ca_coords()`, `_write_stub_cif()`, `_read_residue_bfactors()` (`pipeline.py:146-187`).

## 6. `screen_score` (stub) — `pipeline.py:242` — replace with: in-silico screening / scoring model

- **Signature:** `screen_score(candidates: list[dict]) -> list[dict]`
- **Input:** the `list[Candidate]` from node 5 (must have `structure_path`, `metrics`, `design_metadata`).
- **Output:** the same list, **mutated in place** with an added `"score": float` key on every candidate, **returned sorted descending by `score`**. Caller (`screen_node`, `pipeline.py:417`) takes `scored[:3]` as the iteration's shortlist and `scored[0]` as `state.best`.
- Current stub composite: `0.4*plddt + 0.3*ptm + 0.3*site_confidence`, where `site_confidence` is read from each candidate's own CIF (not from a python list) — a real implementation should keep reading confidence/structure off `structure_path` rather than re-introducing an in-memory-only field, so this stays swappable with a tool that operates on files (e.g. a real PLIP/RMSD/affinity scorer invoked as a subprocess on the CIF).

## 7. `pseudo_lab` (stub) — `pipeline.py:261` — replace with: wet-lab assay / high-fidelity oracle

- **Signature:** `pseudo_lab(candidate: dict, iteration: int) -> dict`
- **Input:** `candidate` = `state.best` (a single `Candidate`, same shape as node 5's output — so a real implementation can read its `structure_path`/`sequence`/`metrics` directly), and the current `iteration` (int, 1-indexed).
- **Output:**
  ```json
  {"real_score": 0.91}
  ```
  Just `{"real_score": float (0..1)}` — higher fidelity ground truth for the single top candidate. The node (`pseudo_lab_node`, `pipeline.py:429`) copies this into `state.pseudo_lab_score` and appends a `history` record.

## 8. `diagnose_replan` (LLM reasoning) — `pipeline.py:441`

Decides whether the loop is done. No new stub function — logic lives directly in the node.
- **Input:** `state.score_source` selects which score to check: `state.best["score"]` (if `"screen"`) or `state.pseudo_lab_score` (if `"pseudo_lab"`), plus `state.target_score`, `state.iteration`, `state.max_iterations`.
- **Output:** `{"done": bool, "verdict": str}` → `state.done`, `state.verdict`. **Guardrail:** the node forces `done = True` once `iteration >= max_iterations` regardless of what the LLM/fallback says — don't remove that when modifying this node.
- If `done` is `False`, the graph loops back to node 4 (`compile_spec`); otherwise it ends.

---

## Quick checklist for a colleague implementing a real node

1. Find the stub function by name (table above) — its signature and return shape are the contract; don't change them without updating every caller.
2. Keep the node wrapper (e.g. `boltzgen_node`) untouched — it only marshals `DesignState` fields in/out of the stub function and prints a one-line trace (`[N] name (stub/LLM) -> ...`).
3. For nodes 5–7, the source of truth for structure/confidence is the CIF file at `structure_path`, not any cached python field — keep that invariant so swapping stubs for real tools (which naturally produce files, not python dicts) is a drop-in change.
4. Run `python pipeline.py` after your change — it must still complete end-to-end offline (no `ANTHROPIC_API_KEY` needed) since the 4 reasoning nodes fall back to deterministic logic.
