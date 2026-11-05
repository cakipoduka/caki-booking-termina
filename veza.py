"""
CAKI testovi v2 — `veza.py`
Otvara Sheetove (baza zadataka + CRM). Ovo je **jedino mjesto** koje zna za vjerodajnice.

`tablice.py` zna gdje su tabovi, `veza.py` zna kako se dolazi do dokumenta.

Vjerodajnice (redom kojim se traže):
  · CRM (testovi, dodjele, pokušaji) → `GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI`, pa `GOOGLE_SERVICE_ACCOUNT_JSON`
  · baza zadataka (samo čitanje)     → `GOOGLE_SERVICE_ACCOUNT_JSON`, pa `GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI`

Zašto odvojeni račun za testove: Google kvota je **60 upisa u minuti po računu** — ako testovi pišu
kroz isti račun kao i ostatak portala, veliki test može potrošiti kvotu portala (i obrnuto).

VAŽNO (greška 25.10.2026.): `gspread.authorize()` prima **credentials objekt**, a ne dict. Za dict se
koristi `gspread.service_account_from_dict()`. Prije je kod predavao dict → `'dict' object has no
attribute 'module'`.
"""
from __future__ import annotations

import streamlit as st

import secrets_json as _sj

# kojim redom tražimo ključ tajne
KLJUCEVI_CRM = ("GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI", "GOOGLE_SERVICE_ACCOUNT_JSON")
KLJUCEVI_BAZA = ("GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI")


def odaberi_kljuc(dostupni, redoslijed) -> str:
    """Vrati prvi ključ iz `redoslijed` koji stvarno postoji u Secrets (prazan string ako nijedan).

    Izdvojeno da se može testirati bez Streamlita i bez Googlea.
    """
    ima = {str(k) for k in (dostupni or ())}
    for kljuc in redoslijed:
        if kljuc in ima:
            return kljuc
    return ""


def _dostupni_kljucevi() -> list[str]:
    try:
        return list(st.secrets.keys())
    except Exception:                                  # noqa: BLE001 — nema secrets.toml
        return []


def klijent(redoslijed=KLJUCEVI_CRM):
    """gspread klijent iz servisnog računa. Baca jasnu grešku ako nijedna tajna ne postoji."""
    kljuc = odaberi_kljuc(_dostupni_kljucevi(), redoslijed)
    if not kljuc:
        raise ValueError(
            "U Secrets nema nijedne vjerodajnice za Google. Dodaj "
            f"`{redoslijed[0]}` (ili `{redoslijed[1]}`) — JSON servisnog računa."
        )
    podaci = _sj.ucitaj(st, kljuc)                      # tolerantno: pametni navodnici, \n, =, zarezi
    from gspread import service_account_from_dict       # gspread >= 6

    return service_account_from_dict(podaci)


@st.cache_resource(show_spinner=False)
def sheet_crm():
    """CRM Sheet — testovi, dodjele, pokušaji, ocjene. Za upis: radije zaseban testni račun."""
    return klijent(KLJUCEVI_CRM).open_by_key(str(st.secrets["CRM_SHEET_ID"]))


@st.cache_resource(show_spinner=False)
def sheet_baze():
    """Baza zadataka (20.000+ zadataka) — samo čitanje."""
    return klijent(KLJUCEVI_BAZA).open_by_key(str(st.secrets["SHEET_ID"]))
