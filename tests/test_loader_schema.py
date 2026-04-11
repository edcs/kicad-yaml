"""Schema-pass tests for the YAML loader."""

from pathlib import Path
import pytest
from kicad_yaml.loader import load_design, LoadError
from kicad_yaml.schema import Design, Layer

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_minimal_flat():
    design = load_design(FIXTURES / "minimal_flat.yaml")
    assert isinstance(design, Design)
    assert design.project.name == "minimal_flat"
    assert design.project.kicad_version == 10
    assert design.board.size == (50.0, 30.0)
    assert design.global_nets == ["VCC", "GND"]
    assert "led" in design.templates
    assert design.templates["led"].symbol == "LED:WS2812B"
    assert "main" in design.sheets

    main = design.sheets["main"]
    assert len(main.components) == 1
    led1 = main.components[0]
    assert led1.ref == "LED1"
    assert led1.template == "led"
    assert led1.pcb.position == (10.0, 15.0)
    assert led1.pcb.layer is Layer.FRONT
    assert led1.pin_nets == {"1": "VCC", "2": "D1", "3": "GND", "4": "D0"}


def test_unknown_top_level_key_errors():
    bad = """
project:
  name: x
board:
  size: [10, 10]
global_nets: []
templates: {}
sheets:
  main:
    paper: A4
extra_key: oops
"""
    with pytest.raises(LoadError, match="unknown key 'extra_key'"):
        load_design(bad)


def test_missing_main_sheet_errors():
    bad = """
project: {name: x}
board: {size: [10, 10]}
global_nets: []
templates: {}
sheets:
  other:
    paper: A4
"""
    with pytest.raises(LoadError, match="main"):
        load_design(bad)


def test_load_accepts_literal_yaml_string():
    yaml_text = (FIXTURES / "minimal_flat.yaml").read_text()
    design = load_design(yaml_text)
    assert design.project.name == "minimal_flat"


def test_load_accepts_pathlib_path():
    design = load_design(FIXTURES / "minimal_flat.yaml")
    assert design.project.name == "minimal_flat"
