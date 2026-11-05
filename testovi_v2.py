"""
CAKI — testovi_v2.py  (05.11.2026., Claude)

MOST prema caki-testovi (v2): Moj CAKI ostaje JEDINI ulaz za učenika (Cakijeva odluka,
05.11.2026. — v. TRACKER §5). Ovaj modul NE otvara novi portal ni prijavu — samo čita v2
dodjele/definicije/pokušaje (isti CRM Sheet, tabovi Definicije_testova/Dodjele_ispita/
Pokusaji/Ocjene_zadataka) i iscrtava ih unutar postojeće kartice `📝 Testovi` u portal_ui.py,
pozivajući VEĆ GOTOV ekran rješavanja iz caki-testovi (`ekran_ucenika_v2.prikazi`) — ništa se
ne piše nanovo, samo se spaja.

Zašto zaseban modul (ne izravno u portal_ui.py): ista podjela kao `testovi_online.py` za v1 —
portal_ui.py samo poziva `testovi_za_ucenika()`/`prikazi_testove()`, logika ostaje ovdje.

OVISNOSTI (kopirane iz caki-testovi 05.11.2026., v. upute/UPDATE_05-11_v2_bridge.md):
    model, tablice, definicije, dodjele, provedba, ocjenjivanje, rjesavanje, unos_odgovora,
    tabele, zavrsetak, drive, ai_pomoc_v2 (=ai_pomoc), radovi_v2 (=radovi),
    slike_zadataka_v2 (=slike_zadataka), ekran_ucenika_v2 (=ekran_ucenika).
    `sheet` koji se predaje u sve funkcije ovdje MORA biti isti CRM Sheet objekt koji portal
    već otvara (npr. `_init_sheet_testovi()`) — v2 tabovi su u ISTOM Sheetu kao i v1 (SHEET_ID),
    NE treba nova vjerodajnica ni novi secret.

NE KORISTITI `veza.py` iz caki-testovi ovdje — taj modul otvara Sheet po SVOM secretu
(`CRM_SHEET_ID`), koji portal_ui.py nema. Portal već ima svoju vlastitu konekciju.
"""
from __future__ import annotations

import definicije
import dodjele
import drive
import ekran_ucenika_v2 as ekran_ucenika
import model
import provedba
import radovi_v2 as radovi
import tablice
import zavrsetak

# 05.11.2026. (Claude): NE treba dodatna st.cache_data predmemorija ovdje za "dvostruko
# čitanje" (brojač + prikaz zovu testovi_za_ucenika() odvojeno). `tablice.ucitaj()` VEĆ ima
# svoju TTL predmemoriju (tablice.py, CACHE_TTL_S = 30 s, ključ (id(sheet), tab), deli se preko
# cijelog procesa) — dva poziva unutar istog prikaza kartice pogode isti cache, nema dva
# stvarna Google poziva. Provjereno čitanjem koda prije nego se ovo "popravilo" nepotrebno.

# KRITIČNO (05.11.2026., Claude — uočeno prije isporuke, nije od Cakija prijavljen bug):
# `tablice.PISANJE` je sigurnosni prekidač za upis u ŽIVU bazu, zadano False. U caki-testovi
# ga na True postavlja `app.py` (admin app) pri učitavanju — ali app.py se OVDJE ne učitava
# (Moj CAKI nikad ne smije pokrenuti admin app), pa bi bez ovoga SVAKI upis iz v2 motora
# (autosave, predaja testa, prilog rada) bacao PermissionError u Moj CAKI, dok bi ČITANJE
# (popis testova) tiho radilo — bug koji bi se otkrio tek kad učenik stvarno pokuša predati.
tablice.postavi_pisanje(True)

KLJUC_AKTIVNI = "v2b_aktivni"


def _pokusaj_za(sheet, dodjela: dict):
    """Aktivni pokušaj ili zadnji predani za tu dodjelu (isto kao caki-testovi/pages/1_Ucenik.py)."""
    did = model.tekst(dodjela.get("dodjela_id"))
    try:
        return provedba.aktivni(sheet, did) or provedba.zadnji_predani(sheet, did)
    except Exception:                                   # noqa: BLE001 — jedan pokušaj ne smije srušiti popis
        return None


def testovi_za_ucenika(sheet, ucenik_id: str) -> list[dict]:
    """Dodjele v2 testova za `ucenik_id`, obogaćene definicijom i pokušajem.

    Vraća [] (ne baca iznimku) ako tabovi još ne postoje ili je Sheet nedostupan — portal_ui.py
    tad jednostavno ne prikazuje v2 testove, kao da ih nema (analogno `online_greska` uzorku
    za v1 u portal_ui.py).
    """
    try:
        dodjele_moje = dodjele.za_ucenika(sheet, ucenik_id)
    except Exception:                                   # noqa: BLE001
        return []
    izlaz = []
    for d in dodjele_moje:
        try:
            defin = definicije.po_id(sheet, model.tekst(d.get("definicija_id")))
        except Exception:                               # noqa: BLE001
            defin = None
        if not defin:
            continue
        pokusaj = _pokusaj_za(sheet, d)
        rjeseno = bool(pokusaj and zavrsetak.je_zavrsen(pokusaj))
        izlaz.append({"dodjela": d, "definicija": defin, "pokusaj": pokusaj, "rjeseno": rjeseno})
    return izlaz


def _pregled_rjesenja(st, sheet, dodjela: dict, definicija: dict, pokusaj: dict) -> None:
    """Prikaži rješenja SAMO ono što Student View dopušta (isto pravilo kao u caki-testovi)."""
    view = definicija.get("student_view_json")
    rok_prosao = dodjele.stanje_roka(dodjela, definicija) == "zatvoren"
    smije_rjesenja = definicije.smije_vidjeti(view, "rjesenja", predano=True, rok_prosao=rok_prosao)
    smije_video = definicije.smije_vidjeti(view, "video", predano=True, rok_prosao=rok_prosao)
    smije_bodove = definicije.smije_vidjeti(view, "bodovi", predano=True, rok_prosao=rok_prosao)

    if not smije_rjesenja:
        st.caption("Rješenja će biti dostupna "
                   + ("nakon isteka roka." if rok_prosao is False else "kasnije."))
        return
    ekran_ucenika.prikazi_pregled_rjesenja(
        st, definicije.zadaci(definicija), provedba.odgovori(pokusaj),
        pokazi_rjesenja=True, pokazi_video=smije_video, pokazi_bodove=smije_bodove,
        sheet=sheet, pokusaj=pokusaj, ucenik_id=model.tekst(dodjela.get("ucenik_id")))


def _kartica(st, sheet, stavka: dict, ucenik_id: str) -> None:
    dodjela, definicija, pokusaj = stavka["dodjela"], stavka["definicija"], stavka["pokusaj"]
    naziv = model.tekst(definicija.get("naziv")) or model.tekst(definicija.get("definicija_id"))
    trajanje = model.cijeli(definicija.get("trajanje_min"), 45)
    bodovi = model.broj(definicija.get("bodovi_ukupno"))
    stanje = dodjele.stanje_roka(dodjela, definicija)
    rok = dodjele.rok_dodjele(dodjela, definicija)
    kljuc = model.tekst(dodjela.get("dodjela_id"))

    with st.container(border=True):
        st.markdown(f"### {naziv}")
        st.caption(f"{model.cijeli(definicija.get('broj_zadataka'), 0)} zadataka · "
                   f"{bodovi:g} bodova · {trajanje} min")
        st.caption(f"Rok: **{model.datum_hr(rok['od']) or '—'}** – "
                   f"**{model.datum_hr(rok['do']) or '—'}**")

        with st.expander("📷 Priloži svoj rad (fotografija ili sken)"):
            _pid = ""
            _svi = provedba.pokusaji_ucenika(sheet, kljuc) if hasattr(provedba, "pokusaji_ucenika") else []
            if _svi:
                _pid = model.tekst(_svi[-1].get("pokusaj_id"))
            if not _pid:
                st.caption("Rad možeš priložiti kad test počne. Fotografiraj papir i pošalji ovdje.")
            else:
                _postojeci = radovi.za_pokusaj(sheet, _pid)
                if _postojeci:
                    st.caption("Već priloženo: " + radovi.stanje(_postojeci))
                _datoteka = st.file_uploader("Odaberi fotografiju ili PDF", type=["png", "jpg", "jpeg", "pdf"],
                                             key=f"v2b_rad_{kljuc}")
                _link = st.text_input("…ili zalijepi poveznicu (npr. s mobitela)",
                                      key=f"v2b_rad_link_{kljuc}")
                if st.button("📤 Pošalji rad", key=f"v2b_rad_salji_{kljuc}"):
                    try:
                        _veza = ""
                        if _datoteka is not None:
                            _bajtovi = _datoteka.getvalue()
                            _folder = drive.folder_id(st.secrets)
                            _veza, _greska = drive.ucitaj(_bajtovi, radovi.sef_datoteke(_datoteka.name),
                                                          folder=_folder)
                            if _greska:
                                # 05.11.2026. (Claude): `drive.ucitaj` vrati tehničnu poruku
                                # (npr. "RADOVI_FOLDER_ID") — učeniku ne pokazujemo ime secreta,
                                # samo da rad ide dalje (poveznica/sirovi sadržaj kao zamjena).
                                st.warning("Fotografija trenutno nije poslana na Drive — "
                                           "rad će se ipak spremiti. Pošalji i poveznicu "
                                           "ispod ako imaš (npr. s mobitela).")
                                st.caption(f"Tehnički detalj (za Cakija): {_greska}")
                        radovi.dodaj_ucenikov_rad(
                            sheet, pokusaj_id=_pid, ucenik_id=ucenik_id,
                            veza=_veza or model.tekst(_link),
                            sadrzaj=(_datoteka.getvalue() if (_datoteka and not _veza) else None),
                            naziv=(_datoteka.name if _datoteka else "Poveznica"))
                        st.success("Rad je poslan profesoru. ✅")
                        st.rerun()
                    except Exception as e:              # noqa: BLE001
                        st.error(f"Rad nije poslan: {e}")

        if pokusaj and zavrsetak.je_zavrsen(pokusaj):
            if zavrsetak.predan_po_isteku(pokusaj):
                st.warning("⏰ Vrijeme je isteklo — test je automatski predan.")
            bod = model.broj(pokusaj.get("bodovi"))
            maks = model.broj(pokusaj.get("bodovi_max"))
            postotak = int(round(100 * bod / maks)) if maks else 0
            st.success(f"✅ Predano — **{bod:g} / {maks:g}** bodova ({postotak} %)")
            with st.expander("Pogledaj rješenja"):
                _pregled_rjesenja(st, sheet, dodjela, definicija, pokusaj)
        elif stanje != "otvoren":
            st.warning("Rok još nije otvoren ili je prošao — javi se profesoru.")
        else:
            tekst = "▶ Nastavi" if pokusaj else "▶ Počni"
            if st.button(tekst, type="primary", key=f"v2b_{kljuc}"):
                st.session_state[KLJUC_AKTIVNI] = kljuc
                st.rerun()


def prikazi_testove(st, sheet, ucenik_id: str) -> None:
    """Iscrtaj v2 testove za `ucenik_id` unutar postojeće kartice `📝 Testovi`.

    Poziva ga portal_ui.py ODMAH NAKON `online_testovi.prikazi_testove(...)` (v1), tako da
    učenik na istom mjestu vidi i stare i nove testove dok traje migracija — ništa se ne
    gasi naglo. Potpuno samostalno: ako v2 tabovi ne postoje / Sheet zapne, ne prikazuje ništa
    i ne baca iznimku (portal nastavlja raditi kao da v2 ne postoji).
    """
    try:
        moje = testovi_za_ucenika(sheet, ucenik_id)
    except Exception:                                   # noqa: BLE001
        return

    aktivni = st.session_state.get(KLJUC_AKTIVNI)
    if aktivni:
        stavka = next((m for m in moje if model.tekst(m["dodjela"].get("dodjela_id")) == aktivni), None)
        if stavka:
            if st.button("← Natrag na popis", key="v2b_natrag"):
                st.session_state.pop(KLJUC_AKTIVNI, None)
                st.rerun()
            ekran_ucenika.prikazi(st, sheet, stavka["definicija"], stavka["dodjela"], dry=False)
            return
        st.session_state.pop(KLJUC_AKTIVNI, None)

    if not moje:
        return

    st.divider()
    st.markdown("#### 📝 Testovi (nova verzija)")
    for stavka in moje:
        _kartica(st, sheet, stavka, ucenik_id)


def broj_za_rjesavanje(sheet, ucenik_id: str) -> int:
    """Koliko v2 testova učenik JOŠ nije riješio — za brojač u nazivu kartice (kao `za_rjesavanje` za v1)."""
    try:
        return len([t for t in testovi_za_ucenika(sheet, ucenik_id) if not t["rjeseno"]])
    except Exception:                                   # noqa: BLE001
        return 0
