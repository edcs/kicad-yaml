"""End-to-end test for the neopixel_grid example.

Requires a real KiCad 10 installation.  Skipped otherwise.
"""

from pathlib import Path
import pytest

from kicad_yaml import build
from kicad_yaml.libraries import LibraryResolver, LibraryError

EXAMPLES = Path(__file__).parent.parent / "examples"
EXAMPLE_YAML = EXAMPLES / "neopixel_grid" / "design.yaml"


def _kicad_available() -> bool:
    try:
        LibraryResolver()
        return True
    except LibraryError:
        return False


@pytest.mark.skipif(not _kicad_available(), reason="KiCad not installed")
def test_neopixel_grid_end_to_end(tmp_path):
    result = build(EXAMPLE_YAML, output_dir=tmp_path)
    assert result.success, [e.message for e in result.errors]

    pcb_path = tmp_path / "neopixel_grid.kicad_pcb"
    sch_path = tmp_path / "main.kicad_sch"
    assert pcb_path.exists()
    assert sch_path.exists()

    from kicad_yaml import kicad_net_patch  # noqa: F401
    from kiutils.board import Board as KiBoard
    from kiutils.schematic import Schematic

    board = KiBoard.from_file(str(pcb_path))
    refs = sorted(fp.properties["Reference"] for fp in board.footprints)
    # 64 LEDs + 64 caps + 1 header = 129
    assert len(refs) == 129

    led_refs = [r for r in refs if r.startswith("LED")]
    assert len(led_refs) == 64

    cap_refs = [r for r in refs if r.startswith("C")]
    assert len(cap_refs) == 64

    assert "J1" in refs

    net_names = {n.name for n in board.nets if n.name}
    assert "VCC" in net_names
    assert "GND" in net_names

    # J1 pin 2 connects to D1 — check J1's pad nets
    j1 = next(fp for fp in board.footprints if fp.properties["Reference"] == "J1")
    j1_nets = {p.number: p.net.name for p in j1.pads if p.net}
    assert j1_nets["1"] == "VCC"
    assert j1_nets["3"] == "GND"
    # D1 is a flat root-local net: /D1
    assert j1_nets["2"] == "/D1"

    # LED1 DIN = /D1, DOUT = /D2
    led1 = next(fp for fp in board.footprints if fp.properties["Reference"] == "LED1")
    led1_nets = {p.number: p.net.name for p in led1.pads if p.net}
    assert led1_nets["4"] == "/D1"
    assert led1_nets["2"] == "/D2"

    sch = Schematic.from_file(str(sch_path))
    assert len(sch.schematicSymbols) == 129
