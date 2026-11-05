"""
CAKI testovi v2 — `ocjenjivanje.py`
TRI SLOJA, JASNO ODVOJENA (Cakijeva odluka 14):

  1. **string** — normalizacija (razmaci, zarez/točka, velika slova, jedinice)
  2. **SymPy** — matematička ekvivalencija (1/2 = 0.5 = 2/4, 2x+1 = 1+2x)
  3. **AI** — samo **prijedlog** uz obrazloženje; nikad ne zaključuje sam

Ako nijedan sloj nije siguran, zadatak dobiva oznaku **„?"** i čeka **profesora** — to je i zakonski
(GDPR čl. 22: automatska odluka mora imati ljudsku provjeru) i pedagoški ispravno.
"""
from __future__ import annotations

import re

import model

IZVOR_STRING = "string"
IZVOR_SYMPY = "sympy"
IZVOR_AI = "ai"
IZVOR_PROFESOR = "profesor"
IZVOR_NEMA = "nema"

# jedinice koje se odbacuju pri usporedbi brojeva (matematika/fizika)
JEDINICE = (
    "cm2", "cm3", "dm2", "dm3", "m2", "m3", "mm2", "mm3", "km2", "km3",
    "cm", "dm", "mm", "km", "kg", "mg", "g", "ms", "min", "h", "s", "l", "ml", "dl",
    "n", "j", "w", "kw", "pa", "kpa", "hz", "khz", "v", "mv", "a", "ma", "ω", "ohm",
    "m", "°c", "k", "mol", "m/s", "km/h", "m/s2", "m/s²", "kg/m3", "kg/m³",
)

try:                                                   # SymPy je u bazi, ali ne mora biti svugdje
    import sympy as _sp
    from sympy.parsing.sympy_parser import (           # „2x+1" → 2*x+1 (implicitno množenje)
        implicit_multiplication_application, parse_expr, standard_transformations)
    _TRANSFORMACIJE = standard_transformations + (implicit_multiplication_application,)
except Exception:                                      # noqa: BLE001
    _sp = None
    _TRANSFORMACIJE = ()


# ------------------------------------------------------------------ 1. sloj: string

def normalizuj(tekst) -> str:
    """Usporediv oblik: bez razmaka, `,`→`.`, bez jedinica, mala slova, bez LaTeX ukrasa."""
    s = model.tekst(tekst)
    if not s:
        return ""
    s = s.replace("\u2212", "-").replace("\u00a0", " ").replace("\u2009", " ")
    s = re.sub(r"\\[,;:! ]", "", s)                    # \, \; \: u LaTeXu
    s = re.sub(r"\\text\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\mathrm\{([^{}]*)\}", r"\1", s)
    s = s.replace("$", "").replace("\\left", "").replace("\\right", "")
    s = s.replace("\\cdot", "*").replace("\\times", "*").replace("\\div", "/")
    s = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", s)
    s = re.sub(r"\s+", "", s)
    s = s.replace(",", ".")
    s = s.lower()
    for j in JEDINICE:
        j2 = j.replace(" ", "")
        if s.endswith(j2) and len(s) > len(j2):
            s = s[: -len(j2)]
            break
    return s.strip(".")


def _kao_broj(tekst):
    """Broj iz stringa („1/2", „0.5", „-3") ili None."""
    s = normalizuj(tekst).replace(" ", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    m = re.fullmatch(r"\(?(-?\d+(?:\.\d+)?)\)?/\(?(-?\d+(?:\.\d+)?)\)?", s)
    if m:
        try:
            nazivnik = float(m.group(2))
            return float(m.group(1)) / nazivnik if nazivnik else None
        except (ValueError, ZeroDivisionError):
            return None
    return None


def tocan_string(kljuc, odgovor, tolerancija: float = 1e-9) -> bool:
    """Prvi sloj: je li odgovor jednak ključu nakon normalizacije (broj ili tekst)."""
    try:
        _rez = _provjera().uporedi(kljuc, odgovor)
        if _rez.get("tocno") is not None:
            return bool(_rez["tocno"])
    except Exception:                       # noqa: BLE001
        pass
    a, b = normalizuj(kljuc), normalizuj(odgovor)
    if not a or not b:
        return False
    if a == b:
        return True
    # „x=2" u bazi, „2" kod učenika (i obrnuto) — najčešći slučaj u našoj bazi
    if bez_varijable(a) == bez_varijable(b) and bez_varijable(a):
        return True
    broj_a, broj_b = _kao_broj(a), _kao_broj(b)
    if broj_a is not None and broj_b is not None:
        return abs(broj_a - broj_b) <= tolerancija
    # više prihvatljivih oblika u ključu: "2 | -2" ili "2; -2"
    for dio in re.split(r"[|;]", a):
        if dio.strip() and (dio.strip() == b or
                            ((_kao_broj(dio) is not None and broj_b is not None
                              and abs(_kao_broj(dio) - broj_b) <= tolerancija))):
            return True
    return False



def bez_varijable(tekst) -> str:
    """„x=2" / „y = -3" / „t=5 s" → desna strana. Ako nema „=", vraća isto."""
    s = normalizuj(tekst)
    if not s or "=" not in s:
        return s
    lijevo, _, desno = s.partition("=")
    if lijevo and len(lijevo) <= 4 and re.fullmatch(r"[a-z][a-z0-9_]*", lijevo):
        return desno
    return s


def _jednadzba(tekst):
    """Za SymPy: „x=2" pretvori u izraz „x-2" (usporedba s nulom)."""
    s = model.tekst(tekst)
    if "=" not in s:
        return None
    lijevo, _, desno = s.partition("=")
    a, b = _izraz(lijevo), _izraz(desno)
    if a is None or b is None:
        return None
    return a - b


# ------------------------------------------------------------------ 2. sloj: SymPy

def _izraz(tekst):
    if _sp is None:
        return None
    s = model.tekst(tekst)
    if not s:
        return None
    s = (s.replace("$", "").replace("\\left", "").replace("\\right", "")
          .replace("\\cdot", "*").replace("\\times", "*").replace(",", ".")
          .replace("^", "**").replace("{", "(").replace("}", ")"))
    s = re.sub(r"\\frac\(([^()]*)\)\(([^()]*)\)", r"((\1)/(\2))", s)
    s = s.replace("\\", "")
    try:
        return parse_expr(s, transformations=_TRANSFORMACIJE, evaluate=True)
    except Exception:                                  # noqa: BLE001 — nije izraz, preskoči sloj
        try:
            return _sp.sympify(s, evaluate=True)
        except Exception:                              # noqa: BLE001
            return None



def rjesenja(tekst) -> set | None:
    """Skup rješenja jednadžbe („2x+1=5" → {2}); None ako nije jednadžba ili SymPy nema."""
    if _sp is None:
        return None
    s = model.tekst(tekst)
    if "=" not in s:
        return None
    izraz = _jednadzba(s)
    if izraz is None:
        return None
    try:
        skup = _sp.solve(izraz)
        return set(skup) if skup else None
    except Exception:                                  # noqa: BLE001
        return None


def _vrijednost(tekst):
    """Broj ili izraz kao SymPy vrijednost (za usporedbu s rješenjem)."""
    s = model.tekst(tekst)
    if "=" in s:
        _, _, desno = s.partition("=")
        return _izraz(desno)
    return _izraz(s)


def tocan_sympy(kljuc, odgovor) -> bool:
    """Drugi sloj: matematički ekvivalentni izrazi (1/2 = 0.5, 2x+1 = 1+2x, 2^3 = 8)."""
    a = _jednadzba(kljuc) if "=" in model.tekst(kljuc) else _izraz(kljuc)
    b = _jednadzba(odgovor) if "=" in model.tekst(odgovor) else _izraz(odgovor)
    if a is None or b is None:
        return False
    try:
        if bool(_sp.simplify(a - b) == 0):
            return True
    except Exception:                                  # noqa: BLE001
        pass

    # Jednadžbe: usporedi SKUPOVE RJEŠENJA („2x+1=5" vs „x=2").
    rj_a = rjesenja(kljuc) if "=" in model.tekst(kljuc) else None
    rj_b = rjesenja(odgovor) if "=" in model.tekst(odgovor) else None
    if rj_a and rj_b:
        return rj_a == rj_b
    if rj_a and not rj_b:
        v = _vrijednost(odgovor)
        if v is None:
            return False
        try:
            return all(bool(_sp.simplify(r - v) == 0) for r in rj_a)
        except Exception:                              # noqa: BLE001
            return False
    if rj_b and not rj_a:
        v = _vrijednost(kljuc)
        if v is None:
            return False
        try:
            return all(bool(_sp.simplify(r - v) == 0) for r in rj_b)
        except Exception:                              # noqa: BLE001
            return False
    return False


# ------------------------------------------------------------------ 3. sloj: AI (prijedlog)

def prijedlog_ai(kljuc: str, odgovor: str, tekst_zadatka: str = "", pozovi=None) -> dict | None:
    """AI kao **pomoćnik**: vraća {"tocno": bool, "sigurnost": "visoka/srednja/niska", "zasto": str}.

    Bez `pozovi` (funkcija modela) ili bez ključa — vraća None (sloj se preskače). Nikad ne baca.
    """
    if not pozovi or not model.tekst(odgovor):
        return None
    uputa = (
        "Usporedi učenikov odgovor s točnim rješenjem. Odgovori ISKLJUČIVO JSON-om:\n"
        '{"tocno": true/false, "sigurnost": "visoka|srednja|niska", "zasto": "do 15 riječi"}\n'
        "Ako nisi siguran, stavi sigurnost niska. Ne objašnjavaj izvan JSON-a."
    )
    pitanje = (f"Zadatak: {model.tekst(tekst_zadatka)[:600]}\n"
               f"Točno rješenje: {model.tekst(kljuc)}\nUčenikov odgovor: {model.tekst(odgovor)}")
    try:
        odg = pozovi(uputa, pitanje) or {}
        tekst = str(odg.get("tekst", "")).strip()
        podaci = None
        try:
            import json
            podaci = json.loads(re.sub(r"^```(?:json)?|```$", "", tekst).strip())
        except Exception:                              # noqa: BLE001
            m = re.search(r"\{.*\}", tekst, re.S)
            if m:
                try:
                    import json
                    podaci = json.loads(m.group(0))
                except Exception:                      # noqa: BLE001
                    podaci = None
        if not isinstance(podaci, dict) or "tocno" not in podaci:
            return None
        sig = model.tekst(podaci.get("sigurnost")).lower()
        return {"tocno": bool(podaci.get("tocno")),
                "sigurnost": sig if sig in ("visoka", "srednja", "niska") else "niska",
                "zasto": model.tekst(podaci.get("zasto"))[:160]}
    except Exception:                                  # noqa: BLE001 — AI ne smije rušiti ocjenu
        return None


# ------------------------------------------------------------------ ocjenjivanje zadatka

def je_izbor(zadatak: dict) -> bool:
    return (model.tekst((zadatak or {}).get("tip")) == "visestruki_izbor"
            and len((zadatak or {}).get("opcije") or []) >= 2)


def tocan_izbor(zadatak: dict, odgovor) -> bool:
    """Kod višestrukog izbora uspoređuje se SLOVO, ne tekst."""
    slovo = model.tekst(odgovor).upper()[:1]
    kljuc = model.tekst(zadatak.get("odgovor")).upper()[:1]
    if not slovo:
        return False
    if kljuc:
        return slovo == kljuc
    return False


def ocjeni_zadatak(zadatak: dict, odgovor, *, pozovi=None, dopusti_ai: bool = True) -> dict:
    """Vrati {"tocno", "bodovi", "max", "izvor", "sigurnost", "zasto"}.

    `izvor` kaže **kako** je odlučeno — to je trag koji traži GDPR i obrana od prigovora.
    """
    max_b = model.broj((zadatak or {}).get("bodovi"), 1)
    odg = model.tekst(odgovor)
    kljuc = model.tekst((zadatak or {}).get("odgovor"))

    if not odg:
        return {"tocno": False, "bodovi": 0.0, "max": max_b, "izvor": IZVOR_NEMA,
                "sigurnost": "", "zasto": "nema odgovora"}

    if je_izbor(zadatak):
        tocno = tocan_izbor(zadatak, odg)
        return {"tocno": tocno, "bodovi": max_b if tocno else 0.0, "max": max_b,
                "izvor": IZVOR_STRING, "sigurnost": "visoka", "zasto": ""}

    if tocan_string(kljuc, odg):
        return {"tocno": True, "bodovi": max_b, "max": max_b, "izvor": IZVOR_STRING,
                "sigurnost": "visoka", "zasto": ""}

    if tocan_sympy(kljuc, odg):
        return {"tocno": True, "bodovi": max_b, "max": max_b, "izvor": IZVOR_SYMPY,
                "sigurnost": "visoka", "zasto": ""}

    if dopusti_ai:
        prijedlog = prijedlog_ai(kljuc, odg, model.tekst((zadatak or {}).get("tekst")), pozovi)
        if prijedlog and prijedlog["sigurnost"] == "visoka":
            return {"tocno": prijedlog["tocno"], "bodovi": max_b if prijedlog["tocno"] else 0.0,
                    "max": max_b, "izvor": IZVOR_AI, "sigurnost": "visoka",
                    "zasto": prijedlog["zasto"]}

    # nije sigurno → čeka profesora
    return {"tocno": False, "bodovi": 0.0, "max": max_b, "izvor": "?", "sigurnost": "niska",
            "zasto": "nije moguće automatski odlučiti — provjeri ručno"}


# Tipovi koji odgovor drže kao popis odvojen znakom `|` (vidi `tipovi.ocjeni`)
TIPOVI_S_CRTICOM = ("poredak", "povezivanje", "popuni_praznine")


def _odgovor_za_tip(tip: str, odgovor):
    """Pretvori pohranjeni odgovor u oblik koji `tipovi.ocjeni` očekuje.

    Izvor istine je `tipovi.ocjeni`:
      · `vise_tocnih` — **tekst slova** („AC”), funkcija radi `moj.replace(...)`,
      · `poredak` / `povezivanje` / `popuni_praznine` — dijelovi odvojeni znakom `|`,
      · ostali — tekst kako je upisan.
    """
    if isinstance(odgovor, (list, tuple)):
        if tip == "vise_tocnih":
            return "".join(model.tekst(x) for x in odgovor)      # lista → „AC”
        return "|".join(model.tekst(x) for x in odgovor)

    tekst = model.tekst(odgovor)
    if not tekst:
        return ""
    if tip in TIPOVI_S_CRTICOM and "," in tekst and "|" not in tekst:
        return "|".join(d.strip() for d in tekst.split(","))
    return tekst


def ocjeni_tipom(tip: str, zadatak: dict, odgovor) -> dict | None:
    """Ocjena preko `tipovi.ocjeni()` — `None` ako tip nije podržan (tada staro ponašanje)."""
    try:
        import tipovi

        if tip not in getattr(tipovi, "TIPOVI", {}):
            return None
        return tipovi.ocjeni(tip, zadatak, _odgovor_za_tip(tip, odgovor))
    except Exception:                                   # noqa: BLE001
        return None


def ocjeni_zadatke(zadaci: list[dict], odgovori, *, pozovi=None, dopusti_ai: bool = True) -> dict:
    """Ocijeni cijeli test. `odgovori` = {redni_broj: odgovor} (redni broj u **izmiješanom** testu).

    Vraća {"bodovi", "maks", "detalji": [...], "ceka_profesora": Int}.
    """
    ukupno = maks = 0.0
    detalji, ceka = [], 0
    for i, z in enumerate(zadaci or []):
        odg = (odgovori or {}).get(i)
        if odg is None and isinstance(odgovori, dict):
            odg = (odgovori or {}).get(str(i))
        r = ocjeni_zadatak(z, odg, pozovi=pozovi, dopusti_ai=dopusti_ai)

        # 🤖 AI kao TREĆI sloj: samo ako je ostalo „sumnja" i profesor je dopustio AI za OVAJ test
        if (r.get("izvor") == "?" and dopusti_ai
                and model.tekst(z.get("tip")) in ("kratki_odgovor", "brojcan", "popuni_praznine",
                                                   "povezivanje", "otvoreni_odgovor")):
            try:
                _ai = ai_provjeri_izraz(
                    z.get("odgovor") or z.get("konacan_odgovor"), odg,
                    model.tekst(z.get("tekst")), pozovi=pozovi)
            except Exception:                       # noqa: BLE001
                _ai = None
            if _ai is not None:
                _maks = model.broj(z.get("bodovi"), r.get("max") or 1) or 1
                r = {**r, "tocno": bool(_ai.get("tocno")),
                     "bodovi": float(_maks) if _ai.get("tocno") else 0.0,
                     "izvor": _ai.get("izvor") or IZVOR_AI,
                     "sigurnost": _ai.get("sigurnost") or "srednja",
                     "zasto": model.tekst(_ai.get("zasto")) or r.get("zasto", "")}

        ukupno += r["bodovi"]
        maks += r["max"]
        if r["izvor"] == "?":
            ceka += 1
        detalji.append({"redni_broj": i, "zadatak_id": model.tekst(z.get("id")),
                        "odgovor": model.tekst(odg), **r})
    return {"bodovi": round(ukupno, 2), "maks": round(maks, 2), "detalji": detalji,
            "ceka_profesora": ceka}


def postotak(bodovi, maks) -> int:
    m = model.broj(maks)
    return int(round(100 * model.broj(bodovi) / m)) if m else 0

# ------------------------------------------------------------------ G1: slojevi provjere izraza

_PROVJERA_MODUL = None


def _provjera():
    """Modul s čistom jezgrom (`provjera_odgovora`) — **učitava se po putanji**.

    Zašto po putanji: u istom pytest procesu postoji i v1 `provjera_odgovora` (druga mapa), pa bi
    običan `import` uzeo pogrešan modul i sve bi završilo u „sumnja".
    """
    global _PROVJERA_MODUL
    if _PROVJERA_MODUL is not None:
        return _PROVJERA_MODUL
    import importlib.util
    import sys
    from pathlib import Path

    putanja = Path(__file__).resolve().parent / "provjera_odgovora.py"
    ime = "caki_v2_provjera_odgovora"
    try:
        spec = importlib.util.spec_from_file_location(ime, putanja)
        modul = importlib.util.module_from_spec(spec)
        sys.modules[ime] = modul
        spec.loader.exec_module(modul)
        _PROVJERA_MODUL = modul
    except Exception:                               # noqa: BLE001
        import provjera_odgovora as modul         # rezerva

        _PROVJERA_MODUL = modul
    return _PROVJERA_MODUL


def normalizuj(tekst) -> str:                       # noqa: F811 — namjerno prekriva staru verziju
    """LaTeX → oblik za usporedbu. **Delegira** na `provjera_odgovora.normalizuj()`."""
    try:
        return _provjera().normalizuj(tekst)
    except Exception:                               # noqa: BLE001
        return model.tekst(tekst).strip()


def ocjeni_izraz(tocan, odgovor, *, maks: float = 1.0) -> dict:
    """Provjeri **izraz** protiv konačnog odgovora (slojevi: string → broj → SymPy → numerika).

    Vraća v2 ugovor. `tocno = None` znači **sumnja** → izvor `?` (red čekanja profesora).
    """
    try:
        rez = _provjera().uporedi(tocan, odgovor)
    except Exception as e:                          # noqa: BLE001
        return {"tocno": None, "bodovi": 0.0, "max": maks, "izvor": IZVOR_NEMA,
                "sigurnost": "nema", "zasto": f"Provjera nije moguća: {e}"}

    stanje = rez.get("tocno")
    nacin = model.tekst(rez.get("nacin"))
    if stanje is None:
        return {"tocno": None, "bodovi": 0.0, "max": maks, "izvor": "?",
                "sigurnost": "nema", "zasto": rez.get("zasto") or "Nesigurno — provjeri ručno."}
    izvor = {"string": IZVOR_STRING, "broj": IZVOR_STRING,
             "sympy": IZVOR_SYMPY, "numericki": IZVOR_SYMPY}.get(nacin, IZVOR_STRING)
    return {"tocno": bool(stanje), "bodovi": float(maks) if stanje else 0.0, "max": maks,
            "izvor": izvor, "sigurnost": "visoka" if stanje is not None else "nema",
            "zasto": rez.get("zasto") or ""}


UPUTA_AI = (
    "Usporedi dva matematička izraza i reci jesu li ALGEBARSKI JEDNAKA. "
    "Ne računaj numerički primjer — provjeri jednakost izraza. "
    "Odgovori ISKLJUČIVO JSON: {\"jednako\": true|false|\"nesigurno\", \"razlog\": \"...\"}"
)


def ai_provjeri_izraz(tocan, odgovor, tekst: str = "", *, pozovi=None,
                      kljuc: str = "", tajna: str = "") -> dict | None:
    """AI kao **treći** sloj. `None` = AI nije dostupan/nije siguran.

    `pozovi(poruke, kljuc, tajna)` je injektabilan (testovi bez mreže).
    """
    import json

    poruke = [{"role": "system", "content": UPUTA_AI},
              {"role": "user", "content": f"ZADATAK: {model.tekst(tekst)}\n"
                                          f"TOČNO: {model.tekst(tocan)}\n"
                                          f"UČENIK: {model.tekst(odgovor)}"}]
    try:
        if pozovi is None:
            import ai_pomoc

            odgovor_ai, greska = ai_pomoc.pitaj(poruke, kljuc=kljuc, tajna=tajna)
        else:
            odgovor_ai, greska = pozovi(poruke, kljuc, tajna)
    except Exception:                               # noqa: BLE001
        return None
    if greska or not model.tekst(odgovor_ai):
        return None
    try:
        podaci = json.loads(odgovor_ai[odgovor_ai.index("{"):odgovor_ai.rindex("}") + 1])
    except Exception:                               # noqa: BLE001
        return None
    jednako = podaci.get("jednako")
    if isinstance(jednako, str):
        if jednako.lower() in ("true", "da", "jednako"):
            jednako = True
        elif jednako.lower() in ("false", "ne", "nije"):
            jednako = False
        else:
            jednako = None
    if jednako is None:
        return None
    return {"tocno": bool(jednako), "izvor": IZVOR_AI, "sigurnost": "srednja",
            "zasto": model.tekst(podaci.get("razlog"))}

