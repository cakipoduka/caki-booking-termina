"""
CAKI — podaci.py
================
JEDNO MJESTO koje zna "gdje su podaci" i "koji je ključ zapisa".

Zašto postoji (5.10.2026.):
    Google Sheet je identitet retka vezao na BROJ RETKA (`_row` = 2, 3, 4...).
    To je u redu dok su podaci samo u Sheetu, ali u bazi broj retka nije
    stabilan: sortiranje, brisanje i istovremeni rad dva čovjeka ga pomiču.
    Zato svaki zapis dobiva KLJUČ (npr. `ucenik_id`, `redak_id`) — vrijednost
    koja ostaje ista bez obzira gdje se redak nalazi.

Što ovo NE dira:
    - `_row` ostaje u svim tablicama kakav je bio. Nijedan postojeći poziv
      (`azuriraj_ucenika(sheet, 7, {...})`) se ne kvari.
    - Ovdje NEMA nijedne promjene poslovnog pravila. Samo imenovanje ključa.

Stanje:
    Korak 1 (ovaj): popis ključeva + `_kljuc` u učitanim podacima + provjere.
    Korak 2 (sljedeći): funkcije za pisanje primaju i ključ, ne samo broj retka,
      i prekidač `PODACI_BACKEND` ("sheets" / "supabase").
"""

from __future__ import annotations

import re
import sys

import pandas as pd

# ============================================================================
#  KLJUC_PO_TABU — koji stupac je ključ zapisa u kojem tabu
# ============================================================================
#  Vrijednost je:
#    - string            -> jedan stupac je ključ
#    - tuple[str, ...]   -> ključ je spoj više stupaca (npr. Cjenik: ista šifra
#                           postoji za više Solo subjekata, pa je ključ
#                           (sifra, subjekt) — potvrđeno na izvozu 5.10.2026.)
#
#  Tabovi kojih ovdje NEMA (npr. "Raspored_Matura_2026/27" čije ime nosi sezonu,
#  i "Zadaci" iz druge baze) dobivaju prazan `_kljuc` i broje se u izvješću
#  `izvjestaj_kljuceva()`. Ne izmišljam im ključ.
# ----------------------------------------------------------------------------
KLJUC_PO_TABU: dict[str, str | tuple[str, ...]] = {
    "Učenici":              "ucenik_id",
    "Prijave":              "redak_id",
    "Grupe":                "grupa_id",
    "Rezervacije":          "rezervacija_id",
    "Gostovanja":           "gostovanje_id",
    "Termini":              "termin_id",
    "Dolasci":              "dolazak_id",
    "Zamjene log":          "termin_id",
    "Biljeske":             "biljeska_id",
    "Instrukcije_termini":  "termin_id",
    "Nastavnici":           "ime",
    "Cjenik":               ("sifra", "subjekt"),      # ista šifra po subjektu
    "Racuni_i_ponude":      "dokument_id",
    "PDV_prag":             ("subjekt", "godina", "mjesec"),
    "Izvjestaji_instruktora": "izvjestaj_id",
    "Dodjele":              "dodjela_id",
    "Honorari":             "honorar_id",
    "Paketi_sati":          "paket_id",
    "Matura_postavke":      "ucenik_id",
    "Razdoblja_termina":    "kljuc",
    "Praznici":             "datum",
    "Mail_predlosci":       "kljuc",
    "WhatsApp_predlosci":   "kljuc",
    "FORM_UPISI":           "Timestamp",               # tab "Form responses 1"
    "Backup_log":           "file_id",
    "Uvoz_instrukcije":     "ucenik_id",               # 89% prazno; vidi izvjestaj
    # GDPR_log NEMA ključ u Sheetu (samo sifra_ucenika, a zapis može biti i bez
    # učenika). U bazi dobiva vlastiti id — vidi 002/003 migraciju.
}

# ----------------------------------------------------------------------------
#  Tabovi čije ime NIJE stalno (nosi sezonu), pa se ne mogu upisati u popis.
#  Primjer: tab rasporeda Mature zove se "Raspored_Matura_202627".
#  Uzorak je regex; ključ je redak_id (redak "kanta s profesorom" je namjerno
#  bez njega i dobiva ključ iz termina — vidi izracunaj_kljuc).
# ----------------------------------------------------------------------------
TABOVI_SA_UZORKOM: list[tuple[str, str | tuple[str, ...]]] = [
    (r"^raspored", "redak_id"),
]


def naziv_taba_rasporeda(sezona: str) -> str:
    """Ime taba rasporeda Mature za sezonu, npr. '2026/27' -> 'Raspored_Matura_202627'.
    Isto pravilo kao u raspored_matura.py — ovdje da podaci.py može prepoznati tab
    i kad mu se ime mijenja svake sezone."""
    return "Raspored_Matura_" + str(sezona or "").replace("/", "")


def _tekst(v) -> str:
    """Vrijednost ćelije u čist tekst; prazno/NaN/None -> ''."""
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat", "<na>") else s


def je_prazan_redak(red) -> bool:
    """True ako su SVE ćelije retka prazne (Sheet vraća takve retke na kraju taba)."""
    try:
        vrijednosti = red.values() if hasattr(red, "values") else red
    except Exception:
        return False
    for v in vrijednosti:
        if _tekst(v) != "":
            return False
    return True


def stupci_kljuca(tab: str) -> tuple[str, ...]:
    """Stupci koji čine ključ taba. Prazan tuple ako tab nije u popisu."""
    zapis = KLJUC_PO_TABU.get(_nadi_tab(tab))
    if not zapis:
        zapis = _po_uzorku(tab)
    if not zapis:
        return ()
    return (zapis,) if isinstance(zapis, str) else tuple(zapis)


def _po_uzorku(tab: str) -> str | tuple[str, ...] | None:
    """Ključ za tabove kojima ime nije stalno (npr. 'Raspored_Matura_202627')."""
    naziv = str(tab or "").strip().lower()
    for uzorak, zapis in TABOVI_SA_UZORKOM:
        try:
            if re.match(uzorak, naziv):
                return zapis
        except re.error:
            continue
    return None


def _nadi_tab(tab: str) -> str:
    """Nade naziv taba u popisu bez obzira na razmake i velika/mala slova."""
    if tab in KLJUC_PO_TABU:
        return tab
    zeljeno = str(tab or "").strip().lower()
    for k in KLJUC_PO_TABU:
        if k.strip().lower() == zeljeno:
            return k
    return str(tab or "")


# Isti tab se u kodu zove na dva nacina: ljudski ("Instrukcije_termini")
# i kratko, kako se zove funkcija za ucitavanje ("Instrukcije").
# Bez ovoga bi kljuc iz jednog poziva bio prazan, a iz drugog ispravan.
ALIJASI_TABOVA: dict[str, str] = {
    "instrukcije": "Instrukcije_termini",
    "instrukcije_termini": "Instrukcije_termini",
    "termini": "Instrukcije_termini",
}


def normaliziraj_tab(tab: str) -> str:
    """Vrati pravi naziv taba iz KLJUC_PO_TABU (ili ulaz ako ga ne prepoznaje)."""
    pronaden = _nadi_tab(tab)
    if pronaden in KLJUC_PO_TABU:
        return pronaden
    return ALIJASI_TABOVA.get(str(tab or "").strip().lower(), str(tab or ""))


def izracunaj_kljuc(red, tab: str) -> str:
    """Ključ jednog retka.

    Redoslijed:
      1. ako tab ima ključ u popisu -> vrijednost iz tog stupca (ili spoj stupaca);
      2. ako je ključ prazan, a redak je redak Rasporeda Matura -> "kanta:dan:termin:ucionica"
         (redak "kanta s profesorom" NAMJERNO nema redak_id — vidi
         `raspored_matura.retci_za_spremanje`; bez ovoga bi takav redak ostao bez identiteta);
      3. inače prazno — i to se broji u izvješću, ne prešućuje.
    """
    stupci = stupci_kljuca(normaliziraj_tab(tab))
    if not stupci:
        return ""
    try:
        dijelovi = [_tekst(red.get(s, "")) for s in stupci]
    except AttributeError:
        return ""
    if len(dijelovi) == 1:
        kljuc = dijelovi[0]
    else:
        # svi dijelovi moraju postojati, inače ključ nije potpun
        kljuc = "|".join(dijelovi) if all(dijelovi) else ""

    if kljuc:
        return kljuc

    # redak rasporeda bez redak_id = "kanta s profesorom" (termin/učionica bez učenika)
    if "raspored" in str(tab).strip().lower():
        dan, termin, ucionica = (_tekst(red.get("dan", "")), _tekst(red.get("termin", "")),
                                 _tekst(red.get("ucionica", "")))
        if dan and termin and ucionica:
            return f"kanta:{dan}:{termin}:{ucionica}"
    return ""


def dodaj_kljuc(df: pd.DataFrame, tab: str) -> pd.DataFrame:
    """Doda stupce `_kljuc` (ključ zapisa) i `_kljuc_izvor` u već učitani DataFrame.

    `_kljuc_izvor` kaže odakle ključ dolazi:
        "tab"    — iz stupca navedenog u KLJUC_PO_TABU
        "kanta"  — izračunat za redak rasporeda bez redak_id
        "nema"   — tab nije u popisu ključeva
        "prazno" — tab JE u popisu, ali ovaj redak nema ključ
    """
    df = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame(df)
    if df.empty:
        df["_kljuc"] = pd.Series(dtype="object")
        df["_kljuc_izvor"] = pd.Series(dtype="object")
        if "_row" not in df.columns:
            df["_row"] = pd.Series(dtype="int64")
        return df

    # `_row` je broj retka i mora postojati da se kljuc može pretvoriti natrag u
    # redak za pisanje. Ako ga tablica već ima (učitavanje iz Sheeta ga postavi),
    # NE diramo ga — inače bi se brojevi redaka pomakli.
    if "_row" not in df.columns:
        df["_row"] = range(2, len(df) + 2)

    ima_kljuc = bool(stupci_kljuca(normaliziraj_tab(tab)))
    kljucevi = [izracunaj_kljuc(red, tab) for _, red in df.iterrows()]
    df["_kljuc"] = kljucevi
    if not ima_kljuc:
        df["_kljuc_izvor"] = "nema"
    else:
        df["_kljuc_izvor"] = [
            ("kanta" if k.startswith("kanta:") else ("tab" if k else "prazno")) for k in kljucevi
        ]
    return df


class NepoznatKljuc(ValueError):
    """Ključ zapisa ne postoji u tabu.

    Diže se NAMJERNO, umjesto da se upiše u pogrešan redak. Tko dobije ovu grešku
    šalje broj retka (`_row`) ili točan ključ iz taba.
    """


class _NemaPodataka(Exception):
    """Privremeno: nemamo podatke za rješavanje pa treba posegnuti za Sheetom."""


def _je_broj_retka(vrijednost) -> bool:
    """Je li vrijednost broj retka (`_row`), a ne ključ.

    `_row` je cijeli broj (2, 3, 4...). Ključevi su tekst (ucenik_id, redak_id,
    dokument_id...). Ako netko slučajno pošalje "7" kao tekst, to je ključ i ne
    nalazi se — bolje glasna greška nego tihi upis u pogrešan redak.
    """
    return isinstance(vrijednost, int) and not isinstance(vrijednost, bool)


def _redak_po_kljucu(df: pd.DataFrame, tab: str, kljuc, sheet_name: str = "") -> int:
    """Nađe `_row` retka čiji je `_kljuc` jednak predanoj vrijednosti."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        raise _NemaPodataka(tab)
    if "_kljuc" not in df.columns:
        raise _NemaPodataka(tab)
    trazeni = _tekst(kljuc)
    if not trazeni:
        raise NepoznatKljuc(f"[{tab}] ključ je prazan — ne mogu ga naći")
    if "_row" not in df.columns:
        raise _NemaPodataka(tab)
    redci = df[df["_kljuc"].astype(str) == trazeni]
    if redci.empty:
        raise NepoznatKljuc(
            f"[{tab}] nema retka s ključem {trazeni!r} "
            f"({len(df)} redaka pregledano) — provjeri je li zapis obrisan ili je ključ pogrešan"
        )
    return int(redci.iloc[0]["_row"])


def riješi(sheet, vrijednost, tab: str, df: pd.DataFrame | None = None,
           podaci_modul=None, sheet_name: str = "") -> int:
    """Broj retka (`_row`) iz onoga što je pozivatelj poslao — broja retka ILI ključa.

    Zašto: dosad su sve funkcije za pisanje primale isključivo broj retka
    (`azuriraj_ucenika(sheet, 7, {...})`). Broj retka se u bazi ne može koristiti
    kao identitet (sortiranje, brisanje i istovremeni rad ga pomiču). Zato se sada
    može poslati i KLJUČ (`azuriraj_ucenika(sheet, "AA1234", {...})`), a stari
    pozivi s brojem retka rade dalje nepromijenjeno.

    Redoslijed:
      1. broj retka -> vraća se odmah;
      2. ključ + predani `df` (najjeftinije, bez ijednog čitanja);
      3. ključ bez `df` -> tablica se učita i ključ se nađe u njoj.

    Ako ključ ne postoji, diže se `NepoznatKljuc` — NIKAD se ne upisuje u pogrešan
    redak. To je namjerno glasno.

    Citanje: ključ se traži u predanom `df`. Ako ga nema, koristi se postojeća
    funkcija za učitavanje tog taba (`load_ucenici`, `load_grupe`...). Kad je zove
    aplikacija, te funkcije su već keširane (`@st.cache_data`), pa nema novih
    poziva prema Googleu. Izvan aplikacije (npr. u skripti) učita se izravno.
    """
    if _je_broj_retka(vrijednost):
        return int(vrijednost)

    naziv = sheet_name or tab
    try:
        return _redak_po_kljucu(df, tab, vrijednost)
    except _NemaPodataka:
        pass

    modul = podaci_modul
    if modul is None:
        modul = sys.modules.get("pipeline_upisi")
    if modul is None:
        try:
            import pipeline_upisi as modul  # kasni uvoz da ne bude kruga
        except ImportError:
            raise NepoznatKljuc(
                f"[{tab}] ne mogu naći redak za ključ {_tekst(vrijednost)!r} "
                f"(nemam učitane podatke)"
            ) from None
    df2 = _ucitaj_tab(modul, naziv, sheet)
    return _redak_po_kljucu(df2, tab, vrijednost)


# Keš učitavača po imenu taba — samo da se ne traži funkcija pri svakom pozivu.
_UCITAVACI: dict[str, object] = {}


def _ucitaj_tab(modul, naziv: str, sheet) -> pd.DataFrame:
    """Učita tab koristeći POSTOJEĆU `load_*` funkciju iz pipelinea.

    Zašto postojeću, a ne novu: te funkcije u aplikaciji imaju `@st.cache_data`,
    pa se podaci ne čitaju ponovno iz Googlea. Nova funkcija bi zaobišla keš.

    Imena se razlikuju (Učenici -> load_ucenici, Grupe -> load_grupe), pa se
    kandidati grade bez dijakritika i s uobičajenim nastavcima.
    """
    ucitavac = _UCITAVACI.get(naziv)
    if ucitavac is None:
        cist = _bez_dijakritika(naziv)
        kandidati = [cist, cist + "e", cist + "i", cist.rstrip("aei")]
        if cist.startswith("instrukcije"):
            kandidati.insert(0, "instrukcije")
        if cist == "dolazak":
            kandidati.append("dolasci")
        ucitavac = None
        for ime in kandidati:
            kandidat = getattr(modul, "load_" + ime, None)
            if callable(kandidat):
                ucitavac = kandidat
                break
    if ucitavac is None:
        # rezerva: izravno učitavanje radnog lista (bez keša, ali točno)
        try:
            return modul._load_worksheet_df(sheet.worksheet(naziv))
        except Exception as e:
            # Tab koji još ne postoji (npr. prazni Izvjestaji_instruktora) NIJE greška:
            # u njemu sigurno nema traženog ključa. Vraćamo praznu tablicu da pozivatelj
            # dobije jasnu poruku "nema retka s tim ključem", a ne rušenje aplikacije.
            if type(e).__name__ == "WorksheetNotFound":
                _UCITAVACI[naziv] = _prazna_tablica
                return _prazna_tablica(sheet)
            raise NepoznatKljuc(f"[{naziv}] ne mogu učitati tab: {type(e).__name__}: {e}") from None
    df = ucitavac(sheet)
    _UCITAVACI[naziv] = ucitavac
    return df


def _prazna_tablica(_sheet=None) -> pd.DataFrame:
    """Prazna tablica (tab još ne postoji) — da rješavanje ključa ne pukne."""
    return pd.DataFrame(columns=["_row", "_kljuc", "_kljuc_izvor"])


def _bez_dijakritika(tekst: str) -> str:
    """'Učenici' -> 'ucenici' (za sastavljanje imena funkcija)."""
    tablica = str.maketrans("čćžšđČĆŽŠĐ", "cczsdCCZSD")
    return str(tekst or "").strip().lower().translate(tablica)


# ============================================================================
#  IZVJESTAJ — što je pronađeno, da se ništa ne izgubi tiho
# ============================================================================

def izvjestaj_kljuceva(df: pd.DataFrame, tab: str) -> dict:
    """Kratki nalaz za jedan tab: ima li ključ, koliko ih je jedinstvenih, koliko praznih."""
    ispravan = normaliziraj_tab(tab)
    if df is None or df.empty:
        return {"tab": tab, "redaka": 0, "kljuc": "/".join(stupci_kljuca(ispravan)) or "-",
                "praznih_kljuceva": 0, "duplih_kljuceva": 0, "jedinstvenih": 0}
    kljucevi = list(df.get("_kljuc", []))
    neprazni = [k for k in kljucevi if k]
    return {
        "tab": tab,
        "redaka": int(len(df)),
        "kljuc": "/".join(stupci_kljuca(ispravan)) or "-",
        "praznih_kljuceva": int(len(kljucevi) - len(neprazni)),
        "duplih_kljuceva": int(len(neprazni) - len(set(neprazni))),
        "jedinstvenih": int(len(set(neprazni))),
    }


def ispisi_izvjestaj_kljuceva(df: pd.DataFrame, tab: str, log=print) -> dict:
    """Ispiše nalaz i vrati ga. Upozorava na prazne i dvostruke ključeve."""
    nalaz = izvjestaj_kljuceva(df, tab)
    if nalaz["redaka"] == 0:
        return nalaz
    if nalaz["kljuc"] == "-":
        log(f"[kljucevi] {tab}: tab nije u KLJUC_PO_TABU — kljuc nije odreden "
            f"({nalaz['redaka']} redaka)")
    elif nalaz["praznih_kljuceva"]:
        log(f"[kljucevi] UPOZORENJE {tab}: {nalaz['praznih_kljuceva']} od {nalaz['redaka']} "
            f"redaka nema kljuc ({nalaz['kljuc']})")
    if nalaz["duplih_kljuceva"]:
        log(f"[kljucevi] UPOZORENJE {tab}: {nalaz['duplih_kljuceva']} dvostrukih kljuceva "
            f"({nalaz['kljuc']}) — u bazi kljuc mora biti jedinstven")
    return nalaz
