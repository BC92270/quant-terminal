"""Isolated Streamlit entrypoint used for WorldMonitor visual regression tests."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worldmonitor_bridge_v211 import render_worldmonitor_bridge_v211


st.set_page_config(page_title="WorldMonitor JARVIS V8 smoke test", layout="wide")
render_worldmonitor_bridge_v211()

