# Schema reference

Every key in `design.yaml` is documented here. All sizes and positions are in millimetres.

## Top-level keys

| Key | Type | Required | Description |
|---|---|---|---|
| `project` | object | yes | Project metadata |
| `board` | object | yes | Physical board properties |
| `global_nets` | list of string | no | Net names shared across every sheet |
| `templates` | dict | no | Named component templates |
| `sheets` | dict | yes | Sheet definitions. Must contain `"main"`. |

## `project`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | yes | -- | Project name. Used as the `.kicad_pcb` filename stem. |
| `kicad_version` | int | no | `10` | KiCad major version. Selects the default format stamp. |
| `format_version` | string | no | per `kicad_version` | `YYYYMMDD` date stamp written into `.kicad_pcb` / `.kicad_sch` headers. Override if you need to match a specific KiCad build; otherwise leave unset. |

## `board`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `size` | `[width, height]` | yes | -- | Board outline dimensions |
| `paper` | string | no | `"A4"` | Default schematic paper size |
| `zones` | list | no | `[]` | Board-level copper pours (see `board.zones[]`) |

### `board.zones[]`

Each entry defines a filled copper zone assigned to one net on one copper layer. Typical use is a GND pour on the back and a VCC pour on the front so that all power connections are handled without per-trace routing.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `net` | string | yes | -- | Net name. Globals pass through; other nets are resolved relative to the root sheet. |
| `layer` | string | yes | -- | KiCad layer name, e.g. `"F.Cu"` or `"B.Cu"`. |
| `polygon` | list of `[x, y]` | yes | -- | Zone outline as a closed polygon (3+ points, mm). |
| `clearance` | float | no | `0.5` | Pad clearance / thermal-relief gap (mm) |
| `min_thickness` | float | no | `0.254` | Minimum copper width when filled (mm) |
| `priority` | int | no | `0` | Fill priority when zones overlap — higher wins |
| `name` | string | no | -- | Optional zone label |

Zones are written unfilled. Press **B** in the KiCad PCB editor to fill them after opening the file.

```yaml
board:
  size: [205, 145]
  zones:
    - net: GND
      layer: B.Cu
      polygon: [[0, 0], [205, 0], [205, 145], [0, 145]]
    - net: VCC
      layer: F.Cu
      polygon: [[0, 0], [205, 0], [205, 145], [0, 145]]
```

## `global_nets`

A list of net names visible on every sheet via `GlobalLabel`. Use for power rails and any signal that needs to cross all sheet boundaries without a `pin_map` entry.

```yaml
global_nets: [VCC, GND]
```

## `templates`

Dict mapping template name to a reusable part definition. Components and grid cells reference templates by name.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `symbol` | `"lib:name"` | yes | -- | KiCad symbol library reference |
| `footprint` | `"lib:name"` | yes | -- | KiCad footprint library reference |
| `value` | string | no | `""` | Default value. Overridable per component. |

## `sheets`

Dict mapping sheet ID to sheet definition. `"main"` is required and serves as the root sheet.

### Sheet fields

| Field | Type | Default | Description |
|---|---|---|---|
| `paper` | string | `"A4"` | Paper size for this sheet's `.kicad_sch` |
| `components` | list | `[]` | Explicit component placements |
| `grids` | list | `[]` | Parametric grid definitions |
| `subsheets` | list | `[]` | Child sheet references |

## `components[]`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `ref` | string | yes | -- | Reference designator |
| `template` | string | * | -- | Template name from `templates:` |
| `symbol` | `"lib:name"` | * | -- | Inline symbol (alternative to template) |
| `footprint` | `"lib:name"` | * | -- | Inline footprint (alternative to template) |
| `value` | string | no | template's | Value text. Overrides template if set. |
| `pcb` | object | yes | -- | PCB placement (see below) |
| `pin_nets` | dict | yes | -- | Pin number/name to net name |
| `no_connect_pins` | list | no | `[]` | Pins that get NoConnect markers |
| `schematic` | object | no | auto | Schematic position override |
| `suppress_keepouts` | bool | no | `false` | Drop any footprint-embedded keepout (rule-area) zones on placement. Use for e.g. the ESP32-S3-WROOM-2 antenna keepout when you want copper pours / traces to flow through that region. Trades a small RF-performance penalty for routing freedom. |

*Either `template` or both `symbol` + `footprint` must be set.

### `pcb`

| Field | Type | Default | Description |
|---|---|---|---|
| `position` | `[x, y]` | required | Board coordinates |
| `layer` | `"front"` or `"back"` | `"front"` | Component side |
| `rotation` | float | `0` | Degrees CCW as viewed from the layer's outside |

### `schematic`

| Field | Type | Default | Description |
|---|---|---|---|
| `position` | `[x, y]` | auto | Schematic canvas position. Auto-placed if omitted. |

## `grids[]`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `id` | string | yes | -- | Grid identifier (used in error messages) |
| `shape` | `[cols, rows]` | yes | -- | Grid dimensions |
| `pitch` | `[x, y]` | yes | -- | Cell spacing |
| `origin` | `[x, y]` | yes | -- | Centre of cell (1,1) on the PCB |
| `order` | string | no | `"row_major"` | Cell numbering order (`row_major`, `row_major_serpentine`) |
| `start_corner` | string | no | `"top-left"` | Which physical corner gets `index = 1`. One of `top-left`, `top-right`, `bottom-left`, `bottom-right`. |
| `layer` | `"front"` / `"back"` | no | `"front"` | Default layer for all cell parts |
| `parts_per_cell` | list | yes | -- | Component definitions per cell |

### `grids[].parts_per_cell[]`

Same fields as `components[]` plus:

| Field | Type | Default | Description |
|---|---|---|---|
| `offset` | `[x, y]` | `[0, 0]` | Position offset from cell centre |
| `layer` | `"front"` / `"back"` | grid's | Per-part layer override |

`ref`, `value`, and `pin_nets` values support `{expression}` syntax.

### `grids[].vias_per_cell[]`

Stitching vias generated once per grid cell.  Typical use: drop a shared net (GND, VCC) from a front-side SMD pad down to a full-board copper pour on the other layer, without routing 117 individual stub tracks.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `net` | string | yes | -- | Net to connect. Globals pass through; sheet-local nets are resolved via the usual sheet-path rules. |
| `offset` | `[x, y]` | no | `[0, 0]` | Offset from cell centre. X is auto-mirrored for `layer: back` grids so a right-side offset still sits on the "right" of each cell when viewed from outside. |
| `size` | float | no | `0.6` | Via annular diameter (mm) |
| `drill` | float | no | `0.3` | Via hole diameter (mm) |

**Conflict detection.**  Before writing each via, kicad-yaml checks the candidate position against every pad on every back-side component.  Vias whose copper would overlap a back-side pad are silently dropped, and the build emits a warning with a list of the skipped `(row, col)` cells so you know which to route by hand.

### `grids[].tracks_per_cell[]`

Track segments generated once per grid cell.  Typical use: the LED-to-LED data chain on a daisy-chained matrix.  Each track references two pads — the "from" pad on a part in the current cell, and the "to" pad on a part that may live in *another* cell (usually `{index+1}`).  When a referenced ref doesn't resolve (e.g. off the end of the chain), that particular track is silently skipped.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `from_pad` | string | yes | -- | `"RefTemplate.padNumber"` — the pad the track starts from, with `{index}` / `{row}` / `{col}` substitution. |
| `to_pad` | string | yes | -- | Same format as `from_pad`, but usually references the next cell (e.g. `"LED{index+1}.4"`). |
| `net` | string | yes | -- | Net name template. Must match the net on both pads; used to look up the right net number. |
| `layer` | string | no | `"F.Cu"` | KiCad copper layer. |
| `width` | float | no | `0.25` | Track width (mm). |
| `style` | string | no | `"direct"` | `"direct"` = single segment pad → pad (may be diagonal). `"45"` = Z-shape with a 45° chamfer at each end and a straight middle run. |
| `corridor_offset` | `[dx, dy]` | no | `[0, 0]` | For `style: "45"` only. Pushes the middle run off the midpoint: `dy` is used on horizontal-dominant hops (shift the middle above/below a row of pads), `dx` on vertical-dominant hops (shift the middle left/right of a column). Use this to route the middle in *clear space* rather than through intermediate pads. If the offset would make the chamfers overlap, kicad-yaml silently falls back to the zero-offset shape. |

```yaml
tracks_per_cell:
  - from_pad: "LED{index}.2"      # DOUT of this cell's LED
    to_pad:   "LED{index+1}.4"    # DIN of next LED in the chain
    net:      "D{index+1}"
    layer:    F.Cu
    width:    0.25
```

The chain respects `order` + `start_corner`, so with `row_major_serpentine` + `start_corner: bottom-left`, every row-end hop naturally stays short.

**Grid orders:**

- `row_major` — index counts left-to-right within each row, top-to-bottom across rows. Cell (r, c) has `index = (r-1) * cols + c`.
- `row_major_serpentine` — same as `row_major` on odd rows (1, 3, 5…), reversed on even rows. Useful for daisy-chained LED matrices: the chain snakes back at each row end, so the last LED of row N and the first LED of row N+1 are physically adjacent and only need a short trace. Physical `row` and `col` are unchanged; only `index` (the chain position) flips on even rows.

**Grid `start_corner`:**

Picks which physical corner gets `index = 1`. The grid geometry (`origin`, `pitch`) is unchanged — only the index-to-cell mapping is permuted. Combine with `row_major_serpentine` to start a snaking chain from any corner. Example use: placing the first LED near an MCU pin at the bottom of the board so the highest-speed signal has the shortest possible entry trace.

## Expression syntax

Inside grid cell strings, `{...}` blocks are evaluated as safe arithmetic expressions.

**Variables** (all 1-based):

| Variable | Description |
|---|---|
| `index` | Flat cell position (1..rows*cols) |
| `row` | Row number (1..rows) |
| `col` | Column number (1..cols) |
| `rows` | Grid row count |
| `cols` | Grid column count |

**Operators:** `+`, `-`, `*`, `/`, `%`, comparisons, ternary (`'a' if x == 1 else 'b'`).

**Not supported (v1):** function calls, attribute access, list indexing.

## `subsheets[]`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `sheet` | string | yes | -- | Child sheet ID. Must exist in `sheets:`. |
| `label` | string | no | sheet ID | Display name on the sheet symbol |
| `schematic` | object | yes | -- | Requires `position: [x, y]` |
| `size` | `[w, h]` | yes | -- | Sheet symbol box dimensions |
| `pin_map` | dict | no | `{}` | `{parent_net: child_net}` for boundary-crossing signals |

**Rules:**
- `global_nets` members are shared automatically. They don't need `pin_map` entries.
- Sheet-local nets stay inside their sheet unless listed in a parent's `pin_map`.
- `pin_map` keys must be nets used on the parent sheet. Values must be nets used on the child sheet.
- The tool generates `HierarchicalLabel`, `HierarchicalSheet`, and `HierarchicalPin` automatically.
