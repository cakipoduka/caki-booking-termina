"""
CAKI testovi v2 — `radovi.py`
📷 RADOVI NA PAPIRU uz ekranski dio testa (Cakijeva odluka 24.10.2026.: „papir + ekran u istom testu").

Kako radi:
  1. učenik rješava ekranski dio (ili samo preda papir),
  2. profesor **skenira/fotografira** rad i priloži ga uz pokušaj,
  3. unos ide u Drive folder `RADOVI_FOLDER_ID` (ako je postavljen) ili se prilaže **poveznica**,
  4. profesor **potvrđuje** ocjenu papirnog dijela — do tada rad stoji kao „čeka provjeru".

Zašto poveznica, a ne samo upload: ako Drive ne dopusti upis (kvota, prava, veličina), profesor i dalje
može zalijepiti link na sken. **Nikad ne ostane bez načina** da priloži rad.

Tablica: `Radovi` (u CRM Sheetu) — jedan redak = jedan priloženi rad.
"""
from __future__ import annotations

import hashlib

import model
import tablice

TAB_RADOVI = "Radovi"
ZAGLAVLJE = ["rad_id", "pokusaj_id", "ucenik_id", "naziv", "veza", "izvor",
             "velicina_bajtova", "prilozio", "prilozeno", "potvrdjeno", "napomena"]

VRSTE = ("sken", "fotografija", "poveznica")

def osiguraj(sheet) -> None:
    """Napravi tab `Radovi` ako ga nema (samo uz uključen upis — inače `PermissionError`)."""
    tablice.osiguraj(sheet, TAB_RADOVI)


def novi_id(postojeci) -> str:
    return tablice.novi_id([model.tekst(r.get("rad_id")) for r in (postojeci or [])], "R26-")


def _veza_iz_bajtova(bajtovi: bytes) -> str:
    return hashlib.sha1(bajtovi or b"").hexdigest()[:16]


def dodaj_vezu(sheet, *, pokusaj_id: str, ucenik_id: str, veza: str, naziv: str = "",
               izvor: str = "poveznica", prilozio: str = "caki", napomena: str = "") -> dict:
    """Priloži rad preko poveznice (Drive, mobitel, skener). Ne treba upload."""
    veza = model.tekst(veza)
    if not veza:
        raise ValueError("Poveznica je prazna — zalijepi link na skenirani rad.")
    if not model.tekst(pokusaj_id):
        raise ValueError("Rad mora pripadati pokušaju (učenik + test).")
    postojeci = tablice.ucitaj(sheet, TAB_RADOVI)
    rad = {
        "rad_id": novi_id(postojeci),
        "pokusaj_id": model.tekst(pokusaj_id),
        "ucenik_id": model.tekst(ucenik_id).upper(),
        "naziv": model.tekst(naziv) or "Skenirani rad",
        "veza": veza,
        "izvor": izvor if izvor in VRSTE else "poveznica",
        "velicina_bajtova": 0,
        "prilozio": model.tekst(prilozio) or "caki",
        "prilozeno": model.sada_iso(),
        "potvrdjeno": "",
        "napomena": model.tekst(napomena),
    }
    tablice.dodaj(sheet, TAB_RADOVI, [rad])
    return rad


def dodaj_upload(sheet, *, pokusaj_id: str, ucenik_id: str, sadrzaj: bytes, naziv: str,
                 veza: str = "", prilozio: str = "caki") -> dict:
    """Priloži rad iz uploadanog skena. `veza` je Drive poveznica koju vrati pozivatelj."""
    if not sadrzaj:
        raise ValueError("Datoteka je prazna.")
    postojeci = tablice.ucitaj(sheet, TAB_RADOVI)
    rad = {
        "rad_id": novi_id(postojeci),
        "pokusaj_id": model.tekst(pokusaj_id),
        "ucenik_id": model.tekst(ucenik_id).upper(),
        "naziv": model.tekst(naziv) or "Skenirani rad",
        "veza": model.tekst(veza),
        "izvor": "sken",
        "velicina_bajtova": len(sadrzaj),
        "prilozio": model.tekst(prilozio) or "caki",
        "prilozeno": model.sada_iso(),
        "potvrdjeno": "",
        "napomena": "",
    }
    tablice.dodaj(sheet, TAB_RADOVI, [rad])
    return rad


def _svi(sheet) -> list[dict]:
    """Svi radovi; prazno ako tab još ne postoji (prvi put)."""
    try:
        return tablice.ucitaj(sheet, TAB_RADOVI)
    except Exception:                                  # noqa: BLE001 — taba još nema
        return []


def za_pokusaj(sheet, pokusaj_id: str) -> list[dict]:
    ids = model.tekst(pokusaj_id)
    return [r for r in _svi(sheet) if model.tekst(r.get("pokusaj_id")) == ids]


def za_ucenika(sheet, ucenik_id: str) -> list[dict]:
    ids = model.tekst(ucenik_id).upper()
    return [r for r in _svi(sheet) if model.tekst(r.get("ucenik_id")) == ids]


def potvrdi(sheet, rad_id: str, *, profesor: str = "caki", napomena: str = "") -> bool:
    """Profesor potvrđuje da je papirni dio pregledan (jedan upis, bez prepisivanja ocjene)."""
    return tablice.azuriraj(sheet, TAB_RADOVI, "rad_id", model.tekst(rad_id), {
        "potvrdjeno": model.sada_iso(),
        "prilozio": model.tekst(profesor) or "caki",
        "napomena": model.tekst(napomena),
    })


def sef_datoteke(naziv: str) -> str:
    """Sigurno ime datoteke za Drive (bez kvačica, razmaka i znakova koji smetaju)."""
    osnova = model.tekst(naziv) or "rad"
    zamjene = {"č": "c", "ć": "c", "ž": "z", "š": "s", "đ": "d",
               "Č": "C", "Ć": "C", "Ž": "Z", "Š": "S", "Đ": "D"}
    for lose, dobro in zamjene.items():
        osnova = osnova.replace(lose, dobro)
    ocisceno = "".join(z if (z.isalnum() or z in "._-") else "_" for z in osnova)
    return ocisceno[:80] or "rad"


def stanje(radovi) -> str:
    """Kratak sažetak za prikaz: koliko radova, koliko čeka potvrdu."""
    radovi = list(radovi or [])
    if not radovi:
        return "bez priloženog rada"
    ceka = sum(1 for r in radovi if not model.tekst(r.get("potvrdjeno")))
    if ceka == 0:
        return f"{len(radovi)} rad(a) — pregledano"
    return f"{len(radovi)} rad(a) — **{ceka} čeka potvrdu**"


# ------------------------------------------------------------------ prilog učenika (iz portala)

def dodaj_ucenikov_rad(sheet, *, pokusaj_id: str, ucenik_id: str, veza: str = "",
                       sadrzaj: bytes | None = None, naziv: str = "") -> dict:
    """Učenik sam prilaže svoj rad (doma, mobitelom ili skenerom).

    Dva načina, oba dopuštena:
      · `veza` — poveznica na fotografiju/sken (najčešće s mobitela),
      · `sadrzaj` — datoteka koju je učenik upravo poslao kroz portal.

    Rad je odmah uz pokušaj, ali **nije pregledan** — profesor ga potvrđuje u Rezultatima.
    """
    if not model.tekst(pokusaj_id):
        raise ValueError("Rad mora pripadati pokušaju (učenik + test).")
    if sadrzaj:
        return dodaj_upload(sheet, pokusaj_id=pokusaj_id, ucenik_id=ucenik_id,
                            sadrzaj=sadrzaj, naziv=naziv or "Učenikov rad",
                            veza=veza, prilozio=model.tekst(ucenik_id).upper())
    return dodaj_vezu(sheet, pokusaj_id=pokusaj_id, ucenik_id=ucenik_id, veza=veza,
                      naziv=naziv or "Učenikov rad", izvor="fotografija",
                      prilozio=model.tekst(ucenik_id).upper())
