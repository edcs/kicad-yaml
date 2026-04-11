"""Tests for KiCad library resolution."""

from pathlib import Path
import pytest
from kicad_yaml.libraries import LibraryResolver, LibraryError

FIXTURES = Path(__file__).parent / "fixtures" / "fake_kicad_share"


def test_resolve_symbol_ok():
    resolver = LibraryResolver(kicad_share=FIXTURES)
    sym = resolver.symbol("Fake:FakeC")
    assert sym.entryName == "FakeC"


def test_resolve_symbol_unknown_name_suggests():
    resolver = LibraryResolver(kicad_share=FIXTURES)
    with pytest.raises(LibraryError, match="FakeC"):
        resolver.symbol("Fake:FakeX")


def test_resolve_symbol_unknown_library_errors():
    resolver = LibraryResolver(kicad_share=FIXTURES)
    with pytest.raises(LibraryError, match="Missing.kicad_sym"):
        resolver.symbol("Missing:Whatever")


def test_resolve_footprint_ok():
    resolver = LibraryResolver(kicad_share=FIXTURES)
    fp = resolver.footprint("Fake:FakeSMD")
    assert fp.entryName == "FakeSMD"


def test_resolve_footprint_unknown_errors():
    resolver = LibraryResolver(kicad_share=FIXTURES)
    with pytest.raises(LibraryError, match="FakeSMD"):
        resolver.footprint("Fake:Nonexistent")


def test_caching_same_lib_only_parsed_once():
    resolver = LibraryResolver(kicad_share=FIXTURES)
    _ = resolver.symbol("Fake:FakeC")
    _ = resolver.symbol("Fake:FakeR")   # same library file
    assert len(resolver._symbol_lib_cache) == 1


def test_auto_detect_requires_existing_path():
    with pytest.raises(LibraryError, match="could not find a KiCad"):
        LibraryResolver(kicad_share=Path("/definitely/not/here"))
