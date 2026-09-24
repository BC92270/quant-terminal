"""Standalone Streamlit harness for the V4.9 admission surface."""

from __future__ import annotations

import streamlit as st

from quantum_research_lab.v49.ui import (
    load_v49_ui_artifact,
    render_v49_admission_panel,
)


def _section_header(title: str, kicker: str, copy: str) -> None:
    st.caption(kicker)
    st.header(title)
    st.write(copy)


st.set_page_config(page_title="Quantum Lab V4.9", layout="wide")
st.title("Quantum Lab · V4.9 Verification Harness")
artifact, integrity = load_v49_ui_artifact()
render_v49_admission_panel(
    _section_header,
    artifact=artifact,
    integrity=integrity.get("valid") is True,
    key_prefix="v49_harness",
)
if integrity.get("errors"):
    st.code("\n".join(str(item) for item in integrity["errors"]))
