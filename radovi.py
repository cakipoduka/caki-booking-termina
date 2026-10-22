"""
CAKI — radovi.py  (22.10.2026.)

📷 **Slike/skenovi rada učenika na papiru** — učenik nakon predaje pošalje fotografije ili PDF
sken svog rada; datoteke idu na Drive (`RADOVI_FOLDER_ID`), a u CRM Sheet se upiše redak u tab
`Radovi` s ID-em datoteke (za pregled bez downloadanja).

Zašto zaseban modul: portal (`caki-booking-termina`) i baza koriste isti tab, a logika uploada
mora raditi bez ikakvog novog paketa — `requests` + token iz `slike_zadataka`.

Tvrdi podaci (tab `Radovi`): rad_id, test_id, ucenik_id, file_id, naziv, vrsta, velicina,
kreirano, status, link.

Cakijeva pravila (22.10.2026.): primamo **JPG i PDF (sken)**, učenik dobije uputu da piše uredno
i skenira; šalje se **samo za testove koje Caki označi** (`rad` = Da); briše se **7 dana** nakon
predaje ili na kraju školske godine.
"""
from __future__ import annotations

import json
import secrets as _secrets
import string
from datetime import date, datetime, timedelta

import requests

from slike_zadataka import SA_SEKRET, SA_SEKRET_TESTOVI, token

RADOVI_TAB = "Radovi"
RADOVI_HEADERS = ["rad_id", "test_id", "ucenik_id", "file_id", "naziv", "vrsta",
                  "velicina", "kreirano", "status", "link"]

FOLDER_SEKRET = "RADOVI_FOLDER_ID"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
DRIVE_WEB = "https://drive.google.com/file/d/{file_id}/view"

MAX_DATOTEKA = 5
MAX_BYTES = 10 * 1024 * 1024           # 10 MB po datoteci
DANI_CUVANJA = 7                       # koliko dana se čuvaju radovi
DOZVOLJENI = ("pdf", "jpg", "jpeg", "png")
TIMEOUT_S = 120

UPUTA_UCENIKU = (
    "**Kako poslati rad:** piši uredno i čitko na papir. Kad završiš, skeniraj (najbolje) ili "
    "uslikaj ravno odozgo, cijelu stranicu, bez sjene. Jedna stranica = jedna datoteka "
    "(PDF, JPG ili PNG). Provjeri prije slanja da se sve vidi — profesor ovo ne prepisuje, "
    "samo gleda tvoj rad."
)


def _tekst(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("nan", "none") else s


def folder_id(st) -> str:
    try:
        return _tekst(st.secrets.get(FOLDER_SEKRET))
    except Exception:                                   # noqa: BLE001 — nema Secrets
        return ""


def ukljuceno(st, test) -> bool:
    """Šalje li učenik rad za OVAJ test (`rad` = Da) i ima li gdje spremiti."""
    return _tekst((test or {}).get("rad")) == "Da" and bool(folder_id(st))


def dozvoljena(naziv: str) -> bool:
    return _tekst(naziv).lower().rsplit(".", 1)[-1] in DOZVOLJENI


def ocisti_naziv(naziv: str) -> str:
    """Sigurno ime datoteke za Drive (bez đ/č i razmaka)."""
    osnovno = _tekst(naziv).split("/")[-1].split("\\")[-1]
    sigurno = "".join(c if (c.isascii() and (c.isalnum() or c in "._-")) else "_"
                      for c in osnovno)
    return sigurno[:120] or "rad"


def ime_datoteke(test_id: str, ucenik_id: str, redni: int, naziv: str) -> str:
    """`T261022-RXA5_AA1111_2026-10-22_1.pdf` — čitljivo i jedinstveno."""
    danas = date.today().strftime("%Y-%m-%d")
    produzetak = _tekst(naziv).lower().rsplit(".", 1)[-1] if "." in _tekst(naziv) else "pdf"
    return f"{_tekst(test_id)}_{_tekst(ucenik_id).upper()}_{danas}_{redni}.{produzetak}"


def _sa_info(st):
    for kljuc in (SA_SEKRET, SA_SEKRET_TESTOVI):
        try:
            sirovo = st.secrets.get(kljuc)
            if sirovo:
                return json.loads(sirovo)
        except Exception:                               # noqa: BLE001
            continue
    return None


def predaj_na_drive(st, naziv: str, sadrzaj: bytes, folder: str = "", transport=None) -> dict:
    """Jedan upload na Drive (multipart). Vraća {'file_id', 'link'} ili baca RuntimeError."""
    folder = folder or folder_id(st)
    if not folder:
        raise RuntimeError("Nema RADOVI_FOLDER_ID u Secrets.")
    info = _sa_info(st)
    if not info:
        raise RuntimeError("Nema servisnog računa u Secrets.")
    tok = token(info)

    meta = {"name": ocisti_naziv(naziv), "parents": [folder]}
    granica = "caki" + "".join(_secrets.choice(string.ascii_lowercase) for _ in range(16))
    tijelo = (
        f"--{granica}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(meta, ensure_ascii=False)}\r\n"
        f"--{granica}\r\nContent-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + sadrzaj + f"\r\n--{granica}--\r\n".encode("utf-8")

    if transport is not None:                       # za testove
        odgovor = transport(tijelo, granica, tok)
        file_id = _tekst((odgovor or {}).get("id"))
        return {"file_id": file_id, "link": DRIVE_WEB.format(file_id=file_id)}

    r = requests.post(
        f"{UPLOAD_URL}?uploadType=multipart&supportsAllDrives=true&fields=id",
        headers={"Authorization": f"Bearer {tok}",
                 "Content-Type": f"multipart/related; boundary={granica}"},
        data=tijelo, timeout=TIMEOUT_S)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Drive je vratio {r.status_code}.")
    try:
        return {"file_id": _tekst(r.json().get("id")), "link": DRIVE_WEB.format(file_id=r.json()["id"])}
    except ValueError as e:
        raise RuntimeError("Drive je vratio nešto što nije JSON.") from e


def novi_id(postojeci=()) -> str:
    danas = datetime.now().strftime("%y%m%d")
    postojeci = {_tekst(x) for x in (postojeci or ()) if _tekst(x)}
    for _ in range(300):
        kandidat = f"R{danas}-{len(postojeci) + 1}"
        if kandidat not in postojeci:
            return kandidat
        postojeci.add(kandidat)
    raise RuntimeError("Ne mogu složiti jedinstven ID rada.")


# ============================================================
# Sheet
# ============================================================

def osiguraj_tab(sheet):
    try:
        return sheet.worksheet(RADOVI_TAB)
    except Exception:                                   # noqa: BLE001
        ws = sheet.add_worksheet(title=RADOVI_TAB, rows=500, cols=len(RADOVI_HEADERS))
        ws.append_row(RADOVI_HEADERS, value_input_option="RAW")
        return ws


def load_radovi(sheet) -> list[dict]:
    try:
        ws = sheet.worksheet(RADOVI_TAB)
    except Exception:                                   # noqa: BLE001
        return []
    try:
        return [r for r in ws.get_all_records() if _tekst(r.get("rad_id"))]
    except Exception:                                   # noqa: BLE001
        return []


def upisi_rad(sheet, *, test_id: str, ucenik_id: str, file_id: str, naziv: str,
              vrsta: str, velicina: int, link: str = "") -> dict:
    ws = osiguraj_tab(sheet)
    try:
        postojeci = [_tekst(v) for v in ws.col_values(1)]
    except Exception:                                   # noqa: BLE001
        postojeci = []
    redak = {
        "rad_id": novi_id(postojeci),
        "test_id": _tekst(test_id),
        "ucenik_id": _tekst(ucenik_id).upper(),
        "file_id": _tekst(file_id),
        "naziv": _tekst(naziv)[:200],
        "vrsta": _tekst(vrsta),
        "velicina": int(velicina or 0),
        "kreirano": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "status": "Novo",
        "link": _tekst(link) or DRIVE_WEB.format(file_id=_tekst(file_id)),
    }
    ws.append_row([redak[h] for h in RADOVI_HEADERS], value_input_option="RAW")
    return redak


# ============================================================
# Pregled i brisanje
# ============================================================

def za_test(radovi, test_id: str) -> list[dict]:
    return [r for r in radovi or [] if _tekst(r.get("test_id")) == _tekst(test_id)]


def stariji_od(radovi, dana: int = DANI_CUVANJA, danas=None) -> list[dict]:
    """Radovi stariji od `dana` (za brisanje). Neispravan datum se preskače."""
    granica = (danas or date.today()) - timedelta(days=max(0, int(dana)))
    izlaz = []
    for r in radovi or []:
        try:
            kad = datetime.fromisoformat(_tekst(r.get("kreirano")).replace(" ", "T")).date()
        except ValueError:
            continue
        if kad < granica and _tekst(r.get("status")) != "Obrisano":
            izlaz.append(r)
    return izlaz


def tablica(radovi):
    import pandas as pd

    return pd.DataFrame([{
        "ID": _tekst(r.get("rad_id")),
        "Test": _tekst(r.get("test_id")),
        "Učenik": _tekst(r.get("ucenik_id")).upper(),
        "Datoteka": _tekst(r.get("naziv")),
        "Vrsta": _tekst(r.get("vrsta")),
        "KB": round(int(r.get("velicina") or 0) / 1024, 1),
        "Kreirano": _tekst(r.get("kreirano")),
        "Status": _tekst(r.get("status")),
        "Otvori": _tekst(r.get("link")),
    } for r in radovi or []])


def oznaci_obrisano(sheet, rad_id: str) -> bool:
    """Označi rad kao Obrisano (zapis ostaje) — koristi baza; ovdje za isti API."""
    try:
        ws = sheet.worksheet(RADOVI_TAB)
        zaglavlje = [_tekst(h) for h in ws.row_values(1)]
        if "status" not in zaglavlje:
            return False
        kolona = zaglavlje.index("status") + 1
        for i, vrijednost in enumerate(ws.col_values(1), start=1):
            if _tekst(vrijednost) == _tekst(rad_id):
                ws.update_cell(i, kolona, "Obrisano")
                return True
    except Exception:                                   # noqa: BLE001
        return False
    return False


def prikazi_slanje_rada(st, sheet, test, ucenik_id: str) -> None:
    """📷 Kutija za slanje rada — pojavljuje se samo za testove s `rad` = Da.

    Nikad ne ruši test: sve greške se pretvaraju u poruku učeniku.
    """
    if not ukljuceno(st, test):
        return
    test_id = _tekst(test.get("test_id"))
    postojeci = [r for r in load_radovi(sheet)
                 if _tekst(r.get("test_id")) == test_id
                 and _tekst(r.get("ucenik_id")).upper() == _tekst(ucenik_id).upper()]
    if postojeci:
        st.success(f"📷 Rad je poslan ({len(postojeci)} datoteka). Caki ga može otvoriti.")
        for r in postojeci:
            st.caption(f"• {_tekst(r.get('naziv'))} — {_tekst(r.get('kreirano'))}")
        return

    with st.expander("📷 Pošalji svoj rad (fotografije ili sken)", expanded=False):
        st.markdown(UPUTA_UCENIKU)
        datoteke = st.file_uploader(
            "Odaberi datoteke (PDF, JPG ili PNG; najviše 5, do 10 MB svaka)",
            type=list(DOZVOLJENI), accept_multiple_files=True, key=f"rad_{test_id}")
        if st.button("📤 Pošalji rad", key=f"rad_posalji_{test_id}", type="primary"):
            if not datoteke:
                st.warning("Odaberi barem jednu datoteku.")
                return
            if len(datoteke) > MAX_DATOTEKA:
                st.error(f"Najviše {MAX_DATOTEKA} datoteka odjednom.")
                return
            poslano, greske = 0, []
            for redni, datoteka in enumerate(datoteke, start=1):
                sadrzaj = datoteka.getvalue()
                if len(sadrzaj) > MAX_BYTES:
                    greske.append(f"{datoteka.name}: veće od 10 MB")
                    continue
                naziv = ime_datoteke(test_id, ucenik_id, redni, datoteka.name)
                try:
                    meta = predaj_na_drive(st, naziv, sadrzaj)
                    upisi_rad(sheet, test_id=test_id, ucenik_id=ucenik_id,
                              file_id=meta["file_id"], naziv=naziv,
                              vrsta=_tekst(datoteka.name).lower().rsplit(".", 1)[-1],
                              velicina=len(sadrzaj), link=meta["link"])
                    poslano += 1
                except Exception as e:                  # noqa: BLE001 — javi, ne ruši
                    greske.append(f"{datoteka.name}: {e}")
            if poslano:
                st.success(f"✅ Poslano {poslano} datoteka. Caki ih vidi u pregledu radova.")
            for g in greske:
                st.error(f"⚠️ {g}")
            if poslano:
                st.rerun()


__all__ = [
    "RADOVI_TAB", "RADOVI_HEADERS", "FOLDER_SEKRET", "MAX_DATOTEKA", "MAX_BYTES",
    "DANI_CUVANJA", "DOZVOLJENI", "UPUTA_UCENIKU", "folder_id", "ukljuceno", "dozvoljena",
    "ocisti_naziv", "ime_datoteke", "predaj_na_drive", "novi_id", "osiguraj_tab", "load_radovi",
    "upisi_rad", "za_test", "stariji_od", "tablica", "prikazi_slanje_rada",
]
