"""Runtime patch for kiutils 1.4.8 to handle KiCad 10's short-form pad net
syntax.

KiCad 10 writes pad nets as ``(net "VCC")`` with no explicit number.  The
installed kiutils parser (``Net.from_sexpr``) expects the legacy long form
``(net N "VCC")`` and raises IndexError.  We monkey-patch ``Net.from_sexpr``
to accept both.  Kiutils writes use the long form, which KiCad reads fine.

Importing this module is enough to apply the patch.  Writer modules should
import it before any ``Board.from_file`` / ``Footprint.from_file`` call.
"""

from __future__ import annotations

from kiutils.items.common import Net


def _patched_net_from_sexpr(cls, exp):
    if not isinstance(exp, list) or exp[0] != "net":
        raise Exception("Expression does not have the correct type")
    obj = cls()
    if len(exp) == 2:              # KiCad 10 short form: (net "NAME")
        obj.number = 0
        obj.name = exp[1]
    else:                          # legacy long form: (net N "NAME")
        obj.number = exp[1]
        obj.name = exp[2]
    return obj


Net.from_sexpr = classmethod(_patched_net_from_sexpr)
