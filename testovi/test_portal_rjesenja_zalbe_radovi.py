"""
Moj CAKI: Cakijeve prijave od 23.11.2026. (testni račun OH3229, test „MATURA A (demo2)"):

1. Zatvoren test, a učenik vidi „Rješenja će biti dostupna nakon isteka roka".
2. Zato nema ni žalbe (uz to je u portalu nedostajao `zalbe.py`, pa je obrazac tiho nestajao).
3. Slika se „poslala" 4 puta, a na Driveu je nema; izvještaj kaže „čeka pregled".

Ime datoteke je drukčije nego u caki-testovi namjerno (pytest iz CAKI_razvoj ne smije naći dvije
test-datoteke istog imena). Fixture `upis_dozvoljen` je ovdje, ne u conftestu, iz istog razloga.

Pokreni:  python -m pytest testovi/test_portal_rjesenja_zalbe_radovi.py -q   (iz caki-booking-termina)
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import date

import pytest

KORIJEN = pathlib.Path(__file__).resolve().parents[1]
for _p in (KORIJEN, KORIJEN / "testovi"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import dodjele  # noqa: E402
import fake_gspread  # noqa: E402
import radovi_v2 as radovi  # noqa: E402
import tablice  # noqa: E402


@pytest.fixture
def upis_dozvoljen():
    staro = tablice.PISANJE
    tablice.postavi_pisanje(True)
    yield
    tablice.postavi_pisanje(staro)


# ------------------------------------------------------------------ 1. zatvoren = zatvoren

def test_dodan_danas_zatvoren_test_je_zatvoren():
    dodjela = {"dodijeljeno": "2026-11-23T09:00:00"}
    d = {"status": "zatvoren", "rok_od": "2026-11-01", "rok_do": "2026-11-10"}
    assert dodjele.stanje_roka(dodjela, d, danas=date(2026, 11, 23)) == "zatvoren"
    d["status"] = "objavljen"
    assert dodjele.stanje_roka(dodjela, d, danas=date(2026, 11, 23)) == "otvoren"


# ------------------------------------------------------------------ 3. slanje rada

def test_drive_odbio_nista_se_ne_zapisuje(upis_dozvoljen):
    s = fake_gspread.FakeSpreadsheet()
    s.dodaj("Radovi", tablice.ZAGLAVLJA["Radovi"], [])
    rez = radovi.posalji_ucenikov_rad(
        s, pokusaj_id="P-1", ucenik_id="OH3229", bajtovi=b"x", naziv_datoteke="D.jpg", folder="F",
        ucitaj=lambda *a, **k: ("", "Slanje u Drive nije uspjelo: [404 notFound]"))
    assert rez["ok"] is False and "notFound" in rez["tehnicki"]
    assert tablice.ucitaj(s, "Radovi") == []


# ------------------------------------------------------------------ 1+2. kartica u portalu

APP = '''
import json, sys
sys.path.insert(0, {korijen!r}); sys.path.insert(0, {testovi!r})
import streamlit as st
import fake_gspread, tablice, testovi_v2
from datetime import date

if "_sheet" not in st.session_state:
    danas = date.today().isoformat()
    zadaci = [{{"id": "Z1", "tekst": "Koliko je $2+2$?", "odgovor": "4", "bodovi": 1,
               "tip": "kratki_odgovor"}},
              {{"id": "Z2", "tekst": "Odaberi", "odgovor": "B", "bodovi": 1,
               "tip": "visestruki_izbor", "opcije": ["1", "2", "3", "4"]}}]
    s = fake_gspread.FakeSpreadsheet()
    s.dodaj("Definicije_testova", tablice.ZAGLAVLJA["Definicije_testova"], [{{
        "definicija_id": "T1", "naziv": "MATURA A (demo2)", "status": st.session_state["_status"],
        "rok_od": "2026-11-01", "rok_do": "2026-11-10", "trajanje_min": 70, "broj_zadataka": 2,
        "bodovi_ukupno": 2, "zadaci_json": json.dumps(zadaci),
        "student_view_json": json.dumps({{"rjesenja": "pri_predaji", "bodovi": "pri_predaji"}})}}])
    s.dodaj("Dodjele_ispita", tablice.ZAGLAVLJA["Dodjele_ispita"], [{{
        "dodjela_id": "D1", "definicija_id": "T1", "ucenik_id": "OH3229",
        "dodijeljeno": danas + "T09:00:00"}}])
    s.dodaj("Pokusaji", tablice.ZAGLAVLJA["Pokusaji"], [{{
        "pokusaj_id": "P1", "dodjela_id": "D1", "definicija_id": "T1", "ucenik_id": "OH3229",
        "status": "po_isteku", "bodovi": 0, "bodovi_max": 2, "predaja": danas + "T10:10:00",
        "odgovori_json": "{{}}", "zadaci_json": json.dumps(zadaci)}}])
    for t in ("Zalbe", "Radovi", "Ocjene_zadataka", "Izmjene_ocjena", "Dnevnik_radnji"):
        s.dodaj(t, tablice.ZAGLAVLJA[t], [])
    st.session_state["_sheet"] = s
testovi_v2.prikazi_testove(st, st.session_state["_sheet"], "OH3229")
'''


def _app(tmp_path, status):
    from streamlit.testing.v1 import AppTest

    skripta = tmp_path / "kartica.py"
    skripta.write_text(APP.format(korijen=str(KORIJEN), testovi=str(KORIJEN / "testovi")),
                       encoding="utf-8")
    at = AppTest.from_file(str(skripta), default_timeout=60)
    at.session_state["_status"] = status
    return at.run()


def test_otvoren_test_ne_pokazuje_rjesenja(tmp_path):
    at = _app(tmp_path, "objavljen")
    assert not at.exception
    assert any("nakon isteka roka" in c.value for c in at.caption)
    assert not [e for e in at.expander if e.label.startswith("Zadatak")]


def test_zatvoren_test_pokazuje_zadatke_i_zalbu(tmp_path):
    at = _app(tmp_path, "zatvoren")
    assert not at.exception, [str(e.value) for e in at.exception]
    assert [e.label for e in at.expander if e.label.startswith("Zadatak")] == [
        "Zadatak 1 — pregled", "Zadatak 2 — pregled"]
    polja = [t for t in at.text_area if "Žalba" in t.label]
    assert len(polja) == 2

    polja[0].input("Moj odgovor je točan.")
    [b for b in at.button if b.label == "Pošalji žalbu"][0].click()
    at.run()
    zalbe = tablice.ucitaj(at.session_state["_sheet"], "Zalbe")
    assert [(z["pokusaj_id"], z["zadatak_id"], z["status"]) for z in zalbe] == [
        ("P1", "Z1", "podnesena")]
