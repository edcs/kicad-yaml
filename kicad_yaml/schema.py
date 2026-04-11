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


@dataclass(frozen=True)
class Project:
    name: str
    kicad_version: int = 10


@dataclass(frozen=True)
class Board:
    size: Tuple[float, float]     # (width, height) in mm
    paper: str = "A4"


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
class Grid:
    id: str
    shape: Tuple[int, int]        # (cols, rows)
    pitch: Tuple[float, float]    # mm
    origin: Tuple[float, float]   # mm; centre of cell (row=1, col=1)
    order: str                    # "row_major" (only one supported in v1)
    layer: Layer
    parts_per_cell: List[GridCellPart]


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
