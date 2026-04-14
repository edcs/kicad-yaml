"""CLI entry point tests."""

from pathlib import Path
import pytest

from kicad_yaml.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_SHARE = FIXTURES / "fake_kicad_share"

YAML_OK = """
project: {name: cli_ok}
board: {size: [50, 30]}
global_nets: [VCC, GND]
templates:
  fc:
    symbol: Fake:FakeC
    footprint: Fake:FakeSMD
sheets:
  main:
    paper: A4
    components:
      - ref: C1
        template: fc
        pcb: {position: [10, 10]}
        pin_nets: {"1": VCC, "2": GND}
"""


def test_build_command_ok(tmp_path, monkeypatch, capsys):
    yaml_path = tmp_path / "design.yaml"
    yaml_path.write_text(YAML_OK)
    monkeypatch.setenv("KICAD_SHARE", str(FAKE_SHARE))
    exit_code = main(["build", str(yaml_path)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "cli_ok.kicad_pcb" in out
    assert "cli_ok.kicad_sch" in out


def test_build_command_missing_file(monkeypatch, capsys):
    monkeypatch.setenv("KICAD_SHARE", str(FAKE_SHARE))
    exit_code = main(["build", "/nonexistent/design.yaml"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "error" in err.lower()


def test_validate_command_ok(tmp_path, monkeypatch, capsys):
    yaml_path = tmp_path / "design.yaml"
    yaml_path.write_text(YAML_OK)
    monkeypatch.setenv("KICAD_SHARE", str(FAKE_SHARE))
    exit_code = main(["validate", str(yaml_path)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "ok" in out.lower() or "valid" in out.lower()


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
