"""PCB file writer.  Given a Design + expanded ResolvedComponent list,
writes a valid KiCad 10 .kicad_pcb file."""

from __future__ import annotations

import copy
import uuid
from pathlib import Path
from typing import Iterable, List, Optional

# Apply the KiCad 10 net-format patch on import so any Board.from_file
# we might do internally succeeds.
from kicad_yaml import kicad_net_patch  # noqa: F401

from kiutils.board import Board as KiBoard
from kiutils.footprint import Footprint
from kiutils.items.common import Net, Position
from kiutils.items.gritems import GrLine

from kicad_yaml.layout import ResolvedComponent, resolve_rotation_for_layer
from kicad_yaml.libraries import LibraryResolver
from kicad_yaml.schema import Design, Layer
from kicad_yaml.topology import SheetTopology


EDGE_WIDTH_MM = 0.15


def qualify_net_name(
    net_name: str,
    *,
    sheet_id: str,
    design: Design,
    topology: Optional[SheetTopology],
) -> str:
    """Return KiCad's hierarchical net name for ``net_name`` as it appears
    on ``sheet_id``.

    Rules:
      - Globals (``design.global_nets``) pass through unchanged.
      - For non-root sheets, if the net is exposed via the sheet's parent
        pin_map, the electrical net is the parent-side name; we recurse
        until we reach a sheet where the name is local.  The qualified
        form is ``/name`` when that terminal sheet is the root, and
        ``/path/to/sheet/name`` when it's a non-root sheet.
      - Unexposed locals get ``/sheet_path/name`` with the sheet's path.
    """
    if net_name in design.global_nets:
        return net_name
    if topology is None:
        # Flat case: treat everything as a root-local net with a leading slash.
        return f"/{net_name}"

    current_sheet = sheet_id
    current_net = net_name
    # Walk up the tree: while the net is exposed by this sheet's parent,
    # rename it to the parent-side name and move to the parent.
    while True:
        pin_map = topology.parent_pin_map(current_sheet)
        inverted = {child: parent for parent, child in pin_map.items()}
        if current_net in inverted:
            current_net = inverted[current_net]
            parent = topology.parent_of(current_sheet)
            if parent is None:
                break
            current_sheet = parent
            continue
        break

    if current_sheet == topology.root:
        return f"/{current_net}"
    # Non-root terminal sheet: prefix with the sheet path (skip root).
    path = "/".join(topology.sheet_path(current_sheet)[1:])
    return f"/{path}/{current_net}"


def write_pcb(
    design: Design,
    resolved: List[ResolvedComponent],
    net_order: List[str],
    output: Path,
    *,
    libraries: Optional[LibraryResolver] = None,
    topology: Optional[SheetTopology] = None,
) -> None:
    """Write a full .kicad_pcb file from a design and its expanded parts.

    ``net_order`` is the canonical list of user nets; we assign consecutive
    net numbers starting at 1 (0 is reserved for "no net").
    """
    board = KiBoard.create_new()
    _set_outline(board, design)
    _set_net_table(board, net_order)

    if resolved and libraries is None:
        libraries = LibraryResolver()
    for rc in resolved:
        fp = _place_footprint(rc, libraries, net_order, design, topology)
        board.footprints.append(fp)

    board.to_file(str(output))


def _set_outline(board: KiBoard, design: Design) -> None:
    w, h = design.board.size
    corners = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h), (0.0, 0.0)]
    for (x1, y1), (x2, y2) in zip(corners, corners[1:]):
        board.graphicItems.append(
            GrLine(
                start=Position(X=x1, Y=y1),
                end=Position(X=x2, Y=y2),
                layer="Edge.Cuts",
                width=EDGE_WIDTH_MM,
                tstamp=str(uuid.uuid4()),
            )
        )


def _set_net_table(board: KiBoard, net_order: Iterable[str]) -> None:
    board.nets = [Net(number=0, name="")]
    for i, name in enumerate(net_order, start=1):
        board.nets.append(Net(number=i, name=name))


def _place_footprint(
    rc: ResolvedComponent,
    libraries: LibraryResolver,
    net_order: List[str],
    design: Design,
    topology: Optional[SheetTopology],
) -> Footprint:
    template = libraries.footprint(rc.footprint_lib_name)
    fp = copy.deepcopy(template)
    angle = resolve_rotation_for_layer(rc.pcb_rotation, rc.pcb_layer)
    fp.position = Position(X=rc.pcb_position[0], Y=rc.pcb_position[1], angle=angle)
    if rc.pcb_layer is Layer.BACK:
        flip_footprint_to_back(fp)
    if fp.properties is None:
        fp.properties = {}
    fp.properties["Reference"] = rc.ref
    fp.properties["Value"] = rc.value

    net_index = {name: i + 1 for i, name in enumerate(net_order)}
    for pad in fp.pads:
        if pad.number in rc.pin_nets:
            raw_name = rc.pin_nets[pad.number]
            qualified = qualify_net_name(
                raw_name,
                sheet_id=rc.sheet_id,
                design=design,
                topology=topology,
            )
            if qualified not in net_index:
                continue   # defensive — net_order should already contain it
            pad.net = Net(number=net_index[qualified], name=qualified)
    if hasattr(fp, "tstamp"):
        fp.tstamp = str(uuid.uuid4())
    return fp


def _flip_layer(layer: str) -> str:
    if layer and layer.startswith("F."):
        return "B." + layer[2:]
    if layer and layer.startswith("B."):
        return "F." + layer[2:]
    return layer


def flip_footprint_to_back(fp: Footprint) -> None:
    """Remap F.* → B.* on every sub-item and set mirrored text effects."""
    fp.layer = _flip_layer(fp.layer)
    for pad in fp.pads:
        pad.layers = [_flip_layer(l) for l in pad.layers]
    for g in fp.graphicItems or []:
        if hasattr(g, "layer") and g.layer:
            g.layer = _flip_layer(g.layer)
        if type(g).__name__ == "FpText" and getattr(g, "effects", None):
            justify = g.effects.justify
            if justify is not None:
                justify.mirror = True
