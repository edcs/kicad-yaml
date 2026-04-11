"""Hierarchical schematic writer tests."""

from pathlib import Path
import tempfile

from kicad_yaml import kicad_net_patch  # noqa: F401
from kicad_yaml.layout import ResolvedComponent
from kicad_yaml.libraries import LibraryResolver
from kicad_yaml.schematic import write_schematic
from kicad_yaml.schema import (
    Board, Design, Layer, Project, SchematicConfig, Sheet, Subsheet,
)
from kicad_yaml.topology import SheetTopology
from kiutils.schematic import Schematic

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_SHARE = FIXTURES / "fake_kicad_share"


def _design() -> Design:
    return Design(
        project=Project(name="t"),
        board=Board(size=(80, 50)),
        global_nets=["VCC", "GND"],
        templates={},
        sheets={
            "main": Sheet(
                paper="A3",
                subsheets=[
                    Subsheet(
                        sheet_id="child",
                        label="Child",
                        schematic=SchematicConfig(position=(150, 100)),
                        size=(40, 30),
                        pin_map={"D_MAIN": "CHAIN_IN"},
                    ),
                ],
            ),
            "child": Sheet(paper="A4"),
        },
    )


def _rc(ref, pin_nets, sheet_id="child", sch_pos=(50.0, 50.0)):
    return ResolvedComponent(
        ref=ref,
        sheet_id=sheet_id,
        symbol_lib_name="Fake:FakeC",
        footprint_lib_name="Fake:FakeSMD",
        value="100n",
        pcb_position=(0.0, 0.0),
        pcb_layer=Layer.FRONT,
        pcb_rotation=0.0,
        pin_nets=pin_nets,
        no_connect_pins=[],
        sch_position=sch_pos,
    )


def test_child_sheet_emits_hierarchical_label_for_exposed_net():
    design = _design()
    topo = SheetTopology.from_design(design)
    resolved = [_rc("C1", {"1": "VCC", "2": "CHAIN_IN"})]

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        write_schematic(
            design, resolved,
            sheet_id="child",
            sheet_paper="A4",
            project_name="t",
            output_dir=out_dir,
            libraries=LibraryResolver(kicad_share=FAKE_SHARE),
            topology=topo,
        )
        sch = Schematic.from_file(str(out_dir / "child.kicad_sch"))

    # CHAIN_IN is exposed, VCC is global, GND isn't used.
    hier_names = {l.text for l in (sch.hierarchicalLabels or [])}
    assert hier_names == {"CHAIN_IN"}
    # The LocalLabel for CHAIN_IN should NOT be emitted because it's a
    # hierarchical boundary net — it only gets a hierarchical label.
    local_names = {l.text for l in sch.labels}
    assert "CHAIN_IN" not in local_names


def test_child_sheet_without_exposed_nets_has_no_hier_labels():
    design = Design(
        project=Project(name="t"),
        board=Board(size=(50, 30)),
        global_nets=["VCC", "GND"],
        templates={},
        sheets={
            "main": Sheet(
                paper="A4",
                subsheets=[
                    Subsheet(
                        sheet_id="child",
                        label="Child",
                        schematic=SchematicConfig(position=(10, 10)),
                        size=(20, 20),
                        pin_map={},
                    ),
                ],
            ),
            "child": Sheet(paper="A4"),
        },
    )
    topo = SheetTopology.from_design(design)
    resolved = [_rc("C1", {"1": "VCC", "2": "GND"})]

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        write_schematic(
            design, resolved,
            sheet_id="child",
            sheet_paper="A4",
            project_name="t",
            output_dir=out_dir,
            libraries=LibraryResolver(kicad_share=FAKE_SHARE),
            topology=topo,
        )
        sch = Schematic.from_file(str(out_dir / "child.kicad_sch"))
    assert not (sch.hierarchicalLabels or [])


def test_main_sheet_without_parent_has_no_hier_labels():
    """Main sheet isn't a child, so no hierarchical labels ever."""
    design = _design()
    topo = SheetTopology.from_design(design)
    resolved = [_rc("R1", {"1": "D_MAIN", "2": "GND"}, sheet_id="main")]

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        write_schematic(
            design, resolved,
            sheet_id="main",
            sheet_paper="A3",
            project_name="t",
            output_dir=out_dir,
            libraries=LibraryResolver(kicad_share=FAKE_SHARE),
            topology=topo,
        )
        sch = Schematic.from_file(str(out_dir / "main.kicad_sch"))
    assert not (sch.hierarchicalLabels or [])


def test_parent_sheet_emits_hierarchical_sheet_symbol():
    design = _design()
    topo = SheetTopology.from_design(design)
    # A component on main using D_MAIN (the parent-side name of CHAIN_IN).
    resolved = [_rc("R1", {"1": "D_MAIN", "2": "GND"}, sheet_id="main",
                    sch_pos=(80.0, 80.0))]

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        write_schematic(
            design, resolved,
            sheet_id="main",
            sheet_paper="A3",
            project_name="t",
            output_dir=out_dir,
            libraries=LibraryResolver(kicad_share=FAKE_SHARE),
            topology=topo,
        )
        sch = Schematic.from_file(str(out_dir / "main.kicad_sch"))

    # One HierarchicalSheet symbol for the 'child' subsheet.
    assert len(sch.sheets or []) == 1
    hs = sch.sheets[0]
    # kiutils stores sheetName/fileName as Property objects; adapt assertions.
    assert hs.sheetName == "Child" or hs.sheetName.value == "Child" or any(
        p.key == "Sheetname" and p.value == "Child" for p in (hs.properties or [])
    )
    assert hs.fileName == "child.kicad_sch" or hs.fileName.value == "child.kicad_sch" or any(
        p.key == "Sheetfile" and p.value == "child.kicad_sch" for p in (hs.properties or [])
    )
    # Exactly one HierarchicalPin for the CHAIN_IN pin_map entry.
    assert len(hs.pins) == 1
    assert hs.pins[0].name == "CHAIN_IN"
    # And one LocalLabel on the parent sheet named "D_MAIN" placed
    # at the pin's absolute position.
    labels = {l.text for l in sch.labels}
    assert "D_MAIN" in labels


def test_sheet_instances_populated_on_every_sheet():
    from kiutils.items.schitems import HierarchicalSheetInstance
    design = _design()
    topo = SheetTopology.from_design(design)
    resolved = [
        _rc("R1", {"1": "D_MAIN", "2": "GND"}, sheet_id="main",
            sch_pos=(80.0, 80.0)),
        _rc("C1", {"1": "VCC", "2": "CHAIN_IN"}, sheet_id="child"),
    ]

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        for sheet_id, paper in (("main", "A3"), ("child", "A4")):
            write_schematic(
                design, resolved,
                sheet_id=sheet_id,
                sheet_paper=paper,
                project_name="t",
                output_dir=out_dir,
                libraries=LibraryResolver(kicad_share=FAKE_SHARE),
                topology=topo,
            )
        sch_main = Schematic.from_file(str(out_dir / "main.kicad_sch"))
        sch_child = Schematic.from_file(str(out_dir / "child.kicad_sch"))

    main_paths = {si.instancePath for si in (sch_main.sheetInstances or [])}
    child_paths = {si.instancePath for si in (sch_child.sheetInstances or [])}

    main_uuid = topo.uuid_for("main")
    child_uuid = topo.uuid_for("child")
    expected = {f"/{main_uuid}", f"/{main_uuid}/{child_uuid}"}
    assert main_paths == expected
    assert child_paths == expected


def test_symbol_project_path_uses_hierarchical_path():
    design = _design()
    topo = SheetTopology.from_design(design)
    resolved = [_rc("C1", {"1": "VCC", "2": "CHAIN_IN"}, sheet_id="child")]

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        write_schematic(
            design, resolved,
            sheet_id="child",
            sheet_paper="A4",
            project_name="t",
            output_dir=out_dir,
            libraries=LibraryResolver(kicad_share=FAKE_SHARE),
            topology=topo,
        )
        sch = Schematic.from_file(str(out_dir / "child.kicad_sch"))
    sym = sch.schematicSymbols[0]
    inst = sym.instances[0]
    path = inst.paths[0].sheetInstancePath
    expected = f"/{topo.uuid_for('main')}/{topo.uuid_for('child')}"
    assert path == expected
