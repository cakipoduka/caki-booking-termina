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


def izracunaj_kljuc(red, tab: str) -> str:
    """Ključ jednog retka.

    Redoslijed:
      1. ako tab ima ključ u popisu -> vrijednost iz tog stupca (ili spoj stupaca);
      2. ako je ključ prazan, a redak je redak Rasporeda Matura -> "kanta:dan:termin:ucionica"
         (redak "kanta s profesorom" NAMJERNO nema redak_id — vidi
         `raspored_matura.retci_za_spremanje`; bez ovoga bi takav redak ostao bez identiteta);
      3. inače prazno — i to se broji u izvješću, ne prešućuje.
    """
    stupci = stupci_kljuca(tab)
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
        return df

    ima_kljuc = bool(stupci_kljuca(tab))
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
#  IZVJESTAJ — što je pronađeno, da se ništa ne izgubi tiho
# ============================================================================

def izvjestaj_kljuceva(df: pd.DataFrame, tab: str) -> dict:
    """Kratki nalaz za jedan tab: ima li ključ, koliko ih je jedinstvenih, koliko praznih."""
    if df is None or df.empty:
        return {"tab": tab, "redaka": 0, "kljuc": "/".join(stupci_kljuca(tab)) or "-",
                "praznih_kljuceva": 0, "duplih_kljuceva": 0, "jedinstvenih": 0}
    kljucevi = list(df.get("_kljuc", []))
    neprazni = [k for k in kljucevi if k]
    return {
        "tab": tab,
        "redaka": int(len(df)),
        "kljuc": "/".join(stupci_kljuca(tab)) or "-",
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
