"""Flat schematic writer.  Plan 2 will extend this to hierarchical sheets."""

from __future__ import annotations

import copy
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Apply the KiCad 10 net-format patch on import.
from kicad_yaml import kicad_net_patch  # noqa: F401

from kiutils.items.common import Effects, Font, PageSettings, Position, Property
from kiutils.items.schitems import (
    GlobalLabel,
    HierarchicalLabel,
    HierarchicalPin,
    HierarchicalSheet,
    HierarchicalSheetInstance,
    HierarchicalSheetProjectInstance,
    HierarchicalSheetProjectPath,
    LocalLabel,
    NoConnect,
    SchematicSymbol,
    SymbolProjectInstance,
    SymbolProjectPath,
)
from kiutils.schematic import Schematic
from kiutils.symbol import Symbol

from kicad_yaml.layout import ResolvedComponent
from kicad_yaml.libraries import LibraryResolver
from kicad_yaml.schema import Design, format_version_for
from kicad_yaml.topology import SheetTopology


def write_schematic(
    design: Design,
    resolved: List[ResolvedComponent],
    sheet_id: str,
    sheet_paper: str,
    project_name: str,
    output_dir: Path,
    *,
    libraries: Optional[LibraryResolver] = None,
    topology: Optional[SheetTopology] = None,
) -> Path:
    """Write one .kicad_sch file for a single sheet."""
    if libraries is None:
        libraries = LibraryResolver()

    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / f"{sheet_id}.kicad_sch"

    sch = Schematic()
    # Older stamps trigger KiCad's "older version, will be upgraded" banner.
    # Default comes from schema.DEFAULT_FORMAT_VERSION; override via
    # design.project.format_version.
    sch.version = format_version_for(design.project)
    sch.generator = "kicad-yaml"
    if topology is not None:
        sch.uuid = topology.uuid_for(sheet_id)
    else:
        sch.uuid = str(uuid.uuid4())
    instance_path = (
        topology.sheet_instance_path(sheet_id)
        if topology is not None
        else f"/{sch.uuid}"
    )
    sch.paper = PageSettings(paperSize=sheet_paper)
    sch.libSymbols = []
    sch.schematicSymbols = []
    sch.labels = []
    sch.globalLabels = []
    sch.hierarchicalLabels = []
    sch.noConnects = []

    sheet_resolved = [r for r in resolved if r.sheet_id == sheet_id]
    global_net_set = set(design.global_nets)

    exposed_child_nets: set[str] = set()
    if topology is not None and sheet_id != topology.root:
        exposed_child_nets = topology.exposed_nets_for_sheet(sheet_id)

    lib_symbols_by_id: Dict[str, Symbol] = {}
    for rc in sheet_resolved:
        lib_symbols_by_id.setdefault(
            rc.symbol_lib_name,
            _load_lib_symbol(libraries, rc.symbol_lib_name),
        )
    sch.libSymbols = list(lib_symbols_by_id.values())

    for rc in sheet_resolved:
        lib_sym = lib_symbols_by_id[rc.symbol_lib_name]
        lib_nick, entry_name = rc.symbol_lib_name.split(":", 1)
        pin_offsets = _pin_offsets_screen(lib_sym)

        sch.schematicSymbols.append(
            _make_symbol_instance(
                lib_nick=lib_nick,
                entry_name=entry_name,
                rc=rc,
                pin_numbers=list(pin_offsets.keys()),
                sheet_instance_path=instance_path,
                project_name=project_name,
            )
        )

        cx, cy = rc.sch_position
        no_connect_pins_set = set(rc.no_connect_pins)

        for pin, (dx, dy) in pin_offsets.items():
            label_pos = Position(X=cx + dx, Y=cy + dy, angle=0)
            if pin in no_connect_pins_set:
                sch.noConnects.append(
                    NoConnect(
                        position=label_pos,
                        uuid=str(uuid.uuid4()),
                    )
                )
                continue
            if pin not in rc.pin_nets:
                continue
            net_name = rc.pin_nets[pin]
            effects = Effects(font=Font(height=1.27, width=1.27))
            if net_name in exposed_child_nets:
                # Hierarchical boundary net — emit a HierarchicalLabel at
                # this pin so the child sheet's graph reaches the sheet
                # symbol.  No LocalLabel; KiCad joins labels by text.
                sch.hierarchicalLabels.append(
                    HierarchicalLabel(
                        text=net_name,
                        shape="passive",
                        position=label_pos,
                        effects=Effects(font=Font(height=1.27, width=1.27)),
                        uuid=str(uuid.uuid4()),
                        fieldsAutoplaced=True,
                    )
                )
            elif net_name in global_net_set:
                sch.globalLabels.append(
                    GlobalLabel(
                        text=net_name,
                        position=label_pos,
                        effects=effects,
                        uuid=str(uuid.uuid4()),
                    )
                )
            else:
                sch.labels.append(
                    LocalLabel(
                        text=net_name,
                        position=label_pos,
                        effects=effects,
                        uuid=str(uuid.uuid4()),
                    )
                )

    # Emit HierarchicalSheet symbols for any subsheets declared on this sheet.
    sch.sheets = []
    if topology is not None:
        current_sheet = design.sheets[sheet_id]
        for sub in current_sheet.subsheets:
            child_id = sub.sheet_id
            child_uuid = topology.uuid_for(child_id)
            hs = _make_hierarchical_sheet(
                sub=sub,
                child_file=f"{child_id}.kicad_sch",
                child_uuid=child_uuid,
                project_name=project_name,
                topology=topology,
                parent_sheet_id=sheet_id,
            )
            sch.sheets.append(hs)
            # LocalLabel on the parent side for each pin, matching the
            # parent-side net name so the pin joins the parent's graph.
            for pin_local_label in _pin_join_labels_for_subsheet(hs, sub):
                sch.labels.append(pin_local_label)

    # Populate sheet_instances with every sheet in the design, using the
    # topology's UUID paths.  Every .kicad_sch in a hierarchical project
    # carries the same sheet_instances table.
    sch.sheetInstances = []
    if topology is not None:
        for sid in topology.all_sheets():
            sch.sheetInstances.append(
                HierarchicalSheetInstance(
                    instancePath=topology.sheet_instance_path(sid),
                    page="1" if sid == topology.root else "2",
                )
            )
    else:
        # Flat case: single "/uuid" entry so KiCad recognizes the sheet.
        sch.sheetInstances = [
            HierarchicalSheetInstance(instancePath=f"/{sch.uuid}", page="1")
        ]

    sch.to_file(str(out))
    return out


def _load_lib_symbol(libraries: LibraryResolver, lib_name: str) -> Symbol:
    lib_nick, entry = lib_name.split(":", 1)
    sym = copy.deepcopy(libraries.symbol(lib_name))
    sym.libraryNickname = lib_nick
    sym.entryName = entry
    return sym


def _pin_offsets_screen(sym: Symbol) -> Dict[str, Tuple[float, float]]:
    """Return {pin_number: (dx, dy)} in schematic screen coordinates.

    Library symbol pin coords are Y-up; screen Y is Y-down, so we negate
    the Y component.
    """
    out: Dict[str, Tuple[float, float]] = {}
    for unit in sym.units:
        for pin in unit.pins:
            out[str(pin.number)] = (pin.position.X, -pin.position.Y)
    return out


def _make_symbol_instance(
    *,
    lib_nick: str,
    entry_name: str,
    rc: ResolvedComponent,
    pin_numbers: List[str],
    sheet_instance_path: str,     # full path, not just the current sheet's UUID
    project_name: str,
) -> SchematicSymbol:
    x, y = rc.sch_position
    font = Font(height=1.27, width=1.27)
    props = [
        Property(key="Reference", value=rc.ref, id=0,
                 position=Position(X=x, Y=y - 11.43, angle=0),
                 effects=Effects(font=font)),
        Property(key="Value", value=rc.value, id=1,
                 position=Position(X=x, Y=y + 11.43, angle=0),
                 effects=Effects(font=font)),
        Property(key="Footprint", value=rc.footprint_lib_name, id=2,
                 position=Position(X=x, Y=y, angle=0),
                 effects=Effects(font=font, hide=True)),
        Property(key="Datasheet", value="", id=3,
                 position=Position(X=x, Y=y, angle=0),
                 effects=Effects(font=font, hide=True)),
    ]
    return SchematicSymbol(
        libraryNickname=lib_nick,
        entryName=entry_name,
        libName=None,
        position=Position(X=x, Y=y, angle=0),
        unit=1,
        inBom=True,
        onBoard=True,
        dnp=False,
        fieldsAutoplaced=True,
        uuid=str(uuid.uuid4()),
        properties=props,
        pins={p: str(uuid.uuid4()) for p in pin_numbers},
        mirror=None,
        instances=[
            SymbolProjectInstance(
                name=project_name,
                paths=[SymbolProjectPath(
                    sheetInstancePath=sheet_instance_path,
                    reference=rc.ref,
                    unit=1,
                )],
            )
        ],
    )


def _make_hierarchical_sheet(
    *,
    sub,                          # Subsheet
    child_file: str,
    child_uuid: str,
    project_name: str,
    topology: SheetTopology,
    parent_sheet_id: str,
) -> HierarchicalSheet:
    """Build a HierarchicalSheet box with edge pins for one subsheet."""
    x, y = sub.schematic.position
    w, h = sub.size
    font = Font(height=1.27, width=1.27)

    pin_names = list(sub.pin_map.values())
    pins: list[HierarchicalPin] = []
    # Distribute pins along the LEFT edge (x = box.x), evenly in Y.
    if pin_names:
        step = h / (len(pin_names) + 1)
        for i, name in enumerate(pin_names, start=1):
            pins.append(
                HierarchicalPin(
                    name=name,
                    connectionType="passive",
                    position=Position(X=x, Y=y + i * step, angle=180),
                    effects=Effects(font=font),
                    uuid=str(uuid.uuid4()),
                )
            )

    parent_instance_path = topology.sheet_instance_path(parent_sheet_id)
    full_child_path = f"{parent_instance_path}/{child_uuid}"

    hs = HierarchicalSheet(
        position=Position(X=x, Y=y, angle=0),
        width=w,
        height=h,
        fieldsAutoplaced=True,
        uuid=child_uuid,
        pins=pins,
        instances=[
            HierarchicalSheetProjectInstance(
                name=project_name,
                paths=[HierarchicalSheetProjectPath(
                    sheetInstancePath=full_child_path,
                    page="2",  # v1: all child sheets get page "2".
                )],
            ),
        ],
    )
    # kiutils stores sheetName and fileName as Property members on the object.
    hs.sheetName.value = sub.label
    hs.fileName.value = child_file
    # Position the name/file labels relative to the box.
    hs.sheetName.position = Position(X=x, Y=y - 2.54, angle=0)
    hs.sheetName.effects = Effects(font=font)
    hs.fileName.position = Position(X=x, Y=y + h + 2.54, angle=0)
    hs.fileName.effects = Effects(font=font)
    return hs


def _pin_join_labels_for_subsheet(
    hs: HierarchicalSheet,
    sub,                          # Subsheet
) -> list[LocalLabel]:
    """Return a LocalLabel per pin placed at the pin's absolute position,
    using the parent-side net name from the pin_map.

    KiCad joins the HierarchicalPin (named with the child-side name) to
    whatever label sits at the same XY coord on the parent sheet.  Giving
    it a LocalLabel with the parent-side name links the pin into the
    parent's electrical graph.
    """
    # Invert pin_map for lookup: child_name -> parent_name
    parent_for_child = {child: parent for parent, child in sub.pin_map.items()}
    labels: list[LocalLabel] = []
    for pin in hs.pins:
        parent_name = parent_for_child.get(pin.name)
        if parent_name is None:
            continue
        labels.append(
            LocalLabel(
                text=parent_name,
                position=Position(
                    X=pin.position.X,
                    Y=pin.position.Y,
                    angle=0,
                ),
                effects=Effects(font=Font(height=1.27, width=1.27)),
                uuid=str(uuid.uuid4()),
            )
        )
    return labels
