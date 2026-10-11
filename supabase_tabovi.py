"""
CAKI — supabase_tabovi.py
=========================
Supabase kao "radni list" — da aplikacija ne zna gdje su podaci.

IDEA:
    Cijeli `pipeline_upisi.py` razgovara sa Sheetom kroz 19 metoda
    (`worksheet`, `get_all_records`, `update_cell`, `append_row`, `delete_rows`...).
    Ako napravimo objekt koji se ponaša ISTO, a podatke drži u Supabaseu, kod se
    ne mijenja — mijenja se samo otkud dolazi `sheet`.

ZASTO JEDNA GENERICKA TABLICA, A NE 25 TABLICA PO JEDNU ZA SVAKI TAB:
    Isti razlog kao u `uvoz/001_uvoz.sql`: zaglavlja su "ugovor" i kod ih čita
    po imenu. Da smo radili 25 tipiziranih tablica, svaki novi stupac u Sheetu
    zahtijevao bi migraciju, a kod bi pukao dok se migracija ne napravi.
    Ovako baza ne treba znati koje stupce tab ima — kao što ih ni danas ne zna.

BROJ RETKA (`_row`):
    Kod koristi broj retka kao identitet (`update_cell(7, 3, ...)`). U bazi broj
    retka nije stabilan, pa ga adapter GLUMI:
      - pri čitanju poreda retke i dodgeli im 2, 3, 4... i zapamti par;
      - pri pisanju pretvori taj broj natrag u (bucket, ordinal).
    Time je ponašanje identično Sheetu, a identitet u bazi ostaje stabilan.

POKRETANJE:
    Ovo nije skripta — ovo je modul. Koristi ga `podaci.py`.
"""

from __future__ import annotations

import json
from typing import Any

try:
    # Kod već hvata `gspread.exceptions.WorksheetNotFound`, pa adapter mora dizati
    # ISTU grešku — inače bi razlika između Sheeta i baze promijenila ponašanje.
    from gspread.exceptions import WorksheetNotFound as _WorksheetNotFound
except ImportError:                                   # pragma: no cover
    class _WorksheetNotFound(Exception):
        pass

# ---------------------------------------------------------------------------
#  SQL za tablice u koje adapter piše (vidi i supabase/migrations u repou)
# ---------------------------------------------------------------------------
SQL_TABLICE = """
-- Jedan redak = jedan redak nekog taba iz CRM-a (npr. jedan učenik).
-- `podaci` je JSON: naziv stupca -> vrijednost (sve kao tekst, kao u Sheetu).
create table if not exists crm.redak (
  tab        text    not null,
  bucket     integer not null default 0,   -- kad ordinal dosegne 1.000.000, ide novi bucket
  ordinal    integer not null,             -- broj retka unutar bucketa (1 = prvi podatak)
  podaci     jsonb   not null,
  azurirano  timestamptz not null default now(),
  primary key (tab, bucket, ordinal)
);

-- Zaglavlje taba: koji stupci i kojim redom (kod čita stupce po imenu)
create table if not exists crm.zaglavlje (
  tab       text    not null,
  pozicija  integer not null,
  stupac    text    not null,
  primary key (tab, pozicija)
);

-- Širina taba (koliko stupaca) — za `col_count` i `add_cols`
create table if not exists crm.sirina (
  tab    text    primary key,
  stupaca integer not null default 26
);

-- Brojač za `append_row`: koji je sljedeći slobodan ordinal
create table if not exists crm.brojac (
  tab     text    primary key,
  ordinal integer not null default 0
);

create index if not exists idx_redak_tab on crm.redak (tab, bucket, ordinal);
"""


class SupabaseWorksheet:
    """Radni list u Supabaseu — isti "oblik" kao gspread Worksheet.

    Namjerno ima iste metode i iste povratne vrijednosti kao gspread, jer ga
    `pipeline_upisi.py` ne razlikuje od pravog radnog lista.
    """

    #: koliko redaka odjednom čitamo iz baze (Supabase vraća najviše 1000)
    VELICINA_CITANJA = 1000

    def __init__(self, klijent: Any, tab: str, broj_stupaca: int = 26):
        self.klijent = klijent          # supabase klijent (ili lažni, u testovima)
        self.title = tab                # isto ime polja kao u gspreadu
        self._stupaca = int(broj_stupaca)
        self._mapa: dict[int, tuple[int, int]] = {}   # _row -> (bucket, ordinal)
        self._zaglavlje: list[str] = []
        self._ucitano = False

    # ------------------------------------------------------------------ čitanje
    def _ucitaj(self) -> None:
        """Učita zaglavlje i mapu redaka. Zove se jednom po radnom listu."""
        if self._ucitano:
            return
        zag = (self.klijent.table("zaglavlje").select("pozicija,stupac")
               .eq("tab", self.title).order("pozicija").execute().data) or []
        self._zaglavlje = [str(z["stupac"]) for z in zag]
        siri = (self.klijent.table("sirina").select("stupaca")
                .eq("tab", self.title).execute().data) or []
        if siri:
            self._stupaca = int(siri[0]["stupaca"])
        self._osvjezi_mapu()

    def _osvjezi_mapu(self) -> None:
        """Napuni mapu `_row` -> (bucket, ordinal): 2, 3, 4... kao u Sheetu."""
        self._mapa = {}
        redci = self._svi_retci()
        for i, r in enumerate(redci, start=2):     # 2 = prvi redak podataka (1 je zaglavlje)
            self._mapa[i] = (int(r["bucket"]), int(r["ordinal"]))

    def _svi_retci(self) -> list[dict]:
        """Svi reci taba, poredani — u dijelovima po 1000 (Supabase ograničenje)."""
        rez, od = [], 0
        while True:
            dio = (self.klijent.table("redak").select("bucket,ordinal,podaci")
                   .eq("tab", self.title).order("bucket").order("ordinal")
                   .range(od, od + self.VELICINA_CITANJA - 1).execute().data) or []
            rez.extend(dio)
            if len(dio) < self.VELICINA_CITANJA:
                return rez
            od += self.VELICINA_CITANJA

    def row_values(self, r: int) -> list:
        """Jedan redak kao lista vrijednosti (1 = zaglavlje).

        Prazne ćelije na KRAJU retka se odrezuju — isto kao gspread. Bez toga bi
        `_dodaj_red_po_nazivu` i slične funkcije vidjele više stupaca nego Sheet.
        """
        self._ucitaj()
        if r == 1:
            return _bez_praznog_kraja(list(self._zaglavlje))
        red = self._redak_po_broju(r)
        if red is None:
            return []
        return _bez_praznog_kraja([red.get(h, "") for h in self._zaglavlje])

    def col_values(self, c: int) -> list:
        """Jedan stupac kao lista (1 = zaglavlje, pa vrijednosti redaka)."""
        self._ucitaj()
        if c < 1 or c > len(self._zaglavlje):
            return []
        ime = self._zaglavlje[c - 1]
        izlaz = [ime]
        for r in self._svi_retci():
            izlaz.append((r.get("podaci") or {}).get(ime, ""))
        while izlaz and izlaz[-1] == "":
            izlaz.pop()
        return izlaz

    def get_all_values(self, **_) -> list[list]:
        """Cijeli tab kao lista redaka (prvi je zaglavlje)."""
        self._ucitaj()
        return [list(self._zaglavlje)] + [
            [(r.get("podaci") or {}).get(h, "") for h in self._zaglavlje] for r in self._svi_retci()
        ]

    def get_all_records(self, value_render_option: str | None = None, **_) -> list[dict]:
        """Svi reci kao rječnici {stupac: vrijednost} — glavni način čitanja u kodu.

        `value_render_option` se prima radi istog potpisa kao gspread; u bazi su
        vrijednosti već "neformatirane" (broj je broj), pa je ponašanje isto.
        """
        self._ucitaj()
        return [dict(r.get("podaci") or {}) for r in self._svi_retci()]

    def cell(self, r: int, c: int):
        """Jedna ćelija (gspread vraća objekt s .value)."""
        self._ucitaj()
        red = self._redak_po_broju(r) or {}
        ime = self._zaglavlje[c - 1] if 0 < c <= len(self._zaglavlje) else ""
        return _Celija(red.get(ime, ""))

    @property
    def col_count(self) -> int:
        self._ucitaj()
        return self._stupaca

    @property
    def row_count(self) -> int:
        self._ucitaj()
        return len(self._mapa) + 1

    # ------------------------------------------------------------------- pisanje
    def update_cell(self, r: int, c: int, vrijednost) -> None:
        """Promijeni jednu ćeliju — NAJVAŽNIJA operacija (svi *azuriraj* pozivi)."""
        self._ucitaj()
        if not (0 < c <= len(self._zaglavlje)):
            raise ValueError(f"[{self.title}] stupac {c} ne postoji (tab ima {len(self._zaglavlje)})")
        ime = self._zaglavlje[c - 1]
        self._zapisi(r, {ime: _tekst(vrijednost)})

    def update(self, values=None, range_name: str | None = None, **_) -> None:
        """Upis raspona (npr. zaglavlja u prvi redak ili cijelog stupca)."""
        self._ucitaj()
        if not values:
            return
        if range_name:
            redak, stupac = _iz_a1(range_name)
        else:
            redak, stupac = 1, 1
        if redak == 1:
            # upis u zaglavlje = dodavanje/izmjena naziva stupaca
            self._postavi_zaglavlje(values[0], od=stupac)
            return
        # upis vrijednosti u stupce
        for i, red_vrijednosti in enumerate(values):
            for j, v in enumerate(red_vrijednosti):
                self.update_cell(redak + i, stupac + j, v)

    def batch_update(self, data: list[dict], raw: bool = True, **_) -> None:
        for d in data or []:
            self.update(values=d.get("values"), range_name=d.get("range"))

    def add_cols(self, n: int) -> None:
        """Proširi tab za n stupaca (kod to zove prije dodavanja novog stupca)."""
        self._ucitaj()
        self._stupaca += int(n)
        self.klijent.table("sirina").upsert(
            {"tab": self.title, "stupaca": self._stupaca}).execute()

    def delete_rows(self, r: int) -> None:
        """Obriši redak. Ostali redci ZADRŽAVAJU svoje brojeve (u Sheetu bi se pomakli)."""
        self._ucitaj()
        bucket, ordinal = self._mapa.get(int(r), (None, None))
        if bucket is None:
            return
        (self.klijent.table("redak").delete()
         .eq("tab", self.title).eq("bucket", bucket).eq("ordinal", ordinal).execute())
        self._osvjezi_mapu()

    def append_row(self, values: list, value_input_option: str = "RAW", **_) -> None:
        self.append_rows([values], value_input_option)

    def append_rows(self, values: list[list], value_input_option: str = "RAW", **_) -> None:
        """Dodaj retke na kraj (kod zove `_dodaj_red_po_nazivu` i slično)."""
        self._ucitaj()
        if not values:
            return
        for red_vrijednosti in values:
            ordinal = self._sljedeci_ordinal()
            podaci = {h: _tekst(v) for h, v in zip(self._zaglavlje, red_vrijednosti)}
            # ako je redak dulji od zaglavlja, višak se čuva pod _visak_N (kao u uvozu)
            for i, v in enumerate(red_vrijednosti[len(self._zaglavlje):], start=1):
                podaci[f"_visak_{i}"] = _tekst(v)
            self.klijent.table("redak").insert(
                {"tab": self.title, "bucket": 0, "ordinal": ordinal, "podaci": podaci}).execute()
        self._osvjezi_mapu()

    # -------------------------------------------------------------------- pomoćno
    def _redak_po_broju(self, r: int) -> dict | None:
        par = self._mapa.get(int(r))
        if par is None:
            return None
        odgovor = (self.klijent.table("redak").select("podaci")
                   .eq("tab", self.title).eq("bucket", par[0]).eq("ordinal", par[1])
                   .execute().data) or []
        return (odgovor[0].get("podaci") or {}) if odgovor else None

    def _zapisi(self, r: int, izmjene: dict) -> None:
        """Spoji izmjene u JSON retka i upiši (jedan poziv, bez čitanja)."""
        par = self._mapa.get(int(r))
        if par is None:
            raise ValueError(f"[{self.title}] redak {r} ne postoji (tab ima {len(self._mapa)} redaka)")
        # Supabase ne zna "spoji JSON" preko REST-a, pa pročitamo pa upišemo.
        # Kod ažurira obično 1-3 polja; redak je mali, pa je ovo jeftino.
        trenutni = self._redak_po_broju(r) or {}
        trenutni.update(izmjene)
        (self.klijent.table("redak").update({"podaci": trenutni})
         .eq("tab", self.title).eq("bucket", par[0]).eq("ordinal", par[1]).execute())

    def _sljedeci_ordinal(self) -> int:
        """Sljedeći slobodan broj retka (`append_row`)."""
        redci = (self.klijent.table("brojac").select("ordinal")
                 .eq("tab", self.title).execute().data) or []
        sljedeci = (int(redci[0]["ordinal"]) if redci else 0) + 1
        self.klijent.table("brojac").upsert({"tab": self.title, "ordinal": sljedeci}).execute()
        return sljedeci

    def _postavi_zaglavlje(self, imena: list, od: int = 1) -> None:
        """Doda/izmijeni nazive stupaca (kod to zove kad uvodi novi stupac)."""
        for i, ime in enumerate(imena, start=od):
            self.klijent.table("zaglavlje").upsert(
                {"tab": self.title, "pozicija": i, "stupac": _tekst(ime)}).execute()
        self._ucitano = False
        self._ucitaj()


class _Celija:
    """Isto što gspread vraća za `ws.cell(r, c)` — samo `.value`."""

    def __init__(self, vrijednost):
        self.value = vrijednost


class SupabaseSpreadsheet:
    """Tablica (datoteka) u Supabaseu — isti oblik kao gspread Spreadsheet."""

    def __init__(self, klijent: Any, tabovi: list[str] | None = None, sirine: dict | None = None):
        self.klijent = klijent
        self._tabovi = list(tabovi or [])
        self._sirine = dict(sirine or {})
        self._kes: dict[str, SupabaseWorksheet] = {}

    def worksheet(self, title: str) -> SupabaseWorksheet:
        if title in self._kes:
            return self._kes[title]
        if self._tabovi and title not in self._tabovi:
            raise _NemaTaba(title)
        ws = SupabaseWorksheet(self.klijent, title, self._sirine.get(title, 26))
        self._kes[title] = ws
        return ws

    def worksheets(self) -> list[SupabaseWorksheet]:
        return [self.worksheet(t) for t in self._tabovi]

    def add_worksheet(self, title: str, rows: int = 100, cols: int = 26):
        """Novi tab. U bazi je "tab" samo naziv — tablica se ne kreira."""
        if title not in self._tabovi:
            self._tabovi.append(title)
        self._sirine[title] = int(cols)
        self.klijent.table("sirina").upsert({"tab": title, "stupaca": int(cols)}).execute()
        self._kes.pop(title, None)
        return self.worksheet(title)


class _NemaTaba(_WorksheetNotFound):
    """Tab ne postoji — ista greška koju diže gspread (`WorksheetNotFound`)."""


# ---------------------------------------------------------------------------
#  male pomoćne funkcije (testiraju se same, bez baze)
# ---------------------------------------------------------------------------

def _tekst(v) -> str:
    """Vrijednost u tekst — isto pravilo kao u Sheetu (sve je tekst)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Da" if v else "Ne"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _bez_praznog_kraja(vrijednosti: list) -> list:
    """Odreži prazne vrijednosti s kraja — gspread to radi sam."""
    izlaz = list(vrijednosti)
    while izlaz and (izlaz[-1] == "" or izlaz[-1] is None):
        izlaz.pop()
    return izlaz


def _iz_a1(oznaka: str) -> tuple[int, int]:
    """'B7' ili 'B7:C9' -> (7, 2). Prva ćelija raspona."""
    prva = str(oznaka).split(":")[0].strip()
    slova = "".join(z for z in prva if z.isalpha())
    brojevi = "".join(z for z in prva if z.isdigit())
    stupac = 0
    for z in slova.upper():
        stupac = stupac * 26 + (ord(z) - ord("A") + 1)
    return (int(brojevi) if brojevi else 1), (stupac if stupac else 1)


def zaglavlje_u_json(zaglavlja: list[str]) -> str:
    """Pomoćno za migracije: zaglavlje kao JSON (za upis u crm.zaglavlje)."""
    return json.dumps(list(zaglavlja), ensure_ascii=False)
