"""Sync PCB positions back into the design YAML.

Reads a .kicad_pcb file, compares footprint positions against the design
YAML, and updates the YAML in-place for any explicit components that moved.
Grid-derived components are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from ruamel.yaml import YAML

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


@dataclass
class PositionChange:
    """Describes a single component's position/rotation change."""
    ref: str
    old_position: tuple
    new_position: tuple
    old_rotation: float
    new_rotation: float


@dataclass
class SyncOutcome:
    """Result of a sync operation."""
    changes: List[PositionChange]
    missing_refs: List[str]    # refs in YAML but not in PCB


# Tolerances for detecting meaningful changes
_POS_TOL = 0.001     # mm
_ROT_TOL = 0.1       # degrees


def _format_value(v: float) -> float:
    """Round a position value to 3 decimal places.
    Return int-like floats cleanly (e.g. 25.0 not 25.000)."""
    rounded = round(v, 3)
    if rounded == int(rounded):
        return float(int(rounded))
    return rounded


def _format_rotation(v: float) -> float:
    """Round rotation to 1 decimal place."""
    rounded = round(v, 1)
    if rounded == int(rounded):
        return float(int(rounded))
    return rounded


def sync_positions(
    yaml_path: Path,
    pcb_path: Path,
) -> SyncOutcome:
    """Sync explicit component positions from a .kicad_pcb into design YAML.

    Reads the PCB, compares positions against the YAML, and updates the
    YAML in-place for any explicit components that moved. Grid-derived
    components are skipped.

    Args:
        yaml_path: Path to the design.yaml file.
        pcb_path: Path to the .kicad_pcb file.

    Returns:
        SyncOutcome with changes made and any missing refs.
    """
    pcb_positions = read_pcb_positions(pcb_path)

    # Load YAML with round-trip mode to preserve formatting.
    # indent() settings match the project convention (2-space mapping,
    # 4-space sequence with 2-offset dash) so the emitter doesn't
    # reformat untouched lines.
    rt_yaml = YAML(typ="rt")
    rt_yaml.preserve_quotes = True
    rt_yaml.indent(mapping=2, sequence=4, offset=2)
    doc = rt_yaml.load(yaml_path)

    changes: List[PositionChange] = []
    missing_refs: List[str] = []

    for sheet_name, sheet_data in doc["sheets"].items():
        components = sheet_data.get("components")
        if not components:
            continue
        for comp in components:
            ref = str(comp["ref"])
            if ref not in pcb_positions:
                missing_refs.append(ref)
                continue

            pcb = pcb_positions[ref]
            yaml_pcb = comp["pcb"]
            yaml_pos = yaml_pcb["position"]
            old_x, old_y = float(yaml_pos[0]), float(yaml_pos[1])
            old_rot = float(yaml_pcb.get("rotation", 0.0))

            layer = pcb.layer
            new_rot = recover_user_rotation(pcb.angle, old_rot, layer)

            new_x = _format_value(pcb.x)
            new_y = _format_value(pcb.y)
            new_rot = _format_rotation(new_rot)

            pos_changed = (
                abs(new_x - old_x) > _POS_TOL
                or abs(new_y - old_y) > _POS_TOL
            )
            rot_changed = abs(new_rot - old_rot) > _ROT_TOL

            if not pos_changed and not rot_changed:
                continue

            if pos_changed:
                yaml_pos[0] = new_x
                yaml_pos[1] = new_y

            if rot_changed:
                if new_rot == 0.0:
                    yaml_pcb.pop("rotation", None)
                else:
                    yaml_pcb["rotation"] = new_rot

            changes.append(PositionChange(
                ref=ref,
                old_position=(old_x, old_y),
                new_position=(new_x, new_y),
                old_rotation=old_rot,
                new_rotation=new_rot,
            ))

    if changes:
        rt_yaml.dump(doc, yaml_path)

    return SyncOutcome(changes=changes, missing_refs=missing_refs)
