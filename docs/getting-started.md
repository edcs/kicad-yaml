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
kicad-yaml build <design.yaml> [--output-dir DIR]
kicad-yaml validate <design.yaml>
kicad-yaml --version
```

`build` writes one `.kicad_pcb` and one `.kicad_sch` per sheet. Files go alongside the YAML file, or into `--output-dir`.

`validate` runs the loader and library checks without writing files.

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

## Tests

```bash
.venv/bin/pytest -v
```

Some tests require a KiCad 10 installation and are skipped automatically if one isn't found.
