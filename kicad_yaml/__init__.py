"""Public API surface for kicad-yaml.

Every UI layer (CLI, future MCP server, future web UI) wraps these two
functions.  Exceptions are only raised for truly unexpected failures
(OS errors, internal bugs); expected failures (schema errors, missing
libraries, etc.) surface in ``BuildResult.errors``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Literal, Optional, Union

from kicad_yaml import kicad_net_patch  # noqa: F401 - apply the patch on import

__version__ = "0.0.1"


@dataclass
class SourceLocation:
    file: Optional[Path]
    line: Optional[int]
    column: Optional[int] = None


@dataclass
class Message:
    severity: Literal["error", "warning"]
    code: str
    message: str
    source: Optional[SourceLocation] = None


@dataclass
class BuildResult:
    success: bool
    generated_files: List[Path] = field(default_factory=list)
    warnings: List[Message] = field(default_factory=list)
    errors: List[Message] = field(default_factory=list)


YamlSource = Union[Path, str]


def build(
    yaml_source: YamlSource,
    output_dir: Optional[Path] = None,
    kicad_share: Optional[Path] = None,
) -> BuildResult:
    """Read a design YAML and write KiCad files."""
    from kicad_yaml.loader import load_design, LoadError
    from kicad_yaml.libraries import LibraryResolver, LibraryError
    from kicad_yaml.layout import expand_design, assign_schematic_positions
    from kicad_yaml.pcb import write_pcb
    from kicad_yaml.schematic import write_schematic
    from kicad_yaml.topology import SheetTopology, TopologyError

    if output_dir is None:
        if isinstance(yaml_source, Path):
            output_dir = yaml_source.parent
        else:
            return _fail("API-OUTPUT-DIR-REQUIRED",
                         "output_dir must be set when yaml_source is a string")
    output_dir = Path(output_dir)

    try:
        design = load_design(yaml_source)
    except LoadError as e:
        return _fail("LOAD-ERROR", str(e),
                     source=_source_for(yaml_source))

    try:
        libraries = LibraryResolver(kicad_share=kicad_share)
    except LibraryError as e:
        return _fail("LIB-RESOLVER-INIT", str(e))

    try:
        topology = SheetTopology.from_design(design)
    except TopologyError as e:
        return _fail("TOPOLOGY-ERROR", str(e))

    resolved = expand_design(design)
    main_sheet = design.sheets["main"]
    assign_schematic_positions(resolved, sheet_paper=main_sheet.paper)

    net_order = _collect_net_order(design, resolved, topology)

    try:
        _preload_libraries(resolved, libraries)
    except LibraryError as e:
        return _fail("LIB-SYMBOL-NOT-FOUND", str(e))

    try:
        pcb_path = output_dir / f"{design.project.name}.kicad_pcb"
        write_pcb(design, resolved, net_order, pcb_path,
                  libraries=libraries, topology=topology)
        sch_paths: list[Path] = []
        for sheet_id, sheet in design.sheets.items():
            sch_path = write_schematic(
                design, resolved,
                sheet_id=sheet_id,
                sheet_paper=sheet.paper,
                project_name=design.project.name,
                output_dir=output_dir,
                libraries=libraries,
                topology=topology,
            )
            sch_paths.append(sch_path)
    except LibraryError as e:
        return _fail("LIB-SYMBOL-NOT-FOUND", str(e))

    return BuildResult(
        success=True,
        generated_files=[pcb_path, *sch_paths],
    )


def validate(
    yaml_source: YamlSource,
    kicad_share: Optional[Path] = None,
) -> BuildResult:
    """Run loader + library resolution without writing any files."""
    from kicad_yaml.loader import load_design, LoadError
    from kicad_yaml.libraries import LibraryResolver, LibraryError
    from kicad_yaml.layout import expand_design
    from kicad_yaml.topology import SheetTopology, TopologyError

    try:
        design = load_design(yaml_source)
    except LoadError as e:
        return _fail("LOAD-ERROR", str(e),
                     source=_source_for(yaml_source))

    try:
        libraries = LibraryResolver(kicad_share=kicad_share)
    except LibraryError as e:
        return _fail("LIB-RESOLVER-INIT", str(e))

    try:
        SheetTopology.from_design(design)
    except TopologyError as e:
        return _fail("TOPOLOGY-ERROR", str(e))

    resolved = expand_design(design)
    try:
        _preload_libraries(resolved, libraries)
    except LibraryError as e:
        return _fail("LIB-SYMBOL-NOT-FOUND", str(e))

    return BuildResult(success=True)


def _fail(code: str, message: str,
          source: Optional[SourceLocation] = None) -> BuildResult:
    return BuildResult(
        success=False,
        errors=[Message(severity="error", code=code,
                        message=message, source=source)],
    )


def _source_for(yaml_source: YamlSource) -> Optional[SourceLocation]:
    if isinstance(yaml_source, Path):
        return SourceLocation(file=yaml_source, line=None)
    return None


def _collect_net_order(design, resolved, topology) -> List[str]:
    """Build the canonical list of fully-qualified net names used on the board.

    Globals come first (unqualified).  Then every raw net name referenced
    by any ResolvedComponent's pin_nets is passed through
    ``qualify_net_name`` and added in first-seen order.  Qualification
    dedupes nets that resolve to the same electrical node across sheets.
    """
    from kicad_yaml.pcb import qualify_net_name

    seen: list[str] = []
    seen_set: set = set()
    for n in design.global_nets:
        if n not in seen_set:
            seen.append(n)
            seen_set.add(n)
    for rc in resolved:
        for raw in rc.pin_nets.values():
            qualified = qualify_net_name(
                raw,
                sheet_id=rc.sheet_id,
                design=design,
                topology=topology,
            )
            if qualified not in seen_set:
                seen.append(qualified)
                seen_set.add(qualified)
    return seen


def _preload_libraries(resolved, libraries) -> None:
    for rc in resolved:
        libraries.symbol(rc.symbol_lib_name)
        libraries.footprint(rc.footprint_lib_name)
