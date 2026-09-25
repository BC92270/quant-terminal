"""Isolated local renderer for Market Intelligence visual validation."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from market_intelligence import render_market_intelligence_lab


st.set_page_config(page_title="Market Intelligence · Quant Terminal", layout="wide")
render_market_intelligence_lab(ticker="NVDA", price_data=None, analysis=None)
