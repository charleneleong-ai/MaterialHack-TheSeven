# BoltzGenAgenticPrompt

**SPEC — From-scratch metal-binding protein design with a CCDC-trained selection filter**

> Paste this into Claude Code, or save it as `SPEC.md` and tell Claude Code:
> *"Read SPEC.md and build it phase by phase, committing after each phase."*

---

## Context (why we're building this)

Generative models (BoltzGen / the Boltz API protein-design endpoint) can now design metal-binding proteins from scratch — but they overproduce: hundreds of candidates, most of which won't bind the right metal or won't survive industrial conditions. Generation is no longer the bottleneck — **selection is**.

We are building the **filter**: a model that takes a designed protein and scores two things —

1. **Selectivity** — does it grab the target metal (e.g. Cu) and reject competitors (e.g. Zn)?
2. **Stability** — will the site hold up in real reactor conditions?

We train the filter on a CCDC metal-binding-site export (provided, see below), then drop it into the design pipeline as the ranking step. The result: instead of 500 maybes, the chemist gets the **5 worth making**. This is the bio-to-metal interface ARIA's Universal Fabricators programme is targeting.

**Your contribution is the filter + its integration.** The generator is a means to an end — don't sink the whole budget into it.

---

## The data (verify before trusting this description)

A zip `ligands_10000.zip` is in the project root. It unzips to:

```
ligands_10000/
├── Zn/   mol_*.mol2   (2912 sites)
├── Ca/                (2406)
├── Mn/                (1812)
├── Mg/                ( 992)
├── Fe/                ( 783)
├── Na/                ( 377)
├── Co/                ( 252)
├── Ni/                ( 237)
├── Fe_Ni/             ( 111)   # bimetallic
├── Ca_Mn/             (  57)   # bimetallic
├── K/                 (  26)
├── Cu/                (  32)   # <-- TINY; the pitch's hero metal
└── Mn_Sr/             (   3)   # bimetallic
```

Ignore `__MACOSX/` and `.DS_Store`. ~10,000 files total. The folder name is the coordinating-metal label (verified reliable on a sample, but cross-check by parsing the metal element from the ATOM block and flag mismatches).

Each `.mol2` is a single metal binding site extracted from a solved PDB/CSD structure — the metal ion(s) plus the real first-shell coordinating residues. Sybyl/Tripos MOL2 format:

- `@<TRIPOS>ATOM`: `id name x y z atom_type substruct_id residue_name charge`. Atom types are Sybyl (e.g. `N.3`, `C.2`, `N.pl3`, `S.3`, `O.2`, and the metal as its element symbol e.g. `Cu`, `Zn`). Residue names carry the residue + PDB number (e.g. `HIS382`). Some sites contain `R`/`Du` dummy atoms — handle/skip them.
- `@<TRIPOS>BOND`: bond list.
- `@<TRIPOS>SUBSTRUCTURE`: residue list.
- `@<TRIPOS>SET`: `CCDC_AMINOACID` (protein atoms) and `CCDC_LIGAND` (metal + first shell) — use these to separate metal/donor atoms from scaffold.
- `@<TRIPOS>COMMENT`: key/value metadata incl. `resolution`, `pdb`, `is_covalent`, `ec_number`, `organism`, `molecule`, `structure_method`. Use `resolution` for quality filtering (e.g. keep <= 2.5 A).

This data is **dual-purpose**: (a) labelled training set for the selectivity classifier, and (b) geometry ground-truth (donor set, coordination number, bond lengths/angles) for scoring designs. Don't treat it as a generic ligand dump.

**Donor identification:** a coordinating donor is a non-metal atom within metal-donor bonding distance of the metal (~1.8-2.6 A; use the BOND records and/or a distance cutoff). Map each donor to its residue + atom (His ND1/NE2, Cys SG, Asp/Glu OD/OE, backbone O/N, water O, etc.).

---

## What to build (phased — commit after each phase)

### Phase 1 — CCDC -> structured coordination dataset

- Write a robust MOL2 parser (don't rely on RDKit reading metal MOL2 cleanly; the format is simple — parse the blocks directly). Extract per site: metal identity, all donor atoms (element + residue + atom name), coordination number, donor-atom-type composition (counts of N/O/S and of His/Cys/Asp/Glu/backbone), metal-donor distances, donor-metal-donor angles, and metadata (resolution, pdb, is_covalent).
- Output a tidy table (`data/sites.parquet`): one row per site, with a feature vector + the metal label + quality fields.
- Print a summary: per-metal counts, donor-set distributions, CN distributions, resolution histogram. Sanity-check against the counts above.
- Quality filter (configurable): drop sites worse than a resolution cutoff and covalent-flagged sites; keep a copy of the unfiltered table.

### Phase 2 — Selectivity model (the core contribution)

- Train a multiclass metal-identity classifier from the coordination feature vector (geometry + donor composition). This is the selectivity engine: for a query site, `P(Cu), P(Zn), P(Ni), ...`; selectivity score = P(target) - max(P(competitors)).
- Imbalance is severe (Cu=32 vs Zn=2912). Use class weighting / resampling; evaluate with macro-F1, per-class AUROC, specificity, balanced accuracy — not raw accuracy. Use stratified k-fold; for low-N classes (Cu, K, bimetallics) report metrics with confidence intervals / variance, and be explicit about the limits.
- Produce a focused **Cu-vs-Zn discrimination report** (the pitch claim): ROC, confusion, and an honest statement of the 32-sample limitation.
- Start with gradient boosting (XGBoost/LightGBM) on the engineered features — fast, interpretable, demo-friendly. Optionally add a second variant that concatenates an ESM-2 embedding of the local sequence context (the residues lining the site) to test whether learned protein embeddings beat hand features; only do this if Phase 1-2 finished with time to spare.
- Save the model + a `predict_selectivity(site_features) -> {metal: prob, selectivity_score}` function.

### Phase 3 — Stability scoring

- Stability labels are thin, so make this a **transparent heuristic score**, not an overclaimed model. Combine signals available from a design's structure: site burial / solvent exposure, secondary-structure context of the coordinating residues (helix/sheet vs loop — more structured = more pre-organized), number of coordinating residues from rigid vs flexible regions, and (if available) the co-fold confidence at the site. Expose `predict_stability(structure) -> score in [0,1]` and document exactly what goes into it.
- Optional stretch: a **Topology Reorganization Score (TRS)** — co-fold the design with vs without the metal and measure how much the coordinating residues move (low movement = pre-organized = better). Wire as a feature if time allows.

### Phase 4 — Generation from scratch (means to an end)

- Generate candidate metal-binding mini-proteins for a chosen target metal using the Boltz API protein-design endpoint (`boltz-api` CLI), metal as a `ligand_ccd` entity, seeded from the CCDC data: pick the most common donor set / coordination number for that metal (from Phase 1) and encode it via epitope + contact constraints.
- Build and debug entirely on a **Boltz API TEST key** first (synthetic, free, instant); only switch to a live key for the final demo run. In the first 10 minutes, send one test-mode design call with a metal-only target to confirm the API accepts it; if it's rejected, fall back to local open-source BoltzGen for generation and note it.
- For each generated candidate, get an independent co-fold via the Boltz `structure-and-binding` prediction (metal as `ligand_ccd`). Trust the structural metrics (`structure_confidence`, `iptm`, `min_interaction_pae`); **do not trust** `binding_confidence`/`optimization_score` for a bare metal ion (affinity head is out-of-distribution for a 1-atom ligand).

### Phase 5 — The filter + ranking + the money result

- For each generated candidate: parse its coordination site (same featurizer as Phase 1), run `predict_selectivity` + `predict_stability`, and compute a combined ranking score.
- Output the top-5 candidates with their sequences, predicted metal, selectivity score, stability score, and co-fold confidence.
- The **headline deliverable**: a comparison showing the filter re-ranks the generated pool vs. naive Boltz structure-confidence ordering — i.e. the top-5-by-filter differ from top-5-by-raw-confidence, and the filter's picks have better selectivity/geometry. Save as a table + a simple plot.
- Write an audit/provenance record (JSONL + a rendered `report.md`): for each candidate, every score and the ranking rationale.

---

## Tech constraints & gotchas

- **Python.** Libs: `numpy`, `pandas`, `scikit-learn`, `xgboost`/`lightgbm`, `biotite` or `biopython` (structure parsing), `matplotlib`. `fair-esm` only if you reach the ESM-2 variant. `pip install --break-system-packages` if needed.
- **MOL2 parsing:** parse the TRIPOS blocks directly; don't assume RDKit handles metal MOL2. Handle `R`/`Du` dummy atoms and multi-metal clusters gracefully.
- **Imbalance** is the central modelling challenge — treat it as first-class, not an afterthought.
- **Boltz API:** test key while building; idempotency key per run; `download-results --name` matches the idempotency slug; parse `results/index.jsonl`. Keep each call a top-level `boltz-api ...` command.
- **Don't fabricate results or metrics.** If a step is blocked (e.g. API access), say so, stub it behind a clean interface, and keep going.

---

## Deliverables (repo layout)

```
metalfilter/
├── SPEC.md
├── src/parse_mol2.py          # Phase 1 parser + featurizer
├── src/build_dataset.py       # -> data/sites.parquet
├── src/train_selectivity.py   # Phase 2 model + eval report
├── src/stability.py           # Phase 3 heuristic (+ optional TRS)
├── src/generate.py            # Phase 4 Boltz API design + cofold
├── src/rank.py                # Phase 5 filter + top-5 + comparison
├── data/                      # parquet, model artifacts
├── reports/                   # eval report, cu_vs_zn, ranking comparison, report.md
└── README.md                  # how to run end-to-end
```

---

## Acceptance criteria ("done")

1. `sites.parquet` built from the zip with correct per-metal counts and donor/CN features; summary printed.
2. Selectivity model trained, evaluated with macro-F1 + per-class AUROC + specificity, plus a Cu-vs-Zn report with the 32-sample caveat stated.
3. Stability scorer implemented and documented (no overclaiming).
4. At least one batch of candidates generated for a target metal (test mode acceptable for the build; one live run for the demo) and co-folded.
5. Filter ranks the pool -> top-5 output, with a comparison vs naive-confidence ranking and an audit `report.md`.
6. `README.md` runs the whole thing end-to-end with one or two commands.

---

## Working style

- Start by unzipping + exploring the data and printing real numbers; write a 5-line plan; then build phase by phase.
- Commit after each phase. Keep functions small and the interfaces clean (the filter must be callable as a drop-in ranking step).
- If you must choose between breadth and a working end-to-end slice, ship the slice: data -> selectivity -> rank a small generated (or even held-out CCDC) pool -> top-5. Polish after.

---

## Results from proof-of-concept run

The following results were produced from an initial execution of this pipeline:

### Phase 1 — Dataset
- **10,000 MOL2 files** parsed with zero errors
- **8,966 sites** after quality filtering (dropped 139 covalent + 895 low-resolution)
- Folder labels match parsed metal identities perfectly (0 mismatches)
- Cu: only 23 sites post-filter (from 32 raw)

### Phase 2 — Selectivity model
- **XGBoost** multiclass classifier, 13 metal classes
- **Macro-F1: 0.80** | Balanced accuracy: 0.80
- **Cu AUROC: 0.96** (one-vs-rest) | **Cu-vs-Zn AUROC: 0.92**
- Cu recall: 14/23 (61%) — strong given only 23 training samples
- Top features: sulfur donors (0.24), coordination number (0.16), metal atom count (0.08)

### Phase 3 — Stability heuristic
- 5-component weighted score: coordination saturation, distance regularity, angular regularity, donor rigidity, multidentate bonus
- Cu sites score highest (0.68 mean) — consistent with rigid His/Cys coordination
- Ca/Na/K score lowest — flexible carboxylate/backbone donors

### Phase 4 — Generation
- `protein:design` endpoint rejected bare metal-ion target (confirmed)
- Fallback: CCDC-informed sequence design + Boltz 2.1 structure-and-binding co-fold
- 10 candidates generated with His/Cys Cu coordination motifs
- Structure confidence range: 0.41-0.62 (de novo sequences — moderate confidence expected)

### Phase 5 — Ranking
- Filter reranked the candidate pool vs naive structure-confidence ordering
- cu_bind_07 (His2Cys2-fold) promoted from rank 6 to rank 5 by the filter due to superior selectivity/stability despite lower fold confidence
- Demonstrates the filter surfaces biochemically relevant candidates that fold-quality alone misses

### Key limitation
- Candidates are **not lab-worthy** (pLDDT 0.43-0.65, need >0.85)
- The **filter is the deliverable**, not the candidates
- Pairing with RFdiffusion + ProteinMPNN for generation would produce foldable candidates that the filter can then rank

---

## Agentic loop extension (next iteration)

The following architecture closes the feedback loop to iteratively improve candidates toward lab-worthy thresholds:

```
            +----------------------------------------------------------+
            |                                                   (loop) |
            v                                                          |
  (LLM)  1. objective_intake     parse objective -> typed DesignSpec   |
            |                                                          |
  (stub) 2. memory_retrieval     template + match score from CCDC      |
            |                                                          |
  (LLM)  3. route_strategy       template if match >= 0.5 else scratch |
            |                                                          |
  (LLM)  4. compile_spec  <--------------------------------------+    |
            |                    objective + template -> design   |    |
  (stub) 5. boltzgen_generate    N candidate structures + metrics |    |
            |                                                     |    |
  (stub) 6. screen_score         CCDC filter, keep top-k          |    |
            |                                                     |    |
  (stub) 7. pseudo_lab           "real-world" validation score    |    |
            |                                                     |    |
  (LLM)  8. diagnose_replan      done vs. continue --- continue --+    |
            |                                                          |
            +--- done --- END                                          |
```

**Why the loop improves scores:**
- **Structure feedback (5->8->4):** LLM reads pLDDT=0.45, diagnoses "charged residues in core," rewrites spec for hydrophobic packing
- **Selectivity feedback (6->8->4):** If P(Cu) is low, LLM adds His or repositions Cys based on CCDC geometry
- **Memory accumulation (2):** Each iteration stores what worked, building design rules from experience

**Expected convergence trajectory:**
```
Iteration 1:  pLDDT ~0.45  struct_conf ~0.41  "doesn't fold"
Iteration 3:  pLDDT ~0.65  struct_conf ~0.60  "partially folded"
Iteration 5:  pLDDT ~0.80  struct_conf ~0.78  "approaching viable"
Iteration 8+: pLDDT ~0.85  struct_conf ~0.82  "worth making"
```

---

## Team

- **Repository:** [MaterialHack-TheSeven](/wenruifan/MaterialHack-TheSeven)
- **Programme:** ARIA Universal Fabricators
- **Target:** Bio-to-metal interface — selective metal-binding protein design
