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
# Preserve footprint property position/layer/effects across the kiutils
# parse → write cycle; otherwise references drift off-board.
from kicad_yaml import kicad_property_patch  # noqa: F401

from kiutils.board import Board as KiBoard
from kiutils.footprint import Footprint
from kiutils.items.common import Net, Position
from kiutils.items.gritems import GrLine

from kicad_yaml.layout import ResolvedComponent, ResolvedVia, resolve_rotation_for_layer
from kicad_yaml.libraries import LibraryResolver
from kicad_yaml.schema import BoardZone, Design, Layer, format_version_for
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
    vias: Optional[List[ResolvedVia]] = None,
) -> List[ResolvedVia]:
    """Write a full .kicad_pcb file from a design and its expanded parts.

    ``net_order`` is the canonical list of user nets; we assign consecutive
    net numbers starting at 1 (0 is reserved for "no net").

    Returns the list of vias that were *skipped* because their position
    would collide with a back-side pad.  Callers can surface these as
    build warnings so the user can patch the design by hand.
    """
    existing_tracks = _read_existing_tracks(output)

    board = KiBoard.create_new()
    board.version = format_version_for(design.project)
    _set_outline(board, design)
    _set_net_table(board, net_order)

    net_index = {name: i + 1 for i, name in enumerate(net_order)}
    for zone_def in design.board.zones:
        board.zones.append(
            _board_zone_to_ki_zone(zone_def, net_index, design, topology)
        )

    if (resolved or vias) and libraries is None:
        libraries = LibraryResolver()
    for rc in resolved:
        fp = _place_footprint(rc, libraries, net_order, design, topology)
        # kiutils serialises footprint zones with (net 0) which KiCad
        # misinterprets as board-level zones at raw local coords.  Extract
        # them, convert to absolute coordinates, and add as board zones.
        # If the component opts into ``suppress_keepouts``, drop any zones
        # that are rule areas (the ESP32 antenna keepout is the canonical
        # example) but keep ordinary copper zones.
        if fp.zones:
            for zone in fp.zones:
                if rc.suppress_keepouts and _is_keepout_zone(zone):
                    continue
                _zone_to_board_coords(zone, fp.position, rc.pcb_layer)
                zone.tstamp = str(uuid.uuid4())
                board.zones.append(zone)
            fp.zones = []
        board.footprints.append(fp)

    # Positions that will be (re)generated by vias_per_cell this build.
    # Any preserved via at one of these positions is stale — drop it before
    # appending the freshly generated ones, otherwise every rebuild doubles
    # the via count.
    auto_via_positions = set()
    if vias:
        for v in vias:
            auto_via_positions.add(
                (round(v.position[0], 3), round(v.position[1], 3))
            )

    if existing_tracks:
        board.traceItems = _sanitise_preserved_traceitems(
            existing_tracks, net_index, auto_via_positions
        )

    skipped_vias: List[ResolvedVia] = []
    if vias:
        keepouts = _back_side_pad_keepouts(resolved, libraries)
        for v in vias:
            via_clearance = v.size / 2.0 + 0.15
            if _point_in_any_keepout(v.position, via_clearance, keepouts):
                skipped_vias.append(v)
                continue
            ki_via = _resolved_via_to_ki_via(v, net_index, design, topology)
            if ki_via is not None:
                board.traceItems.append(ki_via)

    board.to_file(str(output))
    return skipped_vias


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


def _sanitise_preserved_traceitems(
    items: list,
    net_index: dict,
    auto_via_positions: set,
) -> list:
    """Clean up trace items read from an existing .kicad_pcb for re-write.

    - Skip any via whose position matches an auto-generated stitching via's
      target position (within 0.001 mm).  Those are stale copies that the
      current build is about to regenerate.
    - Coerce each item's ``net`` field to the integer index of the current
      net table.  KiCad 10 sometimes writes ``(net "NAME")`` short-form;
      kiutils parses it as a string, and writing that back as an unquoted
      symbol corrupts the file if the name contains ``/`` or other
      characters.  Look the name up in the freshly built net table and
      store the int.
    - Fill in any empty ``tstamp`` with a fresh UUID.  kiutils' writer
      happily emits ``(tstamp )`` with no value when the field is blank,
      which KiCad 10 rejects.
    - Strip the bare ``(free)`` token from vias — KiCad 10 expects either
      ``(free yes)`` or the token omitted; the default kiutils output is
      a bare ``(free)`` which parses as unterminated.
    """
    out = []
    for item in items:
        type_name = type(item).__name__

        # Drop auto-regenerated vias
        if type_name == "Via" and getattr(item, "position", None) is not None:
            key = (round(item.position.X, 3), round(item.position.Y, 3))
            if key in auto_via_positions:
                continue

        # Normalise .net from string → int where possible
        net_attr = getattr(item, "net", None)
        if isinstance(net_attr, str):
            item.net = net_index.get(net_attr, 0)

        # Fresh tstamp if blank
        ts = getattr(item, "tstamp", None)
        if ts is None or (isinstance(ts, str) and not ts.strip()):
            try:
                item.tstamp = str(uuid.uuid4())
            except AttributeError:
                pass

        # Strip malformed ``free`` token on vias
        if type_name == "Via" and hasattr(item, "free"):
            try:
                item.free = None
            except AttributeError:
                pass

        out.append(item)
    return out


def _is_keepout_zone(zone) -> bool:
    """True if the zone is a KiCad rule area (keepout), not a copper fill.

    kiutils models this via the ``keepoutSettings`` attribute: present on
    keepout zones, ``None`` on regular filled zones.
    """
    return getattr(zone, "keepoutSettings", None) is not None


def _back_side_pad_keepouts(
    resolved: List[ResolvedComponent],
    libraries: Optional[LibraryResolver],
) -> List[tuple]:
    """Return axis-aligned keepout rectangles (xmin, ymin, xmax, ymax) in
    board coordinates around every pad on every back-side component.

    Used to reject stitching vias that would punch through a back-side
    component's pad.  A conservative bounding box per pad + a small
    clearance envelope is enough — via diameters and pad sizes are both
    small relative to the cell pitch.
    """
    if not libraries:
        return []
    rects: List[tuple] = []
    for rc in resolved:
        if rc.pcb_layer is not Layer.BACK:
            continue
        try:
            template = libraries.footprint(rc.footprint_lib_name)
        except Exception:
            continue
        fx, fy = rc.pcb_position
        # Same transform kiutils applies when placing the footprint: for
        # back-layer parts the footprint is X-mirrored and rotated by the
        # KiCad-internal angle (resolve_rotation_for_layer converts the
        # user-facing CCW-from-outside angle).
        stored_angle = resolve_rotation_for_layer(rc.pcb_rotation, rc.pcb_layer)
        theta = math.radians(stored_angle)
        cos_a, sin_a = math.cos(theta), math.sin(theta)
        for pad in (template.pads or []):
            if pad.position is None:
                continue
            lx, ly = pad.position.X, pad.position.Y
            if rc.pcb_layer is Layer.BACK:
                lx = -lx
            rx = lx * cos_a - ly * sin_a
            ry = lx * sin_a + ly * cos_a
            ax, ay = fx + rx, fy + ry
            size = getattr(pad, "size", None)
            if size is None:
                half = 0.4   # sensible fallback for fluff pads
            else:
                sx = getattr(size, "X", None)
                sy = getattr(size, "Y", None)
                if sx is None or sy is None:
                    try:
                        sx, sy = size[0], size[1]
                    except Exception:
                        sx = sy = 0.8
                # Rotation of the pad itself — use the diagonal as a
                # conservative enclosing radius rather than solving the
                # rotated AABB exactly.
                half = math.hypot(float(sx), float(sy)) / 2.0
            rects.append((ax - half, ay - half, ax + half, ay + half))
    return rects


def _point_in_any_keepout(
    pt: tuple,
    radius: float,
    rects: List[tuple],
) -> bool:
    x, y = pt
    for xmin, ymin, xmax, ymax in rects:
        if (xmin - radius) <= x <= (xmax + radius) and \
           (ymin - radius) <= y <= (ymax + radius):
            return True
    return False


def _resolved_via_to_ki_via(
    v: ResolvedVia,
    net_index: dict,
    design: Design,
    topology: Optional[SheetTopology],
):
    """Construct a kiutils Via for a single ResolvedVia."""
    try:
        from kiutils.items.brditems import Via as KiVia
    except Exception:
        return None
    qualified = qualify_net_name(
        v.net,
        sheet_id=v.sheet_id,
        design=design,
        topology=topology,
    )
    net_num = net_index.get(qualified, 0)
    ki_via = KiVia(
        position=Position(X=v.position[0], Y=v.position[1]),
        size=v.size,
        drill=v.drill,
        layers=["F.Cu", "B.Cu"],
        net=net_num,
        tstamp=str(uuid.uuid4()),
    )
    return ki_via


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
    # Property raw s-exprs are preserved by kicad_property_patch; flip any
    # layer entries inside so silkscreen/fab references move to the back.
    raw = getattr(fp, "_rawProperties", None)
    if raw:
        for name, item in raw.items():
            for sub in item[3:] if len(item) > 3 else []:
                if isinstance(sub, list) and len(sub) >= 2 and sub[0] == "layer":
                    sub[1] = _flip_layer(sub[1])
