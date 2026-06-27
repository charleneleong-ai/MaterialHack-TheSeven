"""Topological Reorganization Score (TRS) tools."""

from .topological_reorganization_score import (
    AtomRecord,
    AtomStructure,
    ProteinStructure,
    TRSComponents,
    TRSResult,
    calculate_3d_trs,
    calculate_copper_trs_from_files,
    calculate_trs,
    structure_from_3d_coordinates,
)

__all__ = [
    "AtomRecord",
    "AtomStructure",
    "ProteinStructure",
    "TRSComponents",
    "TRSResult",
    "calculate_3d_trs",
    "calculate_copper_trs_from_files",
    "calculate_trs",
    "structure_from_3d_coordinates",
]
