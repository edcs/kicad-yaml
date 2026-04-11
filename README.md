# kicad-yaml

Describe a KiCad PCB design in YAML. Get valid schematic and PCB files out.

## Why

In SolidWorks, a **design table** lets you define a parametric model in a spreadsheet. Dimensions, configurations, and variants live as pure data. The CAD engine generates the geometry.

There's no equivalent for KiCad. If you want to programmatically generate a board, you write a bespoke Python script against kiutils or pcbnew, mixing design intent with file-format plumbing.

`kicad-yaml` separates the two. You describe *what* your board is in a declarative YAML file. The tool handles *how* to turn that into `.kicad_pcb` and `.kicad_sch` files.

## What it's for

The primary use case isn't hand-authoring YAML. It's providing a **stable, well-documented protocol** that AI tools can target:

- **MCP servers** that generate or modify PCB designs from natural-language instructions
- **AI coding assistants** that can read and write the schema without understanding KiCad's S-expression format
- **Automated pipelines** that produce boards from higher-level specs

The YAML schema is the contract, and the Python tool is the reference compiler.

## Quick start

```bash
git clone https://github.com/edcs/kicad-yaml.git
cd kicad-yaml
uv venv --python 3.12 .venv
.venv/bin/pip install -e ".[dev]"
```

Requires KiCad 10. On non-default installs, set `KICAD_SHARE`:

```bash
export KICAD_SHARE=/path/to/kicad/SharedSupport
```

Build the included example:

```bash
kicad-yaml build examples/neopixel_grid/design.yaml
```

## Documentation

- [Getting started](docs/getting-started.md): install, CLI, first build
- [Schema reference](docs/schema.md): every YAML key documented
- [Examples](docs/examples.md): flat grids, hierarchical sheets, back-side components

## Public API

The CLI wraps a Python API. Any UI layer can call it directly.

```python
from kicad_yaml import build, validate

result = build("design.yaml", output_dir="./out")
# result.success, result.generated_files, result.errors
```

See [Getting started](docs/getting-started.md) for details.

## Status

v0.1.0: Flat and hierarchical sheets, grid parametrics, back-side components, expression syntax. KiCad 10 only.

## License

MIT
