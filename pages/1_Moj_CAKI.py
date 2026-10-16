"""
CAKI — pages/1_Moj_CAKI.py
Stari linkovi (.../Moj_CAKI?ucenik_id=AB1234) i dalje rade — prikazuju ISTI portal kao
glavna stranica (portal_ui.py). Od 26.9.2026. booking i Moj CAKI su jedan portal.

15.10.2026. (nalaz 16): uklonjena je zaobilaznica koja je rucno ponovno ucitavala module.
Postojala je jer je Streamlit Cloud nakon git pulla znao zadrzati staru verziju modula u
memoriji (ImportError "cannot import name"). Radni postupak ionako ukljucuje rucni
"Reboot app" nakon svakog Pusha, a reboot podize novi proces i ucitava svjeze module --
pa zaobilaznica nema sto rijesiti. Ako se ImportError ipak vrati, vrati staru verziju
iz gita (Discard / revert) i javi: znacilo bi da reboot ne radi ono sto mislimo.
"""
import streamlit as st

import portal_ui as _portal

st.set_page_config(page_title="Moj CAKI", page_icon="📘", layout="centered")
_portal.prikazi_portal()
