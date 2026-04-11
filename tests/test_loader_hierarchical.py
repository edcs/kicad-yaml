"""Cross-sheet validation tests for the loader."""

import pytest
from kicad_yaml.loader import load_design, LoadError


def _yaml(main_components: str, child_components: str, pin_map: str) -> str:
    return f"""
project: {{name: t}}
board: {{size: [50, 30]}}
global_nets: [VCC, GND]
templates:
  cap:
    symbol: LED:WS2812B
    footprint: LED_SMD:LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm
sheets:
  main:
    paper: A3
    components: {main_components}
    subsheets:
      - sheet: child
        label: Child
        schematic:
          position: [100, 50]
        size: [40, 30]
        pin_map: {pin_map}
  child:
    paper: A4
    components: {child_components}
"""


def test_subsheet_unknown_errors():
    yaml = """
project: {name: t}
board: {size: [50, 30]}
global_nets: []
templates: {}
sheets:
  main:
    paper: A4
    subsheets:
      - sheet: ghost
        label: ghost
        schematic: {position: [10, 10]}
        size: [20, 20]
"""
    with pytest.raises(LoadError, match="unknown subsheet 'ghost'"):
        load_design(yaml)


def test_pin_map_value_must_exist_in_child():
    main = """
      - ref: R1
        template: cap
        pcb: {position: [10, 10]}
        pin_nets: {"1": D0, "2": GND}
    """
    child = """
      - ref: LED1
        template: cap
        pcb: {position: [10, 10]}
        pin_nets: {"1": VCC, "2": GND}
    """
    pin_map = '{D0: CHAIN_IN}'
    with pytest.raises(LoadError, match="pin_map value 'CHAIN_IN'.*child"):
        load_design(_yaml(main, child, pin_map))


def test_pin_map_key_must_exist_in_parent():
    main = """
      - ref: R1
        template: cap
        pcb: {position: [10, 10]}
        pin_nets: {"1": GND, "2": GND}
    """
    child = """
      - ref: LED1
        template: cap
        pcb: {position: [10, 10]}
        pin_nets: {"1": CHAIN_IN, "2": GND}
    """
    # pin_map key D0 isn't used anywhere in main
    pin_map = '{D0: CHAIN_IN}'
    with pytest.raises(LoadError, match="pin_map key 'D0'.*main"):
        load_design(_yaml(main, child, pin_map))


def test_valid_pin_map_passes():
    main = """
      - ref: R1
        template: cap
        pcb: {position: [10, 10]}
        pin_nets: {"1": D0, "2": GND}
    """
    child = """
      - ref: LED1
        template: cap
        pcb: {position: [10, 10]}
        pin_nets: {"1": CHAIN_IN, "2": GND}
    """
    pin_map = '{D0: CHAIN_IN}'
    design = load_design(_yaml(main, child, pin_map))
    assert "child" in design.sheets
    assert design.sheets["main"].subsheets[0].pin_map == {"D0": "CHAIN_IN"}


def test_pin_map_with_grid_generated_net_passes():
    """pin_map value D1 matches the grid's expanded D{index} for index=1."""
    main = """
      - ref: R1
        template: cap
        pcb: {position: [10, 10]}
        pin_nets: {"1": D1, "2": GND}
    """
    child_grid = """
    grids:
      - id: leds
        shape: [2, 1]
        pitch: [15, 15]
        origin: [10, 10]
        parts_per_cell:
          - template: cap
            ref: "LED{index}"
            pin_nets:
              "1": VCC
              "2": "D{index}"
    """
    yaml = f"""
project: {{name: t}}
board: {{size: [50, 30]}}
global_nets: [VCC, GND]
templates:
  cap:
    symbol: LED:WS2812B
    footprint: LED_SMD:LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm
sheets:
  main:
    paper: A3
    components: {main}
    subsheets:
      - sheet: child
        label: Child
        schematic:
          position: [100, 50]
        size: [40, 30]
        pin_map: {{D1: D1}}
  child:
    paper: A4
    components: []
{child_grid}
"""
    design = load_design(yaml)
    assert design.sheets["main"].subsheets[0].pin_map == {"D1": "D1"}
