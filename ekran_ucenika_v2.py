"""
CAKI testovi v2 — `ekran_ucenika.py`
EKRAN RJEŠAVANJA: pitanje po pitanju, autosave, matematički unos, predaja s upozorenjem.

Dva načina rada:
  · **stvarno rješavanje** — učenik ima dodjelu; pokušaj se zapisuje (autosave, predaja)
  · **pregled za Cakija** (`dry=True`) — isti kod, ali **ništa se ne sprema**

Odvojeno od `app.py` namjerno: isti modul sutra koristi portal učenika.
"""
from __future__ import annotations

import time

import streamlit as st

import ai_pomoc_v2 as ai_pomoc
import dodjele
import drive
import model
import ocjenjivanje
import provedba
import rjesavanje
import slike_zadataka_v2 as slike_zadataka
import unos_odgovora
import zavrsetak


def _k(*dijelovi) -> str:
    """Ključ sesije — kratak, bez razmaka, jedinstven po testu/dodjeli."""
    return "v2r_" + "_".join(str(d).replace(" ", "_")[:20] for d in dijelovi)


def _zadaci(definicija: dict, dodjela: dict) -> list[dict]:
    return provedba.zadaci_za_pokusaj(definicija, dodjela)


def _odgovori_kljuc(dodjela: dict) -> str:
    return _k("odg", dodjela.get("dodjela_id", "x"))


def prikazi_tekst_s_tabelama(tekst) -> None:
    """Prikaži tekst zadatka tako da pipe tablica postane PRAVA tablica (Caki 29.10.2026.).

    Ako tablice nema — prikaz je isti kao prije (`rjesavanje.pripremi_latex`).
    """
    try:
        import tabele

        if not tabele.ima_tabelu(tekst):
            st.markdown(rjesavanje.pripremi_latex(tekst))
            return
        for dio in tabele.podijeli(tekst):
            if dio["tip"] == "tabela":
                st.markdown(tabele.html_tabela(dio["sadrzaj"]), unsafe_allow_html=True)
            elif model.tekst(dio["sadrzaj"]).strip():
                st.markdown(rjesavanje.pripremi_latex(dio["sadrzaj"]))
    except Exception:                                  # noqa: BLE001
        st.markdown(rjesavanje.pripremi_latex(tekst))


def prikazi(st, sheet, definicija: dict, dodjela: dict, *, dry: bool = False) -> None:
    """Cijeli ekran rješavanja za jednu dodjelu (ili pregled kad je `dry=True`)."""
    zadaci = _zadaci(definicija, dodjela)
    if not zadaci:
        st.error("Test nema ispravno spremljene zadatke — javi Cakiju.")
        return

    k_odg = _odgovori_kljuc(dodjela)
    k_pit = _k("pitanje", dodjela.get("dodjela_id", "x"))
    k_pok = _k("pokusaj", dodjela.get("dodjela_id", "x"))
    k_gotov = _k("gotov", dodjela.get("dodjela_id", "x"))
    st.session_state.setdefault(k_odg, {})
    st.session_state.setdefault(k_pit, 0)

    # --- pokušaj: stvarni (u Sheetu) ili pregled (u sesiji)
    if dry:
        pokusaj = st.session_state.setdefault(k_pok, {
            "pokusaj_id": "PREGLED", "status": provedba.STATUS_U_TIJEKU,
            "pocetak": model.sada().strftime("%Y-%m-%d %H:%M:%S"),
            "odgovori_json": "{}", "dodjela_id": "PREGLED",
        })
    else:
        gotov = st.session_state.get(k_gotov)
        if gotov:
            prikazi_zavrsnicu(st, sheet, definicija, dodjela, pokusaj=gotov)
            return
        pokusaj = st.session_state.get(k_pok)
        if not pokusaj:
            # 31.10.2026.: ako je test već predan (npr. poslije F5 ili povratka na stranicu),
            # učenik ide na ZAVRŠNICU (slanje postupka), a ne dobiva samo „već predano".
            predan = provedba.zadnji_predani(sheet, dodjela.get("dodjela_id"))
            if predan:
                st.session_state[k_gotov] = predan
                prikazi_zavrsnicu(st, sheet, definicija, dodjela, pokusaj=predan)
                return
            try:
                pokusaj = provedba.zapocni(sheet, dodjela, definicija)
            except ValueError as e:                     # rok / već predano — ne rušiti stranicu
                st.error(f"Test se ne može otvoriti: {e}")
                return
            st.session_state[k_pok] = pokusaj

    # --- ⏰ vrijeme isteklo → AUTOMATSKA PREDAJA (31.10.2026., Cakijev zahtjev)
    # Provjera ide PRIJE crtanja pitanja: nakon isteka učenik ne dobiva polja za unos, pa
    # naknadni odgovori nisu mogući. Živu provjera radi i fragment `_traka` (svake sekunde).
    if not dry and zavrsetak.treba_auto_predaju(pokusaj, definicija):
        _auto_predaj(st, sheet, pokusaj, definicija)
        return

    # --- traka: vrijeme (blinka zadnjih 5 minuta), bodovi i napredak
    odgovori = st.session_state[k_odg]
    try:
        _traka(st, sheet, definicija, dodjela, pokusaj, zadaci, odgovori, dry)
    except Exception:                                   # noqa: BLE001 — traka ne smije srušiti test
        _traka_sadrzaj(st, definicija, pokusaj, zadaci, odgovori)

    # --- navigacija po pitanjima
    index = max(0, min(len(zadaci) - 1, int(st.session_state.get(k_pit, 0))))
    stanja = rjesavanje.stanje_pitanja(zadaci, odgovori)
    with st.container(border=True):
        st.caption("Pitanja: " + " · ".join(rjesavanje.oznaka_pitanja(i, stanja)
                                            for i in range(len(zadaci))))
        b1, b2, b3 = st.columns([1, 1, 4])
        if b1.button("← Prethodno", key=_k("preth", pokusaj["pokusaj_id"])):
            st.session_state[k_pit] = rjesavanje.sljedeci(index, len(zadaci), -1)
            st.rerun()
        if b2.button("Sljedeće →", key=_k("sljedece", pokusaj["pokusaj_id"])):
            st.session_state[k_pit] = rjesavanje.sljedeci(index, len(zadaci), 1)
            st.rerun()
        b3.caption(f"Pitanje **{index + 1}** od **{len(zadaci)}** · odgovor se sprema sam")

    # --- pitanje
    z = zadaci[index]
    trenutni = model.tekst(odgovori.get(str(index)))
    novi = trenutni
    with st.container(border=True):
        st.markdown(f"**Zadatak {index + 1}.** ({model.broj(z.get('bodovi'), 1):g} bod.)")
        prikazi_tekst_s_tabelama(z.get("tekst"))
        if model.tekst(z.get("slika")):
            slike_zadataka.prikazi_sliku_html(st, z.get("slika"))

        opcije = [model.tekst(o) for o in (z.get("opcije") or []) if model.tekst(o)]
        tip_z = model.tekst(z.get("tip"))

        if tip_z == "vise_tocnih" and len(opcije) >= 2:
            # više točnih: slova se spremaju kao „AC" (tako ih ocjenjuje `tipovi.ocjeni`)
            _slova_sva = [chr(65 + i) for i in range(len(opcije))]
            _odabrana = st.multiselect(
                "Odgovor (može više)", _slova_sva,
                default=[s for s in (trenutni or "").upper() if s in _slova_sva],
                format_func=lambda s: f"{s}) "
                                      f"{rjesavanje.pripremi_latex(opcije[ord(s) - 65], zamotaj=True)}",
                key=_k("multi", pokusaj["pokusaj_id"], index))
            novi = "".join(sorted(_odabrana))

        elif tip_z == "tocno_netocno":
            _opcije_tn = ["Točno", "Netočno"]
            _trenutni_tn = ("Točno" if model.tekst(trenutni).lower().startswith("to")
                            else ("Netočno" if model.tekst(trenutni) else None))
            novi = st.radio("Odgovor", _opcije_tn,
                            index=_opcije_tn.index(_trenutni_tn) if _trenutni_tn else None,
                            horizontal=True,
                            key=_k("tn", pokusaj["pokusaj_id"], index)) or ""

        elif tip_z == "brojcan":
            novi = st.text_input("Odgovor (broj)", value=model.tekst(trenutni),
                                 placeholder="npr. 3,14",
                                 key=_k("broj", pokusaj["pokusaj_id"], index))

        elif tip_z == "popuni_praznine":
            _praznine = z.get("praznine") or []
            _postojeci = [d for d in model.tekst(trenutni).split("|")] if trenutni else []
            _vrijednosti = []
            for _i_p in range(len(_praznine)):
                _vrijednosti.append(st.text_input(
                    f"Praznina {_i_p + 1}",
                    value=_postojeci[_i_p] if _i_p < len(_postojeci) else "",
                    key=_k(f"praznina{_i_p}", pokusaj["pokusaj_id"], index)))
            novi = "|".join(model.tekst(v) for v in _vrijednosti)

        elif tip_z in ("poredak", "povezivanje"):
            _uputa = ("Upiši stavke u traženom REDOSLIJEDU, odvojene znakom | "
                      "(npr. 3|1|2)" if tip_z == "poredak"
                      else "Upiši desne strane redom, odvojene znakom | (npr. b|a|c)")
            st.caption(_uputa)
            novi = st.text_input("Odgovor", value=model.tekst(trenutni),
                                 key=_k("redoslijed", pokusaj["pokusaj_id"], index))

        elif tip_z == "otvoreni_odgovor":
            st.caption("Ovaj zadatak ispravlja profesor — napiši postupak.")
            novi = st.text_area("Odgovor", value=model.tekst(trenutni), height=160,
                                key=_k("otvoreni", pokusaj["pokusaj_id"], index))

        elif tip_z == "visestruki_izbor" and len(opcije) >= 2:
            slova = [""] + [chr(65 + i) for i in range(len(opcije))]
            odabrano = st.radio(
                "Odgovor", slova, index=slova.index(trenutni) if trenutni in slova else 0,
                key=_k("radio", pokusaj["pokusaj_id"], index),
                format_func=lambda s: ("— odaberi —" if not s
                                       else f"{s}) "
                                            f"{rjesavanje.pripremi_latex(opcije[ord(s) - 65], zamotaj=True)}"),
            )
            novi = odabrano
        else:
            novi = unos_odgovora.unos_odgovora(
                "Odgovor", key=_k("unos", pokusaj["pokusaj_id"], index),
                vrijednost_latex=trenutni)

    # 💡 pomoć uz ovo pitanje — samo ako je profesor dopustio za OVAJ test
    try:
        import definicije as _def
        _ai_smije = _def.smije_ai(definicija)
    except Exception:                                  # noqa: BLE001
        _ai_smije = False
    try:
        if not _ai_smije:
            raise StopIteration
        ai_pomoc.prikazi_pomoc(
            st, z,
            kljuc_testa=f"{dodjela.get('dodjela_id', 'x')}_{index}",
            secrets=st.secrets,
        )
    except Exception:                                  # noqa: BLE001 — pomoć ne smije blokirati
        pass

    if model.tekst(novi) != trenutni:
        st.session_state[k_odg][str(index)] = novi
        if not dry and model.tekst(pokusaj.get("status")) == provedba.STATUS_U_TIJEKU:
            try:
                provedba.spremi(sheet, pokusaj, {str(index): novi})
            except Exception:                          # noqa: BLE001 — autosave ne blokira
                st.caption("⚠️ Automatsko spremanje trenutno ne radi — odgovor je još na ekranu.")

    # --- predaja (1. korak: POŠALJI ODGOVORE)
    st.divider()
    sazetak = rjesavanje.sto_nedostaje(zadaci, st.session_state[k_odg])
    st.markdown("### 📤 Predaja testa")
    st.caption(zavrsetak.tekst_koraka_1(sazetak["prazno"], sazetak["ukupno"]))
    with st.expander("👀 Provjeri odgovore prije predaje (koji su odgovoreni, koji nisu)"):
        for red in rjesavanje.sazetak_predaje(zadaci, st.session_state[k_odg]):
            st.caption(red)
    if st.button("📤 POŠALJI ODGOVORE", type="primary", width="stretch",
                 key=_k("predaj", pokusaj["pokusaj_id"])):
        try:
            if dry:
                ocj = ocjenjivanje.ocjeni_zadatke(
                    zadaci, {int(k): v for k, v in st.session_state[k_odg].items()},
                    dopusti_ai=False)
                st.success(f"🧪 Pregled: {rjesavanje.rezultat_tekst(ocj['bodovi'], ocj['maks'])} "
                           "— ništa nije spremljeno.")
                st.info(zavrsetak.tekst_koraka_2())
                st.caption("Pregled: u pravom testu ovdje su dva gumba — **pošalji slike postupka** "
                           "ili **nema postupka** — i nakon njih „Test je završen“.")
            else:
                provedba.predaj(sheet, pokusaj, definicija,
                                odgovori_=st.session_state[k_odg], dopusti_ai=False)
                st.session_state.pop(k_pok, None)       # sljedeći prikaz = završnica (korak 2)
                st.rerun()
        except Exception as e:                          # noqa: BLE001 — Caki/učenik mora vidjeti
            st.error(f"Predaja nije uspjela: {e}")
            st.caption("Odgovori su spremljeni — pokušaj predati ponovno ili javi profesoru.")


# ================================================================ traka s vremenom

def _timer_html(stanje: dict) -> str:
    """Timer; u zadnjih 5 minuta **blinka** crveno (Cakijev zahtjev 31.10.2026.)."""
    if stanje.get("istekao"):
        return ('<div style="font-size:0.95rem;opacity:.75;">Preostalo</div>'
                '<div style="font-size:1.6rem;font-weight:700;color:#c62828;">⏰ isteklo</div>')
    if stanje.get("blizi_se"):
        stil = ("<style>@keyframes v2blink{0%,100%{opacity:1}50%{opacity:.15}}"
                ".v2-blink{animation:v2blink 1s ease-in-out infinite;}</style>")
        boja, klasa = "#c62828", " v2-blink"
    else:
        stil, boja, klasa = "", "#1f1f1f", ""
    return (
        stil
        + '<div style="font-size:0.95rem;opacity:.75;">Preostalo</div>'
        + f'<div class="v2-timer{klasa}" style="font-size:1.6rem;font-weight:700;color:{boja};">'
        + f'⏳ {stanje.get("tekst", "")}</div>'
    )


def _traka_sadrzaj(st, definicija: dict, pokusaj: dict, zadaci: list, odgovori: dict) -> dict:
    """Jedna traka: timer, bodovi, napredak i upozorenje pred kraj. Vraća stanje vremena."""
    v = zavrsetak.stanje_vremena(pokusaj, definicija)
    nap = rjesavanje.napredak(zadaci, odgovori)
    c1, c2, c3 = st.columns(3)
    c1.markdown(_timer_html(v), unsafe_allow_html=True)
    c2.metric("Bodova ukupno", f"{model.broj(definicija.get('bodovi_ukupno')):g}")
    c3.metric("Odgovoreno", f"{nap['odgovoreno']}/{nap['ukupno']}")
    st.progress(nap["postotak"] / 100)
    if v["blizi_se"]:
        st.warning(zavrsetak.tekst_upozorenja(v["preostalo_s"]))
    elif v["istekao"]:
        st.error(zavrsetak.tekst_isteka(auto=True))
    return v


def _traka_fragment(st, sheet, definicija: dict, dodjela: dict, pokusaj: dict,
                    zadaci: list, odgovori: dict, dry: bool):
    """Fragment se sam osvježava svake sekunde — timer ide i bez klika učenika.

    U trenutku isteka predaje test bez ikakve radnje učenika (nema naknadnog unosa).
    """
    v = _traka_sadrzaj(st, definicija, pokusaj, zadaci, odgovori)
    if (not dry) and v["istekao"] and zavrsetak.treba_auto_predaju(pokusaj, definicija):
        _auto_predaj(st, sheet, pokusaj, definicija)


def _traka(*args, **kwargs):
    """Omotač: na starijem Streamlitu (bez `st.fragment`) traka samo nema samostalno osvježavanje."""
    return _traka_fragment(*args, **kwargs)


if hasattr(st, "fragment"):
    try:
        _traka = st.fragment(run_every="1s")(_traka_fragment)   # noqa: F811 — namjerno
    except Exception:                                   # noqa: BLE001 — stariji Streamlit
        pass


def _auto_predaj(st, sheet, pokusaj: dict, definicija: dict) -> None:
    """Predaj pokušaj jer je vrijeme isteklo, pa osvježi stranicu na završnicu (korak 2).

    Zaštita od ponavljanja: fragment se osvježava svake sekunde, pa se automatska predaja
    pokušava najviše svakih 10 s (greška u mreži ne smije zatrpavati Sheet upisima).
    """
    k_auto = _k("auto", pokusaj.get("pokusaj_id", "x"))
    k_pok = _k("pokusaj", pokusaj.get("dodjela_id", "x"))
    k_gotov = _k("gotov", pokusaj.get("dodjela_id", "x"))
    zadnji = st.session_state.get(k_auto)
    sada = time.time()
    if isinstance(zadnji, (int, float)) and (sada - zadnji) < 10:
        return
    st.session_state[k_auto] = sada
    try:
        provedba.predaj(sheet, pokusaj, definicija,
                        odgovori_=st.session_state.get(
                            _odgovori_kljuc({"dodjela_id": pokusaj.get("dodjela_id")})),
                        dopusti_ai=False)
    except Exception as e:                              # noqa: BLE001 — već zaključen / mreža
        if not any(k in str(e).lower() for k in ("zaklju", "predan")):
            st.error(f"Automatska predaja nije uspjela: {e}")
            st.caption("Odgovori su spremljeni do trenutka isteka — pokušat ću ponovno za koju "
                       "sekundu. Ako se ponavlja, javi profesoru.")
            return
    # Stanje u Sheetu je mjerodavno: sljedeći prikaz pronađe predani pokušaj i pokaže završnicu.
    st.session_state.pop(k_pok, None)
    st.session_state.pop(k_gotov, None)
    st.rerun()


# ================================================================ završnica (2. korak)

def prikazi_zavrsnicu(st, sheet, definicija: dict, dodjela: dict, *, pokusaj: dict | None = None,
                      dry: bool = False) -> None:
    """Nakon predaje: 2. korak — pošalji slike/PDF postupka ili potvrdi da ih nema.

    Tek nakon toga piše „Test je završen" (Cakijev zahtjev 31.10.2026.). Učenik mora znati da
    profesor **gleda postupak**, ne samo konačan odgovor, i da se slike (može ih biti više) i PDF
    mogu pregledati.
    """
    did = model.tekst((dodjela or {}).get("dodjela_id"))
    k_zav = _k("zavrsnica", did)
    pokusaj = pokusaj or {}
    ucenik_id = model.tekst(pokusaj.get("ucenik_id")) or model.tekst(dodjela.get("ucenik_id"))

    if zavrsetak.predan_po_isteku(pokusaj):
        st.warning(zavrsetak.tekst_isteka(auto=True))
    else:
        st.success("✅ **Tvoj test je predan.**")

    # Rezultat — samo ako ga Student View dopušta (isto pravilo kao pregled rješenja).
    try:
        rok_prosao = dodjele.stanje_roka(dodjela, definicija) == "zatvoren"
        vidi = rjesavanje.sto_vidi_ucenik(definicija.get("student_view_json"),
                                          predano=True, rok_prosao=rok_prosao)
    except Exception:                                   # noqa: BLE001 — prikaz ne smije puknuti
        vidi = {}
    maks = model.broj(pokusaj.get("bodovi_max"))
    if maks and (vidi.get("bodovi") or vidi.get("rezultat")):
        st.metric("Rezultat", rjesavanje.rezultat_tekst(pokusaj.get("bodovi"), maks))
        st.caption("Ako neki zadatak još čeka provjeru profesora, rezultat je privremen.")
    elif maks:
        st.caption("Bodove ćeš vidjeti kad profesor pregleda test.")

    st.divider()

    stanje = st.session_state.get(k_zav)
    if stanje:
        st.success(zavrsetak.tekst_bez_postupka() if stanje == "nema" else zavrsetak.tekst_zavrseno())
        with st.expander("➕ Poslati još slika postupka"):
            _posalji_slike(st, sheet, definicija, dodjela, pokusaj, ucenik_id,
                           dry=dry, kljuc=k_zav, dopusti_nema=False)
        return

    st.markdown("### 📷 Pošalji svoj postupak")
    st.markdown(zavrsetak.tekst_koraka_2())
    _posalji_slike(st, sheet, definicija, dodjela, pokusaj, ucenik_id,
                   dry=dry, kljuc=k_zav, dopusti_nema=True)


def _posalji_slike(st, sheet, definicija: dict, dodjela: dict, pokusaj: dict, ucenik_id: str,
                   *, dry: bool, kljuc: str, dopusti_nema: bool = True) -> None:
    """Upload slika/PDF postupka + rezervni put (poveznica) i gumb „NEMA POSTUPKA"."""
    did = model.tekst((dodjela or {}).get("dodjela_id"))
    datoteke = st.file_uploader(
        "Slike postupka (može više) ili PDF", accept_multiple_files=True,
        type=list(zavrsetak.DOPUSTENE_DATOTEKE), key=_k("upload", did))

    b1, b2 = st.columns([3, 2])
    posalji = b1.button("📤 POŠALJI SLIKE POSTUPKA", type="primary",
                        width="stretch", disabled=not datoteke,
                        key=_k("pos_slike", did))
    nema = b2.button("NEMA POSTUPKA (nemam što poslati)", width="stretch",
                     disabled=not dopusti_nema, key=_k("nema", did))

    if posalji:
        if dry:
            st.info("Pregled: u pravom testu slike bi se spremile uz pokušaj i profesor bi ih vidio.")
        else:
            try:
                rez = zavrsetak.posalji_postupak(
                    sheet, pokusaj=pokusaj, ucenik_id=ucenik_id,
                    datoteke=[{"naziv": getattr(d, "name", "postupak.jpg"),
                               "bajtovi": d.getvalue()} for d in datoteke],
                    folder=drive.folder_id(st.secrets))
            except Exception as e:                      # noqa: BLE001 — slanje ne smije blokirati
                st.error(f"Slanje nije uspjelo: {e}")
            else:
                for g in rez["greske"]:
                    st.error(f"Nije poslano — {g}")
                if rez["poslano"]:
                    st.session_state[kljuc] = "poslano"
                    st.rerun()
                else:
                    st.caption("Možeš pokušati ponovno ili poslati **poveznicu** ispod.")
    if nema:
        st.session_state[kljuc] = "nema"
        st.rerun()

    with st.expander("📎 Ne mogu poslati datoteku — pošalji poveznicu"):
        st.caption("Ako slikanje/upload ne radi, zalijepi poveznicu na fotografiju ili sken "
                   "(Drive, mobitel, bilo gdje dostupno).")
        veza = st.text_input("Poveznica", key=_k("veza", did))
        if st.button("📎 Pošalji poveznicu", key=_k("pos_veza", did)):
            if dry:
                st.info("Pregled: poveznica bi se spremila uz pokušaj.")
            else:
                try:
                    zavrsetak.posalji_poveznicu(sheet, pokusaj=pokusaj, ucenik_id=ucenik_id,
                                                veza=veza)
                except ValueError as e:
                    st.error(str(e))
                else:
                    st.session_state[kljuc] = "poslano"
                    st.rerun()


def prikazi_pregled_rjesenja(st, zadaci: list[dict], odgovori: dict, *,
                             pokazi_rjesenja: bool, pokazi_video: bool,
                             pokazi_bodove: bool, sheet=None,
                             pokusaj: dict | None = None, ucenik_id: str = "") -> None:
    """Nakon testa: što je učenik odgovorio, točan odgovor i 🎬 video — po Student View-u."""
    for i, z in enumerate(zadaci or []):
        red = rjesavanje.pregled_zadatka(
            z, model.tekst((odgovori or {}).get(str(i))),
            pokazi_rjesenje=pokazi_rjesenja, pokazi_video=pokazi_video,
            pokazi_bodove=pokazi_bodove)
        oznaka = "🎬 video" if red["video"] else "pregled"
        with st.expander(f"Zadatak {i + 1} — {oznaka}"):
            prikazi_tekst_s_tabelama(red["tekst"])
            st.caption(f"Tvoj odgovor: **{red['moj_odgovor'] or '— (prazno)'}**")
            if red["pokazi_rjesenje"]:
                st.success(f"Točno: {red['tocan_odgovor']}")
            if red["video"]:
                st.markdown(f"🎬 **Video:** [{red['video']['naslov']}]({red['video']['url']})")
            if sheet is not None and pokusaj:
                try:
                    import zalbe as _zalbe

                    _zid = model.tekst(z.get("id"))
                    _smije, _zasto = _zalbe.moze_podnijeti(sheet, pokusaj, _zid)
                    if _smije:
                        with st.form(f"zalba_{i}"):
                            _razlog = st.text_area(
                                "⚖️ Žalba na ocjenu ovog zadatka (objasni što smatraš pogrešnim)",
                                height=80, key=f"zalba_tekst_{i}")
                            if st.form_submit_button("Pošalji žalbu"):
                                try:
                                    _zalbe.podnesi(sheet, pokusaj=pokusaj, zadatak_id=_zid,
                                                   razlog=_razlog, ucenik_id=ucenik_id)
                                    st.success("Žalba je poslana profesoru.")
                                except Exception as _e_z:      # noqa: BLE001
                                    st.error(f"Žalba nije poslana: {_e_z}")
                    elif model.tekst(_zasto):
                        st.caption(f"⚖️ {_zasto}")
                except Exception:                      # noqa: BLE001
                    pass

