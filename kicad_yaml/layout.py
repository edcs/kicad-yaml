"""Layout engine: expand a Design into a flat list of ResolvedComponent
instances that writers can consume.

Responsibilities:
- Grid → per-cell Component expansion (with template variable substitution)
- Template → symbol/footprint/value resolution
- Layer assignment per part (cell layer overrides grid layer)
- Back-side rotation + offset mirroring so user intent matches visual output
- Sheet membership: every ResolvedComponent knows which sheet it came from
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from kicad_yaml.expressions import substitute
from kicad_yaml.schema import (
    Component,
    Design,
    Grid,
    GridCellPart,
    GridTrack,
    GridVia,
    Layer,
    SchematicConfig,
    Template,
)


@dataclass
class ResolvedComponent:
    """A fully-resolved component ready for writers to consume."""
    ref: str
    sheet_id: str
    symbol_lib_name: str          # "lib:name" for Symbol lookup
    footprint_lib_name: str       # "lib:name" for Footprint lookup
    value: str
    pcb_position: Tuple[float, float]
    pcb_layer: Layer
    pcb_rotation: float           # raw user CCW rotation (not the stored KiCad angle)
    pin_nets: Dict[str, str]
    no_connect_pins: List[str]
    sch_position: Optional[Tuple[float, float]]   # None = auto-layout will fill in
    suppress_keepouts: bool = False                # drop footprint-embedded keepout zones
    show_value: Optional[bool] = None              # per-component override for board.hide_values
    no_connect_pins_set: frozenset = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        self.no_connect_pins_set = frozenset(self.no_connect_pins)


def expand_design(design: Design) -> List[ResolvedComponent]:
    """Return a canonical ordered list of all resolved components in the
    design, grouped by sheet.  Order inside a sheet: explicit components
    first, then grid-expanded cells in row_major order.
    """
    out: List[ResolvedComponent] = []
    for sheet_name, sheet in design.sheets.items():
        for comp in sheet.components:
            out.append(_resolve_component(comp, design.templates, sheet_name))
        for grid in sheet.grids:
            out.extend(_expand_grid(grid, design.templates, sheet_name))
    return out


@dataclass
class ResolvedVia:
    """A grid-generated via with absolute board position and net."""
    sheet_id: str
    net: str
    position: Tuple[float, float]
    size: float
    drill: float
    cell_row: int              # 1-indexed physical row
    cell_col: int              # 1-indexed physical column
    grid_id: str


@dataclass
class ResolvedTrack:
    """A grid-generated track segment awaiting pad-position lookup.

    ``from_ref`` / ``to_ref`` are resolved reference designators
    (template variables already substituted), paired with the pad number
    on each side.  The PCB writer resolves the absolute pad positions
    and emits a kiutils Segment.  If either reference doesn't exist
    (e.g. the last cell in a chain with no successor), the writer skips.
    """
    sheet_id: str
    net: str
    from_ref: str
    from_pad: str
    to_ref: str
    to_pad: str
    layer: str
    width: float
    style: str = "direct"
    corridor_offset: Tuple[float, float] = (0.0, 0.0)


def expand_tracks(design: Design) -> List[ResolvedTrack]:
    """Return every track described by ``tracks_per_cell`` across every
    grid.  References to parts in neighbouring cells are evaluated via
    expression substitution; missing parts are handled at write time."""
    out: List[ResolvedTrack] = []
    for sheet_name, sheet in design.sheets.items():
        for grid in sheet.grids:
            if not grid.tracks_per_cell:
                continue
            cols, rows = grid.shape
            starts_bottom = grid.start_corner.startswith("bottom")
            starts_right = grid.start_corner.endswith("right")
            for r in range(1, rows + 1):
                for c in range(1, cols + 1):
                    srow = (rows - r + 1) if starts_bottom else r
                    scol = (cols - c + 1) if starts_right else c
                    if grid.order == "row_major_serpentine" and srow % 2 == 0:
                        index = (srow - 1) * cols + (cols - scol + 1)
                    else:
                        index = (srow - 1) * cols + scol
                    variables = {
                        "index": index, "row": r, "col": c,
                        "rows": rows, "cols": cols,
                    }
                    for track in grid.tracks_per_cell:
                        from_expr = substitute(track.from_pad, variables)
                        to_expr = substitute(track.to_pad, variables)
                        net = substitute(track.net, variables)
                        # from_pad / to_pad are "Ref.padNumber"
                        if "." not in from_expr or "." not in to_expr:
                            continue
                        from_ref, from_pin = from_expr.rsplit(".", 1)
                        to_ref, to_pin = to_expr.rsplit(".", 1)
                        out.append(ResolvedTrack(
                            sheet_id=sheet_name,
                            net=net,
                            from_ref=from_ref,
                            from_pad=from_pin,
                            to_ref=to_ref,
                            to_pad=to_pin,
                            layer=track.layer,
                            width=track.width,
                            style=track.style,
                            corridor_offset=track.corridor_offset,
                        ))
    return out


def expand_vias(design: Design) -> List[ResolvedVia]:
    """Return every via generated by grids' ``vias_per_cell`` entries,
    in (sheet, grid, row, col) order.  No conflict checking — the PCB
    writer is responsible for dropping vias that overlap other pads."""
    out: List[ResolvedVia] = []
    for sheet_name, sheet in design.sheets.items():
        for grid in sheet.grids:
            if not grid.vias_per_cell:
                continue
            cols, rows = grid.shape
            pitch_x, pitch_y = grid.pitch
            origin_x, origin_y = grid.origin
            for r in range(1, rows + 1):
                for c in range(1, cols + 1):
                    cell_x = origin_x + (c - 1) * pitch_x
                    cell_y = origin_y + (r - 1) * pitch_y
                    for via in grid.vias_per_cell:
                        stride_c, stride_r = via.stride
                        if (c - 1) % stride_c != 0 or (r - 1) % stride_r != 0:
                            continue
                        off_x, off_y = via.offset
                        if grid.layer is Layer.BACK:
                            off_x = -off_x
                        out.append(ResolvedVia(
                            sheet_id=sheet_name,
                            net=via.net,
                            position=(cell_x + off_x, cell_y + off_y),
                            size=via.size,
                            drill=via.drill,
                            cell_row=r,
                            cell_col=c,
                            grid_id=grid.id,
                        ))
    return out


def resolve_rotation_for_layer(rotation_ccw: float, layer: Layer) -> float:
    """Translate a user-facing CCW rotation into the KiCad file-stored angle.

    For front-side parts the rotation is stored verbatim.  For back-side
    parts KiCad applies rotation in the mirrored frame (effective CW as
    viewed from the front), so we invert the angle to match user intent.
    """
    if layer is Layer.FRONT:
        return rotation_ccw % 360.0
    return (-rotation_ccw) % 360.0


def _resolve_part_source(
    part,
    templates: Dict[str, Template],
) -> Tuple[str, str, str]:
    """Return (symbol_lib_name, footprint_lib_name, value) for a part,
    applying template defaults where fields are unset."""
    if part.template is not None:
        tpl = templates[part.template]
        sym = part.symbol or tpl.symbol
        fp = part.footprint or tpl.footprint
        val = part.value if part.value is not None else tpl.value
    else:
        sym = part.symbol or ""
        fp = part.footprint or ""
        val = part.value or ""
    return sym, fp, val


def _resolve_component(
    comp: Component,
    templates: Dict[str, Template],
    sheet_id: str,
) -> ResolvedComponent:
    sym, fp, val = _resolve_part_source(comp, templates)
    return ResolvedComponent(
        ref=comp.ref,
        sheet_id=sheet_id,
        symbol_lib_name=sym,
        footprint_lib_name=fp,
        value=val,
        pcb_position=comp.pcb.position,
        pcb_layer=comp.pcb.layer,
        pcb_rotation=comp.pcb.rotation,
        pin_nets=dict(comp.pin_nets),
        no_connect_pins=list(comp.no_connect_pins),
        sch_position=comp.schematic.position if comp.schematic else None,
        suppress_keepouts=comp.suppress_keepouts,
        show_value=comp.show_value,
    )


def _expand_grid(
    grid: Grid,
    templates: Dict[str, Template],
    sheet_id: str,
) -> List[ResolvedComponent]:
    out: List[ResolvedComponent] = []
    cols, rows = grid.shape
    total = cols * rows
    pitch_x, pitch_y = grid.pitch
    origin_x, origin_y = grid.origin
    starts_bottom = grid.start_corner.startswith("bottom")
    starts_right = grid.start_corner.endswith("right")
    for r in range(1, rows + 1):
        for c in range(1, cols + 1):
            # Logical (srow, scol): (1, 1) is at the start_corner cell,
            # incrementing away from it.  Geometry doesn't change; only
            # the chain index does.
            srow = (rows - r + 1) if starts_bottom else r
            scol = (cols - c + 1) if starts_right else c
            if grid.order == "row_major_serpentine" and srow % 2 == 0:
                index = (srow - 1) * cols + (cols - scol + 1)
            else:
                index = (srow - 1) * cols + scol
            cell_x = origin_x + (c - 1) * pitch_x
            cell_y = origin_y + (r - 1) * pitch_y
            variables = {
                "index": index,
                "row": r,
                "col": c,
                "rows": rows,
                "cols": cols,
            }
            for cell in grid.parts_per_cell:
                layer = cell.layer if cell.layer is not None else grid.layer
                offset_x, offset_y = cell.offset
                if layer is Layer.BACK:
                    offset_x = -offset_x   # mirror X for back-side
                pos = (cell_x + offset_x, cell_y + offset_y)

                ref = substitute(cell.ref, variables)
                pin_nets = {
                    k: substitute(v, variables)
                    for k, v in cell.pin_nets.items()
                }
                no_connect = [substitute(p, variables) for p in cell.no_connect_pins]

                sym, fp, val = _resolve_part_source(cell, templates)

                out.append(
                    ResolvedComponent(
                        ref=ref,
                        sheet_id=sheet_id,
                        symbol_lib_name=sym,
                        footprint_lib_name=fp,
                        value=val,
                        pcb_position=pos,
                        pcb_layer=layer,
                        pcb_rotation=0.0,
                        pin_nets=pin_nets,
                        no_connect_pins=no_connect,
                        sch_position=None,
                    )
                )
    assert len(out) == total * len(grid.parts_per_cell)
    return out


# Schematic auto-layout constants (mm).  Chosen so KiCad's 1.27 mm snap grid
# and default label fonts don't clash.  Tuning these is presentation-only.
_SCH_CELL_W = 38.0
_SCH_CELL_H = 30.0
_SCH_GRID_X0 = 35.0
_SCH_GRID_Y0 = 30.0


def assign_schematic_positions(
    resolved: List[ResolvedComponent],
    *,
    sheet_paper: str,
) -> None:
    """Fill in ``sch_position`` for every ResolvedComponent that doesn't
    already have one.  Mutates the list in place.

    v1: lay auto-placed entries on a dense row-major grid of
    ceil(sqrt(n)) columns, preserving the resolved order.  Explicit
    sch_position entries are left untouched.
    """
    del sheet_paper  # reserved for v2

    grouped: Dict[str, List[ResolvedComponent]] = {}
    for r in resolved:
        if r.sch_position is None:
            grouped.setdefault(r.sheet_id, []).append(r)

    for sheet_id, entries in grouped.items():
        _place_sheet_entries(entries)


def _place_sheet_entries(entries: List[ResolvedComponent]) -> None:
    import math
    n = len(entries)
    cols = max(1, math.ceil(math.sqrt(n)))
    for i, r in enumerate(entries):
        row = i // cols
        col = i % cols
        r.sch_position = (
            _SCH_GRID_X0 + col * _SCH_CELL_W,
            _SCH_GRID_Y0 + row * _SCH_CELL_H,
        )
