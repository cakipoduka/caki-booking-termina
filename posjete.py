"""
CAKI testovi v2 — `posjete.py`
👀 PRAĆENJE PRISTUPA UČENIKA portal (Cakijev zahtjev 26.10.2026.).

Zašto: Caki dodjeljuje testove i šalje informacije, ali ne zna **je li učenik uopće otvorio portal**.
Ovaj modul bilježi posjete — dovoljno da se vidi „prati li", a ne toliko da bude nadzor.

VAŽNO (kvota): Google dopušta ~60 upisa u minuti. Zato se posjeta upisuje **jednom po sesiji**
(`biljeska_jednom` + zastavica u sesiji), a ne pri svakom osvježenju stranice. Inače bi jedan učenik
koji pritisne F5 deset puta potrošio kvotu cijele aplikacije.

Tablica: `Posjete` — jedan redak = jedna zabilježena radnja.
"""
from __future__ import annotations

import model
import tablice

TAB_POSJETE = "Posjete"
ZAGLAVLJE = ["posjeta_id", "ucenik_id", "kad", "radnja", "detalj", "naprava"]

RADNJE = {"posjeta": "otvorio portal", "test": "otvorio test", "predaja": "predao test",
          "rad": "priložio rad"}


def _sve(sheet) -> list[dict]:
    try:
        return tablice.ucitaj(sheet, TAB_POSJETE)
    except Exception:                                  # noqa: BLE001 — taba još nema
        return []


def novi_id(postojeci) -> str:
    return tablice.novi_id([model.tekst(r.get("posjeta_id")) for r in (postojeci or [])], "V26-")


def zabiljezi(sheet, *, ucenik_id: str, radnja: str = "posjeta", detalj: str = "",
              naprava: str = "") -> dict | None:
    """Upiši jednu posjetu/radnju. Bez učenika ne piše ništa (ne troši kvotu uzalud)."""
    ucenik = model.tekst(ucenik_id).upper()
    if not ucenik:
        return None
    radnja = radnja if radnja in RADNJE else "posjeta"
    red = {
        "posjeta_id": novi_id(_sve(sheet)),
        "ucenik_id": ucenik,
        "kad": model.sada_iso(),
        "radnja": radnja,
        "detalj": model.tekst(detalj)[:120],
        "naprava": model.tekst(naprava)[:40],
    }
    tablice.dodaj(sheet, TAB_POSJETE, [red])
    return red


def biljeska_jednom(st, sheet, *, ucenik_id: str, radnja: str = "posjeta",
                    detalj: str = "", naprava: str = "") -> bool:
    """Zabilježi **jednom po sesiji** (štiti Google kvotu). Vraća je li upisano.

    Ključ u sesiji: `v2p_<radnja>_<detalj>` — npr. posjeta se upiše pri prijavi, a otvaranje
    pojedinog testa samo prvi put.
    """
    kljuc = f"v2p_{radnja}_{model.tekst(detalj)[:40]}"
    if st.session_state.get(kljuc):
        return False
    try:
        zabiljezi(sheet, ucenik_id=ucenik_id, radnja=radnja, detalj=detalj, naprava=naprava)
    except Exception:                                  # noqa: BLE001 — praćenje ne smije blokirati
        return False
    st.session_state[kljuc] = True
    return True


# ------------------------------------------------------------------ pregled za profesora

def za_ucenika(sheet, ucenik_id: str) -> list[dict]:
    ucenik = model.tekst(ucenik_id).upper()
    return [r for r in _sve(sheet) if model.tekst(r.get("ucenik_id")) == ucenik]


def sazetak(sheet) -> dict:
    """Po učeniku: koliko posjeta, koliko testova otvoreno, kad je zadnji put bio."""
    izlaz: dict[str, dict] = {}
    for r in _sve(sheet):
        ucenik = model.tekst(r.get("ucenik_id"))
        if not ucenik:
            continue
        red = izlaz.setdefault(ucenik, {"ucenik_id": ucenik, "posjeta": 0, "testova": 0,
                                        "predaja": 0, "radova": 0, "zadnji": ""})
        radnja = model.tekst(r.get("radnja"))
        if radnja == "test":
            red["testova"] += 1
        elif radnja == "predaja":
            red["predaja"] += 1
        elif radnja == "rad":
            red["radova"] += 1
        else:
            red["posjeta"] += 1
        kad = model.tekst(r.get("kad"))
        if kad > red["zadnji"]:
            red["zadnji"] = kad
    return izlaz


def redak_za_prikaz(red: dict) -> str:
    """Kratka rečenica za tablicu: „3 posjete · 2 testa · zadnji 25.10. 19:14"."""
    dijelovi = [f"{red.get('posjeta', 0)} posjeta"]
    if red.get("testova"):
        dijelovi.append(f"{red['testova']} testova otvoreno")
    if red.get("predaja"):
        dijelovi.append(f"{red['predaja']} predaja")
    if red.get("radova"):
        dijelovi.append(f"{red['radova']} radova")
    if red.get("zadnji"):
        dijelovi.append("zadnji " + model.tekst(red["zadnji"])[:16])
    return " · ".join(dijelovi)


def naprava_iz_upita(user_agent: str) -> str:
    """Gruba oznaka naprave (mobitel/tablet/računalo) — dovoljno za „odakle piše"."""
    ua = model.tekst(user_agent).lower()
    if not ua:
        return ""
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if "mobi" in ua or "android" in ua or "iphone" in ua:
        return "mobitel"
    return "računalo"
