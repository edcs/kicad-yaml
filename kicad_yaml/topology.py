# kicad_yaml/topology.py
"""Sheet-tree walker: answers parent/child/path/UUID questions about a
multi-sheet design.  Pure data — no kiutils imports.  Used by the
loader's semantic pass, the schematic writer, and the PCB writer.
"""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from kicad_yaml.schema import Design


class TopologyError(ValueError):
    """Raised when the sheet tree is invalid (cycles, dangling refs, etc.)."""


@dataclass
class SheetTopology:
    """Immutable snapshot of a design's sheet tree.

    Attributes after construction:
        root: the ID of the root sheet (always "main").
        parent: child sheet_id -> parent sheet_id (root has no entry).
        children: parent sheet_id -> list of child sheet_ids (ordered).
        uuids: sheet_id -> freshly generated UUID string.
        pin_maps: child sheet_id -> pin_map (parent_net -> child_net).
    """
    root: str
    parent: Dict[str, str] = field(default_factory=dict)
    children: Dict[str, List[str]] = field(default_factory=dict)
    uuids: Dict[str, str] = field(default_factory=dict)
    pin_maps: Dict[str, Dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_design(cls, design: Design) -> "SheetTopology":
        topo = cls(root="main")

        for sheet_id in design.sheets:
            topo.uuids[sheet_id] = str(_uuid.uuid4())
            topo.children[sheet_id] = []

        for parent_id, sheet in design.sheets.items():
            for sub in sheet.subsheets:
                child_id = sub.sheet_id
                if child_id not in design.sheets:
                    raise TopologyError(
                        f"sheets.{parent_id}.subsheets: unknown subsheet "
                        f"'{child_id}' — not defined in sheets:"
                    )
                if child_id in topo.parent:
                    raise TopologyError(
                        f"sheet '{child_id}' has multiple parents "
                        f"('{topo.parent[child_id]}' and '{parent_id}')"
                    )
                if child_id == "main":
                    raise TopologyError(
                        f"sheets.{parent_id}.subsheets: cycle detected — "
                        f"'main' is the root and cannot be a subsheet"
                    )
                topo.parent[child_id] = parent_id
                topo.children[parent_id].append(child_id)
                topo.pin_maps[child_id] = dict(sub.pin_map)

        # Cycle check via DFS from root.
        visited: Set[str] = set()
        stack: List[str] = ["main"]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            stack.extend(topo.children.get(node, []))

        # Any sheet not reachable from main is either unreferenced (orphan)
        # or part of a cycle.  Walk up the parent chain looking for a cycle.
        for sheet_id in design.sheets:
            if sheet_id in visited:
                continue
            seen: Set[str] = set()
            cursor = sheet_id
            found_main = False
            while cursor in topo.parent:
                if cursor in seen:
                    raise TopologyError(
                        f"sheet tree contains a cycle involving '{sheet_id}'"
                    )
                seen.add(cursor)
                cursor = topo.parent[cursor]
                if cursor == "main":
                    found_main = True
                    break
            if not found_main and sheet_id != "main":
                raise TopologyError(
                    f"sheet '{sheet_id}' is defined but not referenced "
                    f"by any subsheets declaration"
                )
        return topo

    def all_sheets(self) -> List[str]:
        return list(self.uuids.keys())

    def parent_of(self, sheet_id: str) -> Optional[str]:
        return self.parent.get(sheet_id)

    def children_of(self, sheet_id: str) -> List[str]:
        return list(self.children.get(sheet_id, []))

    def uuid_for(self, sheet_id: str) -> str:
        return self.uuids[sheet_id]

    def sheet_path(self, sheet_id: str) -> List[str]:
        """Return the list of sheet ids from root to sheet_id (inclusive)."""
        chain: List[str] = []
        cursor: Optional[str] = sheet_id
        while cursor is not None:
            chain.append(cursor)
            cursor = self.parent.get(cursor)
        chain.reverse()
        return chain

    def sheet_uuid_path(self, sheet_id: str) -> List[str]:
        return [self.uuids[s] for s in self.sheet_path(sheet_id)]

    def sheet_instance_path(self, sheet_id: str) -> str:
        """KiCad's sheetInstancePath format: ``/uuid1/uuid2/...``."""
        return "/" + "/".join(self.sheet_uuid_path(sheet_id))

    def parent_pin_map(self, sheet_id: str) -> Dict[str, str]:
        return dict(self.pin_maps.get(sheet_id, {}))

    def exposed_nets_for_sheet(self, sheet_id: str) -> Set[str]:
        """Return the set of child-side net names (values in pin_map) that
        cross this sheet's boundary via its parent."""
        return set(self.pin_maps.get(sheet_id, {}).values())
