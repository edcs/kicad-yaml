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

from kicad_yaml.layout import (
    ResolvedComponent,
    ResolvedTrack,
    ResolvedVia,
    resolve_rotation_for_layer,
)
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
    tracks: Optional[List[ResolvedTrack]] = None,
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

    # Compute everything we're about to (re)generate *before* we touch the
    # preserved traceItems, so the sanitiser can drop stale copies.
    auto_via_positions = set()
    if vias:
        for v in vias:
            auto_via_positions.add(
                (round(v.position[0], 3), round(v.position[1], 3))
            )

    by_ref = {rc.ref: rc for rc in resolved}
    fresh_segments_by_track: list = []
    auto_track_net_nums = set()
    if tracks:
        for t in tracks:
            segs = _resolved_track_to_segments(
                t, by_ref, libraries, net_index, design, topology
            )
            fresh_segments_by_track.append(segs)
            # Record the net number this track lives on so we can drop any
            # stale preserved segments with the same net (old style, etc.)
            qualified = qualify_net_name(
                t.net, sheet_id=t.sheet_id,
                design=design, topology=topology,
            )
            n = net_index.get(qualified)
            if n is not None:
                auto_track_net_nums.add(n)

    if existing_tracks:
        board.traceItems = _sanitise_preserved_traceitems(
            existing_tracks, net_index, auto_via_positions, auto_track_net_nums
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

    for segs in fresh_segments_by_track:
        for s in segs:
            board.traceItems.append(s)

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
    # KiCad 10 has an inconsistency where certain SMD pad types
    # (notably roundrect) don't pick up the footprint's stored rotation
    # when placed on the back layer.  Side-step the issue by pre-applying
    # the rotation ourselves — rotate pad/graphic coordinates around the
    # footprint origin, set pad angles explicitly, and zero the
    # footprint's stored angle so nothing double-rotates.
    if angle:
        _bake_footprint_rotation(fp, angle)
        fp.position.angle = 0.0
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
    auto_track_net_nums: set,
) -> list:
    """Clean up trace items read from an existing .kicad_pcb for re-write.

    - Skip any via whose position matches an auto-generated stitching via's
      target position (within 0.001 mm).  Those are stale copies that the
      current build is about to regenerate.
    - Drop any segment on a net that ``tracks_per_cell`` owns.  Those
      nets are regenerated on every build, so preserved segments would
      accumulate stale copies (and switching ``style`` would leave the
      old shape alongside the new one).
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

        # Drop auto-regenerated segments, matched by net ownership
        if type_name == "Segment":
            net_val = getattr(item, "net", None)
            # normalise string-net first so the membership test works
            if isinstance(net_val, str):
                net_val = net_index.get(net_val)
                if net_val is not None:
                    item.net = net_val
            if net_val in auto_track_net_nums:
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


def _pad_absolute_position(rc: ResolvedComponent, pad_number: str,
                           libraries: LibraryResolver):
    """Resolve the board-coordinate centre of a specific pad on a placed
    component.  Returns ``None`` if the footprint or pad can't be found."""
    if libraries is None:
        return None
    try:
        template = libraries.footprint(rc.footprint_lib_name)
    except Exception:
        return None
    for pad in (template.pads or []):
        if str(getattr(pad, "number", "")) != str(pad_number):
            continue
        if pad.position is None:
            return None
        lx, ly = pad.position.X, pad.position.Y
        if rc.pcb_layer is Layer.BACK:
            lx = -lx
        stored_angle = resolve_rotation_for_layer(rc.pcb_rotation, rc.pcb_layer)
        theta = math.radians(stored_angle)
        rx = lx * math.cos(theta) - ly * math.sin(theta)
        ry = lx * math.sin(theta) + ly * math.cos(theta)
        return (rc.pcb_position[0] + rx, rc.pcb_position[1] + ry)
    return None


def _track_path_points(
    start: tuple, end: tuple, style: str,
    corridor_offset: tuple = (0.0, 0.0),
) -> List[tuple]:
    """Return the ordered list of corner points for a track between two
    pads.  For a path of N points, the caller emits N-1 segments chained
    through them.

    45-style tracks form a Z with 45° chamfers: diagonal off the start
    pad → straight middle run → diagonal into the end pad.  The straight
    middle sits at the midpoint of the dominant axis by default; a
    ``corridor_offset`` pushes it off that midpoint so the middle run
    can clear a row (or column) of pads instead of cutting through them.
    The two diagonals can have different lengths, each sized so the
    middle + both diagonals still add up to the total span.
    """
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    adx, ady = abs(dx), abs(dy)

    if adx < 1e-6 or ady < 1e-6 or style == "direct":
        return [start, end]

    if style != "45":
        return [start, end]

    sign_x = 1 if dx >= 0 else -1
    sign_y = 1 if dy >= 0 else -1
    off_x, off_y = corridor_offset

    if adx >= ady:
        # Horizontal-dominant: horizontal middle, corridor_y shifts it
        # perpendicular to the dominant axis.
        corridor_y = (sy + ey) / 2.0 + off_y
        d1 = abs(corridor_y - sy)     # chamfer leaving start pad
        d2 = abs(corridor_y - ey)     # chamfer entering end pad
        if d1 + d2 > adx + 1e-6:
            # Offset too large — chamfers would overlap.  Fall back to
            # the no-offset Z so we still emit a valid shape.
            corridor_y = (sy + ey) / 2.0
            d1 = ady / 2.0
            d2 = ady / 2.0
        p1 = (sx + sign_x * d1, corridor_y)
        p2 = (ex - sign_x * d2, corridor_y)
    else:
        # Vertical-dominant: vertical middle, corridor_x shifts it.
        corridor_x = (sx + ex) / 2.0 + off_x
        d1 = abs(corridor_x - sx)
        d2 = abs(corridor_x - ex)
        if d1 + d2 > ady + 1e-6:
            corridor_x = (sx + ex) / 2.0
            d1 = adx / 2.0
            d2 = adx / 2.0
        p1 = (corridor_x, sy + sign_y * d1)
        p2 = (corridor_x, ey - sign_y * d2)

    if abs(p1[0] - p2[0]) < 1e-6 and abs(p1[1] - p2[1]) < 1e-6:
        return [start, p1, end]
    return [start, p1, p2, end]


def _resolved_track_to_segments(
    t: ResolvedTrack,
    by_ref: dict,
    libraries: Optional[LibraryResolver],
    net_index: dict,
    design: Design,
    topology: Optional[SheetTopology],
) -> list:
    """Build one or more kiutils Segments from a ResolvedTrack.  Returns
    an empty list if either endpoint can't be resolved (missing ref or
    pad)."""
    try:
        from kiutils.items.brditems import Segment as KiSegment
    except Exception:
        return []

    src = by_ref.get(t.from_ref)
    dst = by_ref.get(t.to_ref)
    if src is None or dst is None:
        return []

    start = _pad_absolute_position(src, t.from_pad, libraries)
    end = _pad_absolute_position(dst, t.to_pad, libraries)
    if start is None or end is None:
        return []

    qualified = qualify_net_name(
        t.net, sheet_id=t.sheet_id, design=design, topology=topology
    )
    net_num = net_index.get(qualified, 0)

    points = _track_path_points(start, end, t.style, t.corridor_offset)
    segments = []
    for a, b in zip(points, points[1:]):
        segments.append(KiSegment(
            start=Position(X=a[0], Y=a[1]),
            end=Position(X=b[0], Y=b[1]),
            width=t.width,
            layer=t.layer,
            net=net_num,
            tstamp=str(uuid.uuid4()),
        ))
    return segments


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


def _bake_footprint_rotation(fp: Footprint, angle_deg: float) -> None:
    """Pre-apply a rotation to every sub-item in a footprint so the
    ``footprint.at`` angle can be reset to 0.

    Works around KiCad's inconsistent rendering of rotated SMD roundrect
    pads on the back layer: pad *positions* follow the footprint's stored
    rotation, but pad *shape orientations* sometimes don't — resulting in
    rotated coordinates with un-rotated pad rectangles that overlap each
    other.  Baking the rotation removes the ambiguity.
    """
    theta = math.radians(angle_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    def rotate_point(p):
        if p is None:
            return
        x, y = p.X, p.Y
        # 6 decimals = 1 nm precision, kills float-formatting noise
        p.X = round(x * cos_t - y * sin_t, 6)
        p.Y = round(x * sin_t + y * cos_t, 6)

    def bump_angle(p):
        if p is None:
            return
        current = p.angle if p.angle is not None else 0.0
        p.angle = (current + angle_deg) % 360.0

    for pad in fp.pads or []:
        rotate_point(getattr(pad, "position", None))
        bump_angle(getattr(pad, "position", None))

    for g in fp.graphicItems or []:
        for attr in ("position", "start", "end", "mid", "center"):
            rotate_point(getattr(g, attr, None))
        pts = getattr(g, "coordinates", None)
        if pts is not None:
            for pt in pts:
                rotate_point(pt)
        # Rotate text orientation alongside its anchor
        if type(g).__name__ in ("FpText", "FpTextBox"):
            bump_angle(getattr(g, "position", None))

    for zone in fp.zones or []:
        for poly in (zone.polygons or []):
            for pt in (poly.coordinates or []):
                rotate_point(pt)

    # Properties are preserved by kicad_property_patch as raw s-expr lists;
    # rotate their (at X Y angle) entries so silkscreen text stays with the
    # footprint.
    raw = getattr(fp, "_rawProperties", None)
    if raw:
        for name, item in raw.items():
            if len(item) <= 3:
                continue
            for i, sub in enumerate(item[3:], start=3):
                if not isinstance(sub, list) or len(sub) < 3 or sub[0] != "at":
                    continue
                try:
                    x, y = float(sub[1]), float(sub[2])
                except (TypeError, ValueError):
                    continue
                rx = x * cos_t - y * sin_t
                ry = x * sin_t + y * cos_t
                sub[1] = rx
                sub[2] = ry
                # Bump angle too if present
                if len(sub) >= 4:
                    try:
                        cur = float(sub[3])
                        sub[3] = (cur + angle_deg) % 360.0
                    except (TypeError, ValueError):
                        pass


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
