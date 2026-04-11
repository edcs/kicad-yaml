"""PCB writer hierarchical net naming tests."""

from pathlib import Path
import tempfile

from kicad_yaml import kicad_net_patch  # noqa: F401
from kicad_yaml.layout import ResolvedComponent
from kicad_yaml.libraries import LibraryResolver
from kicad_yaml.pcb import qualify_net_name, write_pcb
from kicad_yaml.schema import (
    Board, Design, Layer, Project, SchematicConfig, Sheet, Subsheet,
)
from kicad_yaml.topology import SheetTopology
from kiutils.board import Board as KiBoard

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


def _rc(ref, sheet_id, pin_nets):
    return ResolvedComponent(
        ref=ref,
        sheet_id=sheet_id,
        symbol_lib_name="Fake:FakeC",
        footprint_lib_name="Fake:FakeSMD",
        value="100n",
        pcb_position=(10.0 if sheet_id == "main" else 30.0, 15.0),
        pcb_layer=Layer.FRONT,
        pcb_rotation=0.0,
        pin_nets=pin_nets,
        no_connect_pins=[],
        sch_position=(0.0, 0.0),
    )


def test_qualify_global_net_passes_through():
    design = _design()
    topo = SheetTopology.from_design(design)
    assert qualify_net_name("VCC", sheet_id="child", design=design, topology=topo) == "VCC"
    assert qualify_net_name("GND", sheet_id="main", design=design, topology=topo) == "GND"


def test_qualify_sheet_local_net_gets_slash_path():
    design = _design()
    topo = SheetTopology.from_design(design)
    # CHAIN_IN is exposed to main as D_MAIN — so on the child sheet, the
    # net is electrically the same as main's D_MAIN.  Child's CHAIN_IN
    # collapses to /D_MAIN.
    assert qualify_net_name("CHAIN_IN", sheet_id="child",
                            design=design, topology=topo) == "/D_MAIN"
    # D_MAIN on main is a root-sheet local: bare name with / prefix.
    assert qualify_net_name("D_MAIN", sheet_id="main",
                            design=design, topology=topo) == "/D_MAIN"


def test_qualify_unexposed_local_net_uses_sheet_name():
    """A net that stays inside a non-root sheet gets the /sheet_name/ prefix."""
    design = _design()
    topo = SheetTopology.from_design(design)
    # INTERNAL is not in pin_map, so it stays inside child.
    assert qualify_net_name("INTERNAL", sheet_id="child",
                            design=design, topology=topo) == "/child/INTERNAL"


def test_write_pcb_with_hierarchical_nets_uses_qualified_names():
    design = _design()
    topo = SheetTopology.from_design(design)
    resolved = [
        _rc("R1", "main", {"1": "D_MAIN", "2": "GND"}),
        _rc("C1", "child", {"1": "VCC", "2": "CHAIN_IN"}),
        _rc("C2", "child", {"1": "VCC", "2": "INTERNAL"}),
    ]
    net_order = ["VCC", "GND", "/D_MAIN", "/child/INTERNAL"]

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "t.kicad_pcb"
        write_pcb(
            design, resolved, net_order, out,
            libraries=LibraryResolver(kicad_share=FAKE_SHARE),
            topology=topo,
        )
        board = KiBoard.from_file(str(out))

    net_names = {n.name for n in board.nets if n.name}
    assert net_names == {"VCC", "GND", "/D_MAIN", "/child/INTERNAL"}

    pads_by_ref = {fp.properties["Reference"]: {p.number: p.net.name for p in fp.pads if p.net} for fp in board.footprints}
    assert pads_by_ref["R1"]["1"] == "/D_MAIN"
    assert pads_by_ref["R1"]["2"] == "GND"
    # The child's CHAIN_IN net resolves to the same electrical net as
    # main's D_MAIN, so its qualified name is /D_MAIN.
    assert pads_by_ref["C1"]["2"] == "/D_MAIN"
    assert pads_by_ref["C2"]["2"] == "/child/INTERNAL"
