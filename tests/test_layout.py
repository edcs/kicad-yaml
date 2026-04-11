"""Layout engine tests: grid expansion, layer flip, rotation math."""

import pytest
from kicad_yaml.schema import (
    Board, Component, Design, Grid, GridCellPart, Layer, PcbConfig,
    Project, Sheet, Template,
)
from kicad_yaml.layout import (
    ResolvedComponent,
    expand_design,
    resolve_rotation_for_layer,
)


def _template() -> Template:
    return Template(symbol="Fake:FakeC", footprint="Fake:FakeSMD", value="100n")


def _design(
    *,
    components: list[Component] | None = None,
    grids: list[Grid] | None = None,
) -> Design:
    return Design(
        project=Project(name="t"),
        board=Board(size=(100.0, 100.0)),
        global_nets=["VCC", "GND"],
        templates={"cap": _template()},
        sheets={
            "main": Sheet(
                paper="A4",
                components=components or [],
                grids=grids or [],
            ),
        },
    )


def test_resolve_rotation_front_passthrough():
    assert resolve_rotation_for_layer(90.0, Layer.FRONT) == 90.0
    assert resolve_rotation_for_layer(0.0, Layer.FRONT) == 0.0


def test_resolve_rotation_back_inverts():
    assert resolve_rotation_for_layer(90.0, Layer.BACK) == 270.0
    assert resolve_rotation_for_layer(270.0, Layer.BACK) == 90.0
    assert resolve_rotation_for_layer(0.0, Layer.BACK) == 0.0
    assert resolve_rotation_for_layer(180.0, Layer.BACK) == 180.0


def test_expand_flat_components():
    comp = Component(
        ref="C1",
        template="cap",
        pcb=PcbConfig(position=(10.0, 20.0)),
        pin_nets={"1": "VCC", "2": "GND"},
    )
    resolved = expand_design(_design(components=[comp]))
    assert len(resolved) == 1
    r = resolved[0]
    assert r.ref == "C1"
    assert r.sheet_id == "main"
    assert r.pcb_position == (10.0, 20.0)
    assert r.pcb_layer is Layer.FRONT
    assert r.pin_nets == {"1": "VCC", "2": "GND"}
    assert r.symbol_lib_name == "Fake:FakeC"
    assert r.footprint_lib_name == "Fake:FakeSMD"
    assert r.value == "100n"


def test_component_value_overrides_template():
    comp = Component(
        ref="C1",
        template="cap",
        value="1u",                 # overrides template's "100n"
        pcb=PcbConfig(position=(0.0, 0.0)),
        pin_nets={"1": "VCC"},
    )
    r = expand_design(_design(components=[comp]))[0]
    assert r.value == "1u"


def test_expand_grid_row_major_2x2():
    grid = Grid(
        id="leds",
        shape=(2, 2),
        pitch=(10.0, 10.0),
        origin=(5.0, 5.0),
        order="row_major",
        layer=Layer.FRONT,
        parts_per_cell=[
            GridCellPart(
                template="cap",
                ref="LED{index}",
                pin_nets={"1": "VCC", "2": "D{index+1}", "3": "GND", "4": "D{index}"},
            ),
        ],
    )
    resolved = expand_design(_design(grids=[grid]))
    assert len(resolved) == 4
    refs = sorted(r.ref for r in resolved)
    assert refs == ["LED1", "LED2", "LED3", "LED4"]
    by_ref = {r.ref: r for r in resolved}
    assert by_ref["LED1"].pcb_position == (5.0, 5.0)
    assert by_ref["LED2"].pcb_position == (15.0, 5.0)
    assert by_ref["LED3"].pcb_position == (5.0, 15.0)
    assert by_ref["LED4"].pcb_position == (15.0, 15.0)
    assert by_ref["LED1"].pin_nets == {"1": "VCC", "2": "D2", "3": "GND", "4": "D1"}
    assert by_ref["LED4"].pin_nets == {"1": "VCC", "2": "D5", "3": "GND", "4": "D4"}


def test_grid_cell_with_offset():
    grid = Grid(
        id="caps",
        shape=(2, 1),
        pitch=(10.0, 10.0),
        origin=(5.0, 5.0),
        order="row_major",
        layer=Layer.FRONT,
        parts_per_cell=[
            GridCellPart(
                template="cap",
                ref="C{index}",
                pin_nets={"1": "VCC", "2": "GND"},
                offset=(0.0, 3.0),
            ),
        ],
    )
    resolved = expand_design(_design(grids=[grid]))
    assert resolved[0].pcb_position == (5.0, 8.0)
    assert resolved[1].pcb_position == (15.0, 8.0)


def test_grid_cell_back_layer_flips_offset_x():
    """Grid cell on the back: offset X is mirrored so the cell part
    sits where the user expects when they look at the back view."""
    grid = Grid(
        id="caps",
        shape=(2, 1),
        pitch=(10.0, 10.0),
        origin=(5.0, 5.0),
        order="row_major",
        layer=Layer.BACK,
        parts_per_cell=[
            GridCellPart(
                template="cap",
                ref="C{index}",
                pin_nets={"1": "VCC", "2": "GND"},
                offset=(2.0, 0.0),
            ),
        ],
    )
    resolved = expand_design(_design(grids=[grid]))
    # X offset +2 on back should mirror to -2 in stored PCB coords
    assert resolved[0].pcb_position == (3.0, 5.0)
    assert resolved[0].pcb_layer is Layer.BACK
