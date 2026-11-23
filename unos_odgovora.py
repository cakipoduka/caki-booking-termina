"""
CAKI testovi v2 — `unos_odgovora.py`
Unos kratkog odgovora: WYSIWYG matematičko polje (MathLive) uz siguran fallback na tekst.

Kopija istog modula iz portala (`caki-booking-termina/kratki_odgovor_unos.py`) — drži se **identično**
da se ponašanje ne raziđe. Ako paket `streamlit-mathlive` ne radi, polje se automatski pretvori u
običan tekstualni unos (učenik nikad ne ostane bez mogućnosti upisa).

Vraća **LaTeX** string (prazan ako ništa nije upisano).

POPRAVAK 21.11.2026. — „učenici ne vide MathML editor":
  Paket `streamlit-mathlive==0.0.3` ima potpis
      mathfield(title, value, enable_edit, upright, mathml_preview, key)
  a stari kod ga je zvao s `default_mode=` i `height=`. Tih argumenata nema → `TypeError` →
  `except` ga je tiho progutao i SVAKI put pokazao obično tekstualno polje. Editor se zato nikad
  nije pojavio. Sada se šalju samo argumenti koje funkcija stvarno prima (`_poziv_argumenti`).

  Druga greška iz istog mjesta: komponenta vraća PAR `[latex, mathml]` (prije prvog upisa
  `[None, None]`), a kod je radio `str(rezultat)` — u bazu bi išao tekst „[None, None]".
  Sada `_latex_iz_rezultata` uzima samo LaTeX. Kad komponenta još nije ništa javila (None),
  vraća se postojeći odgovor — inače bi povratak na već odgovoreno pitanje obrisao odgovor.
"""
from __future__ import annotations

import inspect

import streamlit as st

try:
    from st_mathlive import mathfield
except Exception:                                      # noqa: BLE001 — paket nije instaliran
    mathfield = None


def dostupan() -> bool:
    """Je li MathLive dostupan u ovoj okolini (za dijagnostiku)."""
    return mathfield is not None


def _poziv_argumenti(funkcija, vrijednost_latex: str, key: str) -> dict:
    """Složi argumente za `mathfield` — samo one koje ta verzija paketa prima.

    Zašto ovako, a ne izravno: različite verzije `streamlit-mathlive` imaju različite argumente.
    Ako pošaljemo nepostojeći, Python baci `TypeError` i polje nestane (to je bila greška).
    """
    zeljeni = {
        "title": "",
        "value": vrijednost_latex or "",
        "key": key,
        # novije verzije (ako se paket ikad nadogradi):
        "default_mode": "math",
        "height": 90,
    }
    try:
        parametri = inspect.signature(funkcija).parameters
    except (TypeError, ValueError):                    # ne može se pročitati potpis
        return {"value": vrijednost_latex or "", "key": key}
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in parametri.values()):
        return zeljeni
    return {k: v for k, v in zeljeni.items() if k in parametri}


def _latex_iz_rezultata(rezultat, prethodno: str) -> str:
    """Izvuci LaTeX iz onoga što komponenta vrati.

    `streamlit-mathlive` 0.0.3 vraća `[latex, mathml]`; prije prvog upisa `[None, None]`.
    Neke verzije vraćaju samo string. `None` znači „komponenta još nije ništa javila" → zadrži
    ono što je već bilo upisano (inače bi se pri povratku na pitanje odgovor izbrisao).
    """
    if isinstance(rezultat, (list, tuple)):
        rezultat = rezultat[0] if rezultat else None
    if rezultat is None:
        return str(prethodno or "").strip()
    return str(rezultat).strip()


def unos_odgovora(label: str, key: str, vrijednost_latex: str = "",
                  koristi_mathlive: bool = True) -> str:
    """Prikaži polje i vrati upisano kao LaTeX (ili čisti tekst ako MathLive nije dostupan)."""
    if mathfield is not None and koristi_mathlive:
        try:
            if label:
                st.markdown(f"**{label}**")
            rezultat = mathfield(**_poziv_argumenti(mathfield, vrijednost_latex, key))
            return _latex_iz_rezultata(rezultat, vrijednost_latex)
        except Exception:                              # noqa: BLE001 — komponenta pukla
            st.caption("Upiši odgovor kao tekst ili formulu (npr. `2x+1=5`).")

    return str(st.text_input(label, value=vrijednost_latex or "", key=f"{key}_tekst") or "").strip()
