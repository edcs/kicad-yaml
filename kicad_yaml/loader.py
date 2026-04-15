# kicad_yaml/loader.py
"""YAML → schema dataclass loader with friendly errors.

This module owns:
- Reading YAML from a Path or literal string via ruamel.yaml
- Schema pass: unknown-key rejection, type coercion, required-field checks
- Semantic pass (added in Task 5): cross-ref checks, net declarations, etc.

No kiutils imports — the loader produces pure schema objects.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

from ruamel.yaml import YAML

from kicad_yaml.expressions import variables_used, ALLOWED_VARS, substitute
from kicad_yaml.topology import SheetTopology, TopologyError
from kicad_yaml.schema import (
    Board,
    BoardZone,
    Component,
    Design,
    Grid,
    GridCellPart,
    GridTrack,
    GridVia,
    Layer,
    PcbConfig,
    Project,
    SchematicConfig,
    Sheet,
    Subsheet,
    Template,
)


class LoadError(ValueError):
    """Raised when a YAML document can't be parsed into a valid Design."""


_TOP_LEVEL_KEYS = {"project", "board", "global_nets", "templates", "sheets"}
_PROJECT_KEYS = {"name", "kicad_version", "format_version"}
_BOARD_KEYS = {"size", "paper", "zones"}
_ZONE_KEYS = {"net", "layer", "polygon", "clearance", "min_thickness", "priority", "name"}
_TEMPLATE_KEYS = {"symbol", "footprint", "value"}
_COMPONENT_KEYS = {
    "ref", "template", "symbol", "footprint", "value",
    "pcb", "schematic", "pin_nets", "no_connect_pins",
    "suppress_keepouts",
}
_PCB_KEYS = {"position", "layer", "rotation"}
_SCH_KEYS = {"position"}
_GRID_KEYS = {"id", "shape", "pitch", "origin", "order", "layer",
              "parts_per_cell", "start_corner", "vias_per_cell",
              "tracks_per_cell"}
_GRID_VIA_KEYS = {"net", "offset", "size", "drill", "stride"}
_GRID_TRACK_KEYS = {"from_pad", "to_pad", "net", "layer", "width", "style",
                    "corridor_offset"}
_VALID_TRACK_STYLES = {"direct", "45"}
_GRID_CELL_KEYS = _COMPONENT_KEYS | {"offset", "layer"}
_SHEET_KEYS = {"paper", "components", "grids", "subsheets"}
_SUBSHEET_KEYS = {"sheet", "label", "schematic", "size", "pin_map"}


def load_design(source: Union[Path, str]) -> Design:
    """Load a design from a Path or a literal YAML string.

    Path arguments read from disk.  str arguments are always parsed as
    literal YAML content, never as paths.
    """
    if isinstance(source, Path):
        text = source.read_text()
    elif isinstance(source, str):
        text = source
    else:
        raise LoadError(f"source must be Path or str, got {type(source).__name__}")

    yaml = YAML(typ="safe")
    data = yaml.load(text)
    if not isinstance(data, dict):
        raise LoadError("document root must be a mapping")

    _require_keys(data, _TOP_LEVEL_KEYS, "top level", required={"project", "board", "sheets"})
    try:
        design = Design(
            project=_build_project(data["project"]),
            board=_build_board(data["board"]),
            global_nets=_as_str_list(data.get("global_nets", []), "global_nets"),
            templates=_build_templates(data.get("templates", {})),
            sheets=_build_sheets(data["sheets"]),
        )
    except ValueError as exc:
        raise LoadError(str(exc)) from exc
    _validate_semantic(design)
    return design


def _require_keys(
    obj: Dict[str, Any],
    allowed: set,
    context: str,
    *,
    required: set | None = None,
) -> None:
    unknown = set(obj.keys()) - allowed
    if unknown:
        name = next(iter(sorted(unknown)))
        raise LoadError(f"unknown key '{name}' in {context}")
    if required:
        missing = required - set(obj.keys())
        if missing:
            raise LoadError(f"missing required key(s) {sorted(missing)} in {context}")


def _build_project(obj: Any) -> Project:
    _require_dict(obj, "project")
    _require_keys(obj, _PROJECT_KEYS, "project", required={"name"})
    fv = obj.get("format_version")
    return Project(
        name=str(obj["name"]),
        kicad_version=int(obj.get("kicad_version", 10)),
        format_version=str(fv) if fv is not None else None,
    )


def _build_board(obj: Any) -> Board:
    _require_dict(obj, "board")
    _require_keys(obj, _BOARD_KEYS, "board", required={"size"})
    zones = [
        _build_board_zone(z, f"board.zones[{i}]")
        for i, z in enumerate(obj.get("zones") or [])
    ]
    return Board(
        size=_as_xy(obj["size"], "board.size"),
        paper=str(obj.get("paper", "A4")),
        zones=zones,
    )


def _build_board_zone(obj: Any, context: str) -> BoardZone:
    _require_dict(obj, context)
    _require_keys(obj, _ZONE_KEYS, context, required={"net", "layer", "polygon"})
    raw_polygon = obj["polygon"]
    if not isinstance(raw_polygon, list) or len(raw_polygon) < 3:
        raise LoadError(f"{context}.polygon must be a list of at least 3 [x, y] points")
    polygon = [_as_xy(pt, f"{context}.polygon[{i}]") for i, pt in enumerate(raw_polygon)]
    return BoardZone(
        net=str(obj["net"]),
        layer=str(obj["layer"]),
        polygon=polygon,
        clearance=float(obj.get("clearance", 0.5)),
        min_thickness=float(obj.get("min_thickness", 0.254)),
        priority=int(obj.get("priority", 0)),
        name=str(obj["name"]) if obj.get("name") is not None else None,
    )


def _build_templates(obj: Any) -> Dict[str, Template]:
    if obj is None:
        return {}
    _require_dict(obj, "templates")
    result: Dict[str, Template] = {}
    for name, tdata in obj.items():
        _require_dict(tdata, f"templates.{name}")
        _require_keys(tdata, _TEMPLATE_KEYS, f"templates.{name}",
                      required={"symbol", "footprint"})
        result[name] = Template(
            symbol=str(tdata["symbol"]),
            footprint=str(tdata["footprint"]),
            value=str(tdata.get("value", "")),
        )
    return result


def _build_sheets(obj: Any) -> Dict[str, Sheet]:
    _require_dict(obj, "sheets")
    result: Dict[str, Sheet] = {}
    for name, sdata in obj.items():
        if sdata is None:
            sdata = {}
        _require_dict(sdata, f"sheets.{name}")
        _require_keys(sdata, _SHEET_KEYS, f"sheets.{name}")
        result[name] = Sheet(
            paper=str(sdata.get("paper", "A4")),
            components=[_build_component(c, f"sheets.{name}.components[{i}]")
                        for i, c in enumerate(sdata.get("components") or [])],
            grids=[_build_grid(g, f"sheets.{name}.grids[{i}]")
                   for i, g in enumerate(sdata.get("grids") or [])],
            subsheets=[_build_subsheet(s, f"sheets.{name}.subsheets[{i}]")
                       for i, s in enumerate(sdata.get("subsheets") or [])],
        )
    return result


def _build_component(obj: Any, context: str) -> Component:
    _require_dict(obj, context)
    _require_keys(obj, _COMPONENT_KEYS, context, required={"ref", "pcb", "pin_nets"})
    pcb_data = obj["pcb"]
    _require_dict(pcb_data, f"{context}.pcb")
    _require_keys(pcb_data, _PCB_KEYS, f"{context}.pcb", required={"position"})
    pcb = PcbConfig(
        position=_as_xy(pcb_data["position"], f"{context}.pcb.position"),
        layer=_as_layer(pcb_data.get("layer", "front"), f"{context}.pcb.layer"),
        rotation=float(pcb_data.get("rotation", 0.0)),
    )
    sch: SchematicConfig | None = None
    if "schematic" in obj and obj["schematic"] is not None:
        sch_data = obj["schematic"]
        _require_dict(sch_data, f"{context}.schematic")
        _require_keys(sch_data, _SCH_KEYS, f"{context}.schematic", required={"position"})
        sch = SchematicConfig(
            position=_as_xy(sch_data["position"], f"{context}.schematic.position"),
        )
    return Component(
        ref=str(obj["ref"]),
        pcb=pcb,
        pin_nets={str(k): str(v) for k, v in (obj.get("pin_nets") or {}).items()},
        template=obj.get("template"),
        symbol=obj.get("symbol"),
        footprint=obj.get("footprint"),
        value=obj.get("value"),
        schematic=sch,
        no_connect_pins=[str(p) for p in (obj.get("no_connect_pins") or [])],
        suppress_keepouts=bool(obj.get("suppress_keepouts", False)),
    )


def _build_grid(obj: Any, context: str) -> Grid:
    _require_dict(obj, context)
    _require_keys(obj, _GRID_KEYS, context,
                  required={"id", "shape", "pitch", "origin", "parts_per_cell"})
    return Grid(
        id=str(obj["id"]),
        shape=_as_int_pair(obj["shape"], f"{context}.shape"),
        pitch=_as_xy(obj["pitch"], f"{context}.pitch"),
        origin=_as_xy(obj["origin"], f"{context}.origin"),
        order=str(obj.get("order", "row_major")),
        layer=_as_layer(obj.get("layer", "front"), f"{context}.layer"),
        parts_per_cell=[
            _build_grid_cell(p, f"{context}.parts_per_cell[{i}]")
            for i, p in enumerate(obj["parts_per_cell"])
        ],
        start_corner=str(obj.get("start_corner", "top-left")),
        vias_per_cell=[
            _build_grid_via(v, f"{context}.vias_per_cell[{i}]")
            for i, v in enumerate(obj.get("vias_per_cell") or [])
        ],
        tracks_per_cell=[
            _build_grid_track(t, f"{context}.tracks_per_cell[{i}]")
            for i, t in enumerate(obj.get("tracks_per_cell") or [])
        ],
    )


def _build_grid_cell(obj: Any, context: str) -> GridCellPart:
    _require_dict(obj, context)
    _require_keys(obj, _GRID_CELL_KEYS, context, required={"ref", "pin_nets"})
    layer_raw = obj.get("layer")
    return GridCellPart(
        ref=str(obj["ref"]),
        pin_nets={str(k): str(v) for k, v in (obj.get("pin_nets") or {}).items()},
        template=obj.get("template"),
        symbol=obj.get("symbol"),
        footprint=obj.get("footprint"),
        value=obj.get("value"),
        offset=_as_xy(obj.get("offset", [0, 0]), f"{context}.offset"),
        layer=_as_layer(layer_raw, f"{context}.layer") if layer_raw is not None else None,
        no_connect_pins=[str(p) for p in (obj.get("no_connect_pins") or [])],
    )


def _build_grid_via(obj: Any, context: str) -> GridVia:
    _require_dict(obj, context)
    _require_keys(obj, _GRID_VIA_KEYS, context, required={"net"})
    stride = obj.get("stride", [1, 1])
    return GridVia(
        net=str(obj["net"]),
        offset=_as_xy(obj.get("offset", [0, 0]), f"{context}.offset"),
        size=float(obj.get("size", 0.6)),
        drill=float(obj.get("drill", 0.3)),
        stride=_as_int_pair(stride, f"{context}.stride"),
    )


def _build_grid_track(obj: Any, context: str) -> GridTrack:
    _require_dict(obj, context)
    _require_keys(obj, _GRID_TRACK_KEYS, context,
                  required={"from_pad", "to_pad", "net"})
    style = str(obj.get("style", "direct"))
    if style not in _VALID_TRACK_STYLES:
        raise LoadError(
            f"{context}: unknown track style '{style}'. "
            f"supported: {sorted(_VALID_TRACK_STYLES)}"
        )
    return GridTrack(
        from_pad=str(obj["from_pad"]),
        to_pad=str(obj["to_pad"]),
        net=str(obj["net"]),
        layer=str(obj.get("layer", "F.Cu")),
        width=float(obj.get("width", 0.25)),
        style=style,
        corridor_offset=_as_xy(obj.get("corridor_offset", [0, 0]),
                               f"{context}.corridor_offset"),
    )


def _build_subsheet(obj: Any, context: str) -> Subsheet:
    """Plan 1: accept the schema shape but don't enforce semantic rules
    beyond basic type coercion.  Plan 2 adds full subsheet validation."""
    _require_dict(obj, context)
    _require_keys(obj, _SUBSHEET_KEYS, context, required={"sheet", "schematic", "size"})
    sch_data = obj["schematic"]
    _require_dict(sch_data, f"{context}.schematic")
    _require_keys(sch_data, _SCH_KEYS, f"{context}.schematic", required={"position"})
    return Subsheet(
        sheet_id=str(obj["sheet"]),
        label=str(obj.get("label", obj["sheet"])),
        schematic=SchematicConfig(
            position=_as_xy(sch_data["position"], f"{context}.schematic.position"),
        ),
        size=_as_xy(obj["size"], f"{context}.size"),
        pin_map={str(k): str(v) for k, v in (obj.get("pin_map") or {}).items()},
    )


def _require_dict(obj: Any, context: str) -> None:
    if not isinstance(obj, dict):
        raise LoadError(f"{context} must be a mapping, got {type(obj).__name__}")


def _as_str_list(obj: Any, context: str) -> List[str]:
    if obj is None:
        return []
    if not isinstance(obj, list):
        raise LoadError(f"{context} must be a list")
    return [str(x) for x in obj]


def _as_xy(obj: Any, context: str) -> Tuple[float, float]:
    if not isinstance(obj, (list, tuple)) or len(obj) != 2:
        raise LoadError(f"{context} must be a 2-element list [x, y]")
    return (float(obj[0]), float(obj[1]))


def _as_int_pair(obj: Any, context: str) -> Tuple[int, int]:
    if not isinstance(obj, (list, tuple)) or len(obj) != 2:
        raise LoadError(f"{context} must be a 2-element list")
    return (int(obj[0]), int(obj[1]))


def _as_layer(obj: Any, context: str) -> Layer:
    try:
        return Layer(str(obj))
    except ValueError:
        raise LoadError(f"{context} must be 'front' or 'back', got {obj!r}")


_VALID_GRID_ORDERS = {"row_major", "row_major_serpentine"}
_VALID_START_CORNERS = {"top-left", "top-right", "bottom-left", "bottom-right"}


def _validate_semantic(design: Design) -> None:
    """Cross-reference checks that can't be done in the schema pass."""
    refs: dict[str, str] = {}  # ref -> context string

    for sheet_name, sheet in design.sheets.items():
        for i, comp in enumerate(sheet.components):
            context = f"sheets.{sheet_name}.components[{i}]"
            _check_part_source(comp, design.templates, context)
            _check_duplicate_ref(comp.ref, context, refs)

        for grid in sheet.grids:
            grid_context = f"sheets.{sheet_name}.grids[{grid.id}]"
            _check_grid_order(grid, grid_context)
            _check_grid_geometry(grid, grid_context)
            for j, cell in enumerate(grid.parts_per_cell):
                cell_context = f"{grid_context}.parts_per_cell[{j}]"
                _check_part_source(cell, design.templates, cell_context)
                _check_cell_expressions(cell, cell_context)
                # Cell ref uniqueness is checked after expansion (layout pass).

    _validate_hierarchy(design)


def _check_part_source(
    part,
    templates: Dict[str, Template],
    context: str,
) -> None:
    if part.template is not None:
        if part.template not in templates:
            raise LoadError(
                f"{context} ({getattr(part, 'ref', '?')}) references "
                f"unknown template '{part.template}'. "
                f"known templates: {sorted(templates.keys())}"
            )
        return
    if part.symbol and part.footprint:
        return
    raise LoadError(
        f"{context} ({getattr(part, 'ref', '?')}) must set 'template' "
        f"or both 'symbol' and 'footprint'"
    )


def _check_duplicate_ref(ref: str, context: str, seen: Dict[str, str]) -> None:
    if ref in seen:
        raise LoadError(
            f"duplicate ref '{ref}' at {context} (first seen at {seen[ref]})"
        )
    seen[ref] = context


def _check_grid_order(grid: Grid, context: str) -> None:
    if grid.order not in _VALID_GRID_ORDERS:
        raise LoadError(
            f"{context}: unknown grid order '{grid.order}'. "
            f"supported: {sorted(_VALID_GRID_ORDERS)}"
        )
    if grid.start_corner not in _VALID_START_CORNERS:
        raise LoadError(
            f"{context}: unknown start_corner '{grid.start_corner}'. "
            f"supported: {sorted(_VALID_START_CORNERS)}"
        )


def _check_grid_geometry(grid: Grid, context: str) -> None:
    cols, rows = grid.shape
    if cols <= 0 or rows <= 0:
        raise LoadError(f"{context}: shape must be positive, got {grid.shape}")
    if grid.pitch[0] <= 0 or grid.pitch[1] <= 0:
        raise LoadError(f"{context}: pitch must be positive, got {grid.pitch}")


def _check_cell_expressions(cell: GridCellPart, context: str) -> None:
    allowed = set(ALLOWED_VARS)
    strings_to_check = [("ref", cell.ref)]
    for pin, net in cell.pin_nets.items():
        strings_to_check.append((f"pin_nets[{pin}]", net))
    for field_name, text in strings_to_check:
        used = set(variables_used(text))
        unknown = used - allowed
        if unknown:
            name = next(iter(sorted(unknown)))
            raise LoadError(
                f"{context}.{field_name}: expression references unknown "
                f"variable '{name}' in {text!r}. "
                f"allowed: {sorted(allowed)}"
            )


def _collect_nets_in_sheet(sheet) -> set[str]:
    """Return the set of net names referenced by pin_nets in a sheet."""
    nets: set[str] = set()
    for comp in sheet.components:
        nets.update(comp.pin_nets.values())
    for grid in sheet.grids:
        cols, rows = grid.shape
        for r in range(1, rows + 1):
            for c in range(1, cols + 1):
                index = (r - 1) * cols + c
                variables = {
                    "index": index,
                    "row": r,
                    "col": c,
                    "rows": rows,
                    "cols": cols,
                }
                for cell in grid.parts_per_cell:
                    for net_template in cell.pin_nets.values():
                        nets.add(substitute(net_template, variables))
    return nets


def _validate_hierarchy(design: Design) -> None:
    """Cross-sheet semantic checks.

    - Sheet tree must be valid (SheetTopology raises on structural errors).
    - For each parent→child relation, every pin_map key must appear as a
      net used somewhere in the parent's pin_nets, and every pin_map value
      must appear as a net used somewhere in the child's pin_nets.  This
      catches typos and dangling declarations.
    - global_nets members should not appear as pin_map keys or values
      (they're already shared; exposing them explicitly is a mistake).
    """
    try:
        SheetTopology.from_design(design)
    except TopologyError as e:
        raise LoadError(str(e)) from e

    global_set = set(design.global_nets)

    for parent_id, parent_sheet in design.sheets.items():
        parent_nets = _collect_nets_in_sheet(parent_sheet)
        for i, sub in enumerate(parent_sheet.subsheets):
            child_id = sub.sheet_id
            child_sheet = design.sheets[child_id]
            child_nets = _collect_nets_in_sheet(child_sheet)
            context = f"sheets.{parent_id}.subsheets[{i}] (child '{child_id}')"
            for parent_net, child_net in sub.pin_map.items():
                if parent_net in global_set:
                    raise LoadError(
                        f"{context}: pin_map key '{parent_net}' is in "
                        f"global_nets — globals are already shared across "
                        f"all sheets and should not appear in pin_map"
                    )
                if child_net in global_set:
                    raise LoadError(
                        f"{context}: pin_map value '{child_net}' is in "
                        f"global_nets — globals are already shared across "
                        f"all sheets and should not appear in pin_map"
                    )
                if parent_net not in parent_nets:
                    raise LoadError(
                        f"{context}: pin_map key '{parent_net}' is not "
                        f"referenced by any net in the parent sheet '{parent_id}'"
                    )
                if child_net not in child_nets:
                    raise LoadError(
                        f"{context}: pin_map value '{child_net}' is not "
                        f"referenced by any net in the child sheet '{child_id}'"
                    )
