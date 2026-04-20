"""Sync PCB positions back into the design YAML.

Reads a .kicad_pcb file, compares footprint positions against the design
YAML, and updates the YAML in-place for any explicit components that moved.
Grid-derived components are skipped.
"""

from __future__ import annotations


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
