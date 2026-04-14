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
    """
    net: str
    offset: Tuple[float, float] = (0.0, 0.0)
    size: float = 0.6      # annular diameter (mm)
    drill: float = 0.3     # through-hole diameter (mm)


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
