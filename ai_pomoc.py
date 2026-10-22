"""
CAKI — ai_pomoc.py  (21.10.2026.)

💡 „Pomoć pri učenju" u portalu Moj CAKI: učenik, dok rješava test, može pitati za
**sljedeći korak** ili **pravilo** — nikad za rješenje.

KAKO SE ČUVA „NIKAD TOČAN ODGOVOR" (tri sloja, sva tri su u kodu)
    1. Modelu se NIKAD ne šalje `odgovor` ni `detalji` — samo tekst zadatka, ponuđeni
       odgovori, cjelina i razina pomoći. Nema što očitati.
    2. Sustavna uputa zabranjuje konačan rezultat i traži JEDAN korak / jedno pravilo.
    3. Odgovor se prije prikaza filtrira: ako sadrži ključ (isti oblik koji ocjenjivanje
       traži) ili frazu „rješenje je…", učenik dobije generičku uputu, a slučaj se u logu
       označi kao `filtrirano = Da`.

IDENTITET
    Bot se predstavlja kao **Caki** (profesor), bez spominjanja da je AI — Cakijeva odluka
    21.10.2026. Ako to ikad želi promijeniti, dovoljno je urediti `IME_BOTA` i `UPUTA`
    ovdje; log i ograničenja ostaju isti.

OGRANIČENJA
    - najviše `MAX_PITANJA` pitanja po učeniku po testu,
    - samo dok test traje (nakon predaje više ne),
    - svako pitanje se bilježi u tab `AI_pomoc_log` (za Cakijev pregled i za popis zadataka
      za koje se isplati snimiti video rješenje).

Tajne: `DEEPSEEK_API_KEY` u Secrets portala. Bez njega se blok „Pomoć" ne prikazuje.
"""
from __future__ import annotations

import json
import re
import secrets as _secrets
import string
import time
from datetime import datetime

import requests

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
MAX_PITANJA = 5
TIMEOUT_S = 60
MAX_TOKENA = 700
TEMPERATURA = 0.5

LOG_TAB = "AI_pomoc_log"
LOG_HEADERS = ["pitanje_id", "test_id", "ucenik_id", "zadatak_id", "zadatak",
               "razina", "pitanje", "odgovor", "model", "filtrirano", "kreirano"]

IME_BOTA = "Caki"
RAZINE = ["Sljedeći korak", "Pravilo / formula"]

UPUTA = """Ti si {ime}, profesor matematike u CAKI Centru. Učenik rješava zadatak iz testa i traži pomoć.

STROGA PRAVILA:
- NIKAD ne reci konačan rezultat, ni brojčanu vrijednost rješenja, ni "x = …".
- Ne rješavaj zadatak do kraja. Daj TOČNO JEDAN korak (ili jedno pravilo/formulu) i pusti učenika da nastavi.
- Ako učenik traži rješenje, pristojno odbij i ponudi korak.
- Piši na hrvatskom, toplo i korisno: 4–6 rečenica. Smiješ objasniti zašto korak radi i na što
  učenik treba pripaziti (bez konačnog rezultata). Kratki popis koraka je dopušten ako pomaže.
- Nikad ne spominji da si AI, model ni aplikacija. Ti si profesor.

Zadatak: {tekst}
{opcije}Cjelina: {cjelina}
Učenik traži: {razina}
"""

GENERICKI = ("Ne mogu ti dati rješenje — to je tvoj dio posla. 🙂 Pogledaj što zadatak traži, "
             "zapiši što je poznato, a što tražiš, pa pokušaj prvi korak. Ako zapneš, pitaj me "
             "za **pravilo** ili **sljedeći korak**.")

_FRAZE = ("rjesenjeje", "rjesenje:", "odgovorje", "odgovor:", "rezultatje", "rjesenje=",
          "x=", "y=", "=")


# ============================================================
# Pomoćno
# ============================================================

def _tekst(vrijednost) -> str:
    return str(vrijednost or "").strip()


def _normalizuj(tekst) -> str:
    """Ista ideja kao ocjenjivanje: bez razmaka, valuta, LaTeX ukrasa i velikih slova."""
    t = _tekst(tekst).lower()
    t = t.replace("$", "").replace("\\left", "").replace("\\right", "")
    t = t.replace("\\cdot", "*").replace("\\times", "*").replace("\\div", "/")
    t = t.replace("{,}", ".").replace("−", "-").replace("–", "-")
    t = re.sub(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", t)
    t = re.sub(r"\s+", "", t)
    return t.rstrip(".").strip()


def kljuc_iz_testa(zadatak) -> str:
    return _tekst((zadatak or {}).get("odgovor"))


def _bez_indeksa(tekst: str) -> str:
    """'x_1=2' -> 'x=2', 'x1=2' -> 'x=2' — broj u indeksu (x₁) nije dio rješenja.

    Namjerno usko: samo `x`, `y`, `n` bez donje crte, inače bi hrvatski veznik „i”
    („2 i 3”) izgubio broj iza sebe.
    """
    t = re.sub(r"([a-z])_(\d+)", r"\1", tekst or "")
    return re.sub(r"([xyn])(\d+)", r"\1", t)


def _brojevi(tekst: str) -> set[float]:
    """Svi brojevi u tekstu (hrvatski decimalni zarez se pretvara u točku)."""
    izlaz = set()
    for nalaz in re.findall(r"-?\d+(?:[.,]\d+)?", tekst or ""):
        try:
            izlaz.add(round(float(nalaz.replace(",", ".")), 6))
        except ValueError:
            continue
    return izlaz


def izgleda_kao_rjesenje(odgovor: str, kljuc: str) -> bool:
    """Bi li prikaz ovog odgovora odao konačno rješenje?

    Namjerno „failsafe": ako nismo sigurni, bolje zamijeniti generičkom uputom nego pustiti
    da se pojavi rješenje. Redom:
      1. cijeli ključ se pojavljuje u odgovoru (bez razmaka/valuta),
      2. ključ se pojavljuje kao samostalan token (npr. „2” u „podijeli s 2”),
      3. **svi brojevi iz ključa** pojavljuju se u odgovoru (hvata „x=2 i x=3”).
    """
    tekst = _tekst(odgovor)
    if not tekst:
        return True
    k = _normalizuj(kljuc)
    if not k:
        return False
    norm = _normalizuj(tekst)

    if len(k) >= 2 and k in norm:
        return True

    # višedijelni ključ ("x1=2, x2=3") — i JEDAN njegov dio je curenje
    for dio in re.split(r"[,;]+", k):
        if len(dio) >= 3 and dio in norm:
            return True

    for token in re.split(r"[^0-9a-z/.,()+-]+", norm):
        if token and _normalizuj(token) == k:
            return True

    # brojevi se traže u IZVORNOM tekstu (s razmacima), jer se „2, 3” inače stopi u 2,3
    brojevi_kljuca = _brojevi(_bez_indeksa(_tekst(kljuc).lower()))
    if brojevi_kljuca and (brojevi_kljuca & _brojevi(_bez_indeksa(_tekst(odgovor).lower()))):
        return True
    return False


# ============================================================
# DeepSeek
# ============================================================

def ima_kljuc(st) -> bool:
    try:
        return bool(_tekst(st.secrets.get("DEEPSEEK_API_KEY")))
    except Exception:                                   # noqa: BLE001
        return False


def sastavi_uputu(zadatak, razina: str, cjelina: str = "") -> str:
    opcije = [_tekst(o) for o in (zadatak or {}).get("opcije") or [] if _tekst(o)]
    blok = ("Ponuđeni odgovori: " + " | ".join(opcije) + "\n") if opcije else ""
    return UPUTA.format(ime=IME_BOTA, tekst=_tekst((zadatak or {}).get("tekst")),
                        opcije=blok, cjelina=_tekst(cjelina) or "—",
                        razina=razina)


def pitaj_ai(kljuc_api: str, zadatak, razina: str, cjelina: str = "", model: str = MODEL,
             transport=None) -> str:
    """Jedan poziv na DeepSeek. Vraća tekst odgovora (bez filtera — filter je iznad)."""
    if not _tekst(kljuc_api):
        raise RuntimeError("Nema DEEPSEEK_API_KEY u Secrets.")
    tijelo = {
        "model": model,
        "messages": [
            {"role": "system", "content": sastavi_uputu(zadatak, razina, cjelina)},
            {"role": "user", "content": f"Daj mi {razina.lower()} za ovaj zadatak."},
        ],
        "temperature": TEMPERATURA,
        "max_tokens": MAX_TOKENA,
    }
    zaglavlja = {"Authorization": f"Bearer {kljuc_api}", "Content-Type": "application/json"}

    if transport is not None:                       # za testove (bez mreže)
        return _izvuci_tekst(transport(tijelo, zaglavlja))

    zadnja_greska = "nepoznato"
    for cekanje in (0, 2, 6):                       # 3 pokušaja: Google/DeepSeek zna zapeti
        if cekanje:
            time.sleep(cekanje)
        try:
            odgovor = requests.post(DEEPSEEK_URL, headers=zaglavlja, json=tijelo,
                                    timeout=TIMEOUT_S)
        except requests.exceptions.RequestException as e:
            zadnja_greska = f"{type(e).__name__}"
            continue
        if odgovor.status_code == 200:
            try:
                return _izvuci_tekst(odgovor.json())
            except ValueError:
                raise RuntimeError("DeepSeek je vratio nešto što nije JSON.") from None
        zadnja_greska = f"status {odgovor.status_code}"
        if odgovor.status_code != 429 and odgovor.status_code < 500:
            break                                   # 4xx (osim 429) se ne ponavlja
    raise RuntimeError(f"DeepSeek nije odgovorio ({zadnja_greska}).")


def _izvuci_tekst(podaci) -> str:
    try:
        return _tekst(podaci["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError("DeepSeekov odgovor nema očekivani oblik.") from e


# ============================================================
# Log (Sheet)
# ============================================================

def load_log(sheet) -> list[dict]:
    try:
        ws = sheet.worksheet(LOG_TAB)
    except Exception:                                   # noqa: BLE001 — tab još ne postoji
        return []
    try:
        return ws.get_all_records()
    except Exception:                                   # noqa: BLE001
        return []


def osiguraj_log_tab(sheet):
    try:
        return sheet.worksheet(LOG_TAB)
    except Exception:                                   # noqa: BLE001
        ws = sheet.add_worksheet(title=LOG_TAB, rows=1000, cols=len(LOG_HEADERS))
        ws.append_row(LOG_HEADERS, value_input_option="RAW")
        return ws


def broj_pitanja(log, test_id: str, ucenik_id: str) -> int:
    tid, uid = _tekst(test_id), _tekst(ucenik_id).upper()
    return sum(1 for r in log or []
               if _tekst(r.get("test_id")) == tid and _tekst(r.get("ucenik_id")).upper() == uid)


def novi_id(postojeci=()) -> str:
    danas = datetime.now().strftime("%y%m%d%H%M%S")
    postojeci = {_tekst(x) for x in (postojeci or ()) if _tekst(x)}
    for _ in range(40):
        kraj = "".join(_secrets.choice(string.ascii_uppercase + string.digits) for _ in range(3))
        kandidat = f"P{danas}-{kraj}"
        if kandidat not in postojeci:
            return kandidat
    raise RuntimeError("Ne mogu složiti jedinstven ID pitanja.")


def upisi_pitanje(sheet, *, test_id: str, ucenik_id: str, zadatak_id: str, zadatak: str,
                  razina: str, pitanje: str, odgovor: str, filtrirano: bool,
                  model: str = MODEL, sada=None) -> dict:
    """JEDAN upis po pitanju (Sheets kvota)."""
    ws = osiguraj_log_tab(sheet)
    try:
        postojeci = [_tekst(v) for v in ws.col_values(1)]
    except Exception:                                   # noqa: BLE001
        postojeci = []
    sada = sada or datetime.now()
    redak = {
        "pitanje_id": novi_id(postojeci),
        "test_id": _tekst(test_id),
        "ucenik_id": _tekst(ucenik_id).upper(),
        "zadatak_id": _tekst(zadatak_id),
        "zadatak": _tekst(zadatak)[:160],
        "razina": _tekst(razina),
        "pitanje": _tekst(pitanje)[:300],
        "odgovor": _tekst(odgovor)[:1200],
        "model": _tekst(model),
        "filtrirano": "Da" if filtrirano else "Ne",
        "kreirano": sada.strftime("%Y-%m-%d %H:%M"),
    }
    ws.append_row([redak[h] for h in LOG_HEADERS], value_input_option="RAW")
    return redak


# ============================================================
# UI (portalska kartica)
# ============================================================

def _ukljuceno(st, test) -> bool:
    """Je li pomoć dopuštena: po testu (`pomoc` = Da) ili globalno (`AI_POMOC` = Da)."""
    if _tekst((test or {}).get("pomoc")) == "Da":
        return True
    try:
        return _tekst(st.secrets.get("AI_POMOC")).lower() in ("da", "1", "true")
    except Exception:                                   # noqa: BLE001 — nema Secrets
        return False


def dijagnostika_ukljucena(st) -> bool:
    """Prikaži tehničke poruke u portalu — SAMO ako Caki postavi `TESTOVI_DIJAGNOSTIKA = Da`.

    Zašto: 22.10.2026. je poruka o `DEEPSEEK_API_KEY`/Secrets bila vidljiva UČENICIMA. Tehnički
    detalji ne smiju ići učenicima; Caki ih uključi u Secrets portala kad mu trebaju.
    """
    try:
        return _tekst(st.secrets.get("TESTOVI_DIJAGNOSTIKA")).lower() in ("da", "1", "true")
    except Exception:                                   # noqa: BLE001 — nema Secrets
        return False


def prikazi_pomoc(st, sheet, test, zadaci, ucenik_id: str) -> None:
    """Blok „💡 Pomoć pri učenju" unutar rješavanja testa.

    Ništa ovdje ne smije srušiti test — sve greške se pretvaraju u kratku poruku.
    """
    if not _ukljuceno(st, test) or not zadaci:
        return
    if not ima_kljuc(st):
        # Učenik NE vidi nikakvo tehničko objašnjenje — samo Caki, i to ako uključi dijagnostiku.
        if dijagnostika_ukljucena(st):
            st.caption("🔧 [samo za Cakija] Pomoć je uključena, ali u Secrets portala nema "
                       "`DEEPSEEK_API_KEY`.")
        return

    test_id = _tekst(test.get("test_id"))
    try:
        log = load_log(sheet)
    except Exception:                                   # noqa: BLE001
        log = []
    iskoristeno = broj_pitanja(log, test_id, ucenik_id)
    ostalo = max(0, MAX_PITANJA - iskoristeno)

    # 22.10.2026. (Cakijev zahtjev): pomoć stoji u DESNOJ koloni (1/3), uvijek otvorena i
    # ograničene visine — ne raste s brojem zadataka i ostaje pri ruci dok se skrola.
    with st.container(border=True, height=560):
        st.markdown(f"#### 💡 Pomoć pri učenju — {IME_BOTA}")
        st.caption(f"Pitaj me za **sljedeći korak** ili **pravilo**. Rješenje ne pišem — "
                   f"to je tvoj dio posla. Pitanja: {iskoristeno}/{MAX_PITANJA}.")
        if ostalo <= 0:
            st.info("Iskoristio/la si sva pitanja za ovaj test. Pokušaj sam — ako zapneš, "
                    "javi se profesoru na satu.")
            return

        odabir = st.selectbox(
            "Za koji zadatak?", list(range(len(zadaci))),
            format_func=lambda i: f"Zadatak {i + 1}", key=f"pom_zad_{test_id}")
        razina = st.radio("Što ti treba?", RAZINE, horizontal=True, key=f"pom_raz_{test_id}")
        pitanje = st.text_input("Tvoje pitanje (npr. „odakle početi?”)",
                                key=f"pom_q_{test_id}")

        if st.button("💬 Pitaj", key=f"pom_pos_{test_id}"):
            zadatak = zadaci[odabir]
            try:
                odgovor = pitaj_ai(st.secrets["DEEPSEEK_API_KEY"], zadatak, razina,
                                   cjelina=_tekst(test.get("predmet")))
            except Exception as e:                      # noqa: BLE001
                st.warning(f"Pomoć trenutno nije dostupna ({e}). Test nastavi normalno.")
                return

            filtrirano = izgleda_kao_rjesenje(odgovor, kljuc_iz_testa(zadatak))
            prikaz = GENERICKI if filtrirano else odgovor

            try:
                upisi_pitanje(
                    sheet, test_id=test_id, ucenik_id=ucenik_id,
                    zadatak_id=_tekst(zadatak.get("id")),
                    zadatak=_tekst(zadatak.get("tekst")), razina=razina,
                    pitanje=pitanje or f"{razina} (bez teksta)",
                    odgovor=prikaz, filtrirano=filtrirano, model=MODEL)
            except Exception:                           # noqa: BLE001 — log ne smije blokirati
                pass

            st.session_state[f"pom_odg_{test_id}"] = prikaz
            st.rerun()

        odgovor_spremljen = st.session_state.get(f"pom_odg_{test_id}")
        if odgovor_spremljen:
            st.success(odgovor_spremljen)


__all__ = [
    "MODEL", "MAX_PITANJA", "LOG_TAB", "LOG_HEADERS", "IME_BOTA", "RAZINE",
    "ima_kljuc", "dijagnostika_ukljucena", "sastavi_uputu", "pitaj_ai", "izgleda_kao_rjesenje", "kljuc_iz_testa",
    "load_log", "osiguraj_log_tab", "broj_pitanja", "novi_id", "upisi_pitanje",
    "prikazi_pomoc",
]
