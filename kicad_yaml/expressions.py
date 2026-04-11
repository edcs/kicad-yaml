"""Safe arithmetic expression evaluator for grid cell template strings.

Wraps simpleeval with an empty function list and a whitelisted set of
variables.  Used to substitute expressions like ``{index+1}`` inside
strings such as ``"D{index+1}"`` or ``"LED_R{row}_C{col}"``.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, Mapping

from simpleeval import EvalWithCompoundTypes, InvalidExpression, NameNotDefined


ALLOWED_VARS: tuple = ("index", "row", "col", "rows", "cols")
"""Standard variable set exposed to grid cell expressions."""

_EXPR_RE = re.compile(r"\{([^{}]+)\}")


class ExpressionError(ValueError):
    """Raised when a template expression can't be evaluated."""


def substitute(template: str, variables: Mapping[str, int | str]) -> str:
    """Substitute every ``{...}`` expression in ``template`` using
    ``variables``.

    Strings without braces are returned unchanged.  Multiple expressions
    in one string are each evaluated independently.  The evaluator is
    sandboxed: no function calls, no attribute access, no indexing.

    Raises ``ExpressionError`` with a helpful message on any failure.
    """
    if "{" not in template:
        return template

    def _eval_one(match: re.Match) -> str:
        expr = match.group(1)
        evaluator = EvalWithCompoundTypes(names=dict(variables), functions={})
        try:
            value = evaluator.eval(expr)
        except NameNotDefined as e:
            raise ExpressionError(
                f"invalid expression {{{expr}}}: {e}. "
                f"available variables: {', '.join(ALLOWED_VARS)}"
            ) from e
        except InvalidExpression as e:
            raise ExpressionError(
                f"invalid expression {{{expr}}}: {e}"
            ) from e
        except Exception as e:
            raise ExpressionError(
                f"invalid expression {{{expr}}}: {e}"
            ) from e
        return str(value)

    return _EXPR_RE.sub(_eval_one, template)


def variables_used(template: str) -> Iterable[str]:
    """Return the variable names referenced by all ``{...}`` expressions
    in ``template``.  Used by the loader's validation pass to check
    expressions at load time without executing them.
    """
    names: set = set()
    for match in _EXPR_RE.finditer(template):
        expr = match.group(1)
        try:
            import ast
            tree = ast.parse(expr, mode="eval")
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    names.add(node.id)
        except SyntaxError:
            # Defer the real error to substitution time
            continue
    return names
