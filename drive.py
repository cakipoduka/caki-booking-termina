"""
CAKI testovi v2 — `drive.py`
UPLOAD U DRIVE: učenik fotografira papirni rad doma i pošalje ga kroz portal.

Zašto zaseban modul: to je **jedino mjesto** koje piše u Drive. Ako Google promijeni API ili
nestanu prava, popravlja se ovdje — ostalo (radovi, ekran, rezultati) ostaje isto.

Tajne: `RADOVI_FOLDER_ID` (folder za radove), servisni račun (`GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI`
ili `GOOGLE_SERVICE_ACCOUNT_JSON`).

Ako upload ne uspije, **ne ruši se ništa** — vraća se greška, a učenik i dalje može poslati
poveznicu. Bolje poslati link nego izgubiti rad.
"""
from __future__ import annotations

import model

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
MAKS_BAJTOVA = 25 * 1024 * 1024          # 25 MB — dovoljno za fotografiju ili sken


def folder_id(secrets) -> str:
    try:
        return model.tekst(secrets.get("RADOVI_FOLDER_ID"))
    except Exception:                                  # noqa: BLE001
        return ""


def vrsta_datoteke(naziv: str) -> str:
    """MIME tip iz nastavka — Drive ga koristi za prikaz."""
    n = model.tekst(naziv).lower()
    if n.endswith(".pdf"):
        return "application/pdf"
    if n.endswith(".png"):
        return "image/png"
    if n.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if n.endswith(".webp"):
        return "image/webp"
    if n.endswith(".heic"):
        return "image/heic"
    return "application/octet-stream"


def provjeri(bajtovi: bytes, naziv: str) -> str:
    """Vrati poruku greške ili prazno ako je datoteka u redu."""
    if not bajtovi:
        return "Datoteka je prazna — pokušaj ponovno."
    if len(bajtovi) > MAKS_BAJTOVA:
        return (f"Datoteka je prevelika ({len(bajtovi) / 1024 / 1024:.1f} MB). "
                f"Najviše {MAKS_BAJTOVA // 1024 // 1024} MB — smanji fotografiju.")
    if not model.tekst(naziv):
        return "Datoteka nema ime."
    return ""


def ucitaj(bajtovi: bytes, naziv: str, *, folder: str, servis=None) -> tuple[str, str]:
    """Pošalji datoteku u Drive. Vraća (poveznica, greška).

    `servis` je injektabilan za testove (bilo koji objekt s `files().create(...)`).
    """
    greska = provjeri(bajtovi, naziv)
    if greska:
        return "", greska
    if not model.tekst(folder):
        return "", "Folder za radove nije postavljen (RADOVI_FOLDER_ID)."

    if servis is None:
        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build
        except Exception:                              # noqa: BLE001 — paket nije instaliran
            return "", "Google API za Drive nije dostupan u ovoj aplikaciji."
        try:
            import secrets_json as _sj
            import streamlit as st

            podaci = _sj.ucitaj(st, "GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI") \
                if model.tekst(st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI")) \
                else _sj.ucitaj(st, "GOOGLE_SERVICE_ACCOUNT_JSON")
            kredencijali = Credentials.from_service_account_info(podaci, scopes=SCOPES)
            servis = build("drive", "v3", credentials=kredencijali, cache_discovery=False)
        except Exception as e:                         # noqa: BLE001
            return "", f"Drive se ne može otvoriti: {type(e).__name__}."
    try:
        from googleapiclient.http import MediaInMemoryUpload

        medij = MediaInMemoryUpload(bajtovi, mimetype=vrsta_datoteke(naziv), resumable=False)
    except Exception:                                  # noqa: BLE001 — paket nije instaliran
        medij = None
    try:
        rezultat = servis.files().create(
            body={"name": naziv, "parents": [folder]},
            media_body=medij,
            fields="id, webViewLink",
            supportsAllDrives=True,
        ).execute()
        return model.tekst((rezultat or {}).get("webViewLink")), ""
    except Exception as e:                             # noqa: BLE001
        return "", f"Slanje u Drive nije uspjelo: {type(e).__name__}."
