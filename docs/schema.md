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
| `kicad_version` | int | no | `10` | KiCad file format major version |

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
| `order` | string | no | `"row_major"` | Cell numbering order |
| `layer` | `"front"` / `"back"` | no | `"front"` | Default layer for all cell parts |
| `parts_per_cell` | list | yes | -- | Component definitions per cell |

### `grids[].parts_per_cell[]`

Same fields as `components[]` plus:

| Field | Type | Default | Description |
|---|---|---|---|
| `offset` | `[x, y]` | `[0, 0]` | Position offset from cell centre |
| `layer` | `"front"` / `"back"` | grid's | Per-part layer override |

`ref`, `value`, and `pin_nets` values support `{expression}` syntax.

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
