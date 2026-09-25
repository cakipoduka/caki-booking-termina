"""
CAKI — pages/1_Moj_CAKI.py  (§12 / §24 MASTER CRM, 23.9.2026.)
Portal za roditelje i učenike: raspored, dolasci, naplata, rezultati.

Pristup: SAMO šifra učenika (ucenik_id), bez lozinke — svjesna odluka (§24.5), isti
model kao booking stranica. Link: https://caki-termin.streamlit.app/Moj_CAKI?ucenik_id=AB1234

Stranica isključivo ČITA podatke. Nikad ne prikazuje interne napomene, kontakte,
nacrte ponuda ni dokumente koje admin još nije poslao.

Postavi u repo 'caki-booking-termina', mapa pages/ (isti Streamlit secrets kao app_booking.py).
"""
import json

import streamlit as st

# Streamlit Cloud nakon git pulla zna zadržati STARU verziju pipeline_upisi.py u memoriji
# (→ ImportError "cannot import name"). Ako je datoteka novija od učitanog modula, učitaj je ponovno.
import importlib, os, time  # noqa: E401,E402
import pipeline_upisi as _pipeline  # noqa: E402
if os.path.getmtime(_pipeline.__file__) > getattr(_pipeline, "_ucitano_u", 0):
    importlib.reload(_pipeline)
    _pipeline._ucitano_u = time.time()

from pipeline_upisi import (  # noqa: E402
    _load_opcionalno,
    centi_u_tekst,
    dohvati_ucenika_po_id,
    get_gspread_client,
    load_racuni,
    load_ucenici,
    portal_dolasci,
    portal_instrukcije,
    portal_naplata,
    portal_raspored_grupa,
    portal_rezultati,
)

st.set_page_config(page_title="Moj CAKI", page_icon="📘", layout="centered")


@st.cache_resource
def init_sheet():
    sa_info = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    gc = get_gspread_client(sa_info)
    return gc.open_by_key(st.secrets["SHEET_ID"])


sheet = init_sheet()


# Cijeli tabovi se čitaju jednom u minuti i dijele među SVIM posjetiteljima — štiti
# Google Sheets kvotu (60 čitanja/min) i kad više roditelja otvori portal odjednom.
@st.cache_data(ttl=60)
def ucitaj(naziv: str):
    if naziv == "Učenici":
        return load_ucenici(sheet)
    return _load_opcionalno(sheet, naziv)


@st.cache_data(ttl=60)
def ucitaj_racune():
    return load_racuni(sheet)


st.title("📘 Moj CAKI")
st.caption("Raspored, dolasci, naplata i rezultati na jednom mjestu.")

query_id = st.query_params.get("ucenik_id", "")
ucenik_id = st.text_input("Šifra učenika (dobili ste je u mailu)", value=query_id).strip().upper()
if not ucenik_id:
    st.info("Upišite šifru učenika.")
    st.stop()

ucenik = dohvati_ucenika_po_id(ucitaj("Učenici"), ucenik_id)
if ucenik is None:
    st.error("Šifra nije pronađena. Provjerite jeste li je točno prepisali iz maila.")
    st.stop()

st.success(f"**{ucenik['ime_djeteta']}**")

tab_raspored, tab_dolasci, tab_naplata, tab_rezultati = st.tabs(
    ["📅 Raspored", "✅ Dolasci", "💶 Naplata", "📊 Rezultati"]
)

with tab_raspored:
    st.markdown("#### Grupna nastava")
    raspored = portal_raspored_grupa(ucitaj("Rezervacije"), ucitaj("Grupe"), ucenik_id)
    if raspored.empty:
        st.info("Nema rezerviranih termina grupne nastave.")
    else:
        st.dataframe(raspored, hide_index=True, width="stretch")

    st.markdown("#### Instrukcije")
    instr = portal_instrukcije(ucitaj("Instrukcije_termini"), ucitaj_racune(), ucenik_id)
    if instr.empty:
        st.info("Nema evidentiranih instrukcija.")
    else:
        st.dataframe(instr, hide_index=True, width="stretch",
                     column_config={"Cijena (€)": st.column_config.NumberColumn(format="%.2f")})

with tab_dolasci:
    tablica, postotci = portal_dolasci(ucitaj("Dolasci"), ucitaj("Termini"), ucitaj("Grupe"), ucenik_id)
    if tablica.empty:
        st.info("Još nema evidentiranih dolazaka.")
    else:
        stupci = st.columns(min(len(postotci), 3) or 1)
        for i, (grupa, posto) in enumerate(postotci.items()):
            stupci[i % len(stupci)].metric(grupa, f"{posto} %", help="Udio termina na kojima je učenik bio prisutan (uživo ili online).")
        st.dataframe(tablica, hide_index=True, width="stretch")

with tab_naplata:
    dokumenti, dug = portal_naplata(ucitaj_racune(), ucenik_id)
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
    st.caption("Ponude za pripreme za upise u srednju školu dosad stižu samo mailom i ovdje se još ne prikazuju. "
               "Za pitanja o uplatama: +385 95 900 5611.")

with tab_rezultati:
    rezultati = portal_rezultati(ucitaj("Rezultati"), ucenik_id)
    if rezultati.empty:
        st.info("Rezultati testova i simulacija prikazivat će se ovdje.")
    else:
        st.dataframe(rezultati, hide_index=True, width="stretch",
                     column_config={"Postotak": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d %%")})
