"""
CAKI testovi v2 — `zalbe.py`
⚖️ ŽALBA NA OCJENU — učenik traži provjeru, profesor odgovara (Cakijeva odluka 31.10.2026.).

**Rok: 5 dana** od dana kad je rezultat postao vidljiv (`ROK_DANA = 5`).

Tijek:
  1. učenik podnosi žalbu na **jedan zadatak** (`podnesi`) — samo nakon predaje i unutar roka,
  2. profesor **prihvaća** ili **odbija** (`odgovori`),
  3. prihvaćena žalba → `provedba.ocijeni_rucno(..., povod="zalba")` → **trag u `Izmjene_ocjena`**
     (korak 2), pa se vidi tko je i zašto promijenio ocjenu.

Shema (`Zalbe`):
    zalba_id · pokusaj_id · zadatak_id · ucenik_id · podnesena · razlog ·
    status · odgovor · tko_odgovorio · odgovoreno · rok_do
"""
from __future__ import annotations

import model
import tablice

TAB_ZALBE = "Zalbe"

ZAGLAVLJE = [
    "zalba_id", "pokusaj_id", "zadatak_id", "ucenik_id", "podnesena", "razlog",
    "status", "odgovor", "tko_odgovorio", "odgovoreno", "rok_do",
]

ROK_DANA = 5                                   # Caki, 31.10.2026.

STATUS_PODNESENA = "podnesena"
STATUS_PRIHVACENA = "prihvacena"
STATUS_ODBIJENA = "odbijena"


def _svi(sheet) -> list[dict]:
    try:
        return tablice.ucitaj(sheet, TAB_ZALBE) or []
    except Exception:                                   # noqa: BLE001
        return []


def rok_do(predano_kada, *, dana: int = ROK_DANA) -> str:
    """Datum do kojeg se može podnijeti žalba (ISO) — 5 dana od vidljivosti rezultata."""
    from datetime import date, datetime, timedelta

    if not model.tekst(predano_kada):
        return ""
    tekst = model.tekst(predano_kada)[:10]
    for obrazac in ("%Y-%m-%d", "%d.%m.%Y.", "%d.%m.%Y"):
        try:
            d = datetime.strptime(tekst, obrazac).date()
            return (d + timedelta(days=dana)).isoformat()
        except ValueError:
            continue
    return (date.today() + timedelta(days=dana)).isoformat()


def _danas(sada=None):
    from datetime import date, datetime

    if sada is None:
        return date.today()
    if isinstance(sada, datetime):
        return sada.date()
    if isinstance(sada, date):
        return sada
    try:
        return datetime.fromisoformat(model.tekst(sada)[:10]).date()
    except ValueError:
        return date.today()


def moze_podnijeti(sheet, pokusaj: dict, zadatak_id: str, *, sada=None) -> tuple[bool, str]:
    """Smije li se sada podnijeti žalba na taj zadatak? Vraća (smije, razlog)."""
    if not model.je_predan(pokusaj or {}):   # 4.11.: prije nije prihvaćao „predano"
        return False, "Žalba se podnosi nakon predaje testa."
    zid = model.tekst(zadatak_id)
    if not zid:
        return False, "Nedostaje zadatak."
    pid = model.tekst(pokusaj.get("pokusaj_id"))

    for z in _svi(sheet):
        if (model.tekst(z.get("pokusaj_id")) == pid
                and model.tekst(z.get("zadatak_id")) == zid
                and model.tekst(z.get("status")) == STATUS_PODNESENA):
            return False, "Žalba za taj zadatak je već podnesena i čeka odgovor."

    do = model.tekst(pokusaj.get("rok_zalbe")) or rok_do(pokusaj.get("predaja"))
    if do:
        try:
            from datetime import date

            if _danas(sada) > date.fromisoformat(do[:10]):
                return False, f"Rok za žalbu je istekao ({model.datum_hr(do)})."
        except ValueError:
            pass
    return True, "Može se podnijeti."


def podnesi(sheet, *, pokusaj: dict, zadatak_id: str, razlog: str,
            ucenik_id: str = "", sada=None) -> dict:
    """Podnesi žalbu. Baca `ValueError` s razlogom ako nije dopušteno."""
    smije, razlog_odbijanja = moze_podnijeti(sheet, pokusaj, zadatak_id, sada=sada)
    if not smije:
        raise ValueError(razlog_odbijanja)
    izmjene = [model.tekst(z.get("zalba_id")) for z in _svi(sheet)]
    red = {
        "zalba_id": tablice.novi_id(izmjene, "Z26-"),
        "pokusaj_id": model.tekst(pokusaj.get("pokusaj_id")),
        "zadatak_id": model.tekst(zadatak_id),
        "ucenik_id": model.tekst(ucenik_id) or model.tekst(pokusaj.get("ucenik_id")),
        "podnesena": model.sada_iso(),
        "razlog": model.tekst(razlog),
        "status": STATUS_PODNESENA,
        "odgovor": "",
        "tko_odgovorio": "",
        "odgovoreno": "",
        "rok_do": model.tekst(pokusaj.get("rok_zalbe")) or rok_do(pokusaj.get("predaja")),
    }
    tablice.dodaj(sheet, TAB_ZALBE, [red])
    return red


def odgovori(sheet, zalba_id: str, *, prihvati: bool, odgovor: str = "",
             tko: str = "") -> bool:
    """Profesor odgovara na žalbu. Vraća True ako je zapisano."""
    zid = model.tekst(zalba_id)
    for z in _svi(sheet):
        if model.tekst(z.get("zalba_id")) != zid:
            continue
        return bool(tablice.azuriraj(sheet, TAB_ZALBE, "zalba_id", zid, {
            "status": STATUS_PRIHVACENA if prihvati else STATUS_ODBIJENA,
            "odgovor": model.tekst(odgovor),
            "tko_odgovorio": model.tekst(tko),
            "odgovoreno": model.sada_iso(),
        }))
    return False


def za_pokusaj(sheet, pokusaj_id: str) -> list[dict]:
    pid = model.tekst(pokusaj_id)
    return [z for z in _svi(sheet) if model.tekst(z.get("pokusaj_id")) == pid]


def otvorene(sheet) -> list[dict]:
    """Žalbe koje čekaju profesorov odgovor."""
    return [z for z in _svi(sheet) if model.tekst(z.get("status")) == STATUS_PODNESENA]


def prihvati_i_ispravi(sheet, zalba_id: str, *, tocno: bool, bodovi=None,
                       obrazlozenje: str = "", profesor: str = "") -> bool:
    """Prihvati žalbu **i** ispravi ocjenu — trag ide u `Izmjene_ocjena` (povod `zalba`)."""
    import provedba

    zid = model.tekst(zalba_id)
    zalba = next((z for z in _svi(sheet) if model.tekst(z.get("zalba_id")) == zid), None)
    if not zalba:
        return False
    ok = provedba.ocijeni_rucno(
        sheet, model.tekst(zalba.get("pokusaj_id")), model.tekst(zalba.get("zadatak_id")),
        tocno=tocno, bodovi=bodovi, komentar=obrazlozenje or "žalba prihvaćena",
        profesor=profesor or "caki", povod="zalba")
    if ok:
        odgovori(sheet, zid, prihvati=True, odgovor=obrazlozenje, tko=profesor or "caki")
    return ok


def osiguraj(sheet) -> bool:
    try:
        tablice.osiguraj(sheet, TAB_ZALBE)
        return True
    except Exception:                                   # noqa: BLE001
        return False
