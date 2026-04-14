"""Best-effort "tell KiCad to reload the PCB" helper.

Currently implemented only on macOS via osascript — sends File → Revert
to the running PCB Editor so a freshly written .kicad_pcb is reloaded
without the user having to close/reopen the file.

On other platforms (or when KiCad isn't running) this is a no-op.
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path


_APPLESCRIPT = r'''
-- PCB editor can appear under several process names depending on KiCad version.
set tried to {"kicad", "pcbnew", "PCB Editor", "kicad-pcb", "KiCad"}
set matched to ""
tell application "System Events"
    repeat with procName in tried
        if exists process procName then
            set matched to procName as string
            exit repeat
        end if
    end repeat
end tell
if matched is "" then
    return "not-running"
end if

try
    tell application "System Events"
        tell process matched
            set frontmost to true
            set fileMenu to menu 1 of menu bar item "File" of menu bar 1
            -- Try both punctuation variants; menu item names differ by version.
            set itemNames to {"Revert...", "Revert", "Revert\\u2026"}
            repeat with n in itemNames
                if exists menu item (n as string) of fileMenu then
                    click menu item (n as string) of fileMenu
                    return "ok:" & matched
                end if
            end repeat
        end tell
    end tell
    return "error:no-revert-item"
on error errMsg number errNum
    if errNum is -1719 then
        return "error:accessibility-denied"
    end if
    return "error:" & errMsg
end try
'''


def refresh_open_pcb(pcb_path: Path) -> str:
    """Ask a running KiCad PCB editor to reload ``pcb_path``.

    Returns a short status string for diagnostics:
      - ``"skipped:<reason>"`` when we didn't attempt the refresh
      - ``"ok:<process>"`` when the menu click succeeded
      - ``"not-running"`` when no KiCad PCB editor process was found
      - ``"error:<detail>"`` when osascript itself failed

    Never raises — best-effort.
    """
    if platform.system() != "Darwin":
        return "skipped:non-macos"

    lock_file = pcb_path.parent / f"~{pcb_path.name}.lck"
    if not lock_file.exists():
        return "skipped:not-open"

    try:
        result = subprocess.run(
            ["osascript", "-e", _APPLESCRIPT],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"error:{type(exc).__name__}"

    if result.returncode != 0:
        return f"error:{(result.stderr or '').strip()[:120]}"
    return (result.stdout or "").strip() or "error:empty"
