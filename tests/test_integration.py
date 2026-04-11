"""End-to-end smoke test: real YAML fixture → real KiCad files."""

from pathlib import Path

from kicad_yaml import build
from kiutils.board import Board as KiBoard
from kiutils.schematic import Schematic

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_SHARE = FIXTURES / "fake_kicad_share"


def test_integration_flat_end_to_end(tmp_path):
    yaml_path = FIXTURES / "integration_flat.yaml"
    result = build(yaml_path, output_dir=tmp_path, kicad_share=FAKE_SHARE)
    assert result.success, [e.message for e in result.errors]

    pcb_path = tmp_path / "integration_flat.kicad_pcb"
    sch_path = tmp_path / "main.kicad_sch"
    assert pcb_path.exists()
    assert sch_path.exists()

    board = KiBoard.from_file(str(pcb_path))
    # 1 resistor + 2 LEDs + 2 caps
    refs = sorted(fp.properties["Reference"] for fp in board.footprints)
    assert refs == ["C1", "C2", "LED1", "LED2", "R1"]
    # R1 is on the back with rotation 270 (90 CCW user → 270 stored)
    r1 = next(fp for fp in board.footprints if fp.properties["Reference"] == "R1")
    assert r1.layer == "B.Cu"
    assert r1.position.angle == 270.0
    # Net table contains VCC, GND, and root-local nets (slash-prefixed)
    net_names = {n.name for n in board.nets if n.name}
    assert {"VCC", "GND", "/MCU_DATA", "/D0", "/D1", "/D2"} <= net_names

    sch = Schematic.from_file(str(sch_path))
    assert len(sch.schematicSymbols) == 5
    global_names = {l.text for l in sch.globalLabels}
    assert "VCC" in global_names
    assert "GND" in global_names
    local_names = {l.text for l in sch.labels}
    # Local nets: MCU_DATA, D0, D1, D2
    assert {"MCU_DATA", "D0", "D1", "D2"} == local_names
