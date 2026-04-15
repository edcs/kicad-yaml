"""PCB writer: footprint placement and back-side flip."""

from pathlib import Path
import tempfile

from kicad_yaml import kicad_net_patch  # noqa: F401
from kicad_yaml.layout import ResolvedComponent
from kicad_yaml.libraries import LibraryResolver
from kicad_yaml.pcb import write_pcb
from kicad_yaml.schema import Board, Design, Layer, Project, Sheet
from kiutils.board import Board as KiBoard

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


def test_front_footprint_placed():
    resolved = [
        ResolvedComponent(
            ref="C1",
            sheet_id="main",
            symbol_lib_name="Fake:FakeC",
            footprint_lib_name="Fake:FakeSMD",
            value="100n",
            pcb_position=(10.0, 15.0),
            pcb_layer=Layer.FRONT,
            pcb_rotation=0.0,
            pin_nets={"1": "VCC", "2": "GND"},
            no_connect_pins=[],
            sch_position=(100.0, 100.0),
        ),
    ]
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "t.kicad_pcb"
        write_pcb(
            _design(), resolved, net_order=["VCC", "GND"], output=out,
            libraries=LibraryResolver(kicad_share=FAKE_SHARE),
        )
        board = KiBoard.from_file(str(out))
    assert len(board.footprints) == 1
    fp = board.footprints[0]
    assert fp.properties["Reference"] == "C1"
    assert fp.properties["Value"] == "100n"
    assert fp.layer == "F.Cu"
    assert fp.position.X == 10.0 and fp.position.Y == 15.0
    pad_nets = {p.number: p.net.name for p in fp.pads if p.net}
    assert pad_nets == {"1": "VCC", "2": "GND"}


def test_back_footprint_layer_flipped_and_rotation_inverted():
    resolved = [
        ResolvedComponent(
            ref="R1",
            sheet_id="main",
            symbol_lib_name="Fake:FakeR",
            footprint_lib_name="Fake:FakeSMD",
            value="330",
            pcb_position=(20.0, 25.0),
            pcb_layer=Layer.BACK,
            pcb_rotation=90.0,      # user wants 90 CCW on the back
            pin_nets={"1": "VCC", "2": "GND"},
            no_connect_pins=[],
            sch_position=(100.0, 100.0),
        ),
    ]
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "t.kicad_pcb"
        write_pcb(
            _design(), resolved, net_order=["VCC", "GND"], output=out,
            libraries=LibraryResolver(kicad_share=FAKE_SHARE),
        )
        board = KiBoard.from_file(str(out))
    fp = board.footprints[0]
    assert fp.layer == "B.Cu"
    # kicad-yaml bakes footprint rotation into the pad/graphic positions
    # themselves (working around a KiCad rendering bug with rotated SMD
    # pads on the back layer), so the footprint's stored angle is 0 and
    # each pad carries the rotation on its own `at`.
    assert fp.position.angle == 0.0
    for pad in fp.pads:
        if pad.position is None:
            continue
        # 90 CCW user → stored 270 on back → baked as 270 on each pad
        assert pad.position.angle == 270.0
    # All pad layers are B.*
    for pad in fp.pads:
        assert all(l.startswith("B.") for l in pad.layers if not l.startswith("*"))
    # FpText effects.justify.mirror should be True
    from kiutils.items.fpitems import FpText
    fp_texts = [g for g in fp.graphicItems if isinstance(g, FpText)]
    assert any(t.effects and t.effects.justify and t.effects.justify.mirror
               for t in fp_texts)
