"""V4.2 AppTest harness built on the frozen V4.1 offline provider spies.

Importing the predecessor harness renders the real current Quantum Lab with a
frozen BANDS fixture and fail-fast spies.  This successor adds a versioned
caption without duplicating or weakening those controls.
"""

from __future__ import annotations

from pathlib import Path
import runpy

import streamlit as st


# AppTest reruns a script in the same interpreter. ``run_path`` deliberately
# re-executes the frozen predecessor harness on every rerun; a normal import
# would be cached and the real application would disappear after the first run.
predecessor = runpy.run_path(
    str(Path(__file__).resolve().with_name("app_v41_offline_harness.py"))
)
spy_keys = predecessor["SPY_KEYS"]


st.caption(
    "V4.2 OFFLINE APPTEST HARNESS · "
    f"PROVIDER SPY CALLS · {int(st.session_state.get(spy_keys['provider'], 0))} · "
    f"TRANSPILE SPY CALLS · {int(st.session_state.get(spy_keys['transpile'], 0))} · "
    f"SEAL SPY CALLS · {int(st.session_state.get(spy_keys['seal'], 0))} · "
    "REAL SEALED V4.2 EVIDENCE · OFFLINE MARKET FIXTURES EXCLUDED FROM SCIENTIFIC EVIDENCE"
)
