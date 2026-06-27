"""Calculate and plot copper TRS scores from before/after structure files.

Expected directory layouts:

1. One directory with paired files:
   data/copper/P1_before.mol2
   data/copper/P1_after.mol2

2. Separate directories:
   data/copper/before/P1.mol2
   data/copper/after/P1.mol2

3. Current CIF layout:
   data/copper/before binding/1BUG_apo.cif
   data/copper/after binding/1bug.cif
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from pathlib import Path
import sys

import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trs import calculate_copper_trs_from_files


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot copper TRS scores for structure pairs.")
    parser.add_argument("--input-dir", default="data/copper", help="Directory containing copper before/after files.")
    parser.add_argument("--output-dir", default="plot_results", help="Directory for CSV and high-resolution plots.")
    parser.add_argument("--dpi", type=int, default=600, help="Output plot resolution.")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pairs = find_structure_pairs(input_dir)
    if not pairs:
        raise SystemExit(
            "No before/after pairs found. Use P1_before.mol2 + P1_after.mol2, "
            "or before/P1.mol2 + after/P1.mol2."
        )

    rows = []
    for protein_id, before_path, after_path in pairs:
        result = calculate_copper_trs_from_files(before_path, after_path)
        rows.append(
            {
                "protein": protein_id,
                "before_file": str(before_path),
                "after_file": str(after_path),
                "trs_score": result.total,
                **asdict(result.components),
            }
        )

    write_summary_csv(rows, output_dir / "copper_trs_scores.csv")
    plot_before_after_lines(rows, output_dir / "copper_trs_before_after_lines.png", dpi=args.dpi)
    plot_ranked_trs(rows, output_dir / "copper_trs_ranked_change.png", dpi=args.dpi)

    print(f"Processed {len(rows)} copper structure pair(s).")
    print(f"Saved results to {output_dir.resolve()}")


def find_structure_pairs(input_dir: Path) -> list[tuple[str, Path, Path]]:
    suffixes = {".cif", ".mol2", ".txt", ".sdf"}
    pairs: list[tuple[str, Path, Path]] = []

    directory_pairs = [
        (input_dir / "before", input_dir / "after"),
        (input_dir / "before binding", input_dir / "after binding"),
    ]
    for before_dir, after_dir in directory_pairs:
        if not before_dir.is_dir() or not after_dir.is_dir():
            continue
        after_by_id = {
            normalize_protein_id(after_path.stem): after_path
            for after_path in after_dir.iterdir()
            if after_path.suffix.lower() in suffixes
        }
        for before_path in sorted(p for p in before_dir.iterdir() if p.suffix.lower() in suffixes):
            protein_id = normalize_protein_id(before_path.stem)
            after_path = after_by_id.get(protein_id)
            if after_path:
                pairs.append((protein_id.upper(), before_path, after_path))

    for before_path in sorted(input_dir.glob("*_before.*")):
        if before_path.suffix.lower() not in suffixes:
            continue
        protein_id = before_path.stem.removesuffix("_before")
        after_path = before_path.with_name(f"{protein_id}_after{before_path.suffix}")
        if after_path.exists():
            pairs.append((protein_id, before_path, after_path))

    seen = set()
    unique_pairs = []
    for protein_id, before_path, after_path in pairs:
        key = (protein_id, before_path.resolve(), after_path.resolve())
        if key not in seen:
            seen.add(key)
            unique_pairs.append((protein_id, before_path, after_path))
    return unique_pairs


def normalize_protein_id(name: str) -> str:
    normalized = name.lower()
    for suffix in ("_apo", "-apo", "_before", "-before", "_after", "-after"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]
    return normalized


def write_summary_csv(rows: list[dict[str, object]], output_path: Path) -> None:
    fieldnames = list(rows[0])
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def plot_before_after_lines(rows: list[dict[str, object]], output_path: Path, dpi: int) -> None:
    proteins = [str(row["protein"]) for row in rows]
    scores = [float(row["trs_score"]) for row in rows]
    x_positions = range(len(proteins))

    fig, ax = plt.subplots(figsize=(max(8, len(proteins) * 0.8), 5.5))
    for x_position, score in zip(x_positions, scores):
        ax.plot([x_position, x_position], [0, score], color="#4C78A8", linewidth=2.2, alpha=0.8)
        ax.scatter([x_position], [0], color="#72B7B2", s=55, label="Before baseline" if x_position == 0 else "")
        ax.scatter([x_position], [score], color="#E45756", s=70, label="After binding TRS" if x_position == 0 else "")

    ax.set_xticks(list(x_positions), proteins, rotation=35, ha="right")
    ax.set_ylabel("TRS score")
    ax.set_xlabel("Protein")
    ax.set_title("Copper-Induced Structural Change by Protein")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def plot_ranked_trs(rows: list[dict[str, object]], output_path: Path, dpi: int) -> None:
    sorted_rows = sorted(rows, key=lambda row: float(row["trs_score"]), reverse=True)
    proteins = [str(row["protein"]) for row in sorted_rows]
    scores = [float(row["trs_score"]) for row in sorted_rows]

    fig, ax = plt.subplots(figsize=(max(8, len(proteins) * 0.8), 5.5))
    ax.bar(proteins, scores, color="#5B8C5A")
    ax.set_ylabel("TRS score")
    ax.set_xlabel("Protein")
    ax.set_title("Proteins Ranked by Copper-Induced Structural Change")
    ax.tick_params(axis="x", rotation=35)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
