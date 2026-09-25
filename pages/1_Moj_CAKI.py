"""
CAKI — pages/1_Moj_CAKI.py
Stari linkovi (.../Moj_CAKI?ucenik_id=AB1234) i dalje rade — prikazuju ISTI portal kao
glavna stranica (portal_ui.py). Od 26.9.2026. booking i Moj CAKI su jedan portal.
"""
import streamlit as st

import importlib, os, time  # noqa: E401,E402
import pipeline_upisi as _pipeline  # noqa: E402
if os.path.getmtime(_pipeline.__file__) > getattr(_pipeline, "_ucitano_u", 0):
    importlib.reload(_pipeline)
    _pipeline._ucitano_u = time.time()
import portal_ui as _portal  # noqa: E402
if os.path.getmtime(_portal.__file__) > getattr(_portal, "_ucitano_u", 0) or \
        getattr(_portal, "_pipeline_u", 0) != getattr(_pipeline, "_ucitano_u", 0):
    importlib.reload(_portal)
    _portal._ucitano_u = time.time()
    _portal._pipeline_u = getattr(_pipeline, "_ucitano_u", 0)

st.set_page_config(page_title="Moj CAKI", page_icon="📘", layout="centered")
_portal.prikazi_portal()
