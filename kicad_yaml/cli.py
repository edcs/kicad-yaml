"""Command-line entry point: thin wrapper over the public API."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from kicad_yaml import __version__, build, validate, BuildResult


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kicad-yaml",
        description="Generate KiCad schematics and PCBs from a YAML design.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    build_cmd = sub.add_parser("build", help="Generate .kicad_sch and .kicad_pcb from a YAML design")
    build_cmd.add_argument("yaml", type=Path, help="Path to the design YAML file")
    build_cmd.add_argument("--output-dir", type=Path, default=None,
                           help="Where to write the generated files (default: beside the YAML)")
    build_cmd.add_argument("--reload", action="store_true",
                           help="After writing, ask a running KiCad PCB Editor to reload the file (macOS only)")

    val_cmd = sub.add_parser("validate", help="Check a design YAML for errors without writing files")
    val_cmd.add_argument("yaml", type=Path, help="Path to the design YAML file")

    args = parser.parse_args(argv)
    kicad_share_env = os.environ.get("KICAD_SHARE")
    kicad_share = Path(kicad_share_env) if kicad_share_env else None

    if args.command == "build":
        if not args.yaml.exists():
            print(f"error: file not found: {args.yaml}", file=sys.stderr)
            return 1
        result = build(args.yaml, output_dir=args.output_dir,
                       kicad_share=kicad_share, reload_kicad=args.reload)
        return _report(result, "build")

    if args.command == "validate":
        if not args.yaml.exists():
            print(f"error: file not found: {args.yaml}", file=sys.stderr)
            return 1
        result = validate(args.yaml, kicad_share=kicad_share)
        return _report(result, "validate")

    parser.error(f"unknown command {args.command!r}")
    return 2


def _report(result: BuildResult, command: str) -> int:
    if not result.success:
        for msg in result.errors:
            loc = ""
            if msg.source and msg.source.file:
                loc = f"{msg.source.file}:{msg.source.line or '?'}: "
            print(f"{loc}error: [{msg.code}] {msg.message}", file=sys.stderr)
        return 1
    for msg in result.warnings:
        print(f"warning: [{msg.code}] {msg.message}", file=sys.stderr)
    if command == "build":
        print(f"ok: wrote {len(result.generated_files)} file(s)")
        for p in result.generated_files:
            print(f"  {p}")
    else:
        print("ok: design is valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
