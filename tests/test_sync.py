"""Tests for the sync command."""

import pytest

from kicad_yaml.sync import recover_user_rotation


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
