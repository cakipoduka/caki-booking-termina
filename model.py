"""
CAKI testovi v2 — `model.py`
Mali pomoćni sloj: pretvorbe, datumi, ID-evi.

Namjerno bez vanjskih ovisnosti (osim standardne biblioteke) da ga svaki modul može uzeti.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta


# ------------------------------------------------------------------ pretvorbe

def tekst(v) -> str:
    """Uvijek string, bez „None"/„nan" — Sheets vraća svašta."""
    s = "" if v is None else str(v)
    s = s.strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def broj(v, zadano: float = 0.0) -> float:
    """'2,5' → 2.5 · '' → zadano. Nikad ne puca."""
    s = tekst(v).replace(",", ".")
    s = re.sub(r"[^\d.\-]", "", s)
    if not s or s in ("-", ".", "-."):
        return float(zadano)
    try:
        return float(s)
    except ValueError:
        return float(zadano)


def cijeli(v, zadano: int = 0) -> int:
    return int(round(broj(v, zadano)))


def da(v) -> bool:
    """Tumači „Da/Ne", „1/0", True/False — prazno je Ne (za razliku od some Sheets polja)."""
    return tekst(v).lower() in ("da", "1", "true", "yes", "y")


def nije_ne(v) -> bool:
    """Prazno se broji kao DA — za stara polja gdje prazno znači „nije isključeno"."""
    return tekst(v).lower() not in ("ne", "0", "false", "no", "n")


def datum(v) -> date | None:
    """Pretvori bilo što u date (None ako ne može). Prihvaća `YYYY-MM-DD`, `D.M.YYYY`, ISO s vremenom."""
    s = tekst(v)
    if not s:
        return None
    s = s.replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%d.%m.%Y", "%d.%m.%Y.", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def sada() -> datetime:
    return datetime.now().replace(microsecond=0)


def sada_iso() -> str:
    return sada().strftime("%Y-%m-%d %H:%M:%S")


def iso_datum(v) -> str:
    d = datum(v)
    return d.strftime("%Y-%m-%d") if d else ""


def datum_hr(v) -> str:
    d = datum(v)
    return d.strftime("%d.%m.%Y.") if d else ""


# ------------------------------------------------------------------ JSON

def kao_json(v) -> list:
    """Lista iz JSON-a; trpi ograde, `\\u` escape i dvostruko kodiranje. Prazno = []."""
    if isinstance(v, list):
        return v
    s = tekst(v)
    if not s:
        return []
    for _ in range(3):                                  # dvostruko kodirano („\"[{...}]\"" )
        try:
            ucitano = json.loads(s)
        except (json.JSONDecodeError, TypeError):
            s2 = s.replace("\\\\", "\\")
            if s2 == s:
                return []
            s = s2
            continue
        if isinstance(ucitano, list):
            return ucitano
        if isinstance(ucitano, str):
            s = ucitano
            continue
        return []
    return []


def kao_dict(v) -> dict:
    """Dict iz JSON-a (odgovori po zadatku). Trpi dvostruko kodiranje; prazno = {}."""
    if isinstance(v, dict):
        return {str(k): x for k, x in v.items()}
    s = tekst(v)
    for _ in range(4):
        if not s:
            return {}
        try:
            ucitano = json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return {}
        if isinstance(ucitano, dict):
            return {str(k): x for k, x in ucitano.items()}
        if isinstance(ucitano, str):
            s = ucitano
            continue
        return {}
    return {}


def u_json(v) -> str:
    return json.dumps(v, ensure_ascii=False)


# ------------------------------------------------------------------ vrijeme

def minuta_tekst(minute: int) -> str:
    m = max(0, int(minute))
    if m < 60:
        return f"{m} min"
    h, ost = divmod(m, 60)
    return f"{h} h {ost:02d} min" if ost else f"{h} h"


def preostalo_tekst(rok: datetime, sada_: datetime | None = None) -> str:
    """„12 min" ili „isteklo" — za ekran rješavanja."""
    razlika = rok - (sada_ or sada())
    if razlika <= timedelta(0):
        return "isteklo"
    return minuta_tekst(int(razlika.total_seconds() // 60) + 1)


def izmedju(v, od, do) -> bool:
    """Je li `v` unutar [od, do] — None granice ne ograničavaju."""
    d = datum(v)
    if d is None:
        return False
    od_d, do_d = datum(od), datum(do)
    if od_d and d < od_d:
        return False
    if do_d and d > do_d:
        return False
    return True


# 4.11.2026. (Claude, pregled): JEDNO mjesto koje kaže je li pokušaj predan.
# provedba.py i uvoz_v1.py upisuju „predano" (ili „po_isteku"), a pojedini moduli su provjeravali
# „predan" (bez -o) → žalba na normalno predan test je bila odbijena, a „⏳ Započeli, nisu predali"
# je prikazivao i učenike koji su predali. Stari zapisi („predan", „ocjenjen") i dalje vrijede.
STATUSI_PREDANI = ("predano", "po_isteku", "ocijenjeno", "predan", "ocjenjen")


def je_predan(pokusaj_ili_status) -> bool:
    """True ako je pokušaj predan (prima redak pokušaja ili sam status)."""
    st_ = pokusaj_ili_status.get("status") if isinstance(pokusaj_ili_status, dict) else pokusaj_ili_status
    return tekst(st_).strip().lower() in STATUSI_PREDANI
