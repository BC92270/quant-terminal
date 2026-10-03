from __future__ import annotations

import ast
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from institutional_router import INSTRUMENT_BY_SYMBOL, WORKSPACE_BY_CODE, workspace_context
from institutional_router import build_workspace_route
from quant_ai.section_agents import (
    NAVIGATOR_MANIFEST,
    TRADING_PLAN_MANIFEST,
    WORKSPACE_CODES,
    WORKSPACE_MANIFESTS,
    build_default_section_registry,
)


EXPECTED_WORKSPACE_CODES = (
    "corr",
    "portfolio",
    "risk",
    "backtest",
    "momentum",
    "monte_carlo",
    "company",
    "options",
    "decision",
    "ml",
    "fx",
    "commodities",
    "rates",
    "credit",
    "macro",
    "scientific_research",
    "market_intelligence",
    "psychology",
    "quant_ai",
    "worldmonitor",
)

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"


def _query(route: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(route).query)


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _literal_first_argument(node: ast.Call) -> str | None:
    if not node.args or not isinstance(node.args[0], ast.Constant):
        return None
    return node.args[0].value if isinstance(node.args[0].value, str) else None


def test_section_manifests_match_the_authoritative_workspace_router() -> None:
    manifests_by_code = WORKSPACE_MANIFESTS

    assert WORKSPACE_CODES == EXPECTED_WORKSPACE_CODES
    assert tuple(WORKSPACE_BY_CODE) == EXPECTED_WORKSPACE_CODES
    assert tuple(manifests_by_code) == EXPECTED_WORKSPACE_CODES

    routed_fields = (
        "function",
        "label",
        "description",
        "mode",
        "special_route",
        "default_asset",
        "default_symbol",
        "audiences",
        "force_context",
    )
    for code, workspace in WORKSPACE_BY_CODE.items():
        manifest = manifests_by_code[code]
        assert manifest.section_id == code
        for field_name in routed_fields:
            assert getattr(manifest, field_name) == getattr(workspace, field_name)


def test_default_registry_covers_navigator_and_every_workspace_once() -> None:
    registry = build_default_section_registry()
    manifests_by_code = WORKSPACE_MANIFESTS
    expected = {*EXPECTED_WORKSPACE_CODES, "navigator", "trading_plan"}

    assert set(registry.codes()) == expected
    assert len(registry.manifests()) == len(expected) == 22
    assert registry.get("navigator") is NAVIGATOR_MANIFEST
    assert registry.get("trading_plan") is TRADING_PLAN_MANIFEST
    assert all(registry.require(code) is manifests_by_code[code] for code in EXPECTED_WORKSPACE_CODES)


def test_every_workspace_builds_a_complete_round_trip_route() -> None:
    instrument = INSTRUMENT_BY_SYMBOL["SPY"]

    for code, workspace in WORKSPACE_BY_CODE.items():
        query = _query(build_workspace_route(code, instrument, period="2y", interval="1wk"))

        if workspace.special_route:
            assert query == {"workspace": [workspace.special_route]}
            continue

        asset, symbol = workspace_context(code, instrument)
        assert query == {
            "workspace": ["terminal"],
            "asset": [asset],
            "symbol": [symbol],
            "period": ["2y"],
            "interval": ["1wk"],
            "mode": [workspace.mode],
        }


def test_app_mounts_the_fail_soft_assistant_on_all_route_families() -> None:
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"), filename=str(APP_PATH))
    helper_name = "_render_contextual_section_assistant"
    helper = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == helper_name
    )

    assert any(
        _call_name(node) == "render_section_assistant"
        for node in ast.walk(helper)
        if isinstance(node, ast.Call)
    )
    assert any(
        isinstance(node, ast.Try)
        and any(isinstance(handler.type, ast.Name) and handler.type.id == "Exception" for handler in node.handlers)
        for node in ast.walk(helper)
    )

    mounts = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node) == helper_name
    ]
    assert len(mounts) == 7
    assert {_literal_first_argument(node) for node in mounts if node.args} == {
        "navigator",
        "worldmonitor",
        "scientific_research",
        "market_intelligence",
        "psychology",
        "quant_ai",
    }

    dynamic_mount = next(node for node in mounts if not node.args)
    mode_keyword = next(item for item in dynamic_mount.keywords if item.arg == "mode_or_route")
    assert isinstance(mode_keyword.value, ast.Name)
    assert mode_keyword.value.id == "mode_input"

    fixed_income_branch = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == "mode_input"
        and any(
            isinstance(comparator, ast.Constant)
            and comparator.value == "Fixed Income & Credit Analytics"
            for comparator in node.comparators
        )
    )
    assert dynamic_mount.lineno < fixed_income_branch.lineno

    navigator_mount = next(node for node in mounts if _literal_first_argument(node) == "navigator")
    navigator_home = max(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and _call_name(node) == "render_asset_class_home"
            and node.lineno < navigator_mount.lineno
        ),
        key=lambda node: node.lineno,
    )
    navigator_stop = min(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and _call_name(node) == "stop"
            and node.lineno > navigator_mount.lineno
        ),
        key=lambda node: node.lineno,
    )
    assert navigator_home.lineno < navigator_mount.lineno < navigator_stop.lineno
