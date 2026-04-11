"""Verify our kiutils Net.from_sexpr patch handles KiCad 10 short-form nets."""

from kicad_yaml import kicad_net_patch  # noqa: F401 - importing applies the patch
from kiutils.items.common import Net


def test_short_form_net_parses_with_number_zero():
    """KiCad 10 writes (net "VCC") with no number.  We accept it."""
    sexpr = ["net", '"VCC"']
    result = Net.from_sexpr(sexpr)
    assert result.number == 0
    assert result.name == '"VCC"'


def test_long_form_net_still_parses():
    """Legacy (net 1 "VCC") three-element form must still work."""
    sexpr = ["net", 1, '"VCC"']
    result = Net.from_sexpr(sexpr)
    assert result.number == 1
    assert result.name == '"VCC"'


def test_malformed_net_raises():
    """Empty or wrong-keyword input still errors."""
    import pytest
    with pytest.raises(Exception, match="correct type"):
        Net.from_sexpr(["foo", 1, "bar"])
