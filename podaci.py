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


# ============================================================================
#  GDJE SU PODACI — prekidač (korak 3)
# ============================================================================
#  Do sada su svi podaci bili u Google Sheetu. Sada se može birati:
#
#      PODACI_BACKEND = "sheets"     # kako je bilo (zadano)
#      PODACI_BACKEND = "supabase"   # podaci iz baze
#
#  Prekidač se čita iz `st.secrets` (Streamlit → Settings → Secrets). Ako ga
#  nema ili je neispravan, koristi se "sheets" — da se aplikacija NIKAD ne
#  sruši zbog pogrešno upisane postavke, nego nastavi raditi kako je radila.
#
#  Povratak na Sheet: vrati "sheets" i rebootaj aplikaciju. Ništa se ne briše.
# ----------------------------------------------------------------------------
ZADANI_BACKEND = "sheets"
POZNATI_BACKENDOVI = ("sheets", "supabase")


def _tajne():
    """Streamlit postavke, ako ih ima (izvan aplikacije ih nema — npr. u testu)."""
    try:
        import streamlit as st
        return st.secrets
    except Exception:
        return {}


class NepoznatBackend(ValueError):
    """`PODACI_BACKEND` ima vrijednost koja nije poznata.

    Diže se NAMJERNO. Prije (10.10.2026.) se pogrešno upisana vrijednost tiho
    pretvarala u "sheets" — ali tada bi aplikacija, koja je trebala raditi na
    bazi, mirno nastavila pisati u Google Sheet i dvije bi se kopije razišle.
    Bolje je da aplikacija stane s jasnom uputom nego da radi pogrešnu stvar.
    """


def backend(secrets=None) -> str:
    """Koji backend je uključen: "sheets" ili "supabase".

    Nepoznata vrijednost (npr. "baza") NIJE dopuštena — diže se `NepoznatBackend`
    s uputom što upisati. Povratak na Sheet je jedna postavka: "sheets".
    """
    izvor = _tajne() if secrets is None else secrets
    try:
        vrijednost = str(izvor.get("PODACI_BACKEND", ZADANI_BACKEND) or ZADANI_BACKEND).strip().lower()
    except Exception:
        vrijednost = ZADANI_BACKEND
    if vrijednost not in POZNATI_BACKENDOVI:
        raise NepoznatBackend(
            f"PODACI_BACKEND = {vrijednost!r} nije poznat (dopušteno: "
            f"{', '.join(POZNATI_BACKENDOVI)}). Ispravi postavku u st.secrets i rebootaj. "
            f"Aplikacija namjerno NE bira ništa sama — pogrešan odabir znači da se "
            f"podaci pišu na dva mjesta."
        )
    return vrijednost


def je_supabase(secrets=None) -> bool:
    """Je li uključena baza."""
    return backend(secrets) == "supabase"


def tabovi_iz_baze(klijent, tabovi: list[str] | None = None, sirine: dict | None = None):
    """Vrati "radnu knjigu" koja se ponaša kao Google Sheet, a drži podatke u bazi.

    Koristi je `sheet()` u pipelineu — kod dalje ne zna odakle podaci dolaze.
    """
    import supabase_tabovi
    return supabase_tabovi.SupabaseSpreadsheet(klijent, tabovi, sirine)


# ============================================================================
#  HIBRID: koji tab ide u BAZU, a koji OSTAJE u Google Sheetu
# ============================================================================
#  ZASTO OVAJ SMJER ("u bazu samo dopusteno"):
#    Apps Script (mailovi, ponude, obracun instrukcija, PDV prag) i Google Forms
#    rade ISKLJUCIVO nad Sheetom. Kada bi sve preselilo u bazu, te bi skripte
#    nastavile raditi — ali nad podacima koji se vise ne mijenjaju, pa bi mailovi
#    isli na stare podatke, a ponude se sastavljale iz zastarjelih prijava.
#    Zato je sigurno da u bazu ide SAMO ono sto je ovdje izricito navedeno;
#    svaki novi tab ostaje u Sheetu dok se ne doda u skup. Time nijedan tab ne
#    promijeni mjesto slucajno.
#
#  POPIS JE IZVEDEN IZ KODA I SHEETA (11.10.2026.), ne napamet:
#    - imena su TOCNA imena tabova iz Google Sheeta (Provjereno: izvoz Sheeta i
#      `sheet.worksheet(...)` pozivi u kodu). Npr. `Biljeske` (bez kvacice) i
#      `Raspored_Matura_202627` (bez znaka /) — tako se zovu u Sheetu.
#    - skup u Sheetu = sve sto dira Apps Script ili Forms (14 tabova, vidi
#      `CAKI SUPABASE/05_CRM_PRIJELAZ/APPS_SCRIPT_TABOVI.md`) + `Dolasci` i
#      `Gostovanja` (cita ih CAKI_izostanci.gs).
# ----------------------------------------------------------------------------
PODACI_BACKEND_KLJUC = "PODACI_BACKEND"
TABOVI_U_BAZI_KLJUC = "PODACI_TABOVI_U_BAZI"
TABOVI_U_BAZI_SVE = "sve"

#: Tabovi koji IDU U BAZU. Popis se smije samo povecavati — kad se za neki tab
#: dokaže da ga Apps Script ne dira. Skup je NAMJERNO eksplicitan (vidi gore).
#:
#: `Backup_log` NIJE ovdje iako ga aplikacija ne koristi za pisanje: u njega piše
#: `CAKI_backup.gs` (`zapisBackupLog_`). Da je u bazi, aplikacija bi ga čitala iz
#: baze, a skripta pisala u Sheet — pa dnevnik backupa u CRM-u ne bi pokazivao
#: ništa. Ostaje u Sheetu (nalaz iz Dijela A2, 11.10.2026.).
TABOVI_U_BAZI: frozenset[str] = frozenset({
    "Grupe",
    "Termini",
    "Rezervacije",
    "Biljeske",
    "Nastavnici",
    "Zamjene log",
    "Dodjele",
    "Honorari",
    "Paketi_sati",
    "Razdoblja_termina",
    "Praznici",
    "Raspored_Matura_202627",
    "GDPR_log",
    "Izvjestaji_instruktora",
    "WhatsApp_predlosci",
})

#: Tabovi koji OSTAJU u Google Sheetu (Apps Script / Google Forms ih citaju ili pisu).
#: Vodi se radi citljivosti i provjere; tab koji nije u TABOVI_U_BAZI ionako ide u Sheet.
TABOVI_U_SHEETU: frozenset[str] = frozenset({
    "Mail_dnevnik",
    "Form responses 1",
    "Prijave",
    "Učenici",
    "Matura_postavke",
    "Uvoz_instrukcije",
    "Cjenik",
    "Racuni_i_ponude",
    "PDV_prag",
    "Mail_predlosci",
    "Backup_log",          # pise ga CAKI_backup.gs — vidi obrazlozenje gore
    "Instrukcije_termini",
    "Dolasci",
    "Gostovanja",
})


class PodaciBackendError(RuntimeError):
    """Podaci se ne mogu otvoriti onako kako je postavljeno.

    Diže se NAMJERNO (nikad tihi pad na drugi izvor): ako se trazi tab iz Sheeta,
    a veza sa Sheetom ne radi, aplikacija stane s uputom. Tihi povratak znacio bi
    da se dio dana pise u Sheet, a dio u bazu, pa se kopije raziđu.
    """


def svi_tabovi_u_bazi(secrets=None) -> bool:
    """Je li ukljuceno `PODACI_TABOVI_U_BAZI = "sve"` (samo za testni projekt)."""
    izvor = _tajne() if secrets is None else secrets
    try:
        vrijednost = str(izvor.get(TABOVI_U_BAZI_KLJUC, "") or "").strip().lower()
    except Exception:
        vrijednost = ""
    return vrijednost == TABOVI_U_BAZI_SVE


def tabovi_u_bazi(secrets=None) -> frozenset[str]:
    """Skup tabova koji idu u bazu.

    Uz `PODACI_TABOVI_U_BAZI = "sve"` vraca PRAZAN skup, a `izvor_taba` tada sve
    salje u bazu — tako se ne mora voditi drugi popis tabova.
    """
    if svi_tabovi_u_bazi(secrets):
        return frozenset()
    return TABOVI_U_BAZI


def izvor_taba(naziv: str, secrets=None) -> str:
    """Odakle se cita tab: "baza" ili "sheet".

    Pravilo: u bazu ide samo ono sto je u `TABOVI_U_BAZI`. Sve ostalo — ukljucujuci
    svaki novi, nepoznati tab — ostaje u Sheetu (sigurni zadani smjer).
    """
    if svi_tabovi_u_bazi(secrets):
        return "baza"
    return "baza" if str(naziv) in TABOVI_U_BAZI else "sheet"


class HibridnaKnjiga:
    """Radna knjiga koja dio tabova drzi u bazi, a dio u Google Sheetu.

    Ima isti oblik kao gspread Spreadsheet (i kao `SupabaseSpreadsheet`), pa je
    `pipeline_upisi.py` ne razlikuje od ostalih. Spajanje podataka iz oba izvora
    (npr. `Dolasci` iz Sheeta + `Grupe` iz baze preko `ucenik_id`) radi bez izmjena
    pozivajuceg koda — svaki `worksheet(naziv)` vrati ispravan izvor.

    Veza sa Sheetom otvara se LIJENO (`sheet_tvornik` se zove tek kad netko zatrzi
    tab iz Sheeta), da rad s bazom i testovi ne traze Google racun.
    """

    def __init__(self, baza_knjiga, sheet_tvornik, secrets=None):
        self.baza = baza_knjiga
        self._sheet_tvornik = sheet_tvornik          # funkcija bez argumenata
        self._sheet = None
        self._secrets = secrets

    # ------------------------------------------------------------------ izvor
    def _izvor(self, naziv: str) -> str:
        return izvor_taba(naziv, self._secrets)

    def _sheet_knjiga(self):
        """Otvori Sheet tek kad zatreba. Ako ne radi — glasna greska, ne tihi pad."""
        if self._sheet is None:
            if self._sheet_tvornik is None:
                raise PodaciBackendError(
                    "Trazi se tab iz Google Sheeta, ali veza sa Sheetom nije "
                    "postavljena. Provjeri GOOGLE_SERVICE_ACCOUNT_JSON i SHEET_ID "
                    "u postavkama (Streamlit → Settings → Secrets)."
                )
            try:
                self._sheet = self._sheet_tvornik()
            except Exception as e:
                raise PodaciBackendError(
                    f"Trazi se tab iz Google Sheeta, ali veza ne radi "
                    f"({type(e).__name__}: {e}). Provjeri GOOGLE_SERVICE_ACCOUNT_JSON "
                    f"i SHEET_ID. Ako zelis raditi samo na bazi, postavi "
                    f"{TABOVI_U_BAZI_KLJUC} = \"{TABOVI_U_BAZI_SVE}\" (samo testni projekt)."
                ) from None
        return self._sheet

    # --------------------------------------------------------------- sucelje
    def worksheet(self, title: str):
        if self._izvor(title) == "baza":
            return self.baza.worksheet(title)
        return self._sheet_knjiga().worksheet(title)

    def worksheets(self) -> list:
        """Tabovi iz oba izvora — ali SVAKI po pravilu izvora, bez duplikata.

        Vazno (ispravka 11.10.2026., zadatak 01b): tab se uzima iz onog izvora u
        koji ga `izvor_taba()` salje. Ako u bazi zaostane tab koji pripada Sheetu
        (npr. nakon probnog prijenosa), prije bi `worksheets()` vratio objekt iz
        BAZE, a `worksheet(naziv)` objekt iz SHEETA — dvije razlicite istine za
        isti naziv. Sada su oba puta usklađena.
        """
        iz_baze = [ws for ws in self.baza.worksheets()
                   if self._izvor(getattr(ws, "title", "")) == "baza"]
        iz_sheeta = [ws for ws in self._sheet_knjiga().worksheets()
                     if self._izvor(getattr(ws, "title", "")) == "sheet"]
        return iz_baze + iz_sheeta

    def add_worksheet(self, title: str, rows: int = 100, cols: int = 26):
        if self._izvor(title) == "baza":
            return self.baza.add_worksheet(title, rows, cols)
        return self._sheet_knjiga().add_worksheet(title, rows, cols)


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
