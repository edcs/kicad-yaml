"""PCB writer: outline + net table only."""

from pathlib import Path
import tempfile

from kicad_yaml import kicad_net_patch  # noqa: F401
from kicad_yaml.schema import Board, Design, Project, Sheet
from kicad_yaml.pcb import write_pcb
from kiutils.board import Board as KiBoard


def test_write_empty_board_outline():
    design = Design(
        project=Project(name="t"),
        board=Board(size=(50.0, 30.0)),
        global_nets=["VCC", "GND"],
        templates={},
        sheets={"main": Sheet(paper="A4")},
    )

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "test.kicad_pcb"
        write_pcb(design, resolved=[], net_order=["VCC", "GND"], output=out)
        assert out.exists()

        board = KiBoard.from_file(str(out))
        # Four edge segments forming a rectangle
        edge_lines = [g for g in board.graphicItems
                      if type(g).__name__ == "GrLine" and g.layer == "Edge.Cuts"]
        assert len(edge_lines) == 4
        # Net table: (0,"") + VCC + GND
        net_names = [n.name for n in board.nets]
        assert "VCC" in net_names and "GND" in net_names
        assert len(board.footprints) == 0
