"""Tests for the pure-data schema classes (no kiutils, no YAML)."""

import pytest
from kicad_yaml.schema import (
    Project,
    Board,
    Layer,
    PcbConfig,
    SchematicConfig,
    Template,
    Component,
    Grid,
    GridCellPart,
    Sheet,
    Design,
)


def test_layer_enum():
    assert Layer.FRONT.value == "front"
    assert Layer.BACK.value == "back"
    assert Layer("front") is Layer.FRONT


def test_component_minimal_fields():
    comp = Component(
        ref="R1",
        template="resistor_0603",
        value="330",
        pcb=PcbConfig(position=(12.5, 17.5), layer=Layer.BACK, rotation=0.0),
        pin_nets={"1": "MCU_DATA", "2": "D1"},
    )
    assert comp.ref == "R1"
    assert comp.pcb.layer is Layer.BACK
    assert comp.pin_nets["1"] == "MCU_DATA"
    assert comp.no_connect_pins == []
    assert comp.schematic is None


def test_grid_cell_part_defaults():
    cell = GridCellPart(
        template="ws2812b",
        ref="LED{index}",
        pin_nets={"1": "VCC", "2": "D{index+1}", "3": "GND", "4": "D{index}"},
    )
    assert cell.offset == (0.0, 0.0)
    assert cell.layer is None  # inherits from grid


def test_design_minimal():
    design = Design(
        project=Project(name="test", kicad_version=10),
        board=Board(size=(50.0, 30.0), paper="A4"),
        global_nets=["VCC", "GND"],
        templates={},
        sheets={
            "main": Sheet(paper="A4", components=[], grids=[], subsheets=[]),
        },
    )
    assert "main" in design.sheets
    assert design.global_nets == ["VCC", "GND"]


def test_design_requires_main_sheet():
    with pytest.raises(ValueError, match="'main'"):
        Design(
            project=Project(name="test", kicad_version=10),
            board=Board(size=(50.0, 30.0), paper="A4"),
            global_nets=[],
            templates={},
            sheets={"other": Sheet(paper="A4", components=[], grids=[], subsheets=[])},
        )
