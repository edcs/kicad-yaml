"""Tests for SheetTopology — sheet tree walking helper."""

import pytest
from kicad_yaml.schema import (
    Board, Component, Design, GridCellPart, Layer, PcbConfig,
    Project, SchematicConfig, Sheet, Subsheet, Template,
)
from kicad_yaml.topology import SheetTopology, TopologyError


def _design_flat() -> Design:
    return Design(
        project=Project(name="t"),
        board=Board(size=(50.0, 30.0)),
        global_nets=["VCC", "GND"],
        templates={},
        sheets={"main": Sheet(paper="A4")},
    )


def _comp(ref: str, pin_nets: dict[str, str]) -> Component:
    return Component(
        ref=ref,
        template="cap",
        pcb=PcbConfig(position=(0, 0)),
        pin_nets=pin_nets,
    )


def _design_two_level() -> Design:
    main_comp = _comp("R1", {"1": "MCU_DATA", "2": "D0"})
    child_comp = _comp("LED1", {"1": "VCC", "2": "CHAIN_IN"})
    return Design(
        project=Project(name="t"),
        board=Board(size=(100.0, 50.0)),
        global_nets=["VCC", "GND"],
        templates={"cap": Template(symbol="F:C", footprint="F:S")},
        sheets={
            "main": Sheet(
                paper="A3",
                components=[main_comp],
                subsheets=[
                    Subsheet(
                        sheet_id="led_matrix",
                        label="LED Matrix",
                        schematic=SchematicConfig(position=(150, 100)),
                        size=(50, 40),
                        pin_map={"D0": "CHAIN_IN"},
                    ),
                ],
            ),
            "led_matrix": Sheet(
                paper="A2",
                components=[child_comp],
            ),
        },
    )


def test_topology_flat_has_only_main():
    topo = SheetTopology.from_design(_design_flat())
    assert topo.root == "main"
    assert topo.children_of("main") == []
    assert topo.parent_of("main") is None
    assert topo.sheet_path("main") == ["main"]
    assert topo.sheet_uuid_path("main") == [topo.uuid_for("main")]


def test_topology_two_level_tree():
    topo = SheetTopology.from_design(_design_two_level())
    assert topo.children_of("main") == ["led_matrix"]
    assert topo.parent_of("led_matrix") == "main"
    assert topo.parent_of("main") is None
    assert topo.sheet_path("led_matrix") == ["main", "led_matrix"]


def test_topology_allocates_unique_uuids_per_sheet():
    topo = SheetTopology.from_design(_design_two_level())
    uuids = {topo.uuid_for(s) for s in topo.all_sheets()}
    assert len(uuids) == 2


def test_topology_pin_map_for_child():
    topo = SheetTopology.from_design(_design_two_level())
    # led_matrix is exposed by main with pin_map {D0 -> CHAIN_IN}
    assert topo.parent_pin_map("led_matrix") == {"D0": "CHAIN_IN"}
    assert topo.parent_pin_map("main") == {}


def test_topology_exposed_child_net_names():
    topo = SheetTopology.from_design(_design_two_level())
    # Child-side names (the values in pin_map)
    assert topo.exposed_nets_for_sheet("led_matrix") == {"CHAIN_IN"}
    assert topo.exposed_nets_for_sheet("main") == set()


def test_topology_subsheet_cycle_errors():
    """A sheet cannot (indirectly) include itself."""
    design = Design(
        project=Project(name="t"),
        board=Board(size=(50.0, 30.0)),
        global_nets=[],
        templates={},
        sheets={
            "main": Sheet(
                paper="A4",
                subsheets=[
                    Subsheet(
                        sheet_id="a",
                        label="a",
                        schematic=SchematicConfig(position=(0, 0)),
                        size=(10, 10),
                    ),
                ],
            ),
            "a": Sheet(
                paper="A4",
                subsheets=[
                    Subsheet(
                        sheet_id="main",
                        label="main",
                        schematic=SchematicConfig(position=(0, 0)),
                        size=(10, 10),
                    ),
                ],
            ),
        },
    )
    with pytest.raises(TopologyError, match="cycle"):
        SheetTopology.from_design(design)


def test_topology_unknown_subsheet_errors():
    design = Design(
        project=Project(name="t"),
        board=Board(size=(50.0, 30.0)),
        global_nets=[],
        templates={},
        sheets={
            "main": Sheet(
                paper="A4",
                subsheets=[
                    Subsheet(
                        sheet_id="ghost",
                        label="ghost",
                        schematic=SchematicConfig(position=(0, 0)),
                        size=(10, 10),
                    ),
                ],
            ),
        },
    )
    with pytest.raises(TopologyError, match="unknown subsheet 'ghost'"):
        SheetTopology.from_design(design)


def test_topology_sheet_with_two_parents_errors():
    design = Design(
        project=Project(name="t"),
        board=Board(size=(50.0, 30.0)),
        global_nets=[],
        templates={},
        sheets={
            "main": Sheet(
                paper="A4",
                subsheets=[
                    Subsheet(sheet_id="a", label="a",
                             schematic=SchematicConfig(position=(0, 0)),
                             size=(10, 10)),
                    Subsheet(sheet_id="a", label="a2",
                             schematic=SchematicConfig(position=(0, 50)),
                             size=(10, 10)),
                ],
            ),
            "a": Sheet(paper="A4"),
        },
    )
    with pytest.raises(TopologyError, match="multiple parents"):
        SheetTopology.from_design(design)
