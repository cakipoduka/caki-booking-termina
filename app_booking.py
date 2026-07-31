"""
CAKI Upisi u SŠ — app_booking.py
Javna stranica (BEZ lozinke) za roditelje: odabir termina nastave.
Roditelj unosi ucenik_id (dobiven mailom nakon telefonske potvrde),
vidi svoje potvrđene komponente i bira slobodan termin po grupi.
"""
import json

import streamlit as st

from pipeline_upisi import (
    KOMPONENTE,
    KOMPONENTE_ZA_BOOKING,
    REZERVACIJA_ROK_DANA,
    dohvati_ucenika_po_id,
    get_gspread_client,
    izracunaj_dostupnost,
    kreiraj_rezervaciju,
    load_grupe,
    load_prijave,
    load_rezervacije,
    load_ucenici,
)

st.set_page_config(page_title="CAKI — Odaberi termin", page_icon="📅", layout="centered")


@st.cache_resource
def init_sheet():
    sa_info = json.loads(st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"])
    gc = get_gspread_client(sa_info)
    return gc.open_by_key(st.secrets["SHEET_ID"])


sheet = init_sheet()

st.title("📅 Odaberi termin nastave")
st.caption("CAKI centar — Upisi u srednju školu")

# Ucenik_id iz URL-a (ako roditelj klikne link iz maila) ili ručni unos
query_id = st.query_params.get("ucenik_id", "")
ucenik_id = st.text_input("Unesite šifru učenika (dobili ste je u mailu)", value=query_id).strip().upper()

if not ucenik_id:
    st.info("Unesite šifru učenika da vidite dostupne termine.")
    st.stop()


@st.cache_data(ttl=15)
def dohvati_sve():
    return load_ucenici(sheet), load_prijave(sheet), load_grupe(sheet), load_rezervacije(sheet)


df_ucenici, df_prijave, df_grupe, df_rezervacije = dohvati_sve()

ucenik = dohvati_ucenika_po_id(df_ucenici, ucenik_id)

if ucenik is None:
    st.error("Šifra nije pronađena. Provjerite jeste li točno prepisali iz maila.")
    st.stop()

st.success(f"Pozdrav! Biramo termine za: **{ucenik['ime_djeteta']}**")

# Komponente ovog učenika koje su potvrđene (Potvrdio) i koje uopće trebaju booking
komponente_ucenika = df_prijave[
    (df_prijave["ucenik_id"] == ucenik_id)
    & (df_prijave["status_kontakta"] == "Potvrdio")
    & (df_prijave["komponenta"].isin(KOMPONENTE_ZA_BOOKING))
]

if komponente_ucenika.empty:
    st.warning("Nema komponenti spremnih za odabir termina (ili je booking već obavljen).")
    st.stop()

for _, red in komponente_ucenika.iterrows():
    komponenta = red["komponenta"]
    st.divider()
    st.subheader(KOMPONENTE.get(komponenta, komponenta))

    # Već ima aktivnu rezervaciju za ovu komponentu?
    postojece = df_rezervacije[
        (df_rezervacije["ucenik_id"] == ucenik_id)
        & (df_rezervacije["status"].isin(["Rezervirano", "Potvrđeno"]))
    ]
    grupe_te_komponente = df_grupe[df_grupe["program"] == komponenta]
    postojeca_za_komp = postojece[postojece["grupa_id"].isin(grupe_te_komponente["grupa_id"])]

    if not postojeca_za_komp.empty:
        r = postojeca_za_komp.iloc[0]
        grupa_info = df_grupe[df_grupe["grupa_id"] == r["grupa_id"]]
        if not grupa_info.empty:
            g = grupa_info.iloc[0]
            ikonica = "🟠" if r["status"] == "Rezervirano" else "🔴"
            napomena_status = "čeka potvrdu uplate" if r["status"] == "Rezervirano" else "potvrđeno"
            st.write(f"{ikonica} Već rezervirano: **{g['dan']} {g['vrijeme']}** ({g['ucionica']}) — {napomena_status}")
        continue

    aktivne_grupe = grupe_te_komponente[grupe_te_komponente["aktivna"].astype(str).str.lower() == "da"]

    if aktivne_grupe.empty:
        st.info("Termini za ovaj program još nisu otvoreni. Javit ćemo vam se čim budu dostupni.")
        continue

    for _, grupa in aktivne_grupe.iterrows():
        dostupnost = izracunaj_dostupnost(grupa.to_dict(), df_rezervacije)

        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"**{grupa['dan']} {grupa['vrijeme']}** — {grupa['ucionica']} ({grupa['tip']})")
            if dostupnost["status_boja"] == "zeleno":
                st.markdown(f":green[🟢 {dostupnost['slobodna']} slobodnih mjesta]")
            elif dostupnost["status_boja"] == "narancasto":
                st.markdown(f":orange[🟠 Popunjeno — {dostupnost['na_cekanju_uplate']} mjesta čeka potvrdu uplate (rok {REZERVACIJA_ROK_DANA} dana)]")
            else:
                st.markdown(":red[🔴 Popunjeno]")

        with col2:
            kljuc = f"btn_{grupa['grupa_id']}"
            if dostupnost["status_boja"] == "zeleno":
                if st.button("Rezerviraj", key=kljuc):
                    kreiraj_rezervaciju(
                        sheet, grupa["grupa_id"], ucenik_id, ucenik["ime_djeteta"],
                        ucenik.get("mobitel_roditelja", ""), status="Rezervirano"
                    )
                    st.success(
                        f"Vaša rezervacija je evidentirana: {grupa['dan']} {grupa['vrijeme']} "
                        f"({grupa['ucionica']}) — čekamo potvrdu uplate"
                    )
                    st.cache_data.clear()
                    st.rerun()
            elif dostupnost["status_boja"] == "narancasto":
                if st.button("Lista čekanja", key=kljuc):
                    kreiraj_rezervaciju(
                        sheet, grupa["grupa_id"], ucenik_id, ucenik["ime_djeteta"],
                        ucenik.get("mobitel_roditelja", ""), status="Čekanje"
                    )
                    st.success("Dodani ste na listu čekanja — javit ćemo vam se ako se mjesto oslobodi.")
                    st.cache_data.clear()
                    st.rerun()
            else:
                st.button("Popunjeno", key=kljuc, disabled=True)

st.divider()
st.caption("Pitanja? Kontaktirajte nas na [broj telefona / email CAKI centra].")
