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


# Redoslijed ključeva u Secrets. VAŽNO (23.11.2026.): ako aplikacija ima OBA ključa, Drive koristi
# `_TESTOVI`, a Sheet (portal) obični `GOOGLE_SERVICE_ACCOUNT_JSON` — to mogu biti DVA RAZLIČITA
# servisna računa. Zato poruka o grešci sada kaže kojim je računom pokušano.
KLJUCEVI_RACUNA = ("GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI", "GOOGLE_SERVICE_ACCOUNT_JSON")


def vjerodajnice(st=None) -> tuple[dict, str]:
    """(JSON servisnog računa, ime ključa iz kojeg je pročitan). Baca `ValueError` ako nema ni jednog."""
    import secrets_json as _sj

    if st is None:
        import streamlit as st
    for kljuc in KLJUCEVI_RACUNA:
        try:
            ima = st.secrets.get(kljuc)
        except Exception:                              # noqa: BLE001
            ima = None
        if ima:
            return _sj.ucitaj(st, kljuc), kljuc
    raise ValueError("U Secrets nema servisnog računa (" + " ni ".join(KLJUCEVI_RACUNA) + ").")


def racun(st=None) -> dict:
    """Koji servisni račun Drive koristi: {'email', 'kljuc', 'greska'} — e-mail računa nije tajna."""
    try:
        podaci, kljuc = vjerodajnice(st)
        return {"email": model.tekst(podaci.get("client_email")), "kljuc": kljuc, "greska": ""}
    except Exception as e:                             # noqa: BLE001
        return {"email": "", "kljuc": "", "greska": model.tekst(e)[:300]}


def _racun_za_poruku() -> str:
    r = racun()
    return f" · račun: {r['email']} (iz {r['kljuc']})" if r["email"] else ""


def provjeri_pristup(folder: str, *, servis=None) -> dict:
    """Dijagnostika bez upisa: vidi li servisni račun mapu i smije li u nju dodavati?

    Vraća {'ok', 'poruka', 'email', 'kljuc'}. Ne stvara nikakvu datoteku.
    """
    izlaz = {"ok": False, "poruka": "", "email": "", "kljuc": ""}
    if not model.tekst(folder):
        izlaz["poruka"] = "RADOVI_FOLDER_ID nije postavljen u Secrets."
        return izlaz
    if servis is None:
        r = racun()
        izlaz.update({"email": r["email"], "kljuc": r["kljuc"]})
        if r["greska"]:
            izlaz["poruka"] = f"Servisni račun se ne može pročitati: {r['greska']}"
            return izlaz
        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build

            podaci, _ = vjerodajnice()
            servis = build("drive", "v3", cache_discovery=False,
                           credentials=Credentials.from_service_account_info(podaci, scopes=SCOPES))
        except Exception as e:                         # noqa: BLE001
            izlaz["poruka"] = f"Drive se ne može otvoriti: {type(e).__name__}: {model.tekst(e)[:300]}"
            return izlaz
    try:
        m = servis.files().get(fileId=folder, supportsAllDrives=True,
                               fields="id, name, driveId, capabilities(canAddChildren)").execute()
    except Exception as e:                             # noqa: BLE001
        izlaz["poruka"] = f"Mapa nije dostupna: {opis_greske(e)}"
        return izlaz
    m = m or {}
    if not (m.get("capabilities") or {}).get("canAddChildren"):
        izlaz["poruka"] = (f"Mapa „{model.tekst(m.get('name'))}” je vidljiva, ali račun u nju NE smije "
                           "dodavati datoteke (treba uloga Contributor / Content manager).")
        return izlaz
    gdje = "na dijeljenom disku" if m.get("driveId") else "u nečijem „Moj disk” — servisni račun tamo nema prostora"
    izlaz["ok"] = bool(m.get("driveId"))
    izlaz["poruka"] = (f"Mapa „{model.tekst(m.get('name'))}” je dostupna i račun smije dodavati, {gdje}."
                       if izlaz["ok"] else
                       f"Mapa „{model.tekst(m.get('name'))}” je {gdje}. Premjesti je na dijeljeni disk.")
    return izlaz


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
            podaci, kljuc = vjerodajnice()
            kredencijali = Credentials.from_service_account_info(podaci, scopes=SCOPES)
            servis = build("drive", "v3", credentials=kredencijali, cache_discovery=False)
        except Exception as e:                         # noqa: BLE001
            # 23.11.2026.: prije samo ime greške („ValueError") — sad i poruka, jer
            # `secrets_json` u poruci kaže TOČNO što ne valja u Secrets.
            return "", f"Drive se ne može otvoriti: {type(e).__name__}: {model.tekst(e)[:300]}"
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
        return "", f"Slanje u Drive nije uspjelo: {opis_greske(e)}{_racun_za_poruku()}"


# Poznati razlozi odbijanja (polje `reason` u Googleovom odgovoru) → što napraviti.
_RAZLOZI = {
    "notFound": "mapa za radove nije dostupna servisnom računu (provjeri RADOVI_FOLDER_ID i je li "
                "servisni račun član dijeljenog diska)",
    "storageQuotaExceeded": "servisni račun nema prostor na Driveu — mapa mora biti na DIJELJENOM "
                            "disku (Shared Drive), ne u nečijem „Moj disk\"",
    "insufficientFilePermissions": "servisni račun nema pravo pisanja u mapu (treba uloga "
                                   "Contributor/Content manager ili jača)",
    "insufficientPermissions": "aplikacija nema dozvolu za Drive (scope)",
    "accessNotConfigured": "Google Drive API nije uključen u Google Cloud projektu servisnog "
                           "računa (console.cloud.google.com → APIs → Google Drive API → Enable)",
    "SERVICE_DISABLED": "Google Drive API nije uključen u Google Cloud projektu servisnog "
                        "računa (console.cloud.google.com → APIs → Google Drive API → Enable)",
    "forbidden": "Google je odbio upis (prava na mapi)",
}


def opis_greske(e: Exception) -> str:
    """Pretvori grešku Google API-ja u rečenicu koja kaže ZAŠTO (ne samo „HttpError").

    Prije je poruka bila samo ime vrste greške, pa se iz aplikacije nije moglo znati je li kriv
    folder, prava ili kvota.
    """
    import json

    status, razlog, poruka = "", "", ""
    odgovor = getattr(e, "resp", None)
    if odgovor is not None:
        status = model.tekst(getattr(odgovor, "status", ""))
    sadrzaj = getattr(e, "content", b"") or b""
    try:
        podaci = json.loads(sadrzaj.decode("utf-8") if isinstance(sadrzaj, bytes) else sadrzaj)
        gr = (podaci or {}).get("error") or {}
        razlog = model.tekst(((gr.get("errors") or [{}])[0] or {}).get("reason")) \
            or model.tekst(gr.get("status"))
        poruka = model.tekst(gr.get("message"))
        # „Drive API nije uključen" Google šalje u `details[].reason` (SERVICE_DISABLED)
        for detalj in gr.get("details") or []:
            if model.tekst((detalj or {}).get("reason")) == "SERVICE_DISABLED":
                razlog = "SERVICE_DISABLED"
    except Exception:                                  # noqa: BLE001 — sadržaj nije JSON
        pass
    if razlog in _RAZLOZI:
        return f"{_RAZLOZI[razlog]} [{status} {razlog}]".replace("[ ", "[")
    if status or razlog:
        dodatak = f" — {poruka[:200]}" if poruka else ""
        return (f"{type(e).__name__} [{status} {razlog}]".replace(" ]", "]").replace("[ ", "[")
                + dodatak)
    tekst = model.tekst(e)
    return f"{type(e).__name__}: {tekst[:200]}" if tekst else f"{type(e).__name__}."
