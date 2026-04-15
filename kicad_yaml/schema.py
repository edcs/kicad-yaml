"""Pure data classes describing a kicad-yaml design.

No kiutils imports, no YAML imports.  These are constructed by
``loader.py`` from parsed YAML and consumed by ``layout.py`` and the
writer modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Layer(Enum):
    FRONT = "front"
    BACK = "back"


# Default KiCad file-format version stamp ("YYYYMMDD") per major version.
# Used when a design doesn't set `project.format_version`.  Without this,
# kiutils' defaults are old enough to make KiCad 10 show an
# "older-version, will be upgraded on save" banner.
DEFAULT_FORMAT_VERSION: Dict[int, str] = {
    10: "20260206",
}


def format_version_for(project: "Project") -> str:
    """Resolve the effective format-version stamp for a design."""
    if project.format_version:
        return project.format_version
    return DEFAULT_FORMAT_VERSION.get(project.kicad_version, "20260206")


@dataclass(frozen=True)
class Project:
    name: str
    kicad_version: int = 10
    format_version: Optional[str] = None  # YYYYMMDD date stamp; None → use default for kicad_version


@dataclass
class BoardZone:
    net: str                            # net name, e.g. "GND" or "VCC"
    layer: str                          # KiCad layer: "F.Cu", "B.Cu"
    polygon: List[Tuple[float, float]]  # outline corner points (mm)
    clearance: float = 0.5             # thermal-relief / edge clearance (mm)
    min_thickness: float = 0.254       # minimum copper width (mm)
    priority: int = 0
    name: Optional[str] = None


@dataclass
class Board:
    size: Tuple[float, float]     # (width, height) in mm
    paper: str = "A4"
    zones: List[BoardZone] = field(default_factory=list)
    layers: int = 2               # copper layer count: 2 (F.Cu/B.Cu) or 4 (+In1.Cu/In2.Cu)


@dataclass
class Template:
    """Named reusable part definition — symbol + footprint + default value."""
    symbol: str                   # "lib:name"
    footprint: str                # "lib:name"
    value: str = ""


@dataclass
class PcbConfig:
    position: Tuple[float, float]
    layer: Layer = Layer.FRONT
    rotation: float = 0.0         # degrees CCW, as viewed from the layer


@dataclass
class SchematicConfig:
    position: Tuple[float, float]


@dataclass
class Component:
    ref: str
    pcb: PcbConfig
    pin_nets: Dict[str, str]
    template: Optional[str] = None
    symbol: Optional[str] = None
    footprint: Optional[str] = None
    value: Optional[str] = None
    schematic: Optional[SchematicConfig] = None
    no_connect_pins: List[str] = field(default_factory=list)
    # Drop footprint-embedded keepout zones during board placement (e.g.
    # ESP32 antenna keepout). Trades a small RF-performance penalty for
    # unrestricted routing/pour fill in that area.
    suppress_keepouts: bool = False


@dataclass
class GridCellPart:
    ref: str
    pin_nets: Dict[str, str]      # values may contain {index}, {row}, {col} expressions
    template: Optional[str] = None
    symbol: Optional[str] = None
    footprint: Optional[str] = None
    value: Optional[str] = None
    offset: Tuple[float, float] = (0.0, 0.0)
    layer: Optional[Layer] = None  # overrides grid layer when set
    no_connect_pins: List[str] = field(default_factory=list)


@dataclass
class GridVia:
    """A stitching via generated once per grid cell.

    Offset is applied to the cell geometric centre.  For a grid on the
    back layer, X is mirrored so the via sits at the same *visual* spot
    relative to the cell.

    ``stride`` lets you place vias on only every Nth cell along each axis
    (default 1, every cell).  Useful on LED matrices where a single via
    every 2–4 cells is plenty of GND path and keeps fab cost down.
    """
    net: str
    offset: Tuple[float, float] = (0.0, 0.0)
    size: float = 0.6                       # annular diameter (mm)
    drill: float = 0.3                      # through-hole diameter (mm)
    stride: Tuple[int, int] = (1, 1)        # (col_stride, row_stride)


@dataclass
class GridTrack:
    """A track segment generated once per grid cell.

    ``from_pad`` and ``to_pad`` are ``"PartRef.padNumber"`` templates that
    may reference parts in *other* cells via ``{index+1}`` etc.  The
    generator evaluates both expressions with the current cell's
    variables; if either resolved part doesn't exist (e.g. off the end of
    the chain at the last cell), the track is silently skipped.
    """
    from_pad: str           # "LED{index}.2"
    to_pad: str             # "LED{index+1}.4"
    net: str                # "D{index+1}"
    layer: str = "F.Cu"
    width: float = 0.25
    # Segment shape between the two pads:
    # - "direct": one straight segment pad → pad (diagonal if pads aren't aligned).
    # - "45":     Z-shape with 45° chamfers at each end and a straight
    #             horizontal / vertical middle run.
    style: str = "direct"
    # Signed offset applied to the middle run of a 45-style track.  Only the
    # axis perpendicular to the dominant direction is used: for a mostly-
    # horizontal hop, ``corridor_offset[1]`` shifts the middle run in Y (use
    # this to route above/below a row of pads); for a mostly-vertical hop,
    # ``corridor_offset[0]`` shifts the middle in X.
    corridor_offset: Tuple[float, float] = (0.0, 0.0)


@dataclass
class Grid:
    id: str
    shape: Tuple[int, int]        # (cols, rows)
    pitch: Tuple[float, float]    # mm
    origin: Tuple[float, float]   # mm; centre of cell (row=1, col=1)
    order: str                    # "row_major" or "row_major_serpentine"
    layer: Layer
    parts_per_cell: List[GridCellPart]
    # Which physical corner gets index 1.  Geometry (origin, pitch) is
    # unchanged; only the index-to-cell mapping flips.
    start_corner: str = "top-left"
    vias_per_cell: List[GridVia] = field(default_factory=list)
    tracks_per_cell: List[GridTrack] = field(default_factory=list)


@dataclass
class Subsheet:
    sheet_id: str                 # references Design.sheets key
    label: str                    # display name on the sheet symbol
    schematic: SchematicConfig
    size: Tuple[float, float]     # mm; sheet symbol rectangle dimensions
    pin_map: Dict[str, str] = field(default_factory=dict)
    # Reserved for Plan 2; present in schema so Plan 1 round-trips multi-sheet YAML.


@dataclass
class Sheet:
    paper: str
    components: List[Component] = field(default_factory=list)
    grids: List[Grid] = field(default_factory=list)
    subsheets: List[Subsheet] = field(default_factory=list)


@dataclass
class Design:
    project: Project
    board: Board
    global_nets: List[str]
    templates: Dict[str, Template]
    sheets: Dict[str, Sheet]

    def __post_init__(self) -> None:
        if "main" not in self.sheets:
            raise ValueError("design.sheets must contain a 'main' entry")
