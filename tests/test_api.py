"""Public API surface: build(), validate(), BuildResult, Message."""

from pathlib import Path
import tempfile

from kicad_yaml import build, validate, BuildResult, Message, SourceLocation

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_SHARE = FIXTURES / "fake_kicad_share"
MINIMAL = FIXTURES / "minimal_flat.yaml"


def test_validate_minimal_flat_ok():
    result = validate(MINIMAL, kicad_share=FAKE_SHARE)
    assert isinstance(result, BuildResult)
    # minimal_flat uses real library names, not Fake:*, so validation
    # reports LIB errors.  Check that the shape is right:
    assert not result.success
    assert result.errors
    assert all(isinstance(m, Message) for m in result.errors)
    assert result.errors[0].code.startswith("LIB-")


def test_validate_accepts_literal_yaml():
    yaml_text = """
project: {name: t}
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
    result = validate(yaml_text, kicad_share=FAKE_SHARE)
    assert result.success
    assert result.errors == []


def test_build_returns_generated_file_paths():
    yaml_text = """
project: {name: t}
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
    with tempfile.TemporaryDirectory() as td:
        result = build(yaml_text, output_dir=Path(td), kicad_share=FAKE_SHARE)
    assert result.success
    assert len(result.generated_files) == 2
    suffixes = {p.suffix for p in result.generated_files}
    assert suffixes == {".kicad_pcb", ".kicad_sch"}


def test_build_returns_load_error_as_message():
    bad = "project: {name: t}\nboard: {size: [50, 30]}\nsheets: {other: {paper: A4}}"
    result = build(bad, output_dir=Path("/tmp"), kicad_share=FAKE_SHARE)
    assert not result.success
    assert result.errors
    assert any("main" in m.message.lower() for m in result.errors)
    assert all(m.code.startswith("LOAD-") for m in result.errors)
