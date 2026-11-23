"""
Testovi za dva popravka od 21.11.2026.:

1. MathLive polje za kratke odgovore (`unos_odgovora.py`) — editor se nije prikazivao jer je
   `mathfield()` dobivao argumente koje verzija 0.0.3 ne poznaje (TypeError → tihi fallback).
2. Slanje slike/PDF-a postupka u Drive (`drive.py`) — dozvola `drive.file` ne smije pisati u
   ručno napravljenu mapu; poruka o grešci nije govorila zašto.

Portal (Moj CAKI) koristi ISTE module za v2 testove (`unos_odgovora.py`, `drive.py`) — kopije iz
caki-testovi, prenesene 23.11.2026. Ovo je ista provjera, da se kopije ne raziđu.
Datoteka se zove drukčije nego u caki-testovi namjerno: dvije test-datoteke istog imena ruše
pytest kad se pokreće iz CAKI_razvoj („import file mismatch").

Pokreni:  python -m pytest testovi/test_portal_mathlive_i_drive.py -q   (iz mape caki-booking-termina)
"""
from __future__ import annotations

import pathlib
import sys

_KORIJEN = pathlib.Path(__file__).resolve().parents[1]
if str(_KORIJEN) not in sys.path:
    sys.path.insert(0, str(_KORIJEN))

import inspect
import json

import pytest

import drive
import unos_odgovora


# ------------------------------------------------------------------ 1. MathLive

def _mathfield_003(title="Eqn", value="3+2", enable_edit=True, upright=True,
                   mathml_preview=False, key=None):
    """Isti potpis kao `st_mathlive.mathfield` u verziji 0.0.3 (bez default_mode/height)."""
    return ["x^2", "<math>…</math>"]


def test_argumenti_odgovaraju_verziji_0_0_3():
    arg = unos_odgovora._poziv_argumenti(_mathfield_003, "2x", "k1")
    assert "default_mode" not in arg and "height" not in arg
    assert arg["value"] == "2x" and arg["key"] == "k1"
    _mathfield_003(**arg)                     # ne smije baciti TypeError


def test_argumenti_za_novije_verzije_prolaze():
    def novija(value="", key=None, default_mode="math", height=80):
        return "a"
    arg = unos_odgovora._poziv_argumenti(novija, "", "k")
    assert arg["default_mode"] == "math" and arg["height"] == 90
    assert "title" not in arg


def test_argumenti_s_kwargs_salje_sve():
    def sve(**kw):
        return kw
    arg = unos_odgovora._poziv_argumenti(sve, "1", "k")
    assert set(arg) >= {"value", "key", "default_mode", "height"}


def test_instalirani_paket_prima_nase_argumente():
    """Ako je paket instaliran, stvarni potpis mora prihvatiti ono što šaljemo."""
    if unos_odgovora.mathfield is None:
        pytest.skip("streamlit-mathlive nije instaliran")
    arg = unos_odgovora._poziv_argumenti(unos_odgovora.mathfield, "", "k")
    inspect.signature(unos_odgovora.mathfield).bind(**arg)   # baci TypeError ako ne valja


def test_rezultat_par_uzima_samo_latex():
    assert unos_odgovora._latex_iz_rezultata(["\\frac{1}{2}", "<math/>"], "") == "\\frac{1}{2}"


def test_rezultat_none_cuva_prethodni_odgovor():
    # povratak na već odgovoreno pitanje: komponenta još nije javila ništa
    assert unos_odgovora._latex_iz_rezultata([None, None], "x=3") == "x=3"
    assert unos_odgovora._latex_iz_rezultata(None, "x=3") == "x=3"


def test_rezultat_nikad_nije_tekst_liste():
    assert unos_odgovora._latex_iz_rezultata([None, None], "") == ""
    assert "[" not in unos_odgovora._latex_iz_rezultata(["5", None], "")


def test_rezultat_prazan_string_brise_odgovor():
    # učenik je namjerno obrisao polje
    assert unos_odgovora._latex_iz_rezultata(["", ""], "x=3") == ""


def test_rezultat_obican_string():
    assert unos_odgovora._latex_iz_rezultata("  7 ", "") == "7"


def test_unos_koristi_mathlive_bez_fallbacka(monkeypatch):
    pozivi = []

    def lazni(title="Eqn", value="3+2", enable_edit=True, upright=True,
              mathml_preview=False, key=None):
        pozivi.append(value)
        return ["2x+1", "<math/>"]

    monkeypatch.setattr(unos_odgovora, "mathfield", lazni)
    tekst = []
    monkeypatch.setattr(unos_odgovora.st, "text_input",
                        lambda *a, **k: tekst.append(1) or "")
    monkeypatch.setattr(unos_odgovora.st, "markdown", lambda *a, **k: None)
    assert unos_odgovora.unos_odgovora("Odgovor", "k", "x") == "2x+1"
    assert pozivi == ["x"] and not tekst          # tekstualno polje se NIJE pojavilo


def test_unos_fallback_kad_komponenta_pukne(monkeypatch):
    def puca(**kw):
        raise RuntimeError("iframe")
    monkeypatch.setattr(unos_odgovora, "mathfield", puca)
    monkeypatch.setattr(unos_odgovora.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(unos_odgovora.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(unos_odgovora.st, "text_input", lambda *a, **k: " 4 ")
    assert unos_odgovora.unos_odgovora("Odgovor", "k") == "4"


# ------------------------------------------------------------------ 2. Drive

def test_scope_nije_drive_file():
    assert drive.SCOPES == ["https://www.googleapis.com/auth/drive"]


class _Resp:
    def __init__(self, status):
        self.status = status


class _HttpError(Exception):
    def __init__(self, status, reason):
        super().__init__("http")
        self.resp = _Resp(status)
        self.content = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()


@pytest.mark.parametrize("razlog,dio", [
    ("notFound", "RADOVI_FOLDER_ID"),
    ("storageQuotaExceeded", "DIJELJENOM"),
    ("insufficientFilePermissions", "Contributor"),
])
def test_opis_greske_kaze_zasto(razlog, dio):
    opis = drive.opis_greske(_HttpError(404, razlog))
    assert dio in opis and razlog in opis


def test_opis_greske_nepoznat_razlog():
    opis = drive.opis_greske(_HttpError(500, "backendError"))
    assert "500" in opis and "backendError" in opis


def test_opis_greske_obicna_iznimka():
    # 23.11.: uz ime greške ide i njezina poruka (prije samo „ValueError.")
    assert drive.opis_greske(ValueError("x")) == "ValueError: x"
    assert drive.opis_greske(ValueError()) == "ValueError."


def test_ucitaj_vraca_razlog_iz_googlea():
    class Servis:
        def files(self):
            return self

        def create(self, **kw):
            return self

        def execute(self):
            raise _HttpError(404, "notFound")

    veza, greska = drive.ucitaj(b"abc", "a.jpg", folder="F", servis=Servis())
    assert veza == "" and "notFound" in greska and "RADOVI_FOLDER_ID" in greska


def test_ucitaj_uspjeh_salje_u_mapu():
    poslano = {}

    class Servis:
        def files(self):
            return self

        def create(self, **kw):
            poslano.update(kw)
            return self

        def execute(self):
            return {"id": "1", "webViewLink": "https://drive/x"}

    veza, greska = drive.ucitaj(b"abc", "rad.pdf", folder="F", servis=Servis())
    assert (veza, greska) == ("https://drive/x", "")
    assert poslano["body"]["parents"] == ["F"] and poslano["supportsAllDrives"] is True
