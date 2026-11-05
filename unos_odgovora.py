"""
CAKI testovi v2 — `unos_odgovora.py`
Unos kratkog odgovora: WYSIWYG matematičko polje (MathLive) uz siguran fallback na tekst.

Kopija istog modula iz portala (`caki-booking-termina/kratki_odgovor_unos.py`) — drži se **identično**
da se ponašanje ne raziđe. Ako paket `streamlit-mathlive` ne radi, polje se automatski pretvori u
običan tekstualni unos (učenik nikad ne ostane bez mogućnosti upisa).

Vraća **LaTeX** string (prazan ako ništa nije upisano).
"""
from __future__ import annotations

import streamlit as st

try:
    from st_mathlive import mathfield
except Exception:                                      # noqa: BLE001 — paket nije instaliran
    mathfield = None


def dostupan() -> bool:
    """Je li MathLive dostupan u ovoj okolini (za dijagnostiku)."""
    return mathfield is not None


def unos_odgovora(label: str, key: str, vrijednost_latex: str = "",
                  koristi_mathlive: bool = True) -> str:
    """Prikaži polje i vrati upisano kao LaTeX (ili čisti tekst ako MathLive nije dostupan)."""
    if mathfield is not None and koristi_mathlive:
        try:
            rezultat = mathfield(
                value=vrijednost_latex or "",
                default_mode="math",
                key=key,
                height=90,
            )
            return str(rezultat or "").strip()
        except Exception:                              # noqa: BLE001 — komponenta pukla
            st.caption("Upiši odgovor kao tekst ili formulu (npr. `2x+1=5`).")

    return str(st.text_input(label, value=vrijednost_latex or "", key=f"{key}_tekst") or "").strip()
