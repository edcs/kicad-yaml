# tests/test_integration_hierarchical.py
"""Hierarchical end-to-end: real YAML → real KiCad files."""

from pathlib import Path

from kicad_yaml import build
from kiutils.board import Board as KiBoard
from kiutils.schematic import Schematic

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_SHARE = FIXTURES / "fake_kicad_share"


def test_hierarchical_end_to_end(tmp_path):
    yaml_path = FIXTURES / "integration_hierarchical.yaml"
    result = build(yaml_path, output_dir=tmp_path, kicad_share=FAKE_SHARE)
    assert result.success, [e.message for e in result.errors]

    pcb_path = tmp_path / "integration_hierarchical.kicad_pcb"
    main_path = tmp_path / "main.kicad_sch"
    child_path = tmp_path / "led_matrix.kicad_sch"
    for p in (pcb_path, main_path, child_path):
        assert p.exists(), f"missing {p}"

    # ---- PCB ----
    board = KiBoard.from_file(str(pcb_path))
    refs = sorted(fp.properties["Reference"] for fp in board.footprints)
    # 1 R1 + 2 LEDs + 2 caps
    assert refs == ["C1", "C2", "LED1", "LED2", "R1"]
    net_names = {n.name for n in board.nets if n.name}
    # Globals unqualified, MCU_DATA and D_MAIN are main-local (bare /),
    # CHAIN_IN on the child resolves to /D_MAIN.
    assert "VCC" in net_names
    assert "GND" in net_names
    assert "/MCU_DATA" in net_names
    assert "/D_MAIN" in net_names
    # CHAIN_IN must NOT appear as a bare or /child/CHAIN_IN name —
    # it collapses into /D_MAIN via the pin_map.
    assert "CHAIN_IN" not in net_names
    assert "/led_matrix/CHAIN_IN" not in net_names

    # R1 pad 2 drives D_MAIN; LED1/LED2 pad 2 should land on the same net.
    pads = {}
    for fp in board.footprints:
        ref = fp.properties["Reference"]
        pads[ref] = {p.number: (p.net.name if p.net else None) for p in fp.pads}
    assert pads["R1"]["2"] == "/D_MAIN"
    assert pads["LED1"]["2"] == "/D_MAIN"
    assert pads["LED2"]["2"] == "/D_MAIN"

    # ---- Main sheet ----
    sch_main = Schematic.from_file(str(main_path))
    # One HierarchicalSheet symbol referencing led_matrix.kicad_sch.
    assert len(sch_main.sheets or []) == 1
    hs = sch_main.sheets[0]
    # kiutils stores sheetName/fileName as Property objects in this version.
    sheet_file = (
        hs.fileName
        if isinstance(hs.fileName, str)
        else hs.fileName.value
    )
    assert sheet_file == "led_matrix.kicad_sch"
    # The sheet symbol has one pin (CHAIN_IN).
    assert {p.name for p in hs.pins} == {"CHAIN_IN"}
    # The main sheet has no HierarchicalLabels (main isn't a child).
    assert not (sch_main.hierarchicalLabels or [])

    # ---- Child sheet ----
    sch_child = Schematic.from_file(str(child_path))
    # Child has 4 components: 2 LEDs + 2 caps.
    assert len(sch_child.schematicSymbols) == 4
    # Child has one HierarchicalLabel text for CHAIN_IN (one per grid cell
    # that uses it — with 2 LEDs in the grid, there will be 2 labels).
    hier_names = {l.text for l in (sch_child.hierarchicalLabels or [])}
    assert hier_names == {"CHAIN_IN"}
    # No LocalLabel for CHAIN_IN (hierarchical labels only).
    assert "CHAIN_IN" not in {l.text for l in sch_child.labels}
    # Global labels for VCC/GND appear wherever components touch them.
    global_names = {l.text for l in sch_child.globalLabels}
    assert "VCC" in global_names
    assert "GND" in global_names

    # ---- Sheet instances ----
    main_paths = {si.instancePath for si in (sch_main.sheetInstances or [])}
    child_paths = {si.instancePath for si in (sch_child.sheetInstances or [])}
    # Both files share the same sheet tree table.
    assert main_paths == child_paths
    assert len(main_paths) == 2   # /main_uuid and /main_uuid/child_uuid
