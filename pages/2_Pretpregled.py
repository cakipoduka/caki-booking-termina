"""
CAKI — pages/2_Pretpregled.py  (24.10.2026.)
👁️ PRETPREGLED TESTA — točno ono što vidi učenik, za Cakija.

Zašto postoji: prije objave testa Caki mora vidjeti **isto sučelje** koje će učenik dobiti —
zadatke sa slikama, **matematičko polje za unos (MathLive)**, formule i 💡 pomoć pri učenju.
Ako bi se pregled napravio kao zasebna kopija sučelja, ona bi se s vremenom razišla od pravog.

Zato ova stranica **poziva isti kod** koji radi učenik (`testovi_online._prikazi_rjesavanje`),
samo u `dry_run` načinu: **ništa se ne sprema** — nema `Test_pocetak`, nema `Rezultati_testova`,
nema zapisa u AI log. Gumb „Predaj test" u pregledu samo pokaže rezultat i poruku da ništa nije
spremljeno.

Adresa: `<portal>/Pretpregled`  (traži `APP_PASSWORD`, kao i ostale Cakijeve stranice)

SECRETS: SHEET_ID, APP_PASSWORD, GOOGLE_SERVICE_ACCOUNT_JSON (ili _TESTOVI), DEEPSEEK_API_KEY,
         SLIKE_FOLDER_ID (za slike u zadacima).
"""
import streamlit as st

import testovi_online as _online

st.set_page_config(page_title="CAKI — Pretpregled testa", page_icon="👁️", layout="wide")


def _lozinka_pregleda() -> str:
    """Lozinka za pretpregled: `PREGLED_LOZINKA`, a ako je nema — `APP_PASSWORD` (ako postoji)."""
    for kljuc in ("PREGLED_LOZINKA", "APP_PASSWORD"):
        try:
            vrijednost = st.secrets.get(kljuc)
        except Exception:                               # noqa: BLE001 — nema secrets.toml
            vrijednost = None
        if vrijednost:
            return str(vrijednost)
    return ""


def provjeri_lozinku() -> bool:
    ocekivana = _lozinka_pregleda()
    if not ocekivana:
        st.title("👁️ Pretpregled testa")
        st.error("Da bi pretpregled radio, u **Secrets portala** dodaj `PREGLED_LOZINKA` "
                 "(bilo koji niz koji ćeš pamtiti). Bez toga stranica ne može provjeriti smiješ li "
                 "je otvoriti — a testovi se ne smiju vidjeti bez zaštite.")
        return False

    def na_unos():
        st.session_state["autoriziran_pregled"] = (
            st.session_state.get("lozinka_unos_pregled") == ocekivana)

    if st.session_state.get("autoriziran_pregled"):
        return True
    st.title("👁️ Pretpregled testa")
    st.caption("Ovo je stranica za Cakija — vidi se točno ono što dobiva učenik.")
    st.text_input("Lozinka", type="password", key="lozinka_unos_pregled", on_change=na_unos)
    if st.session_state.get("autoriziran_pregled") is False:
        st.error("Pogrešna lozinka.")
    return False


if not provjeri_lozinku():
    st.stop()


@st.cache_resource(show_spinner=False)
def _sheet():
    """Isti Sheet i isti servisni račun koji koristi sustav testiranja (ne diramo portal)."""
    from pipeline_upisi import get_gspread_client

    return get_gspread_client(_online.sa_info_za_testove(st)).open_by_key(st.secrets["SHEET_ID"])


st.title("👁️ Pretpregled testa — kako to vidi učenik")
st.caption("Isti kod kao u portalu učenika: zadaci, slike, **matematički unos**, formule i 💡 pomoć. "
           "**Ništa se ne sprema** — ni početak, ni odgovori, ni pomoć.")

try:
    sheet = _sheet()
    testovi = _online.load_testovi(sheet)
except Exception as e:                                  # noqa: BLE001 — Caki mora vidjeti grešku
    st.error(f"Testovi se ne mogu pročitati: {e}")
    st.stop()

if not testovi:
    st.info("Još nema objavljenih testova u `Testovi_zakazani`.")
    st.stop()

# test se može otvoriti i izravno linkom: .../Pretpregled?test=T26-0001
_zeljeni = str(st.query_params.get("test", "")).strip()
_kljucevi = {str(t.get("test_id", "")).strip(): t for t in testovi}
_index = list(_kljucevi).index(_zeljeni) if _zeljeni in _kljucevi else 0


def _opis(tid):
    t = _kljucevi.get(tid, {})
    naziv = str(t.get("naziv", "")).strip() or tid
    return (f"{naziv} · {t.get('broj_zadataka', '')} zad. · {t.get('bodovi_ukupno', '')} bod. · "
            f"do {t.get('zatvara_do', '')}")


odabrani = st.selectbox("Koji test pregledavamo?", list(_kljucevi), index=_index,
                        format_func=_opis, key="pregled_test")

c1, c2 = st.columns([1, 3])
with c1:
    if st.button("↻ Osvježi popis testova", key="pregled_osvjezi"):
        st.cache_resource.clear()
        st.rerun()
with c2:
    st.caption("Pregled ne troši ništa: nema upisa u Sheet, nema slanja, nema AI zapisa. "
               "Ako test ima 💡 pomoć, možeš je isprobati kao učenik.")

st.divider()
_online.prikazi_pregled(st, _kljucevi[odabrani])
