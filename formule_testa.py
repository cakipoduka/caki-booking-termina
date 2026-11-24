"""
CAKI testovi v2 — `formule_testa.py`
📐 Formule uz test — preneseno iz v1 (`caki-baza-zadataka/formule.py`, 22.10.2026.), 24.11.2026.

Caki: „U ver1 smo imali opciju dodavanja formula (učitane su kroz caki-zadaci…/formule) —
treba tu opciju kopirati i u ver2 caki-testovi."

Isti model kao v1:
  · formule se i dalje UNOSE u bazi zadataka (stranica 📐 Formule, tab `Formule` u Sheetu baze),
    složene u **pakete** (npr. „Matura 2026 — službene");
  · u caki-testovi profesor uz test odabere pakete / pojedinačne formule (ili sve aktivne);
  · u test se **zamrzne kopija** (`Definicije_testova.formule_json`) — portal ne čita bazu, a
    učenik vidi točno ono što je profesor odabrao u tom trenutku;
  · učenik ih tijekom testa otvara gumbom „📐 Formule".

Datoteka je ISTA u caki-testovi i u Moj CAKI (caki-booking-termina).
"""
from __future__ import annotations

import json

import model

FORMULE_TAB = "Formule"


def _t(v) -> str:
    return model.tekst(v)


# ------------------------------------------------------------------ čitanje iz baze

def ucitaj_iz_baze(baza_sheet) -> list[dict]:
    """Svi retci taba `Formule` iz Sheeta baze zadataka ([] ako taba nema)."""
    if baza_sheet is None:
        return []
    try:
        ws = baza_sheet.worksheet(FORMULE_TAB)
        return [dict(r) for r in (ws.get_all_records() or [])]
    except Exception:                                   # noqa: BLE001 — nema taba = nema formula
        return []


# ------------------------------------------------------------------ izbor (isto kao v1)

def aktivne(formule) -> list[dict]:
    return [f for f in formule or [] if _t(f.get("aktivno")) in ("Da", "da", "")]


def paketi(formule) -> list[str]:
    """Nazivi paketa koji imaju barem jednu aktivnu formulu."""
    return sorted({_t(f.get("paket")) for f in aktivne(formule) if _t(f.get("paket"))})


def izbor_za_test(formule, paketi_odabrani=(), idovi_odabrani=(), sve: bool = False) -> list[dict]:
    """Zamrznuti retci za JEDAN test. Redoslijed iz baze; duplikati se preskaču."""
    zele = {_t(p) for p in paketi_odabrani or [] if _t(p)}
    idovi = {_t(i) for i in idovi_odabrani or [] if _t(i)}
    izlaz, vidjeno = [], set()
    for f in aktivne(formule):
        fid = _t(f.get("formula_id"))
        if not (sve or _t(f.get("paket")) in zele or fid in idovi):
            continue
        if fid in vidjeno:
            continue
        vidjeno.add(fid)
        izlaz.append({k: _t(f.get(k)) for k in
                      ("formula_id", "naslov", "cjelina", "paket", "tekst_latex", "datoteka", "opis")})
    return izlaz


def u_json(formule) -> str:
    return json.dumps(list(formule or []), ensure_ascii=False) if formule else ""


def iz_definicije(definicija) -> list[dict]:
    """Zamrznute formule iz testa (`formule_json`)."""
    sirovo = _t((definicija or {}).get("formule_json"))
    if not sirovo:
        return []
    try:
        podaci = json.loads(sirovo)
    except ValueError:
        return []
    if not isinstance(podaci, list):
        return []
    return [f for f in podaci if isinstance(f, dict)
            and (_t(f.get("tekst_latex")) or _t(f.get("datoteka")))]


def trenutni_izbor(definicija) -> tuple[list[str], list[str]]:
    """(paketi, id-jevi) koji su sada u testu — za predpopunu izbornika."""
    f = iz_definicije(definicija)
    return sorted({_t(x.get("paket")) for x in f if _t(x.get("paket"))}), \
        [_t(x.get("formula_id")) for x in f if _t(x.get("formula_id"))]


# ------------------------------------------------------------------ prikaz

def tekst_formule(formula) -> str:
    """Markdown za formulu (Streamlit renderira $…$ / $$…$$ preko KaTeX-a)."""
    latex = _t((formula or {}).get("tekst_latex"))
    if not latex:
        return ""
    return latex if "$" in latex else f"$${latex}$$"


def prikazi_popis(st, formule) -> None:
    """Formule jedna ispod druge (naslov · cjelina, pa formula ili datoteka). Nikad ne ruši test."""
    st.caption("Formule koje smiješ koristiti. Nisu rješenja — samo pravila i obrasci.")
    for f in formule or []:
        naslov, cjelina = _t(f.get("naslov")), _t(f.get("cjelina"))
        st.markdown(f"**{naslov}**" + (f" · *{cjelina}*" if cjelina else ""))
        datoteka = _t(f.get("datoteka"))
        if datoteka:
            prikazano = False
            try:
                import slike_zadataka as _sl
                if not hasattr(_sl, "prikazi_sliku_html"):
                    import slike_zadataka_v2 as _sl          # Moj CAKI: v2 kopija
                prikazano = bool(_sl.prikazi_sliku_html(st, datoteka))
            except Exception:                           # noqa: BLE001
                prikazano = False
            if not prikazano:
                st.caption(f"📄 Formula „{datoteka}” se ne prikazuje — javi profesoru.")
        elif _t(f.get("tekst_latex")):
            st.markdown(tekst_formule(f))
        if _t(f.get("opis")):
            st.caption(_t(f.get("opis")))
        st.divider()


def gumb_formule(st, definicija, *, kljuc: str = "formule") -> None:
    """Učenik tijekom testa: gumb „📐 Formule (N)" otvara popis (ništa ako formula nema)."""
    formule = iz_definicije(definicija)
    if not formule:
        return
    try:
        with st.popover(f"📐 Formule ({len(formule)})"):
            prikazi_popis(st, formule)
    except Exception:                                   # noqa: BLE001 — stariji Streamlit
        with st.expander(f"📐 Formule ({len(formule)})"):
            prikazi_popis(st, formule)
