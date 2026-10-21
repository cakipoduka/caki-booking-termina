"""
CAKI — komentar_napretka.py  (21.10.2026.)
Osvrt profesora roditelju: IZ PODATAKA KOJI SU VEĆ UPISANI sastavi kratku, konkretnu poruku o napretku
učenika, profesor je pregleda i pošalje u Moj CAKI.

Ideja (Cakijeva odluka 21.10.2026., v. `upute/PREDLOG_21-10_napredak_bloom_ai.md`):
  1. PODACI    — sati, zadaća, testovi. Profesor ih ne tipka; već su u `Instrukcije_termini` i `Rezultati_testova`.
  2. FRAZE     — profesor bira 3–5 gotovih rečenica klikom (baza `Fraze_komentara`), tekst se sastavi odmah.
  3. AI        — NIJE ovdje. Dolazi kasnije kao gumb NA OVE fraze; ovaj modul radi bez ijednog API poziva.

ISTA datoteka u caki-evidencija-dolazaka (profesor piše), caki-booking-termina (Moj CAKI prikazuje) i
caki-upisi-crm-main (admin uređuje fraze). Namjerna kopija iste male logike — cross-repo import ne radi na
Streamlit Cloudu (isti razlog kao `sat_biljeska.py` i `obavijesti.py`). Ako se ovo promijeni, mijenja se u
sva tri repoa.

Privatnost (najvažnije pravilo modula):
  - U poruku i u karticu ulaze SAMO `napomena_javna`, `teme`, `zadaca_*` i rezultati testova.
  - `napomena_interna` i `ocjena_sata` (interno ➕/➖) se NIKAD ne čitaju — roditelj ih ne vidi.
  - Plaćanja, dugovi i honorari se ne diraju.

Tabovi (stvaraju se sami pri prvom spremanju; `osiguraj_tabove()` ih postavlja i puni frazama):
  Fraze_komentara  fraza_id, kategorija, smjer, ton, tekst, primjereno_za, aktivan, autor, datum, puta_koristena
  Napredak_poruke  poruka_id, datum, ucenik_id, ime_djeteta, nastavnik, predmet, program, razdoblje_od,
                   razdoblje_do, tekst, fraze, izvor, model, poslano, procitano

Stupac `Učenici.rod` (M/Ž) nije obavezan; bez njega rečenice koriste muški oblik (`{a}` → "").
"""
from __future__ import annotations

import random
import re
import string
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ZAGREB = ZoneInfo("Europe/Zagreb")

FRAZE_TAB = "Fraze_komentara"
PORUKE_TAB = "Napredak_poruke"
UCENICI_TAB = "Učenici"

FRAZE_HEADERS = ["fraza_id", "kategorija", "smjer", "ton", "tekst", "primjereno_za", "aktivan", "autor",
                 "datum", "puta_koristena"]
PORUKE_HEADERS = ["poruka_id", "datum", "ucenik_id", "ime_djeteta", "nastavnik", "predmet", "program",
                  "razdoblje_od", "razdoblje_do", "tekst", "fraze", "izvor", "model", "poslano", "procitano"]

# --- kategorije fraza -------------------------------------------------------------------------
OTVARANJE = "OTVARANJE"
ZAVRSETAK = "ZAVRSETAK"
DOBRO = "DOBRO"
ZAPELO = "ZAPELO"
CILJ = "CILJ"
KOD_KUCE = "KOD_KUCE"
TESKO = "TESKO"

# Redoslijed kategorija u sastavljenoj poruci (jedan odlomak = jedna skupina).
REDOSLIJED = [OTVARANJE, DOBRO, ZAPELO, CILJ, KOD_KUCE, ZAVRSETAK]

# Što ulazi u koji odlomak.
ODLOMCI = [
    [OTVARANJE, DOBRO],
    [ZAPELO, CILJ],
    [KOD_KUCE, ZAVRSETAK],
]

TONOVI = ["Toplo", "Neutralno", "Izravno"]
DULJINE = {"kratko": "Kratko (3–4 rečenice)", "srednje": "Srednje (2 odlomka)", "detaljno": "Detaljnije (3 odlomka)"}

# Dimenzije (drugi dio oznake kategorije) — jedan popis za profesorski portal i za admin.
DIMENZIJE_DOBRO = ["NAPREDAK", "ZALAGANJE", "RAZUMIJEVANJE", "SAMOSTALNOST", "TEMPO"]
DIMENZIJE_ZAPELO = ["PRIMJENA", "ZADACA", "PRISUTNOST", "TEMPO", "SAMOSTALNOST", "PAZNJA"]
SVE_KATEGORIJE = ([OTVARANJE, DOBRO] + [DOBRO + ":" + d for d in DIMENZIJE_DOBRO]
                  + [ZAPELO] + [ZAPELO + ":" + d for d in DIMENZIJE_ZAPELO]
                  + [TESKO, CILJ, KOD_KUCE, ZAVRSETAK])
SMJEROVI = ["Pohvala", "Rast", "Rizik", "Okvir"]

# Statusi termina koji NISU održani sat (isto kao sat_biljeska.STATUSI_BEZ_SATA).
STATUSI_BEZ_SATA = ("Otkazan na vrijeme", "Otkazan kasno", "Nije došao", "Zakazan")
STATUSI_PROPUSTENO = ("Otkazan na vrijeme", "Otkazan kasno", "Nije došao")

MAX_TEKST = 2000
MAX_KRATKO = 1200          # iznad ovoga poruka je preduga za roditelja → upozorenje (ne blokada)
MAX_FRAZA = 400
MIN_SMISLENO = 80          # kraće od ovoga nije poruka

# Riječi koje ne smiju ući u poruku roditelju (etikete i obećanja) — upozorenje, ne blokada.
# Kratki korijeni namjerno: "lijen" pokriva lijen/lijena/lijeno, "nesposob" sve oblike.
ETIKETE = ["lijen", "nesposob", "glup", "beznad", "lenj", "slab intelekt"]
ETIKETE_FRAZE = ["nema šanse", "nikad neće", "ne može naučiti", "nije za školu"]
OBECANJA = ["sigurno će", "sigurno ćete", "jamčim", "garantir", "garantiram", "sigurno položi",
            "sto posto", "100 % prolaz"]
MEDICINSKI = ["adhd", "disleksij", "disgrafij", "terapeut", "psiholog", "dijagnoz", "lijek", "medikament"]

MJESECI = ["siječanj", "veljača", "ožujak", "travanj", "svibanj", "lipanj", "srpanj", "kolovoz",
           "rujan", "listopad", "studeni", "prosinac"]
# Lokativ („u listopadu”) — hrvatski traži padež, pa fraza ne može glasiti „u {razdoblje}”.
MJESECI_LOKATIV = ["siječnju", "veljači", "ožujku", "travnju", "svibnju", "lipnju", "srpnju", "kolovozu",
                   "rujnu", "listopadu", "studenom", "prosincu"]


# ============================================================================================
# Pomoćno
# ============================================================================================

def sada() -> datetime:
    return datetime.now(ZAGREB).replace(tzinfo=None)


def _t(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def novi_id() -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=10))


def datum_iz(v):
    """'2026-10-03' / '03.10.2026.' / date / datetime -> date ili None."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = _t(v)[:10]
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def _broj(v, zadano: float = 0.0) -> float:
    try:
        return float(_t(v).replace(",", "."))
    except (TypeError, ValueError):
        return zadano


def _cijeli(v, zadano: int = 0) -> int:
    b = _broj(v, zadano)
    return int(round(b))


def _da(v) -> bool:
    return _t(v).lower() in ("da", "true", "1", "yes")


def tekst_razdoblja(od, do) -> str:
    """(1.10., 21.10.) -> 'listopad 2026.'; preko mjeseca -> '01.10.–21.10.2026.'.
    Ovo je NASLOV (može stajati sam). U rečenici se koristi `tekst_razdoblja_u()` (padež)."""
    od, do = datum_iz(od), datum_iz(do)
    if od is None and do is None:
        return "dosadašnji rad"
    if od is None:
        od = do
    if do is None:
        do = od
    if (od.year, od.month) == (do.year, do.month):
        return f"{MJESECI[od.month - 1]} {od.year}."
    if od.year == do.year:
        return f"{od.day:02d}.{od.month:02d}.–{do.day:02d}.{do.month:02d}.{do.year}."
    return f"{od.strftime('%d.%m.%Y.')}–{do.strftime('%d.%m.%Y.')}"


def tekst_razdoblja_u(od, do) -> str:
    """Isto, ali u padežu za rečenicu: 'u listopadu 2026.' / 'u razdoblju 20.09.–21.10.2026.'."""
    od, do = datum_iz(od), datum_iz(do)
    if od is None and do is None:
        return "u dosadašnjem radu"
    if od is None:
        od = do
    if do is None:
        do = od
    if (od.year, od.month) == (do.year, do.month):
        return f"u {MJESECI_LOKATIV[od.month - 1]} {od.year}."
    return f"u razdoblju {tekst_razdoblja(od, do)}"


# ============================================================================================
# Baza fraza
# ============================================================================================

# Gotove fraze koje se same upišu u Sheet pri prvom postavljanju tabova. Nakon toga se uređuju
# u adminu (📣 Obavijesti → 🧩 Fraze za osvrt) — ova lista služi samo kao početno stanje i kao
# rezerva dok tab još ne postoji (portal tako radi odmah, bez čekanja na admina).
_F = lambda i, k, s, t, x, p="SVI": {"fraza_id": i, "kategorija": k, "smjer": s, "ton": t, "tekst": x,
                                     "primjereno_za": p, "aktivan": "Da", "autor": "CAKI",
                                     "puta_koristena": "0"}

ZADANE_FRAZE = [
    # --- otvaranje -------------------------------------------------------------------------
    # PRAVILO ZA PISANJE FRAZA: ime se NIKAD ne sklanja. `{ime}` smije stajati samo u nominativu
    # ("{ime} redovito dolazi", "kako {ime} stoji"), nikad kao "s {ime}", "napredak {ime}" i sl.
    # Sklanjanje hrvatskih imena ne može se automatizirati, a pogrešan padež se odmah primijeti.
    _F("OTV-01", OTVARANJE, "Okvir", "Neutralno", "Poštovani, evo kratkog osvrta na {razdoblje}."),
    _F("OTV-02", OTVARANJE, "Okvir", "Neutralno", "Poštovani, javljam se s kratkim osvrtom na {razdoblje}."),
    _F("OTV-03", OTVARANJE, "Okvir", "Neutralno", "Poštovani, evo kako {ime} stoji {u_razdoblju}."),
    _F("OTV-04", OTVARANJE, "Okvir", "Izravno", "Poštovani, ukratko o napretku {u_razdoblju}."),
    _F("OTV-05", OTVARANJE, "Okvir", "Toplo", "Poštovani, drago mi je javiti se s osvrtom na {razdoblje}."),
    _F("OTV-06", OTVARANJE, "Okvir", "Neutralno", "Poštovani, kratki osvrt na {razdoblje} — {predmet}."),

    # --- dobro: napredak (s brojkama) ------------------------------------------------------
    _F("DOB-NAP-01", DOBRO + ":NAPREDAK", "Rast", "Neutralno",
       "Na testovima je {prvi} % → {zadnji} %, što je napredak od {razlika} postotnih bodova {u_razdoblju}."),
    _F("DOB-NAP-02", DOBRO + ":NAPREDAK", "Rast", "Neutralno",
       "Rezultati su {u_razdoblju} porasli s {prvi} % na {zadnji} % — to je {razlika} postotnih bodova više."),
    _F("DOB-NAP-03", DOBRO + ":NAPREDAK", "Rast", "Neutralno",
       "Napredak je vidljiv: s {prvi} % na {zadnji} % {u_razdoblju}."),
    _F("DOB-NAP-04", DOBRO + ":NAPREDAK", "Rast", "Neutralno",
       "Kad se usporede prvi i zadnji test {u_razdoblju}, vidi se pomak s {prvi} % na {zadnji} %."),
    _F("DOB-NAP-05", DOBRO + ":NAPREDAK", "Rast", "Toplo",
       "Najviše me veseli pomak na testovima — s {prvi} % na {zadnji} %."),

    # --- dobro: zalaganje -----------------------------------------------------------------
    _F("DOB-ZAL-01", DOBRO + ":ZALAGANJE", "Pohvala", "Toplo",
       "{ime} redovito dolazi i na svakom satu ima pitanja — to je najbolji znak da prati."),
    _F("DOB-ZAL-02", DOBRO + ":ZALAGANJE", "Pohvala", "Neutralno",
       "Na satu je koncentriran{a} i samostalno kreće u zadatak."),
    _F("DOB-ZAL-03", DOBRO + ":ZALAGANJE", "Pohvala", "Toplo",
       "{ime} ne odustaje kad zadatak ne ide iz prve — pokušava ponovno."),
    _F("DOB-ZAL-04", DOBRO + ":ZALAGANJE", "Pohvala", "Neutralno",
       "Domaće zadaće su uredno napravljene; vidi se da se kod kuće radi."),
    _F("DOB-ZAL-05", DOBRO + ":ZALAGANJE", "Pohvala", "Toplo",
       "Lijepo je vidjeti kako {ime} sve češće pita „zašto” — to je znak da razmišlja, a ne prepisuje."),

    # --- dobro: razumijevanje -------------------------------------------------------------
    _F("DOB-RAZ-01", DOBRO + ":RAZUMIJEVANJE", "Pohvala", "Neutralno",
       "Teme koje smo obradili na satu {ime} uspijeva objasniti svojim riječima."),
    _F("DOB-RAZ-02", DOBRO + ":RAZUMIJEVANJE", "Pohvala", "Neutralno",
       "Vidi se da gradivo prati s razumijevanjem, a ne pamćenjem napamet."),

    # --- dobro: samostalnost / tempo ------------------------------------------------------
    _F("DOB-SAM-01", DOBRO + ":SAMOSTALNOST", "Pohvala", "Neutralno",
       "{ime} samostalno započinje zadatak i ne treba mu potvrda prije svakog koraka."),
    _F("DOB-SAM-02", DOBRO + ":TEMPO", "Pohvala", "Neutralno",
       "Tempo je dobar — zadatke stigne napraviti u predviđenom vremenu."),

    # --- zapelo: zadaća -------------------------------------------------------------------
    _F("ZAP-ZAD-01", ZAPELO + ":ZADACA", "Rizik", "Neutralno",
       "Zadaća {u_razdoblju} nije bila napravljena {ne_zaredom} puta zaredom."),
    _F("ZAP-ZAD-02", ZAPELO + ":ZADACA", "Rizik", "Neutralno",
       "Zadaće su napravljene {napravljeno} od {zadano} puta — na tome bismo trebali poraditi."),
    _F("ZAP-ZAD-03", ZAPELO + ":ZADACA", "Rizik", "Izravno",
       "Zadaća se često ostavlja za zadnji tren, pa se na satu vidi da gradivo nije utvrđeno."),

    # --- zapelo: prisutnost ---------------------------------------------------------------
    _F("ZAP-PRI-01", ZAPELO + ":PRISUTNOST", "Rizik", "Neutralno",
       "Propušteno je {propusteno} od {ukupno_sati} sati {u_razdoblju}."),
    _F("ZAP-PRI-02", ZAPELO + ":PRISUTNOST", "Rizik", "Neutralno",
       "Zbog propuštenih sati nekoliko se tema nije stiglo utvrditi."),
    _F("ZAP-PRI-03", ZAPELO + ":PRISUTNOST", "Rizik", "Izravno",
       "Kad se sat propusti, sljedeći put krećemo ispočetka — zato je redovitost sada najvažnija."),

    # --- zapelo: primjena (najčešći slučaj u matematici) -----------------------------------
    _F("ZAP-PRIM-01", ZAPELO + ":PRIMJENA", "Rizik", "Neutralno",
       "Formule zna, ali ih još ne prenosi na zadatak — kad brojevi nisu isti kao u primjeru, zastane."),
    _F("ZAP-PRIM-02", ZAPELO + ":PRIMJENA", "Rizik", "Neutralno",
       "Postupak nauči na primjeru, a samostalno ga još ne ponavlja na novom zadatku."),
    _F("ZAP-PRIM-03", ZAPELO + ":PRIMJENA", "Rast", "Neutralno",
       "Osnove su tu; sljedeći je korak samostalna primjena na zadatak drugačijeg oblika."),

    # --- zapelo: tempo / samostalnost / pažnja --------------------------------------------
    _F("ZAP-TEM-01", ZAPELO + ":TEMPO", "Rizik", "Neutralno",
       "Radi pažljivo, ali sporo — na testu često ostane zadataka koje ne stigne ni pročitati."),
    _F("ZAP-TEM-02", ZAPELO + ":TEMPO", "Rizik", "Neutralno",
       "Tempo je dobar na poznatim zadacima, a pada čim se promijeni formulacija."),
    _F("ZAP-SAM-01", ZAPELO + ":SAMOSTALNOST", "Rizik", "Neutralno",
       "Zadatke koje smo radili zajedno rješava sigurno; samostalno još traži potvrdu je li točno."),
    _F("ZAP-SAM-02", ZAPELO + ":SAMOSTALNOST", "Rizik", "Neutralno",
       "Lako odustane kad ne ide iz prve i tada traži pomoć — na tome radimo."),
    _F("ZAP-PAZ-01", ZAPELO + ":PAZNJA", "Rizik", "Neutralno",
       "Greške su najčešće zbog nepažnje pri prijepisu, a ne zbog nerazumijevanja."),
    _F("ZAP-PAZ-02", ZAPELO + ":PAZNJA", "Rizik", "Neutralno",
       "Zadatak točno postavi, ali u zadnjem koraku izgubi znak ili jedinicu."),

    # --- teške situacije ------------------------------------------------------------------
    _F("TES-01", TESKO, "Rizik", "Izravno",
       "Iskren ću biti: bez redovitog rada kod kuće teško ćemo napredovati, pa je ovo trenutak za dogovor."),
    _F("TES-02", TESKO, "Rizik", "Toplo",
       "Znam da je raspored gust. Ako uspijemo naći dva kratka termina tjedno, razlika će se vidjeti."),
    _F("TES-03", TESKO, "Rizik", "Neutralno",
       "Ovaj put nije bilo napretka, ali to se događa — važno je da zajedno nađemo što je zapelo."),
    _F("TES-04", TESKO, "Rizik", "Toplo",
       "Razgovarat ćemo o tome što bi pomoglo; ako kod kuće ima nešto što ne znamo, slobodno mi javite."),

    # --- cilj -----------------------------------------------------------------------------
    _F("CIL-01", CILJ, "Rast", "Neutralno", "Cilj do sljedećeg osvrta: {cilj}."),
    _F("CIL-02", CILJ, "Rast", "Neutralno", "Dogovorili smo da ćemo u sljedećem razdoblju raditi na tome da {cilj}."),
    _F("CIL-03", CILJ, "Rast", "Neutralno", "Sljedeći korak je {cilj}."),
    _F("CIL-04", CILJ, "Rast", "Neutralno", "Do sljedećeg razgovora želio bih da {ime} {cilj}."),
    _F("CIL-05", CILJ, "Rast", "Neutralno", "Konkretan cilj za sljedećih mjesec dana: {cilj}."),
    _F("CIL-06", CILJ, "Rast", "Neutralno", "Na sljedećim satovima fokus je na tome da {ime} {cilj}."),

    # --- kod kuće -------------------------------------------------------------------------
    _F("KU-01", KOD_KUCE, "Rast", "Toplo", "Kod kuće bi najviše pomoglo 10 minuta dnevno — {cilj}."),
    _F("KU-02", KOD_KUCE, "Rast", "Neutralno",
       "Ne treba više sati; dovoljno je da se svaki dan kratko ponovi jedno gradivo."),
    _F("KU-03", KOD_KUCE, "Rast", "Neutralno",
       "Ako {ime} zapne, bolje je pitati „gdje si stao” nego odmah pokazati rješenje."),
    _F("KU-04", KOD_KUCE, "Rast", "Neutralno",
       "Najkorisnije je da se zadaća radi u isto vrijeme svaki dan, bez telefona u blizini."),
    _F("KU-05", KOD_KUCE, "Rast", "Toplo",
       "Podrška koja najviše pomaže: pitati što se radilo na satu i pustiti da to prepriča."),
    _F("KU-06", KOD_KUCE, "Rast", "Neutralno",
       "Za vježbu je dovoljna jedna stranica zadataka dnevno, ali svaki dan."),

    # --- završetak ------------------------------------------------------------------------
    _F("ZAV-01", ZAVRSETAK, "Okvir", "Neutralno", "Javljam se ponovno za {tjedana} tjedna."),
    _F("ZAV-02", ZAVRSETAK, "Okvir", "Neutralno", "Za pitanja sam vam na raspolaganju preko centra."),
    _F("ZAV-03", ZAVRSETAK, "Okvir", "Toplo", "Slobodno mi se javite ako se kod kuće nešto promijeni."),
    _F("ZAV-04", ZAVRSETAK, "Okvir", "Toplo", "Hvala na podršci koju dajete kod kuće."),
    _F("ZAV-05", ZAVRSETAK, "Okvir", "Neutralno",
       "Javljam se ponovno za {tjedana} tjedna, a do tada sam dostupan preko centra."),
]


def _osiguraj_tab(sheet, naziv: str, headers):
    """(ws, stvarno zaglavlje). Stvara tab ako ne postoji; dopisuje stupce koji nedostaju."""
    import gspread
    headers = list(headers)
    try:
        ws = sheet.worksheet(naziv)
    except (gspread.exceptions.WorksheetNotFound, KeyError):
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


def osiguraj_stupac_rod(sheet) -> bool:
    """Doda stupac `rod` (M/Ž) na tab Učenici. True = dodano, False = već postoji."""
    from pipeline_upisi import _osiguraj_tab_stupce
    return _osiguraj_tab_stupce(sheet, UCENICI_TAB, ["rod"])


def osiguraj_tabove(sheet) -> list:
    """Postavi tabove Fraze_komentara i Napredak_poruke i upiše zadane fraze ako je tab prazan.
    Vraća popis promjena (za poruku u adminu). Sigurno kliknuti više puta."""
    promjene = []
    ws_f, zagl_f = _osiguraj_tab(sheet, FRAZE_TAB, FRAZE_HEADERS)
    if not ws_f.get_all_values()[1:]:
        ws_f.append_rows([[str(f.get(h, "")) for h in zagl_f] for f in ZADANE_FRAZE], value_input_option="RAW")
        promjene.append(f"{FRAZE_TAB} — upisano {len(ZADANE_FRAZE)} zadanih fraza")
    _osiguraj_tab(sheet, PORUKE_TAB, PORUKE_HEADERS)
    promjene.append(PORUKE_TAB)
    return promjene


def ucitaj_fraze(sheet) -> list:
    """Sve fraze iz taba; ako tab ne postoji ili je prazan → ZADANE_FRAZE (portal radi odmah)."""
    try:
        ws = sheet.worksheet(FRAZE_TAB)
    except Exception:  # noqa: BLE001 — tab još ne postoji / Google zapne
        return [dict(f) for f in ZADANE_FRAZE]
    try:
        zapisi = ws.get_all_records()
    except Exception:  # noqa: BLE001
        return [dict(f) for f in ZADANE_FRAZE]
    if not zapisi:
        return [dict(f) for f in ZADANE_FRAZE]
    izlaz = []
    for r in zapisi:
        f = {h: _t(r.get(h)) for h in FRAZE_HEADERS}
        if not f["fraza_id"] or not f["tekst"]:
            continue
        izlaz.append(f)
    return izlaz or [dict(f) for f in ZADANE_FRAZE]


def fraze_za_prikaz(sheet) -> list:
    """Samo aktivne fraze, uredno sortirane po kategoriji i rednom broju u oznaci."""
    return sorted([f for f in ucitaj_fraze(sheet) if _da(f.get("aktivan", "Da"))],
                  key=lambda f: (f["kategorija"], f["fraza_id"]))


def _kandidati(fraze, kategorije, ton="", primjereno=(), iskljucene=()) -> list:
    """Fraze iz zadanih kategorija, po mogućnosti istog tona; najmanje korištene prve."""
    kat = [str(k) for k in kategorije]
    baza = [f for f in fraze
            if str(f.get("kategorija", "")) in kat and f["fraza_id"] not in set(iskljucene or ())]
    if not baza:
        return []
    if primjereno:
        ok = [f for f in baza if _t(f.get("primjereno_za", "SVI")).upper() in ("SVI", *[str(p).upper() for p in primjereno])]
        baza = ok or baza
    if ton:
        ok = [f for f in baza if _t(f.get("ton")) == ton]
        baza = ok or baza
    return sorted(baza, key=lambda f: (_cijeli(f.get("puta_koristena")), f["fraza_id"]))


def polja_teksta(tekst) -> list:
    return sorted(set(_POLJA.findall(str(tekst or ""))))


def nepoznata_polja(tekst) -> list:
    """Polja koja modul ne zna popuniti (tipfeler u frazi). Takva se fraza nikad ne bi poslala —
    zato admin dobije upozorenje odmah pri spremanju, a ne profesor pred roditeljem."""
    sva = re.findall(r"\{([a-zA-Z_]+)\}", str(tekst or ""))
    return sorted({x for x in sva if x not in _VRIJEDNOSTI})


DIM_PREFIKS = {"NAPREDAK": "NAP", "ZALAGANJE": "ZAL", "RAZUMIJEVANJE": "RAZ", "SAMOSTALNOST": "SAM",
               "TEMPO": "TEM", "ZADACA": "ZAD", "PRISUTNOST": "PRI", "PRIMJENA": "PRIM", "PAZNJA": "PAZ"}
KRATKE_KATEGORIJE = {"OTVARANJE": "OTV", "ZAVRSETAK": "ZAV", "CILJ": "CIL", "KOD_KUCE": "KU", "TESKO": "TES"}


def novi_fraza_id(fraze, kategorija: str) -> str:
    """Sljedeća slobodna oznaka u kategoriji (npr. DOB-ZAL-06) ili FRA-<nasumično>."""
    k = str(kategorija or "")
    if k in KRATKE_KATEGORIJE:
        prefiks = KRATKE_KATEGORIJE[k]
    elif ":" in k:
        osnova, dim = k.split(":", 1)
        prefiks = ("DOB-" if osnova == DOBRO else "ZAP-") + DIM_PREFIKS.get(dim, dim[:3])
    else:
        return f"FRA-{novi_id()[:5].upper()}"
    postojece = [f["fraza_id"] for f in fraze or () if str(f.get("fraza_id", "")).startswith(prefiks + "-")]
    brojevi = [_cijeli(str(x).rsplit("-", 1)[-1], 0) for x in postojece]
    return f"{prefiks}-{(max(brojevi) + 1 if brojevi else 1):02d}"


def _slobodna_oznaka(fraze, zeljena: str) -> str:
    postojece = {f["fraza_id"] for f in fraze or ()}
    return zeljena if zeljena not in postojece else f"{zeljena}-{novi_id()[:4].upper()}"


def dodaj_frazu(sheet, kategorija: str, tekst: str, ton: str = "Neutralno", smjer: str = "Okvir",
                primjereno_za: str = "SVI", autor: str = "CAKI", fraze=None) -> str:
    """Nova fraza u bazu. Vraća fraza_id; baca ValueError za prazan tekst ili nepoznato polje."""
    tekst = re.sub(r"\s+", " ", str(tekst or "")).strip()
    if not tekst:
        raise ValueError("Upiši tekst fraze.")
    if len(tekst) > MAX_FRAZA:
        raise ValueError(f"Fraza je predugačka (najviše {MAX_FRAZA} znakova).")
    lose = nepoznata_polja(tekst)
    if lose:
        raise ValueError("Nepoznato polje u frazi: " + ", ".join("{" + x + "}" for x in lose) +
                         ". Dopušteno je: " + ", ".join("{" + x + "}" for x in _VRIJEDNOSTI) + ".")
    fraze = ucitaj_fraze(sheet) if fraze is None else fraze
    fid = _slobodna_oznaka(fraze, novi_fraza_id(fraze, kategorija))
    ws, zagl = _osiguraj_tab(sheet, FRAZE_TAB, FRAZE_HEADERS)
    polja = {"fraza_id": fid, "kategorija": kategorija, "smjer": smjer, "ton": ton, "tekst": tekst,
             "primjereno_za": primjereno_za, "aktivan": "Da", "autor": autor,
             "datum": sada().strftime("%Y-%m-%d"), "puta_koristena": "0"}
    ws.append_row([str(polja.get(h, "")) for h in zagl], value_input_option="RAW")
    return fid


def uredi_frazu(sheet, fraza_id: str, polja: dict) -> None:
    """Izmijeni frazu (tekst / ton / aktivan / primjereno_za). Ostalo se ne dira."""
    dopusteno = {"tekst", "ton", "aktivan", "primjereno_za", "smjer"}
    izmjene = {k: v for k, v in (polja or {}).items() if k in dopusteno}
    if "tekst" in izmjene:
        izmjene["tekst"] = re.sub(r"\s+", " ", str(izmjene["tekst"] or "")).strip()
        if not izmjene["tekst"]:
            raise ValueError("Tekst fraze ne smije biti prazan.")
        lose = nepoznata_polja(izmjene["tekst"])
        if lose:
            raise ValueError("Nepoznato polje u frazi: " + ", ".join("{" + x + "}" for x in lose) + ".")
    if not izmjene:
        return
    ws, zagl = _osiguraj_tab(sheet, FRAZE_TAB, FRAZE_HEADERS)
    import gspread
    ii = zagl.index("fraza_id") + 1
    for i, r in enumerate(ws.get_all_values()[1:], start=2):
        if (r[ii - 1] if len(r) >= ii else "") == fraza_id:
            ws.batch_update([{"range": gspread.utils.rowcol_to_a1(i, zagl.index(k) + 1), "values": [[str(v)]]}
                             for k, v in izmjene.items() if k in zagl], raw=True)
            return
    raise ValueError("Fraza nije pronađena — osvježi stranicu.")


def ucitaj_poruke(sheet):
    """Sve poruke iz Napredak_poruke (DataFrame). Prazan okvir ako tab ne postoji."""
    import pandas as pd
    try:
        ws = sheet.worksheet(PORUKE_TAB)
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=PORUKE_HEADERS + ["_row"])
    zapisi = ws.get_all_records()
    if not zapisi:
        return pd.DataFrame(columns=PORUKE_HEADERS + ["_row"])
    df = pd.DataFrame(zapisi)
    for h in PORUKE_HEADERS:
        if h not in df.columns:
            df[h] = ""
        df[h] = df[h].astype(str).replace({"nan": "", "None": ""})
    df["_row"] = range(2, len(df) + 2)
    return df


# ============================================================================================
# Kartica učenika — što se ZNA o njemu (bez ijednog novog unosa)
# ============================================================================================

def _u_razdoblju(df, od, do):
    """Redci s datumom unutar [od, do]; df bez stupca datum → kako je predano."""
    if df is None or getattr(df, "empty", True) or "datum" not in getattr(df, "columns", ()):
        return df
    d = df.copy()
    serija = d["datum"].map(datum_iz)
    maska = serija.notna()
    if od is not None:
        maska &= serija >= od
    if do is not None:
        maska &= serija <= do
    return d[maska]


def kartica_ucenika(df_instr, df_rezultati, ucenik_id, od=None, do=None, predmet="") -> dict:
    """Sažetak za razdoblje: sati, zadaća, testovi, napredak, teme, javne bilješke.

    NIKAD ne čita `napomena_interna` ni `ocjena_sata` (roditelj ih ne vidi)."""
    uid = _t(ucenik_id).upper()
    od = datum_iz(od)
    do = datum_iz(do)
    k = {"ucenik_id": uid, "predmet": _t(predmet), "od": od, "do": do,
         "razdoblje_tekst": tekst_razdoblja(od, do),
         "sati": {"odrzano": 0, "propusteno": 0, "ukupno_sati": 0},
         "zadaca": {"zadano": 0, "napravljeno": 0, "djelomicno": 0, "ne": 0, "ne_zaredom": 0},
         "testovi": [], "napredak": None, "teme": [], "biljeske": []}

    d = _u_razdoblju(df_instr, od, do)
    if d is not None and not getattr(d, "empty", True) and "ucenik_id" in getattr(d, "columns", ()):
        d = d[d["ucenik_id"].astype(str).str.strip().str.upper() == uid]
        if predmet and "predmet" in d.columns:
            d = d[d["predmet"].astype(str).str.strip().str.lower() == _t(predmet).lower()]
        if not d.empty:
            if "status_termina" in d.columns:
                stat = d["status_termina"].astype(str).str.strip()
                odrzano = int((~stat.isin(STATUSI_BEZ_SATA)).sum())
                propusteno = int(stat.isin(STATUSI_PROPUSTENO).sum())
            else:                       # stariji tab bez statusa: svaki redak je održan sat
                odrzano, propusteno = len(d), 0
            k["sati"] = {"odrzano": odrzano, "propusteno": propusteno, "ukupno_sati": odrzano + propusteno}

            if "zadaca_zadana" in d.columns:
                z = d[d["zadaca_zadana"].astype(str).str.strip().str.lower() == "da"]
                k["zadaca"]["zadano"] = len(z)
                if "zadaca_napravljena" in z.columns:
                    stanja = z["zadaca_napravljena"].astype(str).str.strip()
                    k["zadaca"]["napravljeno"] = int((stanja == "Da").sum())
                    k["zadaca"]["djelomicno"] = int((stanja == "Djelomično").sum())
                    k["zadaca"]["ne"] = int((stanja == "Ne").sum())
                    provjerene = stanja[stanja.isin(["Da", "Djelomično", "Ne"])]
                    k["zadaca"]["ne_zaredom"] = 2 if len(provjerene) >= 2 and all(
                        x == "Ne" for x in provjerene.iloc[-2:]) else 0

            if "teme" in d.columns:
                sve = []
                for v in d["teme"]:
                    for x in str(v or "").split(";"):
                        x = x.strip()
                        if x and x not in sve:
                            sve.append(x)
                k["teme"] = sve[-8:]
            if "napomena_javna" in d.columns:
                javne = [_t(v) for v in d["napomena_javna"] if _t(v)]
                k["biljeske"] = javne[-5:]

    r = _u_razdoblju(df_rezultati, od, do)
    if r is not None and not getattr(r, "empty", True) and "ucenik_id" in getattr(r, "columns", ()):
        r = r[r["ucenik_id"].astype(str).str.strip().str.upper() == uid]
        if not r.empty:
            r = r.copy()
            r["_d"] = r["vrijeme_predaje"].map(datum_iz) if "vrijeme_predaje" in r.columns else None
            try:
                r = r.sort_values("_d", kind="stable")
            except TypeError:
                pass
            testovi = []
            for _, red in r.iterrows():
                p = _cijeli(red.get("postotak"), -1)
                if p < 0:
                    maks = _broj(red.get("bodovi_max"), 0)
                    p = int(round(100 * _broj(red.get("bodovi")) / maks)) if maks > 0 else 0
                testovi.append({"naziv": _t(red.get("naziv_testa")), "postotak": max(0, min(100, p)),
                                "datum": red["_d"].strftime("%d.%m.%Y.") if red.get("_d") else ""})
            k["testovi"] = testovi
            if len(testovi) >= 2:
                prvi, zadnji = testovi[0]["postotak"], testovi[-1]["postotak"]
                k["napredak"] = {"prvi": prvi, "zadnji": zadnji, "razlika": zadnji - prvi}
    return k


def ime_iz_kartice(df_ucenici, ucenik_id) -> str:
    if df_ucenici is None or getattr(df_ucenici, "empty", True) or "ucenik_id" not in df_ucenici.columns:
        return ""
    red = df_ucenici[df_ucenici["ucenik_id"].astype(str).str.strip().str.upper() == _t(ucenik_id).upper()]
    return _t(red.iloc[0].get("ime_djeteta")) if not red.empty else ""


def rod_ucenika(df_ucenici, ucenik_id) -> str:
    """'M' / 'Ž' / '' — iz stupca Učenici.rod. Bez stupca → '' (rečenice koriste muški oblik)."""
    if df_ucenici is None or getattr(df_ucenici, "empty", True) or "ucenik_id" not in df_ucenici.columns:
        return ""
    red = df_ucenici[df_ucenici["ucenik_id"].astype(str).str.strip().str.upper() == _t(ucenik_id).upper()]
    if red.empty:
        return ""
    r = _t(red.iloc[0].get("rod")).upper()
    return r if r in ("M", "Ž") else ""


# ============================================================================================
# Prijedlog fraza — pravila iz podataka (radi bez AI-a)
# ============================================================================================

def predlozi(kartica: dict, fraze: list, ton: str = "", primjereno=(), iskljucene=()) -> dict:
    """Iz podataka predloži po jednu frazu za svako polje. Vraća
    {"dobro": [fraza], "zapelo": [fraza], "cilj": [fraza], "kod_kuce": [fraza], "napomene": [tekst]}.

    Pravila (v. predlog §3.3) koriste samo ono što je izmjereno. Ako podatak ne postoji, pravilo se
    preskače — bolje ništa nego izmišljena tvrdnja."""
    nap = []
    dobro, zapelo = [], []
    napredak = kartica.get("napredak") or {}
    zad = kartica.get("zadaca") or {}
    sati = kartica.get("sati") or {}
    razlika = _cijeli(napredak.get("razlika"), 0)

    if kartica.get("testovi"):
        if razlika >= 8:
            nap.append(f"📈 Napredak na testovima: {napredak['prvi']} % → {napredak['zadnji']} % "
                       f"(+{razlika} postotnih bodova) — ide prvo u poruci.")
            dobro += _kandidati(fraze, [DOBRO + ":NAPREDAK"], ton, primjereno, iskljucene)[:1]
        elif razlika <= -15:
            nap.append(f"📉 Zadnji test je {abs(razlika)} bodova niži od prvoga — predlažem PITANJE, "
                       "ne zaključak (možda je test bio teži ili je bilo izostanaka).")
            dobro += _kandidati(fraze, [TESKO], ton, primjereno, iskljucene)[:1]
        elif razlika >= 0:
            dobro += _kandidati(fraze, [DOBRO + ":ZALAGANJE"], ton, primjereno, iskljucene)[:1]
    if not dobro:
        dobro += _kandidati(fraze, [DOBRO + ":ZALAGANJE", DOBRO + ":RAZUMIJEVANJE", DOBRO + ":SAMOSTALNOST"],
                            ton, primjereno, iskljucene)[:1]

    if _cijeli(zad.get("ne_zaredom"), 0) >= 2:
        nap.append("📝 Zadaća dva puta zaredom nije napravljena — javlja se i na 🏠 Danas.")
        zapelo += _kandidati(fraze, [ZAPELO + ":ZADACA"], ton, primjereno, iskljucene)[:1]
    elif _cijeli(zad.get("zadano"), 0) >= 3 and _cijeli(zad.get("ne"), 0) >= 2:
        nap.append(f"📝 Zadaća napravljena {zad.get('napravljeno')} od {zad.get('zadano')} puta.")
        zapelo += _kandidati(fraze, [ZAPELO + ":ZADACA"], ton, primjereno, iskljucene)[:1]

    ukupno_sati = _cijeli(sati.get("ukupno_sati"), 0)
    if ukupno_sati >= 3 and _cijeli(sati.get("propusteno"), 0) / ukupno_sati > 0.2:
        nap.append(f"📅 Propušteno {sati.get('propusteno')} od {ukupno_sati} sati "
                   f"({int(round(100 * sati.get('propusteno') / ukupno_sati))} %).")
        zapelo += _kandidati(fraze, [ZAPELO + ":PRISUTNOST"], ton, primjereno, iskljucene)[:1]
    if not zapelo:
        zapelo += _kandidati(fraze, [ZAPELO + ":PRIMJENA", ZAPELO + ":PAZNJA", ZAPELO + ":TEMPO"],
                             ton, primjereno, iskljucene)[:1]

    cilj = _kandidati(fraze, [CILJ], ton, primjereno, iskljucene)[:1]
    kod_kuce = _kandidati(fraze, [KOD_KUCE], ton, primjereno, iskljucene)[:1]
    if not nap:
        nap.append("ℹ️ Nema dovoljno podataka za pravilo — birajte fraze ručno (npr. prvi osvrt).")
    return {"dobro": dobro, "zapelo": zapelo, "cilj": cilj, "kod_kuce": kod_kuce, "napomene": nap}


# ============================================================================================
# Sastavljanje teksta
# ============================================================================================

_VRIJEDNOSTI = ("ime", "razdoblje", "u_razdoblju", "predmet", "razred", "skola", "prvi", "zadnji",
                "razlika", "prosjek", "broj_testova", "odrzano", "ukupno_sati", "propusteno", "zadano",
                "napravljeno", "ne_zaredom", "cilj", "tjedana", "a")
# Polja koja SMIJU biti prazna (nastavak za ženski rod) — inače bi fraza "koncentriran{a}" ispala za dječake.
SMIJE_PRAZNO = {"a"}
_POLJA = re.compile(r"\{(" + "|".join(_VRIJEDNOSTI) + r")\}")


def vrijednosti(kartica: dict, ime: str = "", cilj: str = "", tjedana: int = 4, rod: str = "",
                **dodatno) -> dict:
    """Sve što fraza smije sadržavati. `a` je nastavak za ženski rod ('koncentriran{a}' → 'koncentrirana')."""
    k = kartica or {}
    napredak = k.get("napredak") or {}
    sati = k.get("sati") or {}
    zad = k.get("zadaca") or {}
    testovi = k.get("testovi") or []
    prosjek = int(round(sum(t["postotak"] for t in testovi) / len(testovi))) if testovi else ""
    v = {
        "ime": _t(ime) or "učenik",
        "razdoblje": _t(k.get("razdoblje_tekst")) or "dosadašnji rad",
        "u_razdoblju": tekst_razdoblja_u(k.get("od"), k.get("do")),
        "predmet": _t(k.get("predmet")),
        "razred": "",
        "skola": "",
        "prvi": napredak.get("prvi", ""),
        "zadnji": napredak.get("zadnji", ""),
        "razlika": abs(_cijeli(napredak.get("razlika"), 0)),
        "prosjek": prosjek,
        "broj_testova": len(testovi),
        "odrzano": sati.get("odrzano", 0),
        "ukupno_sati": sati.get("ukupno_sati", 0),
        "propusteno": sati.get("propusteno", 0),
        "zadano": zad.get("zadano", 0),
        "napravljeno": zad.get("napravljeno", 0),
        "ne_zaredom": zad.get("ne_zaredom", 0),
        "cilj": _t(cilj).rstrip("."),
        "tjedana": _cijeli(tjedana, 4) or 4,
        "a": "a" if _t(rod).upper() == "Ž" else "",
    }
    v.update({k2: v2 for k2, v2 in (dodatno or {}).items() if k2 in _VRIJEDNOSTI})
    return v


def ispuni(tekst: str, v: dict) -> str:
    """Zamijeni polja {…}. Vraća '' ako neko polje nema vrijednost — takva se fraza preskače
    (bolje izostaviti rečenicu nego poslati 'napredak od  postotnih bodova')."""
    prazna = []

    def zamjena(m):
        k = m.group(1)
        val = v.get(k)
        if val is None or (val == "" and k not in SMIJE_PRAZNO):
            prazna.append(k)
            return ""
        return str(val)

    t = _POLJA.sub(zamjena, str(tekst or ""))
    if prazna:
        return ""
    t = re.sub(r"\s+", " ", t).strip()
    return t.replace("..", ".")      # 'u razdoblju …2026.' + '.' iz fraze ne smije dati dvojnu točku


def prva(fraze: list, kategorija: str, v: dict):
    """Prva fraza te kategorije koja se MOŽE popuniti zadanim vrijednostima (za zadani odabir u sučelju)."""
    for f in fraze:
        if str(f.get("kategorija", "")) == str(kategorija) and ispuni(f.get("tekst", ""), v):
            return f
    return None


def oznaka_fraze(f: dict) -> str:
    """Kratka oznaka za izbornik u sučelju (bez polja koja se popunjavaju)."""
    t = _POLJA.sub("…", str(f.get("tekst", "")))
    return f"[{f.get('kategorija', '')}] {t[:95]}{'…' if len(t) > 95 else ''}"


def sastavi_tekst(kartica: dict, odabrane: list, ime: str = "", cilj: str = "", tjedana: int = 4,
                  rod: str = "", duljina: str = "srednje") -> tuple:
    """(tekst, upozorenja). `odabrane` = popis fraza (dict) koje je profesor označio + cilj svojim riječima.

    Kratko  = 1. odlomak (uvod + dobro) + 1 rečenica 'zapelo'.
    Srednje = sva tri odlomka. Detaljnije = sva tri, dopuštena 2 'dobro' i 2 'zapelo'.
    Redoslijed unutar odlomka prati REDOSLIJED, bez obzira na redoslijed odabira."""
    v = vrijednosti(kartica, ime=ime, cilj=cilj, tjedana=tjedana, rod=rod)
    upozorenja = []
    po_kat: dict[str, list] = {}
    for f in odabrane or []:
        t = ispuni(f.get("tekst", ""), v)
        if not t:
            upozorenja.append(f"Fraza {f.get('fraza_id', '?')} je preskočena — nedostaje podatak za "
                              f"njezina polja ({', '.join(sorted(set(_POLJA.findall(str(f.get('tekst', ''))))))}).")
            continue
        if not t.endswith((".", "!", "?", "…", ":")):
            t += "."
        po_kat.setdefault(str(f.get("kategorija", "")), []).append(t)

    limit = {"kratko": (1, 1), "srednje": (1, 1), "detaljno": (2, 2)}.get(duljina, (1, 1))
    for baza_kat, najvise in ((DOBRO, limit[0]), (ZAPELO, limit[1])):
        for kk in [kk for kk in po_kat if kk == baza_kat or kk.startswith(baza_kat + ":")]:
            if len(po_kat[kk]) > najvise:
                upozorenja.append(f"Previše rečenica u „{baza_kat}” — uzet će se prve {najvise}.")
                po_kat[kk] = po_kat[kk][:najvise]

    def uzmi(kat: str, najvise: int = 9) -> list:
        out = []
        for kk in [k for k in REDOSLIJED if k == kat] + \
                  [k for k in sorted(po_kat) if k.startswith(kat + ":")]:
            out += po_kat.get(kk, [])
        return out[:najvise]

    odlomci = []
    for i, skupina in enumerate(ODLOMCI):
        dijelovi = []
        for kat in skupina:
            if duljina == "kratko" and kat in (CILJ, KOD_KUCE):
                continue
            dijelovi += uzmi(kat, 2 if (duljina == "detaljno" and kat in (DOBRO, ZAPELO)) else 1)
        if dijelovi:
            odlomci.append(" ".join(dijelovi))
    tekst = "\n\n".join(odlomci).strip()
    if not tekst:
        upozorenja.append("Nije odabrana nijedna rečenica — odaberi barem uvod i jednu tvrdnju.")
    return tekst, upozorenja


# ============================================================================================
# Provjere prije slanja (radi i bez AI-a: čuva od pogrešnog imena i etikete)
# ============================================================================================

def _bez_dijakritike(t: str) -> str:
    zamjene = {"č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "d"}
    return "".join(zamjene.get(z, z) for z in str(t or "").lower())


def _sadrzi_ime(tekst: str, ime: str) -> bool:
    """Pojavljuje li se `ime` kao riječ (bez dijakritike, bez velikih slova)?"""
    ime = _bez_dijakritike(_t(ime))
    if len(ime) < 3:
        return False
    return re.search(r"(?<![a-z])" + re.escape(ime) + r"(?![a-z])", _bez_dijakritike(tekst)) is not None


def provjeri_tekst(tekst: str, ime_ucenika: str = "", druga_imena=(), max_znakova: int = MAX_KRATKO) -> tuple:
    """(blokira, upozorenja). `blokira` = poruka se NE smije poslati dok se ne ispravi.

    Blokira samo ono što je stvarno opasno (ime drugog djeteta = GDPR). Etikete, obećanja i duljina
    samo upozoravaju — profesor je taj koji odlučuje, ali mora vidjeti upozorenje."""
    tekst = str(tekst or "").strip()
    blokira, upozorenja = [], []
    if not tekst:
        blokira.append("Poruka je prazna.")
        return blokira, upozorenja
    if len(tekst) < MIN_SMISLENO:
        upozorenja.append(f"Poruka je vrlo kratka ({len(tekst)} znakova) — roditelju to može izgledati kao "
                          "da nije bilo što reći.")

    for ime in druga_imena or ():
        if _t(ime) and _t(ime).lower() != _t(ime_ucenika).lower() and _sadrzi_ime(tekst, ime):
            blokira.append(f"U poruci se pojavljuje ime drugog učenika („{_t(ime)}”). Ukloni ga — poruka o "
                           "jednom djetetu ne smije sadržavati ime drugoga.")
    niz = _bez_dijakritike(tekst)
    for e in ETIKETE:                  # korijen riječi: "lijen" hvata lijen/lijena/lijeno
        if re.search(r"(?<![a-z])" + re.escape(_bez_dijakritike(e)), niz):
            upozorenja.append(f"Riječ „{e}…” opisuje OSOBU, a ne ponašanje. Preformuliraj na konkretno "
                              "ponašanje (npr. „zadaća nije napravljena” umjesto etikete).")
    for e in ETIKETE_FRAZE:
        if _bez_dijakritike(e) in niz:
            upozorenja.append(f"„{e}” je zaključak o djetetu koji profesor ne može donijeti. Ukloni ili "
                              "preformuliraj na konkretno ponašanje.")
    for o in OBECANJA:
        if _bez_dijakritike(o) in niz:
            upozorenja.append(f"„{o}” je obećanje ishoda koje profesor ne može dati. Ukloni ili preformuliraj.")
    for m in MEDICINSKI:
        if _bez_dijakritike(m) in niz:
            upozorenja.append(f"„{m}” ulazi u područje zdravlja/dijagnoze — to nije posao profesora. "
                              "Predloži razgovor s roditeljem bez dijagnoze.")
    if len(tekst) > max_znakova:
        upozorenja.append(f"Poruka je dugačka ({len(tekst)} znakova, preporuka je do {max_znakova}). "
                          "Roditelj je najčešće čita na telefonu.")
    if "{a}" in tekst or re.search(r"\{[a-z_]+\}", tekst):
        upozorenja.append("U tekstu je ostalo polje poput {ime} — popuni ga svojim tekstom.")
    return blokira, upozorenja


# ============================================================================================
# Slanje
# ============================================================================================

def povecaj_koristenje(sheet, fraza_ids) -> None:
    """`puta_koristena` +1 za korištene fraze (jedan batch_update, ne N pojedinačnih upisa)."""
    ids = {_t(x) for x in (fraza_ids or ()) if _t(x)}
    if not ids:
        return
    import gspread
    try:
        ws = sheet.worksheet(FRAZE_TAB)
    except Exception:  # noqa: BLE001
        return
    zagl = [_t(h) for h in ws.row_values(1)]
    if "puta_koristena" not in zagl or "fraza_id" not in zagl:
        return
    ci, ii = zagl.index("puta_koristena") + 1, zagl.index("fraza_id") + 1
    azur = []
    for i, r in enumerate(ws.get_all_values()[1:], start=2):
        fid = r[ii - 1] if len(r) >= ii else ""
        if fid in ids:
            trenutno = _cijeli(r[ci - 1], 0) if len(r) >= ci else 0
            azur.append({"range": gspread.utils.rowcol_to_a1(i, ci), "values": [[trenutno + 1]]})
    if azur:
        ws.batch_update(azur, raw=True)


def posalji_poruku(sheet, *, ucenik_id: str, ime_djeteta: str, nastavnik: str, tekst: str,
                   predmet: str = "", program: str = "", razdoblje_od=None, razdoblje_do=None,
                   fraze=(), izvor: str = "fraze", model: str = "") -> str:
    """Upiše poruku u Napredak_poruke i vrati poruka_id. NIKAD ne šalje mail ni WhatsApp —
    poruka čeka u Moj CAKI (kartica 📈 Napredak). Provjere (`provjeri_tekst`) radi sučelje,
    ali se osnovne stvari provjeravaju i ovdje da se ne može zaobići."""
    tekst = str(tekst or "").strip().replace("\r\n", "\n")
    if not tekst:
        raise ValueError("Poruka je prazna.")
    if len(tekst) > MAX_TEKST:
        raise ValueError(f"Poruka je predugačka (najviše {MAX_TEKST} znakova).")
    if not _t(ucenik_id):
        raise ValueError("Nedostaje učenik.")
    ws, zagl = _osiguraj_tab(sheet, PORUKE_TAB, PORUKE_HEADERS)
    pid = novi_id()
    polja = {
        "poruka_id": pid, "datum": sada().strftime("%Y-%m-%d %H:%M:%S"),
        "ucenik_id": _t(ucenik_id).upper(), "ime_djeteta": _t(ime_djeteta), "nastavnik": _t(nastavnik),
        "predmet": _t(predmet), "program": _t(program),
        "razdoblje_od": datum_iz(razdoblje_od).isoformat() if datum_iz(razdoblje_od) else "",
        "razdoblje_do": datum_iz(razdoblje_do).isoformat() if datum_iz(razdoblje_do) else "",
        "tekst": tekst, "fraze": ", ".join(_t(x) for x in (fraze or ()) if _t(x)),
        "izvor": _t(izvor) or "rucno", "model": _t(model), "poslano": "Da", "procitano": "",
    }
    ws.append_row([str(polja.get(h, "")) for h in zagl], value_input_option="RAW")
    povecaj_koristenje(sheet, fraze)
    return pid


def poruke_ucenika(df, ucenik_id) -> list:
    """Poruke jednog učenika za Moj CAKI — samo poslane, najnovije prve."""
    if df is None or getattr(df, "empty", True) or "ucenik_id" not in getattr(df, "columns", ()):
        return []
    uid = _t(ucenik_id).upper()
    izlaz = []
    for _, r in df.iterrows():
        if _t(r.get("ucenik_id")).upper() != uid or not _da(r.get("poslano", "Da")):
            continue
        od, do = datum_iz(r.get("razdoblje_od")), datum_iz(r.get("razdoblje_do"))
        izlaz.append({
            "poruka_id": _t(r.get("poruka_id")),
            "datum": (_t(r.get("datum")) or "")[:10],
            "nastavnik": _t(r.get("nastavnik")),
            "predmet": _t(r.get("predmet")),
            "razdoblje": tekst_razdoblja(od, do) if (od or do) else "",
            "tekst": _t(r.get("tekst")),
            "_sort": (_t(r.get("datum")), _cijeli(r.get("_row"), 0)),
        })
    izlaz.sort(key=lambda x: x["_sort"], reverse=True)
    return izlaz


def zadnja_poruka(df, ucenik_id):
    """Datum zadnje poslane poruke (date) ili None — za 'razdoblje od zadnje poruke'."""
    p = poruke_ucenika(df, ucenik_id)
    return datum_iz(p[0]["datum"]) if p else None


def razdoblje_od_zadnje(df, ucenik_id, danas=None, zadano_dana: int = 30) -> tuple:
    """(od, do) — od zadnje poslane poruke + 1 dan, ili zadnjih `zadano_dana` dana."""
    danas = datum_iz(danas) or sada().date()
    z = zadnja_poruka(df, ucenik_id)
    od = (z + timedelta(days=1)) if z else (danas - timedelta(days=zadano_dana))
    if od > danas:
        od = danas - timedelta(days=zadano_dana)
    return od, danas


# ============================================================================================
# Prikaz (Streamlit) — kartica učenika i obrazac
# ============================================================================================

def tekst_kartice(kartica: dict) -> dict:
    """Mali rječnik za `st.metric` u sučelju (da se ne računa u UI datoteci)."""
    sati = kartica.get("sati") or {}
    zad = kartica.get("zadaca") or {}
    napredak = kartica.get("napredak") or {}
    testovi = kartica.get("testovi") or []
    return {
        "sati": f"{sati.get('odrzano', 0)} od {sati.get('ukupno_sati', 0)}",
        "zadaca": f"{zad.get('napravljeno', 0)} od {zad.get('zadano', 0)}",
        "test": (f"{napredak['prvi']} % → {napredak['zadnji']} %" if napredak
                 else (f"{testovi[-1]['postotak']} %" if testovi else "—")),
        "napredak": (f"{napredak['razlika']:+d}" if napredak else ""),
    }
