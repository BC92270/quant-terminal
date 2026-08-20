#!/usr/bin/env python3
"""Safely synchronize the global JARVIS header while Market Psychology is open.

The patch is deliberately narrow:
1) extend the existing Market Psychology import to include the shell-header renderer;
2) replace only the existing render_header() wrapper so Psychology uses its autonomous
   session-state header while every other workspace keeps the original generic header.

No routing, mode registry, command-center buttons, analysis logic, or asset router is changed.
A timestamp-free `.pre_market_psychology_v25.bak` backup is written next to app.py.
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path


def patch(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    if "market_psychology_lab_open" not in src or "render_market_psychology_lab" not in src:
        raise SystemExit("Refusing patch: this app.py does not appear to contain the existing Market Psychology direct route.")

    original = src

    # Import: support either the original one-line import or an already parenthesized block.
    if "render_market_psychology_shell_header" not in src:
        one_line = "from market_psychology_lab import render_market_psychology_lab"
        if one_line in src:
            src = src.replace(
                one_line,
                "from market_psychology_lab import (\n        render_market_psychology_lab,\n        render_market_psychology_shell_header,\n    )",
                1,
            )
        else:
            raise SystemExit("Refusing patch: existing Market Psychology import block was not recognized.")

    # Replace only the render_header wrapper, bounded by the next known function.
    pattern = re.compile(
        r"def render_header\(\):\n(?:.|\n)*?\n\n\ndef render_main_metrics\(analysis: dict\):",
        re.MULTILINE,
    )
    match = pattern.search(src)
    if not match:
        raise SystemExit("Refusing patch: render_header() wrapper was not recognized. No file was modified.")

    replacement = '''def render_header():
    """Terminal shell header with an additive Market Psychology autonomous view."""
    apply_terminal_shell_theme()

    # Market Psychology is intentionally outside the normal ticker-mode router.
    # While its direct-route flag is active, use its own non-sensitive session-state
    # context instead of leaking the previously selected Correlation Matrix workspace
    # into the global header. Every other module follows the exact legacy path below.
    if st.session_state.get("market_psychology_lab_open", False):
        try:
            if callable(globals().get("render_market_psychology_shell_header")):
                render_market_psychology_shell_header()
                return
        except Exception:
            # Header failure must never block the research workspace.
            pass

    render_terminal_header_shell(
        ticker=st.session_state.get("ticker"),
        analysis=st.session_state.get("analysis"),
        last_params=st.session_state.get("last_params"),
    )



def render_main_metrics(analysis: dict):'''
    src = pattern.sub(replacement, src, count=1)

    if src == original:
        raise SystemExit("No changes were required.")

    backup = path.with_name(path.name + ".pre_market_psychology_v25.bak")
    shutil.copy2(path, backup)
    path.write_text(src, encoding="utf-8")
    print(f"Patched: {path}")
    print(f"Backup:  {backup}")
    print("Changed only: Market Psychology shell-header import + render_header() wrapper.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python apply_market_psychology_v25_header_patch.py app.py")
    patch(Path(sys.argv[1]).resolve())
