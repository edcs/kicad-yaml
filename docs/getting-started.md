# Getting started

## Install

```bash
git clone https://github.com/edcs/kicad-yaml.git
cd kicad-yaml
uv venv --python 3.12 .venv
.venv/bin/pip install -e ".[dev]"
```

Requires a stock KiCad 10 installation. The tool auto-detects the library location on macOS, Linux, and Windows. To override:

```bash
export KICAD_SHARE=/path/to/kicad/SharedSupport
```

## CLI

```
kicad-yaml build <design.yaml> [--output-dir DIR] [--reload]
kicad-yaml validate <design.yaml>
kicad-yaml --version
```

`build` writes one `.kicad_pcb` and one `.kicad_sch` per sheet. Files go alongside the YAML file, or into `--output-dir`.

`validate` runs the loader and library checks without writing files.

### `--reload` (macOS)

Asks a running KiCad PCB Editor to reload the file via AppleScript (**File → Revert**). Requires a one-time grant of Accessibility permission to the terminal you run this from:

**System Settings → Privacy & Security → Accessibility → + → your terminal app**.

On Linux and Windows, `--reload` is a silent no-op. If KiCad isn't running or the permission isn't granted, `build` still succeeds and emits a warning explaining what to do.

## Route preservation

When `build` overwrites an existing `.kicad_pcb`, it reads the previous file first and copies every track segment, arc, and via into the new output. Manually routed traces therefore survive rebuilds.

- If a component's position didn't change in the YAML, its tracks stay electrically valid.
- If a component moved, its tracks will be stale in the new board — they show up as DRC errors and can be rerouted.
- To start from a clean slate, delete the `.kicad_pcb` before building.

Board-level zones (`board.zones`) are regenerated from the YAML on every build, not preserved from the previous file.

## KiCad file-format version

Each generated `.kicad_pcb` / `.kicad_sch` carries a `YYYYMMDD` format stamp in its header. kicad-yaml writes the correct stamp for the major KiCad version declared in `project.kicad_version` (default `10` → `20260206`), so you won't see KiCad's "This file was created by an older version" banner on open.

Override only if you need a specific build:

```yaml
project:
  name: wordclock
  kicad_version: 10
  format_version: "20270101"
```

## Python API

```python
from pathlib import Path
from kicad_yaml import build, validate, BuildResult

# Build from a file path
result: BuildResult = build(Path("design.yaml"))

# Build from a literal YAML string (useful for MCP tool calls)
result = build(yaml_string, output_dir=Path("./out"))

# Validate without writing
result = validate(Path("design.yaml"))

# Structured result
if result.success:
    for path in result.generated_files:
        print(f"wrote {path}")
else:
    for error in result.errors:
        print(f"[{error.code}] {error.message}")
```

`build()` and `validate()` return a `BuildResult` with structured `Message` objects. Expected failures like schema errors and missing libraries appear in `result.errors`. Only truly unexpected failures raise exceptions.

### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `yaml_source` | `Path` or `str` | required | `Path` reads from disk. `str` is parsed as literal YAML content. |
| `output_dir` | `Path` or `None` | YAML file's directory | Where to write generated files |
| `kicad_share` | `Path` or `None` | auto-detect | Override KiCad library root |
| `reload_kicad` | `bool` | `False` | After writing, try to reload an open KiCad PCB Editor (macOS only) |

## Tests

```bash
.venv/bin/pytest -v
```

Some tests require a KiCad 10 installation and are skipped automatically if one isn't found.
