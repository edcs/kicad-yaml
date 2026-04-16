"""Sync PCB positions back into the design YAML.

Reads a .kicad_pcb file, compares footprint positions against the design
YAML, and updates the YAML in-place for any explicit components that moved.
Grid-derived components are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from kicad_yaml import kicad_net_patch  # noqa: F401
from kicad_yaml import kicad_property_patch  # noqa: F401


@dataclass
class FootprintPosition:
    """Position data for a single footprint read from a .kicad_pcb."""

    x: float
    y: float
    angle: float    # stored KiCad angle (0 if rotation was baked)
    layer: str      # "F.Cu" or "B.Cu"


def read_pcb_positions(pcb_path: Path) -> Dict[str, FootprintPosition]:
    """Read all footprint positions from a .kicad_pcb file.

    Returns a dict mapping reference designator to FootprintPosition.
    Raises FileNotFoundError if the PCB file doesn't exist.
    """
    from kiutils.board import Board as KiBoard

    if not pcb_path.exists():
        raise FileNotFoundError(f"PCB file not found: {pcb_path}")

    board = KiBoard.from_file(str(pcb_path))
    positions: Dict[str, FootprintPosition] = {}
    for fp in board.footprints:
        ref = (fp.properties or {}).get("Reference")
        if ref is None:
            continue
        pos = fp.position
        positions[ref] = FootprintPosition(
            x=pos.X if pos else 0.0,
            y=pos.Y if pos else 0.0,
            angle=pos.angle if pos and pos.angle else 0.0,
            layer=fp.layer or "F.Cu",
        )
    return positions


def recover_user_rotation(
    stored_angle: float,
    yaml_rotation: float,
    layer: str,
) -> float:
    """Convert a stored PCB angle delta back to user-facing CCW rotation.

    kicad-yaml bakes rotation into pad coordinates and zeros the stored
    angle.  Any non-zero stored angle is a delta the user added in KiCad.

    Args:
        stored_angle: The footprint's position.angle from the .kicad_pcb.
        yaml_rotation: The current rotation value from design.yaml (user CCW).
        layer: Footprint layer string ("F.Cu" or "B.Cu").

    Returns:
        The new user-facing CCW rotation (0-360).
    """
    if layer == "F.Cu":
        delta = stored_angle % 360.0
    else:
        delta = (-stored_angle) % 360.0
    return (yaml_rotation + delta) % 360.0
