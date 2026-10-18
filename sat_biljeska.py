"""
CAKI — sat_biljeska.py  (17.10.2026.)
Bilješka sata za INSTRUKCIJE: obrađene teme (iz šifrarnika baze zadataka), ocjena sata (+ / −) i zadaća
(zadana → na sljedećem satu profesor označi je li napravljena). Podsjetnik adminu kad dijete dvaput zaredom
nije napravilo zadaću (kartica na 🏠 Danas + gotova WhatsApp poruka roditelju; šalje Caki klikom).

ISTA datoteka u caki-evidencija-dolazaka (profesor piše), caki-booking-termina (Moj CAKI prikazuje) i
caki-upisi-crm (admin). Ne uvozi pipeline_upisi.py, da se ne mora sinkronizirati s njim.

Novi stupci u tabu Instrukcije_termini (dopisuju se sami na desni kraj pri prvom spremanju):
  teme                 obrađene teme, odvojene s " ; " (svaka oblika "Cjelina › Potpoglavlje" ili slobodan tekst)
  ocjena_sata          "+" ili "-" (INTERNO: vide profesori i admin, roditelj ne vidi)
  zadaca_zadana        "Da" ako je na tom satu zadana zadaća
  zadaca_napravljena   "Da" / "Djelomično" / "Ne" (upisuje profesor na SLJEDEĆEM satu)
  zadaca_javljeno      "Da" kad je admin javio roditelju (kartica nestaje)

Privatnost: interna napomena i ocjena sata se roditelju nikad ne prikazuju; profesor koji preuzme učenika
vidi povijest sati i teme BEZ imena prethodnog profesora i bez ikakvih plaćanja.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import gspread
import pandas as pd


def _danas() -> date:
    """Današnji datum u Zagrebu. NE date.today(): server (Streamlit Cloud) je u UTC-u, pa bi
    rokovi nakon ponoći po našem vremenu bili pomaknuti za dan (popravak 18.10.2026.).
    Ovaj modul namjerno ne uvozi pipeline_upisi, pa koristi isti obrazac kao profesori.py."""
    return datetime.now(ZoneInfo("Europe/Zagreb")).date()

TAB = "Instrukcije_termini"
SAT_STUPCI = ["teme", "ocjena_sata", "zadaca_zadana", "zadaca_napravljena", "zadaca_javljeno"]
OCJENE = ["", "+", "-"]
ZADACA_STATUSI = ["Da", "Djelomično", "Ne"]
ZADACA_OZNAKE = {"Da": "✅ napravljena", "Djelomično": "🟡 djelomično", "Ne": "❌ nije napravljena", "": "⏳ čeka provjeru"}
SEP = " ; "
MAX_TEME = 600
STATUSI_BEZ_SATA = ("Otkazan na vrijeme", "Otkazan kasno", "Nije došao", "Zakazan")


def _t(v) -> str:
    return "" if v is None else str(v).strip()


def datum_iz(v):
    """'2026-10-03' / '2026-10-03 17:00' → date ili None."""
    s = _t(v)[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


# ------------------------------------------------------------------ teme

def teme_u_tekst(teme) -> str:
    """Popis tema → jedan tekst za Sheet. Čisti separator i prekomjernu duljinu."""
    ciste = []
    for x in teme or []:
        x = re.sub(r"[\x00-\x1f]", " ", _t(x)).replace(";", ",").strip()
        if x and x not in ciste:
            ciste.append(x)
    return SEP.join(ciste)[:MAX_TEME]


def teme_iz_teksta(tekst) -> list:
    return [x.strip() for x in _t(tekst).split(";") if x.strip()]


def ucitaj_sifrarnik(spreadsheet) -> dict:
    """{cjelina: [potpoglavlja]} iz tabova Sifrarnik_cjelina i Sifrarnik_potpoglavlja baze zadataka.
    Prazan dict ako tabova nema (pozivatelj onda nudi slobodan unos)."""
    try:
        wc = spreadsheet.worksheet("Sifrarnik_cjelina")
    except gspread.exceptions.WorksheetNotFound:
        return {}
    zagl = [_t(h).lower() for h in (wc.row_values(1) or [])]
    ic = zagl.index("cjelina") if "cjelina" in zagl else 1
    out = {}
    for r in wc.get_all_values()[1:]:
        c = _t(r[ic]) if len(r) > ic else ""
        if c:
            out.setdefault(c, [])
    try:
        wp = spreadsheet.worksheet("Sifrarnik_potpoglavlja")
        redovi = []
        for r in wp.get_all_values()[1:]:
            if len(r) >= 2 and _t(r[0]) and _t(r[1]):
                try:
                    red = float(_t(r[2]).replace(",", ".")) if len(r) > 2 and _t(r[2]) else 9999.0
                except ValueError:
                    red = 9999.0
                redovi.append((_t(r[0]), _t(r[1]), red))
        for c, p, _ in sorted(redovi, key=lambda x: x[2]):
            lista = out.setdefault(c, [])
            if p not in lista:
                lista.append(p)
    except gspread.exceptions.WorksheetNotFound:
        pass
    return out


def popis_tema(sifrarnik: dict) -> list:
    """Za padajući izbornik: 'Cjelina' pa ispod 'Cjelina › Potpoglavlje'."""
    out = []
    for c, ps in (sifrarnik or {}).items():
        out.append(c)
        out += [f"{c} › {p}" for p in ps]
    return out


# ------------------------------------------------------------------ pisanje

def _ws_sa_stupcima(sheet):
    ws = sheet.worksheet(TAB)
    zagl = [_t(h) for h in ws.row_values(1)]
    fale = [h for h in SAT_STUPCI if h not in zagl]
    if fale:
        if ws.col_count < len(zagl) + len(fale):
            ws.add_cols(len(zagl) + len(fale) - ws.col_count)
        ws.update(range_name=gspread.utils.rowcol_to_a1(1, len(zagl) + 1), values=[fale], value_input_option="RAW")
        zagl += fale
    return ws, zagl


def _nadji(ws, zagl, termin_id):
    """(row, zapis) za termin_id; ValueError ako ga nema."""
    ci = zagl.index("termin_id")
    for i, r in enumerate(ws.get_all_values()[1:], start=2):
        if len(r) > ci and _t(r[ci]) == _t(termin_id):
            return i, {zagl[j]: (r[j] if j < len(r) else "") for j in range(len(zagl))}
    raise ValueError("Termin nije pronađen — osvježi stranicu.")


def _upisi(ws, zagl, row, polja: dict):
    ws.batch_update([{"range": gspread.utils.rowcol_to_a1(row, zagl.index(k) + 1), "values": [[str(v)]]}
                     for k, v in polja.items()], raw=True)


def spremi_sat(sheet, termin_id: str, teme, ocjena: str = "", zadaca_zadana: bool = False,
               nastavnik: str = "", rok_dana: int | None = None, danas: date | None = None):
    """Spremi teme, ocjenu i 'zadaća zadana' za termin. Profesor (nastavnik zadan): samo svoj termin, u roku."""
    if ocjena not in OCJENE:
        raise ValueError("Ocjena sata može biti samo + ili −.")
    ws, zagl = _ws_sa_stupcima(sheet)
    row, z = _nadji(ws, zagl, termin_id)
    if nastavnik and _t(z.get("nastavnik")) != nastavnik:
        raise ValueError("Možete uređivati samo svoje termine.")
    if rok_dana is not None:
        d = datum_iz(z.get("datum"))
        danas = danas or _danas()
        if d and (danas - d).days > rok_dana:
            raise ValueError(f"Bilješku možete mijenjati najviše {rok_dana} dana nakon termina — javite se adminu.")
    novo = {"teme": teme_u_tekst(teme), "ocjena_sata": ocjena, "zadaca_zadana": "Da" if zadaca_zadana else ""}
    if not zadaca_zadana:
        novo["zadaca_napravljena"] = ""     # nema zadaće → nema ni provjere
    _upisi(ws, zagl, row, novo)


def smije_provjeriti(df_instr: pd.DataFrame, nastavnik: str, ucenik_id: str, df_dodjele: pd.DataFrame | None = None,
                     danas: date | None = None) -> bool:
    """Profesor smije označiti zadaću učenika kojeg ima: ima njegov termin s tim učenikom ILI mu je učenik
    dodijeljen (aktivna dodjela) — novi profesor tako može provjeriti zadaću prije svog prvog sata."""
    uid = _t(ucenik_id)
    if df_instr is not None and not df_instr.empty and "nastavnik" in df_instr.columns:
        if ((df_instr["ucenik_id"].astype(str) == uid) & (df_instr["nastavnik"].astype(str) == nastavnik)).any():
            return True
    if df_dodjele is not None and not df_dodjele.empty and "profesor" in df_dodjele.columns:
        danas = danas or _danas()
        for _, r in df_dodjele[(df_dodjele["ucenik_id"].astype(str) == uid)
                               & (df_dodjele["profesor"].astype(str) == nastavnik)].iterrows():
            do = datum_iz(r.get("do"))
            if do is None or do >= danas:
                return True
    return False


def oznaci_zadacu(sheet, termin_id: str, status: str, nastavnik: str, df_instr: pd.DataFrame,
                  df_dodjele: pd.DataFrame | None = None):
    """Na SLJEDEĆEM satu: je li zadaća zadana na termin_id napravljena. Smije profesor koji ima tog učenika
    (ne mora biti isti koji je zadao zadaću — učenik je možda prebačen)."""
    if status not in ZADACA_STATUSI:
        raise ValueError("Odaberi: napravljena, djelomično ili nije napravljena.")
    ws, zagl = _ws_sa_stupcima(sheet)
    row, z = _nadji(ws, zagl, termin_id)
    if _t(z.get("zadaca_zadana")) != "Da":
        raise ValueError("Na tom satu nije zadana zadaća.")
    if nastavnik and not smije_provjeriti(df_instr, nastavnik, z.get("ucenik_id"), df_dodjele):
        raise ValueError("Zadaću možete provjeriti samo za svoje učenike.")
    _upisi(ws, zagl, row, {"zadaca_napravljena": status, "zadaca_javljeno": ""})


def oznaci_javljeno(sheet, termin_id: str):
    """Admin: roditelju je javljeno (kartica 'zadaća' za taj niz nestaje)."""
    ws, zagl = _ws_sa_stupcima(sheet)
    row, _ = _nadji(ws, zagl, termin_id)
    _upisi(ws, zagl, row, {"zadaca_javljeno": "Da"})


# ------------------------------------------------------------------ logika nad tablicom

def _stupac(df, naziv):
    return df[naziv].astype(str).str.strip() if naziv in df.columns else pd.Series([""] * len(df), index=df.index)


def odrzani(df_instr: pd.DataFrame) -> pd.DataFrame:
    """Termini koji su se održali (bez zakazanih/otkazanih), s pomoćnim stupcem _d (datum)."""
    if df_instr is None or df_instr.empty or "ucenik_id" not in df_instr.columns:
        return pd.DataFrame()
    d = df_instr.copy()
    if "status_termina" in d.columns:
        d = d[~d["status_termina"].astype(str).str.strip().isin(STATUSI_BEZ_SATA)]
    d["_d"] = d["datum"].apply(datum_iz)
    d = d[d["_d"].notna()]
    return d.sort_values("_d", kind="stable")


def zadaca_na_cekanju(df_instr: pd.DataFrame, ucenik_id: str, prije: date | None = None):
    """Zadnji održani sat učenika s zadanom zadaćom koja još nije provjerena (dict) ili None.
    `prije`: samo sati strogo prije tog datuma (da novi sat ne provjerava samog sebe)."""
    d = odrzani(df_instr)
    if d.empty:
        return None
    d = d[d["ucenik_id"].astype(str) == _t(ucenik_id)]
    d = d[(_stupac(d, "zadaca_zadana") == "Da") & (_stupac(d, "zadaca_napravljena") == "")]
    if prije:
        d = d[d["_d"] < prije]
    if d.empty:
        return None
    r = d.iloc[-1]
    return {"termin_id": _t(r.get("termin_id")), "datum": r["_d"], "predmet": _t(r.get("predmet")),
            "teme": _t(r.get("teme"))}


def povijest_ucenika(df_instr: pd.DataFrame, ucenik_id: str) -> pd.DataFrame:
    """Za profesora koji preuzima učenika: sati, teme, javna bilješka, ocjena, zadaća. BEZ imena profesora,
    BEZ interne napomene, BEZ plaćanja. Najnoviji prvi."""
    d = odrzani(df_instr)
    if d.empty:
        return pd.DataFrame()
    d = d[d["ucenik_id"].astype(str) == _t(ucenik_id)].sort_values("_d", ascending=False, kind="stable")
    if d.empty:
        return pd.DataFrame()
    zad = []
    for _, r in d.iterrows():
        if _t(r.get("zadaca_zadana")) == "Da":
            zad.append("📝 zadana — " + ZADACA_OZNAKE.get(_t(r.get("zadaca_napravljena")), ""))
        else:
            zad.append("")
    return pd.DataFrame({
        "Datum": [x.strftime("%d.%m.%Y.") for x in d["_d"]],
        "Predmet": _stupac(d, "predmet").values,
        "Teme": _stupac(d, "teme").values,
        "📒 Bilješka": _stupac(d, "napomena_javna").values,
        "Ocjena": _stupac(d, "ocjena_sata").values,
        "Zadaća": zad,
    })


def za_roditelja(df_instr: pd.DataFrame, ucenik_id: str) -> pd.DataFrame:
    """Što roditelj/učenik vidi u Moj CAKI: teme i zadaća po satu. NIKAD ocjena sata ni interna napomena."""
    d = odrzani(df_instr)
    if d.empty:
        return pd.DataFrame()
    d = d[d["ucenik_id"].astype(str) == _t(ucenik_id)].sort_values("_d", ascending=False, kind="stable")
    d = d[(_stupac(d, "teme") != "") | (_stupac(d, "zadaca_zadana") == "Da")]
    if d.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        "Datum": [x.strftime("%d.%m.%Y.") for x in d["_d"]],
        "Predmet": _stupac(d, "predmet").values,
        "Što smo radili": _stupac(d, "teme").str.replace(SEP.strip(), ",", regex=False).values,
        "Zadaća": [ZADACA_OZNAKE.get(_t(r.get("zadaca_napravljena")), "") if _t(r.get("zadaca_zadana")) == "Da" else ""
                   for _, r in d.iterrows()],
    })


# ------------------------------------------------------------------ podsjetnik adminu

def tekst_roditelju(ime_djeteta: str, predmet: str = "", datum: date | None = None) -> str:
    ime = _t(ime_djeteta) or "Vaše dijete"
    sto = f" iz predmeta {_t(predmet)}" if _t(predmet) else ""
    kada = f" (zadnji put za sat {datum.strftime('%d.%m.')})" if datum else ""
    return (f"Poštovani, javljamo da {ime} dva puta zaredom nije napravio/la zadaću{sto}{kada}. "
            "Molimo vas da dijete potaknete da zadaću napravi do sljedećeg sata. Hvala! CAKI centar")


def podsjetnici_zadace(df_instr: pd.DataFrame, df_ucenici: pd.DataFrame | None = None) -> list:
    """Učenici kojima su zadnje DVIJE provjerene zadaće 'Ne' (od zadnje provjere roditelju nije javljeno).
    [{ucenik_id, ime_djeteta, predmet, zadnji_termin_id, datum, tekst, mobitel_roditelja}] — najnoviji prvi."""
    d = odrzani(df_instr)
    if d.empty or "zadaca_zadana" not in d.columns:
        return []
    d = d[(_stupac(d, "zadaca_zadana") == "Da") & (_stupac(d, "zadaca_napravljena") != "")]
    uc = {} if df_ucenici is None or df_ucenici.empty or "ucenik_id" not in df_ucenici.columns else \
        {_t(r["ucenik_id"]): r for _, r in df_ucenici.iterrows()}
    out = []
    for uid, g in d.groupby(d["ucenik_id"].astype(str)):
        zadnje = g.iloc[-2:]
        if len(zadnje) < 2 or not all(_t(x) == "Ne" for x in zadnje["zadaca_napravljena"]):
            continue
        zadnji = zadnje.iloc[-1]
        if _t(zadnji.get("zadaca_javljeno")) == "Da":
            continue
        u = uc.get(uid)
        ime = _t(zadnji.get("ime_djeteta")) or (_t(u.get("ime_djeteta")) if u is not None else "")
        out.append({"ucenik_id": uid, "ime_djeteta": ime, "predmet": _t(zadnji.get("predmet")),
                    "nastavnik": _t(zadnji.get("nastavnik")),
                    "zadnji_termin_id": _t(zadnji.get("termin_id")), "datum": zadnji["_d"],
                    "tekst": tekst_roditelju(ime, _t(zadnji.get("predmet")), zadnji["_d"]),
                    "mobitel_roditelja": _t(u.get("mobitel_roditelja")) if u is not None else ""})
    return sorted(out, key=lambda x: x["datum"], reverse=True)


def tekst_profesoru(ime_djeteta: str, ime_profesora: str = "") -> str:
    """Kratki podsjetnik profesoru (admin ga šalje klikom)."""
    pozdrav = f"Bok {_t(ime_profesora)}! " if _t(ime_profesora) else "Bok! "
    return (f"{pozdrav}Podsjetnik: {_t(ime_djeteta) or 'učenik'} dva puta zaredom nije napravio/la zadaću. "
            "Molim te da to spomeneš na sljedećem satu i zadaš zadaću koja je izvediva. Hvala!")


def wa_link(tekst: str, broj) -> str:
    b = re.sub(r"\D", "", _t(broj))
    if b.startswith("00"):
        b = b[2:]
    if b.startswith("0"):
        b = "385" + b[1:]
    return f"https://wa.me/{b if len(b) >= 9 else ''}?text={quote(tekst)}"
