# Copper Structure Inputs

Place copper before/after structure files here before running the plotting
script.

Supported layouts:

```text
data/copper/P1_before.mol2
data/copper/P1_after.mol2
data/copper/P2_before.mol2
data/copper/P2_after.mol2
```

or:

```text
data/copper/before/P1.mol2
data/copper/after/P1.mol2
data/copper/before/P2.mol2
data/copper/after/P2.mol2
```

The parser reads the `@<TRIPOS>ATOM` section from TRIPOS/MOL2-style files.

Copper defaults:

- copper-donor cutoff: `2.8 A`
- donor atoms: `O`, `N`, `S`
- non-metal heavy-atom contact cutoff: `4.5 A`

Run:

```powershell
python scripts/plot_copper_trs.py --input-dir data/copper --output-dir outputs/copper_trs --dpi 600
```

Outputs:

- `outputs/copper_trs/copper_trs_scores.csv`
- `outputs/copper_trs/copper_trs_before_after_lines.png`
- `outputs/copper_trs/copper_trs_ranked_change.png`
