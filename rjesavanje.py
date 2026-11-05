"""
CAKI testovi v2 — `rjesavanje.py`
LOGIKA EKRANA RJEŠAVANJA (bez Streamlita — zato se testira).

Ovdje je ono što se u starom sustavu nije moglo:
  · pitanje po pitanju, s napretkom i „vrati se na prethodno"
  · **autosave** — odgovori se pamte čim nastanu, prekid ih ne briše
  · **predaja s upozorenjem** — točno piše koliko je odgovoreno, a koliko prazno
  · **povratna informacija po Student View-u** — rješenja i 🎬 video tek kad smiju
"""
from __future__ import annotations

import model
import ocjenjivanje


# ------------------------------------------------------------------ napredak

def napredak(zadaci: list[dict], odgovori: dict) -> dict:
    """Koliko je odgovoreno, koliko prazno, koliko bodova „nosi" ono što je upisano."""
    odg = {str(k): v for k, v in (odgovori or {}).items()}
    ukupno = len(zadaci or [])
    odgovoreno = 0
    for i in range(ukupno):
        if model.tekst(odg.get(str(i))):
            odgovoreno += 1
    return {
        "ukupno": ukupno,
        "odgovoreno": odgovoreno,
        "prazno": ukupno - odgovoreno,
        "postotak": int(round(100 * odgovoreno / ukupno)) if ukupno else 0,
        "tekst": f"{odgovoreno} / {ukupno} odgovoreno",
    }


def stanje_pitanja(zadaci: list[dict], odgovori: dict) -> list[str]:
    """Za popis pitanja: `odgovoreno` · `prazno`."""
    odg = {str(k): v for k, v in (odgovori or {}).items()}
    return ["odgovoreno" if model.tekst(odg.get(str(i))) else "prazno"
            for i in range(len(zadaci or []))]


def oznaka_pitanja(index: int, stanja: list[str]) -> str:
    """Kratka oznaka za navigaciju: „3 ✓" ili „4 ·”."""
    stanje = stanja[index] if 0 <= index < len(stanja) else "prazno"
    return f"{index + 1} " + ("✓" if stanje == "odgovoreno" else "·")


def sljedeci(index: int, ukupno: int, smjer: int = 1) -> int:
    """Sljedeće/prethodno pitanje, unutar granica."""
    if ukupno <= 0:
        return 0
    return max(0, min(ukupno - 1, index + smjer))


# ------------------------------------------------------------------ predaja

def sto_nedostaje(zadaci: list[dict], odgovori: dict) -> dict:
    """Što učenik mora znati prije predaje (umjesto skoka u prazno)."""
    n = napredak(zadaci, odgovori)
    if n["prazno"] == 0:
        return {"moze": True, "poruka": "Svi zadaci imaju odgovor.", **n}
    return {
        "moze": False,
        "poruka": (f"**{n['prazno']}** od **{n['ukupno']}** zadataka nema odgovor. "
                   f"Možeš predati i sada — prazni zadaci nose 0 bodova."),
        **n,
    }


def sazetak_predaje(zadaci: list[dict], odgovori: dict) -> list[str]:
    """Redci za dijalog predaje: broj pitanja, je li odgovoreno."""
    odg = {str(k): v for k, v in (odgovori or {}).items()}
    redci = []
    for i, z in enumerate(zadaci or []):
        odgovor = model.tekst(odg.get(str(i)))
        redci.append(f"{i + 1}. " + ("✅ odgovoreno" if odgovor else "⬜ prazno"))
    return redci


# ------------------------------------------------------------------ rezultat i povratna informacija

def rezultat_tekst(bodovi, maks, postotak=None) -> str:
    b, m = model.broj(bodovi), model.broj(maks)
    p = postotak if postotak is not None else ocjenjivanje.postotak(b, m)
    return f"{b:g} / {m:g} bodova ({p} %)"


def sto_vidi_ucenik(student_view, *, predano: bool, rok_prosao: bool) -> dict:
    """Što se smije prikazati nakon rješavanja (v. `definicije.smije_vidjeti`)."""
    import definicije

    return {
        resurs: definicije.smije_vidjeti(student_view, resurs, predano=predano, rok_prosao=rok_prosao)
        for resurs in definicije.RESURSI
    }


def pregled_zadatka(zadatak: dict, odgovor: str, *,
                    pokazi_rjesenje: bool, pokazi_video: bool, pokazi_bodove: bool,
                    izvor_ocjene: str = "") -> dict:
    """Jedan redak pregleda nakon predaje — poštuje Student View.

    🎬 Video se prikazuje **samo** ako je rješenje dopušteno (ne može se video vidjeti prije
    rješenja — inače bi bio zaobilazni put do odgovora).
    """
    import banka

    tocan = model.tekst((zadatak or {}).get("odgovor"))
    moj = model.tekst(odgovor)
    video = banka.video_za(zadatak) if pokazi_video else None
    return {
        "tekst": model.tekst((zadatak or {}).get("tekst")),
        "moj_odgovor": moj,
        "tocan_odgovor": tocan if pokazi_rjesenje else "",
        "pokazi_rjesenje": bool(pokazi_rjesenje),
        "video": video if pokazi_rjesenje else None,
        "pokazi_video": bool(pokazi_video and pokazi_rjesenje),
        "pokazi_bodove": bool(pokazi_bodove),
        "izvor_ocjene": model.tekst(izvor_ocjene),
        "ceka_profesora": model.tekst(izvor_ocjene) == "?",
    }


def poruka_o_cekanju(broj: int) -> str:
    """Kad ocjena nije mogla biti automatska — učenik ne smije vidjeti lažnu nulu."""
    if broj <= 0:
        return ""
    if broj == 1:
        return "1 zadatak čeka provjeru profesora — rezultat je privremen."
    return f"{broj} zadataka čekaju provjeru profesora — rezultat je privremen."


# ------------------------------------------------------------------ prikaz teksta

def pripremi_latex(tekst, zamotaj: bool = False) -> str:
    r"""LaTeX iz baze → oblik koji Streamlit prikazuje.

    `\(…\)` i `\[…\]` pretvaraju se u `$…$` / `$$…$$` (tako je zapisano u bazi).

    `zamotaj=True` (preuzeto iz portala, `testovi_online.pripremi_latex`): ako tekst **nema**
    `$`, a očito je matematika (`\frac`, `^`, `_`, `\sqrt`…), umotaj ga u `$…$` — inače učenik
    vidi sirovi `\frac{1}{a^{3}+b^{3}}` umjesto razlomka.
    """
    s = model.tekst(tekst)
    if not s:
        return ""
    s = s.replace("\\(", "$").replace("\\)", "$")
    s = s.replace("\\[", "$$").replace("\\]", "$$")
    if zamotaj and "$" not in s:
        if any(znak in s for znak in ("\\", "^", "_")) or any(
                naredba in s for naredba in ("frac", "sqrt", "cdot", "alpha", "beta", "pi")):
            s = f"${s}$"
    return s
