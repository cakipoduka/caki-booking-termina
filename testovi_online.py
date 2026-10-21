"""
CAKI — testovi_online.py  (19.10.2026.)  ·  portal Moj CAKI

Koraci 4–6 sustava online testova (MASTER_BAZA §37.4): učenik u portalu vidi testove koji
su mu objavljeni iz Test Buildera (tab `Testovi_zakazani` u CRM Sheetu), rješava ih,
odgovori se ocjenjuju deterministički (višestruki izbor + kratki odgovor) i rezultat se
upisuje u `Rezultati_testova` — JEDAN upis po predaji (jedan Google API poziv), kako
nalaže nalaz o Sheets write-kvoti (`Claude outputs/CAKI_BRIEF_kvota_sheets-2026-10-18-0730.md`).

PRISTUP: portal se i dalje otvara samo šifrom učenika (ucenik_id), bez lozinke — ista
odluka kao za cijeli Moj CAKI (§3.6 MASTER_CRM). Test vidi samo učenik kojem je
objavljen (ili svi, ako je objavljen bez šifre) i samo u razdoblju otvaranja.

ŠTO OVAJ MODUL NE DIRA
    - `pipeline_upisi.py` (nema novih funkcija u zajedničkom modulu),
    - postojeće kartice portala (nova kartica se dodaje iz `portal_ui.py`),
    - tab `Rezultati` (stari rezultati simulacija); ovo je zaseban `Rezultati_testova`.

OGRANIČENJA v1 (namjerno, zapisano u uputi):
    - jedna predaja po testu (nema ponovnog rješavanja),
    - slike: prikazuju se samo ako je portal povezan s Driveom; inače uz zadatak piše
      da slika postoji (v. uputu),
    - kratki odgovor se uspoređuje deterministički (normalizacija zapisa, brojevi i
      razlomci); netočno zapisan točan odgovor ne dobiva bodove — Caki vidi detalje.
"""
from __future__ import annotations

import json
import re
import secrets as _secrets
import string
from datetime import date, datetime, timedelta

TEST_TAB = "Testovi_zakazani"          # piše ga Test Builder (caki-baza-zadataka/testovi_online.py)
REZ_TAB = "Rezultati_testova"
POCETAK_TAB = "Test_pocetak"           # 21.10.2026.: serverski početak testa (preživi F5)

POCETAK_HEADERS = ["test_id", "ucenik_id", "pocetak", "azurirano"]

REZ_HEADERS = [
    "rezultat_id", "test_id", "naziv_testa", "ucenik_id", "ime_djeteta",
    "bodovi", "bodovi_max", "postotak", "odgovori_json", "detalji_json",
    "vrijeme_pocetka", "vrijeme_predaje", "trajanje_s", "status", "kreirano",
]

STATUS_PREDANO = "Predano"
STATUS_ISTEKLO = "Predano (vrijeme isteklo)"


def _poruka_json(naziv_kljuca: str, sto: str) -> str:
    return (f"`{naziv_kljuca}` u Streamlit Secrets {sto}.\n\n"
            "**Kako popraviti:** otvori Secrets → taj ključ → mora biti JSON servisnog računa "
            "(`{\"type\": \"service_account\", …}`). Najčešća greška je da `private_key` sadrži "
            "STVARNE prijelome redaka — u JSON-u mora stajati `\\n` (jedna linija), ili se cijeli JSON "
            "zalijepi u TOML s trostrukim navodnicima. Ne stavljaj navodnike oko cijelog JSON-a.")


def sa_info_iz_teksta(tekst, naziv_kljuca: str = "GOOGLE_SERVICE_ACCOUNT_JSON") -> dict:
    """JSON servisnog računa iz Secrets — tolerantno na uobičajene pogreške pri lijepljenju.

    Zašto postoji (21.10.2026.): u Secrets je zalijepljen JSON u kojem `private_key` ima STVARNE
    prijelome redaka umjesto `\\n`. `json.loads` to odbija („Invalid control character at: line 5
    column 46”), stranica padne, a poruka je glasila na krivu stranu („CRM Sheet se ne može otvoriti”
    / „dodaj servisni račun na Sheet”) iako je Sheet bio ispravno podijeljen. Takav se JSON ovdje
    prihvati (`strict=False`) jer se nakon parsiranja dobije isti ključ kakav Google očekuje.

    Prihvaća i JSON u navodnicima (zalijepljen s `"…"`), BOM na početku i višak praznina.
    Ako ni to ne prođe, greška kaže TOČNO koji ključ u Secrets je u pitanju i što napraviti.
    """
    import json
    t = str(tekst or "").replace("\ufeff", "").strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"') and t[1:2] == "{":
        t = t[1:-1].strip()                       # zalijepljen s navodnicima oko cijelog JSON-a
    podaci, zadnja = None, None
    for strogo in (True, False):                  # False dopušta stvarne \n unutar stringa
        try:
            podaci = json.loads(t, strict=strogo)
            break
        except json.JSONDecodeError as e:
            zadnja = e
    if podaci is None:
        raise ValueError(_poruka_json(naziv_kljuca, f"nije ispravan JSON ({zadnja})"))
    if not isinstance(podaci, dict):
        raise ValueError(_poruka_json(naziv_kljuca, "nije JSON objekt (mora biti od `{` do `}`)"))
    fale = [k for k in ("private_key", "client_email", "token_uri") if not str(podaci.get(k) or "").strip()]
    if fale:
        raise ValueError(_poruka_json(naziv_kljuca, "nema obavezna polja: " + ", ".join(fale)))
    if "BEGIN" not in str(podaci["private_key"])[:60]:
        raise ValueError(_poruka_json(naziv_kljuca, "polje `private_key` ne sadrži "
                                                    "„-----BEGIN PRIVATE KEY-----”"))
    return podaci


def sa_info_za_testove(st) -> dict:
    """Servisni racun za sustav testiranja (Testovi_zakazani/Rezultati_testova).

    Cakijeva odluka 21.10.2026. (v. TRACKER): ZASEBAN servisni racun samo za sustav
    testiranja, da se njegova write-kvota (v. `Claude outputs/CAKI_BRIEF_kvota_sheets-
    2026-10-18-0730.md`) ne dijeli s ostatkom portala Moj CAKI (Prijave/Dolasci/itd. i
    dalje idu preko dijeljenog racuna). Koristi `GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI`
    ako postoji u Secrets, inace pada natrag na dijeljeni `GOOGLE_SERVICE_ACCOUNT_JSON`
    -- nista ne puca prije nego Caki postavi novi racun. ISTA logika kao
    `caki-baza-zadataka/testovi_online.py::sa_info_za_testove` -- namjerna kopija,
    isti razlog kao i ostala dvostruka mjesta u ovom modulu (cross-repo import ne radi
    na Streamlit Cloudu).

    Parsiranje ide kroz `sa_info_iz_teksta` (21.10.2026.) da stvarni prijelom retka u
    `private_key` ne sruši cijeli portal.
    """
    kljuc = ("GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI" if "GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI" in st.secrets
             else "GOOGLE_SERVICE_ACCOUNT_JSON")
    return sa_info_iz_teksta(st.secrets[kljuc], kljuc)


# ============================================================
# Pomoćno
# ============================================================

def _tekst(vrijednost) -> str:
    return str(vrijednost or "").strip()


def _broj(vrijednost, zadano: float = 1.0) -> float:
    try:
        b = float(str(vrijednost).replace(",", ".").strip())
    except (TypeError, ValueError):
        return zadano
    return b if b > 0 else zadano


def _danas(vrijednost) -> str:
    """'2026-10-19' ili '2026-10-19 08:00' -> '2026-10-19' (prazno ostaje prazno)."""
    return _tekst(vrijednost)[:10]


# ============================================================
# Sheet — čitanje testova i rezultata
# ============================================================

def load_testovi(sheet) -> list[dict]:
    try:
        ws = sheet.worksheet(TEST_TAB)
    except Exception:
        return []
    try:
        return [r for r in ws.get_all_records() if _tekst(r.get("test_id"))]
    except Exception:
        return []


def load_rezultati(sheet) -> list[dict]:
    try:
        ws = sheet.worksheet(REZ_TAB)
    except Exception:
        return []
    try:
        return [r for r in ws.get_all_records() if _tekst(r.get("rezultat_id"))]
    except Exception:
        return []


def osiguraj_rez_tab(sheet):
    try:
        ws = sheet.worksheet(REZ_TAB)
    except Exception:
        ws = sheet.add_worksheet(title=REZ_TAB, rows=500, cols=len(REZ_HEADERS))
        ws.append_row(REZ_HEADERS, value_input_option="RAW")
        return ws

    zaglavlje = [_tekst(h) for h in ws.row_values(1)]
    if not any(zaglavlje):
        ws.append_row(REZ_HEADERS, value_input_option="RAW")
    else:
        fali = [h for h in REZ_HEADERS if h not in zaglavlje]
        if fali:
            ws.update(values=[zaglavlje + fali], range_name="A1")
    return ws


def zadaci_iz_retka(redak) -> list[dict]:
    sirovo = redak.get("zadaci_json") if isinstance(redak, dict) else redak
    try:
        zadaci = json.loads(str(sirovo or "[]"))
    except (TypeError, ValueError):
        return []
    return zadaci if isinstance(zadaci, list) else []


# ============================================================
# Serverski početak testa (21.10.2026.) — tab Test_pocetak
# ============================================================

def load_pocetci(sheet) -> list[dict]:
    """Svi zapisi početaka (prazna lista ako tab još ne postoji)."""
    try:
        ws = sheet.worksheet(POCETAK_TAB)
    except Exception:                                   # noqa: BLE001 — tab još ne postoji
        return []
    try:
        return ws.get_all_records()
    except Exception:                                   # noqa: BLE001 — Google ne odgovara
        return []


def osiguraj_pocetak_tab(sheet):
    try:
        return sheet.worksheet(POCETAK_TAB)
    except Exception:                                   # noqa: BLE001
        ws = sheet.add_worksheet(title=POCETAK_TAB, rows=500, cols=len(POCETAK_HEADERS))
        ws.append_row(POCETAK_HEADERS, value_input_option="RAW")
        return ws


def pocetak_ucenika(pocetci, test_id: str, ucenik_id: str):
    """Kad je učenik počeo taj test (ili None). Jedan test + jedan učenik = jedan zapis."""
    tid, uid = _tekst(test_id), _tekst(ucenik_id).upper()
    for r in pocetci or []:
        if _tekst(r.get("test_id")) == tid and _tekst(r.get("ucenik_id")).upper() == uid:
            try:
                return datetime.fromisoformat(_tekst(r.get("pocetak"))).replace(tzinfo=None)
            except (TypeError, ValueError):
                return None
    return None


def upisi_pocetak(sheet, test_id: str, ucenik_id: str, pocetak: datetime,
                  sada: datetime | None = None) -> bool:
    """Upiše početak testa (ili osvježi postojeći zapis). Vraća True ako je upisan.

    Jedan redak u tabu `Test_pocetak`; koristi se samo za vrijeme rješavanja, ne za ocjenu.
    """
    tid, uid = _tekst(test_id), _tekst(ucenik_id).upper()
    if not tid or not uid:
        return False
    ws = osiguraj_pocetak_tab(sheet)
    azurirano = (sada or datetime.now()).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M")
    vrijednost = pocetak.strftime("%Y-%m-%d %H:%M:%S")

    ids = [_tekst(v) for v in ws.col_values(1)]
    ucenici = [_tekst(v).upper() for v in ws.col_values(2)]
    for i, (t, u) in enumerate(zip(ids, ucenici)):
        if t == tid and u == uid:
            ws.update_cell(i + 1, 3, vrijednost)
            ws.update_cell(i + 1, 4, azurirano)
            return True
    ws.append_row([tid, uid, vrijednost, azurirano], value_input_option="RAW")
    return True


def je_vec_predan(rezultati, test_id: str, ucenik_id: str) -> bool:
    """Je li taj učenik već predao taj test (štiti od dvostrukog klika / dva taba)."""
    tid, uid = _tekst(test_id), _tekst(ucenik_id).upper()
    for r in rezultati or []:
        if _tekst(r.get("test_id")) == tid and _tekst(r.get("ucenik_id")).upper() == uid:
            return True
    return False


def smije_li_predati(sheet, test_id: str, ucenik_id: str) -> tuple[bool, str]:
    """(smije li se upisati predaja, poruka ako ne smije).

    Jedan učenik = jedna predaja po testu. Ako Google ne odgovori, propušta se (bolje
    izgubiti zaštitu nego učeniku odgovore) — dvostruki upis tada hvata ljudsko oko u 📝 Testovi.
    """
    try:
        if je_vec_predan(load_rezultati(sheet), test_id, ucenik_id):
            return False, ("Ovaj test je već predan s tvojim podacima — novi upis nije napravljen "
                           "(da se rezultat ne bi brojao dvaput). Ako misliš da je greška, javi Cakiju.")
    except Exception:                           # noqa: BLE001 — Sheet ne smije blokirati predaju
        return True, ""
    return True, ""


def _pocetak_testa(st, sheet, test_id: str, ucenik_id: str, sada) -> datetime:
    """Početak testa: iz sesije → iz taba `Test_pocetak` → upiši sada.

    Time vrijeme preživi osvježavanje stranice (F5), novi tab i prekid interneta — učenik
    nastavlja s istim rokom, a ne počinje iznova.
    """
    kljuc = f"_online_pocetak_{_tekst(test_id)}_{_tekst(ucenik_id).upper()}"
    zapis = st.session_state.get(kljuc)
    if zapis:
        try:
            return datetime.fromisoformat(str(zapis)).replace(tzinfo=None)
        except (TypeError, ValueError):
            pass
    try:
        vec = pocetak_ucenika(load_pocetci(sheet), test_id, ucenik_id)
    except Exception:                                   # noqa: BLE001 — Sheet ne smije blokirati
        vec = None
    if vec is not None:
        st.session_state[kljuc] = vec.isoformat(timespec="seconds")
        return vec

    pocetak = (sada or datetime.now()).replace(tzinfo=None)
    try:
        upisi_pocetak(sheet, test_id, ucenik_id, pocetak, sada=pocetak)
    except Exception:                                   # noqa: BLE001 — test ide dalje
        pass
    st.session_state[kljuc] = pocetak.isoformat(timespec="seconds")
    return pocetak


# ============================================================
# Koji testovi su dostupni kojem učeniku
# ============================================================

def testovi_za_ucenika(testovi, rezultati, ucenik_id: str, programi=(), danas=None) -> list[dict]:
    """Vraća dostupne testove za učenika, svaki s oznakom 'rjeseno' i 'rezultat'.

    Pravila:
      - `aktivan` mora biti Da (prazno se broji kao Da — stariji redci),
      - `ucenik_id` prazan = svi učenici; inače mora odgovarati,
      - `program` prazan = svi programi; inače mora biti među učenikovim programima,
      - datum mora biti unutar [otvara_od, zatvara_do] (prazna granica = nema granice),
      - test koji je učenik već predao ostaje na popisu, ali označen kao rješen.
    """
    ucenik_id = _tekst(ucenik_id).upper()
    programi = {_tekst(p) for p in (programi or ()) if _tekst(p)}
    danas = _danas(danas or date.today())

    rjeseni = {}
    for r in rezultati or []:
        if _tekst(r.get("ucenik_id")).upper() == ucenik_id:
            rjeseni[_tekst(r.get("test_id"))] = r

    out = []
    for t in testovi or []:
        if _tekst(t.get("aktivan")).lower() not in ("", "da", "1", "true"):
            continue
        cilj = _tekst(t.get("ucenik_id")).upper()
        if cilj and cilj != ucenik_id:
            continue
        if not cilj:
            # 21.10.2026. (nalaz): program se provjerava SAMO za opcu objavu (bez ucenik_id-a,
            # npr. "svi na Maturi"). Test ciljan na KONKRETNOG ucenika (objavi_test/
            # objavi_za_ucenike s ucenik_id-om) prikazuje se njemu uvijek, bez obzira ima li
            # redak u Prijave s odgovarajucim program_tip-om -- inace test ciljan na ucenika
            # koji nema (ili jos nema) redak u Prijave (npr. samostalni Instrukcije klijent
            # bez popunjene forme) nikad ne bi bio vidljiv, iako ga je Caki eksplicitno njemu
            # poslao. V. TRACKER.md 21.10.2026.
            program = _tekst(t.get("program"))
            if program and program not in programi:
                continue
        od, do = _danas(t.get("otvara_od")), _danas(t.get("zatvara_do"))
        if od and danas < od:
            continue
        if do and danas > do:
            continue
        test = dict(t)
        test["rjeseno"] = _tekst(t.get("test_id")) in rjeseni
        test["rezultat"] = rjeseni.get(_tekst(t.get("test_id")))
        out.append(test)

    out.sort(key=lambda t: (_tekst(t.get("kreirano")), _tekst(t.get("test_id"))), reverse=True)
    return out


def rezultati_ucenika(rezultati, ucenik_id: str) -> list[dict]:
    ucenik_id = _tekst(ucenik_id).upper()
    moji = [dict(r) for r in (rezultati or []) if _tekst(r.get("ucenik_id")).upper() == ucenik_id]
    moji.sort(key=lambda r: _tekst(r.get("kreirano")), reverse=True)
    return moji


# ============================================================
# Ocjenjivanje (deterministički — bez AI-ja)
# ============================================================

def normalizuj(tex) -> str:
    """LaTeX/tekst u oblik pogodan za usporedbu: bez $, \\left, razmaka, s razlomkom kao (a)/(b)."""
    t = _tekst(tex)
    if not t:
        return ""
    t = t.replace("$", "")
    t = t.replace("\\left", "").replace("\\right", "")
    t = t.replace("\\displaystyle", "")
    t = re.sub(r"\\[,;!:]", "", t)
    t = t.replace("~", "")
    t = t.replace("\\cdot", "*").replace("\\times", "*").replace("\\div", "/")
    # dulje oznake prvo: \leq prije \le (inače ostane "<=q")
    t = (t.replace("\\leq", "<=").replace("\\geq", ">=")
         .replace("\\le", "<=").replace("\\ge", ">="))
    t = t.replace("\\sqrt", "sqrt").replace("√", "sqrt")
    t = t.replace("\\pi", "pi")
    t = t.replace("−", "-").replace("–", "-").replace("—", "-")
    t = t.replace("{,}", ".")
    for _ in range(4):   # \frac{a}{b} -> (a)/(b), i ugniježđeno
        novi = re.sub(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", t)
        if novi == t:
            break
        t = novi
    t = re.sub(r"\s+", "", t)
    return t.rstrip(".").lower()


def _bez_varijable(izraz: str) -> str:
    """'x=2' -> '2', 'n:5' -> '5' — učenik često napiše ime nepoznanice."""
    return re.sub(r"^[a-z]=|^[a-z]:", "", izraz.strip())


def _kao_broj(izraz: str):
    s = izraz.strip()
    # decimalni zarez (hrvatski zapis): "2,5" -> "2.5"; samo kad je cijeli izraz broj/razlomak
    if "," in s:
        s = s.replace(",", ".")
    m = re.fullmatch(r"\(?(-?\d+(?:\.\d+)?)\)?/\(?(-?\d+(?:\.\d+)?)\)?", s)
    if m:
        nazivnik = float(m.group(2))
        return float(m.group(1)) / nazivnik if nazivnik else None
    try:
        return float(s)
    except ValueError:
        return None


def kratki_tocan(kljuc, odgovor) -> bool:
    """Usporedba kratkog odgovora: jednak zapis, jednak broj ili jednak razlomak."""
    a, b = normalizuj(kljuc), normalizuj(odgovor)
    if not a or not b:
        return False
    if a == b:
        return True
    va, vb = _bez_varijable(a), _bez_varijable(b)
    if va == vb:
        return True
    # postotak: "50%" i "50"
    if va.rstrip("%") == vb.rstrip("%"):
        return True
    x, y = _kao_broj(va), _kao_broj(vb)
    if x is not None and y is not None:
        return abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y))
    return False


def _slovo_iz_kljuca(kljuc, opcije) -> str:
    """Konačan odgovor višestrukog izbora -> 'A'/'B'/'C'/'D' (ili '' ako se ne prepozna)."""
    k = _tekst(kljuc)
    if not k:
        return ""
    m = re.match(r"^([A-Za-zČĆŽŠĐ])\s*[\)\.:\-–]", k)
    if m:
        return m.group(1).upper()
    if len(k) == 1 and k.isalpha():
        return k.upper()
    nk = normalizuj(k)
    for i, opcija in enumerate(opcije or []):
        if normalizuj(opcija) and normalizuj(opcija) == nk:
            return chr(65 + i)
    for i, opcija in enumerate(opcije or []):
        if normalizuj(opcija) and normalizuj(opcija) in nk:
            return chr(65 + i)
    return ""


def je_tocan(zadatak, odgovor) -> bool:
    if not _tekst(odgovor):
        return False
    if _tekst(zadatak.get("tip")) == "visestruki_izbor" and zadatak.get("opcije"):
        tocno = _slovo_iz_kljuca(zadatak.get("odgovor"), opcije_zadatka(zadatak))
        if tocno:
            return _tekst(odgovor).upper()[:1] == tocno
        # nema slova u ključu — usporedi tekst odabrane opcije
        opcije = opcije_zadatka(zadatak)
        slovo = _tekst(odgovor).upper()[:1]
        if "A" <= slovo <= "Z" and 0 <= ord(slovo) - 65 < len(opcije):
            return kratki_tocan(zadatak.get("odgovor"), opcije[ord(slovo) - 65])
        return False
    return kratki_tocan(zadatak.get("odgovor"), odgovor)


def opcije_zadatka(zadatak) -> list:
    opcije = zadatak.get("opcije") or []
    return [o for o in opcije if _tekst(o)]


def ocjeni(zadaci, odgovori) -> tuple[float, float, list]:
    """Vraća (bodovi, bodovi_max, detalji). `odgovori` je dict {redni_broj: odgovor}."""
    bodovi = 0.0
    maks = 0.0
    detalji = []
    for i, z in enumerate(zadaci or []):
        m = _broj(z.get("bodovi"))
        maks += m
        odgovor = _tekst((odgovori or {}).get(i))
        tocno = je_tocan(z, odgovor)
        b = m if tocno else 0.0
        bodovi += b
        detalji.append({
            "id": _tekst(z.get("id")),
            "tocno": tocno,
            "bodovi": round(b, 2),
            "max": round(m, 2),
            "odgovor": odgovor,
            "ocekivano": _tekst(z.get("odgovor")),
        })
    return round(bodovi, 2), round(maks, 2), detalji


# ============================================================
# Upis rezultata — JEDAN redak po predaji
# ============================================================

def novi_rezultat_id(postojeci=()) -> str:
    danas = datetime.now().strftime("%y%m%d%H%M%S")
    postojeci = {_tekst(x) for x in (postojeci or ()) if _tekst(x)}
    for _ in range(50):
        kraj = "".join(_secrets.choice(string.ascii_uppercase + string.digits) for _ in range(3))
        kandidat = f"R{danas}-{kraj}"
        if kandidat not in postojeci:
            return kandidat
    raise RuntimeError("Ne mogu složiti jedinstven rezultat_id.")


def spremi_rezultat(sheet, *, test, ucenik_id: str, ime_djeteta: str, bodovi: float,
                    bodovi_max: float, detalji: list, odgovori: dict, pocetak: datetime,
                    predaja: datetime, status: str = STATUS_PREDANO) -> dict:
    """Upisuje rezultat u JEDNOM pozivu (append_row) — pravilo iz nalaza o Sheets kvoti."""
    ws = osiguraj_rez_tab(sheet)
    try:
        postojeci = [_tekst(v) for v in ws.col_values(1)]
    except Exception:
        postojeci = []

    postotak = round(100 * bodovi / bodovi_max) if bodovi_max else 0
    redak = {
        "rezultat_id": novi_rezultat_id(postojeci),
        "test_id": _tekst(test.get("test_id")),
        "naziv_testa": _tekst(test.get("naziv")),
        "ucenik_id": _tekst(ucenik_id).upper(),
        "ime_djeteta": _tekst(ime_djeteta),
        "bodovi": round(float(bodovi), 2),
        "bodovi_max": round(float(bodovi_max), 2),
        "postotak": postotak,
        "odgovori_json": json.dumps(odgovori, ensure_ascii=False),
        "detalji_json": json.dumps(detalji, ensure_ascii=False),
        "vrijeme_pocetka": pocetak.strftime("%Y-%m-%d %H:%M"),
        "vrijeme_predaje": predaja.strftime("%Y-%m-%d %H:%M"),
        "trajanje_s": max(0, int((predaja - pocetak).total_seconds())),
        "status": status,
        "kreirano": predaja.strftime("%Y-%m-%d %H:%M"),
    }
    ws.append_row([redak[h] for h in REZ_HEADERS], value_input_option="RAW")
    return redak


# ============================================================
# UI — kartica 📝 Testovi u portalu
# ============================================================

def _kljuc(test_id: str, i: int) -> str:
    return f"online_{test_id}_{i}"


def _ocisti_kljuceve(st, test_id: str) -> None:
    for k in [k for k in list(st.session_state.keys()) if str(k).startswith(f"online_{test_id}_")]:
        st.session_state.pop(k, None)


def tabela_rezultata(rezultati):
    """Rezultati učenika kao pandas tablica za prikaz (prazna tablica ako nema rezultata)."""
    import pandas as pd

    return pd.DataFrame([{
        "Datum": _tekst(r.get("vrijeme_predaje"))[:16],
        "Test": _tekst(r.get("naziv_testa")),
        "Bodovi": _tekst(r.get("bodovi")),
        "Od": _tekst(r.get("bodovi_max")),
        "Postotak": int(float(_tekst(r.get("postotak")) or 0)),
        "Status": _tekst(r.get("status")),
    } for r in (rezultati or [])])


def _prikazi_rezultate(st, rezultati) -> None:
    if not rezultati:
        return
    st.markdown("#### 📊 Moji rezultati testova")
    st.dataframe(tabela_rezultata(rezultati), hide_index=True, width="stretch",
                 column_config={"Postotak": st.column_config.ProgressColumn(
                     min_value=0, max_value=100, format="%d %%")})


def _prikazi_sliku_zadatka(st, naziv) -> bool:
    """Prikaže sliku zadatka iz Drivea (modul `slike_zadataka`). Nikad ne ruši test.

    Vraća False ako slike nema, ako `SLIKE_FOLDER_ID` nije u Secrets ili ako Drive ne
    odgovori — tada portal pokaže dosadašnju tekstualnu napomenu.
    """
    try:
        from slike_zadataka import prikazi_sliku      # noqa: PLC0415 — modul je u portalu
    except Exception:                                  # noqa: BLE001 — nije u ovoj kopiji repoa
        return False
    try:
        return bool(prikazi_sliku(st, naziv))
    except Exception:                                  # noqa: BLE001 — slika ne ruši test
        return False


def _prikazi_rjesavanje(st, sheet, test, ucenik, ucenik_id, sada) -> None:
    zadaci = zadaci_iz_retka(test)
    test_id = _tekst(test.get("test_id"))
    trajanje = int(float(_tekst(test.get("trajanje_min")) or 45))

    if not zadaci:
        st.error("Test nema ispravno spremljene zadatke — javi Cakiju. Odgovori se ne mogu spremiti.")
        if st.button("Zatvori", key=f"zatvori_{test_id}"):
            st.session_state.pop("_online_test_id", None)
            st.session_state.pop("_online_test_pocetak", None)
            st.rerun()
        return

    # 21.10.2026.: početak testa se pamti u Sheetu (tab Test_pocetak), ne samo u sesiji —
    # tako rok preživi osvježavanje stranice (F5), novi tab i prekid interneta.
    pocetak = _pocetak_testa(st, sheet, test_id, ucenik_id, sada)

    rok = pocetak + timedelta(minutes=trajanje)

    st.markdown(f"### 📝 {_tekst(test.get('naziv'))}")
    st.caption(f"{len(zadaci)} zadataka · {_tekst(test.get('bodovi_ukupno'))} bodova · "
               f"vrijeme: {trajanje} minuta")
    if sada > rok:
        st.error(f"⏰ Vrijeme je isteklo u {rok:%H:%M}. Odgovori se i dalje mogu predati, ali će "
                 f"rezultat biti označen kao predan po isteku vremena.")
    else:
        st.info(f"⏱️ Vrijeme se mjeri od početka. Rok za predaju: **{rok:%H:%M}**. "
                f"Ako osvježiš stranicu, vrijeme se nastavlja (ne počinje iznova).")

    from kratki_odgovor_unos import kratki_odgovor_unos

    odgovori: dict[int, str] = {}
    for i, z in enumerate(zadaci):
        with st.container(border=True):
            st.markdown(f"**Zadatak {i + 1}.** ({_broj(z.get('bodovi')):g} bod.)")
            st.markdown(_tekst(z.get("tekst")))
            if _tekst(z.get("slika")):
                if not _prikazi_sliku_zadatka(st, z.get("slika")):
                    st.caption("🖼️ Uz zadatak ide slika — ako je ne vidiš, javi Cakiju prije predaje.")
            if _tekst(z.get("tip")) == "visestruki_izbor" and opcije_zadatka(z):
                opcije = opcije_zadatka(z)
                slova = [""] + [chr(65 + k) for k in range(len(opcije))]
                odgovori[i] = st.radio(
                    "Odgovor", slova, index=0, horizontal=False, key=_kljuc(test_id, i),
                    format_func=lambda s, o=opcije: "— odaberi —" if not s else f"{s}) {o[ord(s) - 65]}",
                )
            else:
                odgovori[i] = kratki_odgovor_unos("Odgovor", key=_kljuc(test_id, i))

    c1, c2 = st.columns([1, 1])
    predaj = c1.button("✅ Predaj test", type="primary", key=f"predaj_{test_id}")
    odustani = c2.button("Odustani (odgovori se ne spremaju)", key=f"odustani_{test_id}")

    if odustani:
        _ocisti_kljuceve(st, test_id)
        st.session_state.pop("_online_test_id", None)
        st.session_state.pop("_online_test_pocetak", None)
        st.rerun()

    if predaj:
        # 21.10.2026.: zaštita od dvostrukog upisa (dva klika, dva taba, dva uređaja).
        smije, razlog = smije_li_predati(sheet, test_id, ucenik_id)
        if not smije:
            st.warning(razlog)
            _ocisti_kljuceve(st, test_id)
            st.session_state.pop("_online_test_id", None)
            st.session_state.pop("_online_test_pocetak", None)
            return

        bodovi, maks, detalji = ocjeni(zadaci, odgovori)
        status = STATUS_ISTEKLO if sada > rok + timedelta(seconds=60) else STATUS_PREDANO
        try:
            spremi_rezultat(sheet, test=test, ucenik_id=ucenik_id,
                            ime_djeteta=_tekst(ucenik.get("ime_djeteta")), bodovi=bodovi,
                            bodovi_max=maks, detalji=detalji, odgovori=odgovori,
                            pocetak=pocetak, predaja=sada, status=status)
        except Exception:  # noqa: BLE001 — učenik ne smije izgubiti odgovore zbog Google greške
            st.error("Rezultat nije spremljen (Google trenutno ne odgovara). Pokušaj ponovno za minutu "
                     "ili javi Cakiju — odgovori su još na ekranu.")
            return
        _ocisti_kljuceve(st, test_id)
        st.session_state.pop("_online_test_id", None)
        st.session_state.pop("_online_test_pocetak", None)
        st.session_state["_online_rezultat"] = {
            "naziv": _tekst(test.get("naziv")), "bodovi": bodovi,
            "maks": maks, "status": status,
        }
        st.cache_data.clear()
        st.rerun()


def prikazi_testove(st, sheet, testovi, rezultati, ucenik, ucenik_id: str, programi=(),
                    sada=None) -> None:
    """Kartica 📝 Testovi: popis dostupnih testova, rješavanje i moji rezultati."""
    sada = (sada or datetime.now()).replace(tzinfo=None)
    moji = rezultati_ucenika(rezultati, ucenik_id)

    poruka = st.session_state.pop("_online_rezultat", None)
    if poruka:
        st.success(f"✅ Test „{poruka['naziv']}” je predan: **{poruka['bodovi']:g} / {poruka['maks']:g}** "
                   f"bodova ({poruka['status']}).")
        if poruka["maks"] and poruka["bodovi"] == poruka["maks"]:
            st.balloons()

    # 21.10.2026.: kratke upute učeniku (Cakijev zahtjev — da se ne pita u chatovima)
    with st.expander("ℹ️ Kako radi test"):
        st.markdown(
            "- Test rješavaš **jednom**. Vrijeme se mjeri od otvaranja i **ne staje** ako "
            "osvježiš stranicu ili zatvoriš tab.\n"
            "- Piše ti do kada moraš predati. Ako vrijeme istekne, odgovori se i dalje mogu "
            "predati, ali rezultat se označi kao predan po isteku.\n"
            "- **Višestruki izbor**: klikni slovo. **Kratki odgovor**: upiši broj ili izraz "
            "(može razlomak `1/2` ili decimalni zarez `0,5`).\n"
            "- Ako piše da uz zadatak ide slika, a ne vidiš je — javi Cakiju **prije** predaje.\n"
            "- Rezultat vidiš odmah nakon predaje i trajno u 📊 Rezultati."
        )

    dostupni = testovi_za_ucenika(testovi, rezultati, ucenik_id, programi, sada.date())

    aktivni = _tekst(st.session_state.get("_online_test_id"))
    if aktivni:
        test = next((t for t in dostupni
                     if _tekst(t.get("test_id")) == aktivni and not t["rjeseno"]), None)
        if test is None:
            st.warning("Ovaj test više nije otvoren ili je već predan. Odgovori nisu spremljeni.")
            st.session_state.pop("_online_test_id", None)
            st.session_state.pop("_online_test_pocetak", None)
        else:
            _prikazi_rjesavanje(st, sheet, test, ucenik, ucenik_id, sada)
            return

    za_rjesavanje = [t for t in dostupni if not t["rjeseno"]]

    if not dostupni and not moji:
        st.info("Trenutno nema testova za tebe. Kad Caki objavi test, pojavit će se ovdje.")
        return

    if za_rjesavanje:
        st.markdown("#### ✍️ Testovi za rješavanje")
        for t in za_rjesavanje:
            with st.container(border=True):
                c1, c2 = st.columns([4, 1])
                c1.markdown(f"**{_tekst(t.get('naziv'))}**")
                c1.caption(f"{_tekst(t.get('broj_zadataka'))} zadataka · "
                           f"{int(float(_tekst(t.get('trajanje_min')) or 45))} minuta · "
                           f"vrijedi do {_tekst(t.get('zatvara_do')) or 'dalje'}")
                if c2.button("▶️ Počni test", key=f"pocni_{_tekst(t.get('test_id'))}", type="primary"):
                    st.session_state["_online_test_id"] = _tekst(t.get("test_id"))
                    st.session_state["_online_test_pocetak"] = sada.isoformat(timespec="seconds")
                    st.rerun()
    else:
        st.success("Svi dostupni testovi su riješeni. 🎉")

    if any(t["rjeseno"] for t in dostupni):
        st.markdown("#### ✅ Riješeni testovi")
        for t in dostupni:
            if not t["rjeseno"]:
                continue
            r = t["rezultat"] or {}
            st.write(f"**{_tekst(t.get('naziv'))}** — {_tekst(r.get('bodovi'))} / "
                     f"{_tekst(r.get('bodovi_max'))} bodova ({_tekst(r.get('postotak'))} %) · "
                     f"{_tekst(r.get('vrijeme_predaje'))}")

    _prikazi_rezultate(st, moji)


__all__ = [
    "TEST_TAB", "REZ_TAB", "REZ_HEADERS", "STATUS_PREDANO", "STATUS_ISTEKLO",
    "POCETAK_TAB", "POCETAK_HEADERS", "sa_info_za_testove", "sa_info_iz_teksta",
    "load_testovi", "load_rezultati", "osiguraj_rez_tab", "zadaci_iz_retka",
    "load_pocetci", "osiguraj_pocetak_tab", "pocetak_ucenika", "upisi_pocetak",
    "je_vec_predan",
    "testovi_za_ucenika", "rezultati_ucenika", "normalizuj", "kratki_tocan",
    "je_tocan", "ocjeni", "novi_rezultat_id", "spremi_rezultat", "tabela_rezultata",
    "prikazi_testove",
]
