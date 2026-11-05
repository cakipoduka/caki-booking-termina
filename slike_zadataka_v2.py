"""
CAKI — slike_zadataka.py  (21.10.2026.)

Prikaz SLIKE uz zadatak u portalu Moj CAKI. Slike zadataka žive u Drive folderu baze
zadataka, a u objavljenom testu je zapisano samo **ime datoteke** (polje `slika` u JSON-u).
Ovaj modul ime pretvori u Drive ID i dohvati bajtove.

BEZ NOVOG PAKETA
    `google-api-python-client` NIJE u portalu i namjerno se ne dodaje (rizik deploya).
    Dovoljni su `google-auth` (već je tu zbog gspreada) i `requests` — Drive REST pozivi.

SECRETS
    `SLIKE_FOLDER_ID` — ID Drive foldera sa slikama (ista vrijednost kao u bazi zadataka).
    Ako ga nema, modul tiho ne radi ništa i portal pokaže dosadašnju napomenu
    („Uz zadatak ide slika — ako je ne vidiš, javi Cakiju”). Ništa se ne ruši.

SERVISNI RAČUN
    Prvo se pokušava **dijeljeni** `GOOGLE_SERVICE_ACCOUNT_JSON` (on već ima pristup folderu
    jer ga koristi baza zadataka). Ako on ne može (npr. folder je podijeljen samo s testnim
    računom), pokušava se `GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI`. Tako radi u obje postavke —
    Caki ne mora znati koji je račun kojem imenu.

KEŠ
    ID-evi i bajtovi se pamte u procesu (do 300 slika) — isti zadatak se ne skida dvaput
    pri svakom rerunu. Keš je samo u memoriji, ne piše ništa na disk.
"""
from __future__ import annotations

import json
import time

import requests
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials

DRIVE_API = "https://www.googleapis.com/drive/v3"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
SLIKE_SEKRET = "SLIKE_FOLDER_ID"
# Baza zadataka bira folder po predmetu (predmet_config.py) — portal proba sve redom.
FOLDER_KLJUCEVI = ("SLIKE_FOLDER_ID", "SLIKE_FOLDER_ID_MATEMATIKA_OS",
                   "SLIKE_FOLDER_ID_FIZIKA", "SLIKE_FOLDER_ID_FAKULTET",
                   "FORMULE_FOLDER_ID")   # 22.10.: formule (PDF/slika) su u svojoj mapi
SA_SEKRET = "GOOGLE_SERVICE_ACCOUNT_JSON"
SA_SEKRET_TESTOVI = "GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI"
TIMEOUT_S = 20
MAX_KES = 300

_TOKEN = {"token": "", "vrijedi_do": 0.0}
_KEŠ_ID: dict[str, str] = {}
_KEŠ_SLIKA: dict[str, bytes] = {}
ZADNJA_GRESKA = ""          # zašto se zadnja slika nije prikazala (v. zadnja_greska)


# ============================================================
# Pomoćno
# ============================================================

def _tekst(vrijednost) -> str:
    return str(vrijednost or "").strip()


def folder_id(st) -> str:
    """ID foldera sa slikama iz Secrets (prazno ako nije postavljen)."""
    try:
        return _tekst(st.secrets.get(SLIKE_SEKRET))
    except Exception:                               # noqa: BLE001 — nema Secrets
        return ""




def _json_tolerantno(sirovo) -> dict:
    """JSON servisnog računa i kad je zalijepljen ljudski (pametni navodnici, prijelomi).

    Isti popravak kao `secrets_json.ucitaj` — ovdje lokalno da modul ostane samostalan.
    """
    tekst = str(sirovo or "").replace("\ufeff", "").strip()
    for lose in ("\u201c", "\u201d", "\u201e", "\u201f"):
        tekst = tekst.replace(lose, '"')
    for trojka in ('"""', "'''"):
        if tekst.startswith(trojka):
            tekst = tekst[3:]
        if tekst.endswith(trojka):
            tekst = tekst[:-3]
    tekst = tekst.strip()
    for strogo in (True, False):
        try:
            return json.loads(tekst, strict=strogo) or {}
        except Exception:
            continue
    return {}


def sa_info(st):
    """Servisni račun za Drive (dijeljeni, ili testni ako dijeljenog nema) ili None."""
    kandidati = sa_kandidati(st)
    return kandidati[0] if kandidati else None


def sa_kandidati(st) -> list[dict]:
    """Svi servisni računi koje portal ima — dijeljeni prvi, pa testni.

    Redoslijed je namjeran: dijeljeni račun već vidi folder sa slikama jer ga koristi
    baza zadataka. Ako folder ipak nije podijeljen s njim, `prikazi_sliku` proba testni.
    """
    izlaz: list[dict] = []
    for kljuc in (SA_SEKRET, SA_SEKRET_TESTOVI):
        try:
            sirovo = st.secrets.get(kljuc)
            if not sirovo:
                continue
            podaci = _json_tolerantno(sirovo)
            if podaci and podaci not in izlaz:
                izlaz.append(podaci)
        except Exception:                               # noqa: BLE001 — nema Secrets / loš JSON
            continue
    return izlaz


def folder_kandidati(st) -> list[str]:
    """Svi ID-evi foldera sa slikama koje portal ima u Secrets — redom.

    22.10.2026. (Cakijev nalaz „slike se ne vide”): baza zadataka bira folder **po predmetu**
    (`SLIKE_FOLDER_ID`, `..._MATEMATIKA_OS`, `..._FIZIKA`), a portal je čitao samo prvi ključ.
    Zato se sada probaju svi — radi bez obzira na to koji je ključ Caki ispunio u portalu.
    """
    izlaz: list[str] = []
    for kljuc in FOLDER_KLJUCEVI:
        try:
            vrijednost = _tekst(st.secrets.get(kljuc))
        except Exception:                               # noqa: BLE001 — nema Secrets
            vrijednost = ""
        if vrijednost and vrijednost not in izlaz:
            izlaz.append(vrijednost)
    return izlaz


def token(sa_info_dict) -> str:
    """OAuth token servisnog računa (pamti se do isteka)."""
    sada = time.time()
    if _TOKEN["token"] and sada < _TOKEN["vrijedi_do"] - 60:
        return _TOKEN["token"]
    creds = Credentials.from_service_account_info(sa_info_dict, scopes=SCOPES)
    creds.refresh(Request())
    _TOKEN["token"] = creds.token
    _TOKEN["vrijedi_do"] = sada + 3000
    return creds.token


def _transport(url: str, params: dict, tok: str, sirovo: bool = False):
    """Jedan GET prema Driveu. `sirovo=True` vraća bajtove (alt=media), inače JSON."""
    odgovor = requests.get(url, params=params, headers={"Authorization": f"Bearer {tok}"},
                           timeout=TIMEOUT_S)
    odgovor.raise_for_status()
    return odgovor.content if sirovo else odgovor.json()


def _u_upit(naziv: str) -> str:
    """Ime datoteke sigurno u Drive upit (apostrof i backslash se escapeaju)."""
    return _tekst(naziv).replace("\\", "\\\\").replace("'", "\\'")


def nadji_id(naziv: str, folder: str, tok: str, transport=None) -> str:
    """Drive ID datoteke po imenu — prvo u zadanom folderu, pa **bilo gdje** na driveu.

    22.10.2026. (Cakijev nalaz „slike se i dalje ne vide”): ako folder u Secrets nije dobro
    postavljen (ili ga uopće nema), traženje po imenu unutar foldera ne nađe ništa. Zato se,
    kad u folderu nema rezultata, radi **globalna pretraga po imenu** preko svih driveova na
    koje servisni račun ima pristup (`corpora=allDrives`).
    """
    naziv = _tekst(naziv)
    if not naziv:
        return ""
    if naziv in _KEŠ_ID:
        return _KEŠ_ID[naziv]

    transport = transport or _transport

    def _trazi(upit: str, dodatno: dict) -> str:
        parametri = {"q": upit, "fields": "files(id,name)", "pageSize": 5,
                     "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
        parametri.update(dodatno)
        podaci = transport(f"{DRIVE_API}/files", parametri, tok)
        datoteke = (podaci or {}).get("files") or []
        return _tekst(datoteke[0].get("id")) if datoteke else ""

    dobiveni = ""
    if folder:
        dobiveni = _trazi(f"name = '{_u_upit(naziv)}' and '{folder}' in parents and trashed = false",
                          {})
    if not dobiveni:
        # globalna pretraga: ime + da nije u smeću (bez ograničenja na folder)
        dobiveni = _trazi(f"name = '{_u_upit(naziv)}' and trashed = false",
                          {"corpora": "allDrives"})

    if dobiveni:
        if len(_KEŠ_ID) >= MAX_KES:
            _KEŠ_ID.clear()
        _KEŠ_ID[naziv] = dobiveni
    return dobiveni


def slika_bytes(naziv: str, folder: str, tok: str, transport=None) -> bytes:
    """Bajtovi slike (prazno ako je nema ili Drive ne odgovori)."""
    file_id = nadji_id(naziv, folder, tok, transport=transport)
    if not file_id:
        return b""
    if file_id in _KEŠ_SLIKA:
        return _KEŠ_SLIKA[file_id]

    transport = transport or _transport
    bajtovi = transport(f"{DRIVE_API}/files/{file_id}", {"alt": "media"}, tok, True)
    if bajtovi:
        if len(_KEŠ_SLIKA) >= MAX_KES:
            _KEŠ_SLIKA.clear()
        _KEŠ_SLIKA[file_id] = bajtovi
    return bajtovi or b""


def prikazi_sliku(st, naziv: str, folder: str = "", sa_info_dict=None,
                  transport=None) -> bool:
    """Prikaže sliku zadatka u portalu. Vraća True ako je slika stvarno prikazana.

    Nijedna greška ovdje ne smije prekinuti test — zato sve vraća False i portal tada
    pokaže tekstualnu napomenu (dosadašnje ponašanje). Ako je zadan `sa_info_dict`,
    koristi se samo on; inače se redom probaju računi iz Secrets (dijeljeni, pa testni).

    Razlog neuspjeha se pamti u `ZADNJA_GRESKA` (v. `zadnja_greska()`) da ga Caki vidi u
    portalu — 22.10.2026., jer se slike nisu prikazale bez ikakve poruke.
    """
    global ZADNJA_GRESKA
    ZADNJA_GRESKA = ""
    try:
        folderi = [folder] if folder else folder_kandidati(st)
        if not folderi:
            # 22.10.2026.: nema ključa u Secrets — ipak probaj GLOBALNU pretragu po imenu
            # (servisni račun vidi cijeli medijski drive). Bolje naći sliku nego odustati.
            folderi = [""]
        kandidati = [sa_info_dict] if sa_info_dict is not None else sa_kandidati(st)
        if not kandidati:
            ZADNJA_GRESKA = "nema servisnog računa u Secrets"
            return False
        greske = []
        for _folder in folderi:
            for podaci in kandidati:
                try:
                    bajtovi = slika_bytes(naziv, _folder, token(podaci), transport=transport)
                except Exception as e:          # noqa: BLE001 — probaj sljedeći folder/račun
                    greske.append(f"{type(e).__name__}")
                    continue
                if bajtovi:
                    # Namjerno BEZ širine: `use_container_width` je u novijim Streamlitima
                    # zastario, a `width="stretch"` ne postoji u starijima.
                    st.image(bajtovi, caption=f"🖼️ {_tekst(naziv)}")
                    return True
        ZADNJA_GRESKA = "datoteka nije nađena ni u jednom folderu (ili Drive greška: " + \
                        (", ".join(greske) or "nema pristupa") + ")"
        return False
    except Exception as e:                      # noqa: BLE001 — slika ne ruši test
        ZADNJA_GRESKA = f"{type(e).__name__}: {e}"
        return False


def zadnja_greska() -> str:
    """Zašto se zadnja slika nije prikazala (prazno = prikazala se)."""
    return ZADNJA_GRESKA


def dijagnostika_slika(st, nazivi, transport=None) -> list[str]:
    """Kratki izvještaj za Cakija: koji su ključevi postavljeni i vidi li Drive datoteke.

    Prikazuje se SAMO kad je u Secrets portala `TESTOVI_DIJAGNOSTIKA = Da` — učenicima se
    ovo nikad ne pokazuje. Namjerno ne baca greške.
    """
    izlaz = []
    try:
        kljucevi = []
        for k in FOLDER_KLJUCEVI:
            try:
                v = _tekst(st.secrets.get(k))
            except Exception:                       # noqa: BLE001
                v = ""
            if v:
                kljucevi.append(f"{k}={v[:12]}…")
        izlaz.append("folderi: " + (", ".join(kljucevi) if kljucevi else "NIJEDAN ključ nije postavljen"))

        racuni = []
        for info in sa_kandidati(st):
            racuni.append(_tekst(info.get("client_email")) or "bez client_email")
        izlaz.append("servisni računi: " + (", ".join(racuni) if racuni else "NIJEDAN"))

        za_probe = [n for n in (nazivi or []) if _tekst(n)][:3]
        if za_probe:
            for naziv in za_probe:
                try:
                    _folderi = folder_kandidati(st) or [""]
                    bajtovi = slika_bytes(naziv, _folderi[0], token(sa_kandidati(st)[0]),
                                          transport=transport)
                except Exception as e:              # noqa: BLE001
                    izlaz.append(f"„{naziv}”: greška {type(e).__name__}")
                    continue
                izlaz.append(f"„{naziv}”: {'nađena (' + str(len(bajtovi)) + ' B)' if bajtovi else 'NIJE nađena'}")
    except Exception as e:                          # noqa: BLE001
        izlaz.append(f"dijagnostika nije uspjela ({type(e).__name__})")
    return izlaz


def ocisti_kes() -> None:
    """Prazni memorijski keš slika (za testove i za slučaj da Caki zamijeni sliku)."""
    _KEŠ_ID.clear()
    _KEŠ_SLIKA.clear()


__all__ = [
    "SLIKE_SEKRET", "SA_SEKRET", "SA_SEKRET_TESTOVI", "folder_id", "sa_info",
    "sa_kandidati", "token", "nadji_id", "slika_bytes", "prikazi_sliku", "ocisti_kes",
    "zadnja_greska", "ZADNJA_GRESKA", "folder_kandidati", "FOLDER_KLJUCEVI",
    "dijagnostika_slika",
]


def prikazi_sliku_zadatka(st, naziv: str, *, sa_info_dict=None) -> bool:
    """Prikaži sliku zadatka ako postoji. Vraća True ako je prikazana (nikad ne ruši ekran)."""
    naziv = _tekst(naziv)
    if not naziv:
        return False
    folderi = folder_kandidati(st)
    if not folderi:
        st.caption("🖼️ Uz zadatak ide slika — ako je ne vidiš, javi Cakiju.")
        return False
    try:
        prikazi_sliku(st, naziv, folder=folderi[0], sa_info_dict=sa_info_dict)
        return True
    except Exception:
        st.caption("🖼️ Sliku trenutno nije moguće dohvatiti — javi Cakiju.")
        return False


# ------------------------------------------------------------------ HTML prikaz (Kladova lekcija)

def _valjana_slika(bajtovi: bytes) -> bool:
    """Zaglavlje mora biti poznata slika — neispravna datoteka ne smije doći do prikaza."""
    if not bajtovi or len(bajtovi) < 12:
        return False
    return (bajtovi[:8] == b"\x89PNG\r\n\x1a\n"
            or bajtovi[:3] == b"\xff\xd8\xff"
            or bajtovi[:6] in (b"GIF87a", b"GIF89a")
            or (bajtovi[:4] == b"RIFF" and bajtovi[8:12] == b"WEBP"))


def _mime(bajtovi: bytes) -> str:
    if bajtovi[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if bajtovi[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if bajtovi[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/webp"


def html_slika(bajtovi: bytes, width: int = 420) -> str:
    """`<img>` s ugrađenim base64 — PREGLEDNIK dekodira, server ne (zato ne ruši proces)."""
    if not _valjana_slika(bajtovi):
        return ""
    import base64

    return (f'<img src="data:{_mime(bajtovi)};base64,{base64.b64encode(bajtovi).decode()}" '
            f'style="max-width:{int(width)}px;width:100%;height:auto;" />')


def prikazi_sliku_html(st, naziv: str, folder: str = "", sa_info_dict=None,
                       width: int = 420) -> bool:
    """Prikaži sliku kao HTML (sigurno). Vraća True ako je prikazana."""
    naziv = _tekst(naziv)
    if not naziv:
        return False
    try:
        folderi = [folder] if _tekst(folder) else folder_kandidati(st)
        if not folderi:
            return False
        for ime_foldera in folderi:
            podaci = sadrzaj = None
            try:
                podaci = sa_info_dict or sa_info(st)
                if not podaci:
                    continue
                sadrzaj = slika_bytes(naziv, ime_foldera, token(podaci))
            except Exception:                                # noqa: BLE001
                continue
            html = html_slika(sadrzaj, width=width) if sadrzaj else ""
            if html:
                st.markdown(html, unsafe_allow_html=True)
                return True
    except Exception:                                        # noqa: BLE001
        return False
    return False


def preuzmi_url(url: str, timeout: int = 20):
    """Preuzmi sliku s URL-a (Mathpix crop) — vraća bajtove ili None."""
    try:
        import requests

        r = requests.get(str(url), timeout=timeout)
        if getattr(r, "status_code", 0) == 200 and r.content and _valjana_slika(r.content):
            return r.content
    except Exception:                                  # noqa: BLE001
        return None
    return None
