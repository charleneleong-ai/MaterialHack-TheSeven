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

- `metal`: target label, e.g. `"Ni2+"`, `"Cu2+"`, `"Co2+"`.
- `deep=True`: add MLIP (MACE) relaxation + 300 K MD — needs a GPU; default is the instant
  geometry + bond-valence check, which runs anywhere.
- `stress=True`: add a robustness map (`neutral` / `leachate` / `low_pH`) — does the site
  hold up under acidic-leachate / low-pH operating conditions?

## Reading the result
A JSON dict with per-tier verdicts (each `label` / `score` / `reason` + a `metrics` block of
raw numbers), a `stack` listing every tier with its `status` (`ran` / `skipped` /
`needs_input`), and a top-level `consensus`:

- **trust** — every verifier that ran agrees the site is on-manifold → clears the wet-lab bar.
- **weak** — judgeable but not confidently sound → iterate, don't synthesize yet.
- **defer** — off-manifold, or a verifier couldn't run → reject / needs a different check.

Consensus is defense-in-depth: a single `defer` collapses it. **Only `trust` is worth wet-lab.**

## Scope
The trust threshold is grounded in CSD geometry + physics, **not yet calibrated to wet-lab
outcomes** — read `trust` as "physically / precedent-plausible," not a calibrated binding
probability. Tiers needing a GPU (MLIP) or a licence (CSD/Mogul) report as `needs_input`
rather than guessing.
