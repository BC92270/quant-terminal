"""Validation-only V3.6 AppTest harness.

This wrapper reuses the frozen V3.5 offline fixture, which stubs unrelated
market/provider surfaces before rendering the real Phase-III implementation.
No fixture value is scientific evidence and no network or credential path is
invoked by this harness.
"""

import importlib
import sys

import streamlit as st

# Importing the frozen harness applies its provider/market stubs and renders the
# real Quantum Lab once. Keeping the parent harness byte-exact preserves V3.5.
if "app_v35_offline_harness" in sys.modules:
    importlib.reload(sys.modules["app_v35_offline_harness"])
else:
    import app_v35_offline_harness  # noqa: F401,E402


st.caption(
    "V3.6 OFFLINE APPTEST HARNESS · NETWORK/PROVIDER ACTIONS NOT INVOKED · "
    "FIXTURES EXCLUDED FROM SCIENTIFIC EVIDENCE"
)
