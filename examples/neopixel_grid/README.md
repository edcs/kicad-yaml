# NeoPixel Grid — kicad-yaml Example

An 8×8 WS2812B LED grid with per-LED decoupling caps and a 3-pin header for power + data.

## Build

```bash
kicad-yaml build design.yaml
# Writes: neopixel_grid.kicad_pcb, main.kicad_sch
```

## Design

- 64 × WS2812B on a 10 mm grid (front)
- 64 × 100 nF decoupling caps (front, 3 mm below each LED)
- 1 × 3-pin header J1 for VCC / Data / GND (front, bottom-left)
- Board: 100 × 100 mm
