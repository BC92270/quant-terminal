from __future__ import annotations

import subprocess
import sys


def test_market_intelligence_import_is_lazy_and_network_free() -> None:
    code = """
import socket, sys
def blocked(*args, **kwargs):
    raise AssertionError('network access attempted during import')
socket.create_connection = blocked
import market_intelligence
assert callable(market_intelligence.render_market_intelligence_lab)
assert '_quant_terminal_market_intelligence_legacy' not in sys.modules
print('ok')
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_legacy_macro_api_remains_available_through_lazy_bridge() -> None:
    from market_intelligence import render_market_intelligence

    assert callable(render_market_intelligence)
