"""Validation-only V3.7 AppTest harness.

This wrapper reuses the frozen V3.6 offline harness chain, which stubs unrelated
market/provider surfaces before rendering the real Phase-III implementation.
Only those out-of-scope market/provider stubs are excluded from scientific
evidence.  The sealed N=4, K=2 compiler fixture remains the explicitly bounded
V3.7 prototype evidence.  The harness invokes no network, credential, provider
or QPU path.
"""

import importlib
import sys

import streamlit as st

# Importing the frozen predecessor harness applies its offline stubs and renders
# the current Quantum Lab once.  The V3.6 harness itself remains byte-exact.
if "app_v36_offline_harness" in sys.modules:
    importlib.reload(sys.modules["app_v36_offline_harness"])
else:
    import app_v36_offline_harness  # noqa: F401,E402


st.caption(
    "V3.7 OFFLINE APPTEST HARNESS · NETWORK/PROVIDER ACTIONS NOT INVOKED · "
    "OFFLINE MARKET/PROVIDER STUBS EXCLUDED FROM SCIENTIFIC EVIDENCE"
)
