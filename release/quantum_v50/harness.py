"""Standalone Streamlit harness for the V5.0 control plane."""

from __future__ import annotations

import streamlit as st

from quantum_research_lab.v50.ui import load_v50_ui_artifact, render_v50_control_plane


def _section_header(title: str, kicker: str, copy: str) -> None:
    st.caption(kicker)
    st.header(title)
    st.write(copy)


st.set_page_config(page_title="Quantum Lab V5.0", layout="wide")
st.title("Quantum Lab · V5.0 Verification Harness")
artifact, integrity = load_v50_ui_artifact()
render_v50_control_plane(
    _section_header,
    artifact=artifact,
    integrity=integrity.get("valid") is True,
    key_prefix="v50_harness",
)
if integrity.get("errors"):
    st.code("\n".join(str(item) for item in integrity["errors"]))
