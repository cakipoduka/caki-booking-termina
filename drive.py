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

# 21.11.2026.: bilo je `drive.file`. Ta dozvola smije pisati SAMO u mape koje je aplikacija sama
# stvorila — u ručno napravljenu mapu `02_Radovi_ucenika` Google odbija upis (404 notFound), pa
# je učenik dobivao „Fotografija nije poslana na Drive". Puna `drive` dozvola vrijedi samo za ono
# što je servisnom računu podijeljeno, dakle i dalje ne vidi ništa drugo.
SCOPES = ["https://www.googleapis.com/auth/drive"]
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
        return "", f"Slanje u Drive nije uspjelo: {opis_greske(e)}"


# Poznati razlozi odbijanja (polje `reason` u Googleovom odgovoru) → što napraviti.
_RAZLOZI = {
    "notFound": "mapa za radove nije dostupna servisnom računu (provjeri RADOVI_FOLDER_ID i je li "
                "servisni račun član dijeljenog diska)",
    "storageQuotaExceeded": "servisni račun nema prostor na Driveu — mapa mora biti na DIJELJENOM "
                            "disku (Shared Drive), ne u nečijem „Moj disk\"",
    "insufficientFilePermissions": "servisni račun nema pravo pisanja u mapu (treba uloga "
                                   "Contributor/Content manager ili jača)",
    "insufficientPermissions": "aplikacija nema dozvolu za Drive (scope)",
    "forbidden": "Google je odbio upis (prava na mapi)",
}


def opis_greske(e: Exception) -> str:
    """Pretvori grešku Google API-ja u rečenicu koja kaže ZAŠTO (ne samo „HttpError").

    Prije je poruka bila samo ime vrste greške, pa se iz aplikacije nije moglo znati je li kriv
    folder, prava ili kvota.
    """
    import json

    status, razlog = "", ""
    odgovor = getattr(e, "resp", None)
    if odgovor is not None:
        status = model.tekst(getattr(odgovor, "status", ""))
    sadrzaj = getattr(e, "content", b"") or b""
    try:
        podaci = json.loads(sadrzaj.decode("utf-8") if isinstance(sadrzaj, bytes) else sadrzaj)
        gr = (podaci or {}).get("error") or {}
        razlog = model.tekst(((gr.get("errors") or [{}])[0] or {}).get("reason")) \
            or model.tekst(gr.get("status"))
    except Exception:                                  # noqa: BLE001 — sadržaj nije JSON
        pass
    if razlog in _RAZLOZI:
        return f"{_RAZLOZI[razlog]} [{status} {razlog}]".replace("[ ", "[")
    if status or razlog:
        return f"{type(e).__name__} [{status} {razlog}]".replace(" ]", "]").replace("[ ", "[")
    return f"{type(e).__name__}."
