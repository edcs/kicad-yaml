"""Keep the KiCad ``.kicad_pro`` file's sheet registry in sync with the
schematics kicad-yaml just generated.

KiCad's Project Manager only lists schematics that appear in the
``sheets`` array (and the root must match ``schematic.top_level_sheets``).
If we don't update those entries, the newly generated child sheets stay
hidden in the project tree even though the files exist on disk.

This module is intentionally conservative: it only touches keys that
matter for schematic discovery, and it only runs when the ``.kicad_pro``
file already exists.  Creating a fresh project file from scratch is
KiCad's job — we just keep it honest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple


def sync_sheet_registry(
    project_path: Path,
    *,
    project_name: str,
    root_sheet: Tuple[str, str],
    all_sheets: List[Tuple[str, str]],
) -> None:
    """Rewrite ``sheets`` and ``schematic.top_level_sheets`` in place.

    Args:
        project_path: path to the ``.kicad_pro`` file (may not exist).
        project_name: used as ``top_level_sheets[].name``.
        root_sheet: ``(uuid, filename)`` for the root schematic.
        all_sheets: every generated schematic as ``(uuid, filename)``.
            The root should be included; order is preserved.

    Silently returns if the file doesn't exist or isn't valid JSON.
    """
    if not project_path.exists():
        return
    try:
        data = json.loads(project_path.read_text())
    except (OSError, json.JSONDecodeError):
        return

    if not isinstance(data, dict):
        return

    data["sheets"] = [[uuid, fname] for (uuid, fname) in all_sheets]

    root_uuid, root_filename = root_sheet
    schematic = data.setdefault("schematic", {})
    schematic["top_level_sheets"] = [{
        "filename": root_filename,
        "name": project_name,
        "uuid": root_uuid,
    }]

    project_path.write_text(json.dumps(data, indent=2) + "\n")
