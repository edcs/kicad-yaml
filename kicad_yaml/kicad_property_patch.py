"""Runtime patch for kiutils to preserve the full footprint property
definition (position, layer, effects) through parse → write.

kiutils 1.4.x reduces a footprint property to just ``name -> text``
(``Dict[str, str]``) when parsing, so on write it emits only
``(property "Reference" "R1")`` with no position or layer.  KiCad then
has no idea where to render the reference text and places it at an
arbitrary default location, producing "ghost" labels floating off the
board — especially visible on rotated back-layer footprints.

This patch:

  1. Augments ``Footprint.from_sexpr`` to also stash the raw parsed
     ``property`` s-expressions on the footprint as ``_rawProperties``.
  2. Replaces ``Footprint.to_sexpr`` output so that each bare
     ``(property "Name" "Value")`` line is replaced with the full
     multi-line form using the preserved position/layer/effects.

The dict value in ``fp.properties["Reference"]`` remains authoritative
for the *text*; everything else (position, layer, effects) round-trips
verbatim from the source footprint.

Importing this module applies the patch.  Writer modules should import
it before any ``Board.from_file`` / ``Footprint.from_file`` call.
"""

from __future__ import annotations

import re
from typing import Any, List

from kiutils.footprint import Footprint, dequote


_original_from_sexpr = Footprint.from_sexpr.__func__
_original_to_sexpr = Footprint.to_sexpr


def _patched_from_sexpr(cls, exp):
    obj = _original_from_sexpr(cls, exp)
    raw: dict = {}
    for item in exp[1:]:
        if isinstance(item, list) and len(item) >= 2 and item[0] == "property":
            raw[str(item[1])] = item
    # Use object.__setattr__ in case kiutils ever makes Footprint frozen.
    object.__setattr__(obj, "_rawProperties", raw)
    return obj


def _format_sub(node: Any) -> str:
    """Format a single parsed s-expr node as KiCad-style text (one line)."""
    if isinstance(node, list):
        parts = [_format_sub(item) for item in node]
        return "(" + " ".join(parts) + ")"
    if isinstance(node, bool):
        return "yes" if node else "no"
    if isinstance(node, str):
        # Heuristic: quote if the string contains whitespace, is empty, or
        # looks like a layer/value that stock footprints always quote.
        needs_quote = (
            not node
            or any(c.isspace() for c in node)
            or "." in node
            or "/" in node
            or "*" in node
            or ":" in node
        )
        return f'"{node}"' if needs_quote else node
    return str(node)


def _format_property(raw: List[Any], indent_str: str, new_value: str) -> str:
    """Render a full property s-expr list as multi-line KiCad text.

    ``raw`` is the parsed list, e.g.::

        ['property', 'Reference', 'REF**',
         ['at', 0, -1.43, 0], ['layer', 'F.SilkS'], ['effects', ...]]

    ``new_value`` replaces ``raw[2]`` (the text) so edits made through
    ``fp.properties[name] = ...`` are honoured.
    """
    name = str(raw[1])
    head = f'{indent_str}(property "{dequote(name)}" "{dequote(new_value)}"'
    if len(raw) <= 3:
        return head + ")\n"
    sub_indent = indent_str + "  "
    lines = [head]
    for sub in raw[3:]:
        lines.append(f"{sub_indent}{_format_sub(sub)}")
    lines.append(f"{indent_str})")
    return "\n".join(lines) + "\n"


def _patched_to_sexpr(
    self, indent: int = 1, newline: bool = True, layerInFirstLine: bool = False
) -> str:
    text = _original_to_sexpr(self, indent, newline, layerInFirstLine)
    raw = getattr(self, "_rawProperties", None)
    if not raw:
        return text
    for name, value in self.properties.items():
        full = raw.get(name)
        if full is None:
            continue
        # Match the bare "(property \"Name\" \"Value\")" line regardless of
        # how many leading spaces kiutils used.
        pattern = re.compile(
            r'^([ \t]*)\(property[ \t]+"'
            + re.escape(dequote(name))
            + r'"[ \t]+"'
            + re.escape(dequote(value))
            + r'"\)\s*\n',
            re.MULTILINE,
        )
        def _sub(match: re.Match) -> str:
            indent_str = match.group(1)
            return _format_property(full, indent_str, value)
        text = pattern.sub(_sub, text, count=1)
    return text


Footprint.from_sexpr = classmethod(_patched_from_sexpr)
Footprint.to_sexpr = _patched_to_sexpr
