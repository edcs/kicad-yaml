"""Flat schematic writer tests."""

from pathlib import Path
import tempfile

from kicad_yaml import kicad_net_patch  # noqa: F401
from kicad_yaml.layout import ResolvedComponent
from kicad_yaml.libraries import LibraryResolver
from kicad_yaml.schematic import write_schematic
from kicad_yaml.schema import Board, Design, Layer, Project, Sheet
from kiutils.schematic import Schematic

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_SHARE = FIXTURES / "fake_kicad_share"


def _design() -> Design:
    return Design(
        project=Project(name="t"),
        board=Board(size=(50.0, 30.0)),
        global_nets=["VCC", "GND"],
        templates={},
        sheets={"main": Sheet(paper="A4")},
    )


def _rc(ref, pin_nets, *, sch_pos=(50.0, 50.0), no_connect=None):
    return ResolvedComponent(
        ref=ref,
        sheet_id="main",
        symbol_lib_name="Fake:FakeC",
        footprint_lib_name="Fake:FakeSMD",
        value="100n",
        pcb_position=(0.0, 0.0),
        pcb_layer=Layer.FRONT,
        pcb_rotation=0.0,
        pin_nets=pin_nets,
        no_connect_pins=list(no_connect or []),
        sch_position=sch_pos,
    )


def test_flat_schematic_single_component():
    resolved = [_rc("C1", {"1": "VCC", "2": "GND"})]
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        write_schematic(
            _design(), resolved, sheet_id="main",
            sheet_paper="A4", project_name="t",
            output_dir=out_dir,
            libraries=LibraryResolver(kicad_share=FAKE_SHARE),
        )
        sch_path = out_dir / "t.kicad_sch"
        assert sch_path.exists()
        sch = Schematic.from_file(str(sch_path))

    assert len(sch.schematicSymbols) == 1
    sym = sch.schematicSymbols[0]
    assert sym.libraryNickname == "Fake"
    assert sym.entryName == "FakeC"
    globals_ = [l for l in sch.globalLabels]
    global_names = sorted({l.text for l in globals_})
    assert global_names == ["GND", "VCC"]
    assert len(sch.labels) == 0   # everything was global here
    assert len(sch.libSymbols) == 1
    assert sch.libSymbols[0].entryName == "FakeC"


def test_flat_schematic_local_net_label():
    resolved = [
        _rc("C1", {"1": "VCC", "2": "D0"}),   # D0 is not global
    ]
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        write_schematic(
            _design(), resolved, sheet_id="main",
            sheet_paper="A4", project_name="t",
            output_dir=out_dir,
            libraries=LibraryResolver(kicad_share=FAKE_SHARE),
        )
        sch = Schematic.from_file(str(out_dir / "t.kicad_sch"))

    assert {l.text for l in sch.labels} == {"D0"}
    assert {l.text for l in sch.globalLabels} == {"VCC"}


def test_flat_schematic_no_connect_markers():
    resolved = [
        _rc("C1", {"1": "VCC"}, no_connect=["2"]),
    ]
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        write_schematic(
            _design(), resolved, sheet_id="main",
            sheet_paper="A4", project_name="t",
            output_dir=out_dir,
            libraries=LibraryResolver(kicad_share=FAKE_SHARE),
        )
        sch = Schematic.from_file(str(out_dir / "t.kicad_sch"))

    assert len(sch.noConnects or []) == 1


def test_no_connect_pin_does_not_get_label():
    """A pin listed in both pin_nets and no_connect_pins gets only the NoConnect,
    not a net label.  Prevents KiCad DRC errors from overlapping markers."""
    resolved = [
        _rc("C1", {"1": "VCC", "2": "GND"}, no_connect=["1"]),
    ]
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        write_schematic(
            _design(), resolved, sheet_id="main",
            sheet_paper="A4", project_name="t",
            output_dir=out_dir,
            libraries=LibraryResolver(kicad_share=FAKE_SHARE),
        )
        sch = Schematic.from_file(str(out_dir / "t.kicad_sch"))
    # Pin 1 should have a NoConnect marker and NO VCC label at its position.
    assert len(sch.noConnects) == 1
    global_names = {l.text for l in sch.globalLabels}
    # GND from pin 2 stays; VCC from pin 1 should NOT appear
    assert "GND" in global_names
    assert "VCC" not in global_names
