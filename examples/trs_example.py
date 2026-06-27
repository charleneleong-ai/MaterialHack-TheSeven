from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trs import ProteinStructure, calculate_trs


before = ProteinStructure.from_edges(
    edges=[
        ("A", "B"),
        ("B", "C"),
        ("C", "D"),
    ],
    coordinates={
        "A": (0.0, 0.0, 0.0),
        "B": (1.0, 0.0, 0.0),
        "C": (2.0, 0.0, 0.0),
        "D": (3.0, 0.0, 0.0),
    },
)

after = ProteinStructure.from_edges(
    edges=[
        ("A", "B"),
        ("B", "C"),
        ("C", "D"),
        ("B", "ZN"),
        ("C", "ZN"),
        ("B", "D"),
    ],
    coordinates={
        "A": (0.0, 0.0, 0.0),
        "B": (1.0, 0.1, 0.0),
        "C": (2.0, -0.1, 0.0),
        "D": (3.0, 0.0, 0.0),
        "ZN": (1.5, 0.0, 0.0),
    },
    metal_nodes=["ZN"],
)

result = calculate_trs(after=after, before=before, default_ideal_angle=109.5)

print(f"TRS total: {result.total:.4f}")
print(result.components)
