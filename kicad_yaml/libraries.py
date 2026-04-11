"""KiCad library resolution: detect the install, load/cache symbols and
footprints, produce friendly errors with fuzzy suggestions on failure."""

from __future__ import annotations

import difflib
import os
import sys
from pathlib import Path
from typing import Dict, Optional

from kiutils.footprint import Footprint
from kiutils.symbol import Symbol, SymbolLib


class LibraryError(ValueError):
    """Raised when a symbol or footprint can't be resolved."""


class LibraryResolver:
    """Resolves ``lib:name`` references to kiutils Symbol / Footprint objects.

    Resolution order:
      1. ``kicad_share`` constructor arg (explicit override)
      2. ``KICAD_SHARE`` environment variable
      3. OS default auto-detect
    """

    def __init__(self, kicad_share: Optional[Path] = None) -> None:
        if kicad_share is None:
            env = os.environ.get("KICAD_SHARE")
            if env:
                kicad_share = Path(env)
            else:
                kicad_share = _auto_detect_kicad_share()
        if kicad_share is None or not kicad_share.exists():
            raise LibraryError(
                f"could not find a KiCad install. "
                f"tried: {kicad_share}. "
                f"set KICAD_SHARE env var to override."
            )
        self.kicad_share = kicad_share
        self._symbol_lib_cache: Dict[str, SymbolLib] = {}
        self._footprint_cache: Dict[str, Footprint] = {}

    def symbol(self, lib_name: str) -> Symbol:
        lib, name = _split_lib_name(lib_name)
        sym_lib = self._load_symbol_lib(lib)
        for sym in sym_lib.symbols:
            if sym.entryName == name:
                return sym
        candidates = [s.entryName for s in sym_lib.symbols]
        suggestions = difflib.get_close_matches(name, candidates, n=3, cutoff=0.6)
        suffix = (
            f" did you mean: {', '.join(suggestions)}?"
            if suggestions
            else f" available symbols in '{lib}': {', '.join(candidates[:10])}"
            + ("..." if len(candidates) > 10 else "")
        )
        raise LibraryError(
            f"symbol '{lib_name}' not found in {lib}.kicad_sym.{suffix}"
        )

    def footprint(self, lib_name: str) -> Footprint:
        if lib_name in self._footprint_cache:
            return self._footprint_cache[lib_name]
        lib, name = _split_lib_name(lib_name)
        lib_dir = self.kicad_share / "footprints" / f"{lib}.pretty"
        if not lib_dir.exists():
            raise LibraryError(
                f"footprint library '{lib}' not found at {lib_dir}"
            )
        fp_path = lib_dir / f"{name}.kicad_mod"
        if not fp_path.exists():
            candidates = [p.stem for p in lib_dir.glob("*.kicad_mod")]
            suggestions = difflib.get_close_matches(name, candidates, n=3, cutoff=0.6)
            suffix = (
                f" did you mean: {', '.join(suggestions)}?"
                if suggestions
                else f" available footprints in '{lib}': {', '.join(candidates[:10])}"
                + ("..." if len(candidates) > 10 else "")
            )
            raise LibraryError(
                f"footprint '{lib_name}' not found.{suffix}"
            )
        fp = Footprint.from_file(str(fp_path))
        self._footprint_cache[lib_name] = fp
        return fp

    def _load_symbol_lib(self, lib: str) -> SymbolLib:
        if lib in self._symbol_lib_cache:
            return self._symbol_lib_cache[lib]
        path = self.kicad_share / "symbols" / f"{lib}.kicad_sym"
        if not path.exists():
            raise LibraryError(f"symbol library file not found: {path.name}")
        sym_lib = SymbolLib.from_file(str(path))
        self._symbol_lib_cache[lib] = sym_lib
        return sym_lib


def _split_lib_name(lib_name: str) -> tuple[str, str]:
    if ":" not in lib_name:
        raise LibraryError(
            f"library reference '{lib_name}' must be in 'lib:name' form"
        )
    lib, name = lib_name.split(":", 1)
    return lib, name


def _auto_detect_kicad_share() -> Optional[Path]:
    """Return the first stock KiCad 10 install directory we find, or None."""
    candidates: list[Path] = []
    if sys.platform == "darwin":
        candidates.append(Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport"))
        candidates.append(Path("/Applications/KiCad-nightly/KiCad.app/Contents/SharedSupport"))
    elif sys.platform.startswith("linux"):
        candidates.append(Path("/usr/share/kicad"))
        candidates.append(Path("/usr/local/share/kicad"))
    elif sys.platform == "win32":
        base = Path("C:/Program Files/KiCad")
        if base.exists():
            for sub in sorted(base.iterdir(), reverse=True):
                if sub.name.startswith("10."):
                    candidates.append(sub / "share" / "kicad")
    for c in candidates:
        if c.exists():
            return c
    return None
