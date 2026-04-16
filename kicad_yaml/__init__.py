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
    reload_kicad: bool = False,
) -> BuildResult:
    """Read a design YAML and write KiCad files."""
    from kicad_yaml.loader import load_design, LoadError
    from kicad_yaml.libraries import LibraryResolver, LibraryError
    from kicad_yaml.layout import (
        expand_design, expand_vias, expand_tracks, assign_schematic_positions,
    )
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

    # Check for KiCad lock files before writing. If KiCad has the project
    # open, it will overwrite our output when it saves. Warn so the user
    # knows to reload in KiCad rather than save.
    warnings = _check_lock_files(output_dir, design.project.name)

    vias = expand_vias(design)
    tracks = expand_tracks(design)

    try:
        pcb_path = output_dir / f"{design.project.name}.kicad_pcb"
        skipped_vias = write_pcb(
            design, resolved, net_order, pcb_path,
            libraries=libraries, topology=topology,
            vias=vias,
            tracks=tracks,
        )
        if skipped_vias:
            cell_list = ", ".join(
                f"{v.grid_id}[r{v.cell_row},c{v.cell_col}]" for v in skipped_vias
            )
            warnings.append(Message(
                severity="warning",
                code="VIA-SKIPPED-BACKSIDE-CONFLICT",
                message=(
                    f"skipped {len(skipped_vias)} via(s) that would collide "
                    f"with back-side pads — route these cells manually: "
                    f"{cell_list}"
                ),
            ))
        sch_paths: list[Path] = []
        # (uuid, filename) pairs in iteration order, root first.
        sheet_entries: list[tuple[str, str]] = []
        root_entry: Optional[tuple[str, str]] = None
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
            sheet_uuid = topology.uuid_for(sheet_id) if topology else sheet_id
            entry = (sheet_uuid, sch_path.name)
            sheet_entries.append(entry)
            if topology is None or sheet_id == topology.root:
                root_entry = entry
    except LibraryError as e:
        return _fail("LIB-SYMBOL-NOT-FOUND", str(e))

    # Keep the KiCad project file's sheet registry in sync so child
    # schematics show up in the Project Manager tree.
    if root_entry is not None:
        from kicad_yaml.project_file import sync_sheet_registry
        pro_path = output_dir / f"{design.project.name}.kicad_pro"
        ordered = [root_entry] + [e for e in sheet_entries if e != root_entry]
        sync_sheet_registry(
            pro_path,
            project_name=design.project.name,
            root_sheet=root_entry,
            all_sheets=ordered,
        )

    if reload_kicad:
        from kicad_yaml.kicad_refresh import refresh_open_pcb
        status = refresh_open_pcb(pcb_path)
        if status == "error:accessibility-denied":
            warnings.append(Message(
                severity="warning",
                code="KICAD-REFRESH-ACCESSIBILITY",
                message=(
                    "--reload needs Accessibility permission on macOS. "
                    "Open System Settings → Privacy & Security → Accessibility "
                    "and enable the terminal app running this command."
                ),
            ))
        elif status.startswith("error:"):
            warnings.append(Message(
                severity="warning",
                code="KICAD-REFRESH-FAILED",
                message=f"could not refresh open KiCad PCB: {status[6:]}",
            ))

    return BuildResult(
        success=True,
        generated_files=[pcb_path, *sch_paths],
        warnings=warnings,
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


def sync(
    yaml_source: Path,
) -> BuildResult:
    """Read positions from .kicad_pcb and update the design YAML in-place."""
    from kicad_yaml.sync import sync_positions

    yaml_path = Path(yaml_source)
    if not yaml_path.exists():
        return _fail("SYNC-YAML-NOT-FOUND", f"YAML file not found: {yaml_path}")

    from ruamel.yaml import YAML as RuamelYAML
    rt = RuamelYAML(typ="safe")
    data = rt.load(yaml_path)
    project_name = data["project"]["name"]
    pcb_path = yaml_path.parent / f"{project_name}.kicad_pcb"

    if not pcb_path.exists():
        return _fail(
            "SYNC-PCB-NOT-FOUND",
            f"no .kicad_pcb found at {pcb_path}; run `build` first",
        )

    try:
        outcome = sync_positions(yaml_path, pcb_path)
    except Exception as e:
        return _fail("SYNC-ERROR", str(e))

    info: list[Message] = []
    for c in outcome.changes:
        parts = []
        if c.old_position != c.new_position:
            parts.append(
                f"position [{c.old_position[0]}, {c.old_position[1]}]"
                f" -> [{c.new_position[0]}, {c.new_position[1]}]"
            )
        if c.old_rotation != c.new_rotation:
            parts.append(f"rotation {c.old_rotation} -> {c.new_rotation}")
        info.append(Message(
            severity="warning", code="SYNC-CHANGED",
            message=f"{c.ref}: {', '.join(parts)}",
        ))

    for ref in outcome.missing_refs:
        info.append(Message(
            severity="warning", code="SYNC-REF-NOT-IN-PCB",
            message=f"{ref} not found in PCB; skipped (run `build` to regenerate)",
        ))

    return BuildResult(
        success=True,
        generated_files=[yaml_path] if outcome.changes else [],
        warnings=info,
    )


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


def _check_lock_files(output_dir: Path, project_name: str) -> List[Message]:
    """Check for KiCad lock files in the output directory.

    KiCad creates ``~filename.lck`` when a file is open. If we write over
    files that KiCad has open, KiCad's next save will overwrite our output
    with its stale in-memory copy. We warn so the user knows to reload in
    KiCad (not save) after the build finishes.
    """
    warnings: List[Message] = []
    lock_patterns = [
        f"~{project_name}.kicad_pcb.lck",
        "~main.kicad_sch.lck",
        "~*.kicad_sch.lck",
        "~*.kicad_pcb.lck",
    ]
    found = set()
    for pattern in lock_patterns:
        for lck in output_dir.glob(pattern):
            found.add(lck.name)
    if found:
        names = ", ".join(sorted(found))
        warnings.append(Message(
            severity="warning",
            code="KICAD-LOCK-FILES",
            message=(
                f"KiCad appears to have files open ({names}). "
                f"Files were written successfully, but switch to KiCad and "
                f"reload when prompted. Do not save in KiCad before reloading, "
                f"or it will overwrite the generated output."
            ),
        ))
    return warnings


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
