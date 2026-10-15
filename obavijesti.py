"""
CAKI — obavijesti.py  (15.10.2026.)
Moj CAKI → prva kartica "📣 Obavijesti": poruke od Cakija, važni linkovi i komentari učenika/roditelja.

ISTA datoteka u caki-booking-termina (portal) i caki-upisi-crm (admin). Ne uvozi pipeline_upisi.py,
da se ne mora sinkronizirati s njim.

Tabovi u CRM Sheetu (stvaraju se sami kad admin prvi put nešto spremi):
  Obavijesti        poruke (obavijest_id, datum, naslov, tekst, za, vazno, vrijedi_do, aktivna, autor)
  Linkovi_portal    važni linkovi (link_id, naziv, url, opis, za, redoslijed, aktivan)
  Komentari_portal  komentari klijenata + Cakijev odgovor
                    (komentar_id, datum, ucenik_id, ime_djeteta, od, tekst, status, odgovor, odgovor_datum)

"Samo za mene" napomene NE idu ovamo nego u postojeći tab Biljeske — portal Biljeske nikad ne čita.

Stupac `za` (kome je poruka/link namijenjen), više oznaka odvojeno zarezom:
  SVI                  svi učenici
  MATURA, UPISI, INSTRUKCIJE      svi učenici tog programa
  UPISI:MAT-DUGI       učenici s tom komponentom Upisa (oznake iz KOMPONENTE u pipeline_upisi.py)
  MATURA:MAT-A         učenici tog predmeta Mature; MATURA:MAT pokriva MAT-A i MAT-B
  KS9530               jedan učenik (šifra)
PRAZNO `za` = ne vidi nitko (zaštita od slučajnog prikaza privatne poruke svima).
"""
from __future__ import annotations

import random
import re
import string
from datetime import date, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import gspread
import pandas as pd

ZAGREB = ZoneInfo("Europe/Zagreb")

OBAVIJESTI_TAB = "Obavijesti"
OBAVIJESTI_HEADERS = ["obavijest_id", "datum", "naslov", "tekst", "za", "vazno", "vrijedi_do", "aktivna", "autor"]
LINKOVI_TAB = "Linkovi_portal"
LINKOVI_HEADERS = ["link_id", "naziv", "url", "opis", "za", "redoslijed", "aktivan"]
KOMENTARI_TAB = "Komentari_portal"
KOMENTARI_HEADERS = ["komentar_id", "datum", "ucenik_id", "ime_djeteta", "od", "tekst", "status", "odgovor",
                     "odgovor_datum"]

SVI = "SVI"
PROGRAMI = ["MATURA", "UPISI", "INSTRUKCIJE"]
OD_OPCIJE = ["Roditelj", "Učenik"]
STATUS_NOVO = "Novo"
STATUS_PROCITANO = "Pročitano"

MAX_NASLOV = 120
MAX_TEKST = 2000
MAX_KOMENTAR = 1000
MAX_ODGOVOR = 1000
MAX_NAZIV_LINKA = 80
MAX_OPIS_LINKA = 200
MAX_KOMENTARA_NA_DAN = 5

# isto kao KRATICE_PREDMETA_MATURA u pipeline_upisi.py
_KRATICE_MATURA = {
    "hrvatski": "HRV", "matematika": "MAT", "engleski": "ENG", "fizika": "FIZ", "kemija": "KEM",
    "biologija": "BIO", "fizika_medicina": "FIZ-MED", "kemija_medicina": "KEM-MED", "biologija_medicina": "BIO-MED",
}
_OZNAKA_RE = re.compile(r"[A-Z0-9][A-Z0-9:-]{1,29}")


# ------------------------------------------------------------------ opći pomoćnici

def sada() -> datetime:
    return datetime.now(ZAGREB).replace(tzinfo=None)


def novi_id() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=10))


def ocisti_tekst(v, maks: int) -> str:
    """Normalizira prijelome redaka, miče nevidljive kontrolne znakove i skraćuje na `maks`."""
    t = str(v or "").replace("\r\n", "\n").replace("\r", "\n")
    t = "".join(ch for ch in t if ch == "\n" or ch >= " ")
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t[:maks]


def sigurni_url(url) -> str:
    """Vraća ispravan http(s) URL ili "" (javascript:, data:, razmaci, nepotpune adrese se odbacuju).
    Adresa bez http(s):// dobiva https:// (npr. chat.whatsapp.com/abc)."""
    u = str(url or "").strip()
    if not u or any(c.isspace() for c in u):
        return ""
    if "://" not in u:
        u = "https://" + u
    try:
        p = urlparse(u)
    except ValueError:
        return ""
    if p.scheme.lower() not in ("http", "https"):
        return ""
    if not re.fullmatch(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+(:\d{1,5})?", p.netloc):
        return ""
    return u


def u_datum(v):
    """'2026-10-31' / '31.10.2026.' / date -> date; prazno ili neispravno -> None."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    t = str(v if v is not None else "").strip().rstrip(".")
    if not t or t.lower() in ("nan", "none", "nat"):
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d. %m. %Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            pass
    return None


def prikaz_datuma(v) -> str:
    d = u_datum(v)
    return d.strftime("%d.%m.%Y.") if d else ""


def _da(v) -> bool:
    return str(v or "").strip().lower() in ("da", "true", "1", "yes")


# ------------------------------------------------------------------ kome je namijenjeno

def tokeni(za) -> list:
    return [t for t in re.split(r"[,;\s]+", str(za or "").upper()) if t]


def normaliziraj_za(za) -> str:
    """'svi' / 'matura, UPISI:MAT-DUGI' / 'KS9530' -> uredan zapis; baca ValueError za neispravno."""
    t = tokeni(za)
    if not t:
        raise ValueError("Odaberi kome je poruka namijenjena.")
    for x in t:
        if not _OZNAKA_RE.fullmatch(x):
            raise ValueError(f"Neispravna oznaka primatelja: {x}")
    return ", ".join(dict.fromkeys(t))


def oznake_ucenika(df_prijave, ucenik_id, matura_oznake=()) -> set:
    """Sve oznake koje opisuju učenika: programi (MATURA/UPISI/INSTRUKCIJE), komponente Upisa
    (UPISI:MAT-DUGI) i predmeti Mature (MATURA:MAT-A i MATURA:MAT). Odustali/otkazani se ne računaju.
    `matura_oznake` = predmeti iz rasporeda Mature (npr. ['MAT-A', 'KEM'])."""
    uid = str(ucenik_id or "").strip().upper()
    out = set()

    def _matura(oznaka):
        o = str(oznaka or "").strip().upper()
        if o:
            out.add("MATURA:" + o)
            out.add("MATURA:" + o.split("-")[0])
            out.add("MATURA")

    for o in matura_oznake or ():
        _matura(o)
    if df_prijave is None or getattr(df_prijave, "empty", True) or "ucenik_id" not in df_prijave.columns:
        return out
    d = df_prijave[df_prijave["ucenik_id"].astype(str).str.strip().str.upper() == uid]
    for _, r in d.iterrows():
        if str(r.get("status_kontakta", "") or "").strip() in ("Otkazano", "Odustao"):
            continue
        komponenta = str(r.get("komponenta", "") or "").strip().upper()
        tip = str(r.get("program_tip", "") or "").strip().upper() or ("UPISI" if komponenta else "")
        if tip == "UPISI":
            out.add("UPISI")
            if komponenta:
                out.add("UPISI:" + komponenta)
        elif tip == "MATURA":
            out.add("MATURA")
            predmet = str(r.get("predmet", "") or "").strip().lower()
            kratica = _KRATICE_MATURA.get(predmet, predmet.upper())
            razina = str(r.get("razina_ispita", "") or "").strip().upper()
            if kratica:
                _matura(f"{kratica}-{razina}" if razina in ("A", "B") else kratica)
        elif tip == "INSTRUKCIJE":
            out.add("INSTRUKCIJE")
    return out


def vidi_li(za, ucenik_id, oznake) -> bool:
    """True ako je poruka namijenjena ovom učeniku. Prazno `za` = nitko."""
    t = set(tokeni(za))
    if not t:
        return False
    if SVI in t or str(ucenik_id or "").strip().upper() in t:
        return True
    return bool(t & {str(o).upper() for o in oznake})


# ------------------------------------------------------------------ čitanje

def _prazan(headers) -> pd.DataFrame:
    return pd.DataFrame(columns=list(headers) + ["_row"])


def _ucitaj_tab(sheet, naziv: str, headers) -> pd.DataFrame:
    """Čita tab; ako ne postoji → prazan DataFrame (čitanje NIKAD ne stvara tab). Sve vrijednosti kao tekst."""
    try:
        ws = sheet.worksheet(naziv)
    except gspread.exceptions.WorksheetNotFound:
        return _prazan(headers)
    zapisi = ws.get_all_records()
    if not zapisi:
        return _prazan(headers)
    df = pd.DataFrame(zapisi)
    for h in headers:
        if h not in df.columns:
            df[h] = ""
    for h in headers:
        df[h] = df[h].astype(str).replace({"nan": "", "None": ""})
    df["_row"] = range(2, len(df) + 2)
    return df


def load_obavijesti(sheet) -> pd.DataFrame:
    return _ucitaj_tab(sheet, OBAVIJESTI_TAB, OBAVIJESTI_HEADERS)


def load_linkove(sheet) -> pd.DataFrame:
    return _ucitaj_tab(sheet, LINKOVI_TAB, LINKOVI_HEADERS)


def load_komentare(sheet) -> pd.DataFrame:
    return _ucitaj_tab(sheet, KOMENTARI_TAB, KOMENTARI_HEADERS)


# ------------------------------------------------------------------ pisanje (zajednički dio)

def _osiguraj_tab(sheet, naziv: str, headers):
    """(ws, stvarno zaglavlje). Stvara tab ako ne postoji; dopisuje stupce koji nedostaju (na desni kraj)."""
    headers = list(headers)
    try:
        ws = sheet.worksheet(naziv)
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=naziv, rows=500, cols=max(len(headers), 8))
        ws.update(range_name="A1", values=[headers], value_input_option="RAW")
        return ws, headers
    zaglavlje = [str(h).strip() for h in ws.row_values(1)]
    if not any(zaglavlje):
        ws.update(range_name="A1", values=[headers], value_input_option="RAW")
        return ws, headers
    nedostaju = [h for h in headers if h not in zaglavlje]
    if nedostaju:
        ukupno = len(zaglavlje) + len(nedostaju)
        if ws.col_count < ukupno:
            ws.add_cols(ukupno - ws.col_count)
        ws.update(range_name=gspread.utils.rowcol_to_a1(1, len(zaglavlje) + 1), values=[nedostaju],
                  value_input_option="RAW")
        zaglavlje += nedostaju
    return ws, zaglavlje


def _dodaj_redak(sheet, naziv: str, headers, polja: dict):
    ws, zaglavlje = _osiguraj_tab(sheet, naziv, headers)
    ws.append_row([str(polja.get(h, "")) for h in zaglavlje], value_input_option="RAW")


def _postavi_polja(sheet, naziv: str, headers, id_polje: str, id_vrijednost: str, row: int, polja: dict):
    """Upiše polja u redak `row`, ali tek nakon provjere da je u tom retku još uvijek traženi id
    (ako je netko u međuvremenu brisao/umetao retke u Sheetu, ništa se ne piše u krivi redak)."""
    ws, zaglavlje = _osiguraj_tab(sheet, naziv, headers)
    trenutni = ws.cell(int(row), zaglavlje.index(id_polje) + 1).value
    if str(trenutni or "").strip() != str(id_vrijednost).strip():
        raise ValueError("Tablica se u međuvremenu promijenila — klikni 🔄 Osvježi podatke i pokušaj ponovno.")
    podaci = [{"range": gspread.utils.rowcol_to_a1(int(row), zaglavlje.index(k) + 1), "values": [[str(v)]]}
              for k, v in polja.items() if k in zaglavlje]
    if podaci:
        ws.batch_update(podaci, raw=True)


# ------------------------------------------------------------------ obavijesti (admin piše, portal čita)

def dodaj_obavijest(sheet, naslov, tekst, za, vazno=False, vrijedi_do=None, autor="Caki") -> str:
    naslov = ocisti_tekst(naslov, MAX_NASLOV).replace("\n", " ")
    tekst = ocisti_tekst(tekst, MAX_TEKST)
    if not naslov:
        raise ValueError("Upiši naslov poruke.")
    if not tekst:
        raise ValueError("Upiši tekst poruke.")
    za = normaliziraj_za(za)
    do = u_datum(vrijedi_do)
    oid = novi_id()
    _dodaj_redak(sheet, OBAVIJESTI_TAB, OBAVIJESTI_HEADERS, {
        "obavijest_id": oid, "datum": sada().strftime("%Y-%m-%d %H:%M:%S"), "naslov": naslov, "tekst": tekst,
        "za": za, "vazno": "Da" if vazno else "", "vrijedi_do": do.isoformat() if do else "",
        "aktivna": "Da", "autor": str(autor or "").strip()})
    return oid


def uredi_obavijest(sheet, obavijest_id, row, naslov, tekst, za, vazno=False, vrijedi_do=None):
    naslov = ocisti_tekst(naslov, MAX_NASLOV).replace("\n", " ")
    tekst = ocisti_tekst(tekst, MAX_TEKST)
    if not naslov or not tekst:
        raise ValueError("Naslov i tekst ne smiju biti prazni.")
    do = u_datum(vrijedi_do)
    _postavi_polja(sheet, OBAVIJESTI_TAB, OBAVIJESTI_HEADERS, "obavijest_id", obavijest_id, row, {
        "naslov": naslov, "tekst": tekst, "za": normaliziraj_za(za), "vazno": "Da" if vazno else "",
        "vrijedi_do": do.isoformat() if do else ""})


def postavi_aktivnu_obavijest(sheet, obavijest_id, row, aktivna: bool):
    _postavi_polja(sheet, OBAVIJESTI_TAB, OBAVIJESTI_HEADERS, "obavijest_id", obavijest_id, row,
                   {"aktivna": "Da" if aktivna else "Ne"})


def obavijesti_za_ucenika(df, ucenik_id, oznake, danas=None) -> list:
    """Aktivne, nepredugo stare poruke namijenjene učeniku: važne prve, zatim najnovije."""
    if df is None or df.empty:
        return []
    danas = danas or sada().date()
    out = []
    for _, r in df.iterrows():
        if not str(r.get("obavijest_id", "")).strip() or not str(r.get("naslov", "")).strip():
            continue
        if not _da(r.get("aktivna")) or not vidi_li(r.get("za"), ucenik_id, oznake):
            continue
        do = u_datum(r.get("vrijedi_do"))
        if do and danas > do:
            continue
        out.append({"obavijest_id": str(r["obavijest_id"]), "datum": prikaz_datuma(r.get("datum")),
                    "_sort": (str(r.get("datum", "")), _cijeli(r.get("_row"), 0)), "naslov": str(r["naslov"]), "tekst": str(r.get("tekst", "")),
                    "vazno": _da(r.get("vazno"))})
    out.sort(key=lambda o: o["_sort"], reverse=True)      # najnovije prvo (isti trenutak → kasniji redak)
    out.sort(key=lambda o: not o["vazno"])
    return out


# ------------------------------------------------------------------ linkovi

def dodaj_link(sheet, naziv, url, opis="", za="SVI", redoslijed=100) -> str:
    naziv = ocisti_tekst(naziv, MAX_NAZIV_LINKA).replace("\n", " ")
    ispravan = sigurni_url(url)
    if not naziv:
        raise ValueError("Upiši naziv linka.")
    if not ispravan:
        raise ValueError("Adresa linka nije ispravna (mora biti npr. https://chat.whatsapp.com/…).")
    lid = novi_id()
    _dodaj_redak(sheet, LINKOVI_TAB, LINKOVI_HEADERS, {
        "link_id": lid, "naziv": naziv, "url": ispravan, "opis": ocisti_tekst(opis, MAX_OPIS_LINKA).replace("\n", " "),
        "za": normaliziraj_za(za), "redoslijed": int(redoslijed), "aktivan": "Da"})
    return lid


def uredi_link(sheet, link_id, row, naziv, url, opis, za, redoslijed):
    naziv = ocisti_tekst(naziv, MAX_NAZIV_LINKA).replace("\n", " ")
    ispravan = sigurni_url(url)
    if not naziv or not ispravan:
        raise ValueError("Naziv i ispravna adresa linka su obavezni.")
    _postavi_polja(sheet, LINKOVI_TAB, LINKOVI_HEADERS, "link_id", link_id, row, {
        "naziv": naziv, "url": ispravan, "opis": ocisti_tekst(opis, MAX_OPIS_LINKA).replace("\n", " "),
        "za": normaliziraj_za(za), "redoslijed": int(redoslijed)})


def postavi_aktivan_link(sheet, link_id, row, aktivan: bool):
    _postavi_polja(sheet, LINKOVI_TAB, LINKOVI_HEADERS, "link_id", link_id, row, {"aktivan": "Da" if aktivan else "Ne"})


def _cijeli(v, zadano=999) -> int:
    try:
        return int(float(str(v).strip().replace(",", ".")))
    except (TypeError, ValueError):
        return zadano


def linkovi_za_ucenika(df, ucenik_id, oznake) -> list:
    """Aktivni linkovi namijenjeni učeniku, poredani po redoslijedu. Neispravan URL se ne prikazuje."""
    if df is None or df.empty:
        return []
    out = []
    for _, r in df.iterrows():
        url = sigurni_url(r.get("url"))
        if not url or not str(r.get("naziv", "")).strip():
            continue
        if not _da(r.get("aktivan")) or not vidi_li(r.get("za"), ucenik_id, oznake):
            continue
        out.append({"link_id": str(r.get("link_id", "")), "naziv": str(r["naziv"]), "url": url,
                    "opis": str(r.get("opis", "") or ""), "redoslijed": _cijeli(r.get("redoslijed"))})
    out.sort(key=lambda x: (x["redoslijed"], x["naziv"].lower()))
    return out


# ------------------------------------------------------------------ komentari klijenata

def previse_komentara(df, ucenik_id, sada_=None, limit=MAX_KOMENTARA_NA_DAN) -> bool:
    """Zaštita od spama: najviše `limit` komentara po učeniku u jednom danu."""
    if df is None or df.empty:
        return False
    danas = (sada_ or sada()).date()
    mine = df[df["ucenik_id"].astype(str).str.strip().str.upper() == str(ucenik_id).strip().upper()]
    return sum(1 for v in mine["datum"] if u_datum(v) == danas) >= limit


def dodaj_komentar(sheet, ucenik_id, ime_djeteta, od, tekst) -> str:
    tekst = ocisti_tekst(tekst, MAX_KOMENTAR)
    if not tekst:
        raise ValueError("Upiši poruku.")
    if od not in OD_OPCIJE:
        raise ValueError("Odaberi tko piše (roditelj ili učenik).")
    kid = novi_id()
    _dodaj_redak(sheet, KOMENTARI_TAB, KOMENTARI_HEADERS, {
        "komentar_id": kid, "datum": sada().strftime("%Y-%m-%d %H:%M:%S"), "ucenik_id": str(ucenik_id).strip(),
        "ime_djeteta": str(ime_djeteta or "").strip(), "od": od, "tekst": tekst, "status": STATUS_NOVO,
        "odgovor": "", "odgovor_datum": ""})
    return kid


def komentari_ucenika(df, ucenik_id) -> list:
    """SAMO komentari tog učenika (strogo po šifri), najnoviji prvi, s Cakijevim odgovorom ako postoji."""
    if df is None or df.empty:
        return []
    uid = str(ucenik_id or "").strip().upper()
    out = []
    for _, r in df.iterrows():
        if str(r.get("ucenik_id", "")).strip().upper() != uid or not str(r.get("komentar_id", "")).strip():
            continue
        out.append({"datum": prikaz_datuma(r.get("datum")),
                    "_sort": (str(r.get("datum", "")), _cijeli(r.get("_row"), 0)),
                    "od": str(r.get("od", "")), "tekst": str(r.get("tekst", "")),
                    "odgovor": str(r.get("odgovor", "") or ""), "odgovor_datum": prikaz_datuma(r.get("odgovor_datum"))})
    out.sort(key=lambda k: k["_sort"], reverse=True)
    return out


def broj_novih_komentara(df) -> int:
    if df is None or df.empty or "status" not in df.columns:
        return 0
    return int(sum(1 for i, s in zip(df["komentar_id"], df["status"])
                   if str(i).strip() and str(s).strip() != STATUS_PROCITANO))


def odgovori_na_komentar(sheet, komentar_id, row, odgovor):
    odgovor = ocisti_tekst(odgovor, MAX_ODGOVOR)
    if not odgovor:
        raise ValueError("Upiši odgovor.")
    _postavi_polja(sheet, KOMENTARI_TAB, KOMENTARI_HEADERS, "komentar_id", komentar_id, row, {
        "odgovor": odgovor, "odgovor_datum": sada().strftime("%Y-%m-%d %H:%M:%S"), "status": STATUS_PROCITANO})


def postavi_status_komentara(sheet, komentar_id, row, status):
    if status not in (STATUS_NOVO, STATUS_PROCITANO):
        raise ValueError("Nepoznat status.")
    _postavi_polja(sheet, KOMENTARI_TAB, KOMENTARI_HEADERS, "komentar_id", komentar_id, row, {"status": status})


# ------------------------------------------------------------------ tekst za WhatsApp (šalje Caki ručno)

def tekst_poruke_za_whatsapp(naslov, tekst, link="") -> str:
    dijelovi = [f"*{naslov}*" if str(naslov or "").strip() else "", str(tekst or "").strip(), str(link or "").strip()]
    return "\n\n".join(d for d in dijelovi if d)
