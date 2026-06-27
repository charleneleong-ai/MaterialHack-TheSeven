# MaterialHack-TheSeven

## Topological Reorganization Score

This branch contains a standalone Python implementation of the Topological
Reorganization Score (TRS) for protein-metal binding.

TRS compares:

- `S(P)`: the protein residue structure before metal binding
- `S(P, M)`: the protein structure after binding, including optional metal nodes

For CCDC-style coordinate tables, use `calculate_3d_trs`. This compares the 3D
structures directly: every atom is a node with its exact `(x, y, z)` coordinate,
and contacts are inferred from distance cutoffs.

```python
from trs import calculate_3d_trs

before_table = """
1 OD1 0.0 0.0 0.0 O.co2 1 ASP276 0.0000
2 NZ  8.0 0.0 0.0 N.4   2 LYS293 1.0000
"""

after_table = """
1 OD1 0.0 0.0 0.0 O.co2 1 ASP276 0.0000
2 NZ  8.0 0.0 0.0 N.4   2 LYS293 1.0000
3 CA  2.4 0.0 0.0 Ca    3 CA506  0.0000
"""

result = calculate_3d_trs(before_table, after_table, metal_cutoff=3.0)
print(result.total)
print(result.components)
```

The expected atom-table columns are:

```text
atom_id atom_name x y z atom_type residue_index residue_name charge
```

Connectivity is still chemistry/contact-defined. Two atoms can both be present
and can both have exact coordinates, but they are disconnected unless their 3D
distance satisfies the contact rule. Metal-donor contacts use `metal_cutoff`;
other heavy-atom contacts use `contact_cutoff`.

The main API is:

```python
from trs import ProteinStructure, calculate_trs

before = ProteinStructure.from_edges(edges=[("A", "B"), ("B", "C")])
after = ProteinStructure.from_edges(
    edges=[("A", "B"), ("B", "C"), ("B", "ZN")],
    metal_nodes=["ZN"],
)

result = calculate_trs(before, after)
print(result.total)
print(result.components)
```

Implemented component terms:

- degree change
- local clustering change
- metal coordination number
- adjacency matrix change
- triangle count change
- average shortest path change
- Laplacian lambda2 change
- Laplacian spectrum change when lambda2 is approximately unchanged
- Laplacian matrix Frobenius norm change
- betweenness centrality change
- structure diameter change
- residue-residue edge distance change when coordinates are provided
- metal-residue angle penalty when ideal angles are provided
- metal betweenness centrality after binding

All component weights default to `1.0`. Pass a `weights` dictionary to tune the
importance of each term.

## Copper File Workflow

For copper structures saved as TRIPOS/MOL2-style files, place before/after files
under `data/copper`.

Supported layouts:

```text
data/copper/P1_before.mol2
data/copper/P1_after.mol2
```

or:

```text
data/copper/before/P1.mol2
data/copper/after/P1.mol2
```

Copper defaults:

- copper-donor cutoff: `2.8 A`
- donor atoms: `O`, `N`, `S`
- non-metal heavy-atom contact cutoff: `4.5 A`

Run the plotting workflow:

```powershell
python scripts/plot_copper_trs.py --input-dir data/copper --output-dir outputs/copper_trs --dpi 600
```

This writes:

- `outputs/copper_trs/copper_trs_scores.csv`
- `outputs/copper_trs/copper_trs_before_after_lines.png`
- `outputs/copper_trs/copper_trs_ranked_change.png`

The line plot uses `0` as the before-binding baseline and the after-binding
point as the computed TRS change. The ranked bar plot is usually the clearest
view for identifying which protein changed most.

## How TRS Can Be Used in Chemistry

For the LLM agent, TRS can act as an interpretable ranking and explanation tool
for protein-metal binding structures from a CCDC-linked database.

### Ranking Candidate Structures

A scientist might ask:

> Find zinc-binding proteins where the metal causes a big rearrangement around
> the active site.

The system can search candidate structures, build before/after 3D contact
structures, compute TRS, and rank the results:

- high TRS: large topological reorganization after binding
- low TRS: metal binds with less structural disruption

The LLM can then answer in scientific language:

> These candidates show strong zinc-induced reorganization. The highest score
> comes mainly from increased coordination number and shorter residue-residue
> paths near the metal.

### Explaining Binding Behavior

TRS components are interpretable, so the model can explain why a structure was
ranked highly. For example, it can report that:

- coordination number increased
- key residues became more connected
- shortest paths changed
- local clustering increased
- the metal became a communication hub

This matters because scientists usually need more than a score. They need a
reason for why a structure matches the query.

### Detecting Pocket Opening or Compaction

The clustering and triangle terms can help detect whether the binding pocket
became more compact or more open after metal binding.

Example scientist query:

> Find structures where copper binding opens space near the pocket.

The system can look for cases where local clustering or triangle density
decreases around the binding site, then return structures where binding
reorganizes the local geometry.

### Comparing Different Metals

TRS can compare how different metals affect similar proteins or binding motifs.

Example scientist query:

> Does zinc or magnesium reorganize this family more?

The system can compute:

```text
TRS(P, Zn), TRS(P, Mg), TRS(P, Fe)
```

The LLM can then summarize:

> Zinc gives the largest topology change, mostly through increased coordination
> and Laplacian connectivity change.

### Supporting Structure Design

For design tasks, high TRS is not always better. The desired score depends on
the scientist's goal:

- low TRS: useful when metal binding should not strongly disturb the protein
- high TRS: useful when metal binding should trigger a conformational or
  topological switch

This lets the LLM translate simple scientific language into different TRS
weighting and ranking strategies.

Run the example:

```powershell
python examples/trs_example.py
```

Run tests:

```powershell
python -m unittest
```
