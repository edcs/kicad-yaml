"""Tests for schematic auto-layout."""

import math

from kicad_yaml.schema import (
    Board, Component, Design, Grid, GridCellPart, Layer, PcbConfig,
    Project, Sheet, SchematicConfig, Template,
)
from kicad_yaml.layout import expand_design, assign_schematic_positions


def _template() -> Template:
    return Template(symbol="Fake:FakeC", footprint="Fake:FakeSMD", value="100n")


def _design(**sheet_kwargs) -> Design:
    return Design(
        project=Project(name="t"),
        board=Board(size=(100.0, 100.0)),
        global_nets=["VCC", "GND"],
        templates={"cap": _template()},
        sheets={"main": Sheet(paper="A4", **sheet_kwargs)},
    )


def test_auto_layout_three_components_on_dense_grid():
    """With 3 auto-placed components, sqrt(3)~=2 columns, so we get
    2 cols x 2 rows, 3 entries filled in row-major order."""
    comps = [
        Component(ref=f"R{i}", template="cap",
                  pcb=PcbConfig(position=(0, 0)),
                  pin_nets={"1": "VCC", "2": "GND"})
        for i in range(1, 4)
    ]
    resolved = expand_design(_design(components=comps))
    assign_schematic_positions(resolved, sheet_paper="A4")
    positions = [r.sch_position for r in resolved]
    assert all(p is not None for p in positions)
    # 3 items -> ceil(sqrt(3)) = 2 cols
    cols = math.ceil(math.sqrt(3))
    assert cols == 2
    # positions[0] and positions[1] same row (row 0), positions[2] row 1
    assert positions[0][1] == positions[1][1]
    assert positions[2][1] > positions[0][1]
    assert positions[0][0] != positions[1][0]


def test_auto_layout_respects_explicit_positions():
    comps = [
        Component(ref="R1", template="cap",
                  pcb=PcbConfig(position=(0, 0)),
                  pin_nets={"1": "VCC"},
                  schematic=SchematicConfig(position=(42.0, 77.0))),
    ]
    resolved = expand_design(_design(components=comps))
    assign_schematic_positions(resolved, sheet_paper="A4")
    assert resolved[0].sch_position == (42.0, 77.0)


def test_auto_layout_grid_uses_matching_grid():
    grid = Grid(
        id="g",
        shape=(3, 2),
        pitch=(10.0, 10.0),
        origin=(0.0, 0.0),
        order="row_major",
        layer=Layer.FRONT,
        parts_per_cell=[
            GridCellPart(template="cap", ref="C{index}",
                         pin_nets={"1": "VCC", "2": "GND"}),
        ],
    )
    resolved = expand_design(_design(grids=[grid]))
    assign_schematic_positions(resolved, sheet_paper="A2")
    # 6 cells, all placed, no duplicates, arranged on a schematic-pitch grid
    positions = [r.sch_position for r in resolved]
    assert all(p is not None for p in positions)
    assert len(set(positions)) == 6
