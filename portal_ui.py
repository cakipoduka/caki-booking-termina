"""
CAKI — portal_ui.py  (26.9.2026.)
Jedan portal za roditelje i učenike: odabir termina (bivši booking) + Moj CAKI
(raspored, dolasci, instrukcije, plaćanja, rezultati) na jednom mjestu, u karticama.

Koriste ga app_booking.py (glavna adresa, link iz maila) i pages/1_Moj_CAKI.py
(stari linkovi .../Moj_CAKI?ucenik_id=... i dalje rade).

Pristup: samo šifra učenika (ucenik_id), bez lozinke — svjesna odluka (§24.5).
Portal nikad ne prikazuje interne napomene, kontakte, nacrte ponuda ni neposlane dokumente.
"""
import json
import re

import pandas as pd
import streamlit as st

from pipeline_upisi import (
    KOMPONENTE,
    KOMPONENTE_ZA_BOOKING,
    REZERVACIJA_ROK_DANA,
    _load_opcionalno,
    centi_u_tekst,
    dohvati_ucenika_po_id,
    get_gspread_client,
    izracunaj_dostupnost,
    ucionica_javno,
    kreiraj_rezervaciju,
    load_racuni,
    load_rezervacije,
    load_ucenici,
    portal_dolasci,
    portal_instrukcije,
    portal_paketi,
    PAKETI_TAB,
    portal_naplata,
    portal_raspored_grupa,
    portal_raspored_matura,
    naziv_taba_rasporeda_mature,
    portal_rezultati,
    datumi_termina,
    kljuc_predmeta_mature,
    u_datum,
    ucitaj_praznike,
    ucitaj_razdoblja,
    sada_zagreb,
)
from sat_biljeska import za_roditelja as sat_za_roditelja  # 17.10.2026.: teme i zadaca po satu
import testovi_online as online_testovi  # 19.10.2026.: online testovi (objavljeni iz Test Buildera)
from obavijesti import (  # 15.10.2026.: kartica 📣 Obavijesti (poruke od Cakija, linkovi, komentari)
    MAX_KOMENTAR,
    OD_OPCIJE,
    dodaj_komentar,
    komentari_ucenika,
    linkovi_za_ucenika,
    load_komentare,
    load_linkove,
    load_obavijesti,
    obavijesti_za_ucenika,
    oznake_ucenika,
    previse_komentara,
)

KONTAKT = "📞 +385 95 900 5611 · ✉️ info@cakipoduka.com"
AKTIVNE_REZERVACIJE = ["Rezervirano", "Potvrđeno", "Čekanje"]


@st.cache_resource
def _init_sheet():
    sa_info = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    gc = get_gspread_client(sa_info)
    return gc.open_by_key(st.secrets["SHEET_ID"])


# Tabovi se čitaju najviše jednom u minuti i dijele među SVIM posjetiteljima — čuva Google kvotu.
@st.cache_data(ttl=60)
def _ucitaj(naziv: str):
    sheet = _init_sheet()
    if naziv == "Učenici":
        return load_ucenici(sheet)
    return _load_opcionalno(sheet, naziv)


# Slobodna mjesta moraju biti svježija
@st.cache_data(ttl=30)
def _ucitaj_rezervacije():
    return _load_opcionalno(_init_sheet(), "Rezervacije")


@st.cache_data(ttl=60)
def _ucitaj_racune():
    return load_racuni(_init_sheet())


# 12.10.2026.: početak priprema po predmetu (tab Razdoblja_termina) i praznici — isto čitanje kao u adminu
@st.cache_data(ttl=60)
def _ucitaj_razdoblja():
    return ucitaj_razdoblja(_init_sheet())


@st.cache_data(ttl=60)
def _ucitaj_praznike():
    return ucitaj_praznike(_init_sheet())


def pocetak_predmeta(oznaka: str, dan: str, razdoblja: dict, praznici: dict) -> str:
    """Datum prvog sata za predmet Mature na zadani dan u tjednu: prvi takav dan >= datuma početka predmeta
    (praznici se preskaču). Predmet bez upisanog početka koristi opći 'MATURA' unos; ako ni njega nema → 'Javit ćemo'."""
    zapis = (razdoblja or {}).get(kljuc_predmeta_mature(oznaka)) or (razdoblja or {}).get("MATURA")
    od = u_datum(zapis.get("od")) if zapis else None
    if not od:
        return "Javit ćemo"
    datumi, _ = datumi_termina(od, dan, 1, praznici)
    return (datumi[0] if datumi else od).strftime("%d.%m.%Y.")


# 15.10.2026.: Obavijesti — tabovi Obavijesti, Linkovi_portal, Komentari_portal (stvara ih admin kad prvi put nešto spremi)
@st.cache_data(ttl=60)
def _ucitaj_obavijesti():
    return load_obavijesti(_init_sheet())


@st.cache_data(ttl=60)
def _ucitaj_linkove():
    return load_linkove(_init_sheet())


@st.cache_data(ttl=30)
def _ucitaj_komentare():
    return load_komentare(_init_sheet())


# 19.10.2026.: online testovi — tabovi Testovi_zakazani / Rezultati_testova u CRM Sheetu.
# Kratki TTL jer učitelj može objaviti test usred dana; rezultati moraju biti svježi odmah.
@st.cache_data(ttl=60)
def _ucitaj_online_testove():
    return online_testovi.load_testovi(_init_sheet())


@st.cache_data(ttl=30)
def _ucitaj_online_rezultate():
    return online_testovi.load_rezultati(_init_sheet())


def _md_sigurno(tekst: str) -> str:
    """Tekst koji je napisao klijent prikazuje se doslovno (bez markdowna, linkova i oznaka)."""
    return re.sub(r"([\\`*_{}\[\]()#+!|<>~$:-])", r"\\\1", str(tekst or "")).replace("\n", "  \n")


def _gumb_link(naziv: str, url: str):
    """Gumb-link preko cijele širine (radi i na starijim i na novijim verzijama Streamlita)."""
    try:
        st.link_button(naziv, url, width="stretch")
    except TypeError:
        st.link_button(naziv, url, use_container_width=True)


def _poruka(vrsta: str, tekst: str):
    """Poruka koja preživi st.rerun()."""
    st.session_state["_portal_poruka"] = (vrsta, tekst)


# ------------------------------------------------------------------ odabir termina

def komponente_za_odabir(df_prijave: pd.DataFrame, ucenik_id: str) -> list:
    """Potvrđene Upisi komponente koje imaju tjedne termine — svaka samo JEDNOM
    (i kad je ista komponenta u Prijavama dvaput, npr. ponovljena prijava)."""
    if df_prijave.empty or "komponenta" not in df_prijave.columns:
        return []
    k = df_prijave[(df_prijave["ucenik_id"] == ucenik_id)
                   & (df_prijave["status_kontakta"] == "Potvrdio")
                   & (df_prijave["komponenta"].isin(KOMPONENTE_ZA_BOOKING))]
    return list(dict.fromkeys(k["komponenta"]))


def treba_odabrati_termin(komponente: list, df_grupe: pd.DataFrame, df_rez: pd.DataFrame, ucenik_id: str) -> list:
    """Komponente za koje učenik još NEMA aktivnu rezervaciju."""
    if df_grupe.empty:
        return komponente
    moje = df_rez[(df_rez["ucenik_id"] == ucenik_id) & (df_rez["status"].isin(AKTIVNE_REZERVACIJE))] \
        if not df_rez.empty else df_rez
    rez = []
    for komp in komponente:
        grupe = df_grupe[df_grupe["program"] == komp]["grupa_id"]
        if moje.empty or not moje["grupa_id"].isin(grupe).any():
            rez.append(komp)
    return rez


def _prikazi_odabir_termina(sheet, ucenik, ucenik_id, komponente, df_grupe, df_rez):
    if not komponente:
        st.info("Nema programa za koje se bira termin (ili je odabir već obavljen).")
        return
    for komponenta in komponente:
        st.markdown(f"#### {KOMPONENTE.get(komponenta, komponenta)}")
        grupe_komp = df_grupe[df_grupe["program"] == komponenta].drop_duplicates("grupa_id") \
            if not df_grupe.empty else df_grupe
        moje = df_rez[(df_rez["ucenik_id"] == ucenik_id) & (df_rez["status"].isin(AKTIVNE_REZERVACIJE))
                      & (df_rez["grupa_id"].isin(grupe_komp.get("grupa_id", [])))] if not df_rez.empty else df_rez

        if not moje.empty:
            r = moje.iloc[0]
            g = grupe_komp[grupe_komp["grupa_id"] == r["grupa_id"]].iloc[0]
            if r["status"] == "Čekanje":
                st.info(f"🕐 Na listi čekanja: **{g['dan']} {g['vrijeme']}** ({ucionica_javno(g['ucionica'])}) — "
                        "javit ćemo vam se ako se mjesto oslobodi.")
            elif r["status"] == "Rezervirano":
                st.warning(f"🟠 Rezervirano: **{g['dan']} {g['vrijeme']}** ({ucionica_javno(g['ucionica'])}) — čeka potvrdu uplate.")
            else:
                st.success(f"✅ Potvrđeno: **{g['dan']} {g['vrijeme']}** ({ucionica_javno(g['ucionica'])})")
            continue

        aktivne = grupe_komp[grupe_komp["aktivna"].astype(str).str.lower() == "da"] if not grupe_komp.empty else grupe_komp
        if aktivne.empty:
            st.info("Termini za ovaj program još nisu otvoreni. Javit ćemo vam se čim budu dostupni.")
            continue

        for _, grupa in aktivne.iterrows():
            dostupnost = izracunaj_dostupnost(grupa.to_dict(), df_rez)
            kljuc = f"rez_{komponenta}_{grupa['grupa_id']}"
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                c1.write(f"**{grupa['dan']} {grupa['vrijeme']}** — {ucionica_javno(grupa['ucionica'])}")
                if dostupnost["status_boja"] == "zeleno":
                    c1.markdown(f":green[🟢 {dostupnost['slobodna']} slobodnih mjesta]")
                    status_nove = "Rezervirano"
                    natpis = "Rezerviraj"
                elif dostupnost["status_boja"] == "narancasto":
                    c1.markdown(f":orange[🟠 Popunjeno — {dostupnost['na_cekanju_uplate']} mjesta čeka potvrdu "
                                f"uplate (rok {REZERVACIJA_ROK_DANA} dana)]")
                    status_nove = "Čekanje"
                    natpis = "Lista čekanja"
                else:
                    c1.markdown(":red[🔴 Popunjeno]")
                    c2.button("Popunjeno", key=kljuc, disabled=True)
                    continue

                if c2.button(natpis, key=kljuc, type="primary" if status_nove == "Rezervirano" else "secondary"):
                    # Svježa provjera iz Sheeta — zaštita od dvostrukog klika
                    svjeze = load_rezervacije(sheet)
                    vec = (not svjeze.empty) and not svjeze[
                        (svjeze["ucenik_id"] == ucenik_id) & (svjeze["grupa_id"] == grupa["grupa_id"])
                        & (svjeze["status"].isin(AKTIVNE_REZERVACIJE))].empty
                    if vec:
                        _poruka("warning", "Rezervacija za ovaj termin je već zabilježena.")
                    else:
                        kreiraj_rezervaciju(sheet, grupa["grupa_id"], ucenik_id, ucenik["ime_djeteta"],
                                            ucenik.get("mobitel_roditelja", ""), status=status_nove)
                        _poruka("success",
                                f"Rezervacija je evidentirana: {grupa['dan']} {grupa['vrijeme']} ({ucionica_javno(grupa['ucionica'])})"
                                " — čekamo potvrdu uplate." if status_nove == "Rezervirano"
                                else "Dodani ste na listu čekanja — javit ćemo vam se ako se mjesto oslobodi.")
                    st.cache_data.clear()
                    st.rerun()


# ------------------------------------------------------------------ obavijesti (prva kartica)

def _prikazi_obavijesti(sheet, ucenik, ucenik_id, obavijesti, linkovi, df_komentari, greska=False):
    if greska:
        st.info("Obavijesti trenutno nisu dostupne. Pokušajte malo kasnije ili nas nazovite.")
        return

    if not obavijesti and not linkovi:
        st.caption("Trenutno nema novih obavijesti.")
    for o in obavijesti:
        with st.container(border=True):
            st.markdown(("📌 " if o["vazno"] else "") + f"**{o['naslov']}**")
            if o["datum"]:
                st.caption(o["datum"])
            st.markdown(o["tekst"].replace("\n", "  \n"))

    if linkovi:
        st.markdown("#### 🔗 Važni linkovi")
        for l in linkovi:
            _gumb_link(l["naziv"], l["url"])
            if l["opis"]:
                st.caption(l["opis"])

    st.markdown("#### 💬 Napišite nam")
    st.caption("Komentar, pitanje ili napomena za CAKI — ostaje zabilježena uz učenika, a odgovor vidite ovdje. "
               "Za hitne stvari nazovite nas. Ne upisujte osjetljive osobne podatke.")
    with st.form("obrazac_komentar", clear_on_submit=True):
        od = st.radio("Tko piše?", OD_OPCIJE, horizontal=True)
        tekst = st.text_area("Vaša poruka", max_chars=MAX_KOMENTAR, height=120)
        poslano = st.form_submit_button("Pošalji", type="primary")
    if poslano:
        if not tekst.strip():
            st.warning("Upišite poruku.")
        elif previse_komentara(df_komentari, ucenik_id):
            st.warning("Danas ste već poslali nekoliko poruka. Za hitne stvari nazovite nas.")
        else:
            try:
                dodaj_komentar(sheet, ucenik_id, ucenik["ime_djeteta"], od, tekst)
            except Exception:
                st.error("Poruka nije poslana. Pokušajte ponovno ili nas nazovite.")
            else:
                _ucitaj_komentare.clear()
                _poruka("success", "Hvala! Poruka je zabilježena.")
                st.rerun()

    moji = komentari_ucenika(df_komentari, ucenik_id)
    if moji:
        with st.expander(f"Vaše poruke ({len(moji)})"):
            for k in moji:
                st.markdown(f"**{k['datum']}** · {k['od']}")
                st.markdown(_md_sigurno(k["tekst"]))
                if k["odgovor"]:
                    st.info("💬 **CAKI:** " + k["odgovor"].replace("\n", "  \n"))
                st.divider()


# ------------------------------------------------------------------ portal

def prikazi_portal():
    sheet = _init_sheet()

    # 12.10.2026.: veliki brojevi u zaglavlju više se ne režu ("Srijeda 15:0…") — manji font i dopušten prijelom
    st.markdown("""<style>
[data-testid="stMetricValue"] { font-size: 1.7rem; }
[data-testid="stMetricValue"] > div { white-space: normal; overflow: visible; text-overflow: clip; line-height: 1.25; }
</style>""", unsafe_allow_html=True)

    st.title("📘 Moj CAKI")
    st.caption("Odabir termina, raspored, dolasci, instrukcije i plaćanja — sve na jednom mjestu.")

    query_id = st.query_params.get("ucenik_id", "")
    ucenik_id = st.text_input("Šifra učenika (dobili ste je u mailu)", value=query_id).strip().upper()
    if not ucenik_id:
        st.info("Upišite šifru učenika.")
        st.stop()

    ucenik = dohvati_ucenika_po_id(_ucitaj("Učenici"), ucenik_id)
    if ucenik is None:
        st.error("Šifra nije pronađena. Provjerite jeste li je točno prepisali iz maila.")
        st.stop()

    if "_portal_poruka" in st.session_state:
        vrsta, tekst = st.session_state.pop("_portal_poruka")
        getattr(st, vrsta)(tekst)

    df_grupe = _ucitaj("Grupe")
    df_rez = _ucitaj_rezervacije()
    df_racuni = _ucitaj_racune()
    df_prijave = _ucitaj("Prijave")
    komponente = komponente_za_odabir(df_prijave, ucenik_id)
    bez_termina = treba_odabrati_termin(komponente, df_grupe, df_rez, ucenik_id)
    raspored = portal_raspored_grupa(df_rez, df_grupe, ucenik_id)
    raspored_matura = portal_raspored_matura(_ucitaj(naziv_taba_rasporeda_mature()), ucenik_id)   # 26.9.2026.
    tablica_dol, postotci = portal_dolasci(_ucitaj("Dolasci"), _ucitaj("Termini"), df_grupe, ucenik_id)
    dokumenti, dug = portal_naplata(df_racuni, ucenik_id)

    # --- Online testovi (19.10.2026.): kratice iz Test Buildera; ako tabovi ne postoje, portal radi kao prije ---
    try:
        df_online_testovi = _ucitaj_online_testove()
        df_online_rezultati = _ucitaj_online_rezultate()
        programi_ucenika = set(
            df_prijave.loc[df_prijave["ucenik_id"] == ucenik_id, "program_tip"].astype(str)
        ) if not df_prijave.empty and "program_tip" in df_prijave.columns else set()
        online_dostupni = online_testovi.testovi_za_ucenika(
            df_online_testovi, df_online_rezultati, ucenik_id, programi_ucenika, sada_zagreb().date())
        online_greska = ""
    except Exception:
        df_online_testovi, df_online_rezultati = [], []
        programi_ucenika, online_dostupni = set(), []
        online_greska = "Online testovi trenutno nisu dostupni — pokušajte malo kasnije."
    za_rjesavanje = len([t for t in online_dostupni if not t["rjeseno"]])
    moji_online_rezultati = online_testovi.rezultati_ucenika(df_online_rezultati, ucenik_id)

    # --- Obavijesti (15.10.2026.): ako tabovi ne postoje / Google zapne, ostatak portala radi dalje ---
    try:
        oznake = oznake_ucenika(_ucitaj("Prijave"), ucenik_id,
                                matura_oznake=list(raspored_matura["Predmet"]) if not raspored_matura.empty else ())
        obavijesti = obavijesti_za_ucenika(_ucitaj_obavijesti(), ucenik_id, oznake)
        linkovi = linkovi_za_ucenika(_ucitaj_linkove(), ucenik_id, oznake)
        df_komentari, obav_greska = _ucitaj_komentare(), False
    except Exception:
        obavijesti, linkovi, df_komentari, obav_greska = [], [], pd.DataFrame(), True

    # --- Zaglavlje: tko je i najvažnije u 3 broja ---
    with st.container(border=True):
        st.markdown(f"### 👋 {ucenik['ime_djeteta']}")
        m1, m2, m3 = st.columns([2.4, 1, 1.5])
        prvi = raspored if not raspored.empty else raspored_matura
        m1.metric("📅 Grupa", f"{prvi.iloc[0]['Dan']} {prvi.iloc[0]['Vrijeme']}" if not prvi.empty else "—",
                  help="Prvi termin u tjednu, s vremenom (svi termini i datumi početka su u kartici Raspored).")
        ukupno_dol = round(sum(postotci.values()) / len(postotci)) if postotci else None
        m2.metric("✅ Dolasci", f"{ukupno_dol} %" if ukupno_dol is not None else "—")
        m3.metric("💶 Za uplatu", f"{centi_u_tekst(dug)} €" if dug else "0,00 €")
    if bez_termina:
        st.warning("📅 **Odaberite termin nastave** — kartica *Odabir termina* ispod.")

    naziv_obav = f"📣 Obavijesti ({len(obavijesti)})" if obavijesti else "📣 Obavijesti"
    naziv_testovi = f"📝 Testovi ({za_rjesavanje})" if za_rjesavanje else "📝 Testovi"
    nazivi = [naziv_obav]
    if komponente and bez_termina:
        nazivi.append("📅 Odabir termina")
    if online_dostupni or moji_online_rezultati:
        nazivi.append(naziv_testovi)
    nazivi += ["🗓️ Raspored", "✅ Dolasci", "💶 Plaćanja", "📊 Rezultati"]
    if komponente and not bez_termina:
        nazivi.append("📅 Odabir termina")
    kartice = dict(zip(nazivi, st.tabs(nazivi)))

    with kartice[naziv_obav]:
        _prikazi_obavijesti(sheet, ucenik, ucenik_id, obavijesti, linkovi, df_komentari, obav_greska)

    if naziv_testovi in kartice:
        with kartice[naziv_testovi]:
            if online_greska:
                st.info(online_greska)
            else:
                online_testovi.prikazi_testove(
                    st, sheet, df_online_testovi, df_online_rezultati, ucenik, ucenik_id,
                    programi_ucenika, sada_zagreb())

    if "📅 Odabir termina" in kartice:
        with kartice["📅 Odabir termina"]:
            _prikazi_odabir_termina(sheet, ucenik, ucenik_id, komponente, df_grupe, df_rez)

    with kartice["🗓️ Raspored"]:
        if not raspored_matura.empty:
            st.markdown("#### Pripreme za Maturu")
            razdoblja, praznici = _ucitaj_razdoblja(), _ucitaj_praznike()
            raspored_matura = raspored_matura.copy()
            raspored_matura["Početak"] = [pocetak_predmeta(r["Predmet"], r["Dan"], razdoblja, praznici)
                                          for _, r in raspored_matura.iterrows()]
            st.dataframe(raspored_matura, hide_index=True, width="stretch")
            st.caption("Tjedni raspored po predmetima. U stupcu *Početak* je datum prvog sata za svaki predmet "
                       "(početak nastave razlikuje se po predmetu). Ako piše „Javit ćemo“, datum još nije određen.")
        if not raspored.empty or raspored_matura.empty:
            st.markdown("#### Grupna nastava")
            if raspored.empty:
                st.info("Nema rezerviranih termina grupne nastave.")
            else:
                st.dataframe(raspored, hide_index=True, width="stretch")
        st.markdown("#### Instrukcije")
        df_instr_p = _ucitaj("Instrukcije_termini")
        instr = portal_instrukcije(df_instr_p, df_racuni, ucenik_id)
        if instr.empty:
            st.info("Nema evidentiranih instrukcija.")
        else:
            st.dataframe(instr, hide_index=True, width="stretch",
                         column_config={"Cijena (€)": st.column_config.NumberColumn(format="%.2f")})
            st.caption("📒 Bilješku sa sata piše profesor (što se radilo, domaća zadaća). Termin otkažite najkasnije "
                       "24 sata ranije — kasnije otkazivanje i nedolazak se naplaćuju.")
        try:  # 17.10.2026.: teme i zadaća po satu (ocjena sata i interna napomena se NE prikazuju)
            sat_tablica = sat_za_roditelja(df_instr_p, ucenik_id)
        except Exception:
            sat_tablica = None
        if sat_tablica is not None and not sat_tablica.empty:
            st.markdown("#### 📚 Što smo radili i zadaća")
            st.dataframe(sat_tablica, hide_index=True, width="stretch")

        paketi = portal_paketi(_ucitaj(PAKETI_TAB), df_instr_p, ucenik_id)
        if not paketi.empty:
            st.markdown("#### 📦 Paket sati")
            st.dataframe(paketi, hide_index=True, width="stretch")

    with kartice["✅ Dolasci"]:
        if tablica_dol.empty:
            st.info("Još nema evidentiranih dolazaka.")
        else:
            stupci = st.columns(min(len(postotci), 3) or 1)
            for i, (grupa, posto) in enumerate(postotci.items()):
                stupci[i % len(stupci)].metric(grupa, f"{posto} %",
                                               help="Udio termina na kojima je učenik bio prisutan (uživo ili online).")
            st.dataframe(tablica_dol, hide_index=True, width="stretch")

    with kartice["💶 Plaćanja"]:
        if dokumenti.empty:
            st.info("Nema poslanih ponuda ni računa.")
        else:
            if dug > 0:
                st.metric("Otvoreno za uplatu", f"{centi_u_tekst(dug)} €")
            else:
                st.success("Sve poslane ponude su plaćene. Hvala!")
            st.dataframe(dokumenti, hide_index=True, width="stretch", column_config={
                "Iznos (€)": st.column_config.NumberColumn(format="%.2f"),
                "Dokument": st.column_config.LinkColumn(display_text="PDF"),
            })

    with kartice["📊 Rezultati"]:
        rezultati = portal_rezultati(_ucitaj("Rezultati"), ucenik_id)
        if rezultati.empty:
            st.info("Rezultati testova i simulacija prikazivat će se ovdje.")
        else:
            st.dataframe(rezultati, hide_index=True, width="stretch",
                         column_config={"Postotak": st.column_config.ProgressColumn(min_value=0, max_value=100,
                                                                                   format="%d %%")})
        # 19.10.2026.: online testovi (odvojen tab Rezultati_testova) — isti popis kao u kartici 📝 Testovi
        if moji_online_rezultati:
            st.markdown("#### 📝 Online testovi")
            st.dataframe(online_testovi.tabela_rezultata(moji_online_rezultati), hide_index=True,
                         width="stretch",
                         column_config={"Postotak": st.column_config.ProgressColumn(
                             min_value=0, max_value=100, format="%d %%")})

    st.divider()
    st.caption(f"Pitanja? {KONTAKT}")
