"""Validation-only V3.8 AppTest harness with zero provider activity."""

import importlib
import sys

import streamlit as st

# The frozen predecessor harness applies the offline market/provider stubs and
# renders the current Quantum Lab.  V3.8 adds no network-capable dependency.
if "app_v37_offline_harness" in sys.modules:
    importlib.reload(sys.modules["app_v37_offline_harness"])
else:
    import app_v37_offline_harness  # noqa: F401,E402


st.caption(
    "V3.8 OFFLINE APPTEST HARNESS · NETWORK/PROVIDER ACTIONS NOT INVOKED · "
    "OFFLINE MARKET/PROVIDER STUBS EXCLUDED FROM SCIENTIFIC EVIDENCE"
)
