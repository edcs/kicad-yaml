"""Tests for the grid-cell template expression evaluator."""

import pytest
from kicad_yaml.expressions import substitute, ExpressionError, ALLOWED_VARS


def test_substitute_single_var():
    assert substitute("LED{index}", {"index": 1, "row": 1, "col": 1}) == "LED1"


def test_substitute_arithmetic():
    assert substitute("D{index+1}", {"index": 5}) == "D6"


def test_substitute_multi_var():
    vars_ = {"row": 2, "col": 3, "cols": 13}
    assert substitute("LED_R{row}_C{col}", vars_) == "LED_R2_C3"
    assert substitute("KEY{(row-1)*cols+col}", vars_) == "KEY16"


def test_substitute_ternary():
    vars_ = {"index": 1, "row": 1}
    assert substitute("{'VCC' if row == 1 else 'ROW_POS'}", vars_) == "VCC"
    vars_["row"] = 2
    assert substitute("{'VCC' if row == 1 else 'ROW_POS'}", vars_) == "ROW_POS"


def test_substitute_no_braces_passthrough():
    assert substitute("GND", {"index": 1}) == "GND"


def test_substitute_multiple_expressions_in_one_string():
    assert substitute("D{index}_to_D{index+1}", {"index": 5}) == "D5_to_D6"


def test_substitute_undefined_variable_raises():
    with pytest.raises(ExpressionError, match="foo"):
        substitute("LED{index+foo}", {"index": 1})


def test_substitute_function_call_rejected():
    """simpleeval must be configured with functions={} — no abs(), min(), etc. in v1."""
    with pytest.raises(ExpressionError):
        substitute("X{abs(-5)}", {})


def test_allowed_vars_contains_standard_set():
    assert set(ALLOWED_VARS) == {"index", "row", "col", "rows", "cols"}
