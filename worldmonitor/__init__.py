"""WorldMonitor JARVIS institutional geospatial intelligence package.

The runtime consumes versioned, precompiled assets from :mod:`worldmonitor.data`.
Reference archives are accepted only by the offline build script and are never
scanned by the Streamlit application.
"""

from .assets import asset_manifest, country_profiles, load_static_objects
from .config import MODULE_VERSION
from .engine import get_capabilities, render

__all__ = [
    "MODULE_VERSION",
    "asset_manifest",
    "country_profiles",
    "get_capabilities",
    "load_static_objects",
    "render",
]
