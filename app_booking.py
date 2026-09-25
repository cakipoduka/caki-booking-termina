"""
CAKI — app_booking.py  (glavna adresa portala, link iz maila: ...streamlit.app/?ucenik_id=AB1234)

26.9.2026.: booking i Moj CAKI spojeni u JEDAN portal s karticama (portal_ui.py):
odabir termina, raspored, dolasci, instrukcije, plaćanja, rezultati.
Stari linkovi .../Moj_CAKI?ucenik_id=... i dalje rade (pages/1_Moj_CAKI.py prikazuje isto).
"""
import streamlit as st

# Streamlit Cloud nakon git pulla zna zadržati STARU verziju modula u memoriji
# (→ ImportError "cannot import name"). Ako je datoteka novija od učitanog modula, učitaj je ponovno.
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
