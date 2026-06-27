# Verifying designs with touchstone

`touchstone` is a generator-agnostic verifier for designed metal-binding proteins. After
BoltzGen (or any generator) proposes a metal binder, touchstone judges whether the
*predicted* coordination site is real enough to take to wet-lab — a trust/weak/defer
consensus across independent methods (geometry + bond-valence + CSD, plus MLIP physics
and co-fold cross-checks when available).

It is wired in as an MCP server (`.mcp.json`), so any agent in this repo can call it; `uvx`
pulls it from the public [`charleneleong-ai/ai4science`](https://github.com/charleneleong-ai/ai4science)
repo on first use (requires `uv` on PATH). No install or vendoring.

## When to use it
- After generating a metal-binder structure (`.pdb` / `.cif`) → verify **before** wet-lab.
- Choosing which of several candidates to synthesize → keep only the `trust` set.
- Scoring designs as a reward signal for iteration.

## How to call it
MCP tool (preferred — available to the agent automatically):

> `verify_metal_binder(structure_path="design.cif", metal="Ni2+", deep=False, stress=False)`

### Parameters
| param | type | default | meaning |
| --- | --- | --- | --- |
| `structure_path` | str | — (required) | path to the design (`.pdb` / `.cif`) containing the metal + protein |
| `metal` | str | `"Ni2+"` | target metal label. Empirical reference priors exist for `Ni2+`, `Cu2+`, `Co2+`; other metals run the angle/symmetry tiers but defer where a prior is missing |
| `deep` | bool | `False` | also run MLIP (MACE) relaxation + 300 K MD — **needs a GPU**. Default is the instant CPU tiers, which run anywhere |
| `stress` | bool | `False` | also return a robustness map (`neutral` / `leachate` bond-stretch / `low_pH` donor-protonation) — does the site hold up under recovery-process conditions? |

## Reading the result
A JSON dict with per-tier verdicts (each `label` / `score` / `reason` + a `metrics` block of
raw numbers), a `stack` listing every tier with its `status` (`ran` / `skipped` /
`needs_input`), and a top-level `consensus`:

- **trust** — every verifier that ran agrees the site is on-manifold → clears the wet-lab bar.
- **weak** — judgeable but not confidently sound → iterate, don't synthesize yet.
- **defer** — off-manifold, or a verifier couldn't run → reject / needs a different check.

Consensus is defense-in-depth: a single `defer` collapses it. **Only `trust` is worth wet-lab.**

## The stack — what runs, and the numbers each tier reports
Returned under `stack` (cost order), each tier `ran` / `skipped` / `needs_input`:

| tier | runs | checks | key `metrics` |
| --- | --- | --- | --- |
| `geometry` | always (CPU) | M–donor bond lengths vs reference (z-score) + CN | `strain_sigma`, `cn`, `cn_modal` |
| `bond_valence` | always (CPU) | bond-valence sum vs formal charge | `bvs`, `formal_valence`, `delta` |
| `coord_symmetry` | always (CPU) | nVECSUM — is the metal enclosed, or one-sided? | `nvecsum` (0 = enclosed, →1 = lopsided) |
| `coord_geometry` | always (CPU) | polyhedron shape vs ideal (tet/sq-planar/oct/…) | `angle_rmsd_deg` |
| `mlip` | `deep=True` (GPU) | MACE relaxation — does the site hold? | `drift_angstrom`, `cn_before/after`, `interaction_energy_ev` |
| `mlip_md` | `deep=True` (GPU) | 300 K MD — does the shell survive? | `retention`, `cn_initial` |
| `mogul` | needs CSD licence | per-bond CSD geometry (Mogul) | — |
| `trs` | needs apo structure | topology reorganization on binding | — |
| `cofold` / `expression` / `thermostability` | needs a scorer | independent re-fold / ESM expression / Tm | — |

The four CPU tiers cover the static metal site to [CheckMyMetal](https://journals.iucr.org/m/issues/2024/05/00/be5298/) parity (lengths · valence · nVECSUM · geometry); the rest add physics, precedent, and protein-level checks when their inputs are available.

## Scope
The trust threshold is grounded in CSD geometry + physics, **not yet calibrated to wet-lab
outcomes** — read `trust` as "physically / precedent-plausible," not a calibrated binding
probability. Tiers needing a GPU (MLIP) or a licence (CSD/Mogul) report as `needs_input`
rather than guessing.
