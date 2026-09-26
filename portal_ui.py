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
    kreiraj_rezervaciju,
    load_racuni,
    load_rezervacije,
    load_ucenici,
    portal_dolasci,
    portal_instrukcije,
    portal_naplata,
    portal_raspored_grupa,
    portal_raspored_matura,
    naziv_taba_rasporeda_mature,
    portal_rezultati,
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
@st.cache_data(ttl=15)
def _ucitaj_rezervacije():
    return _load_opcionalno(_init_sheet(), "Rezervacije")


@st.cache_data(ttl=60)
def _ucitaj_racune():
    return load_racuni(_init_sheet())


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
                st.info(f"🕐 Na listi čekanja: **{g['dan']} {g['vrijeme']}** ({g['ucionica']}) — "
                        "javit ćemo vam se ako se mjesto oslobodi.")
            elif r["status"] == "Rezervirano":
                st.warning(f"🟠 Rezervirano: **{g['dan']} {g['vrijeme']}** ({g['ucionica']}) — čeka potvrdu uplate.")
            else:
                st.success(f"✅ Potvrđeno: **{g['dan']} {g['vrijeme']}** ({g['ucionica']})")
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
                c1.write(f"**{grupa['dan']} {grupa['vrijeme']}** — {grupa['ucionica']}")
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
                                f"Rezervacija je evidentirana: {grupa['dan']} {grupa['vrijeme']} ({grupa['ucionica']})"
                                " — čekamo potvrdu uplate." if status_nove == "Rezervirano"
                                else "Dodani ste na listu čekanja — javit ćemo vam se ako se mjesto oslobodi.")
                    st.cache_data.clear()
                    st.rerun()


# ------------------------------------------------------------------ portal

def prikazi_portal():
    sheet = _init_sheet()

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
    komponente = komponente_za_odabir(_ucitaj("Prijave"), ucenik_id)
    bez_termina = treba_odabrati_termin(komponente, df_grupe, df_rez, ucenik_id)
    raspored = portal_raspored_grupa(df_rez, df_grupe, ucenik_id)
    raspored_matura = portal_raspored_matura(_ucitaj(naziv_taba_rasporeda_mature()), ucenik_id)   # 26.9.2026.
    tablica_dol, postotci = portal_dolasci(_ucitaj("Dolasci"), _ucitaj("Termini"), df_grupe, ucenik_id)
    dokumenti, dug = portal_naplata(df_racuni, ucenik_id)

    # --- Zaglavlje: tko je i najvažnije u 3 broja ---
    with st.container(border=True):
        st.markdown(f"### 👋 {ucenik['ime_djeteta']}")
        m1, m2, m3 = st.columns(3)
        prvi = raspored if not raspored.empty else raspored_matura
        m1.metric("📅 Grupa", f"{prvi.iloc[0]['Dan']} {prvi.iloc[0]['Vrijeme']}" if not prvi.empty else "—",
                  help="Prvi termin u tjednu (svi termini su u kartici Raspored).")
        ukupno_dol = round(sum(postotci.values()) / len(postotci)) if postotci else None
        m2.metric("✅ Dolasci", f"{ukupno_dol} %" if ukupno_dol is not None else "—")
        m3.metric("💶 Za uplatu", f"{centi_u_tekst(dug)} €" if dug else "0,00 €")
    if bez_termina:
        st.warning("📅 **Odaberite termin nastave** — kartica *Odabir termina* ispod.")

    nazivi = ["🗓️ Raspored", "✅ Dolasci", "💶 Plaćanja", "📊 Rezultati"]
    if komponente:
        nazivi.insert(0 if bez_termina else len(nazivi), "📅 Odabir termina")
    kartice = dict(zip(nazivi, st.tabs(nazivi)))

    if "📅 Odabir termina" in kartice:
        with kartice["📅 Odabir termina"]:
            _prikazi_odabir_termina(sheet, ucenik, ucenik_id, komponente, df_grupe, df_rez)

    with kartice["🗓️ Raspored"]:
        if not raspored_matura.empty:
            st.markdown("#### Pripreme za Maturu")
            st.dataframe(raspored_matura, hide_index=True, width="stretch")
            st.caption("Tjedni raspored po predmetima. Početak nastave razlikuje se po predmetu — javit ćemo vam ga.")
        if not raspored.empty or raspored_matura.empty:
            st.markdown("#### Grupna nastava")
            if raspored.empty:
                st.info("Nema rezerviranih termina grupne nastave.")
            else:
                st.dataframe(raspored, hide_index=True, width="stretch")
        st.markdown("#### Instrukcije")
        instr = portal_instrukcije(_ucitaj("Instrukcije_termini"), df_racuni, ucenik_id)
        if instr.empty:
            st.info("Nema evidentiranih instrukcija.")
        else:
            st.dataframe(instr, hide_index=True, width="stretch",
                         column_config={"Cijena (€)": st.column_config.NumberColumn(format="%.2f")})

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

    st.divider()
    st.caption(f"Pitanja? {KONTAKT}")
