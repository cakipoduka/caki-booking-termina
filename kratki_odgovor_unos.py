"""
CAKI — kratki_odgovor_unos.py  (18.10.2026.)
Unos kratkog odgovora za online test (matura format): WYSIWYG matematičko polje preko
paketa `streamlit-mathlive` (vraća LaTeX izravno, bez OCR-a — v. MASTER_BAZA §26.2/§37),
uz fallback na čisti LaTeX tekstualni unos ako komponenta ne radi pouzdano.

RIZIK PAKETA (zapisano u TRACKER-u 18.10.2026., v. ondje za detalje): `streamlit-mathlive`
je verzija 0.0.3, zadnje izdanje 3.9.2025., samo 1 GitHub star/fork/watcher — slab signal
održavanja za nešto na čemu će učenici upisivati odgovore za maturu. Zato POSTOJI fallback
(parametar `koristi_mathlive=False`) i zato je potrebna Cakijeva vizualna provjera
(`_demo_mathlive.py`) PRIJE nego ovo ide u stvarnu stranicu za rješavanje testa (task #4).

Ne dira pipeline_upisi.py niti druge portal datoteke — samostalan modul, bez Sheet pristupa.
"""
from __future__ import annotations

import streamlit as st

try:
    from st_mathlive import mathfield
except ImportError:
    mathfield = None   # paket nije instaliran — kod svejedno radi, samo preko fallbacka


def kratki_odgovor_unos(label: str, key: str, vrijednost_latex: str = "",
                        koristi_mathlive: bool = True) -> str:
    """Prikaže polje za unos kratkog odgovora i vrati upisano kao LaTeX string
    (prazan string ako još ništa nije upisano).

    `koristi_mathlive=False` prisilno koristi čisti tekstualni fallback (npr. ako se
    Cakijevom provjerom u `_demo_mathlive.py` pokaže da WYSIWYG komponenta ne radi
    pouzdano na Streamlit Cloudu). Isto se događa automatski ako paket nije instaliran
    ili ako poziv komponente baci iznimku — učenik svejedno može odgovoriti, samo bez
    vizualne tipkovnice.
    """
    if koristi_mathlive and mathfield is not None:
        try:
            rezultat = mathfield(title=label, value=vrijednost_latex, key=key)
        except Exception:
            rezultat = None
        else:
            tex, _mathml = rezultat if rezultat else (None, None)
            return tex or ""
    return st.text_input(f"{label} — upiši LaTeX (npr. \\frac{{1}}{{2}})",
                         value=vrijednost_latex, key=f"{key}_fallback")
