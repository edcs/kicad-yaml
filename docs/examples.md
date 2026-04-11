# Examples

## Flat design: NeoPixel grid

The included example at `examples/neopixel_grid/design.yaml` demonstrates the core features on a single sheet:

- 8x8 WS2812B LED grid at 10mm pitch
- Per-LED 100nF decoupling cap with 3mm offset
- 3-pin header for VCC, Data, and GND
- 100 x 100mm board

```yaml
project:
  name: neopixel_grid

board:
  size: [100, 100]

global_nets: [VCC, GND]

templates:
  ws2812b:
    symbol: LED:WS2812B
    footprint: LED_SMD:LED_WS2812B_PLCC4_5.0x5.0mm_P3.2mm
    value: WS2812B
  decoupling_cap:
    symbol: Device:C
    footprint: Capacitor_SMD:C_0603_1608Metric_Pad1.08x0.95mm_HandSolder
    value: 100nF

sheets:
  main:
    paper: A4
    components:
      - ref: J1
        symbol: Connector_Generic:Conn_01x03
        footprint: Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical
        value: "Header 3P"
        pcb:
          position: [10, 90]
        pin_nets:
          "1": VCC
          "2": D1
          "3": GND
    grids:
      - id: leds
        shape: [8, 8]
        pitch: [10, 10]
        origin: [15, 15]
        parts_per_cell:
          - template: ws2812b
            ref: "LED{index}"
            pin_nets:
              "1": VCC
              "2": "D{index+1}"
              "3": GND
              "4": "D{index}"
          - template: decoupling_cap
            ref: "C{index}"
            offset: [0, 3]
            pin_nets:
              "1": VCC
              "2": GND
```

Build it:

```bash
kicad-yaml build examples/neopixel_grid/design.yaml
```

## Hierarchical design

Split a large design across sheets. The main sheet holds connectors and power. A subsheet holds the LED matrix.

```yaml
global_nets: [VCC, GND]

sheets:
  main:
    paper: A3
    components:
      - ref: R1
        template: resistor_0603
        pcb: {position: [5, 5], layer: back}
        pin_nets: {"1": MCU_DATA, "2": D1}
    subsheets:
      - sheet: led_matrix
        label: "LED Matrix"
        schematic: {position: [150, 80]}
        size: [50, 40]
        pin_map:
          D1: D1            # parent net D1 ↔ child net D1

  led_matrix:
    paper: A2
    grids:
      - id: leds
        shape: [13, 9]
        # ...
```

**How nets cross sheet boundaries:**

- `global_nets` are shared across all sheets automatically. No `pin_map` needed for VCC or GND.
- Other nets are sheet-local unless exposed via `subsheets[].pin_map`.
- `pin_map` keys are the parent-side names. Values are the child-side names. They can be the same string.
- The tool generates `HierarchicalLabel`, `HierarchicalSheet`, and `HierarchicalPin` in the KiCad output. You just declare the mapping.

## Back-side components

```yaml
components:
  - ref: J1
    template: usb_c
    pcb:
      position: [20, 125]
      layer: back
      rotation: 90      # 90° CCW as viewed from the back
    pin_nets:
      A1: GND
      A4: VCC
      # ...
```

`rotation` is always expressed as degrees counter-clockwise, **as viewed from the outside of the layer the part sits on**. The tool converts this to KiCad's internal convention automatically.

## Grid expressions

Template variables inside grid cells (`{...}`) are evaluated per-cell using [simpleeval](https://github.com/danthedeluxe/simpleeval):

| Variable | Description | Range |
|---|---|---|
| `index` | Flat cell position | 1..rows*cols |
| `row` | Row number | 1..rows |
| `col` | Column number | 1..cols |
| `rows` | Grid row count | constant |
| `cols` | Grid column count | constant |

Arithmetic, comparison, and ternary expressions are supported:

```yaml
ref: "LED{index}"
ref: "KEY{(row-1)*cols+col}"
pin_nets: {"2": "D{index+1}"}
pin_nets: {"1": "{'VCC' if row == 1 else 'ROW_POS'}"}
```
