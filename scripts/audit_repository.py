#!/usr/bin/env python3
"""Fail-closed structural checks for the Quant Terminal repository."""

from __future__ import annotations

import ast
from collections import defaultdict
import hashlib
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {
    ".industrialization",
    ".pytest_cache",
    ".quant_cache",
    "__pycache__",
    "backups",
    "data_cache",
}
FORBIDDEN_NAMES = {".DS_Store", "package-lock.json"}
FORBIDDEN_SUFFIXES = {".bak", ".patch", ".pyc", ".zip"}
DUPLICATE_EXTENSIONS = {".json", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
DUPLICATE_EXEMPT_NAMES = {".gitkeep", "__init__.py"}
NON_DOMAIN_ROOTS = {"legacy", "scripts", "tests"}


def tracked_files() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    ).decode("utf-8")
    return [ROOT / name for name in output.split("\0") if name and (ROOT / name).is_file()]


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def forbidden_files(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        rel = path.relative_to(ROOT)
        if (
            set(rel.parts) & FORBIDDEN_PARTS
            or path.name in FORBIDDEN_NAMES
            or path.suffix.lower() in FORBIDDEN_SUFFIXES
        ):
            findings.append(rel.as_posix())
    return sorted(findings)


def syntax_errors(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if path.suffix != ".py":
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=relative(path))
        except (SyntaxError, UnicodeDecodeError) as exc:
            findings.append(f"{relative(path)}: {exc}")
    return findings


def exact_duplicates(paths: list[Path]) -> list[list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        if (
            path.suffix.lower() not in DUPLICATE_EXTENSIONS
            or path.name in DUPLICATE_EXEMPT_NAMES
            or "legacy" in path.relative_to(ROOT).parts
        ):
            continue
        payload = path.read_bytes()
        if payload:
            groups[hashlib.sha256(payload).hexdigest()].append(relative(path))
    return [sorted(group) for group in groups.values() if len(group) > 1]


def domain_cycles(paths: list[Path]) -> list[list[str]]:
    python_paths = [path for path in paths if path.suffix == ".py"]
    root_modules = {
        path.stem
        for path in python_paths
        if len(path.relative_to(ROOT).parts) == 1
    }
    packages = {
        path.relative_to(ROOT).parts[0]
        for path in python_paths
        if len(path.relative_to(ROOT).parts) > 1
        and (ROOT / path.relative_to(ROOT).parts[0] / "__init__.py").is_file()
    }
    local_domains = root_modules | packages
    graph: dict[str, set[str]] = defaultdict(set)

    for path in python_paths:
        rel = path.relative_to(ROOT)
        source = path.stem if len(rel.parts) == 1 else rel.parts[0]
        if source in NON_DOMAIN_ROOTS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel.as_posix())
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported = [node.module.split(".")[0]]
            for target in imported:
                if target in local_domains and target != source:
                    graph[source].add(target)

    index: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []
    counter = 0

    def visit(node: str) -> None:
        nonlocal counter
        index[node] = counter
        lowlink[node] = counter
        counter += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph[node]:
            if target not in index:
                visit(target)
                lowlink[node] = min(lowlink[node], lowlink[target])
            elif target in on_stack:
                lowlink[node] = min(lowlink[node], index[target])
        if lowlink[node] != index[node]:
            return
        component: list[str] = []
        while True:
            target = stack.pop()
            on_stack.remove(target)
            component.append(target)
            if target == node:
                break
        if len(component) > 1:
            components.append(sorted(component))

    for node in sorted(local_domains):
        if node not in index:
            visit(node)
    return sorted(components)


def main() -> int:
    paths = tracked_files()
    checks: dict[str, object] = {
        "tracked_files": len(paths),
        "python_files": sum(path.suffix == ".py" for path in paths),
        "forbidden_files": forbidden_files(paths),
        "syntax_errors": syntax_errors(paths),
        "exact_duplicates": exact_duplicates(paths),
        "domain_cycles": domain_cycles(paths),
    }
    failed = any(checks[key] for key in (
        "forbidden_files",
        "syntax_errors",
        "exact_duplicates",
        "domain_cycles",
    ))
    for key, value in checks.items():
        print(f"{key}: {value}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
