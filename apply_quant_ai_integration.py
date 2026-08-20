"""Safe one-shot integrator for Quant AI CIO.

Run from the Quant Terminal project root after copying this package there:
    python apply_quant_ai_integration.py

The installer is idempotent, creates backups, renames the menu entry Snapshot -> Quant AI,
and keeps the legacy Snapshot route accepted as an alias for old session state/bookmarks.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app.py"
UI_CANDIDATES = [ROOT / "ui_terminal_standby.py", ROOT / "ui_terminal_shell.py", ROOT / "ui_terminal.py", APP]
REQ = ROOT / "requirements.txt"

IMPORT_BLOCK = '''
# ============================================================
# QUANT AI CIO — SAFE IMPORT
# ============================================================
try:
    from quant_ai_lab import render_quant_ai_terminal
    QUANT_AI_IMPORT_ERROR = None
except Exception as exc:
    render_quant_ai_terminal = None
    QUANT_AI_IMPORT_ERROR = exc

'''

ROUTE_BLOCK = '''{indent}elif mode_input in {{"Quant AI", "Snapshot"}}:
{indent}    if callable(render_quant_ai_terminal):
{indent}        render_quant_ai_terminal(
{indent}            ticker=ticker,
{indent}            price_data=price_data,
{indent}            analysis=analysis,
{indent}        )
{indent}    else:
{indent}        st.error(
{indent}            "Quant AI CIO is unavailable. "
{indent}            f"Import error: {{QUANT_AI_IMPORT_ERROR}}"
{indent}        )

'''


def compile_file(path: Path) -> None:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def backup(path: Path) -> None:
    if not path.exists():
        return
    target = path.with_suffix(path.suffix + ".bak_before_quant_ai")
    if not target.exists():
        shutil.copy2(path, target)


def integrate_app() -> None:
    if not APP.exists():
        raise FileNotFoundError(f"app.py not found at {APP}")
    text = APP.read_text(encoding="utf-8")
    changed = False
    if "from quant_ai_lab import render_quant_ai_terminal" not in text:
        markers = [
            "# ============================================================\n# COMPANY INTELLIGENCE",
            "from ui_theme import",
            "st.set_page_config(",
        ]
        pos = -1
        for marker in markers:
            pos = text.find(marker)
            if pos >= 0:
                break
        if pos < 0:
            match = re.search(r"\n(?=st\.set_page_config\()", text)
            pos = match.start() + 1 if match else 0
        text = text[:pos] + IMPORT_BLOCK + text[pos:]
        changed = True

    if 'mode_input in {"Quant AI", "Snapshot"}' not in text:
        pattern = re.compile(
            r'^(?P<indent>[ \t]*)elif mode_input == "Snapshot":\s*\n(?P=indent)[ \t]+render_snapshot_mode\(ticker, price_data, analysis\)\s*\n',
            re.MULTILINE,
        )
        match = pattern.search(text)
        if not match:
            raise RuntimeError('Could not locate the exact legacy Snapshot routing block in app.py. No app.py write was made.')
        text = text[:match.start()] + ROUTE_BLOCK.format(indent=match.group("indent")) + text[match.end():]
        changed = True

    if changed:
        backup(APP)
        APP.write_text(text, encoding="utf-8")
    compile_file(APP)
    print(f"[OK] app.py {'updated' if changed else 'already integrated'}")


def integrate_menu() -> None:
    for path in UI_CANDIDATES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if '"Quant AI"' in text:
            compile_file(path)
            print(f"[OK] menu already integrated in {path.name}")
            return
        if '"Snapshot"' not in text:
            continue
        # Replace only a list item line, never prose/function names.
        updated, n = re.subn(r'^(?P<i>[ \t]*)"Snapshot",(?P<t>[ \t]*)$', r'\g<i>"Quant AI",\g<t>', text, count=1, flags=re.MULTILINE)
        if n:
            backup(path)
            path.write_text(updated, encoding="utf-8")
            compile_file(path)
            print(f"[OK] Snapshot menu renamed to Quant AI in {path.name}")
            return
    raise RuntimeError('Could not find a standalone "Snapshot", menu item. app.py may be integrated, but menu was not modified.')


def update_requirements() -> None:
    required = ["openai-agents>=0.16.0", "pydantic>=2.8"]
    text = REQ.read_text(encoding="utf-8") if REQ.exists() else ""
    additions = []
    for req in required:
        package = req.split(">=")[0].lower().replace("_", "-")
        present = any(line.strip().lower().replace("_", "-").startswith(package) for line in text.splitlines())
        if not present:
            additions.append(req)
    if additions:
        if REQ.exists():
            backup(REQ)
        suffix = "" if not text or text.endswith("\n") else "\n"
        REQ.write_text(text + suffix + "\n".join(additions) + "\n", encoding="utf-8")
        print("[OK] requirements updated: " + ", ".join(additions))
    else:
        print("[SKIP] Quant AI requirements already present")


def verify_package() -> None:
    paths = [ROOT / "quant_ai_lab.py", *sorted((ROOT / "quant_ai").glob("*.py"))]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing Quant AI files: " + ", ".join(missing))
    for path in paths:
        compile_file(path)
    print(f"[OK] Quant AI package syntax: {len(paths)} files")


def main() -> int:
    try:
        verify_package()
        integrate_app()
        integrate_menu()
        update_requirements()
        print("\nQuant AI CIO integration complete.")
        print("Next:")
        print("  python verify_quant_ai.py")
        print("  pip install -r requirements.txt")
        print("  export OPENAI_API_KEY='...'   # or add to your existing secret environment")
        print("  streamlit run app.py")
        return 0
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
