"""
CAKI Upisi u SŠ — pipeline_upisi.py
Pomoćne funkcije za rad s Učenici/Prijave tabovima preko gspread-a.
Isti stack kao baza zadataka (get_credentials/get_gspread_client pattern).
"""
import io
import os
import random
import string
import json
import math
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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

# Koliko sati nakon telefonske potvrde ("Potvrdio") ponuda smije krenuti (§23.6: jedinstveno 36h
# za sve programe, odluka 22.9.2026.). Mijenja se samo ovdje.
POSALJI_NAKON_SATI = 36

# Streamlit Cloud radi u UTC vremenu, a Apps Script u zagrebačkom — sva vremena koja
# Apps Script čita (posalji_nakon) moraju biti zagrebačka, inače se ponuda šalje 1-2 h ranije.
ZAGREB = ZoneInfo("Europe/Zagreb")


def sada_zagreb() -> datetime:
    """Trenutno vrijeme u Zagrebu, bez oznake zone (isti oblik koji Apps Script očekuje)."""
    return datetime.now(ZAGREB).replace(tzinfo=None)

# Popis nastavnika — jednostavan popis imena, dovoljno za sad (bez zasebnog Nastavnici taba)
NASTAVNICI = ["Caki (ja)", "Neira", "Slađana", "Mirela", "Ivica", "Martina"]

# --- Matura predmeti (nema Cjenik šifri kao za Upise — v. CRM master §21.2, otvoreno) ---
# Predmeti se dodaju BEZ komponenta/nacin_placanja, isti oblik retka kakav piše
# CAKI_matura_onFormSubmit.gs. Kad Cjenik za Maturu bude definiran, ovo se nadograđuje.
PREDMETI_MATURA = {
    "hrvatski": "Hrvatski",
    "matematika": "Matematika",
    "engleski": "Engleski",
    "fizika": "Fizika",
    "kemija": "Kemija",
    "biologija": "Biologija",
    "fizika_medicina": "Fizika (Paket MEDICINA)",
    "kemija_medicina": "Kemija (Paket MEDICINA)",
    "biologija_medicina": "Biologija (Paket MEDICINA)",
}

# Predmeti za koje se pita razina ispita A/B (v. §21.2)
PREDMETI_S_RAZINOM = ["matematika", "engleski"]

NACINI_PRACENJA = ["uživo", "isključivo online"]
DANI_U_TJEDNU = ["Ponedjeljak", "Utorak", "Srijeda", "Četvrtak", "Petak", "Subota", "Nedjelja"]

# --- Instrukcije (individualne/male-grupne, odvojeno od Upisi grupnih Termina/Dolazaka) ---
INSTRUKCIJE_TRAJANJA = [45, 60, 90, 120]  # minuta
INSTRUKCIJE_OBLICI = ["Individualno", "Grupa"]


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
    Ako je novi_status == 'Potvrdio', upisuje i posalji_nakon = sada + POSALJI_NAKON_SATI (36h)."""
    ws = sheet.worksheet("Prijave")
    prijave = ws.get_all_records()
    headers = ws.row_values(1)
    col_status = headers.index("status_kontakta") + 1
    col_posalji = headers.index("posalji_nakon") + 1 if "posalji_nakon" in headers else None

    posalji_nakon_vrijednost = ""
    if novi_status == "Potvrdio":
        posalji_nakon_vrijednost = (sada_zagreb() + timedelta(hours=POSALJI_NAKON_SATI)).strftime("%Y-%m-%d %H:%M:%S")

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


def dodaj_maturu_predmet(sheet, ucenik_id: str, ime_djeteta: str, predmet: str,
                          razina_ispita: str = "", nacin_pracenja: str = "", napomena: str = ""):
    """Dodaje jedan Matura predmet postojećem učeniku. Piše po NAZIVU stupca (ne
    pozicijski) da radi bez obzira gdje su stupci program_tip/predmet/... u headeru —
    isti pristup kao CAKI_matura_onFormSubmit.gs."""
    ws = sheet.worksheet("Prijave")
    headers = ws.row_values(1)

    redak_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    vrijednosti = {
        "redak_id": redak_id,
        "ucenik_id": str(ucenik_id),
        "ime_djeteta": str(ime_djeteta),
        "status_kontakta": "Čeka poziv",
        "napomena": str(napomena),
        "timestamp_prijave": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sezona": SEZONA,
        "program_tip": "Matura",
        "predmet": str(predmet),
        "stupanj_skolovanja": "Srednja škola",
        "razina_ispita": str(razina_ispita),
        "nacin_pracenja": str(nacin_pracenja),
    }

    red = ["" for _ in headers]
    for naziv, vrijednost in vrijednosti.items():
        if naziv in headers:
            red[headers.index(naziv)] = vrijednost
    ws.append_row(red)

# ============================================================
# GRUPE / REZERVACIJE — booking sustav
# ============================================================

def postavi_tabove_booking(sheet):
    """Kreira 'Grupe' i 'Rezervacije' tabove ako ne postoje. Pokreni jednom ručno."""
    postojeci = [ws.title for ws in sheet.worksheets()]

    if "Grupe" not in postojeci:
        ws = sheet.add_worksheet(title="Grupe", rows=200, cols=11)
        ws.append_row([
            "grupa_id", "program", "dan", "vrijeme", "ucionica",
            "kapacitet", "tip", "aktivna", "admin_rezervirano", "redovni_nastavnik", "sezona"
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


def kreiraj_grupu(sheet, program, dan, vrijeme, ucionica, kapacitet, tip, aktivna=True, redovni_nastavnik=""):
    ws = sheet.worksheet("Grupe")
    grupa_id = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    ws.append_row([
        grupa_id, program, dan, vrijeme, ucionica,
        kapacitet, tip, "da" if aktivna else "ne", 0, str(redovni_nastavnik), SEZONA
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


def azuriraj_rezervaciju(sheet, row_number: int, novi_status: str, resetiraj_vrijeme: bool = False):
    ws = sheet.worksheet("Rezervacije")
    headers = ws.row_values(1)
    col_status = headers.index("status") + 1
    ws.update_cell(row_number, col_status, novi_status)

    if resetiraj_vrijeme and "vrijeme_rezervacije" in headers:
        col_vrijeme = headers.index("vrijeme_rezervacije") + 1
        ws.update_cell(row_number, col_vrijeme, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def dohvati_ucenika_po_id(df_ucenici: pd.DataFrame, ucenik_id: str):
    red = df_ucenici[df_ucenici["ucenik_id"] == ucenik_id]
    return red.iloc[0] if not red.empty else None


# ============================================================
# DOLASCI — Termini / Dolasci / Gostovanja / Zamjene log
# ============================================================

def postavi_tabove_dolasci(sheet):
    """Kreira Termini, Dolasci, Gostovanja, Zamjene log tabove ako ne postoje. Pokreni jednom ručno."""
    postojeci = [ws.title for ws in sheet.worksheets()]

    if "Termini" not in postojeci:
        ws = sheet.add_worksheet(title="Termini", rows=1000, cols=6)
        ws.append_row(["termin_id", "grupa_id", "datum", "nastavnik_odrzao", "sezona"])

    if "Dolasci" not in postojeci:
        ws = sheet.add_worksheet(title="Dolasci", rows=5000, cols=8)
        ws.append_row(["dolazak_id", "termin_id", "grupa_id", "ucenik_id", "ime_djeteta", "status", "sezona"])

    if "Gostovanja" not in postojeci:
        ws = sheet.add_worksheet(title="Gostovanja", rows=500, cols=8)
        ws.append_row(["gostovanje_id", "datum", "ucenik_id", "ime_djeteta", "maticna_grupa", "grupa_gostovanja", "sezona"])

    if "Zamjene log" not in postojeci:
        ws = sheet.add_worksheet(title="Zamjene log", rows=500, cols=6)
        ws.append_row(["datum", "grupa_id", "redovni_nastavnik", "zamjena_nastavnik", "razlog", "iznos_obracuna"])


def load_termini(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Termini"))


def load_dolasci(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Dolasci"))


def load_gostovanja(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Gostovanja"))


def pronadji_ili_kreiraj_termin(sheet, grupa_id: str, datum: str, nastavnik_odrzao: str, redovni_nastavnik: str) -> str:
    """Vraća termin_id za (grupa_id, datum) - reuse ako već postoji (npr. nastavnik uređuje isti dan),
    inače kreira novi. Ako nastavnik_odrzao != redovni_nastavnik, upisuje u Zamjene log (samo jednom)."""
    ws_termini = sheet.worksheet("Termini")
    postojeci = ws_termini.get_all_records()
    headers = ws_termini.row_values(1)

    for i, red in enumerate(postojeci, start=2):
        if str(red.get("grupa_id")) == str(grupa_id) and str(red.get("datum")) == str(datum):
            # Termin već postoji — ažuriraj nastavnika ako se promijenio
            if str(red.get("nastavnik_odrzao")) != str(nastavnik_odrzao):
                col = headers.index("nastavnik_odrzao") + 1
                ws_termini.update_cell(i, col, str(nastavnik_odrzao))
                _mozda_upisi_zamjenu(sheet, grupa_id, datum, redovni_nastavnik, nastavnik_odrzao)
            return red.get("termin_id")

    # Novi termin
    termin_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    ws_termini.append_row([termin_id, str(grupa_id), str(datum), str(nastavnik_odrzao), SEZONA])

    if str(nastavnik_odrzao) != str(redovni_nastavnik):
        _mozda_upisi_zamjenu(sheet, grupa_id, datum, redovni_nastavnik, nastavnik_odrzao)

    return termin_id


def _mozda_upisi_zamjenu(sheet, grupa_id, datum, redovni_nastavnik, zamjena_nastavnik):
    ws = sheet.worksheet("Zamjene log")
    postojeci = ws.get_all_records()
    for red in postojeci:
        if str(red.get("grupa_id")) == str(grupa_id) and str(red.get("datum")) == str(datum):
            return  # već zabilježeno, ne dupliciraj
    ws.append_row([str(datum), str(grupa_id), str(redovni_nastavnik), str(zamjena_nastavnik), "", ""])


def spremi_dolazak(sheet, termin_id: str, grupa_id: str, ucenik_id: str, ime_djeteta: str, status: str):
    """Upsert - ako već postoji zapis za (termin_id, ucenik_id), ažurira status umjesto duplog upisa.
    NAPOMENA: koristi spremi_cijeli_termin() za spremanje više učenika odjednom - puno manje API poziva."""
    ws = sheet.worksheet("Dolasci")
    postojeci = ws.get_all_records()
    headers = ws.row_values(1)

    for i, red in enumerate(postojeci, start=2):
        if str(red.get("termin_id")) == str(termin_id) and str(red.get("ucenik_id")) == str(ucenik_id):
            col = headers.index("status") + 1
            ws.update_cell(i, col, str(status))
            return

    dolazak_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    ws.append_row([dolazak_id, str(termin_id), str(grupa_id), str(ucenik_id), str(ime_djeteta), str(status), SEZONA])


def spremi_cijeli_termin(sheet, grupa_id, datum, nastavnik_odrzao, redovni_nastavnik, roster_zapisi, gosti_zapisi):
    """Sprema termin + sve dolaske (roster i goste) u minimalnom broju API poziva - jedan Save klik = par poziva, ne desetci.
    roster_zapisi / gosti_zapisi = liste dictova: {"ucenik_id":..., "ime_djeteta":..., "status":..., "maticna_grupa": (samo gosti)}"""

    # --- 1) Termin: jedan get_all_records + jedan append/update ---
    ws_termini = sheet.worksheet("Termini")
    termini_postojeci = ws_termini.get_all_records()
    termini_headers = ws_termini.row_values(1)

    termin_id = None
    for i, red in enumerate(termini_postojeci, start=2):
        if str(red.get("grupa_id")) == str(grupa_id) and str(red.get("datum")) == str(datum):
            termin_id = red.get("termin_id")
            if str(red.get("nastavnik_odrzao")) != str(nastavnik_odrzao):
                col = termini_headers.index("nastavnik_odrzao") + 1
                ws_termini.update_cell(i, col, str(nastavnik_odrzao))
            break

    if termin_id is None:
        termin_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        ws_termini.append_row([termin_id, str(grupa_id), str(datum), str(nastavnik_odrzao), SEZONA])

    if str(nastavnik_odrzao) != str(redovni_nastavnik):
        _mozda_upisi_zamjenu(sheet, grupa_id, datum, redovni_nastavnik, nastavnik_odrzao)

    # --- 2) Dolasci: jedan get_all_records, pa batch update + batch append ---
    ws_dolasci = sheet.worksheet("Dolasci")
    dolasci_postojeci = ws_dolasci.get_all_records()
    dolasci_headers = ws_dolasci.row_values(1)
    col_status = dolasci_headers.index("status") + 1

    postojeci_lookup = {}
    for i, red in enumerate(dolasci_postojeci, start=2):
        if str(red.get("termin_id")) == str(termin_id):
            postojeci_lookup[str(red.get("ucenik_id"))] = i

    svi_zapisi = list(roster_zapisi) + list(gosti_zapisi)

    batch_update_podaci = []
    novi_redovi = []
    for z in svi_zapisi:
        uid = str(z["ucenik_id"])
        if uid in postojeci_lookup:
            redak = postojeci_lookup[uid]
            batch_update_podaci.append({
                "range": gspread.utils.rowcol_to_a1(redak, col_status),
                "values": [[str(z["status"])]],
            })
        else:
            dolazak_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
            novi_redovi.append([dolazak_id, str(termin_id), str(grupa_id), uid, str(z["ime_djeteta"]), str(z["status"]), SEZONA])

    if batch_update_podaci:
        ws_dolasci.batch_update(batch_update_podaci)
    if novi_redovi:
        ws_dolasci.append_rows(novi_redovi)

    # --- 3) Gostovanja: jedan get_all_records, pa batch append (samo novi) ---
    if gosti_zapisi:
        ws_gost = sheet.worksheet("Gostovanja")
        gost_postojeci = ws_gost.get_all_records()
        gost_postojeci_set = {
            (str(r.get("datum")), str(r.get("ucenik_id")), str(r.get("grupa_gostovanja")))
            for r in gost_postojeci
        }
        novi_gosti = []
        for z in gosti_zapisi:
            kljuc = (str(datum), str(z["ucenik_id"]), str(grupa_id))
            if kljuc not in gost_postojeci_set:
                gostovanje_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
                novi_gosti.append([
                    gostovanje_id, str(datum), str(z["ucenik_id"]), str(z["ime_djeteta"]),
                    str(z["maticna_grupa"]), str(grupa_id), SEZONA
                ])
        if novi_gosti:
            ws_gost.append_rows(novi_gosti)

    return termin_id


def dodaj_gostovanje(sheet, datum: str, ucenik_id: str, ime_djeteta: str, maticna_grupa: str, grupa_gostovanja: str):
    ws = sheet.worksheet("Gostovanja")
    postojeci = ws.get_all_records()
    for red in postojeci:
        if (
            str(red.get("datum")) == str(datum)
            and str(red.get("ucenik_id")) == str(ucenik_id)
            and str(red.get("grupa_gostovanja")) == str(grupa_gostovanja)
        ):
            return  # već zabilježeno ovaj dan za ovu grupu, ne dupliciraj
    gostovanje_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    ws.append_row([gostovanje_id, str(datum), str(ucenik_id), str(ime_djeteta), str(maticna_grupa), str(grupa_gostovanja), SEZONA])


def roster_grupe(df_rezervacije: pd.DataFrame, grupa_id: str) -> pd.DataFrame:
    """Potvrđeni učenici (platili, mjesto sigurno) za tu grupu - službeni roster za dolaske."""
    if df_rezervacije.empty:
        return df_rezervacije
    return df_rezervacije[
        (df_rezervacije["grupa_id"] == grupa_id) & (df_rezervacije["status"] == "Potvrđeno")
    ]


def izgradi_grid_dolazaka(df_dolasci: pd.DataFrame, df_termini: pd.DataFrame, grupa_id: str):
    """Vraća (grid_df, nastavnici_po_datumu) za pregled - redovi=učenici, stupci=datumi."""
    if df_dolasci.empty or df_termini.empty:
        return pd.DataFrame(), {}

    termini_grupe = df_termini[df_termini["grupa_id"] == grupa_id]
    if termini_grupe.empty:
        return pd.DataFrame(), {}

    termin_id_u_datum = dict(zip(termini_grupe["termin_id"], termini_grupe["datum"]))
    nastavnici_po_datumu = dict(zip(termini_grupe["datum"], termini_grupe["nastavnik_odrzao"]))

    dolasci_grupe = df_dolasci[df_dolasci["termin_id"].isin(termini_grupe["termin_id"])].copy()
    if dolasci_grupe.empty:
        return pd.DataFrame(), nastavnici_po_datumu

    dolasci_grupe["datum"] = dolasci_grupe["termin_id"].map(termin_id_u_datum)

    ikone = {"1": "✅", "0": "❌", "2": "💻"}
    dolasci_grupe["prikaz"] = dolasci_grupe["status"].astype(str).map(ikone).fillna("")

    grid = dolasci_grupe.pivot_table(
        index="ime_djeteta", columns="datum", values="prikaz", aggfunc="first", fill_value=""
    )
    # Sortiraj stupce kronološki
    grid = grid[sorted(grid.columns)]
    return grid, nastavnici_po_datumu


# --- Bilješke / povijest kontakta + follow-up ---

def postavi_tabove_biljeske(sheet):
    """Kreira 'Biljeske' tab ako ne postoji. Pokreni jednom ručno (gumb u sidebaru)."""
    nazivi_tabova = [ws.title for ws in sheet.worksheets()]
    if "Biljeske" not in nazivi_tabova:
        ws = sheet.add_worksheet(title="Biljeske", rows=1000, cols=6)
        ws.append_row(["biljeska_id", "ucenik_id", "datum", "autor", "tekst", "sljedeci_kontakt"])


def load_biljeske(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Biljeske"))


def dodaj_biljesku(sheet, ucenik_id: str, autor: str, tekst: str, sljedeci_kontakt: str = ""):
    ws = sheet.worksheet("Biljeske")
    biljeska_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    ws.append_row([
        biljeska_id,
        str(ucenik_id),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        str(autor),
        str(tekst),
        str(sljedeci_kontakt),
    ])


# --- Obitelj (braća/sestre) — poveznica umjesto spajanja u jedan zapis ---

def osiguraj_stupac_povezani_ucenici(sheet):
    """Dodaje stupac 'povezani_ucenici' na Učenici tab ako ne postoji (na desni kraj headera)."""
    ws = sheet.worksheet("Učenici")
    headers = ws.row_values(1)
    if "povezani_ucenici" not in headers:
        ws.update_cell(1, len(headers) + 1, "povezani_ucenici")


def poveci_kao_obitelj(sheet, ucenik_id_1: str, ucenik_id_2: str):
    """Povezuje dva zapisa kao braću/sestre (dvosmjerno), bez spajanja u jedan zapis.
    Zahtijeva stupac 'povezani_ucenici' na Učenici tabu (gumb 'Dodaj povezani_ucenici stupac')."""
    ws = sheet.worksheet("Učenici")
    headers = ws.row_values(1)
    if "povezani_ucenici" not in headers:
        raise ValueError("Nedostaje stupac 'povezani_ucenici' na Učenici tabu — klikni prvo gumb za njegovo dodavanje.")
    col = headers.index("povezani_ucenici") + 1
    ucenici = ws.get_all_records()

    def dodaj_vezu(ciljni_id, novi_id):
        for i, red in enumerate(ucenici, start=2):
            if red.get("ucenik_id") == ciljni_id:
                trenutno = str(red.get("povezani_ucenici", "")).strip()
                popis = [x.strip() for x in trenutno.split(",") if x.strip()]
                if novi_id not in popis:
                    popis.append(novi_id)
                ws.update_cell(i, col, ", ".join(popis))
                return

    dodaj_vezu(ucenik_id_1, ucenik_id_2)
    dodaj_vezu(ucenik_id_2, ucenik_id_1)


# ============================================================
# INSTRUKCIJE — individualne/male-grupne, NAMJERNO odvojeno od
# Upisi grupnih "Termini"/"Dolasci" (druga poslovna logika: naplata
# po terminu, ne po sezonskom paketu; dolazak jednog djeteta, ne
# cijele grupe). Vidi CAKI_MASTER_CRM razgovor o Instrukcije CRM-u.
# ============================================================

def postavi_tab_instrukcije(sheet):
    """Kreira 'Instrukcije_termini' tab ako ne postoji. Pokreni jednom ručno."""
    postojeci = [ws.title for ws in sheet.worksheets()]

    if "Instrukcije_termini" not in postojeci:
        ws = sheet.add_worksheet(title="Instrukcije_termini", rows=2000, cols=13)
        ws.append_row([
            "termin_id", "ucenik_id", "ime_djeteta", "nastavnik", "datum",
            "duljina_min", "oblik", "broj_ucenika_u_grupi",
            "placeno_oznaka_prof", "uplata_potvrdjena_admin",
            "napomena_interna", "napomena_javna", "sezona",
        ])


def load_instrukcije(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Instrukcije_termini"))


def dodaj_instrukciju_termin(
    sheet,
    ucenik_id: str,
    ime_djeteta: str,
    nastavnik: str,
    datum: str,
    duljina_min,
    oblik: str,
    broj_ucenika_u_grupi,
    placeno_oznaka_prof: str,
    napomena_interna: str = "",
    napomena_javna: str = "",
    predmet: str = "",
    stupanj_skolovanja: str = "",
    sifra: str = "",
    cijena_termina=None,
    nacin_naplate: str | None = None,
) -> str:
    """Dodaje novi termin instrukcija. Poziva ga i instruktor (nastavnik = iz
    logina, ne uređuje se ručno) i admin (nastavnik bira sam iz padajućeg popisa).
    'uplata_potvrdjena_admin' UVIJEK kreće prazno ('Ne') — to polje smije
    mijenjati isključivo admin preko azuriraj_instrukciju(), nikad ovaj poziv.

    23.9.2026.: piše po NAZIVU stupca (ne pozicijski), pa radi i prije i poslije
    dodavanja naplatnih stupaca (osiguraj_stupce_instrukcije_naplata). Naplatna polja:
      - sifra / cijena_termina: ako nisu zadani, računaju se (odredi_sifru_instrukcije,
        izracunaj_cijenu_termina iz Cjenika). Ako Cjenik još ne postoji, cijena ostaje
        prazna — mjesečni obračun je izračuna kasnije.
      - nacin_naplate: None = naslijedi zadnju vrijednost za tog učenika i predmet
        (§23.3.2), a ako je nema → "Jednokratno". Instruktor ga NE bira (financijska odluka).
    """
    ws = sheet.worksheet("Instrukcije_termini")
    headers = ws.row_values(1)
    termin_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))

    ima_naplatu = "status_obracuna" in headers
    if ima_naplatu:
        if not sifra:
            sifra = odredi_sifru_instrukcije(oblik, predmet)
        if cijena_termina in (None, ""):
            try:
                cijena_termina = izracunaj_cijenu_termina(load_cjenik(sheet), sifra, duljina_min)
            except Exception:
                cijena_termina = None
        if nacin_naplate is None:
            nacin_naplate = zadnji_nacin_naplate(_load_worksheet_df(ws), ucenik_id, predmet)

    vrijednosti = {
        "termin_id": termin_id,
        "ucenik_id": str(ucenik_id),
        "ime_djeteta": str(ime_djeteta),
        "nastavnik": str(nastavnik),
        "datum": str(datum),
        "duljina_min": str(duljina_min),
        "oblik": str(oblik),
        "broj_ucenika_u_grupi": str(broj_ucenika_u_grupi or ""),
        "placeno_oznaka_prof": str(placeno_oznaka_prof),
        "uplata_potvrdjena_admin": "Ne",
        "napomena_interna": str(napomena_interna),
        "napomena_javna": str(napomena_javna),
        "sezona": SEZONA,
        "predmet": str(predmet),
        "stupanj_skolovanja": str(stupanj_skolovanja),
        "sifra": str(sifra),
        "nacin_naplate": str(nacin_naplate or ""),
        "cijena_termina": "" if cijena_termina is None else float(cijena_termina),
        "status_obracuna": "Neobračunato",
        "dokument_id": "",
    }
    red = ["" for _ in headers]
    for naziv, vrijednost in vrijednosti.items():
        if naziv in headers:
            red[headers.index(naziv)] = vrijednost
    ws.append_row(red)
    return termin_id


def azuriraj_instrukciju(sheet, row_number: int, polja: dict):
    """Generičko uređivanje retka (isti obrazac kao azuriraj_ucenika).
    polja = {"uplata_potvrdjena_admin": "Da", ...}
    NAPOMENA za UI sloj: stranica za instruktore smije zvati ovo SAMO za
    polja koja instruktor smije mijenjati (napomena_interna, napomena_javna,
    placeno_oznaka_prof) — nikad za uplata_potvrdjena_admin. To ograničenje
    nije tehnički nametnuto ovdje (funkcija je generička), nego mora biti
    nametnuto u Streamlit sučelju (ne nuditi to polje instruktoru u formi)."""
    ws = sheet.worksheet("Instrukcije_termini")
    headers = ws.row_values(1)
    for naziv_polja, vrijednost in polja.items():
        if naziv_polja in headers:
            col = headers.index(naziv_polja) + 1
            ws.update_cell(row_number, col, vrijednost)


def obrisi_instrukciju(sheet, row_number: int):
    """Trajno brisanje retka termina. Samo admin."""
    ws = sheet.worksheet("Instrukcije_termini")
    ws.delete_rows(row_number)


def pretrazi_ucenike(df_ucenici: pd.DataFrame, upit: str) -> pd.DataFrame:
    """Pretraga po imenu ili ucenik_id. Pretraga po školi NAMJERNO izostavljena —
    'skola' polje ne postoji na Učenici tabu, odgođeno na Cakijev zahtjev."""
    if not upit:
        return df_ucenici
    return df_ucenici[
        df_ucenici["ime_djeteta"].str.contains(upit, case=False, na=False)
        | df_ucenici["ucenik_id"].str.contains(upit, case=False, na=False)
    ]


# ============================================================
# NASTAVNICI — upravljanje imenima/šiframa kroz Sheet, ne kroz kod.
# NASTAVNICI konstanta (na vrhu fajla) ostaje SAMO kao početni seed pri
# prvom kreiranju taba i kao fallback ako tab još ne postoji — nakon
# postavljanja, sve stranice čitaju popis odavde, ne iz konstante.
# ============================================================

def postavi_tab_nastavnici(sheet):
    """Kreira 'Nastavnici' tab ako ne postoji, seed-an trenutnom NASTAVNICI
    konstantom sa privremenom lozinkom (svatko je treba promijeniti pri prvom
    korištenju). Pokreni jednom ručno."""
    postojeci = [ws.title for ws in sheet.worksheets()]
    if "Nastavnici" not in postojeci:
        ws = sheet.add_worksheet(title="Nastavnici", rows=50, cols=3)
        ws.append_row(["ime", "lozinka", "aktivan"])
        for ime in NASTAVNICI:
            ws.append_row([ime, "promijeni123", "Da"])


def load_nastavnici(sheet) -> pd.DataFrame:
    return _load_worksheet_df(sheet.worksheet("Nastavnici"))


def nastavnici_aktivni(df_nastavnici: pd.DataFrame) -> list:
    """Popis imena AKTIVNIH nastavnika za padajuće izbornike — zamjena za staru
    hardkodiranu NASTAVNICI konstantu. Fallback na konstantu ako tab još nije
    kreiran (prije prvog klika na setup gumb), da ništa ne pukne u međuvremenu."""
    if df_nastavnici.empty:
        return NASTAVNICI
    aktivni = df_nastavnici[df_nastavnici["aktivan"].astype(str).str.lower() == "da"]
    return aktivni["ime"].tolist() or NASTAVNICI


def provjeri_lozinku_instruktora(df_nastavnici: pd.DataFrame, ime: str, lozinka: str) -> bool:
    """True samo ako ime+lozinka odgovaraju i nastavnik je trenutno aktivan —
    deaktiviran (bivši) nastavnik se više ne može prijaviti čak i sa starom lozinkom."""
    red = df_nastavnici[
        (df_nastavnici["ime"] == ime)
        & (df_nastavnici["lozinka"] == lozinka)
        & (df_nastavnici["aktivan"].astype(str).str.lower() == "da")
    ]
    return not red.empty


def dodaj_nastavnika(sheet, ime: str, lozinka: str):
    ws = sheet.worksheet("Nastavnici")
    ws.append_row([str(ime), str(lozinka), "Da"])


def azuriraj_nastavnika(sheet, row_number: int, polja: dict):
    """polja = {"lozinka": "...", "aktivan": "Ne", ...} — isti generički obrazac
    kao azuriraj_ucenika/azuriraj_instrukciju."""
    ws = sheet.worksheet("Nastavnici")
    headers = ws.row_values(1)
    for naziv, vrijednost in polja.items():
        if naziv in headers:
            col = headers.index(naziv) + 1
            ws.update_cell(row_number, col, vrijednost)


# ============================================================
# SOLO — dva pravna subjekta, ručan odabir po prijavi (14.9.2026.)
# "Caki obrt za poduke" (treći subjekt) namjerno izostavljen — nije povezan.
# ============================================================

SOLO_SUBJEKTI = ["CAKI centar d.o.o.", "Caki poduka obrt"]


def postavi_solo_racun(sheet, row_number: int, subjekt: str):
    """Ručno postavlja koji pravni subjekt izdaje Solo ponudu za taj Prijave redak.
    Prazno/nepostavljeno = solo_ponuda_i_mail.gs preskače redak dok se ne odabere."""
    ws = sheet.worksheet("Prijave")
    headers = ws.row_values(1)
    if "solo_racun" not in headers:
        raise ValueError("Stupac 'solo_racun' ne postoji u Prijave tabu — dodaj ga ručno u header.")
    col = headers.index("solo_racun") + 1
    ws.update_cell(row_number, col, subjekt)


def posalji_ponudu_odmah(sheet, row_number: int):
    """Postavlja status_kontakta na 'Potvrdio' i posalji_nakon na sada — postojeći
    Apps Script trigger (provjeriIPosaljiPonude, svakih ~15 min) automatski pošalje
    Solo ponudu za taj redak čim ga sljedeći put obradi. Ne duplicira Solo API poziv
    u Pythonu — samo "gura" redak u istu, već testiranu automatiku."""
    ws = sheet.worksheet("Prijave")
    headers = ws.row_values(1)
    col_status = headers.index("status_kontakta") + 1
    col_posalji = headers.index("posalji_nakon") + 1
    ws.update_cell(row_number, col_status, "Potvrdio")
    ws.update_cell(row_number, col_posalji, sada_zagreb().strftime("%Y-%m-%d %H:%M:%S"))


def oznaci_placeno_gotovinom(sheet, row_number: int):
    """Označava redak kao plaćen gotovinom — solo_poslano='Da' trajno preskače
    automatsko slanje Solo ponude/računa za taj redak, uz zabilješku u napomeni."""
    ws = sheet.worksheet("Prijave")
    headers = ws.row_values(1)
    col_solo_poslano = headers.index("solo_poslano") + 1
    ws.update_cell(row_number, col_solo_poslano, "Da")

    if "napomena" in headers:
        col_napomena = headers.index("napomena") + 1
        trenutna = ws.cell(row_number, col_napomena).value or ""
        oznaka = f"💵 Plaćeno gotovinom (ručno, {datetime.now().strftime('%d.%m.%Y.')})"
        nova = f"{trenutna} | {oznaka}" if trenutna else oznaka
        ws.update_cell(row_number, col_napomena, nova)


# ============================================================
# PDF IZVOZ — reusable helper (koristi ga "Uredi učenika" izvoz,
# može ga koristiti i bilo koji budući izvoz popisa)
# ============================================================

_DEJAVU_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_DEJAVU_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_font_registriran = False


def _osiguraj_pdf_font() -> bool:
    """Registrira DejaVuSans (podržava č,ć,š,đ,ž ispravno — ugrađeni Helvetica ne
    podržava đ/č/ć) ako je dostupan na sustavu. Streamlit Cloud treba paket
    'fonts-dejavu-core' u packages.txt. Ako font nije nađen, tiho vraća False —
    pozivatelj onda koristi Helvetica (PDF se svejedno generira, dijakritici
    mogu biti krivi, ali app ne puca)."""
    global _font_registriran
    if _font_registriran:
        return True
    if os.path.exists(_DEJAVU_REGULAR):
        pdfmetrics.registerFont(TTFont("DejaVuSans", _DEJAVU_REGULAR))
        if os.path.exists(_DEJAVU_BOLD):
            pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", _DEJAVU_BOLD))
        _font_registriran = True
        return True
    return False


def izgradi_pdf_izvoza(naslov: str, stupci: list, retci: list) -> bytes:
    """stupci = ["Ime djeteta", "Mobitel roditelja", ...] (već prevedeni nazivi za prikaz).
    retci = [[vrijednost1, vrijednost2, ...], ...] (isti redoslijed kao stupci).
    Vraća PDF kao bytes — spremno za st.download_button. Landscape A4 jer popisi
    učenika lako imaju 4-6 stupaca."""
    ima_dejavu = _osiguraj_pdf_font()
    font_normal = "DejaVuSans" if ima_dejavu else "Helvetica"
    font_bold = "DejaVuSans-Bold" if ima_dejavu else "Helvetica-Bold"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
    )

    stilovi = getSampleStyleSheet()
    stil_naslov = stilovi["Title"]
    stil_naslov.fontName = font_bold

    stil_celija = stilovi["Normal"]
    stil_celija.fontName = font_normal
    stil_celija.fontSize = 8
    stil_celija.leading = 10

    stil_zaglavlje = stilovi["Normal"].clone("zaglavlje")
    stil_zaglavlje.fontName = font_bold
    stil_zaglavlje.fontSize = 8
    stil_zaglavlje.textColor = colors.white

    zaglavlje_red = [Paragraph(str(s), stil_zaglavlje) for s in stupci]
    podaci = [zaglavlje_red]
    for redak in retci:
        podaci.append([Paragraph(str(v) if v not in (None, "nan") else "", stil_celija) for v in redak])

    tablica = Table(podaci, repeatRows=1)
    tablica.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2a3f5f")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))

    elementi = [
        Paragraph(naslov, stil_naslov),
        Spacer(1, 0.3 * cm),
        Paragraph(f"Generirano: {datetime.now().strftime('%d.%m.%Y. %H:%M')}", stil_celija),
        Spacer(1, 0.5 * cm),
        tablica,
    ]
    doc.build(elementi)
    return buffer.getvalue()


# ============================================================
# FINANCIJE — Cjenik, Racuni_i_ponude ("financijska kartica"), Instrukcije naplata
# (§22 / §23.2 / §23.3 MASTER CRM, 23.9.2026.)
#
# Podjela posla (namjerno):
#   Apps Script (CAKI_financije.gs) — sve što ZOVE SOLO: sinkronizacija Cjenika,
#       slanje odobrenih dokumenata, automatski nacrti (Matura, mjesečne Instrukcije).
#       Solo tokeni žive samo tamo (Script Properties), nikad u Streamlitu.
#   Python (ovdje) — sve što radi ČOVJEK u admin panelu: pregled i uređivanje nacrta,
#       podjela na rate, odobravanje ("Odobreno" → Apps Script šalje u roku ~5 min),
#       odbacivanje, označavanje plaćenog, jednokratni obračun Instrukcija.
# ============================================================

CJENIK_TAB = "Cjenik"
LEDGER_TAB = "Racuni_i_ponude"

STATUSI_DOKUMENTA = ["Nacrt", "Odobreno", "Šalje se…", "Poslano", "Greška", "Plaćeno", "Otkazano", "Isteklo"]
NACINI_UPLATE = {1: "Transakcijski račun", 2: "Gotovina", 3: "Kartice", 4: "Ček", 5: "Ostalo"}

NACINI_NAPLATE_INSTRUKCIJA = ["Jednokratno", "Mjesečno"]
# Fakultet NAMJERNO izostavljen — fakultetske instrukcije parkirane na Cakijev zahtjev (§23.10)
STUPNJEVI_SKOLOVANJA_INSTR = ["Osnovna škola", "Srednja škola"]
# Popis predmeta za padajući izbornik — slobodno mijenjati (samo tekst, ne utječe na cijenu,
# osim stranih jezika i međunarodnih ispita, v. odredi_sifru_instrukcije)
INSTRUKCIJE_PREDMETI = [
    "Matematika", "Fizika", "Kemija", "Biologija", "Hrvatski", "Informatika",
    "Engleski", "Njemački", "Talijanski", "Francuski", "Španjolski",
    "Međunarodni ispit (SAT/IB/Cambridge…)", "Ostalo",
]
INSTRUKCIJE_STRANI_JEZICI = {"Engleski", "Njemački", "Talijanski", "Francuski", "Španjolski"}
INSTRUKCIJE_SIFRE = {
    "INSTR-IND": "Individualna",
    "INSTR-GRU": "Grupna (cijena po učeniku)",
    "INSTR-STRANI": "Strani jezik",
    "INSTR-MEDJ": "Međunarodni ispit",
}
INSTR_IND_90_FIKSNO = 40.0  # §23.3.1 — koristi se samo ako Cjenik nema upisan iznimka_90min
INSTRUKCIJE_NAPLATNI_STUPCI = [
    "predmet", "stupanj_skolovanja", "sifra", "nacin_naplate",
    "cijena_termina", "status_obracuna", "dokument_id",
]
MJESECI_HR = ["siječanj", "veljača", "ožujak", "travanj", "svibanj", "lipanj",
              "srpanj", "kolovoz", "rujan", "listopad", "studeni", "prosinac"]


# --- novac: interno UVIJEK cijeli centi, nikad float zbrajanje ---

def u_cente(v):
    """7 / 7.5 / "7,00" / "1.234,50" / "1,234.50" / "" → cijeli broj centi ili None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and math.isnan(v):
            return None
        return int(math.floor(v * 100 + 0.5))
    s = str(v).strip().replace(" ", "").replace("€", "")
    if not s:
        return None
    zarez, tocka = s.rfind(","), s.rfind(".")
    s = s.replace(".", "").replace(",", ".") if zarez > tocka else s.replace(",", "")
    try:
        return int(math.floor(float(s) * 100 + 0.5))
    except ValueError:
        return None


def centi_u_tekst(c) -> str:
    """36075 → '360,75' (hrvatski prikaz i Solo format)."""
    return "" if c is None else f"{c / 100:.2f}".replace(".", ",")


def konacna_cijena_centi(bazna_centi, popust_postotak) -> int:
    """Ista formula kao Apps Script: Math.round(bazna * (1 - popust/100))."""
    return int(math.floor(bazna_centi * (1 - float(popust_postotak or 0) / 100) + 0.5))


# --- učitavanje (opcionalni tabovi: prazan DataFrame dok ih Apps Script ne kreira) ---

def _load_df_neformatirano(ws) -> pd.DataFrame:
    """Kao _load_worksheet_df, ali brojeve vraća kao brojeve (ne '360,75' ovisno o jeziku Sheeta)."""
    headers = ws.row_values(1)
    records = ws.get_all_records(value_render_option="UNFORMATTED_VALUE")
    df = pd.DataFrame(records) if records else pd.DataFrame(columns=headers)
    df["_row"] = range(2, len(df) + 2)
    return df


def load_cjenik(sheet) -> pd.DataFrame:
    try:
        return _load_df_neformatirano(sheet.worksheet(CJENIK_TAB))
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame(columns=["subjekt", "sifra", "cijena", "_row"])


def load_racuni(sheet) -> pd.DataFrame:
    try:
        return _load_df_neformatirano(sheet.worksheet(LEDGER_TAB))
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame(columns=["dokument_id", "ucenik_id", "status", "_row"])


def _azuriraj_polja(ws, row_number: int, polja: dict, headers: list | None = None):
    """Više ćelija jednog retka u JEDNOM API pozivu, RAW (Sheets ne 'pametuje' vrijednosti)."""
    headers = headers or ws.row_values(1)
    data = []
    for naziv, vrijednost in polja.items():
        if naziv not in headers:
            raise ValueError(f"Stupac '{naziv}' ne postoji u tabu {ws.title}")
        data.append({
            "range": gspread.utils.rowcol_to_a1(row_number, headers.index(naziv) + 1),
            "values": [[vrijednost]],
        })
    if data:
        ws.batch_update(data, raw=True)


def _dodaj_red_po_nazivu(ws, vrijednosti: dict, headers: list | None = None):
    headers = headers or ws.row_values(1)
    ws.append_row([vrijednosti.get(h, "") for h in headers], value_input_option="RAW")


# --- Cjenik i cijena Instrukcija ---

def cijena_iz_cjenika(df_cjenik: pd.DataFrame, sifra: str, subjekt: str = ""):
    """Redak Cjenika za šifru (prvo istog subjekta, inače bilo kojeg) kao dict, ili None."""
    if df_cjenik is None or df_cjenik.empty or "sifra" not in df_cjenik.columns:
        return None
    kandidati = df_cjenik[df_cjenik["sifra"].astype(str) == str(sifra)]
    kandidati = kandidati[kandidati["cijena"].apply(lambda v: u_cente(v) is not None)]
    if kandidati.empty:
        return None
    if subjekt and "subjekt" in kandidati.columns and (kandidati["subjekt"] == subjekt).any():
        kandidati = kandidati[kandidati["subjekt"] == subjekt]
    return kandidati.iloc[0].to_dict()


def naziv_iz_sola(df_cjenik: pd.DataFrame, sifra: str, je90: bool = False) -> str:
    """Točan naziv stavke iz Solo kataloga (Cjenik). Za individualne instrukcije od 90 min koristi
    stavku sa šifrom INSTR-IND-90 ako postoji u Solu, inače naziv stavke INSTR-IND."""
    if je90 and sifra == "INSTR-IND":
        red90 = cijena_iz_cjenika(df_cjenik, "INSTR-IND-90")
        if red90 and str(red90.get("opis", "")).strip():
            return str(red90["opis"]).strip()
    red = cijena_iz_cjenika(df_cjenik, sifra)
    return str((red or {}).get("opis", "") or "").strip() or "Instrukcije"


def odredi_sifru_instrukcije(oblik: str, predmet: str) -> str:
    """Pravilo za zadanu šifru (admin je može promijeniti po terminu):
    međunarodni ispit → INSTR-MEDJ; strani jezik → INSTR-STRANI; grupa → INSTR-GRU; inače INSTR-IND."""
    predmet = str(predmet or "")
    if predmet.startswith("Međunarodni ispit"):
        return "INSTR-MEDJ"
    if predmet in INSTRUKCIJE_STRANI_JEZICI:
        return "INSTR-STRANI"
    if str(oblik) == "Grupa":
        return "INSTR-GRU"
    return "INSTR-IND"


def izracunaj_cijenu_termina(df_cjenik: pd.DataFrame, sifra: str, duljina_min):
    """§23.3.1: satnica(sifra) × trajanje/60, linearno; iznimka INSTR-IND 90 min = 40 € fiksno.
    Satnica = Cjenik.cijena_po_satu ako je upisana, inače Cjenik.cijena (Solo stavka za 60 min).
    Vraća float (eura) ili None ako cijena nije poznata — NIKAD ne nagađa."""
    try:
        minuta = int(float(duljina_min))
    except (TypeError, ValueError):
        return None
    red = cijena_iz_cjenika(df_cjenik, sifra)
    if red is None or minuta <= 0:
        return None
    if minuta == 90:
        iznimka = u_cente(red.get("iznimka_90min"))
        if iznimka is not None:
            return iznimka / 100
        if sifra == "INSTR-IND":
            return INSTR_IND_90_FIKSNO
    satnica = u_cente(red.get("cijena_po_satu"))
    if satnica is None:
        satnica = u_cente(red.get("cijena"))
    return int(math.floor(satnica * minuta / 60 + 0.5)) / 100


def osiguraj_stupce_instrukcije_naplata(sheet) -> list:
    """Doda naplatne stupce (§23.3.2) na DESNI kraj Instrukcije_termini headera, ako ih nema.
    Postojeći retci dobivaju status_obracuna='Neobračunato' i nacin_naplate='Jednokratno'.
    Vraća popis dodanih stupaca. Sigurno za ponovno pokretanje."""
    ws = sheet.worksheet("Instrukcije_termini")
    headers = ws.row_values(1)
    nedostaju = [h for h in INSTRUKCIJE_NAPLATNI_STUPCI if h not in headers]
    if not nedostaju:
        return []
    if ws.col_count < len(headers) + len(nedostaju):
        ws.add_cols(len(headers) + len(nedostaju) - ws.col_count)
    prvi = len(headers) + 1
    ws.update(
        range_name=gspread.utils.rowcol_to_a1(1, prvi),
        values=[nedostaju],
        value_input_option="RAW",
    )
    headers = headers + nedostaju
    broj_redaka = len(ws.col_values(1))
    if broj_redaka > 1:
        zadano = {"status_obracuna": "Neobračunato", "nacin_naplate": "Jednokratno"}
        data = []
        for stupac, vrijednost in zadano.items():
            if stupac in nedostaju:
                c = headers.index(stupac) + 1
                data.append({
                    "range": f"{gspread.utils.rowcol_to_a1(2, c)}:{gspread.utils.rowcol_to_a1(broj_redaka, c)}",
                    "values": [[vrijednost]] * (broj_redaka - 1),
                })
        if data:
            ws.batch_update(data, raw=True)
    return nedostaju


def zadnji_nacin_naplate(df_instrukcije: pd.DataFrame, ucenik_id: str, predmet: str = "") -> str:
    """§23.3.2: novi termin nasljeđuje zadnji nacin_naplate za istog učenika (i predmet ako
    postoji takav termin). Zadano 'Jednokratno'."""
    if df_instrukcije is None or df_instrukcije.empty or "nacin_naplate" not in df_instrukcije.columns:
        return "Jednokratno"
    df = df_instrukcije[df_instrukcije["ucenik_id"] == ucenik_id]
    df = df[df["nacin_naplate"].isin(NACINI_NAPLATE_INSTRUKCIJA)]
    if predmet and "predmet" in df.columns and (df["predmet"] == predmet).any():
        df = df[df["predmet"] == predmet]
    return df.iloc[-1]["nacin_naplate"] if not df.empty else "Jednokratno"


# --- Racuni_i_ponude: stavke, provjere, odobravanje, rate ---

def parsiraj_stavke(tekst) -> list:
    try:
        stavke = json.loads(tekst) if tekst else []
        return stavke if isinstance(stavke, list) else []
    except (TypeError, ValueError):
        return []


def preracunaj_stavke(stavke: list) -> list:
    """Iz cijena_bazna + popust_postotak izračuna cijena_konacna (tekst '360,75') za svaku stavku.
    Popust je UVIJEK postotak po stavci — isto kako ga bilježi Solo."""
    rezultat = []
    for st in stavke:
        st = dict(st)
        st.pop("popust_iznos", None)
        bazna = u_cente(st.get("cijena_bazna"))
        popust = float(st.get("popust_postotak") or 0)
        st["popust_postotak"] = popust
        st["kolicina"] = st.get("kolicina") or 1
        st["cijena_bazna"] = centi_u_tekst(bazna) if bazna is not None else ""
        st["cijena_konacna"] = centi_u_tekst(konacna_cijena_centi(bazna, popust)) if bazna is not None else ""
        rezultat.append(st)
    return rezultat


def zbroj_stavki_centi(stavke: list) -> int:
    ukupno = 0
    for st in stavke:
        c = u_cente(st.get("cijena_konacna"))
        if c is not None:
            ukupno += c * int(float(st.get("kolicina") or 1))
    return ukupno


def provjeri_za_slanje(stavke: list, solo_racun: str, rate: list | None = None) -> list:
    """Vraća popis grešaka (prazan = smije se poslati). Rate: lista (iznos_centi, date)."""
    greske = []
    if solo_racun not in SOLO_SUBJEKTI:
        greske.append("Odaberi pravni subjekt (Solo račun).")
    if not stavke:
        greske.append("Dokument nema nijednu stavku.")
    for st in stavke:
        c = u_cente(st.get("cijena_konacna"))
        if c is None or c <= 0:
            greske.append(f"Stavka '{st.get('opis', '?')}' nema ispravnu cijenu.")
        if not str(st.get("opis", "")).strip():
            greske.append("Svaka stavka mora imati opis.")
        if not 0 <= float(st.get("popust_postotak") or 0) < 100:
            greske.append(f"Popust za '{st.get('opis', '?')}' mora biti između 0 i 100 %.")
    if rate is not None:
        if len(rate) < 2:
            greske.append("Plaćanje na rate treba barem 2 rate.")
        if any(iznos <= 0 for iznos, _ in rate):
            greske.append("Svaka rata mora biti veća od 0.")
        if sum(iznos for iznos, _ in rate) != zbroj_stavki_centi(stavke):
            greske.append(
                f"Zbroj rata ({centi_u_tekst(sum(i for i, _ in rate))} €) mora biti jednak ukupnom iznosu "
                f"({centi_u_tekst(zbroj_stavki_centi(stavke))} €)."
            )
        rokovi = [r for _, r in rate]
        if any(r is None for r in rokovi):
            greske.append("Svaka rata mora imati rok plaćanja.")
        elif rokovi != sorted(rokovi):
            greske.append("Rokovi rata moraju ići kronološki.")
    return greske


def predlozi_rate(ukupno_centi: int, broj_rata: int, prvi_rok: date) -> list:
    """Jednake rate (zadnja preuzima ostatak od zaokruživanja), rok svakih 30 dana."""
    osnovna = ukupno_centi // broj_rata
    rate = [osnovna] * broj_rata
    rate[-1] += ukupno_centi - osnovna * broj_rata
    return [(iznos, prvi_rok + timedelta(days=30 * k)) for k, iznos in enumerate(rate)]


def _mail_polja(headers: list, mail_predmet, mail_tekst) -> dict:
    """Uređeni mail sprema se samo ako tab već ima te stupce (dodaje ih postaviFinancije)."""
    if mail_tekst is None or "mail_tekst" not in headers:
        return {}
    return {"mail_predmet": str(mail_predmet or "")[:250], "mail_tekst": str(mail_tekst or "")}


def spremi_nacrt(sheet, row_number: int, stavke: list, solo_racun: str, nacin_uplate: int,
                 napomena: str, rok_placanja, mail_predmet=None, mail_tekst=None):
    """Sprema izmjene nacrta BEZ slanja (status ostaje Nacrt)."""
    stavke = preracunaj_stavke(stavke)
    ws = sheet.worksheet(LEDGER_TAB)
    headers = ws.row_values(1)
    _azuriraj_polja(ws, row_number, {**_mail_polja(headers, mail_predmet, mail_tekst), 
        "stavke_snapshot_json": json.dumps(stavke, ensure_ascii=False),
        "iznos_ukupno": zbroj_stavki_centi(stavke) / 100,
        "solo_racun": solo_racun if solo_racun in SOLO_SUBJEKTI else "",
        "nacin_uplate": int(nacin_uplate),
        "napomena": str(napomena or "")[:1000],
        "rok_placanja": rok_placanja.strftime("%Y-%m-%d") if rok_placanja else "",
    }, headers)


def odobri_dokument(sheet, red: dict, stavke: list, solo_racun: str, nacin_uplate: int,
                    napomena: str, rok_placanja, rate: list | None = None,
                    mail_predmet=None, mail_tekst=None) -> list:
    """Admin klikne "✅ Pošalji": dokument (ili više njih, ako su rate) dobiva status
    'Odobreno'. Stvarno slanje u Solo radi Apps Script posaljiOdobrene() u roku ~5 min.
    rate = None (jednokratno) ili lista (iznos_centi, rok: date).
    Vraća listu dokument_id. Baca ValueError s popisom grešaka ako provjera ne prođe."""
    stavke = preracunaj_stavke(stavke)
    greske = provjeri_za_slanje(stavke, solo_racun, rate)
    if greske:
        raise ValueError(" ".join(greske))

    ws = sheet.worksheet(LEDGER_TAB)
    headers = ws.row_values(1)
    row_number = int(red["_row"])

    # Svježa provjera — da nitko u međuvremenu nije već odobrio/odbacio isti dokument
    trenutni_status = ws.cell(row_number, headers.index("status") + 1).value
    if trenutni_status not in ("Nacrt", "Greška"):
        raise ValueError(f"Dokument je u međuvremenu promijenio status u '{trenutni_status}' — osvježi stranicu.")

    zajednicko = {
        **_mail_polja(headers, mail_predmet, mail_tekst),
        "solo_racun": solo_racun,
        "nacin_uplate": int(nacin_uplate),
        "napomena": str(napomena or "")[:1000],
        "greska_slanja": "",
    }
    stavke_json = json.dumps(stavke, ensure_ascii=False)

    if not rate:
        _azuriraj_polja(ws, row_number, dict(zajednicko, **{
            "stavke_snapshot_json": stavke_json,
            "iznos_ukupno": zbroj_stavki_centi(stavke) / 100,
            "rok_placanja": rok_placanja.strftime("%Y-%m-%d") if rok_placanja else "",
            "status": "Odobreno",
        }), headers)
        return [red["dokument_id"]]

    # --- Rate: svaka rata = zaseban Solo dokument (§22.4), svi odobreni ODJEDNOM ---
    grupa_id = "G-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    n = len(rate)
    opis_programa = ", ".join(str(st.get("opis", "")) for st in stavke)
    program = red.get("program_tip", "")
    dokumenti = []
    for k, (iznos, rok) in enumerate(rate, start=1):
        stavka_rate = [{
            "sifra": "RATA",
            # Točan naziv iz Sola + oznaka rate (bez vlastitih naziva programa)
            "opis": f"{opis_programa[:480]} (rata {k}/{n})",
            "kolicina": 1,
            "cijena_bazna": centi_u_tekst(iznos),
            "popust_postotak": 0,
            "cijena_konacna": centi_u_tekst(iznos),
        }]
        polja = dict(zajednicko, **{
            "stavke_snapshot_json": json.dumps(stavka_rate, ensure_ascii=False),
            "stavke_izvorno_json": stavke_json,
            "iznos_ukupno": iznos / 100,
            "rok_placanja": rok.strftime("%Y-%m-%d"),
            "rata_grupa_id": grupa_id,
            "rata_broj": k,
            "rata_ukupno_u_grupi": n,
            "status": "Odobreno",
        })
        if k == 1:
            # prva rata = postojeći redak (zadržava dokument_id i izvorni_redci)
            _azuriraj_polja(ws, row_number, polja, headers)
            dokumenti.append(red["dokument_id"])
        else:
            novi_id = f"{red['dokument_id']}-R{k}"
            _dodaj_red_po_nazivu(ws, dict(polja, **{
                "dokument_id": novi_id,
                "ucenik_id": red.get("ucenik_id", ""),
                "ime_djeteta": red.get("ime_djeteta", ""),
                "program_tip": program,
                "tip_dokumenta": red.get("tip_dokumenta", "Ponuda"),
                "izvorni_redci": "",  # izvorni retci vežu se samo uz 1. ratu (sprječava dvostruko brojanje)
                "datum_kreiranja": sada_zagreb().strftime("%Y-%m-%d %H:%M:%S"),
            }), headers)
            dokumenti.append(novi_id)
    return dokumenti


def ponovi_slanje(sheet, row_number: int):
    """Dokument u statusu 'Greška' (npr. Solo nije odgovorio) ponovno stavi u red za slanje."""
    ws = sheet.worksheet(LEDGER_TAB)
    _azuriraj_polja(ws, row_number, {"status": "Odobreno", "greska_slanja": ""})


def _termini_dokumenta(sheet, dokument_id: str):
    """(ws, headers, [row_number, ...]) Instrukcije termina vezanih uz dokument."""
    ws = sheet.worksheet("Instrukcije_termini")
    df = _load_worksheet_df(ws)
    if df.empty or "dokument_id" not in df.columns:
        return ws, ws.row_values(1), []
    return ws, ws.row_values(1), df[df["dokument_id"] == dokument_id]["_row"].tolist()


def odbaci_dokument(sheet, red: dict):
    """"❌ Odbaci": dokument se NE šalje (status Otkazano, ostaje u povijesti).
    Instrukcije: vezani termini se vraćaju u 'Neobračunato' (mogu se obračunati ponovno).
    Matura: prijave ostaju "iskorištene" — Assembler ih neće ponovno ubaciti u nacrt
    (ako roditelj ipak treba ponudu, dodaj predmet ponovno ili je pošalji ručno)."""
    ws = sheet.worksheet(LEDGER_TAB)
    _azuriraj_polja(ws, int(red["_row"]), {"status": "Otkazano"})
    if red.get("program_tip") == "Instrukcije":
        ws_i, h_i, retci = _termini_dokumenta(sheet, red["dokument_id"])
        for r in retci:
            _azuriraj_polja(ws_i, r, {"status_obracuna": "Neobračunato", "dokument_id": ""}, h_i)


def oznaci_dokument_placen(sheet, red: dict):
    """"💶 Plaćeno": status Plaćeno + datum. Za Instrukcije se ujedno potvrđuje uplata
    (uplata_potvrdjena_admin='Da') na svim terminima tog dokumenta."""
    ws = sheet.worksheet(LEDGER_TAB)
    _azuriraj_polja(ws, int(red["_row"]), {
        "status": "Plaćeno",
        "datum_placanja": sada_zagreb().strftime("%Y-%m-%d %H:%M:%S"),
    })
    if red.get("program_tip") == "Instrukcije":
        ws_i, h_i, retci = _termini_dokumenta(sheet, red["dokument_id"])
        for r in retci:
            _azuriraj_polja(ws_i, r, {"uplata_potvrdjena_admin": "Da"}, h_i)


def oznaci_dokument_istekao(sheet, row_number: int):
    _azuriraj_polja(sheet.worksheet(LEDGER_TAB), row_number, {"status": "Isteklo"})


def kreiraj_nacrt_instrukcije(sheet, df_odabrani: pd.DataFrame, df_cjenik: pd.DataFrame,
                              df_racuni: pd.DataFrame) -> str:
    """Jednokratna naplata (§23.3.4): admin odabere Neobračunate termine JEDNOG učenika →
    nacrt u Racuni_i_ponude, termini → Obračunato + dokument_id. Ista logika grupiranja
    (po predmetu) kao mjesečni obračun u Apps Scriptu. Vraća dokument_id."""
    if df_odabrani.empty:
        raise ValueError("Nije odabran nijedan termin.")
    if df_odabrani["ucenik_id"].nunique() != 1:
        raise ValueError("Jedan nacrt = jedan učenik.")
    if (df_odabrani.get("status_obracuna", pd.Series(dtype=str)) == "Obračunato").any():
        raise ValueError("Neki od odabranih termina su već obračunati.")

    ucenik_id = df_odabrani.iloc[0]["ucenik_id"]
    upozorenja, grupe, pregled = [], {}, []
    for _, t in df_odabrani.sort_values("datum").iterrows():
        sifra = str(t.get("sifra", "") or "")
        predmet = str(t.get("predmet", "") or "") or "?"
        minuta = int(float(t.get("duljina_min") or 0))
        centi = u_cente(t.get("cijena_termina"))
        if centi is None:
            centi = u_cente(izracunaj_cijenu_termina(df_cjenik, sifra, minuta))
        if centi is None:
            upozorenja.append(f"Termin {t['datum']} ({predmet}): cijena nepoznata — upiši ručno.")
        datum = str(t["datum"])
        datum_txt = datetime.strptime(datum[:10], "%Y-%m-%d").strftime("%d.%m.") if len(datum) >= 10 and datum[4] == "-" else datum
        pregled.append(f"{datum_txt} {predmet} {minuta} min")
        je90 = minuta == 90
        g = grupe.setdefault((sifra, centi, je90), {"termina": 0})
        g["termina"] += 1

    stavke = []
    for (sifra, centi, je90), g in grupe.items():
        stavke.append({
            "sifra": sifra,
            "opis": naziv_iz_sola(df_cjenik, sifra, je90),   # TOČAN naziv iz Sola, bez dodataka
            "kolicina": g["termina"],
            "cijena_bazna": "" if centi is None else centi_u_tekst(centi),
            "popust_postotak": 0,
            "cijena_konacna": "" if centi is None else centi_u_tekst(centi),
        })
    upozorenja.insert(0, "ℹ️ Termini: " + ", ".join(pregled))

    # Predloži subjekt po zadnjem Instrukcije dokumentu tog učenika (admin ga može promijeniti)
    subjekt = ""
    if not df_racuni.empty and "program_tip" in df_racuni.columns:
        prethodni = df_racuni[(df_racuni["ucenik_id"] == ucenik_id) & (df_racuni["program_tip"] == "Instrukcije")
                              & (df_racuni["solo_racun"].astype(str) != "")]
        if not prethodni.empty:
            subjekt = prethodni.iloc[-1]["solo_racun"]
    if not subjekt:
        upozorenja.append("Odaberi pravni subjekt (solo_racun) prije slanja.")

    dokument_id = "D-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    ws = sheet.worksheet(LEDGER_TAB)
    _dodaj_red_po_nazivu(ws, {
        "dokument_id": dokument_id,
        "ucenik_id": ucenik_id,
        "ime_djeteta": df_odabrani.iloc[0].get("ime_djeteta", ""),
        "program_tip": "Instrukcije",
        "solo_racun": subjekt,
        "tip_dokumenta": "Ponuda",
        "status": "Nacrt",
        "iznos_ukupno": zbroj_stavki_centi(stavke) / 100,
        "stavke_snapshot_json": json.dumps(stavke, ensure_ascii=False),
        "izvorni_redci": ",".join("I:" + str(t) for t in df_odabrani["termin_id"]),
        "nacin_uplate": 1,
        "datum_kreiranja": sada_zagreb().strftime("%Y-%m-%d %H:%M:%S"),
        "upozorenja": " | ".join(upozorenja),
    })

    ws_i = sheet.worksheet("Instrukcije_termini")
    h_i = ws_i.row_values(1)
    for r in df_odabrani["_row"]:
        _azuriraj_polja(ws_i, int(r), {"status_obracuna": "Obračunato", "dokument_id": dokument_id}, h_i)
    return dokument_id


MAIL_PREDLOZAK_PO_PROGRAMU = {"Matura": "matura_potvrda", "Instrukcije": "instrukcije_obracun", "Upisi": "upisi_potvrda"}


def ucitaj_mail_predlozak(sheet, program_tip: str) -> tuple:
    """(predmet, tijelo) predloška iz taba Mail_predlosci za dani program, ili ('', '') ako ga nema.
    Placeholderi {ime_roditelja}, {ime_djeteta}, {popis_programa}, {link_ponuda} ostaju kakvi jesu —
    popunjava ih Apps Script u trenutku slanja."""
    try:
        ws = sheet.worksheet("Mail_predlosci")
    except gspread.exceptions.WorksheetNotFound:
        return "", ""
    kljuc = MAIL_PREDLOZAK_PO_PROGRAMU.get(program_tip, "")
    for r in ws.get_all_records():
        if r.get("kljuc") == kljuc:
            return str(r.get("predmet", "")), str(r.get("tijelo", ""))
    return "", ""


def popuni_mail_pregled(tekst: str, zamjene: dict) -> str:
    """Isto što radi Apps Script popuniPredlozak — za pregled u admin panelu."""
    for k, v in zamjene.items():
        tekst = tekst.replace("{" + k + "}", str(v))
    return tekst


def prikazi_datum(v) -> str:
    """Datum iz Sheeta za prikaz: tekst ostaje tekst, a Sheets serijski broj (npr. 46290.69)
    pretvara se u '2026-09-25 16:41'."""
    if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)) and v > 30000:
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).strftime("%Y-%m-%d %H:%M")
    return "" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v)


def dug_ucenika(df_racuni: pd.DataFrame, ucenik_id: str) -> int:
    """§24.4: dug = zbroj iznosa dokumenata u statusu Poslano ili Isteklo (centi)."""
    if df_racuni.empty:
        return 0
    df = df_racuni[(df_racuni["ucenik_id"] == ucenik_id) & (df_racuni["status"].isin(["Poslano", "Isteklo"]))]
    return sum(u_cente(v) or 0 for v in df["iznos_ukupno"])


# ============================================================
# PORTAL "Moj CAKI" (§12/§24) — samo ČITANJE, pristup po ucenik_id (bez lozinke,
# svjesna odluka 23.9.2026., §24.5). Funkcije su čiste (DataFrame → DataFrame) radi testiranja.
# NIKAD ne vraćaju interne podatke: napomena_interna, nacrte (Nacrt/Odobreno/Greška), kontakte.
# ============================================================

def _load_opcionalno(sheet, naziv: str) -> pd.DataFrame:
    """Tab koji možda (još) ne postoji → prazan DataFrame umjesto greške."""
    try:
        return _load_worksheet_df(sheet.worksheet(naziv))
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame()


def portal_raspored_grupa(df_rezervacije: pd.DataFrame, df_grupe: pd.DataFrame, ucenik_id: str) -> pd.DataFrame:
    """§24.2: tjedni raspored grupnih programa (potvrđene + rezervirane, čekaju uplatu)."""
    if df_rezervacije.empty or df_grupe.empty:
        return pd.DataFrame()
    rez = df_rezervacije[(df_rezervacije["ucenik_id"] == ucenik_id)
                         & (df_rezervacije["status"].isin(["Potvrđeno", "Rezervirano"]))]
    if rez.empty:
        return pd.DataFrame()
    spojeno = rez.merge(df_grupe, on="grupa_id", how="inner", suffixes=("", "_g"))
    redoslijed = {d: i for i, d in enumerate(DANI_U_TJEDNU)}
    spojeno["_dan"] = spojeno["dan"].map(redoslijed).fillna(9)
    spojeno = spojeno.sort_values(["_dan", "vrijeme"])
    return pd.DataFrame({
        "Program": spojeno["program"].map(lambda k: KOMPONENTE.get(k, k)),
        "Dan": spojeno["dan"],
        "Vrijeme": spojeno["vrijeme"],
        "Učionica": spojeno["ucionica"],
        "Status": spojeno["status"].map({"Potvrđeno": "✅ Potvrđeno", "Rezervirano": "🟠 Čeka potvrdu uplate"}),
    }).reset_index(drop=True)


def portal_dolasci(df_dolasci: pd.DataFrame, df_termini: pd.DataFrame, df_grupe: pd.DataFrame, ucenik_id: str):
    """§24.1: (tablica po datumu, {grupa_labela: postotak}) — uključuje i gostovanja."""
    if df_dolasci.empty or df_termini.empty:
        return pd.DataFrame(), {}
    d = df_dolasci[df_dolasci["ucenik_id"] == ucenik_id]
    if d.empty:
        return pd.DataFrame(), {}
    d = d.merge(df_termini[["termin_id", "datum"]], on="termin_id", how="left")
    labele = {}
    if not df_grupe.empty:
        for _, g in df_grupe.iterrows():
            labele[g["grupa_id"]] = f"{KOMPONENTE.get(g['program'], g['program'])} · {g['dan']} {g['vrijeme']}"
    d["Grupa"] = d["grupa_id"].map(lambda gid: labele.get(gid, gid))
    d["Dolazak"] = d["status"].astype(str).map({"1": "✅ Prisutan", "0": "❌ Odsutan", "2": "💻 Online"}).fillna("?")
    tablica = d.sort_values("datum", ascending=False)[["datum", "Grupa", "Dolazak"]].rename(columns={"datum": "Datum"})
    postotci = {}
    for grupa, g in d.groupby("Grupa"):
        prisutan = g["status"].astype(str).isin(["1", "2"]).sum()
        postotci[grupa] = round(100 * prisutan / len(g))
    return tablica.reset_index(drop=True), postotci


_PORTAL_STATUS_DOKUMENTA = {
    "Poslano": "📄 Poslano — čeka uplatu",
    "Isteklo": "⚠️ Rok plaćanja istekao",
    "Plaćeno": "✅ Plaćeno",
}


def portal_instrukcije(df_instrukcije: pd.DataFrame, df_racuni: pd.DataFrame, ucenik_id: str) -> pd.DataFrame:
    """§24.3: odrađene instrukcije + status naplate (bez interne napomene)."""
    if df_instrukcije.empty:
        return pd.DataFrame()
    t = df_instrukcije[df_instrukcije["ucenik_id"] == ucenik_id]
    if t.empty:
        return pd.DataFrame()
    status_dok = {}
    if not df_racuni.empty and "dokument_id" in df_racuni.columns:
        status_dok = dict(zip(df_racuni["dokument_id"], df_racuni["status"]))

    def status(r):
        if str(r.get("uplata_potvrdjena_admin")) == "Da":
            return "✅ Plaćeno"
        dok = str(r.get("dokument_id", "") or "")
        if dok and status_dok.get(dok) in _PORTAL_STATUS_DOKUMENTA:
            return _PORTAL_STATUS_DOKUMENTA[status_dok[dok]]
        if dok:
            return "🕐 Obračun u pripremi"
        return "🕐 Još nije obračunato"

    t = t.sort_values("datum", ascending=False)
    out = pd.DataFrame({
        "Datum": t["datum"],
        "Predmet": t["predmet"] if "predmet" in t.columns else "",
        "Trajanje (min)": t["duljina_min"],
        "Oblik": t["oblik"],
        "Cijena (€)": [(u_cente(v) or 0) / 100 if u_cente(v) is not None else None
                       for v in (t["cijena_termina"] if "cijena_termina" in t.columns else [None] * len(t))],
        "Naplata": [status(r) for _, r in t.iterrows()],
        "Napomena": t["napomena_javna"] if "napomena_javna" in t.columns else "",
    })
    return out.reset_index(drop=True)


def portal_naplata(df_racuni: pd.DataFrame, ucenik_id: str):
    """§24.4: (tablica poslanih dokumenata, dug u centima). Nacrti/odobreni/greške/otkazani se NE prikazuju."""
    if df_racuni.empty or "status" not in df_racuni.columns:
        return pd.DataFrame(), 0
    r = df_racuni[(df_racuni["ucenik_id"] == ucenik_id) & (df_racuni["status"].isin(list(_PORTAL_STATUS_DOKUMENTA)))]
    if r.empty:
        return pd.DataFrame(), 0

    def opis(red):
        stavke = parsiraj_stavke(red.get("stavke_izvorno_json") or red.get("stavke_snapshot_json"))
        tekst = ", ".join(str(s.get("opis", "")) for s in stavke)[:120]
        if str(red.get("rata_broj", "")) not in ("", "nan"):
            tekst = f"Rata {red['rata_broj']}/{red['rata_ukupno_u_grupi']} — {tekst}"
        return tekst

    r = r.sort_values("datum_slanja", ascending=False) if "datum_slanja" in r.columns else r
    out = pd.DataFrame({
        "Program": r["program_tip"],
        "Opis": [opis(x) for _, x in r.iterrows()],
        "Iznos (€)": [(u_cente(v) or 0) / 100 for v in r["iznos_ukupno"]],
        "Rok plaćanja": r["rok_placanja"] if "rok_placanja" in r.columns else "",
        "Status": r["status"].map(_PORTAL_STATUS_DOKUMENTA),
        "Dokument": r["link_pdf"] if "link_pdf" in r.columns else "",
    })
    return out.reset_index(drop=True), dug_ucenika(df_racuni, ucenik_id)


def portal_rezultati(df_rezultati: pd.DataFrame, ucenik_id: str) -> pd.DataFrame:
    """§12: tab 'Rezultati' (ucenik_id, program, datum, tip, bodovi, maksimalno_bodova, napomena)."""
    if df_rezultati.empty or "ucenik_id" not in df_rezultati.columns:
        return pd.DataFrame()
    r = df_rezultati[df_rezultati["ucenik_id"] == ucenik_id].copy()
    if r.empty:
        return pd.DataFrame()

    def postotak(x):
        b, m = u_cente(x.get("bodovi")), u_cente(x.get("maksimalno_bodova"))
        return round(100 * b / m) if b is not None and m else None

    r["Postotak"] = [postotak(x) for _, x in r.iterrows()]
    return r.sort_values("datum", ascending=False)[
        [c for c in ["datum", "program", "tip", "bodovi", "maksimalno_bodova", "Postotak", "napomena"] if c in r.columns]
    ].rename(columns={"datum": "Datum", "program": "Program", "tip": "Vrsta", "bodovi": "Bodovi",
                      "maksimalno_bodova": "Od", "napomena": "Napomena"}).reset_index(drop=True)
