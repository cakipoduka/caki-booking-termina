"""
CAKI Upisi u SŠ — pipeline_upisi.py
Pomoćne funkcije za rad s Učenici/Prijave tabovima preko gspread-a.
Isti stack kao baza zadataka (get_credentials/get_gspread_client pattern).
"""
import random
import string
from datetime import datetime, timedelta

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Nazivi komponenti — kod : čitljiva labela za dropdown
KOMPONENTE = {
    "MAT-KRATKI": "Matematika — kratki (20h)",
    "MAT-DUGI": "Matematika — dugi (36h)",
    "PRELOG-KRATKI": "Prelog — kratki (34h)",
    "PRELOG-DUGI": "Prelog — dugi (46h)",
    "HR": "Hrvatski (10h)",
    "ENG": "Engleski (10h)",
    "SIM-A": "Simulacija A — Prelog",
    "SIM-B": "Simulacija B — Matematika (matematičke gimnazije)",
    "SIM-C": "Simulacija C — Matematika i hrvatski (opće gimnazije)",
}

STATUSI_POZIVA = ["Čeka poziv", "Potvrdio", "Čeka", "Odustao"]

# Ista konstanta kao u Apps Scriptu — mijenja se jednom godišnje
SEZONA = "2026/27"

# Koje komponente uopće imaju tjedne termine za booking (SIM-* i HR isključeni — drugi obrasci rasporeda)
KOMPONENTE_ZA_BOOKING = ["MAT-KRATKI", "MAT-DUGI", "PRELOG-KRATKI", "PRELOG-DUGI", "ENG"]

REZERVACIJA_ROK_DANA = 5


# --- Autentifikacija (identično baza zadataka) ---

def get_credentials(service_account_info: dict):
    return Credentials.from_service_account_info(service_account_info, scopes=SCOPES)


def get_gspread_client(service_account_info: dict):
    return gspread.authorize(get_credentials(service_account_info))


# --- Učitavanje podataka ---

def _load_worksheet_df(ws) -> pd.DataFrame:
    """Robustno učitavanje - radi ispravno i kad tab ima samo header, bez ijednog retka podataka."""
    headers = ws.row_values(1)
    records = ws.get_all_records()
    if not records:
        df = pd.DataFrame(columns=headers)
    else:
        df = pd.DataFrame(records)
    df["_row"] = range(2, len(df) + 2)
    return df


def load_ucenici(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Učenici"))


def load_prijave(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Prijave"))


# --- Uređivanje kontakt podataka učenika ---

def azuriraj_ucenika(sheet, row_number: int, polja: dict):
    """polja = {"ime_djeteta": "...", "mobitel_djeteta": "...", ...}"""
    ws = sheet.worksheet("Učenici")
    headers = ws.row_values(1)
    for naziv_polja, vrijednost in polja.items():
        if naziv_polja in headers:
            col = headers.index(naziv_polja) + 1
            ws.update_cell(row_number, col, vrijednost)


def ocisti_duplikat_flag(sheet, row_number: int):
    azuriraj_ucenika(sheet, row_number, {"moguci_duplikat_id": ""})


def spoji_ucenike(sheet, primarni_id: str, duplikat_id: str):
    """Prebacuje sve Prijave retke s duplikat_id na primarni_id, briše duplikat iz Učenici."""
    ws_prijave = sheet.worksheet("Prijave")
    prijave = ws_prijave.get_all_records()
    headers = ws_prijave.row_values(1)
    col_ucenik_id = headers.index("ucenik_id") + 1

    for i, red in enumerate(prijave, start=2):
        if red.get("ucenik_id") == duplikat_id:
            ws_prijave.update_cell(i, col_ucenik_id, primarni_id)

    ws_ucenici = sheet.worksheet("Učenici")
    ucenici = ws_ucenici.get_all_records()
    for i, red in enumerate(ucenici, start=2):
        if red.get("ucenik_id") == duplikat_id:
            ws_ucenici.delete_rows(i)
            break


# --- Status poziva ---

def postavi_status_poziva(sheet, ucenik_id: str, novi_status: str):
    """Postavlja status_kontakta na sve 'Čeka poziv' retke tog učenika.
    Ako je novi_status == 'Potvrdio', upisuje i posalji_nakon = sada + 24h."""
    ws = sheet.worksheet("Prijave")
    prijave = ws.get_all_records()
    headers = ws.row_values(1)
    col_status = headers.index("status_kontakta") + 1
    col_posalji = headers.index("posalji_nakon") + 1 if "posalji_nakon" in headers else None

    posalji_nakon_vrijednost = ""
    if novi_status == "Potvrdio":
        posalji_nakon_vrijednost = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    azurirano = 0
    for i, red in enumerate(prijave, start=2):
        if red.get("ucenik_id") == ucenik_id and red.get("status_kontakta") == "Čeka poziv":
            ws.update_cell(i, col_status, novi_status)
            if novi_status == "Potvrdio" and col_posalji:
                ws.update_cell(i, col_posalji, posalji_nakon_vrijednost)
            azurirano += 1

    return azurirano


def oznaci_otkazano(sheet, row_number: int):
    ws = sheet.worksheet("Prijave")
    headers = ws.row_values(1)
    col_status = headers.index("status_kontakta") + 1
    ws.update_cell(row_number, col_status, "Otkazano")


# --- Dodavanje nove komponente postojećem učeniku ---

def dodaj_komponentu(sheet, ucenik_id: str, ime_djeteta: str, komponenta_kod: str, nacin_placanja: str, napomena: str = ""):
    ws = sheet.worksheet("Prijave")
    redak_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    ws.append_row([
        redak_id,
        str(ucenik_id),
        str(ime_djeteta),
        str(komponenta_kod),
        str(nacin_placanja),
        "Čeka poziv",
        "Ne",
        str(napomena),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "",
        "",
        SEZONA,
    ])


# ============================================================
# GRUPE / REZERVACIJE — booking sustav
# ============================================================

def postavi_tabove_booking(sheet):
    """Kreira 'Grupe' i 'Rezervacije' tabove ako ne postoje. Pokreni jednom ručno."""
    postojeci = [ws.title for ws in sheet.worksheets()]

    if "Grupe" not in postojeci:
        ws = sheet.add_worksheet(title="Grupe", rows=200, cols=10)
        ws.append_row([
            "grupa_id", "program", "dan", "vrijeme", "ucionica",
            "kapacitet", "tip", "aktivna", "admin_rezervirano", "sezona"
        ])

    if "Rezervacije" not in postojeci:
        ws = sheet.add_worksheet(title="Rezervacije", rows=500, cols=8)
        ws.append_row([
            "rezervacija_id", "grupa_id", "ucenik_id", "ime_djeteta",
            "kontakt_roditelja", "vrijeme_rezervacije", "status", "sezona"
        ])


def load_grupe(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Grupe"))


def load_rezervacije(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Rezervacije"))


def kreiraj_grupu(sheet, program, dan, vrijeme, ucionica, kapacitet, tip, aktivna=True):
    ws = sheet.worksheet("Grupe")
    grupa_id = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    ws.append_row([
        grupa_id, program, dan, vrijeme, ucionica,
        kapacitet, tip, "da" if aktivna else "ne", 0, SEZONA
    ])
    return grupa_id


def azuriraj_grupu(sheet, row_number: int, polja: dict):
    ws = sheet.worksheet("Grupe")
    headers = ws.row_values(1)
    for naziv, vrijednost in polja.items():
        if naziv in headers:
            col = headers.index(naziv) + 1
            ws.update_cell(row_number, col, vrijednost)


def izracunaj_dostupnost(grupa_red: dict, df_rezervacije: pd.DataFrame) -> dict:
    """Vraća {'slobodna': int, 'potvrdjeno': int, 'na_cekanju_uplate': int, 'status_boja': 'zeleno'/'narancasto'/'crveno'}"""
    grupa_id = grupa_red["grupa_id"]
    kapacitet = int(grupa_red.get("kapacitet") or 0)
    admin_rez = int(grupa_red.get("admin_rezervirano") or 0)

    rez_grupe = df_rezervacije[df_rezervacije["grupa_id"] == grupa_id] if not df_rezervacije.empty else df_rezervacije

    potvrdjeno = 0
    na_cekanju = 0
    if not rez_grupe.empty:
        potvrdjeno = len(rez_grupe[rez_grupe["status"] == "Potvrđeno"])
        sada = datetime.now()

        def nije_isteklo(red):
            try:
                vrijeme = datetime.strptime(red["vrijeme_rezervacije"], "%Y-%m-%d %H:%M:%S")
                return (sada - vrijeme).days < REZERVACIJA_ROK_DANA
            except (ValueError, TypeError):
                return True

        cekaju = rez_grupe[rez_grupe["status"] == "Rezervirano"]
        na_cekanju = sum(1 for _, r in cekaju.iterrows() if nije_isteklo(r))

    zauzeto = potvrdjeno + na_cekanju + admin_rez
    slobodna = kapacitet - zauzeto

    if slobodna > 0:
        boja = "zeleno"
    elif na_cekanju > 0:
        boja = "narancasto"
    else:
        boja = "crveno"

    return {
        "slobodna": max(slobodna, 0),
        "potvrdjeno": potvrdjeno,
        "na_cekanju_uplate": na_cekanju,
        "status_boja": boja,
    }


def kreiraj_rezervaciju(sheet, grupa_id, ucenik_id, ime_djeteta, kontakt_roditelja, status="Rezervirano"):
    ws = sheet.worksheet("Rezervacije")
    rezervacija_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    ws.append_row([
        rezervacija_id,
        str(grupa_id),
        str(ucenik_id),
        str(ime_djeteta),
        str(kontakt_roditelja),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        str(status),
        SEZONA,
    ])
    return rezervacija_id


def dohvati_ucenika_po_id(df_ucenici: pd.DataFrame, ucenik_id: str):
    red = df_ucenici[df_ucenici["ucenik_id"] == ucenik_id]
    return red.iloc[0] if not red.empty else None
