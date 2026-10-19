"""
CAKI — _demo_mathlive.py  (18.10.2026.)
PROLAZNA demo stranica — SAMO za Cakijevu vizualnu provjeru `kratki_odgovor_unos.py`
prije nego ide u stvarnu stranicu za rješavanje testa (task #4). Nije dio portala,
ne povezuje se iz izbornika, briše se nakon provjere.

Pokreni lokalno:  streamlit run _demo_mathlive.py
Provjeri:
  1. Vidi li se matematička tipkovnica/polje (ne samo prazan pravokutnik).
  2. Upiši npr. "x^2+1" preko tipkovnice ili inputa — pokazuje li se ispod kao LaTeX?
  3. Isključi "Koristi MathLive" kvačicu — pojavljuje li se čisti tekstualni unos umjesto?
  4. Ako vidiš grešku/prazninu umjesto matematičkog polja: paket `streamlit-mathlive`
     nije pouzdan za ovu primjenu — javi, prelazimo trajno na fallback (čisti LaTeX unos).
"""
import streamlit as st

from kratki_odgovor_unos import kratki_odgovor_unos

st.title("Demo: unos kratkog odgovora")

koristi_mathlive = st.checkbox("Koristi MathLive (WYSIWYG)", value=True)

odgovor = kratki_odgovor_unos("Zadatak 1: Riješi jednadžbu x² + 1 = 0", key="demo1",
                              koristi_mathlive=koristi_mathlive)

st.write("**Upisani LaTeX:**", repr(odgovor))
if odgovor:
    st.latex(odgovor)
