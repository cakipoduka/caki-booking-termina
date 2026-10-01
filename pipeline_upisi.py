"""
CAKI Upisi u SŠ — pipeline_upisi.py
Pomoćne funkcije za rad s Učenici/Prijave tabovima preko gspread-a.
Isti stack kao baza zadataka (get_credentials/get_gspread_client pattern).
"""
import io
import os
import random
import re
import string
import time
import json
import math
from decimal import Decimal, ROUND_HALF_UP
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
# 1.10.2026.: 0 (bilo 36) — ponuda ionako ne ide u Solo bez pregleda i klika u 💶 Financije,
# pa nema razloga čekati; nacrt se pojavi u roku ~5 min nakon "Potvrdio" (trigger sastaviNacrte).
POSALJI_NAKON_SATI = 0

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
INSTRUKCIJE_OBLICI = ["Individualno", "Grupa", "Online"]  # Online = individualno na daljinu (26.9.2026.)


# --- Autentifikacija (identično baza zadataka) ---

def get_credentials(service_account_info: dict):
    return Credentials.from_service_account_info(service_account_info, scopes=SCOPES)


class PonoviHTTPClient(gspread.http_client.HTTPClient):
    """Google Sheets povremeno odbije zahtjev: previše čitanja u minuti (greška 429) ili kratki
    kvar na Googleovoj strani (5xx). Umjesto crvene greške u aplikaciji pričeka i pokuša ponovno —
    ukupno do ~65 s, jer Googleova kvota (60 čitanja u minuti) se obnavlja svake minute.
    Druge greške (npr. nema pristupa) javlja odmah."""

    CEKANJA = (2, 5, 10, 18, 30, None)

    def request(self, *args, **kwargs):
        for cekanje in self.CEKANJA:
            try:
                return super().request(*args, **kwargs)
            except gspread.exceptions.APIError as e:
                kod = int(getattr(e, "code", 0) or 0)
                if cekanje is None or not (kod in (408, 429) or kod >= 500):
                    raise
                time.sleep(cekanje)


TAB_KES_SEKUNDI = 300


def kesiraj_tabove(spreadsheet, ttl: int = TAB_KES_SEKUNDI):
    """sheet.worksheet("Naziv") svaki put pita Google za popis tabova (1 čitanje). Ovdje se
    rezultat pamti 5 min, pa se broj čitanja po stranici otprilike prepolovi (27.9.2026.)."""
    izvorni = spreadsheet.worksheet
    kes = {}

    def worksheet(title):
        sada = time.time()
        zapis = kes.get(title)
        if zapis and sada - zapis[1] < ttl:
            return zapis[0]
        ws = izvorni(title)
        kes[title] = (ws, sada)
        return ws

    spreadsheet.worksheet = worksheet
    return spreadsheet


def get_gspread_client(service_account_info: dict):
    klijent = gspread.authorize(get_credentials(service_account_info), http_client=PonoviHTTPClient)
    izvorni_open = klijent.open_by_key
    klijent.open_by_key = lambda key: kesiraj_tabove(izvorni_open(key))
    return klijent


# --- Učitavanje podataka ---

def _load_worksheet_df(ws) -> pd.DataFrame:
    """Robustno učitavanje - radi ispravno i kad tab ima samo header, bez ijednog retka podataka.
    Zaglavlje se posebno čita samo kad tab nema redaka (inače 1 čitanje umjesto 2)."""
    records = ws.get_all_records()
    if not records:
        df = pd.DataFrame(columns=ws.row_values(1))
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
    Ako je novi_status == 'Potvrdio', upisuje i posalji_nakon = sada + POSALJI_NAKON_SATI (0 h od 1.10.2026.)."""
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


def kreiraj_grupu(sheet, program, dan, vrijeme, ucionica, kapacitet, tip, aktivna=True, redovni_nastavnik="",
                  datum_od=None, datum_do=None):
    """2.10.2026.: redak se slaže PO ZAGLAVLJU (ne po redoslijedu stupaca) i ima razdoblje datum_od/datum_do."""
    headers = osiguraj_stupce_grupa(sheet)
    ws = sheet.worksheet("Grupe")
    grupa_id = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    od, do = u_datum(datum_od), u_datum(datum_do)
    vrijednosti = {
        "grupa_id": grupa_id, "program": program, "dan": dan, "vrijeme": vrijeme, "ucionica": ucionica,
        "kapacitet": kapacitet, "tip": tip, "aktivna": "da" if aktivna else "ne", "admin_rezervirano": 0,
        "redovni_nastavnik": str(redovni_nastavnik), "sezona": SEZONA,
        "datum_od": od.isoformat() if od else "", "datum_do": do.isoformat() if do else "",
    }
    ws.append_row([vrijednosti.get(h, "") for h in headers])
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


def osiguraj_stupac_skola(sheet):
    """Dodaje stupac 'skola' na Učenici tab ako ne postoji (na desni kraj headera). 28.9.2026. —
    naziv škole koju učenik pohađa (bitno za Maturu, npr. grupiranje MIOC učenika u istu smjenu);
    za OŠ učenike (Upisi program) ostaje prazno dok admin ručno ne dopuni."""
    ws = sheet.worksheet("Učenici")
    headers = ws.row_values(1)
    if "skola" not in headers:
        ws.update_cell(1, len(headers) + 1, "skola")


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
        try:
            df_cjenik = load_cjenik(sheet)
        except Exception:
            df_cjenik = None
        if not sifra:
            sifra = odredi_sifru_instrukcije(oblik, predmet, df_cjenik)
        if cijena_termina in (None, ""):
            try:
                cijena_termina = izracunaj_cijenu_termina(df_cjenik, sifra, duljina_min)
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
        "status_obracuna": STATUS_OBRACUNA_GOTOVINA if placeno_oznaka_prof == PLACENO_GOTOVINOM else "Neobračunato",
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


def smije_naplatu_gotovinom(df_nastavnici: pd.DataFrame, ime: str) -> bool:
    """Ovlaštenje iz taba Nastavnici (stupac naplata_gotovinom = Da) — postavlja ga admin."""
    if df_nastavnici is None or df_nastavnici.empty or "naplata_gotovinom" not in df_nastavnici.columns:
        return False
    red = df_nastavnici[df_nastavnici["ime"] == ime]
    return not red.empty and str(red.iloc[0]["naplata_gotovinom"]).strip().lower() == "da"


def oznaci_naplatu_gotovinom(sheet, row_number: int, nastavnik: str):
    """Instruktor s ovlaštenjem označi da je termin naplatio gotovinom. Termin više ne ulazi u
    obračun (status_obracuna), a roditelj na portalu vidi "✅ Plaćeno". Radi samo za termin
    tog instruktora koji još nije obračunat."""
    ws = sheet.worksheet("Instrukcije_termini")
    headers = ws.row_values(1)
    red = dict(zip(headers, ws.row_values(row_number) + [""] * len(headers)))
    if red.get("nastavnik") != nastavnik:
        raise ValueError("Možete označiti samo svoje termine.")
    if str(red.get("status_obracuna", "")) not in STATUSI_ZA_OBRACUN:
        raise ValueError("Termin je već obračunat (ponuda) ili naplaćen — javite adminu.")
    polja = {"placeno_oznaka_prof": PLACENO_GOTOVINOM}
    if "status_obracuna" in headers:
        polja["status_obracuna"] = STATUS_OBRACUNA_GOTOVINA
    _azuriraj_polja(ws, row_number, polja, headers)


def postavi_naplatu_gotovinom(sheet, row_number: int, smije: bool):
    """Admin: ovlaštenje instruktora za evidentiranje naplate gotovinom (stupac se doda ako ga nema)."""
    ws = sheet.worksheet("Nastavnici")
    headers = ws.row_values(1)
    if "naplata_gotovinom" not in headers:
        if ws.col_count < len(headers) + 1:
            ws.add_cols(1)
        ws.update_cell(1, len(headers) + 1, "naplata_gotovinom")
        headers = headers + ["naplata_gotovinom"]
    _azuriraj_polja(ws, row_number, {"naplata_gotovinom": "Da" if smije else ""}, headers)


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
# SOLO — pravni subjekti, ručan odabir po prijavi (14.9.2026.)
# 29.9.2026.: dodan treći subjekt "CAKI obrt za poduku (DEDA)" (katalog se postupno puni).
# Naziv MORA biti isti kao ključ u SOLO_SUBJEKTI u Apps Scriptu (CAKI_solo_ponuda_i_mail.gs).
# ============================================================

SOLO_SUBJEKTI = ["CAKI centar d.o.o.", "Caki poduka obrt", "CAKI obrt za poduku (DEDA)"]


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
    """Postavlja status_kontakta na 'Potvrdio' i posalji_nakon na sada — Apps Script
    sastaviNacrte (svakih 5 min) od toga napravi NACRT u 💶 Financije. Ništa ne ide u Solo
    bez admin pregleda i klika "✅ Pošalji"."""
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

STATUSI_DOKUMENTA = ["Nacrt", "Odobreno", "Šalje se…", "Poslano", "Greška", "Plaćeno", "Otkazano", "Isteklo",
                     "Za brisanje", "Obrisano", "Brisanje nije uspjelo"]
# Dokumenti koji postoje u Solu i mogu se tamo obrisati (Apps Script posaljiOdobrene, ~5 min)
STATUSI_U_SOLU = ("Poslano", "Isteklo", "Brisanje nije uspjelo")
# Dokumenti koji još NISU u Solu — samo se otkazuju u tablici
STATUSI_PRIJE_SOLA = ("Nacrt", "Odobreno", "Greška")
NACINI_UPLATE = {1: "Transakcijski račun", 2: "Gotovina", 3: "Kartice", 4: "Ček", 5: "Ostalo"}

NACINI_NAPLATE_INSTRUKCIJA = ["Jednokratno", "Mjesečno"]
STUPNJEVI_SKOLOVANJA_INSTR = ["Osnovna škola", "Srednja škola", "Fakultet"]  # Fakultet dodan 26.9.2026.
# Popis predmeta za padajući izbornik — slobodno mijenjati (samo tekst, ne utječe na cijenu,
# osim stranih jezika i međunarodnih ispita, v. odredi_sifru_instrukcije)
INSTRUKCIJE_PREDMETI = [
    "Matematika", "Fizika", "Kemija", "Biologija", "Hrvatski", "Informatika", "Engleski",
    "Matura individualno", "Međunarodni ispit (SAT/IB/Cambridge…)", "Ostalo",
]
INSTRUKCIJE_STRANI_JEZICI = {"Engleski"}
# Posebne šifre koje se koriste SAMO ako postoje u Cjeniku (Solo katalogu); inače individualna cijena
INSTR_SIFRA_MATURA = "INSTR-MATURA"
INSTR_SIFRA_ONLINE = "INSTR-ONLINE"
# Oznaka u placeno_oznaka_prof kad instruktor s ovlaštenjem (Nastavnici.naplata_gotovinom = Da)
# evidentira da je termin naplaćen gotovinom. Taj termin više NE ulazi u obračun ni ponudu.
PLACENO_GOTOVINOM = "Gotovina"
STATUS_OBRACUNA_GOTOVINA = "Naplaćeno gotovinom"
STATUSI_ZA_OBRACUN = ("", "Neobračunato")  # samo takvi termini ulaze u mjesečni / jednokratni obračun
INSTRUKCIJE_SIFRE = {
    "INSTR-IND": "Individualna",
    "INSTR-GRU": "Grupna (cijena po učeniku)",
    "INSTR-STRANI": "Strani jezik",
    "INSTR-MEDJ": "Međunarodni ispit",
    "INSTR-MATURA": "Matura individualno (samo ako postoji u Solu)",
    "INSTR-ONLINE": "Online (samo ako postoji u Solu)",
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


def _cijena_s_popustom_tocno(bazna_centi, popust_postotak) -> Decimal:
    """Točan (necijeli) iznos u centima: bazna × (100 − popust) / 100, bez grešaka decimalnih brojeva."""
    p = Decimal(str(float(popust_postotak or 0)))
    return Decimal(int(bazna_centi)) * (Decimal(100) - p) / Decimal(100)


def konacna_cijena_centi(bazna_centi, popust_postotak) -> int:
    """Cijena nakon popusta, zaokružena na cent (0,5 centa ide gore) — kao Solo i Apps Script."""
    return int(_cijena_s_popustom_tocno(bazna_centi, popust_postotak).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --- učitavanje (opcionalni tabovi: prazan DataFrame dok ih Apps Script ne kreira) ---

def _load_df_neformatirano(ws) -> pd.DataFrame:
    """Kao _load_worksheet_df, ali brojeve vraća kao brojeve (ne '360,75' ovisno o jeziku Sheeta)."""
    records = ws.get_all_records(value_render_option="UNFORMATTED_VALUE")
    df = pd.DataFrame(records) if records else pd.DataFrame(columns=ws.row_values(1))
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


# ============================================================
# PDV PRAG (1.10.2026.) — koliko je računa izdano po subjektu u kalendarskoj godini
# ============================================================
# Tab PDV_prag puni Apps Script CAKI_pdv_prag.gs (svaki sat, samo čita Solo): jedan red po
# subjekt × godina × mjesec (iznos u centima) + red mjesec=0 za tekuću godinu (znak da je provjereno).
# Ovdje je samo izračun za prikaz — bez poziva Sola.
PDV_PRAG_TAB = "PDV_prag"
PDV_PRAG_CENTI = 60_000_00          # prag za ulazak u sustav PDV-a (od 1.1.2025.)
PDV_ZUTO_CENTI = 50_000_00          # Cakijeva odluka 1.10.2026.: žuto od 50.000 €
PDV_CRVENO_CENTI = 57_000_00        # crveno od 57.000 €
PDV_SUBJEKTI_BEZ_PRAGA: list = []   # subjekt koji JE u sustavu PDV-a: samo promet, bez limita
_PDV_STUPCI = ["subjekt", "godina", "mjesec", "broj_racuna", "iznos_centi", "zadnji_racun", "osvjezeno", "greska"]


def load_pdv_prag(sheet) -> pd.DataFrame:
    try:
        return _load_df_neformatirano(sheet.worksheet(PDV_PRAG_TAB))
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame(columns=_PDV_STUPCI)


def _int0(v) -> int:
    try:
        if v is None or (isinstance(v, float) and math.isnan(v)) or str(v).strip() == "":
            return 0
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def pdv_razina(ukupno_centi: int) -> str:
    if ukupno_centi > PDV_PRAG_CENTI:
        return "prekoračeno"
    if ukupno_centi >= PDV_CRVENO_CENTI:
        return "crveno"
    if ukupno_centi >= PDV_ZUTO_CENTI:
        return "žuto"
    return "zeleno"


def izracunaj_pdv_prag(df: pd.DataFrame, danas: date, subjekti: list | None = None) -> list:
    """Po subjektu: izdano ove godine, preostalo do praga, razina upozorenja i procjena do 31.12.

    Procjena: ako postoje računi iz prošle godine → ovogodišnje + ono što je prošle godine izdano
    od današnjeg dana do kraja godine (poduka je sezonska, pa je to točnije od prosjeka);
    inače linearno (prosjek po danu × dana u godini), tek nakon 30 dana u godini."""
    import calendar
    subjekti = subjekti if subjekti is not None else SOLO_SUBJEKTI
    g = danas.year
    dan_u_godini = danas.timetuple().tm_yday
    dana_u_godini = 366 if calendar.isleap(g) else 365
    dana_u_mjesecu = calendar.monthrange(g, danas.month)[1]

    if df is None or df.empty or "subjekt" not in df.columns:
        df = pd.DataFrame(columns=_PDV_STUPCI)
    d = df.copy()
    for k in _PDV_STUPCI:
        if k not in d.columns:
            d[k] = ""
    d["_g"] = d["godina"].apply(_int0)
    d["_m"] = d["mjesec"].apply(_int0)
    d["_c"] = d["iznos_centi"].apply(_int0)
    d["_n"] = d["broj_racuna"].apply(_int0)

    def _tekstovi(serija):
        return [str(x).strip() for x in serija.fillna("") if str(x).strip() not in ("", "nan")]

    rez = []
    for s in subjekti:
        ds = d[d["subjekt"].astype(str).str.strip() == s]
        provjereno = not ds[(ds["_g"] == g) & pd.to_numeric(ds["mjesec"], errors="coerce").notna()].empty
        tek = ds[(ds["_g"] == g) & ds["_m"].between(1, 12)]
        pro = ds[(ds["_g"] == g - 1) & ds["_m"].between(1, 12)]
        ukupno = int(tek["_c"].sum())
        mjesecno = {m: int(tek.loc[tek["_m"] == m, "_c"].sum()) for m in range(1, 13)}
        pro_mj = {m: int(pro.loc[pro["_m"] == m, "_c"].sum()) for m in range(1, 13)}
        proslo_ukupno = int(pro["_c"].sum())

        if proslo_ukupno > 0:
            ostatak = sum(pro_mj[m] for m in range(danas.month + 1, 13))
            ostatak += pro_mj[danas.month] * (1 - danas.day / dana_u_mjesecu)
            procjena, nacin = int(round(ukupno + ostatak)), "po prošlogodišnjem ritmu"
        elif dan_u_godini >= 30 and ukupno > 0:
            procjena, nacin = int(round(ukupno / dan_u_godini * dana_u_godini)), "prosjek po danu"
        else:
            procjena, nacin = None, ""

        bez_praga = s in PDV_SUBJEKTI_BEZ_PRAGA
        zadnji = _tekstovi(tek["zadnji_racun"])
        osv = _tekstovi(ds["osvjezeno"])
        rez.append({
            "subjekt": s,
            "provjereno": provjereno,
            "greska": "; ".join(dict.fromkeys(_tekstovi(ds["greska"]))),
            "ukupno_centi": ukupno,
            "broj_racuna": int(tek["_n"].sum()),
            "preostalo_centi": max(PDV_PRAG_CENTI - ukupno, 0),
            "postotak": min(max(ukupno, 0) / PDV_PRAG_CENTI, 1.0),
            "razina": "bez praga" if bez_praga else pdv_razina(ukupno),
            "procjena_centi": procjena,
            "procjena_nacin": nacin,
            "procjena_preko": procjena is not None and procjena > PDV_PRAG_CENTI and not bez_praga,
            "proslo_ukupno_centi": proslo_ukupno,
            "proslo_preko": proslo_ukupno > PDV_PRAG_CENTI and not bez_praga,
            "mjesecno_centi": mjesecno,
            "zadnji_racun": max(zadnji) if zadnji else "",
            "osvjezeno": max(osv) if osv else "",
        })
    return rez


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


def odredi_sifru_instrukcije(oblik: str, predmet: str, df_cjenik: pd.DataFrame | None = None) -> str:
    """Pravilo za zadanu šifru (admin je može promijeniti po terminu):
    međunarodni ispit → INSTR-MEDJ; strani jezik → INSTR-STRANI; grupa → INSTR-GRU;
    Matura individualno → INSTR-MATURA, Online → INSTR-ONLINE (SAMO ako ta šifra postoji u Cjeniku,
    inače obična individualna cijena); inače INSTR-IND."""
    predmet = str(predmet or "")

    def postoji(sifra):
        return df_cjenik is not None and cijena_iz_cjenika(df_cjenik, sifra) is not None

    if predmet.startswith("Međunarodni ispit"):
        return "INSTR-MEDJ"
    if predmet in INSTRUKCIJE_STRANI_JEZICI:
        return "INSTR-STRANI"
    if str(oblik) == "Grupa":
        return "INSTR-GRU"
    if predmet == "Matura individualno" and postoji(INSTR_SIFRA_MATURA):
        return INSTR_SIFRA_MATURA
    if str(oblik) == "Online" and postoji(INSTR_SIFRA_ONLINE):
        return INSTR_SIFRA_ONLINE
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


def _kolicina(st) -> Decimal:
    return Decimal(str(float(st.get("kolicina") or 1)))


def _puta_kolicina(centi: int, st) -> int:
    return int((Decimal(centi) * _kolicina(st)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def zbroj_stavki_centi(stavke: list) -> int:
    """Ukupno ZA UPLATU (nakon popusta), u centima."""
    ukupno = 0
    for st in stavke:
        c = u_cente(st.get("cijena_konacna"))
        if c is not None:
            ukupno += _puta_kolicina(c, st)
    return ukupno


def zbroj_osnovica_centi(stavke: list) -> int:
    """Ukupno PRIJE popusta (originalne cijene × količina), u centima."""
    ukupno = 0
    for st in stavke:
        c = u_cente(st.get("cijena_bazna"))
        if c is not None:
            ukupno += _puta_kolicina(c, st)
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
        # Rate se zadaju kao OSNOVICA (originalna cijena prije popusta); popust % ide na svaku ratu posebno
        if len(rate) < 2:
            greske.append("Plaćanje na rate treba barem 2 rate.")
        if any(iznos <= 0 for iznos, _ in rate):
            greske.append("Svaka rata mora biti veća od 0.")
        osnovica = zbroj_osnovica_centi(stavke)
        if sum(iznos for iznos, _ in rate) != osnovica:
            greske.append(
                f"Zbroj rata ({centi_u_tekst(sum(i for i, _ in rate))} €) mora biti jednak ukupnoj cijeni "
                f"prije popusta ({centi_u_tekst(osnovica)} €)."
            )
        elif not greske:
            try:
                raspodjela_rata(stavke, [i for i, _ in rate])
            except ValueError as e:
                greske.append(str(e))
        rokovi = [r for _, r in rate]
        if any(r is None for r in rokovi):
            greske.append("Svaka rata mora imati rok plaćanja.")
        elif rokovi != sorted(rokovi):
            greske.append("Rokovi rata moraju ići kronološki.")
    return greske


# --- RATE S POPUSTOM (25.9.2026., Caki): na svakoj rati ORIGINALNA cijena (dio) + popust %, ---
# --- tako da roditelj na svakoj ponudi vidi da je popust obračunat.                        ---
# Primjer: 216 € na 4 rate uz 25 % → svaka rata: cijena 54,00 €, popust 25 %, za uplatu 40,50 €.

def _na_pola_centa(bazna_centi: int, popust) -> bool:
    """True ako iznos nakon popusta pada točno na pola centa (npr. 83,75 − 10 % = 75,375) —
    takve iznose izbjegavamo jer bi Solo mogao zaokružiti drugačije od nas."""
    return _cijena_s_popustom_tocno(bazna_centi, popust) % 1 == Decimal("0.5")


def _raspodijeli_stavku(osnovica: int, popust, cilj: int, n: int) -> list:
    """Osnovicu jedne stavke podijeli na n rata tako da:
    1) zbroj osnovica = originalna cijena (točno),
    2) zbroj iznosa za uplatu = iznos kao kod jednokratnog plaćanja (točno, ako je moguće),
    3) nijedna rata ne pada na pola centa, 4) rate su što jednakije."""
    x = [osnovica // n] * n
    x[-1] += osnovica - sum(x)

    def ocjena(v):
        return (abs(cilj - sum(konacna_cijena_centi(c, popust) for c in v)),
                sum(_na_pola_centa(c, popust) for c in v),
                max(v) - min(v))

    najbolja = ocjena(x)
    for _ in range(300):
        if najbolja == (0, 0, 0) or (najbolja[:2] == (0, 0) and najbolja[2] <= 1):
            break
        poboljsano = False
        for korak in (1, 2, 3):
            for a in reversed(range(n)):
                for b in reversed(range(n)):
                    if a == b or x[b] - korak <= 0:
                        continue
                    y = list(x)
                    y[a] += korak
                    y[b] -= korak
                    o = ocjena(y)
                    if o < najbolja:
                        x, najbolja, poboljsano = y, o, True
                        break
                if poboljsano:
                    break
            if poboljsano:
                break
        if not poboljsano:
            break
    return x


def _podaci_stavki(stavke: list) -> list:
    """(osnovica_centi, popust, za_uplatu_centi) po stavci, za cijelu količinu."""
    rez = []
    for st in stavke:
        b = u_cente(st.get("cijena_bazna")) or 0
        p = float(st.get("popust_postotak") or 0)
        rez.append((_puta_kolicina(b, st), p, _puta_kolicina(konacna_cijena_centi(b, p), st)))
    return rez


def _zadana_raspodjela(stavke: list, n: int) -> list:
    """Matrica [stavka][rata] osnovica u centima — zadani (automatski) prijedlog."""
    return [_raspodijeli_stavku(B, p, F, n) for B, p, F in _podaci_stavki(stavke)]


def raspodjela_rata(stavke: list, osnovice_rata: list) -> list:
    """Za zadane osnovice po ratama (zbroj = ukupna cijena prije popusta) vrati matricu
    [stavka][rata] osnovica. Ako su osnovice jednake automatskom prijedlogu, koristi se on;
    inače (admin je ručno promijenio iznose) svaka se rata dijeli na stavke razmjerno cijeni."""
    n = len(osnovice_rata)
    zadana = _zadana_raspodjela(stavke, n)
    if [sum(r[k] for r in zadana) for k in range(n)] == list(osnovice_rata):
        return zadana
    podaci = _podaci_stavki(stavke)
    ukupno = sum(B for B, _, _ in podaci)
    if ukupno <= 0 or sum(osnovice_rata) != ukupno:
        raise ValueError("Zbroj rata mora biti jednak ukupnoj cijeni prije popusta.")
    m = [[0] * n for _ in podaci]
    for k in range(n - 1):
        for i, (B, _, _) in enumerate(podaci[:-1]):
            m[i][k] = int((Decimal(osnovice_rata[k]) * B / ukupno).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        m[-1][k] = osnovice_rata[k] - sum(m[i][k] for i in range(len(podaci) - 1))
    for i, (B, _, _) in enumerate(podaci):
        m[i][n - 1] = B - sum(m[i][:n - 1])
    if any(v < 0 for red in m for v in red):
        raise ValueError("Rate su preneravnomjerne da bi se podijelile po stavkama — ujednačite iznose rata.")
    return m


def stavke_za_rate(stavke: list, osnovice_rata: list) -> list:
    """Lista (po ratama) stavki koje idu u Solo: svaka stavka zadržava ORIGINALNI naziv iz Sola
    + "(rata k/N)", cijenu = njezin dio originalne cijene, i ISTI popust % kao na jednokratnoj ponudi."""
    stavke = preracunaj_stavke(stavke)
    n = len(osnovice_rata)
    m = raspodjela_rata(stavke, osnovice_rata)
    po_ratama = []
    for k in range(n):
        linije = []
        for i, st in enumerate(stavke):
            bazna = m[i][k]
            if bazna <= 0:
                continue
            p = float(st.get("popust_postotak") or 0)
            linija = {
                "sifra": st.get("sifra", ""),
                "opis": f"{str(st.get('opis', ''))[:480]} (rata {k + 1}/{n})",
                "kolicina": 1,
                "cijena_bazna": centi_u_tekst(bazna),
                "popust_postotak": p,
                "cijena_konacna": centi_u_tekst(konacna_cijena_centi(bazna, p)),
            }
            if st.get("izvor"):
                linija["izvor"] = st["izvor"]
            linije.append(linija)
        po_ratama.append(linije)
    return po_ratama


def pregled_rata(stavke: list, osnovice_rata: list) -> list:
    """Za prikaz u adminu: po rati osnovica, popust i iznos za uplatu (centi)."""
    rez = []
    for linije in stavke_za_rate(stavke, osnovice_rata):
        popusti = sorted({float(l["popust_postotak"]) for l in linije if float(l["popust_postotak"])})
        tekst = " / ".join(f"{p:g}".replace(".", ",") for p in popusti)
        if not popusti:
            tekst = "—"
        elif any(not float(l["popust_postotak"]) for l in linije):
            tekst = f"−{tekst} % (na dio stavki)"
        else:
            tekst = f"−{tekst} %"
        rez.append({
            "osnovica": sum(u_cente(l["cijena_bazna"]) for l in linije),
            "popust": tekst,
            "za_uplatu": sum(u_cente(l["cijena_konacna"]) for l in linije),
        })
    return rez


def predlozi_rate(stavke, broj_rata: int, prvi_rok: date) -> list:
    """Prijedlog rata: lista (osnovica_centi, rok) — osnovica = dio ORIGINALNE cijene (prije popusta),
    rok svakih 30 dana. (Za kompatibilnost: ako se umjesto stavki preda broj centi, dijeli se taj broj.)"""
    if isinstance(stavke, (int, float)):
        ukupno = int(stavke)
        osnovne = [ukupno // broj_rata] * broj_rata
        osnovne[-1] += ukupno - sum(osnovne)
    else:
        m = _zadana_raspodjela(preracunaj_stavke(stavke), broj_rata)
        osnovne = [sum(r[k] for r in m) for k in range(broj_rata)]
    return [(iznos, prvi_rok + timedelta(days=30 * k)) for k, iznos in enumerate(osnovne)]


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
    # Na svakoj rati: originalni naziv iz Sola + "(rata k/N)", dio ORIGINALNE cijene i popust %
    # (Solo ga ispisuje na ponudi, pa roditelj vidi da je popust obračunat).
    grupa_id = "G-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    n = len(rate)
    po_ratama = stavke_za_rate(stavke, [i for i, _ in rate])
    program = red.get("program_tip", "")
    dokumenti = []
    for k, ((_, rok), stavke_rate) in enumerate(zip(rate, po_ratama), start=1):
        iznos = zbroj_stavki_centi(stavke_rate)
        polja = dict(zajednicko, **{
            "stavke_snapshot_json": json.dumps(stavke_rate, ensure_ascii=False),
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


# ============================================================
# BRISANJE POSLANIH PONUDA, ISPRAVAK I ODUSTAJANJE (25.9.2026.)
# Streamlit NE zove Solo izravno (tokeni su samo u Apps Scriptu): admin označi dokument
# "Za brisanje", a Apps Script posaljiOdobrene() ga u roku ~5 min obriše u Solu → "Obrisano".
# Ponuda u Solu nije fiskalizirani dokument, pa se smije obrisati. RAČUN se ne briše (storno u Solu).
# ============================================================

def _stupac_ako_postoji(headers: list, polja: dict) -> dict:
    """Izbaci polja za stupce koje tab još nema (dodaje ih postaviFinancije)."""
    return {k: v for k, v in polja.items() if k in headers}


def dokumenti_grupe(df_racuni: pd.DataFrame, red) -> pd.DataFrame:
    """Sve rate istog dokumenta (isti rata_grupa_id), ili samo taj dokument."""
    grupa = str(red.get("rata_grupa_id") or "")
    if grupa and grupa != "nan" and "rata_grupa_id" in df_racuni.columns:
        return df_racuni[df_racuni["rata_grupa_id"].astype(str) == grupa]
    return df_racuni[df_racuni["dokument_id"] == red["dokument_id"]]


def _termini_vise_dokumenata(sheet, dokument_ids: list):
    ws = sheet.worksheet("Instrukcije_termini")
    df = _load_worksheet_df(ws)
    if df.empty or "dokument_id" not in df.columns:
        return ws, ws.row_values(1), []
    return ws, ws.row_values(1), df[df["dokument_id"].isin(dokument_ids)]["_row"].tolist()


def zatrazi_brisanje(sheet, dokumenti: list, razlog: str = "", termini: str = "otpisi") -> dict:
    """Za svaki dokument (dict s _row, dokument_id, program_tip, ...):
      - Nacrt/Odobreno/Greška (još nije u Solu)  → Otkazano,
      - Poslano/Isteklo/Brisanje nije uspjelo    → Za brisanje (Apps Script ga briše u Solu),
      - Plaćeno / Šalje se… / Račun               → preskače se, uz objašnjenje.
    termini (samo Instrukcije): "otpisi" = termini se više ne naplaćuju (Otpisano),
    "vrati" = natrag u Neobračunato (ući će u sljedeći obračun), "zadrzi" = ne dirati (ispravak).
    Vraća {"za_brisanje": n, "otkazano": n, "preskoceno": [tekst, ...]}."""
    ws = sheet.worksheet(LEDGER_TAB)
    headers = ws.row_values(1)
    svjezi_statusi = ws.col_values(headers.index("status") + 1)  # svježe, ne iz cachea
    rez = {"za_brisanje": 0, "otkazano": 0, "preskoceno": []}
    instrukcije_ids = []
    for d in dokumenti:
        row = int(d["_row"])
        status = svjezi_statusi[row - 1] if row - 1 < len(svjezi_statusi) else ""
        oznaka = f"{d.get('ime_djeteta', '')} {d.get('broj_dokumenta') or d.get('dokument_id')}".strip()
        if status == "Plaćeno":
            rez["preskoceno"].append(f"{oznaka}: već plaćeno — ostaje (povrat novca riješite ručno).")
            continue
        if status == "Šalje se…":
            rez["preskoceno"].append(f"{oznaka}: upravo se šalje u Solo — pokušajte ponovno za 5 minuta.")
            continue
        if str(d.get("tip_dokumenta", "Ponuda") or "Ponuda") not in ("Ponuda", "nan"):
            rez["preskoceno"].append(f"{oznaka}: račun se ne briše — napravite storno u Solu.")
            continue
        polja = _stupac_ako_postoji(headers, {"razlog_brisanja": str(razlog or "")[:500]})
        if status in STATUSI_PRIJE_SOLA:
            polja["status"] = "Otkazano"
            rez["otkazano"] += 1
        elif status in STATUSI_U_SOLU:
            polja.update({"status": "Za brisanje", "greska_slanja": ""})
            rez["za_brisanje"] += 1
        else:
            continue  # već Otkazano / Obrisano / Za brisanje
        _azuriraj_polja(ws, row, polja, headers)
        if d.get("program_tip") == "Instrukcije":
            instrukcije_ids.append(d["dokument_id"])

    if instrukcije_ids and termini in ("otpisi", "vrati"):
        ws_i, h_i, retci = _termini_vise_dokumenata(sheet, instrukcije_ids)
        for r in retci:
            _azuriraj_polja(ws_i, r, {"status_obracuna": "Otpisano"} if termini == "otpisi"
                            else {"status_obracuna": "Neobračunato", "dokument_id": ""}, h_i)
    return rez


def ispravi_dokument(sheet, df_racuni: pd.DataFrame, red) -> tuple:
    """"✏️ Ispravi": poslana ponuda (sa svim ratama) briše se u Solu, a u Nacrtima nastaje nova
    s istim stavkama, subjektom, načinom uplate i napomenom — admin je ispravi i pošalje.
    Vraća (novi_dokument_id, rezultat zatrazi_brisanje)."""
    grupa = dokumenti_grupe(df_racuni, red).copy()
    if (grupa["status"] == "Plaćeno").any():
        raise ValueError("Dio ove ponude (neka rata) je već plaćen — ispravak nije moguć. "
                         "Obrišite samo neplaćene rate i napravite novu ponudu ručno.")
    if (grupa["status"] == "Šalje se…").any():
        raise ValueError("Ponuda se upravo šalje u Solo — pokušajte ponovno za 5 minuta.")
    grupa["_k"] = pd.to_numeric(grupa.get("rata_broj", 1), errors="coerce").fillna(1)
    grupa = grupa.sort_values("_k")
    prvi = grupa.iloc[0].to_dict()
    stavke = parsiraj_stavke(prvi.get("stavke_izvorno_json") or prvi.get("stavke_snapshot_json"))
    if not stavke:
        raise ValueError("Ponuda nema zapisane stavke — napravite novu ručno.")
    stavke = preracunaj_stavke(stavke)
    izvorni = next((str(v) for v in grupa.get("izvorni_redci", []) if str(v) not in ("", "nan")), "")
    brojevi = ", ".join(str(b) for b in grupa.get("broj_dokumenta", []) if str(b) not in ("", "nan")) or prvi["dokument_id"]
    n_rata = len(grupa)

    rez = zatrazi_brisanje(sheet, [r.to_dict() for _, r in grupa.iterrows()],
                           razlog="Ispravak — zamijenjeno novom ponudom", termini="zadrzi")

    novi_id = "D-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    ws = sheet.worksheet(LEDGER_TAB)
    upozorenja = f"✏️ Ispravak ponude {brojevi} (stara se briše u Solu). Promijenite što treba i pošaljite."
    if n_rata > 1:
        upozorenja += f" Prije: NA RATE ({n_rata})."

    def _v(k):
        v = prvi.get(k, "")
        return "" if v is None or (isinstance(v, float) and math.isnan(v)) else v

    _dodaj_red_po_nazivu(ws, {
        "dokument_id": novi_id,
        "ucenik_id": _v("ucenik_id"),
        "ime_djeteta": _v("ime_djeteta"),
        "program_tip": _v("program_tip"),
        "solo_racun": _v("solo_racun"),
        "tip_dokumenta": _v("tip_dokumenta") or "Ponuda",
        "status": "Nacrt",
        "iznos_ukupno": zbroj_stavki_centi(stavke) / 100,
        "stavke_snapshot_json": json.dumps(stavke, ensure_ascii=False),
        "izvorni_redci": izvorni,
        "nacin_uplate": _v("nacin_uplate") or 1,
        "napomena": _v("napomena"),
        "datum_kreiranja": sada_zagreb().strftime("%Y-%m-%d %H:%M:%S"),
        "upozorenja": upozorenja,
    })
    if prvi.get("program_tip") == "Instrukcije":
        ws_i, h_i, retci = _termini_vise_dokumenata(sheet, grupa["dokument_id"].tolist())
        for r in retci:
            _azuriraj_polja(ws_i, r, {"dokument_id": novi_id, "status_obracuna": "Obračunato"}, h_i)
    return novi_id, rez


def ponovi_brisanje(sheet, row_number: int):
    _azuriraj_polja(sheet.worksheet(LEDGER_TAB), row_number, {"status": "Za brisanje", "greska_slanja": ""})


def oznaci_obrisano_rucno(sheet, row_number: int):
    """Admin je ponudu već sam obrisao u Solu (ili je nikad nije bilo) — samo zapiši stanje."""
    _azuriraj_polja(sheet.worksheet(LEDGER_TAB), row_number, {"status": "Obrisano", "greska_slanja": ""})


def odustao_od_programa(sheet, ucenik_id: str, prijave: dict, dokumenti: list,
                        rezervacije_retci: list, razlog: str = "", autor: str = "") -> dict:
    """"🚪 Odustao": odabrane prijave → Odustao, rezervacije termina → Otkazano (mjesto u grupi
    se oslobađa), odabrane ponude → brisanje u Solu / otkazivanje, bilješka u povijesti kontakta.
    Učenik se NE briše iz tablice — ostaje povijest (i ista šifra ako se vrati).
    prijave = {redak_id: čitljiv opis}."""
    opis = []
    redak_ids = list(prijave)
    if redak_ids:
        ws_p = sheet.worksheet("Prijave")
        df_p = _load_worksheet_df(ws_p)
        h_p = ws_p.row_values(1)
        for _, r in df_p[df_p["redak_id"].isin(redak_ids) & (df_p["ucenik_id"] == ucenik_id)].iterrows():
            _azuriraj_polja(ws_p, int(r["_row"]), {"status_kontakta": "Odustao"}, h_p)
            opis.append(str(prijave.get(r["redak_id"]) or r["redak_id"]))
    if rezervacije_retci:
        ws_r = sheet.worksheet("Rezervacije")
        h_r = ws_r.row_values(1)
        for row in rezervacije_retci:
            _azuriraj_polja(ws_r, int(row), {"status": "Otkazano"}, h_r)
    rez = zatrazi_brisanje(sheet, dokumenti, razlog=("Odustao: " + razlog).strip(": "), termini="otpisi")
    rez["prijava"] = len(opis)
    rez["rezervacija"] = len(rezervacije_retci)
    try:
        tekst = "🚪 Odustao" + (f" od: {', '.join(opis)}" if opis else "") + "."
        if razlog:
            tekst += f" Razlog: {razlog}."
        tekst += (f" Ponude: {rez['za_brisanje']} za brisanje u Solu, {rez['otkazano']} otkazano"
                  f"{', ' + str(len(rez['preskoceno'])) + ' preskočeno' if rez['preskoceno'] else ''}.")
        dodaj_biljesku(sheet, ucenik_id, autor or "admin", tekst)
    except gspread.exceptions.WorksheetNotFound:
        pass
    return rez


def kreiraj_nacrt_instrukcije(sheet, df_odabrani: pd.DataFrame, df_cjenik: pd.DataFrame,
                              df_racuni: pd.DataFrame) -> str:
    """Jednokratna naplata (§23.3.4): admin odabere Neobračunate termine JEDNOG učenika →
    nacrt u Racuni_i_ponude, termini → Obračunato + dokument_id. Ista logika grupiranja
    (po predmetu) kao mjesečni obračun u Apps Scriptu. Vraća dokument_id."""
    if df_odabrani.empty:
        raise ValueError("Nije odabran nijedan termin.")
    if df_odabrani["ucenik_id"].nunique() != 1:
        raise ValueError("Jedan nacrt = jedan učenik.")
    if not df_odabrani.get("status_obracuna", pd.Series("", index=df_odabrani.index)).fillna("").isin(STATUSI_ZA_OBRACUN).all():
        raise ValueError("Neki od odabranih termina su već obračunati, otpisani ili naplaćeni gotovinom.")

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


def popis_programa_za_mail(stavke: list) -> str:
    """{popis_programa} u mailu — isto kao Apps Script popisZaMail_(). Popust se vidi i u mailu:
    "- Naziv — 335,00 € − 10 % = 301,50 €", "- Naziv — 8 × 20,00 € = 160,00 €"."""
    redovi = []
    for st in stavke:
        kol = float(st.get("kolicina") or 1)
        p = float(st.get("popust_postotak") or 0)
        bazna = u_cente(st.get("cijena_bazna"))
        konacna = u_cente(st.get("cijena_konacna"))
        if bazna is None:
            bazna = konacna
        tekst = f"- {st.get('opis', '')} — "
        if kol != 1:
            tekst += f"{kol:g}".replace(".", ",") + " × "
        tekst += f"{centi_u_tekst(bazna)} €"
        if p:
            tekst += f" − {p:g}".replace(".", ",") + " %"
        if p or kol != 1:
            tekst += f" = {centi_u_tekst(_puta_kolicina(konacna or 0, st))} €"
        redovi.append(tekst)
    return "\n".join(redovi)


def naslov_maila(predmet: str, ime_djeteta: str, ucenik_id: str) -> str:
    """Isto kao Apps Script naslovMaila_(): kratko + ime i šifra učenika."""
    p = str(predmet or "").strip()
    m = re.match(r"^Potvrda prijave i ponuda za uplatu\s*[—–-]\s*(.+)$", p, re.IGNORECASE)
    if m:
        p = m.group(1).strip() + " · prijava i ponuda"
    if ime_djeteta and str(ime_djeteta) not in p:
        p += f" — {ime_djeteta} ({ucenik_id})"
    elif ucenik_id not in p:
        p += f" ({ucenik_id})"
    return p


def tekst_moj_caki(ime_djeteta: str, ucenik_id: str, portal_url: str = "[adresa portala Moj CAKI]") -> str:
    """Isto kao Apps Script tekstMojCaki_()."""
    return (f"Učenik: {ime_djeteta} · šifra za pristup: {ucenik_id}\n"
            f"Moj CAKI — raspored nastave, dolasci, uplate i dokumenti na jednom mjestu:\n"
            f"{str(portal_url).rstrip('/')}/?ucenik_id={ucenik_id}")


def tekst_nacin_placanja(ime_djeteta: str, ucenik_id: str, ime_roditelja: str, nacin_placanja: str,
                         portal_url: str = "[adresa portala Moj CAKI]") -> str:
    """🆕 28.9.2026. — WhatsApp/mail podsjetnik roditelju: odabrani način plaćanja (Jednokratno/Na rate,
    iz Prijave.nacin_placanja) + da je ponuda poslana na mail + link na Moj CAKI. NAMJERNO ne ponavlja
    bankovne podatke (IBAN/poziv na broj) — ti podaci su već na Solo ponudi koju je roditelj dobio
    mailom, pa nema rizika da se nešto krivo prepiše/zastari u ovoj poruci."""
    pozdrav = f"Poštovani/a {ime_roditelja}," if str(ime_roditelja or "").strip() else "Poštovani,"
    nacin_recenica = f" Odabrani način plaćanja: *{nacin_placanja}*." if str(nacin_placanja or "").strip() else ""
    dijelovi = [
        pozdrav,
        "",
        f"ponuda za {ime_djeteta} poslana je na mail.{nacin_recenica} Molimo provjerite mail i "
        "uplatite prema uputama na ponudi (rok plaćanja je naveden na njoj).",
        "",
        tekst_moj_caki(ime_djeteta, ucenik_id, portal_url),
        "",
        "Za sva pitanja slobodno nam se javite.",
        "",
        "Lijep pozdrav,\nCAKI centar",
    ]
    return "\n".join(dijelovi)


# --- R1: račun na firmu (26.9.2026.) — podaci u tabu Učenici; Apps Script ih šalje Solu kao kupca ---
R1_STUPCI = ["r1_naziv", "r1_oib", "r1_adresa"]


def spremi_r1(sheet, row_number: int, naziv: str, oib: str, adresa: str):
    """Upiše podatke firme za R1 (prazan OIB = ponude idu na roditelja kao i dosad)."""
    oib = re.sub(r"\s", "", str(oib or ""))
    if oib and not re.fullmatch(r"\d{11}", oib):
        raise ValueError("OIB mora imati točno 11 znamenki.")
    if oib and not str(naziv or "").strip():
        raise ValueError("Upišite naziv firme.")
    ws = sheet.worksheet("Učenici")
    headers = ws.row_values(1)
    nedostaju = [h for h in R1_STUPCI if h not in headers]
    if nedostaju:
        if ws.col_count < len(headers) + len(nedostaju):
            ws.add_cols(len(headers) + len(nedostaju) - ws.col_count)
        ws.update(range_name=gspread.utils.rowcol_to_a1(1, len(headers) + 1), values=[nedostaju], value_input_option="RAW")
        headers = headers + nedostaju
    _azuriraj_polja(ws, row_number, {"r1_naziv": str(naziv or "").strip()[:100], "r1_oib": oib,
                                     "r1_adresa": str(adresa or "").strip()[:255]}, headers)


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
    d["Grupa"] = d["grupa_id"].map(lambda gid: labele.get(gid, labela_matura_grupe(gid)))
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
        if str(r.get("uplata_potvrdjena_admin")) == "Da" or str(r.get("placeno_oznaka_prof")) == PLACENO_GOTOVINOM:
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
    # Poslane ponude kojima mail još NIJE ni pokušan (npr. druga rata iste grupe čeka slanje) se ne
    # prikazuju — roditelj ih vidi tek kad dobije mail sa svim ratama. Plaćene se prikazuju uvijek.
    if "mail_poslan" in r.columns:
        r = r[(r["status"] == "Plaćeno") | (r["mail_poslan"].astype(str).str.strip().replace("nan", "") != "")]
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
    return out.reset_index(drop=True), dug_ucenika(r, ucenik_id)   # dug samo od prikazanih dokumenata


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


# ============================================================
# MJESEČNI IZVJEŠTAJ INSTRUKTORA (26.9.2026.)
# Instruktor generira popis odrađenih termina za mjesec (BEZ cijena — financije vide samo admini),
# preuzme PDF i pošalje ga adminu na provjeru. Admin ga potvrdi / označi isplaćenim / vrati.
# ============================================================

IZVJESTAJI_TAB = "Izvjestaji_instruktora"
IZVJESTAJI_HEADERS = ["izvjestaj_id", "nastavnik", "mjesec", "poslano", "broj_instrukcija", "sati_instrukcija",
                      "broj_grupnih_termina", "status", "napomena_admin", "azurirano",
                      "nacin_isplate", "iznos_isplate", "datum_isplate"]
# Samo admin vidi (portal za profesore prikazuje samo status i napomenu)
NACINI_ISPLATE = ["Ugovor o djelu", "Autorski ugovor", "Račun (obrt / firma)", "Plaća", "Naknada / ostalo"]
STATUSI_IZVJESTAJA = ["Čeka provjeru", "Potvrđeno", "Isplaćeno", "Vraćeno na ispravak"]


def _u_mjesecu(v, godina: int, mjesec: int) -> bool:
    d = pd.to_datetime(str(v)[:10], format="%Y-%m-%d", errors="coerce")
    return pd.notna(d) and d.year == godina and d.month == mjesec


def izvjestaj_instruktora(df_instrukcije: pd.DataFrame, df_termini: pd.DataFrame, df_grupe: pd.DataFrame,
                          nastavnik: str, godina: int, mjesec: int) -> dict:
    """Odrađeni termini instruktora u mjesecu: instrukcije + grupni termini koje je održao.
    NAMJERNO bez cijena i naplate."""
    instr = pd.DataFrame()
    if not df_instrukcije.empty and "nastavnik" in df_instrukcije.columns:
        t = df_instrukcije[(df_instrukcije["nastavnik"] == nastavnik)
                           & df_instrukcije["datum"].apply(lambda v: _u_mjesecu(v, godina, mjesec))]
        t = t.sort_values("datum")
        instr = pd.DataFrame({
            "Datum": [str(v)[:10] for v in t["datum"]],
            "Učenik": t["ime_djeteta"],
            "Predmet": t["predmet"] if "predmet" in t.columns else "",
            "Trajanje (min)": [int(float(v or 0)) for v in t["duljina_min"]],
            "Oblik": t["oblik"],
        }).reset_index(drop=True)
    grupni = pd.DataFrame()
    if not df_termini.empty and "nastavnik_odrzao" in df_termini.columns:
        g = df_termini[(df_termini["nastavnik_odrzao"] == nastavnik)
                       & df_termini["datum"].apply(lambda v: _u_mjesecu(v, godina, mjesec))].sort_values("datum")
        labele = {}
        if not df_grupe.empty:
            for _, r in df_grupe.iterrows():
                labele[r["grupa_id"]] = f"{KOMPONENTE.get(r['program'], r['program'])} · {r['dan']} {r['vrijeme']}"
        grupni = pd.DataFrame({
            "Datum": [str(v)[:10] for v in g["datum"]],
            "Grupa": [labele.get(x, labela_matura_grupe(x)) for x in g["grupa_id"]],
        }).reset_index(drop=True)
    minute = int(instr["Trajanje (min)"].sum()) if not instr.empty else 0
    return {
        "nastavnik": nastavnik, "mjesec": f"{godina}-{mjesec:02d}",
        "instrukcije": instr, "grupni": grupni,
        "broj_instrukcija": len(instr), "sati_instrukcija": round(minute / 60, 2),
        "broj_grupnih_termina": len(grupni),
    }


def pdf_izvjestaja_instruktora(izv: dict) -> bytes:
    """PDF za isplatu: sažetak + popis instrukcija + popis grupnih termina (bez cijena)."""
    ima_dejavu = _osiguraj_pdf_font()
    font_n = "DejaVuSans" if ima_dejavu else "Helvetica"
    font_b = "DejaVuSans-Bold" if ima_dejavu else "Helvetica-Bold"
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    st_ = getSampleStyleSheet()
    naslov = st_["Title"].clone("n_izv"); naslov.fontName = font_b
    h2 = st_["Heading2"].clone("h_izv"); h2.fontName = font_b
    tekst = st_["Normal"].clone("t_izv"); tekst.fontName = font_n; tekst.fontSize = 9; tekst.leading = 12
    zag = tekst.clone("z_izv"); zag.fontName = font_b; zag.textColor = colors.white
    godina, mjesec = izv["mjesec"].split("-")

    def tablica(df):
        podaci = [[Paragraph(str(c), zag) for c in df.columns]]
        podaci += [[Paragraph(str(v), tekst) for v in r] for r in df.values.tolist()]
        t = Table(podaci, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2a3f5f")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return t

    el = [
        Paragraph(f"Izvještaj o odrađenim terminima — {MJESECI_HR[int(mjesec) - 1]} {godina}.", naslov),
        Paragraph(f"Instruktor/ica: <b>{izv['nastavnik']}</b>", tekst),
        Paragraph(f"Instrukcije: <b>{izv['broj_instrukcija']}</b> termina, ukupno <b>{izv['sati_instrukcija']:g}</b> h"
                  f" · Grupni termini: <b>{izv['broj_grupnih_termina']}</b>", tekst),
        Paragraph(f"Generirano: {sada_zagreb().strftime('%d.%m.%Y. %H:%M')}", tekst),
        Spacer(1, 0.4 * cm),
    ]
    if not izv["instrukcije"].empty:
        el += [Paragraph("Instrukcije", h2), tablica(izv["instrukcije"]), Spacer(1, 0.4 * cm)]
    if not izv["grupni"].empty:
        el += [Paragraph("Grupni termini", h2), tablica(izv["grupni"])]
    if izv["instrukcije"].empty and izv["grupni"].empty:
        el.append(Paragraph("U ovom mjesecu nema evidentiranih termina.", tekst))
    doc.build(el)
    return buffer.getvalue()


def load_izvjestaji(sheet) -> pd.DataFrame:
    return _load_opcionalno(sheet, IZVJESTAJI_TAB)


def posalji_izvjestaj_instruktora(sheet, izv: dict) -> str:
    """Upiše (ili osvježi) izvještaj za mjesec. Već potvrđen / isplaćen se ne mijenja."""
    try:
        ws = sheet.worksheet(IZVJESTAJI_TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=IZVJESTAJI_TAB, rows=500, cols=len(IZVJESTAJI_HEADERS))
        ws.append_row(IZVJESTAJI_HEADERS)
    headers = ws.row_values(1)
    df = _load_worksheet_df(ws)
    sada = sada_zagreb().strftime("%Y-%m-%d %H:%M")
    polja = {
        "poslano": sada, "broj_instrukcija": izv["broj_instrukcija"], "sati_instrukcija": izv["sati_instrukcija"],
        "broj_grupnih_termina": izv["broj_grupnih_termina"], "status": "Čeka provjeru", "azurirano": sada,
    }
    if not df.empty:
        postojeci = df[(df["nastavnik"] == izv["nastavnik"]) & (df["mjesec"].astype(str) == izv["mjesec"])]
        if not postojeci.empty:
            r = postojeci.iloc[0]
            if r["status"] in ("Potvrđeno", "Isplaćeno"):
                raise ValueError(f"Izvještaj za {izv['mjesec']} je već {r['status'].lower()} — za izmjene se javite adminu.")
            _azuriraj_polja(ws, int(r["_row"]), polja, headers)
            return r["izvjestaj_id"]
    izv_id = "IZ-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    _dodaj_red_po_nazivu(ws, dict(polja, izvjestaj_id=izv_id, nastavnik=izv["nastavnik"], mjesec=izv["mjesec"]), headers)
    return izv_id


def azuriraj_izvjestaj(sheet, row_number: int, status: str, napomena: str = "",
                      nacin_isplate: str = "", iznos_isplate=None):
    ws = sheet.worksheet(IZVJESTAJI_TAB)
    headers = ws.row_values(1)
    nedostaju = [h for h in IZVJESTAJI_HEADERS if h not in headers]
    if nedostaju:   # tab napravljen prije 26.9. — dodaj nove stupce
        if ws.col_count < len(headers) + len(nedostaju):
            ws.add_cols(len(headers) + len(nedostaju) - ws.col_count)
        ws.update(range_name=gspread.utils.rowcol_to_a1(1, len(headers) + 1), values=[nedostaju], value_input_option="RAW")
        headers = headers + nedostaju
    sada = sada_zagreb().strftime("%Y-%m-%d %H:%M")
    polja = {"status": status, "napomena_admin": str(napomena or "")[:500], "azurirano": sada}
    if status == "Isplaćeno":
        polja.update({"nacin_isplate": str(nacin_isplate or ""), "datum_isplate": sada[:10],
                      "iznos_isplate": "" if iznos_isplate in (None, "") else float(iznos_isplate)})
    _azuriraj_polja(ws, row_number, polja, headers)


# ============================================================
# MATURA — raspored (tab Raspored_Matura_<sezona>, piše ga admin → 🎓 Raspored Matura) i dolasci
# (26.9.2026.). Dolasci Mature koriste POSTOJEĆE tabove Termini / Dolasci / Gostovanja i funkciju
# spremi_cijeli_termin; grupa_id Matura sata je oznaka kante: "MATURA|Subota|1|A".
# Sve funkcije su čiste (DataFrame → podaci) radi testiranja. v. Claude outputs/CAKI_Matura_Dolasci_Prijedlog.
# ============================================================
MATURA_PREFIKS = "MATURA|"
ROK_PROFESOR_DANA = 14      # profesor smije upisati/ispraviti sat najviše 2 tjedna unatrag (odluka 26.9.2026.)

KRATICE_PREDMETA_MATURA = {
    "hrvatski": "HRV", "matematika": "MAT", "engleski": "ENG", "fizika": "FIZ", "kemija": "KEM",
    "biologija": "BIO", "fizika_medicina": "FIZ-MED", "kemija_medicina": "KEM-MED", "biologija_medicina": "BIO-MED",
}
# Oznake koje se mogu dodijeliti profesoru (⚙️ Postavke → Nastavnici)
OZNAKE_PREDMETA_MATURA = ["MAT-A", "MAT-B", "HRV", "ENG-A", "ENG-B", "FIZ", "KEM", "BIO", "FIZ-MED", "KEM-MED", "BIO-MED"]


def oznaka_predmeta_matura(predmet, razina="") -> str:
    """'matematika' + 'A' -> 'MAT-A'; nepoznat predmet ostaje kakav jest (velikim slovima)."""
    p = str(predmet or "").strip().lower()
    kratica = KRATICE_PREDMETA_MATURA.get(p, p.upper() or "?")
    r = str(razina or "").strip().upper()
    return f"{kratica}-{r}" if r in ("A", "B") else kratica


def naziv_taba_rasporeda_mature(sezona: str = SEZONA) -> str:
    return f"Raspored_Matura_{sezona}"


def load_raspored_matura(sheet, sezona: str = SEZONA) -> pd.DataFrame:
    return _load_opcionalno(sheet, naziv_taba_rasporeda_mature(sezona))


def matura_grupa_id(dan: str, termin, ucionica: str) -> str:
    return f"{MATURA_PREFIKS}{dan}|{int(termin)}|{ucionica}"


def je_matura_grupa(grupa_id) -> bool:
    return str(grupa_id or "").startswith(MATURA_PREFIKS)


def labela_matura_grupe(grupa_id, vrijeme: str = "") -> str:
    """'MATURA|Subota|1|A' -> 'Matura · Subota T1 · Uč. A'. Ostale oznake vraća nepromijenjene."""
    if not je_matura_grupa(grupa_id):
        return grupa_id
    try:
        _p, dan, t, uc = str(grupa_id).split("|")
    except ValueError:
        return grupa_id
    return f"Matura · {dan} T{t}{(' ' + vrijeme) if vrijeme else ''} · Uč. {uc}"


def _je_online(v) -> bool:
    return "online" in str(v or "").lower()


def matura_kante(df_raspored: pd.DataFrame) -> list:
    """Kante (dan × termin × učionica) iz spremljenog rasporeda Mature, poredane po danu i terminu:
    [{grupa_id, dan, termin, vrijeme, ucionica, profesor, predmeti: [oznake], ucenici: [{ucenik_id,
    ime_djeteta, online, predmet}]}]. Retci bez redak_id (kanta samo s profesorom) daju praznu kantu."""
    if df_raspored is None or df_raspored.empty or "dan" not in df_raspored.columns:
        return []
    kante = {}
    for _, r in df_raspored.iterrows():
        dan, uc = str(r.get("dan", "")).strip(), str(r.get("ucionica", "")).strip()
        try:
            t = int(str(r.get("termin", "")).strip())
        except ValueError:
            continue
        if dan not in DANI_U_TJEDNU or not uc:
            continue
        gid = matura_grupa_id(dan, t, uc)
        k = kante.setdefault(gid, {"grupa_id": gid, "dan": dan, "termin": t, "vrijeme": "", "ucionica": uc,
                                    "profesor": "", "predmeti": [], "ucenici": []})
        k["vrijeme"] = k["vrijeme"] or str(r.get("vrijeme", "") or "").strip()
        k["profesor"] = k["profesor"] or str(r.get("profesor", "") or "").strip()
        if str(r.get("redak_id", "") or "").strip() and str(r.get("ucenik_id", "") or "").strip():
            oznaka = oznaka_predmeta_matura(r.get("predmet"), r.get("razina_ispita"))
            if oznaka not in k["predmeti"]:
                k["predmeti"].append(oznaka)
            k["ucenici"].append({"ucenik_id": str(r["ucenik_id"]).strip(), "ime_djeteta": str(r.get("ime_djeteta", "")),
                                 "online": _je_online(r.get("nacin_pracenja")), "predmet": oznaka})
    red_dana = {d: i for i, d in enumerate(DANI_U_TJEDNU)}
    out = sorted(kante.values(), key=lambda k: (red_dana[k["dan"]], k["termin"], k["ucionica"]))
    for k in out:
        k["predmeti"].sort()
        k["ucenici"].sort(key=lambda u: u["ime_djeteta"])
    return out


def labela_kante(k: dict, s_profesorom: bool = False) -> str:
    return (f"{k['dan']} T{k['termin']} {k['vrijeme']} · Uč. {k['ucionica']} · "
            f"{' + '.join(k['predmeti']) or '—'} ({len(k['ucenici'])} uč.)"
            + (f" · {k['profesor'] or 'bez profesora'}" if s_profesorom else ""))


def predmeti_nastavnika(df_nastavnici: pd.DataFrame, ime: str) -> list:
    """Predmeti Mature koje profesor predaje (stupac Nastavnici.predmeti, npr. 'MAT-A, MAT-B').
    Prazna lista = nije upisano → profesor vidi sve (da ništa ne pukne prije nego se popuni)."""
    if df_nastavnici is None or df_nastavnici.empty or "predmeti" not in df_nastavnici.columns:
        return []
    red = df_nastavnici[df_nastavnici["ime"] == ime]
    if red.empty:
        return []
    return [p.strip().upper() for p in re.split(r"[,;]", str(red.iloc[0]["predmeti"] or "")) if p.strip()]


def postavi_predmete_nastavnika(sheet, row_number: int, predmeti: list):
    """Admin: predmeti koje nastavnik predaje (stupac 'predmeti' se doda ako ga nema)."""
    ws = sheet.worksheet("Nastavnici")
    headers = ws.row_values(1)
    if "predmeti" not in headers:
        if ws.col_count < len(headers) + 1:
            ws.add_cols(1)
        ws.update_cell(1, len(headers) + 1, "predmeti")
        headers = headers + ["predmeti"]
    _azuriraj_polja(ws, row_number, {"predmeti": ", ".join(predmeti)}, headers)


def predaje_predmet(predmeti_prof: list, oznaka: str) -> bool:
    """Prazan popis = predaje sve. 'MAT' pokriva MAT-A i MAT-B; 'MAT-A' pokriva samo MAT-A."""
    if not predmeti_prof:
        return True
    o = str(oznaka or "").upper()
    for p in predmeti_prof:
        if o == p or o.split("-")[0] == p:
            return True
    return False


def kante_za_profesora(kante: list, ime: str, predmeti_prof: list):
    """(moje, ostale): moje = kante gdje je upisan kao profesor; ostale = kante NJEGOVIH predmeta
    kod drugih profesora (za "Držim sat umjesto kolege"). Kante drugih predmeta ne vidi."""
    moje = [k for k in kante if k["profesor"] == ime]
    ostale = [k for k in kante if k["profesor"] != ime
              and (any(predaje_predmet(predmeti_prof, o) for o in k["predmeti"])
                   or (not k["predmeti"] and not predmeti_prof))]
    return moje, ostale


def zadnji_datum_dana(dan: str, danas: date) -> date:
    """Najbliži datum <= danas koji pada na zadani dan u tjednu (zadani datum sata)."""
    razlika = (danas.weekday() - DANI_U_TJEDNU.index(dan)) % 7
    return danas - timedelta(days=razlika)


def datum_u_roku(datum: date, danas: date, dana: int = ROK_PROFESOR_DANA) -> bool:
    return danas - timedelta(days=dana) <= datum <= danas


def postojeci_dolasci(df_termini: pd.DataFrame, df_dolasci: pd.DataFrame, grupa_id: str, datum: str) -> dict:
    """{ucenik_id: status} već spremljenog sata (za ispravak), ili {} ako sat još nije zabilježen."""
    if df_termini is None or df_termini.empty or df_dolasci is None or df_dolasci.empty:
        return {}
    t = df_termini[(df_termini["grupa_id"].astype(str) == str(grupa_id))
                   & (df_termini["datum"].astype(str).str[:10] == str(datum)[:10])]
    if t.empty:
        return {}
    tid = str(t.iloc[0]["termin_id"])
    d = df_dolasci[df_dolasci["termin_id"].astype(str) == tid]
    return {str(r["ucenik_id"]): str(r["status"]) for _, r in d.iterrows()}


ZNAK_DOLASKA = {"1": "✅", "0": "❌", "2": "💻"}


def dolasci_matura(df_termini: pd.DataFrame, df_dolasci: pd.DataFrame) -> pd.DataFrame:
    """Svi zapisi dolazaka na Matura satove: grupa_id, datum, ucenik_id, ime_djeteta, status, nastavnik_odrzao."""
    stupci = ["grupa_id", "datum", "ucenik_id", "ime_djeteta", "status", "nastavnik_odrzao"]
    if df_termini is None or df_termini.empty or df_dolasci is None or df_dolasci.empty:
        return pd.DataFrame(columns=stupci)
    d = df_dolasci[df_dolasci["grupa_id"].astype(str).str.startswith(MATURA_PREFIKS)]
    if d.empty:
        return pd.DataFrame(columns=stupci)
    t = df_termini[["termin_id", "datum"] + (["nastavnik_odrzao"] if "nastavnik_odrzao" in df_termini.columns else [])]
    d = d.merge(t, on="termin_id", how="left")
    d["datum"] = d["datum"].astype(str).str[:10]
    d["status"] = d["status"].astype(str)
    if "nastavnik_odrzao" not in d.columns:
        d["nastavnik_odrzao"] = ""
    return d[stupci].reset_index(drop=True)


def tablica_dolazaka_kante(d_matura: pd.DataFrame, kanta: dict) -> pd.DataFrame:
    """Učenik × datum (✅/❌/💻) za jednu kantu + stupac '%' (prisutan ili online / svi zapisi).
    Uključuje učenike iz rasporeda i one koji su bili zapisani (npr. premješteni kasnije)."""
    d = d_matura[d_matura["grupa_id"] == kanta["grupa_id"]] if not d_matura.empty else d_matura
    datumi = sorted(set(d["datum"])) if not d.empty else []
    imena = {u["ucenik_id"]: u["ime_djeteta"] for u in kanta["ucenici"]}
    for _, r in d.iterrows():
        imena.setdefault(str(r["ucenik_id"]), str(r["ime_djeteta"]))
    retci = []
    for uid, ime in sorted(imena.items(), key=lambda x: x[1]):
        du = d[d["ucenik_id"].astype(str) == uid]
        st_po_datumu = dict(zip(du["datum"], du["status"]))
        red = {"Učenik": ime}
        for dt in datumi:
            red[_kratki_datum(dt)] = ZNAK_DOLASKA.get(st_po_datumu.get(dt, ""), "")
        red["%"] = f"{round(100 * du['status'].isin(['1', '2']).sum() / len(du))} %" if len(du) else "—"
        retci.append(red)
    return pd.DataFrame(retci)


def _kratki_datum(iso: str) -> str:
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").strftime("%d.%m.")
    except ValueError:
        return str(iso)


def portal_raspored_matura(df_raspored: pd.DataFrame, ucenik_id: str) -> pd.DataFrame:
    """Moj CAKI: tjedni raspored Mature za jednog učenika (bez imena drugih učenika i bez profesora)."""
    retci = []
    for k in matura_kante(df_raspored):
        for u in k["ucenici"]:
            if u["ucenik_id"] == str(ucenik_id):
                retci.append({"Dan": k["dan"], "Vrijeme": k["vrijeme"], "Predmet": u["predmet"],
                              "Učionica": k["ucionica"] + (" (online)" if u["online"] else "")})
    return pd.DataFrame(retci)


def broj_mobitela_za_whatsapp(broj) -> str:
    """'091 234 5678' / '+385 91 234 5678' / '00385912345678' -> '385912345678' (za wa.me link)."""
    b = re.sub(r"\D", "", str(broj or ""))
    if b.startswith("00"):
        b = b[2:]
    if b.startswith("0"):
        b = "385" + b[1:]
    return b if len(b) >= 9 else ""


def whatsapp_link(tekst: str, broj: str = "") -> str:
    """Link koji otvori WhatsApp s pripremljenom porukom. Bez broja: WhatsApp pita kome (grupa,
    zajednica, osoba). S brojem: otvori razgovor s tom osobom. Ništa se ne šalje samo — šalje Caki."""
    from urllib.parse import quote
    return f"https://wa.me/{broj_mobitela_za_whatsapp(broj) if broj else ''}?text={quote(tekst)}"


# ============================================================
# 🆕 30.9.2026. — RUČNO SLANJE MAILA (i WhatsApp poruke) IZ KARTICE UČENIKA
# Tok: admin u kartici odabere program, vrstu i predložak, pregleda tekst i klikne
# "Pošalji" → redak u tabu Mail_dnevnik sa statusom "Za slanje" → Apps Script
# CAKI_mail_rucno.gs (svake minute) pošalje mail s info@ i upiše thread i link.
# Automatskog slanja NEMA: bez klika admina ne odlazi ništa.
# ============================================================

MAIL_DNEVNIK_TAB = "Mail_dnevnik"
MAIL_DNEVNIK_HEADERS = [
    "mail_id", "datum_zahtjeva", "ucenik_id", "ime_djeteta", "program", "vrsta", "predlozak",
    "nacin", "odgovor_na_thread", "prima", "kopija", "predmet", "tijelo",
    "status", "datum_slanja", "gmail_thread_id", "gmail_message_id", "gmail_link", "greska", "poslao",
]
MAIL_PREDLOSCI_TAB = "Mail_predlosci"
MAIL_PREDLOSCI_HEADERS = ["kljuc", "program", "vrsta", "predmet", "tijelo"]
MAIL_VRSTE = ["ponuda", "podsjetnik", "programi/raspored", "promo"]
MAIL_VRSTE_AKTIVNE = ["ponuda", "podsjetnik", "programi/raspored"]   # promo tek uz GDPR privolu
MAIL_PROGRAMI = ["Upisi", "Matura"]                                    # Instrukcije naknadno
MAIL_FAZA_U_NASLOVU = {"ponuda": "ponuda", "podsjetnik": "podsjetnik",
                       "programi/raspored": "programi i raspored", "promo": "novosti"}
MAIL_CC = ["info@cakipoduka.com", "matematika@cakipoduka.com"]
GMAIL_RACUN = "info@cakipoduka.com"
NACIN_NOVI = "novi"
NACIN_ODGOVOR = "odgovor"
THREAD_AUTO = "AUTO"      # Apps Script sam nađe najnoviji razgovor s tim adresama u Gmailu
STATUS_ZA_SLANJE = "Za slanje"
STATUSI_U_TIJEKU = ("Za slanje", "Šalje se…")

# Postojeći predlošci (koristi ih 💶 Financije) — kojem programu i vrsti pripadaju
_VRSTA_POSTOJECIH = {
    "upisi_potvrda": ("Upisi", "ponuda"),
    "matura_potvrda": ("Matura", "ponuda"),
    "instrukcije_obracun": ("Instrukcije", "ponuda"),
}

_POTPIS = "\n\nZa sva pitanja slobodno nam se javite.\n\nSrdačan pozdrav,\nCAKI centar"

# PRIVREMENI tekstovi — admin ih mijenja na ⚙️ Postavke → ✉️ Mail predlošci (bez novog koda)
PRIVREMENI_PREDLOSCI = [
    {"kljuc": "upisi_podsjetnik", "program": "Upisi", "vrsta": "podsjetnik",
     "predmet": "UPISI {skolska_godina}g. - {ime_djeteta} - podsjetnik",
     "tijelo": "Poštovani/a {ime_roditelja},\n\nljubazno podsjećamo da ponuda za {ime_djeteta} još čeka uplatu:\n\n"
               "{link_ponuda}\n\nAko ste već uplatili, zanemarite ovu poruku — uplata će biti vidljiva u "
               "portalu Moj CAKI čim je evidentiramo.\n\n{moj_caki}" + _POTPIS},
    {"kljuc": "upisi_raspored", "program": "Upisi", "vrsta": "programi/raspored",
     "predmet": "UPISI {skolska_godina}g. - {ime_djeteta} - program i raspored",
     "tijelo": "Poštovani/a {ime_roditelja},\n\nšaljemo informacije o programu za {ime_djeteta}:\n\n"
               "{popis_programa}\n\n{odjeljak_termina}\n\n{moj_caki}" + _POTPIS},
    {"kljuc": "matura_podsjetnik", "program": "Matura", "vrsta": "podsjetnik",
     "predmet": "MATURA {skolska_godina}g. - {ime_djeteta} - podsjetnik",
     "tijelo": "Poštovani/a {ime_roditelja},\n\nljubazno podsjećamo da ponuda za pripreme za državnu maturu "
               "({ime_djeteta}) još čeka uplatu:\n\n{link_ponuda}\n\nAko ste već uplatili, zanemarite ovu poruku — "
               "uplata će biti vidljiva u portalu Moj CAKI čim je evidentiramo.\n\n{moj_caki}" + _POTPIS},
    {"kljuc": "matura_raspored", "program": "Matura", "vrsta": "programi/raspored",
     "predmet": "MATURA {skolska_godina}g. - {ime_djeteta} - program i raspored",
     "tijelo": "Poštovani/a {ime_roditelja},\n\nšaljemo informacije o pripremama za državnu maturu za "
               "{ime_djeteta}:\n\n{popis_programa}\n\nRaspored nastave (dan, vrijeme, učionica) vidi se u "
               "portalu Moj CAKI:\n\n{moj_caki}" + _POTPIS},
]

OZNAKE_PREDLOZAKA = {
    "ime_roditelja": "ime roditelja", "ime_djeteta": "ime i prezime djeteta", "sifra": "šifra učenika",
    "program": "Upisi / Matura", "program_veliko": "UPISI / MATURA",
    "skolska_godina": "školska godina iz sezone, npr. 2026.-2027. (u naslov dopiši sam npr. 'g.')",
    "faza": "ponuda / podsjetnik / programi i raspored",
    "moj_caki": "ime, šifra i osobni link na Moj CAKI (dodaje se sam ako ga nema)",
    "popis_programa": "stavke ponude s cijenama", "link_ponuda": "link(ovi) na PDF ponude iz Sola (s ratama i rokovima)",
    "odjeljak_termina": "Upisi: link za odabir termina (ili tekst za online); Matura: prazno",
}


def skolska_godina(sezona: str = "") -> str:
    """'2026/27' → '2026.-2027.' (za naslove, npr. 'MATURA 2026.-2027.g. - Dora Trstenjak')."""
    m = re.match(r"^\s*(\d{4})\s*/\s*(\d{2,4})\s*$", str(sezona or SEZONA))
    if not m:
        return str(sezona or SEZONA)
    g1 = int(m.group(1))
    return f"{g1}.-{g1 + 1}."


def naslov_iz_predloska(predmet_predloska: str, zamjene: dict, program: str, ime_djeteta: str, vrsta: str) -> str:
    """Naslov ručnog maila: iz predloška (s popunjenim oznakama) ili, ako je prazan, "Program, Ime, faza"."""
    p = str(predmet_predloska or "").strip()
    if not p or p.lower() == "nan":
        return naslov_rucnog_maila(program, ime_djeteta, vrsta)
    return re.sub(r"\s{2,}", " ", popuni_mail_pregled(p, zamjene)).strip()


def naslov_rucnog_maila(program: str, ime_djeteta: str, vrsta: str) -> str:
    """Odluka 30.9.2026.: "Program, Ime Prezime djeteta, faza" — bez predmeta u naslovu."""
    faza = MAIL_FAZA_U_NASLOVU.get(vrsta, vrsta)
    return f"{program}, {str(ime_djeteta or '').strip()}, {faza}"


def primatelji_maila(ucenik: dict) -> tuple:
    """(To, Cc): To = dijete + roditelj (bez praznih i duplikata), Cc = info@ i matematika@."""
    to = []
    for kljuc in ("email_djeteta", "email_roditelja"):
        e = str(ucenik.get(kljuc, "") or "").strip()
        if e and e.lower() not in [x.lower() for x in to]:
            to.append(e)
    return to, list(MAIL_CC)


def gmail_link(thread_id: str) -> str:
    """Link koji otvara thread u Gmailu računa info@ (i kad je u pregledniku prijavljeno više računa)."""
    return f"https://mail.google.com/mail/?authuser={GMAIL_RACUN}#all/{thread_id}" if thread_id else ""


def load_mail_predlosci(sheet) -> pd.DataFrame:
    """Svi predlošci; program/vrsta za stare ključeve popunjavaju se sami ako stupci još ne postoje."""
    try:
        df = _load_worksheet_df(sheet.worksheet(MAIL_PREDLOSCI_TAB))
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame(columns=MAIL_PREDLOSCI_HEADERS + ["_row"])
    for h in MAIL_PREDLOSCI_HEADERS:
        if h not in df.columns:
            df[h] = ""
        df[h] = df[h].astype(str).replace("nan", "")
    for i, r in df.iterrows():
        prog, vrsta = _VRSTA_POSTOJECIH.get(r["kljuc"], ("", ""))
        if not r["program"] and prog:
            df.at[i, "program"] = prog
        if not r["vrsta"] and vrsta:
            df.at[i, "vrsta"] = vrsta
    return df


def predlosci_za(df_predlosci: pd.DataFrame, program: str, vrsta: str) -> pd.DataFrame:
    if df_predlosci.empty:
        return df_predlosci
    return df_predlosci[(df_predlosci["program"] == program) & (df_predlosci["vrsta"] == vrsta)]


def osiguraj_mail_predloske(sheet) -> dict:
    """Jednokratno (sigurno ponoviti): tab Mail_predlosci dobiva stupce program i vrsta, stari ključevi
    dobivaju vrstu, a nedostajući PRIVREMENI predlošci se dodaju. Postojeći tekstovi se NE diraju."""
    rez = {"dodani_stupci": [], "dodani_predlosci": [], "popunjena_vrsta": []}
    try:
        ws = sheet.worksheet(MAIL_PREDLOSCI_TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=MAIL_PREDLOSCI_TAB, rows=100, cols=len(MAIL_PREDLOSCI_HEADERS))
        ws.append_row(MAIL_PREDLOSCI_HEADERS)
        rez["dodani_stupci"] = list(MAIL_PREDLOSCI_HEADERS)
    headers = ws.row_values(1)
    for h in MAIL_PREDLOSCI_HEADERS:
        if h not in headers:
            ws.update_cell(1, len(headers) + 1, h)
            headers.append(h)
            rez["dodani_stupci"].append(h)
    zapisi = ws.get_all_records()
    for i, r in enumerate(zapisi, start=2):
        prog, vrsta = _VRSTA_POSTOJECIH.get(r.get("kljuc", ""), ("", ""))
        polja = {}
        if prog and not str(r.get("program", "")).strip():
            polja["program"] = prog
        if vrsta and not str(r.get("vrsta", "")).strip():
            polja["vrsta"] = vrsta
        if polja:
            _azuriraj_polja(ws, i, polja, headers)
            rez["popunjena_vrsta"].append(r.get("kljuc", ""))
    postojeci = {str(r.get("kljuc", "")) for r in zapisi}
    for p in PRIVREMENI_PREDLOSCI:
        if p["kljuc"] not in postojeci:
            _dodaj_red_po_nazivu(ws, p, headers)
            rez["dodani_predlosci"].append(p["kljuc"])
    return rez


def spremi_mail_predlozak(sheet, kljuc: str, program: str, vrsta: str, predmet: str, tijelo: str) -> str:
    """Upis ili izmjena predloška po ključu. Vraća 'novi' ili 'izmijenjen'."""
    kljuc = re.sub(r"[^a-z0-9_]", "_", str(kljuc or "").strip().lower())
    if not kljuc:
        raise ValueError("Ključ predloška ne smije biti prazan.")
    if vrsta not in MAIL_VRSTE:
        raise ValueError(f"Nepoznata vrsta '{vrsta}'.")
    if not str(tijelo or "").strip():
        raise ValueError("Tekst predloška ne smije biti prazan.")
    ws = sheet.worksheet(MAIL_PREDLOSCI_TAB)
    headers = ws.row_values(1)
    nedostaju = [h for h in MAIL_PREDLOSCI_HEADERS if h not in headers]
    if nedostaju:
        raise ValueError("Tab Mail_predlosci nema stupce " + ", ".join(nedostaju) +
                         " — klikni prvo '🔧 Pripremi predloške'.")
    polja = {"kljuc": kljuc, "program": program, "vrsta": vrsta, "predmet": predmet, "tijelo": tijelo}
    for i, r in enumerate(ws.get_all_records(), start=2):
        if r.get("kljuc") == kljuc:
            _azuriraj_polja(ws, i, polja, headers)
            return "izmijenjen"
    _dodaj_red_po_nazivu(ws, polja, headers)
    return "novi"


def postavi_tab_mail_dnevnik(sheet) -> bool:
    """Kreira tab Mail_dnevnik ako ne postoji. Vraća True ako je kreiran."""
    if MAIL_DNEVNIK_TAB in [ws.title for ws in sheet.worksheets()]:
        return False
    ws = sheet.add_worksheet(title=MAIL_DNEVNIK_TAB, rows=1000, cols=len(MAIL_DNEVNIK_HEADERS))
    ws.append_row(MAIL_DNEVNIK_HEADERS)
    return True


def load_mail_dnevnik(sheet) -> pd.DataFrame:
    try:
        df = _load_worksheet_df(sheet.worksheet(MAIL_DNEVNIK_TAB))
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame(columns=MAIL_DNEVNIK_HEADERS + ["_row"])
    for h in MAIL_DNEVNIK_HEADERS:
        if h not in df.columns:
            df[h] = ""
        df[h] = df[h].astype(str).replace("nan", "")
    return df


def threadovi_ucenika(df_dnevnik: pd.DataFrame, ucenik_id: str) -> list:
    """Razgovori (threadovi) koje je CRM već poslao ovom učeniku — najnoviji prvi, svaki jednom."""
    if df_dnevnik.empty:
        return []
    df = df_dnevnik[(df_dnevnik["ucenik_id"] == ucenik_id) & (df_dnevnik["status"] == "Poslano")
                    & (df_dnevnik["gmail_thread_id"] != "")]
    df = df.sort_values("datum_slanja", ascending=False)
    out, vidjeni = [], set()
    for _, r in df.iterrows():
        if r["gmail_thread_id"] in vidjeni:
            continue
        vidjeni.add(r["gmail_thread_id"])
        out.append({"thread_id": r["gmail_thread_id"], "predmet": r["predmet"], "datum": r["datum_slanja"],
                    "vrsta": r["vrsta"], "link": r["gmail_link"] or gmail_link(r["gmail_thread_id"])})
    return out


def _datum_kratko(v) -> str:
    d = pd.to_datetime(prikazi_datum(v) or None, errors="coerce")
    return "" if pd.isna(d) else f"{d.day}.{d.month}.{d.year}."


def zamjene_za_rucni_mail(ucenik: dict, df_racuni: pd.DataFrame, program: str,
                          portal_url: str, online: bool = False, vrsta: str = "") -> dict:
    """Vrijednosti za {oznake} u ručnom mailu. link_ponuda/popis_programa dolaze iz poslanih a neplaćenih
    ponuda (status Poslano ili Isteklo) tog programa u Racuni_i_ponude — isti oblik kao automatski mail."""
    uid = str(ucenik.get("ucenik_id", ""))
    ime = str(ucenik.get("ime_djeteta", "") or "")
    z = {
        "ime_roditelja": str(ucenik.get("ime_roditelja", "") or ""),
        "ime_djeteta": ime, "sifra": uid,
        "moj_caki": tekst_moj_caki(ime, uid, portal_url),
        "popis_programa": "", "link_ponuda": "", "odjeljak_termina": "",
        "program": program, "program_veliko": str(program).upper(), "skolska_godina": skolska_godina(),
        "faza": MAIL_FAZA_U_NASLOVU.get(vrsta, vrsta),
    }
    if program == "Upisi":
        if online:
            z["odjeljak_termina"] = ("Budući da pratite nastavu isključivo online, ne trebate birati termin — "
                                     "možete se pridružiti bilo kojem terminu grupe koja vam odgovara.")
        else:
            z["odjeljak_termina"] = (f"Termin nastave birate ovdje (link je personaliziran za {ime}):\n"
                                     f"{str(portal_url).rstrip('/')}/?ucenik_id={uid}\n\n"
                                     f"Rezervaciju termina potrebno je potvrditi uplatom u roku od "
                                     f"{REZERVACIJA_ROK_DANA} dana, nakon čega mjesto može biti ponuđeno "
                                     f"sljedećem djetetu na listi čekanja.")
    if df_racuni is None or df_racuni.empty or "status" not in df_racuni.columns:
        return z
    dok = df_racuni[(df_racuni["ucenik_id"].astype(str) == uid)
                    & (df_racuni.get("program_tip", "").astype(str) == program)
                    & (df_racuni["status"].isin(["Poslano", "Isteklo"]))]
    if dok.empty:
        return z
    grupe = {}
    for _, r in dok.iterrows():
        g = str(r.get("rata_grupa_id", "") or "").strip()
        g = r["dokument_id"] if g in ("", "nan") else g
        grupe.setdefault(g, []).append(r)
    linkovi, popisi = [], []
    for g, retci in grupe.items():
        retci.sort(key=lambda r: float(r.get("rata_broj") or 0) if str(r.get("rata_broj", "")) not in ("", "nan") else 0)
        prvi = retci[0]
        izvorne = parsiraj_stavke(prvi.get("stavke_izvorno_json", "")) or parsiraj_stavke(prvi.get("stavke_snapshot_json", ""))
        if izvorne:
            popisi.append(popis_programa_za_mail(izvorne))
        for r in retci:
            link = str(r.get("link_pdf", "") or "")
            ukupno = str(r.get("rata_ukupno_u_grupi", "") or "")
            if ukupno not in ("", "nan", "0", "1", "1.0") and len(retci) > 1:
                rok = _datum_kratko(r.get("rok_placanja", ""))
                broj = str(r.get("rata_broj", "")).replace(".0", "")
                linkovi.append(f"Rata {broj}/{ukupno.replace('.0', '')} — za uplatu "
                               f"{centi_u_tekst(u_cente(r.get('iznos_ukupno')) or 0)} €"
                               + (f" (rok {rok})" if rok else "") + f":\n{link}")
            else:
                linkovi.append(link)
    z["link_ponuda"] = "\n\n".join(l for l in linkovi if l)
    z["popis_programa"] = "\n".join(p for p in popisi if p)
    return z


def popuni_rucni_mail(tijelo: str, zamjene: dict, vrsta: str = "") -> str:
    """Tekst maila spreman za slanje. Ime, šifra i Moj CAKI uvijek su u mailu (pravilo 27.9.2026.);
    kod ponude i podsjetnika link na ponudu se doda na kraj ako je {link_ponuda} obrisan."""
    t = str(tijelo or "")
    if vrsta in ("ponuda", "podsjetnik") and "{link_ponuda}" not in t and zamjene.get("link_ponuda"):
        t += "\n\nPonuda za uplatu:\n{link_ponuda}"
    if "{moj_caki}" not in t:
        t += "\n\n{moj_caki}"
    t = popuni_mail_pregled(t, zamjene)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def provjeri_rucni_mail(to: list, predmet: str, tijelo: str, nacin: str, thread: str, vrsta: str = "",
                        ima_ponudu: bool = True) -> list:
    """Popis prepreka slanju (prazan = smije se poslati)."""
    greske = []
    if not to:
        greske.append("Nema email adrese djeteta ni roditelja (upiši je gore i spremi).")
    for e in to:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", e):
            greske.append(f"Neispravna email adresa: {e}")
    if nacin == NACIN_NOVI and not str(predmet or "").strip():
        greske.append("Naslov maila je prazan.")
    if nacin == NACIN_NOVI and re.findall(r"\{[a-z_]+\}", str(predmet or "")):
        greske.append("U naslovu su ostale nepopunjene oznake: " +
                      ", ".join(sorted(set(re.findall(r"\{[a-z_]+\}", str(predmet or ""))))))
    if not str(tijelo or "").strip():
        greske.append("Tekst maila je prazan.")
    ostaci = re.findall(r"\{[a-z_]+\}", str(tijelo or ""))
    if ostaci:
        greske.append("U tekstu su ostale nepopunjene oznake: " + ", ".join(sorted(set(ostaci))))
    if nacin == NACIN_ODGOVOR and not str(thread or "").strip():
        greske.append("Odaberi razgovor (thread) na koji se odgovara.")
    if vrsta in ("ponuda", "podsjetnik") and not ima_ponudu:
        greske.append("U mailu nema linka na ponudu — ovaj učenik nema poslanu (neplaćenu) ponudu u 💶 Financije "
                      "za odabrani program. Pošalji ponudu u Solo ili odaberi drugu vrstu maila.")
    return greske


def zatrazi_slanje_maila(sheet, ucenik: dict, program: str, vrsta: str, predlozak: str, nacin: str,
                         thread: str, predmet: str, tijelo: str, poslao: str = "", ima_ponudu: bool = True) -> str:
    """Upisuje zahtjev u Mail_dnevnik (status 'Za slanje'); šalje ga Apps Script u roku ~1 min.
    Zaštita od dvostrukog klika: isti tekst istom učeniku koji još čeka slanje se ne upisuje ponovno."""
    to, cc = primatelji_maila(ucenik)
    greske = provjeri_rucni_mail(to, predmet, tijelo, nacin, thread, vrsta, ima_ponudu)
    if greske:
        raise ValueError(" ".join(greske))
    postavi_tab_mail_dnevnik(sheet)
    ws = sheet.worksheet(MAIL_DNEVNIK_TAB)
    headers = ws.row_values(1)
    uid = str(ucenik.get("ucenik_id", ""))
    for r in ws.get_all_records():
        if (str(r.get("ucenik_id")) == uid and r.get("status") in STATUSI_U_TIJEKU
                and str(r.get("tijelo", "")).strip() == str(tijelo).strip()):
            raise ValueError("Isti mail ovom učeniku već čeka slanje (dvostruki klik?) — pričekaj minutu.")
    mail_id = "M-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    _dodaj_red_po_nazivu(ws, {
        "mail_id": mail_id, "datum_zahtjeva": sada_zagreb().strftime("%Y-%m-%d %H:%M:%S"),
        "ucenik_id": uid, "ime_djeteta": str(ucenik.get("ime_djeteta", "")), "program": program,
        "vrsta": vrsta, "predlozak": predlozak, "nacin": nacin,
        "odgovor_na_thread": thread if nacin == NACIN_ODGOVOR else "",
        "prima": ", ".join(to), "kopija": ", ".join(cc), "predmet": str(predmet or "").strip(),
        "tijelo": str(tijelo), "status": STATUS_ZA_SLANJE, "poslao": poslao,
    }, headers)
    if vrsta == "ponuda":
        oznaci_ponude_poslane_mailom(sheet, uid, program)
    return mail_id

def oznaci_ponude_poslane_mailom(sheet, ucenik_id: str, program: str) -> int:
    """1.10.2026.: automatski mail nakon Solo ponude je isključen — ponudu roditelju šalje admin ručnim
    mailom (vrsta "ponuda"). Tada se poslane, neplaćene ponude tog učenika i programa (iste one čiji je link
    u mailu) označe mail_poslan = "Da", kao što je prije radio automatski mail. Bez toga ih portal Moj CAKI
    skriva (pravilo za rate: roditelj vidi ponudu tek kad dobije mail). Vraća broj označenih dokumenata."""
    try:
        ws = sheet.worksheet(LEDGER_TAB)
    except Exception:
        return 0
    vrijednosti = ws.get_all_values()
    if not vrijednosti:
        return 0
    h = [str(x).strip() for x in vrijednosti[0]]
    if not all(k in h for k in ("ucenik_id", "program_tip", "status", "mail_poslan")):
        return 0
    i_u, i_p, i_s, i_m = (h.index(k) for k in ("ucenik_id", "program_tip", "status", "mail_poslan"))
    oznaceno = 0
    for broj_retka, r in enumerate(vrijednosti[1:], start=2):
        r = list(r) + [""] * (len(h) - len(r))
        if (str(r[i_u]).strip() == str(ucenik_id) and str(r[i_p]).strip() == program
                and str(r[i_s]).strip() in ("Poslano", "Isteklo") and not str(r[i_m]).strip()):
            _azuriraj_polja(ws, broj_retka, {"mail_poslan": "Da"}, h)
            oznaceno += 1
    return oznaceno


def otkazi_zahtjev_maila(sheet, mail_id: str) -> bool:
    """Zahtjev koji još čeka ('Za slanje') → 'Otkazano'. Već poslani mail se ne može opozvati."""
    ws = sheet.worksheet(MAIL_DNEVNIK_TAB)
    headers = ws.row_values(1)
    for i, r in enumerate(ws.get_all_records(), start=2):
        if r.get("mail_id") == mail_id:
            if r.get("status") != STATUS_ZA_SLANJE:
                return False
            _azuriraj_polja(ws, i, {"status": "Otkazano"}, headers)
            return True
    return False


# ============================================================
# 🆕 1.10.2026. — A) ♻️ VRATI U NACRT  ·  B) DODAJ/UKLONI PREDMET IZRAVNO U NACRTU
# Cilj: ispravak tijekom razgovora s roditeljem bez ponovnog prolaska kroz
# "dodaj komponentu → Potvrdio → Pošalji ponudu".
# ============================================================

STATUSI_ZA_VRACANJE = ("Otkazano", "Obrisano")
OZNAKA_VRACENO = "♻️ Vraćeno iz"

# Šifra iz Solo kataloga → Matura predmet i razina (obrnuto od MATURA_SIFRA_PREDMETA u CAKI_financije.gs)
MATURA_SIFRA_U_PREDMET = {
    "MATURA-HRV": ("hrvatski", ""),
    "MATURA-MAT-A": ("matematika", "A"), "MATURA-MAT-B": ("matematika", "B"),
    "MATURA-ENG-A": ("engleski", "A"), "MATURA-ENG-B": ("engleski", "B"),
    "MATURA-FIZ": ("fizika", ""), "MATURA-FIZ-MED": ("fizika_medicina", ""),
}


def _cisto(v) -> str:
    return "" if v is None or (isinstance(v, float) and math.isnan(v)) or str(v) == "nan" else str(v)


def vec_vraceno(df_racuni: pd.DataFrame, dokument_id: str) -> bool:
    """Je li iz ovog (otkazanog/obrisanog) dokumenta već napravljen novi nacrt?"""
    if df_racuni.empty or "upozorenja" not in df_racuni.columns:
        return False
    return df_racuni["upozorenja"].astype(str).str.contains(f"{OZNAKA_VRACENO} {dokument_id}", regex=False).any()


def dokumenti_za_vracanje(df_racuni: pd.DataFrame) -> pd.DataFrame:
    """Otkazani/obrisani Upisi i Matura dokumenti (po jedan red po grupi rata) koji još nisu vraćeni.
    Instrukcije se NE vraćaju ovako (njihovi termini se pri odbacivanju već vraćaju u obračun)."""
    if df_racuni.empty or "status" not in df_racuni.columns:
        return df_racuni
    df = df_racuni[df_racuni["status"].isin(STATUSI_ZA_VRACANJE)
                   & df_racuni["program_tip"].isin(["Upisi", "Matura"])].copy()
    if df.empty:
        return df
    df["_grupa"] = [(_cisto(g) or d) for g, d in zip(df.get("rata_grupa_id", ""), df["dokument_id"])]
    df = df.drop_duplicates("_grupa")
    return df[[not vec_vraceno(df_racuni, d) for d in df["dokument_id"]]]


def vrati_u_nacrt(sheet, df_racuni: pd.DataFrame, red) -> str:
    """A) ♻️ Otkazani/obrisani dokument (sa svim ratama) → NOVI nacrt s istim stavkama, subjektom,
    načinom uplate i napomenom. Ništa ne ide u Solo; admin ga ispravi i pošalje kao i svaki nacrt.
    Prijave tih predmeta koje su bile Otkazano/Odustao vraćaju se u Potvrdio. Vraća novi dokument_id."""
    red = red.to_dict() if hasattr(red, "to_dict") else dict(red)
    grupa = dokumenti_grupe(df_racuni, pd.Series(red)).copy()
    if not grupa["status"].isin(STATUSI_ZA_VRACANJE).all():
        raise ValueError("Vratiti u nacrt mogu se samo Otkazani ili Obrisani dokumenti (sve rate).")
    if any(vec_vraceno(df_racuni, d) for d in grupa["dokument_id"]):
        raise ValueError("Ovaj dokument je već vraćen u nacrt — pogledaj tab 🟡 Čeka odobrenje.")
    grupa["_k"] = pd.to_numeric(grupa.get("rata_broj", 1), errors="coerce").fillna(1)
    grupa = grupa.sort_values("_k")
    prvi = grupa.iloc[0].to_dict()
    stavke = parsiraj_stavke(_cisto(prvi.get("stavke_izvorno_json")) or prvi.get("stavke_snapshot_json"))
    if not stavke:
        raise ValueError("Dokument nema zapisane stavke — napravi novu ponudu.")
    stavke = preracunaj_stavke(stavke)
    izvori = []
    for v in grupa.get("izvorni_redci", []):
        for s_ in sifre_izvora(_cisto(v)):
            if s_ not in izvori:
                izvori.append(s_)
    stari = ", ".join(grupa["dokument_id"])
    upoz = f"{OZNAKA_VRACENO} {stari}. Provjeri stavke, popust i rate pa pošalji."
    if len(grupa) > 1:
        upoz += f" Prije: NA RATE ({len(grupa)})."

    novi_id = "D-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    ws = sheet.worksheet(LEDGER_TAB)
    _dodaj_red_po_nazivu(ws, {
        "dokument_id": novi_id, "ucenik_id": _cisto(prvi.get("ucenik_id")), "ime_djeteta": _cisto(prvi.get("ime_djeteta")),
        "program_tip": _cisto(prvi.get("program_tip")), "solo_racun": _cisto(prvi.get("solo_racun")),
        "tip_dokumenta": _cisto(prvi.get("tip_dokumenta")) or "Ponuda", "status": "Nacrt",
        "iznos_ukupno": zbroj_stavki_centi(stavke) / 100,
        "stavke_snapshot_json": json.dumps(stavke, ensure_ascii=False),
        "izvorni_redci": ",".join(izvori), "nacin_uplate": _cisto(prvi.get("nacin_uplate")) or 1,
        "napomena": _cisto(prvi.get("napomena")), "datum_kreiranja": sada_zagreb().strftime("%Y-%m-%d %H:%M:%S"),
        "upozorenja": upoz,
    })
    # Prijave koje su pri otkazivanju označene Otkazano/Odustao → opet Potvrdio
    rids = [s_[2:] for s_ in izvori if s_.startswith("P:")]
    if rids:
        wp = sheet.worksheet("Prijave")
        hp = wp.row_values(1)
        for i, r in enumerate(wp.get_all_records(), start=2):
            if str(r.get("redak_id")) in rids and r.get("status_kontakta") in ("Otkazano", "Odustao"):
                _azuriraj_polja(wp, i, {"status_kontakta": "Potvrdio"}, hp)
    return novi_id


def sifre_izvora(izvorni_redci: str) -> list:
    return [s_.strip() for s_ in str(izvorni_redci or "").split(",") if s_.strip()]


def stavke_cjenika_za_nacrt(df_cjenik: pd.DataFrame, program: str, subjekt: str = "") -> list:
    """B) Ponuda za "➕ Dodaj iz Cjenika": stavke tog programa (MATURA-… / UPISI-…), samo one koje su u Solu.
    Ako je subjekt odabran, prednost imaju njegove cijene. [{sifra, opis, centi}] po šifri, abecedno po nazivu."""
    if df_cjenik is None or df_cjenik.empty or "sifra" not in df_cjenik.columns:
        return []
    pref = {"Matura": "MATURA-", "Upisi": "UPISI-"}.get(program, "")
    if not pref:
        return []
    df = df_cjenik[df_cjenik["sifra"].astype(str).str.startswith(pref)]
    if "u_solu" in df.columns:
        df = df[df["u_solu"].astype(str) != "Ne"]
    out = {}
    for _, r in df.iterrows():
        sifra = str(r["sifra"])
        centi = u_cente(r.get("cijena"))
        if centi is None:
            continue
        zapis = {"sifra": sifra, "opis": _cisto(r.get("opis")).strip() or sifra, "centi": centi}
        if sifra not in out or (subjekt and r.get("subjekt") == subjekt):
            out[sifra] = zapis
    return sorted(out.values(), key=lambda z: z["opis"].lower())


def dodaj_stavku_u_nacrt(sheet, red: dict, sifra: str, opis: str, centi: int, popust: float = 0) -> str:
    """B) ➕ Predmet/komponenta izravno u nacrt. Za poznate šifre nastaje i redak u Prijave (Potvrdio),
    da predmet postoji i za raspored/dolazke — i odmah je vezan uz OVAJ nacrt, pa ga Assembler ne
    ubacuje u novi. Vraća redak_id nove prijave ili '' (stavka bez prijave, npr. simulacija)."""
    red = red.to_dict() if hasattr(red, "to_dict") else dict(red)
    if red.get("status") not in ("Nacrt", "Greška"):
        raise ValueError("Stavke se mogu dodavati samo u nacrt.")
    program = red.get("program_tip")
    redak_id = ""
    prijava = {}
    if program == "Matura" and sifra in MATURA_SIFRA_U_PREDMET:
        predmet, razina = MATURA_SIFRA_U_PREDMET[sifra]
        prijava = {"program_tip": "Matura", "predmet": predmet, "razina_ispita": razina,
                   "stupanj_skolovanja": "Srednja škola"}
    elif program == "Upisi" and sifra.startswith("UPISI-") and sifra != "UPISI-SIM":
        prijava = {"program_tip": "Upisi", "komponenta": sifra[len("UPISI-"):]}
    if prijava:
        redak_id = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))

    ws = sheet.worksheet(LEDGER_TAB)
    headers = ws.row_values(1)
    stavke = parsiraj_stavke(red.get("stavke_snapshot_json"))
    stavke.append({"sifra": sifra, "opis": opis, "kolicina": 1, "cijena_bazna": centi_u_tekst(centi),
                   "popust_postotak": float(popust or 0), "izvor": f"P:{redak_id}" if redak_id else ""})
    stavke = preracunaj_stavke(stavke)
    izvori = sifre_izvora(_cisto(red.get("izvorni_redci")))
    if redak_id:
        izvori.append(f"P:{redak_id}")
    # PRVO nacrt (izvorni_redci), PA prijava — tako je Assembler nikad ne vidi kao "slobodnu"
    _azuriraj_polja(ws, int(red["_row"]), {
        "stavke_snapshot_json": json.dumps(stavke, ensure_ascii=False),
        "iznos_ukupno": zbroj_stavki_centi(stavke) / 100,
        "izvorni_redci": ",".join(izvori),
    }, headers)
    if redak_id:
        wp = sheet.worksheet("Prijave")
        sada = sada_zagreb().strftime("%Y-%m-%d %H:%M:%S")
        _dodaj_red_po_nazivu(wp, {
            "redak_id": redak_id, "ucenik_id": _cisto(red.get("ucenik_id")), "ime_djeteta": _cisto(red.get("ime_djeteta")),
            "status_kontakta": "Potvrdio", "rani_ispit": "Ne", "timestamp_prijave": sada, "posalji_nakon": sada,
            "sezona": SEZONA, "solo_racun": _cisto(red.get("solo_racun")),
            "napomena": f"➕ dodano izravno u nacrt {red.get('dokument_id')}", **prijava,
        })
    return redak_id


def uklonjeni_izvori(red: dict, nove_stavke: list) -> list:
    """B) Prijave (redak_id) koje su bile u nacrtu, a admin je njihovu stavku obrisao u tablici."""
    red = red.to_dict() if hasattr(red, "to_dict") else dict(red)
    u_nacrtu = [s_[2:] for s_ in sifre_izvora(_cisto(red.get("izvorni_redci"))) if s_.startswith("P:")]
    ostale = {str(s_.get("izvor", ""))[2:] for s_ in nove_stavke if str(s_.get("izvor", "")).startswith("P:")}
    # Samo ako je stavka TOG izvora i prije postojala u nacrtu (stari nacrti nemaju izvor po stavci)
    prije = {str(s_.get("izvor", ""))[2:] for s_ in parsiraj_stavke(red.get("stavke_snapshot_json"))
             if str(s_.get("izvor", "")).startswith("P:")}
    return [r for r in u_nacrtu if r in prije and r not in ostale]


def otkazi_uklonjene_prijave(sheet, redak_ids: list, dokument_id: str) -> int:
    """B) Prijava čiju je stavku admin uklonio iz nacrta → Otkazano (ostaje vezana uz nacrt, pa se ne vraća sama)."""
    if not redak_ids:
        return 0
    wp = sheet.worksheet("Prijave")
    hp = wp.row_values(1)
    n = 0
    for i, r in enumerate(wp.get_all_records(), start=2):
        if str(r.get("redak_id")) in redak_ids and r.get("status_kontakta") not in ("Otkazano", "Odustao"):
            polja = {"status_kontakta": "Otkazano"}
            if "napomena" in hp:
                stara = str(r.get("napomena", "") or "")
                polja["napomena"] = (stara + " | " if stara else "") + f"uklonjeno iz nacrta {dokument_id}"
            _azuriraj_polja(wp, i, polja, hp)
            n += 1
    return n


# ============================================================
# PREDMETI NA KARTICI UČENIKA — "jedna kartica, jedan klik" (2.10.2026.)
# ============================================================
# Stranice Prijave i Učenici su spojene: predmeti se potvrđuju/otkazuju na kartici učenika i
# odabrani se JEDNIM upisom šalju u 💶 Financije (Apps Script sastaviNacrte od toga napravi
# JEDAN nacrt po subjektu). Svaki zapis prvo svježe pročita Sheet — dvostruki klik ne može
# poslati isti predmet dvaput, a predmet koji je već u Financijama više se ne može mijenjati ovdje.
# Kemija / biologija (i medicinske) za Maturu predaju i naplaćuju vanjski profesori:
# bez Solo ponude (0 €), ne smetaju na kartici, a admin im šalje popis učenika.

VANJSKI_PREDMETI = {
    "kemija": "Ivica", "kemija_medicina": "Ivica",
    "biologija": "Mirela", "biologija_medicina": "Mirela",
}
VANJSKI_PROFESORI = ["Ivica", "Mirela"]
STATUSI_PREDMETA = ["Čeka poziv", "Čeka", "Potvrdio", "Otkazano"]
OZNAKE_STATUSA_PREDMETA = {"Čeka poziv": "📞 Čeka poziv", "Čeka": "⏳ Čeka", "Potvrdio": "✅ Potvrdio",
                           "Otkazano": "❌ Otkazao"}
STATUSI_NEAKTIVNI = ["Otkazano", "Odustao"]
_DOK_U_FINANCIJAMA = ["Nacrt", "Odobreno", "Šalje se…", "Greška"]
_DOK_POSLAN = ["Poslano", "Isteklo"]
_DOK_UGASEN = ["Za brisanje", "Obrisano", "Brisanje nije uspjelo", "Otkazano"]


def vanjski_profesor(red) -> str:
    """'Ivica' / 'Mirela' za Matura kemiju/biologiju (i medicinske), inače ''."""
    if str(red.get("program_tip", "") or "").strip() != "Matura":
        return ""
    return VANJSKI_PREDMETI.get(str(red.get("predmet", "") or "").strip(), "")


def je_ceka_poziv(red) -> bool:
    """Redak koji stvarno čeka poziv (vanjski predmeti se ne broje — njih ne zovemo radi ponude)."""
    return str(red.get("status_kontakta", "")).strip() == "Čeka poziv" and not vanjski_profesor(red)


def dokumenti_po_retku(df_racuni: pd.DataFrame) -> dict:
    """redak_id Prijave → najnoviji dokument koji ga sadrži: {status, broj_dokumenta, dokument_id}."""
    out = {}
    if df_racuni is None or df_racuni.empty or "izvorni_redci" not in df_racuni.columns:
        return out
    df = df_racuni
    if "datum_kreiranja" in df.columns:
        df = df.assign(_d=df["datum_kreiranja"].astype(str)).sort_values("_d", kind="stable")
    for _, r in df.iterrows():
        for s in str(r.get("izvorni_redci", "") or "").split(","):
            s = s.strip()
            if s.startswith("P:") and len(s) > 2:
                out[s[2:]] = {"status": str(r.get("status", "") or ""), "dokument_id": str(r.get("dokument_id", "")),
                              "broj_dokumenta": str(r.get("broj_dokumenta", "") or "").replace("nan", "")}
    return out


def stanje_predmeta(red, dok_po_retku: dict) -> dict:
    """Oznaka i smije li se predmet još mijenjati na kartici.
    kod: neaktivan / vanjski / financije / greska / poslano / placeno / ugasen / gotovina / ide / uredi"""
    status = str(red.get("status_kontakta", "") or "").strip()
    rid = str(red.get("redak_id", "") or "").strip()
    if status in STATUSI_NEAKTIVNI:
        return {"kod": "neaktivan", "oznaka": f"🗄️ {status}", "uredivo": False}
    prof = vanjski_profesor(red)
    if prof:
        return {"kod": "vanjski", "oznaka": f"🧪 {prof} — bez ponude (0 €)", "uredivo": False}
    if str(red.get("program_tip", "") or "").strip() == "Instrukcije" and status not in ("Čeka poziv", "Čeka"):
        # 2.10.2026.: instrukcije nemaju ponudu iz prijave — naplata ide po održanim terminima (📝 Instrukcije)
        return {"kod": "instrukcije", "oznaka": "📝 Instrukcije — naplata po održanim terminima", "uredivo": False}
    dok = dok_po_retku.get(rid) if rid else None
    if dok:
        s, broj = dok["status"], dok["broj_dokumenta"]
        if s == "Greška":
            return {"kod": "greska", "oznaka": "⚠️ Greška slanja — vidi 💶 Financije", "uredivo": False}
        if s in _DOK_U_FINANCIJAMA:
            return {"kod": "financije", "oznaka": "🟡 Nacrt u 💶 Financijama", "uredivo": False}
        if s in _DOK_POSLAN:
            return {"kod": "poslano", "oznaka": "📤 Ponuda poslana" + (f" ({broj})" if broj else "")
                    + (" — rok istekao" if s == "Isteklo" else ""), "uredivo": False}
        if s == "Plaćeno":
            return {"kod": "placeno", "oznaka": "✅ Plaćeno" + (f" ({broj})" if broj else ""), "uredivo": False}
        if s in _DOK_UGASEN:
            return {"kod": "ugasen", "oznaka": f"🗑️ Ponuda {s.lower()} — novu napravi u 💶 Financije (✏️ Ispravi)",
                    "uredivo": False}
    if str(red.get("solo_poslano", "") or "").strip():
        gotovina = "gotovin" in str(red.get("napomena", "") or "").lower()
        return {"kod": "gotovina", "oznaka": "💵 Plaćeno gotovinom" if gotovina else "📤 Ponuda poslana (stari tok)",
                "uredivo": False}
    if status == "Potvrdio" and str(red.get("posalji_nakon", "") or "").strip():
        return {"kod": "ide", "oznaka": "🕓 Ide u 💶 Financije (nacrt za ≤ 5 min)", "uredivo": False}
    if status == "Potvrdio":
        return {"kod": "uredi", "oznaka": "✅ Potvrdio — spremno za ponudu", "uredivo": True}
    return {"kod": "uredi", "oznaka": OZNAKE_STATUSA_PREDMETA.get(status, status or "—"), "uredivo": True}


def _svjeze_prijave(sheet):
    """(ws, headers, {redak_id: (broj_retka, dict)}) — svježe iz Sheeta, jednim čitanjem."""
    ws = sheet.worksheet("Prijave")
    vrijednosti = ws.get_all_values()
    h = [str(x).strip() for x in (vrijednosti[0] if vrijednosti else [])]
    retci = {}
    for i, r in enumerate(vrijednosti[1:], start=2):
        r = list(r) + [""] * (len(h) - len(r))
        d = dict(zip(h, r))
        rid = str(d.get("redak_id", "")).strip()
        if rid:
            retci[rid] = (i, d)
    return ws, h, retci


def _upisi_prijave(ws, h, izmjene: dict):
    """izmjene = {broj_retka: {stupac: vrijednost}} → JEDAN batch poziv prema Googleu."""
    data = []
    for broj, polja in izmjene.items():
        for naziv, v in polja.items():
            if naziv not in h:
                raise ValueError(f"Stupac '{naziv}' ne postoji u tabu Prijave")
            data.append({"range": gspread.utils.rowcol_to_a1(broj, h.index(naziv) + 1), "values": [[v]]})
    if data:
        ws.batch_update(data, raw=True)


def spremi_statuse_predmeta(sheet, statusi: dict, subjekt: str = "") -> int:
    """statusi = {redak_id: 'Čeka poziv'|'Čeka'|'Potvrdio'|'Otkazano'}. Mijenja samo predmete koji su
    još uredivi (nisu u Financijama, poslani, vanjski...). 'Potvrdio' ovdje NE šalje u Financije.
    Ako je zadan subjekt, upiše ga potvrđenima (za kasnije 📤 Pošalji sve). Vraća broj izmijenjenih."""
    if subjekt and subjekt not in SOLO_SUBJEKTI:
        raise ValueError("Nepoznat pravni subjekt.")
    ws, h, retci = _svjeze_prijave(sheet)
    dok = dokumenti_po_retku(load_racuni(sheet))
    izmjene = {}
    for rid, novi in statusi.items():
        if novi not in STATUSI_PREDMETA or rid not in retci:
            continue
        broj, red = retci[rid]
        if not stanje_predmeta(red, dok)["uredivo"]:
            continue
        polja = {}
        if red.get("status_kontakta", "") != novi:
            polja["status_kontakta"] = novi
        if subjekt and novi == "Potvrdio" and "solo_racun" in h and red.get("solo_racun", "") != subjekt:
            polja["solo_racun"] = subjekt
        if polja:
            izmjene[broj] = polja
    _upisi_prijave(ws, h, izmjene)
    return len(izmjene)


def posalji_predmete_u_financije(sheet, redak_ids: list, subjekt: str) -> int:
    """📤 Odabrani predmeti → status Potvrdio + solo_racun + posalji_nakon = sada, JEDNIM upisom.
    Apps Script (svakih 5 min) od svih predmeta istog učenika i subjekta napravi JEDAN nacrt."""
    if subjekt not in SOLO_SUBJEKTI:
        raise ValueError("Odaberi pravni subjekt (Solo račun) za ovu ponudu.")
    if not redak_ids:
        raise ValueError("Nijedan predmet nije označen za slanje.")
    ws, h, retci = _svjeze_prijave(sheet)
    dok = dokumenti_po_retku(load_racuni(sheet))
    sada = sada_zagreb().strftime("%Y-%m-%d %H:%M:%S")
    izmjene, preskoceno = {}, []
    for rid in redak_ids:
        if rid not in retci:
            preskoceno.append(rid)
            continue
        broj, red = retci[rid]
        if not stanje_predmeta(red, dok)["uredivo"] or red.get("status_kontakta") == "Otkazano":
            preskoceno.append(rid)
            continue
        if str(red.get("program_tip", "") or "").strip() == "Instrukcije":
            izmjene[broj] = {"status_kontakta": "Potvrdio"}   # 2.10.2026.: samo potvrda, bez nacrta ponude
            continue
        izmjene[broj] = {"status_kontakta": "Potvrdio", "solo_racun": subjekt, "posalji_nakon": sada}
    if not izmjene:
        raise ValueError("Odabrani predmeti su već poslani u Financije (ili otkazani) — osvježi stranicu.")
    _upisi_prijave(ws, h, izmjene)
    return len(izmjene)


def oznaci_predmete_gotovinom(sheet, redak_ids: list) -> int:
    """💵 Odabrani predmeti plaćeni gotovinom: solo_poslano='Da' (ne ide u ponudu) + zabilješka, jednim upisom."""
    ws, h, retci = _svjeze_prijave(sheet)
    dok = dokumenti_po_retku(load_racuni(sheet))
    oznaka = f"💵 Plaćeno gotovinom (ručno, {sada_zagreb().strftime('%d.%m.%Y.')})"
    izmjene = {}
    for rid in redak_ids:
        if rid in retci and stanje_predmeta(retci[rid][1], dok)["uredivo"]:
            broj, red = retci[rid]
            stara = str(red.get("napomena", "") or "")
            izmjene[broj] = {"solo_poslano": "Da", "napomena": f"{stara} | {oznaka}" if stara else oznaka}
    _upisi_prijave(ws, h, izmjene)
    return len(izmjene)


def kandidati_za_slanje(df_prijave: pd.DataFrame, df_racuni: pd.DataFrame) -> tuple:
    """Za 📤 Pošalji sve: (potvrđeni predmeti spremni za ponudu S odabranim subjektom, broj potvrđenih BEZ subjekta)."""
    if df_prijave is None or df_prijave.empty:
        return pd.DataFrame(), 0
    dok = dokumenti_po_retku(df_racuni)
    maska = df_prijave.apply(lambda r: str(r.get("status_kontakta", "")) == "Potvrdio"
                             and stanje_predmeta(r, dok)["kod"] == "uredi", axis=1)
    spremni = df_prijave[maska]
    if spremni.empty:
        return spremni, 0
    sa_subjektom = spremni["solo_racun"].astype(str).isin(SOLO_SUBJEKTI) if "solo_racun" in spremni.columns \
        else pd.Series(False, index=spremni.index)
    return spremni[sa_subjektom], int((~sa_subjektom).sum())


def posalji_sve_u_financije(sheet) -> tuple:
    """📤 Pošalji sve: svi potvrđeni predmeti s odabranim subjektom idu u Financije jednim upisom.
    Svježe čita Sheet. Vraća (broj učenika, broj predmeta)."""
    df_p = load_prijave(sheet)
    spremni, _ = kandidati_za_slanje(df_p, load_racuni(sheet))
    if spremni.empty:
        return 0, 0
    ws, h, retci = _svjeze_prijave(sheet)
    sada = sada_zagreb().strftime("%Y-%m-%d %H:%M:%S")
    izmjene = {retci[str(r)][0]: {"posalji_nakon": sada} for r in spremni["redak_id"] if str(r) in retci}
    _upisi_prijave(ws, h, izmjene)
    return int(spremni["ucenik_id"].nunique()), len(izmjene)


def popis_za_vanjskog(df_prijave: pd.DataFrame, df_ucenici: pd.DataFrame, profesor: str,
                      samo_novi: bool = True) -> pd.DataFrame:
    """🧪 Popis učenika za Ivicu / Mirelu (oni sami izdaju račune). Bez otkazanih."""
    stupci = ["redak_id", "Ime djeteta", "Šifra", "Predmet", "Način praćenja", "Roditelj", "Mobitel roditelja",
              "Email roditelja", "Email djeteta", "Mobitel djeteta", "Prijava", "Poslano profesoru"]
    if df_prijave is None or df_prijave.empty:
        return pd.DataFrame(columns=stupci)
    p = df_prijave[df_prijave.apply(lambda r: vanjski_profesor(r) == profesor
                                    and str(r.get("status_kontakta", "")) not in STATUSI_NEAKTIVNI, axis=1)]
    if samo_novi and "vanjski_poslano" in p.columns:
        p = p[p["vanjski_poslano"].astype(str).str.strip().replace("nan", "") == ""]
    if p.empty:
        return pd.DataFrame(columns=stupci)
    uc = {str(r["ucenik_id"]): r for _, r in df_ucenici.iterrows()} if df_ucenici is not None and not df_ucenici.empty else {}
    retci = []
    for _, r in p.iterrows():
        u = uc.get(str(r["ucenik_id"]), {})
        g = lambda k: str(u.get(k, "") or "") if len(u) else ""  # noqa: E731
        retci.append({
            "redak_id": r.get("redak_id", ""), "Ime djeteta": g("ime_djeteta") or r.get("ime_djeteta", ""),
            "Šifra": r["ucenik_id"], "Predmet": PREDMETI_MATURA.get(r.get("predmet", ""), r.get("predmet", "")),
            "Način praćenja": r.get("nacin_pracenja", ""), "Roditelj": g("ime_roditelja"),
            "Mobitel roditelja": g("mobitel_roditelja"), "Email roditelja": g("email_roditelja"),
            "Email djeteta": g("email_djeteta"), "Mobitel djeteta": g("mobitel_djeteta"),
            "Prijava": str(r.get("timestamp_prijave", ""))[:10],
            "Poslano profesoru": str(r.get("vanjski_poslano", "") or "").replace("nan", ""),
        })
    return pd.DataFrame(retci, columns=stupci).sort_values("Ime djeteta", key=lambda s: s.str.lower()).reset_index(drop=True)


def tekst_popisa_za_vanjskog(df: pd.DataFrame, profesor: str) -> str:
    """Tekst za kopiranje u mail / WhatsApp profesoru."""
    if df is None or df.empty:
        return ""
    redovi = [f"Pozdrav {profesor}, popis učenika prijavljenih na CAKI Maturu ({len(df)}):", ""]
    for i, r in enumerate(df.itertuples(index=False), start=1):
        d = dict(zip(df.columns, list(r)))
        kontakt = ", ".join(x for x in [d["Roditelj"], d["Mobitel roditelja"], d["Email roditelja"]] if x)
        redovi.append(f"{i}. {d['Ime djeteta']} — {d['Predmet']}"
                      + (f" ({d['Način praćenja']})" if d["Način praćenja"] else "")
                      + (f" — roditelj: {kontakt}" if kontakt else ""))
    return "\n".join(redovi)


def oznaci_vanjske_poslane(sheet, redak_ids: list) -> int:
    """Upiše datum slanja popisa profesoru (stupac vanjski_poslano; doda ga ako ne postoji)."""
    ws, h, retci = _svjeze_prijave(sheet)
    if "vanjski_poslano" not in h:
        if ws.col_count < len(h) + 1:
            ws.add_cols(1)
        ws.update_cell(1, len(h) + 1, "vanjski_poslano")
        h = h + ["vanjski_poslano"]
    danas = sada_zagreb().strftime("%Y-%m-%d")
    izmjene = {retci[r][0]: {"vanjski_poslano": danas} for r in redak_ids if r in retci}
    _upisi_prijave(ws, h, izmjene)
    return len(izmjene)


# ============================================================
# 2.10.2026. (b) — PDV: procjena s poslanim ponudama · oznaka ponude po učeniku · WhatsApp predlošci
# ============================================================

def _godina_roka(v):
    """Godina iz rok_placanja (tekst 'YYYY-MM-DD', 'd.M.yyyy.' ili Sheets serijski broj) ili None."""
    t = prikazi_datum(v).strip()
    m = re.search(r"(20\d{2})", t)
    return int(m.group(1)) if m else None


def ponude_za_pdv(df_racuni: pd.DataFrame, godina: int) -> dict:
    """Po subjektu: poslane a neplaćene ponude (Poslano/Isteklo) koje će — kad se plate — postati računi.
    {subjekt: {"ove_godine": c, "kasnije": c, "nacrti": c, "broj": n}}. Rok u sljedećoj godini → 'kasnije'
    (ne ulazi u limit ove godine). Plaćene se ne broje (račun je već u Solu, tj. u 'Izdano')."""
    out = {}
    if df_racuni is None or df_racuni.empty or "status" not in df_racuni.columns:
        return out
    for _, r in df_racuni.iterrows():
        s = str(r.get("solo_racun", "") or "").strip()
        st_ = str(r.get("status", ""))
        if not s or (st_ not in ("Poslano", "Isteklo", "Nacrt", "Odobreno", "Šalje se…")):
            continue
        if str(r.get("tip_dokumenta", "Ponuda") or "Ponuda") not in ("Ponuda", "nan"):
            continue
        c = u_cente(r.get("iznos_ukupno")) or 0
        d = out.setdefault(s, {"ove_godine": 0, "kasnije": 0, "nacrti": 0, "broj": 0})
        if st_ in ("Poslano", "Isteklo"):
            g = _godina_roka(r.get("rok_placanja", ""))
            if g is not None and g > godina:
                d["kasnije"] += c
            else:
                d["ove_godine"] += c
            d["broj"] += 1
        else:
            d["nacrti"] += c
    return out


OZNAKE_PONUDE_UCENIKA = {"placeno": "✅", "poslano": "📤", "nacrt": "🟡"}


def ponude_po_uceniku(df_racuni: pd.DataFrame) -> dict:
    """ucenik_id → 'poslano' (ima poslanu neplaćenu ponudu) / 'placeno' (sve plaćeno) / 'nacrt' (samo u
    pripremi). Obrisane/otkazane ponude se ne broje. Učenik bez ponude nije u rječniku."""
    out = {}
    if df_racuni is None or df_racuni.empty or "status" not in df_racuni.columns:
        return out
    for uid, g in df_racuni.groupby(df_racuni["ucenik_id"].astype(str)):
        s = set(g["status"].astype(str)) - set(_DOK_UGASEN)
        if s & set(_DOK_POSLAN):
            out[uid] = "poslano"
        elif s and s <= {"Plaćeno"}:
            out[uid] = "placeno"
        elif s & {"Plaćeno"}:
            out[uid] = "placeno" if not (s & set(_DOK_U_FINANCIJAMA)) else "nacrt"
        elif s & set(_DOK_U_FINANCIJAMA):
            out[uid] = "nacrt"
    return out


# --- 📲 WhatsApp predlošci (tab WhatsApp_predlosci; uređuju se u ⚙️ Postavke) ---
WA_PREDLOSCI_TAB = "WhatsApp_predlosci"
WA_PREDLOSCI_HEADERS = ["kljuc", "naziv", "program", "tijelo"]
WA_PROGRAMI = ["Svi", "Upisi", "Matura", "Instrukcije"]
WA_LINK_OZNAKA = "[OVDJE ZALIJEPI LINK"
WA_POCETNI = [
    {"kljuc": "pridruzivanje_grupi", "naziv": "Pridruživanje WhatsApp grupi za nastavu", "program": "Svi",
     "tijelo": "Poštovani/a {ime_roditelja},\n\n{ime_djeteta} je upisan/a u CAKI {program} {skolska_godina}. "
               "Molimo da se pridružite WhatsApp grupi za nastavu — tamo objavljujemo raspored, obavijesti i "
               "promjene termina:\n[OVDJE ZALIJEPI LINK GRUPE]\n\n{moj_caki}\n\nLijep pozdrav,\nCAKI centar"},
    {"kljuc": "pridruzivanje_zajednici", "naziv": "Pridruživanje CAKI WhatsApp zajednici", "program": "Svi",
     "tijelo": "Poštovani/a {ime_roditelja},\n\nPozivamo vas u CAKI WhatsApp zajednicu — sve važne obavijesti "
               "na jednom mjestu:\n[OVDJE ZALIJEPI LINK ZAJEDNICE]\n\nLijep pozdrav,\nCAKI centar"},
]


def load_whatsapp_predlosci(sheet) -> pd.DataFrame:
    try:
        df = _load_worksheet_df(sheet.worksheet(WA_PREDLOSCI_TAB))
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame(columns=WA_PREDLOSCI_HEADERS + ["_row"])
    for h in WA_PREDLOSCI_HEADERS:
        if h not in df.columns:
            df[h] = ""
        df[h] = df[h].astype(str).replace("nan", "")
    return df


def _ws_whatsapp(sheet):
    try:
        return sheet.worksheet(WA_PREDLOSCI_TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=WA_PREDLOSCI_TAB, rows=100, cols=len(WA_PREDLOSCI_HEADERS))
        ws.append_row(WA_PREDLOSCI_HEADERS)
        return ws


def osiguraj_whatsapp_predloske(sheet) -> list:
    """Kreira tab (ako ga nema) i doda POČETNE predloške koji nedostaju. Postojeći tekstovi se ne diraju."""
    ws = _ws_whatsapp(sheet)
    headers = ws.row_values(1)
    postojeci = {str(r.get("kljuc", "")) for r in ws.get_all_records()}
    dodani = []
    for p in WA_POCETNI:
        if p["kljuc"] not in postojeci:
            _dodaj_red_po_nazivu(ws, p, headers)
            dodani.append(p["kljuc"])
    return dodani


def spremi_whatsapp_predlozak(sheet, kljuc: str, naziv: str, program: str, tijelo: str) -> str:
    """Upis ili izmjena po ključu → 'novi' / 'izmijenjen'."""
    kljuc = re.sub(r"[^a-z0-9_]", "_", str(kljuc or "").strip().lower()).strip("_")
    if not kljuc:
        raise ValueError("Ključ predloška ne smije biti prazan.")
    if program not in WA_PROGRAMI:
        raise ValueError(f"Nepoznat program '{program}'.")
    if not str(tijelo or "").strip():
        raise ValueError("Tekst poruke ne smije biti prazan.")
    ws = _ws_whatsapp(sheet)
    headers = ws.row_values(1)
    polja = {"kljuc": kljuc, "naziv": str(naziv or kljuc).strip(), "program": program, "tijelo": str(tijelo)}
    for i, r in enumerate(ws.get_all_records(), start=2):
        if r.get("kljuc") == kljuc:
            _azuriraj_polja(ws, i, polja, headers)
            return "izmijenjen"
    _dodaj_red_po_nazivu(ws, polja, headers)
    return "novi"


def whatsapp_predlosci_za(df: pd.DataFrame, program: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=WA_PREDLOSCI_HEADERS)
    return df[df["program"].isin([program, "Svi", ""])]


def popuni_whatsapp(tijelo: str, ucenik: dict, program: str, portal_url: str) -> str:
    """Tekst WhatsApp poruke: iste oznake kao u mailu ({ime_roditelja}, {ime_djeteta}, {sifra}, {moj_caki},
    {program}, {program_veliko}, {skolska_godina})."""
    uid = str(ucenik.get("ucenik_id", ""))
    ime = str(ucenik.get("ime_djeteta", "") or "")
    zamjene = {"ime_roditelja": str(ucenik.get("ime_roditelja", "") or ""), "ime_djeteta": ime, "sifra": uid,
               "moj_caki": tekst_moj_caki(ime, uid, portal_url), "program": program,
               "program_veliko": str(program).upper(), "skolska_godina": skolska_godina()}
    return popuni_mail_pregled(str(tijelo or ""), zamjene).strip()


def provjeri_whatsapp(tekst: str) -> list:
    """Upozorenja prije slanja: nepopunjene oznake ili link koji nije zalijepljen u predložak."""
    upoz = []
    ostaci = sorted(set(re.findall(r"\{[a-z_]+\}", str(tekst or ""))))
    if ostaci:
        upoz.append("Nepopunjene oznake: " + ", ".join(ostaci))
    if WA_LINK_OZNAKA in str(tekst or ""):
        upoz.append("U poruci je još „[OVDJE ZALIJEPI LINK …]” — zalijepi pravi link (najbolje trajno u "
                    "⚙️ Postavke → 📲 WhatsApp predlošci).")
    return upoz


# ============================================================
# 💬 PORUKA IZ PRIJAVNICE ("Vaše pitanje ili poruka za nas.") — 2.10.2026.
# ============================================================
# Matura: onFormSubmit upisuje poruku u Prijave.napomena kao "💬 …" (od 2.10.; stare dopunjava
# ▶ dopuniPorukeIzForme). Upisi: poruka je u tabu "Form responses 1" (Upisi forma piše u CRM Sheet)
# → povezuje se s učenikom po imenu djeteta (+ email roditelja ako ima više istih imena).
FORM_UPISI_TAB = "Form responses 1"
PORUKA_ZNAK = "💬"


def _norm(t) -> str:
    return re.sub(r"\s+", " ", str(t or "")).strip().lower()


def load_form_upisi(sheet) -> pd.DataFrame:
    """Odgovori Upisi forme iz CRM Sheeta (samo čitanje). Prazno ako taba nema."""
    try:
        v = sheet.worksheet(FORM_UPISI_TAB).get_all_values()
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame()
    if not v:
        return pd.DataFrame()
    h = [str(x).strip() for x in v[0]]
    return pd.DataFrame([list(r) + [""] * (len(h) - len(r)) for r in v[1:]], columns=h)


def _stupac_koji_sadrzi(df: pd.DataFrame, *dijelovi) -> str:
    for c in df.columns:
        if all(d in _norm(c) for d in dijelovi):
            return c
    return ""


def poruke_ucenika(df_prijave: pd.DataFrame, df_form: pd.DataFrame, df_ucenici: pd.DataFrame) -> dict:
    """ucenik_id → popis poruka iz prijavnice (bez duplikata, redom kako su stigle)."""
    out = {}

    def dodaj(uid, tekst):
        tekst = str(tekst or "").strip()
        if uid and tekst and tekst not in out.setdefault(uid, []):
            out[uid].append(tekst)

    if df_prijave is not None and not df_prijave.empty and "napomena" in df_prijave.columns:
        for _, r in df_prijave.iterrows():
            for dio in str(r.get("napomena", "") or "").split(" | "):
                dio = dio.strip()
                if dio.startswith(PORUKA_ZNAK):
                    dodaj(str(r["ucenik_id"]), dio[len(PORUKA_ZNAK):].strip())
    if df_form is None or df_form.empty or df_ucenici is None or df_ucenici.empty:
        return out
    c_por = _stupac_koji_sadrzi(df_form, "pitanje ili poruka")
    c_ime = _stupac_koji_sadrzi(df_form, "ime i prezime djeteta")
    c_mail = _stupac_koji_sadrzi(df_form, "e-mail", "roditelja")
    if not c_por or not c_ime:
        return out
    po_imenu = {}
    for _, u in df_ucenici.iterrows():
        po_imenu.setdefault(_norm(u.get("ime_djeteta", "")), []).append(u)
    for _, f in df_form.iterrows():
        poruka = str(f.get(c_por, "") or "").strip()
        if not poruka:
            continue
        kandidati = po_imenu.get(_norm(f.get(c_ime, "")), [])
        if len(kandidati) > 1 and c_mail:
            mail = _norm(f.get(c_mail, ""))
            uz_mail = [u for u in kandidati if _norm(u.get("email_roditelja", "")) == mail]
            kandidati = uz_mail or kandidati
        if len(kandidati) == 1:
            dodaj(str(kandidati[0]["ucenik_id"]), poruka)
    return out


# ============================================================
# ZAUZETOST UČIONICA — Matura + Upisi zajedno (2.10.2026.)
# Ista prostorija ima dva naziva: u Rasporedu Mature A/B/C, u Grupama (Upisi) "Učionica 1/2/3".
# Odluka 2.10.2026.: A = Učionica 1 (6), B = Učionica 2 (6), C = Učionica 3 (12); drugih prostorija nema.
# Dvije grupe ne smiju biti u istoj učionici u isto vrijeme ako im se RAZDOBLJA (datum_od–datum_do)
# preklapaju — tako se u lipnju može unaprijed složiti Upisi kratki u učionici gdje su do tada Upisi dugi.
# Online grupe ne zauzimaju učionicu. Sve funkcije su čiste (bez Streamlita) radi testiranja.
# ============================================================
UCIONICE_CENTRA = [("A", "Učionica 1", 6), ("B", "Učionica 2", 6), ("C", "Učionica 3", 12)]
UCIONICE_UPISI_OPCIJE = ["Učionica 1 (6)", "Učionica 2 (6)", "Učionica 3 (12)", "Online"]
GRUPA_ARHIVA = "arhiva"            # Grupe.aktivna = "arhiva": skrivena svima, ne zauzima učionicu
STUPCI_RAZDOBLJA_GRUPE = ["datum_od", "datum_do"]
RAZDOBLJA_TAB = "Razdoblja_programa"
STUPCI_RAZDOBLJA = ["program", "datum_od", "datum_do", "zadnje_azurirano"]
TRAJANJE_BEZ_KRAJA_MIN = 90        # "17:00" bez završetka → pretpostavi 90 min


def oznaka_ucionice(tekst) -> str:
    """'Učionica 1 (6)' / 'A' / 'Uč. A' / 'U1' -> 'A'; 'Online' ili nepoznato -> ''."""
    t = str(tekst or "").strip().lower()
    if not t or "online" in t:
        return ""
    if t in ("a", "b", "c"):
        return t.upper()
    m = re.search(r"(?:u[čc]ionica|u[čc]\.?|^u)\s*([abc123])\b", t)
    if not m:
        return ""
    z = m.group(1)
    return {"1": "A", "2": "B", "3": "C"}.get(z, z.upper())


def kapacitet_ucionice_centra(oznaka: str) -> int:
    return {o: k for o, _n, k in UCIONICE_CENTRA}.get(oznaka, 0)


def naziv_ucionice_centra(oznaka: str) -> str:
    """'A' -> 'Učionica 1 / A (6)'."""
    for o, n, k in UCIONICE_CENTRA:
        if o == oznaka:
            return f"{n} / {o} ({k})"
    return oznaka or "Online"


def opcija_ucionice_upisi(oznaka: str) -> str:
    """'A' -> 'Učionica 1 (6)' (vrijednost koju pišemo u Grupe.ucionica); '' -> 'Online'."""
    for o, n, k in UCIONICE_CENTRA:
        if o == oznaka:
            return f"{n} ({k})"
    return "Online"


def vrijeme_u_minute(tekst):
    """'15:00-16:30' / '15.00 – 16.30' -> (900, 990); '17:00' -> (1020, 1110); neispravno -> None."""
    nadjeno = re.findall(r"(\d{1,2})[:.](\d{2})", str(tekst or ""))
    if not nadjeno:
        return None
    minute = [int(h) * 60 + int(m) for h, m in nadjeno if int(h) < 24 and int(m) < 60]
    if not minute:
        return None
    od = minute[0]
    do = minute[1] if len(minute) > 1 and minute[1] > od else od + TRAJANJE_BEZ_KRAJA_MIN
    return od, do


def je_ispravno_vrijeme(tekst) -> bool:
    """Za unos termina: traži se početak I kraj (npr. 15:00-16:30)."""
    return len(re.findall(r"(\d{1,2})[:.](\d{2})", str(tekst or ""))) >= 2 and vrijeme_u_minute(tekst) is not None


def lijepo_vrijeme(tekst) -> str:
    v = vrijeme_u_minute(tekst)
    if not v:
        return str(tekst or "").strip()
    return f"{v[0] // 60:02d}:{v[0] % 60:02d}–{v[1] // 60:02d}:{v[1] % 60:02d}"


def vremena_se_preklapaju(a, b) -> bool:
    return bool(a and b and a[0] < b[1] and b[0] < a[1])


def u_datum(v):
    """'2026-10-31' / '31.10.2026.' / date -> date; prazno/neispravno -> None (= bez ograničenja)."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    t = str(v or "").strip().rstrip(".")
    if not t:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d. %m. %Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    return None


def razdoblja_se_preklapaju(od1, do1, od2, do2) -> bool:
    """Prazan datum = otvoreno (od početka / do kraja sezone)."""
    od1, do1, od2, do2 = u_datum(od1), u_datum(do1), u_datum(od2), u_datum(do2)
    if do1 and od2 and do1 < od2:
        return False
    if do2 and od1 and do2 < od1:
        return False
    return True


def ponedjeljak_tjedna(d: date) -> date:
    return d - timedelta(days=d.weekday())


def blok_aktivan_u_tjednu(blok: dict, ponedjeljak: date) -> bool:
    return razdoblja_se_preklapaju(blok.get("datum_od"), blok.get("datum_do"), ponedjeljak, ponedjeljak + timedelta(days=6))


def blok_aktivan_na_datum(blok: dict, d: date) -> bool:
    return razdoblja_se_preklapaju(blok.get("datum_od"), blok.get("datum_do"), d, d)


def tekst_razdoblja(od, do) -> str:
    od, do = u_datum(od), u_datum(do)
    if not od and not do:
        return "cijela sezona"
    f = lambda x: x.strftime("%d.%m.%Y.")  # noqa: E731
    return f"{f(od) if od else '…'} – {f(do) if do else '…'}"


def ucitaj_razdoblja(sheet) -> dict:
    """{program: (datum_od, datum_do)} iz taba Razdoblja_programa (npr. 'MATURA'). Nema taba -> {}."""
    df = _load_opcionalno(sheet, RAZDOBLJA_TAB)
    out = {}
    if df is None or df.empty or "program" not in df.columns:
        return out
    for _, r in df.iterrows():
        p = str(r.get("program", "")).strip().upper()
        if p:
            out[p] = (u_datum(r.get("datum_od")), u_datum(r.get("datum_do")))
    return out


def spremi_razdoblje(sheet, program: str, datum_od, datum_do) -> None:
    """Upiše/ažurira jedan redak u Razdoblja_programa (tab se stvori ako ne postoji)."""
    try:
        ws = sheet.worksheet(RAZDOBLJA_TAB)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=RAZDOBLJA_TAB, rows=50, cols=len(STUPCI_RAZDOBLJA))
        ws.update(range_name="A1", values=[STUPCI_RAZDOBLJA], value_input_option="RAW")
    program = str(program).strip().upper()
    od, do = u_datum(datum_od), u_datum(datum_do)
    vrijednosti = [program, od.isoformat() if od else "", do.isoformat() if do else "",
                   sada_zagreb().strftime("%Y-%m-%d %H:%M:%S")]
    programi = [str(p).strip().upper() for p in ws.col_values(1)]
    if program in programi[1:]:
        red = programi.index(program) + 1
    else:
        red = max(len(programi), 1) + 1
    ws.update(range_name=f"A{red}", values=[vrijednosti], value_input_option="RAW")


def blokovi_zauzetosti(df_grupe, df_raspored_matura=None, razdoblja: dict | None = None) -> list:
    """Svi termini koji zauzimaju učionicu: grupe Upisa (osim arhiviranih i online) + kante Mature.
    [{izvor 'UPISI'/'MATURA', id, dan, vrijeme, minute (od, do), ucionica 'A'/'B'/'C', kapacitet,
      oznaka, profesor, datum_od, datum_do, broj_ucenika}]"""
    razdoblja = razdoblja or {}
    out = []
    if df_grupe is not None and not getattr(df_grupe, "empty", True):
        for _, g in df_grupe.iterrows():
            if str(g.get("aktivna", "")).strip().lower() == GRUPA_ARHIVA:
                continue
            uc = oznaka_ucionice(g.get("ucionica"))
            if not uc:
                continue
            out.append({"izvor": "UPISI", "id": str(g.get("grupa_id", "")), "dan": str(g.get("dan", "")).strip(),
                        "vrijeme": lijepo_vrijeme(g.get("vrijeme")), "minute": vrijeme_u_minute(g.get("vrijeme")),
                        "ucionica": uc, "kapacitet": kapacitet_ucionice_centra(uc),
                        "oznaka": str(g.get("program", "")).strip(),
                        "profesor": str(g.get("redovni_nastavnik", "") or "").strip(),
                        "datum_od": u_datum(g.get("datum_od")), "datum_do": u_datum(g.get("datum_do")),
                        "broj_ucenika": None})
    mat_od, mat_do = razdoblja.get("MATURA", (None, None))
    for k in matura_kante(df_raspored_matura):
        uc = oznaka_ucionice(k["ucionica"])
        if not uc:
            continue
        out.append({"izvor": "MATURA", "id": k["grupa_id"], "dan": k["dan"], "vrijeme": lijepo_vrijeme(k["vrijeme"]),
                    "minute": vrijeme_u_minute(k["vrijeme"]), "ucionica": uc, "kapacitet": kapacitet_ucionice_centra(uc),
                    "oznaka": " + ".join(k["predmeti"]) or "MATURA", "profesor": k["profesor"],
                    "datum_od": mat_od, "datum_do": mat_do, "broj_ucenika": len(k["ucenici"])})
    return out


def sukobi_bloka(blok: dict, blokovi: list) -> list:
    """Blokovi koji su u ISTOJ učionici, ISTI dan, vrijeme se preklapa i razdoblje se preklapa."""
    out = []
    for b in blokovi:
        if (b["izvor"], b["id"]) == (blok.get("izvor"), blok.get("id")):
            continue
        if b["dan"] != blok.get("dan") or b["ucionica"] != blok.get("ucionica"):
            continue
        if not vremena_se_preklapaju(b["minute"], blok.get("minute")):
            continue
        if not razdoblja_se_preklapaju(b["datum_od"], b["datum_do"], blok.get("datum_od"), blok.get("datum_do")):
            continue
        out.append(b)
    return out


def svi_sukobi(blokovi: list) -> list:
    """[(blok1, blok2), ...] — svaki par jednom."""
    out, vidjeno = [], set()
    for b in blokovi:
        for d in sukobi_bloka(b, blokovi):
            par = tuple(sorted([(b["izvor"], b["id"]), (d["izvor"], d["id"])]))
            if par not in vidjeno:
                vidjeno.add(par)
                out.append((b, d))
    return out


def opis_bloka(b: dict, javno: bool = False) -> str:
    """Admin: '15:00–16:30 MATURA BIO (6) · Mirela'. Javno (portal profesora): '15:00–16:30 ZAUZETO – MATURA'."""
    if javno:
        return f"{b['vrijeme']} ZAUZETO – {b['izvor']}"
    return (f"{b['vrijeme']} {b['izvor']} {b['oznaka']} ({b['kapacitet']})"
            + (f" · {b['profesor']}" if b["profesor"] else ""))


def tekst_sukoba(b: dict) -> str:
    return (f"{naziv_ucionice_centra(b['ucionica'])} je {b['dan'].lower()} {b['vrijeme']} zauzeta: "
            f"{b['izvor']} {b['oznaka']}" + (f" · {b['profesor']}" if b["profesor"] else "")
            + f" ({tekst_razdoblja(b['datum_od'], b['datum_do'])})")


def tjedna_mreza(blokovi: list, ponedjeljak: date | None = None) -> dict:
    """{ucionica: {dan: [blokovi po vremenu]}} za tjedan koji počinje 'ponedjeljak' (None = svi blokovi)."""
    mreza = {o: {d: [] for d in DANI_U_TJEDNU} for o, _n, _k in UCIONICE_CENTRA}
    for b in blokovi:
        if b["ucionica"] not in mreza or b["dan"] not in DANI_U_TJEDNU:
            continue
        if ponedjeljak and not blok_aktivan_u_tjednu(b, ponedjeljak):
            continue
        mreza[b["ucionica"]][b["dan"]].append(b)
    for po_danu in mreza.values():
        for lista in po_danu.values():
            lista.sort(key=lambda x: ((x["minute"] or (9999, 0))[0], x["izvor"]))
    return mreza


def html_tjedne_mreze(blokovi: list, ponedjeljak: date | None = None, javno: bool = False) -> str:
    """HTML tablica: stupci = dani (pon–ned), retci = učionice; sukobi crveno obrubljeni."""
    import html
    mreza = tjedna_mreza(blokovi, ponedjeljak)
    aktivni = [b for po in mreza.values() for lista in po.values() for b in lista]
    u_sukobu = {(b["izvor"], b["id"]) for par in svi_sukobi(aktivni) for b in par}
    boje = {"MATURA": "#dbeafe", "UPISI": "#dcfce7"}
    kratko = {"Ponedjeljak": "Pon", "Utorak": "Uto", "Srijeda": "Sri", "Četvrtak": "Čet", "Petak": "Pet",
              "Subota": "Sub", "Nedjelja": "Ned"}
    th = "padding:4px;border:1px solid #ccc;background:#f3f4f6;color:#111;font-size:0.8rem"
    redovi = ["<div style='overflow-x:auto'><table style='border-collapse:collapse;width:100%;table-layout:fixed'>",
              f"<tr><th style='{th};width:90px'>Učionica</th>"
              + "".join(f"<th style='{th}'>{kratko[d]}</th>" for d in DANI_U_TJEDNU) + "</tr>"]
    for o, n, k in UCIONICE_CENTRA:
        celije = []
        for d in DANI_U_TJEDNU:
            kartice = []
            for b in mreza[o][d]:
                sukob = (b["izvor"], b["id"]) in u_sukobu and not javno
                tekst = html.escape(opis_bloka(b, javno))
                kartice.append(f"<div style='background:{'#f3f4f6' if javno else boje[b['izvor']]};"
                               f"border:{'2px solid #dc2626' if sukob else '1px solid #bbb'};border-radius:4px;"
                               f"padding:2px 4px;margin:2px 0;font-size:0.72rem;line-height:1.25;color:#111'>"
                               f"{'⛔ ' if sukob else ''}{tekst}</div>")
            celije.append(f"<td style='vertical-align:top;border:1px solid #ccc;padding:2px'>{''.join(kartice)}</td>")
        redovi.append(f"<tr><td style='{th};font-weight:600'>{html.escape(n)}<br>{o} ({k})</td>{''.join(celije)}</tr>")
    redovi.append("</table></div>")
    return "".join(redovi)


def blok_iz_unosa_grupe(grupa_id, dan, vrijeme, ucionica, program="", profesor="", datum_od=None, datum_do=None) -> dict:
    """Blok za provjeru PRIJE spremanja nove/izmijenjene grupe Upisa."""
    uc = oznaka_ucionice(ucionica)
    return {"izvor": "UPISI", "id": str(grupa_id or "__nova__"), "dan": dan, "vrijeme": lijepo_vrijeme(vrijeme),
            "minute": vrijeme_u_minute(vrijeme), "ucionica": uc, "kapacitet": kapacitet_ucionice_centra(uc),
            "oznaka": program, "profesor": profesor, "datum_od": u_datum(datum_od), "datum_do": u_datum(datum_do),
            "broj_ucenika": None}


def provjeri_grupu_upisa(blok: dict, blokovi: list) -> list:
    """Popis tekstova sukoba ([] = smije se spremiti). Online grupa nikad nema sukob."""
    if not blok.get("ucionica"):
        return []
    return [tekst_sukoba(b) for b in sukobi_bloka(blok, blokovi)]


def osiguraj_stupce_grupa(sheet) -> list:
    """Doda stupce datum_od / datum_do u tab Grupe ako ih nema. Vraća zaglavlje."""
    ws = sheet.worksheet("Grupe")
    headers = ws.row_values(1)
    nedostaje = [s for s in STUPCI_RAZDOBLJA_GRUPE if s not in headers]
    if nedostaje:
        if ws.col_count < len(headers) + len(nedostaje):
            ws.add_cols(len(headers) + len(nedostaje) - ws.col_count)
        for i, s in enumerate(nedostaje):
            ws.update_cell(1, len(headers) + i + 1, s)
        headers = headers + nedostaje
    return headers


def _red_grupe(ws, grupa_id: str) -> int:
    """Broj retka grupe u tabu (čita se svježe — ne oslanja se na stari _row)."""
    ids = [str(v).strip() for v in ws.col_values(1)]
    if str(grupa_id) not in ids[1:]:
        raise ValueError(f"Grupa {grupa_id} nije pronađena u tabu Grupe (možda je već obrisana).")
    return ids.index(str(grupa_id)) + 1


def uredi_grupu(sheet, grupa_id: str, polja: dict) -> None:
    """Promjena dana/vremena/učionice/kapaciteta/profesora/razdoblja postojeće grupe (po grupa_id)."""
    headers = osiguraj_stupce_grupa(sheet)
    ws = sheet.worksheet("Grupe")
    red = _red_grupe(ws, grupa_id)
    polja = {k: (v.isoformat() if isinstance(v, date) else ("" if v is None else v)) for k, v in polja.items()}
    _azuriraj_polja(ws, red, polja, headers)


def brisanje_grupe_dozvoljeno(grupa_id: str, df_rezervacije, df_termini) -> tuple:
    """(True, '') ako grupa nema aktivnih rezervacija ni održanih (evidentiranih) termina;
    inače (False, razlog) — tada se grupa arhivira umjesto brisanja, da se ne izgubi povijest."""
    razlozi = []
    if df_rezervacije is not None and not df_rezervacije.empty and "grupa_id" in df_rezervacije.columns:
        r = df_rezervacije[(df_rezervacije["grupa_id"].astype(str) == str(grupa_id))
                           & (df_rezervacije["status"].astype(str) != "Otkazano")]
        if len(r):
            razlozi.append(f"{len(r)} učenika s rezervacijom (otkaži ih ili premjesti termin)")
    if df_termini is not None and not df_termini.empty and "grupa_id" in df_termini.columns:
        t = df_termini[df_termini["grupa_id"].astype(str) == str(grupa_id)]
        if len(t):
            razlozi.append(f"{len(t)} održanih termina s evidencijom dolazaka")
    return (not razlozi), "; ".join(razlozi)


def obrisi_grupu(sheet, grupa_id: str) -> None:
    ws = sheet.worksheet("Grupe")
    ws.delete_rows(_red_grupe(ws, grupa_id))
