"""Tests for the sync command."""

from pathlib import Path

import pytest

from kicad_yaml import build
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
