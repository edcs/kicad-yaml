"""Semantic (cross-reference) validation tests for the loader."""

import pytest
from kicad_yaml.loader import load_design, LoadError


BASE = """
project: {{name: t}}
board: {{size: [50, 30]}}
global_nets: [VCC, GND]
templates:
  led:
    symbol: LED:WS2812B
    footprint: LED_SMD:LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm
    value: WS2812B
sheets:
  main:
    paper: A4
    components: {components}
    grids: {grids}
"""


def _yaml(components: str = "[]", grids: str = "[]") -> str:
    return BASE.format(components=components, grids=grids)


def test_loader_accepts_board_layers_2():
    yaml = BASE.replace("{{size: [50, 30]}}", "{{size: [50, 30], layers: 2}}") \
               .format(components="[]", grids="[]")
    design = load_design(yaml)
    assert design.board.layers == 2


def test_loader_accepts_board_layers_4():
    yaml = BASE.replace("{{size: [50, 30]}}", "{{size: [50, 30], layers: 4}}") \
               .format(components="[]", grids="[]")
    design = load_design(yaml)
    assert design.board.layers == 4


def test_loader_rejects_invalid_layer_count():
    yaml = BASE.replace("{{size: [50, 30]}}", "{{size: [50, 30], layers: 6}}") \
               .format(components="[]", grids="[]")
    with pytest.raises(LoadError, match="board.layers must be 2 or 4"):
        load_design(yaml)


def test_component_with_unknown_template_errors():
    bad_component = """
      - ref: LED1
        template: ghost
        pcb:
          position: [10, 10]
        pin_nets: {"1": VCC}
    """
    with pytest.raises(LoadError, match="unknown template 'ghost'"):
        load_design(_yaml(components=bad_component))


def test_component_without_template_or_symbol_errors():
    bad_component = """
      - ref: LED1
        pcb:
          position: [10, 10]
        pin_nets: {"1": VCC}
    """
    with pytest.raises(LoadError, match="LED1.*must set 'template' or both 'symbol' and 'footprint'"):
        load_design(_yaml(components=bad_component))


def test_duplicate_refs_error():
    dup = """
      - ref: LED1
        template: led
        pcb: {position: [10, 10]}
        pin_nets: {"1": VCC}
      - ref: LED1
        template: led
        pcb: {position: [20, 10]}
        pin_nets: {"1": VCC}
    """
    with pytest.raises(LoadError, match="duplicate ref 'LED1'"):
        load_design(_yaml(components=dup))


def test_grid_with_invalid_expression_errors():
    bad_grid = """
      - id: leds
        shape: [2, 1]
        pitch: [15, 15]
        origin: [10, 10]
        parts_per_cell:
          - template: led
            ref: "LED{missing_var}"
            pin_nets: {"1": VCC}
    """
    with pytest.raises(LoadError, match="missing_var"):
        load_design(_yaml(grids=bad_grid))


def test_grid_with_invalid_order_errors():
    bad = """
      - id: leds
        shape: [2, 1]
        pitch: [15, 15]
        origin: [10, 10]
        order: spiral
        parts_per_cell:
          - template: led
            ref: "LED{index}"
            pin_nets: {"1": VCC}
    """
    with pytest.raises(LoadError, match="unknown grid order 'spiral'"):
        load_design(_yaml(grids=bad))


def test_grid_with_nonpositive_pitch_errors():
    bad = """
      - id: leds
        shape: [2, 1]
        pitch: [0, 15]
        origin: [10, 10]
        parts_per_cell:
          - template: led
            ref: "LED{index}"
            pin_nets: {"1": VCC}
    """
    with pytest.raises(LoadError, match="pitch.*positive"):
        load_design(_yaml(grids=bad))


def test_valid_grid_passes():
    ok = """
      - id: leds
        shape: [2, 1]
        pitch: [15, 15]
        origin: [10, 10]
        parts_per_cell:
          - template: led
            ref: "LED{index}"
            pin_nets:
              "1": VCC
              "2": "D{index+1}"
              "3": GND
              "4": "D{index}"
    """
    design = load_design(_yaml(grids=ok))
    assert len(design.sheets["main"].grids) == 1
