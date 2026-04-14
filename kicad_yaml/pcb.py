"""PCB file writer.  Given a Design + expanded ResolvedComponent list,
writes a valid KiCad 10 .kicad_pcb file."""

from __future__ import annotations

import copy
import math
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
from kicad_yaml.schema import BoardZone, Design, Layer
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
    existing_tracks = _read_existing_tracks(output)

    board = KiBoard.create_new()
    _set_outline(board, design)
    _set_net_table(board, net_order)

    net_index = {name: i + 1 for i, name in enumerate(net_order)}
    for zone_def in design.board.zones:
        board.zones.append(
            _board_zone_to_ki_zone(zone_def, net_index, design, topology)
        )

    if resolved and libraries is None:
        libraries = LibraryResolver()
    for rc in resolved:
        fp = _place_footprint(rc, libraries, net_order, design, topology)
        # kiutils serialises footprint zones with (net 0) which KiCad
        # misinterprets as board-level zones at raw local coords.  Extract
        # them, convert to absolute coordinates, and add as board zones.
        if fp.zones:
            for zone in fp.zones:
                _zone_to_board_coords(zone, fp.position, rc.pcb_layer)
                zone.tstamp = str(uuid.uuid4())
                board.zones.append(zone)
            fp.zones = []
        board.footprints.append(fp)

    if existing_tracks:
        board.traceItems = existing_tracks

    board.to_file(str(output))


def _read_existing_tracks(output: Path) -> list:
    """Return all trace items (segments, arcs, vias) from an existing PCB file.

    Called before the file is overwritten so that manually routed traces
    survive a rebuild.  Returns an empty list if the file does not exist
    or cannot be parsed.
    """
    if not output.exists():
        return []
    try:
        old_board = KiBoard.from_file(str(output))
        return list(old_board.traceItems or [])
    except Exception:
        return []


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


def _zone_to_board_coords(
    zone, fp_pos: Position, layer: Layer
) -> None:
    """Convert a footprint-local zone to board-level absolute coordinates."""
    angle_rad = math.radians(fp_pos.angle or 0)
    mirror_x = layer is Layer.BACK
    if mirror_x:
        zone.layers = [_flip_layer(l) for l in zone.layers]
    for poly in zone.polygons or []:
        for pt in poly.coordinates or []:
            lx, ly = pt.X, pt.Y
            if mirror_x:
                lx = -lx
            # Apply rotation
            rx = lx * math.cos(angle_rad) - ly * math.sin(angle_rad)
            ry = lx * math.sin(angle_rad) + ly * math.cos(angle_rad)
            pt.X = fp_pos.X + rx
            pt.Y = fp_pos.Y + ry


def _flip_layer(layer: str) -> str:
    if layer and layer.startswith("F."):
        return "B." + layer[2:]
    if layer and layer.startswith("B."):
        return "F." + layer[2:]
    return layer


def _board_zone_to_ki_zone(
    zone_def: BoardZone,
    net_index: dict,
    design: Design,
    topology: Optional[SheetTopology],
):
    """Convert a schema BoardZone to a kiutils Zone for the board."""
    from kiutils.items.zones import Zone as KiZone
    from kiutils.items.zones import ZonePolygon as KiZonePolygon
    from kiutils.items.zones import FillSettings, Hatch

    qualified = qualify_net_name(
        zone_def.net,
        sheet_id="main",
        design=design,
        topology=topology,
    )
    net_num = net_index.get(qualified, 0)
    net_name = qualified if net_num else zone_def.net

    coords = [Position(X=x, Y=y) for x, y in zone_def.polygon]
    ki_poly = KiZonePolygon(coordinates=coords)

    return KiZone(
        net=net_num,
        netName=net_name,
        layers=[zone_def.layer],
        tstamp=str(uuid.uuid4()),
        name=zone_def.name,
        priority=zone_def.priority or None,
        clearance=zone_def.clearance,
        minThickness=zone_def.min_thickness,
        hatch=Hatch(style="edge", pitch=0.508),
        fillSettings=FillSettings(
            yes=False,
            thermalGap=zone_def.clearance,
            thermalBridgeWidth=0.5,
        ),
        polygons=[ki_poly],
        filledPolygons=[],
    )


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
