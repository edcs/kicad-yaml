"""Tests for the sync command."""

from pathlib import Path

import pytest

from kicad_yaml import build
from kicad_yaml.cli import main
from kicad_yaml.sync import read_pcb_positions, recover_user_rotation

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_SHARE = FIXTURES / "fake_kicad_share"


class TestRecoverUserRotation:
    """recover_user_rotation converts a stored PCB angle delta back to
    user-facing CCW rotation, accounting for baked rotation."""

    def test_front_no_change(self):
        assert recover_user_rotation(
            stored_angle=0.0, yaml_rotation=0.0, layer="F.Cu",
        ) == 0.0

    def test_front_user_rotated(self):
        assert recover_user_rotation(
            stored_angle=90.0, yaml_rotation=0.0, layer="F.Cu",
        ) == 90.0

    def test_front_delta_on_existing(self):
        assert recover_user_rotation(
            stored_angle=45.0, yaml_rotation=90.0, layer="F.Cu",
        ) == 135.0

    def test_front_wraparound(self):
        assert recover_user_rotation(
            stored_angle=20.0, yaml_rotation=350.0, layer="F.Cu",
        ) == 10.0

    def test_back_no_change(self):
        assert recover_user_rotation(
            stored_angle=0.0, yaml_rotation=0.0, layer="B.Cu",
        ) == 0.0

    def test_back_user_rotated(self):
        assert recover_user_rotation(
            stored_angle=270.0, yaml_rotation=0.0, layer="B.Cu",
        ) == 90.0

    def test_back_delta_on_existing(self):
        assert recover_user_rotation(
            stored_angle=315.0, yaml_rotation=90.0, layer="B.Cu",
        ) == 135.0

    def test_back_no_delta(self):
        assert recover_user_rotation(
            stored_angle=0.0, yaml_rotation=90.0, layer="B.Cu",
        ) == 90.0


class TestReadPcbPositions:
    """read_pcb_positions extracts ref -> position data from a .kicad_pcb."""

    def test_reads_positions_from_built_pcb(self, tmp_path):
        yaml_path = FIXTURES / "integration_flat.yaml"
        result = build(yaml_path, output_dir=tmp_path, kicad_share=FAKE_SHARE)
        assert result.success

        pcb_path = tmp_path / "integration_flat.kicad_pcb"
        positions = read_pcb_positions(pcb_path)

        # R1 is explicit: position [5, 5], back layer
        assert "R1" in positions
        r1 = positions["R1"]
        assert r1.x == pytest.approx(5.0)
        assert r1.y == pytest.approx(5.0)
        assert r1.layer == "B.Cu"
        # Rotation is baked, so stored angle should be 0
        assert r1.angle == pytest.approx(0.0)

        # Grid components are also present (the reader doesn't filter)
        assert "LED1" in positions
        assert "C1" in positions

    def test_missing_pcb_raises(self):
        with pytest.raises(FileNotFoundError):
            read_pcb_positions(Path("/nonexistent/board.kicad_pcb"))


import shutil

from kiutils.board import Board as KiBoard
from ruamel.yaml import YAML

from kicad_yaml.sync import sync_positions


class TestSyncPositions:
    """sync_positions updates YAML in-place from PCB positions."""

    def _build_and_get_paths(self, tmp_path):
        """Build a PCB from integration_flat.yaml, return (yaml_copy, pcb_path)."""
        yaml_src = FIXTURES / "integration_flat.yaml"
        yaml_copy = tmp_path / "design.yaml"
        shutil.copy(yaml_src, yaml_copy)

        result = build(yaml_copy, output_dir=tmp_path, kicad_share=FAKE_SHARE)
        assert result.success
        pcb_path = tmp_path / "integration_flat.kicad_pcb"
        return yaml_copy, pcb_path

    def test_position_update(self, tmp_path):
        yaml_path, pcb_path = self._build_and_get_paths(tmp_path)

        # Move R1 in the PCB
        board = KiBoard.from_file(str(pcb_path))
        r1 = next(fp for fp in board.footprints if fp.properties["Reference"] == "R1")
        r1.position.X = 25.0
        r1.position.Y = 10.0
        board.to_file(str(pcb_path))

        # Sync
        outcome = sync_positions(yaml_path, pcb_path)
        assert len(outcome.changes) == 1
        assert outcome.changes[0].ref == "R1"

        # Verify YAML updated
        yaml = YAML(typ="safe")
        data = yaml.load(yaml_path)
        r1_pcb = data["sheets"]["main"]["components"][0]["pcb"]
        assert r1_pcb["position"] == [25.0, 10.0]

    def test_rotation_update(self, tmp_path):
        yaml_path, pcb_path = self._build_and_get_paths(tmp_path)

        # Rotate R1 in KiCad (it's on back layer, yaml rotation=90)
        # Add 45 CCW from back = stored -45 = 315 in KiCad convention
        board = KiBoard.from_file(str(pcb_path))
        r1 = next(fp for fp in board.footprints if fp.properties["Reference"] == "R1")
        r1.position.angle = 315.0
        board.to_file(str(pcb_path))

        outcome = sync_positions(yaml_path, pcb_path)
        assert len(outcome.changes) == 1

        yaml = YAML(typ="safe")
        data = yaml.load(yaml_path)
        r1_pcb = data["sheets"]["main"]["components"][0]["pcb"]
        assert r1_pcb["rotation"] == 135.0

    def test_grid_components_skipped(self, tmp_path):
        yaml_path, pcb_path = self._build_and_get_paths(tmp_path)

        # Move a grid component — should be ignored
        board = KiBoard.from_file(str(pcb_path))
        led1 = next(fp for fp in board.footprints if fp.properties["Reference"] == "LED1")
        led1.position.X = 999.0
        board.to_file(str(pcb_path))

        outcome = sync_positions(yaml_path, pcb_path)
        assert len(outcome.changes) == 0

    def test_no_changes(self, tmp_path):
        yaml_path, pcb_path = self._build_and_get_paths(tmp_path)

        # Read original YAML bytes
        original = yaml_path.read_text()

        outcome = sync_positions(yaml_path, pcb_path)
        assert len(outcome.changes) == 0

        # YAML should be byte-identical
        assert yaml_path.read_text() == original

    def test_preserves_yaml_structure(self, tmp_path):
        """Non-position content (templates, grids, pin_nets) survives sync."""
        yaml_path, pcb_path = self._build_and_get_paths(tmp_path)

        # Move R1
        board = KiBoard.from_file(str(pcb_path))
        r1 = next(fp for fp in board.footprints if fp.properties["Reference"] == "R1")
        r1.position.X = 30.0
        board.to_file(str(pcb_path))

        sync_positions(yaml_path, pcb_path)

        # Verify other YAML content intact
        yaml = YAML(typ="safe")
        data = yaml.load(yaml_path)
        assert data["project"]["name"] == "integration_flat"
        assert data["global_nets"] == ["VCC", "GND"]
        assert "fake_led" in data["templates"]
        r1_comp = data["sheets"]["main"]["components"][0]
        assert r1_comp["pin_nets"] == {"1": "MCU_DATA", "2": "D0"}
        assert r1_comp["template"] == "fake_r"
        # Grid still present
        assert len(data["sheets"]["main"]["grids"]) == 1


class TestSyncCli:
    """CLI integration for the sync subcommand."""

    def test_sync_command_ok(self, tmp_path, monkeypatch, capsys):
        yaml_src = FIXTURES / "integration_flat.yaml"
        yaml_copy = tmp_path / "design.yaml"
        shutil.copy(yaml_src, yaml_copy)
        monkeypatch.setenv("KICAD_SHARE", str(FAKE_SHARE))

        # Build first so we have a PCB
        exit_code = main(["build", str(yaml_copy)])
        assert exit_code == 0
        capsys.readouterr()  # clear build output

        # Now sync (no changes expected since we just built)
        exit_code = main(["sync", str(yaml_copy)])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "no position changes" in out.lower()

    def test_sync_command_missing_pcb(self, tmp_path, monkeypatch, capsys):
        # Write a YAML but don't build
        yaml_path = tmp_path / "design.yaml"
        yaml_path.write_text((FIXTURES / "integration_flat.yaml").read_text())
        monkeypatch.setenv("KICAD_SHARE", str(FAKE_SHARE))

        exit_code = main(["sync", str(yaml_path)])
        assert exit_code == 1
        err = capsys.readouterr().err
        assert "error" in err.lower()

    def test_sync_command_missing_yaml(self, monkeypatch, capsys):
        monkeypatch.setenv("KICAD_SHARE", str(FAKE_SHARE))
        exit_code = main(["sync", "/nonexistent/design.yaml"])
        assert exit_code == 1
        err = capsys.readouterr().err
        assert "error" in err.lower()
