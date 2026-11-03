"""CAKI — zajednička tema za PORTALE (profesori, Moj CAKI, testovi) — 3.11.2026. (Claude)

Ista tema kao CRM admin (admin_tema.py u caki-upisi-crm-main, Cakijeva odluka 2.11.2026.):
font IBM Plex Sans, tinta #1b2230, plava #1d64b8, podloga #f4f5f7, bijele kartice s tankim rubom.
Datoteka je ISTA u caki-evidencija-dolazaka, caki-booking-termina i caki-testovi.

Uz CSS donosi i male pomoćnike koje portali koriste:
  · nav(...)      — traka kartica od gumba; iscrtava se SAMO odabrana kartica (štedi čitanja Sheeta),
  · chip(), redak(), kutija() — isti izgled kao kartica učenika u CRM-u.

Povratak na staru temu: u portalu umjesto `caki_tema.primijeni()` vratiti `caki_stil.primijeni()`.
Ovdje se NE dira nikakav podatak — samo izgled.
"""
from __future__ import annotations

import html
import re

import streamlit as st

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
:root{ --kc-ink:#1b2230; --kc-muted:#5a6375; --kc-line:#dde1e7; --kc-line2:#eef0f3; --kc-bg:#f4f5f7;
  --kc-blue:#1d64b8; --kc-blue-d:#164e90; --kc-in:#c3c9d2; }

/* ---------- podloga, font, veličine ---------- */
.stApp{ background:var(--kc-bg); color:var(--kc-ink); }
.stApp, .stApp p, .stApp li, .stApp label, .stApp input, .stApp textarea, .stApp select, .stApp button,
.stApp td, .stApp th, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp div,
.stApp span:not([data-testid="stIconMaterial"]):not(.material-symbols-rounded){
  font-family:'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; }
header[data-testid="stHeader"]{ background:transparent; }
[data-testid="stMainBlockContainer"], .block-container{ max-width:1360px; padding-top:1.4rem; padding-bottom:3rem; }
.stApp [data-testid="stMarkdownContainer"] p, .stApp [data-testid="stMarkdownContainer"] li{ font-size:15px; line-height:1.5; }
.stApp h1{ font-size:28px !important; font-weight:700 !important; color:var(--kc-ink) !important; letter-spacing:0; }
.stApp h2{ font-size:22px !important; font-weight:600 !important; color:var(--kc-ink) !important; }
.stApp h3{ font-size:18px !important; font-weight:600 !important; color:var(--kc-ink) !important; }
.stApp h4{ font-size:16px !important; font-weight:600 !important; color:var(--kc-ink) !important; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p{ color:var(--kc-muted) !important; font-size:13px !important; }
.stApp a{ color:var(--kc-blue); } .stApp a:hover{ color:var(--kc-blue-d); }

/* ---------- bočni izbornik: tamna traka kao na skici ---------- */
[data-testid="stSidebar"]{ background:#1b2230; }
[data-testid="stSidebar"] p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] span,
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3{ color:#eef1f6 !important; }
[data-testid="stSidebar"] button p, [data-testid="stSidebar"] button span{ color:#1b2230 !important; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{ color:#b8c1d1 !important; }

/* ---------- gumbi ---------- */
.stApp button[data-testid="stBaseButton-secondary"], .stApp a[data-testid="stBaseLinkButton-secondary"]{
  background:#fff; border:1px solid var(--kc-in); border-radius:8px; color:var(--kc-ink); min-height:40px; }
.stApp button[data-testid="stBaseButton-secondary"]:hover, .stApp a[data-testid="stBaseLinkButton-secondary"]:hover{
  border-color:var(--kc-blue); color:var(--kc-blue); }
.stApp button[data-testid="stBaseButton-primary"], .stApp a[data-testid="stBaseLinkButton-primary"]{
  background:var(--kc-blue); border:1px solid var(--kc-blue); border-radius:8px; min-height:40px; }
.stApp button[data-testid="stBaseButton-primary"]:hover{ background:var(--kc-blue-d); border-color:var(--kc-blue-d); }
.stApp button p, .stApp a[data-testid^="stBaseLinkButton"] p{ font-size:14px !important; }
.stApp button[data-testid="stBaseButton-tertiary"] p{ color:var(--kc-blue) !important; font-size:14px !important; }

/* ---------- unosi, expanderi, tabovi, metrike ---------- */
.stApp [data-baseweb="input"], .stApp [data-baseweb="select"] > div, .stApp [data-baseweb="textarea"]{ border-radius:8px !important; }
.stApp [data-testid="stExpander"] details{ background:#fff; border:1px solid var(--kc-line); border-radius:12px; }
.stApp [data-testid="stExpander"] summary p{ font-size:15px !important; font-weight:500; }
.stApp [data-baseweb="tab-list"]{ border-bottom:1px solid var(--kc-line); gap:0; }
.stApp [data-baseweb="tab"] p{ font-size:15px !important; }
.stApp [data-testid="stMetricLabel"] p{ color:var(--kc-muted) !important; font-size:13px !important; }
.stApp [data-testid="stMetricValue"]{ font-size:22px !important; font-weight:600 !important; color:var(--kc-ink); }
.stApp [data-testid="stAlert"]{ border-radius:10px; }

/* ---------- kartica učenika (kontejneri s ključem kc_…) ---------- */
.stApp [class*="st-key-kc_box"], .stApp [class*="st-key-kc_tile"]{
  background:#fff; border:1px solid var(--kc-line); border-radius:12px; padding:18px 20px; gap:10px; }
.stApp .st-key-kc_tabovi{ border-bottom:1px solid var(--kc-line); gap:0 !important; flex-wrap:nowrap !important;
  overflow-x:auto; padding:0; }
.stApp .st-key-kc_tabovi button{ background:transparent !important; border:0 !important; border-radius:0 !important;
  border-bottom:3px solid transparent !important; min-height:46px; padding:10px 16px; box-shadow:none !important; }
.stApp .st-key-kc_tabovi button p{ font-size:15px !important; color:#3c4556 !important; white-space:nowrap; }
.stApp .st-key-kc_tabovi button:hover{ background:#eceff3 !important; }
.stApp .st-key-kc_tabovi button[data-testid="stBaseButton-primary"]{ border-bottom-color:var(--kc-blue) !important; }
.stApp .st-key-kc_tabovi button[data-testid="stBaseButton-primary"] p{ color:var(--kc-ink) !important; font-weight:600; }

.kc-h1{ font-size:28px; font-weight:700; line-height:1.2; margin:0; color:var(--kc-ink); }
.kc-h3{ font-size:16px; font-weight:600; margin:0; color:var(--kc-ink); }
.kc-muted{ color:var(--kc-muted); }
.kc-small{ font-size:13px; }
.kc-chips{ display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
.kc-chip{ display:inline-block; font-size:13px; line-height:18px; padding:3px 10px; border-radius:999px;
  background:#eceff3; color:#2b3445; white-space:nowrap; }
.kc-chip-o{ background:#fff0e0; color:#8a4207; }
.kc-chip-g{ background:#e4f3ea; color:#1b6b3d; }
.kc-chip-b{ background:#e6effb; color:#174f92; }
.kc-kontakti{ display:flex; gap:6px 28px; flex-wrap:wrap; font-size:14px; margin:4px 0 10px; }
.kc-row{ display:flex; justify-content:space-between; flex-wrap:wrap; gap:6px 12px; align-items:center;
  font-size:14px; padding:9px 0; border-top:1px solid var(--kc-line2); }
.kc-row .kc-r{ display:flex; gap:6px; flex-wrap:wrap; align-items:center; text-align:right; }
.kc-nums{ display:flex; gap:8px 20px; flex-wrap:wrap; }
.kc-num{ display:flex; flex-direction:column; gap:2px; font-size:13px; color:var(--kc-muted); }
.kc-num b{ font-size:20px; font-weight:600; color:var(--kc-ink); }
.kc-num b.o{ color:#8a4207; }
.kc-ev{ display:flex; flex-direction:column; gap:2px; font-size:14px; padding:9px 0; border-top:1px solid var(--kc-line2); }
.kc-ev .d{ font-size:13px; color:var(--kc-muted); }
.kc-prazno{ font-size:14px; color:var(--kc-muted); padding:6px 0; }
.kc-tbl{ width:100%; border-collapse:collapse; font-size:14px; border:0 !important; }
.kc-tbl tr, .kc-tbl th, .kc-tbl td{ border-left:0 !important; border-right:0 !important; border-top:0 !important; background:transparent !important; }
.kc-tbl th{ text-align:left; font-weight:600; color:var(--kc-muted); padding:8px; border-bottom:1px solid var(--kc-line); white-space:nowrap; }
.kc-tbl td{ padding:9px 8px; border-bottom:1px solid var(--kc-line2); vertical-align:middle; }
.kc-tbl td.r, .kc-tbl th.r{ text-align:right; }

/* ---------- PDV trake (stil.napredak) — prenesene iz caki_stil, u novim bojama ---------- */
.caki-traka-blok{ background:#fff; border:1px solid var(--kc-line); border-radius:12px; padding:16px 18px; }
.caki-traka-blok .hd{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:4px; }
.caki-traka-blok .hd b{ font-size:14px; font-weight:600; }
.caki-traka-blok .hd span{ font-size:12px; color:var(--kc-muted); }
.caki-traka{ margin-top:16px; }
.caki-traka .head{ display:flex; align-items:baseline; justify-content:space-between; gap:10px; }
.caki-traka .nm{ font-size:14px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.caki-traka .pc{ font-size:13px; font-weight:700; flex:0 0 auto; }
.caki-traka .bar{ margin-top:8px; height:10px; border-radius:999px; background:#eef0f3; overflow:hidden; }
.caki-traka .fill{ height:100%; border-radius:999px; }
.caki-traka .ft{ margin-top:7px; display:flex; justify-content:space-between; gap:8px; font-size:12px; color:var(--kc-muted); }
.caki-traka .ft b{ color:var(--kc-ink); font-weight:600; }
.caki-traka .op{ margin-top:4px; font-size:12px; font-weight:600; }

/* ---------- 3.11.2026.: zajedničko za portale (profesori, Moj CAKI, testovi) ---------- */
.stApp [class*="st-key-box_"]{ background:#fff; border:1px solid var(--kc-line); border-radius:12px; padding:18px 20px; gap:10px; }
.stApp [class*="st-key-nav_traka"]{ border-bottom:1px solid var(--kc-line); gap:0 !important; flex-wrap:nowrap !important;
  overflow-x:auto; padding:0; margin-bottom:6px; }
.stApp [class*="st-key-nav_traka"] button{ background:transparent !important; border:0 !important; border-radius:0 !important;
  border-bottom:3px solid transparent !important; min-height:46px; padding:10px 10px; box-shadow:none !important; }
.stApp [class*="st-key-nav_traka"] button p{ font-size:14.5px !important; color:#3c4556 !important; white-space:nowrap; }
.stApp [class*="st-key-nav_traka"] button:hover{ background:#eceff3 !important; }
.stApp [class*="st-key-nav_traka"] button[data-testid="stBaseButton-primary"]{ border-bottom-color:var(--kc-blue) !important; }
.stApp [class*="st-key-nav_traka"] button[data-testid="stBaseButton-primary"] p{ color:var(--kc-ink) !important; font-weight:600; }
.stApp [data-testid="stDataFrame"]{ border:1px solid var(--kc-line); border-radius:10px; overflow:hidden; background:#fff; }

.stApp [data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]){ border-radius:12px; }
.kc-tile-btn{ font-size:14px; }
.kc-pozdrav{ font-size:13px; color:var(--kc-muted); margin-bottom:2px; }

@media (max-width: 640px){
  .kc-h1{ font-size:23px; }
  [data-testid="stMainBlockContainer"], .block-container{ padding-left:1rem; padding-right:1rem; }
}
</style>
"""




def primijeni() -> None:
    """Ubaci CSS teme. Zove se jednom, odmah nakon st.set_page_config()."""
    st.markdown(CSS, unsafe_allow_html=True)


def _slug(tekst: str) -> str:
    """Ključ gumba neovisan o broju u zagradi i emojiju: '✅ Zadaci (3)' → 'zadaci'."""
    t = re.sub(r"\(\d+\)", "", str(tekst)).lower()
    for a, b in (("č", "c"), ("ć", "c"), ("ž", "z"), ("š", "s"), ("đ", "d")):
        t = t.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "_", t).strip("_") or "x"


def nav(stavke: list[str], kljuc: str, zadano: str | None = None) -> str:
    """Traka kartica od gumba (aktivna = plava crta). Vraća OSNOVNI naziv odabrane kartice
    (bez broja u zagradi). Za razliku od st.tabs, iscrtava se samo odabrana kartica."""
    osnovni = [re.sub(r"\s*\(\d+\)$", "", s) for s in stavke]
    stanje = f"{kljuc}_aktivna"
    aktivna = st.session_state.get(stanje)
    if aktivna not in osnovni:
        aktivna = zadano if zadano in osnovni else osnovni[0]
        st.session_state[stanje] = aktivna
    with st.container(horizontal=True, gap=None, key=f"nav_traka_{kljuc}"):
        for s, o in zip(stavke, osnovni):
            st.button(s, key=f"nav_{kljuc}_{_slug(o)}", type="primary" if o == aktivna else "secondary",
                      on_click=st.session_state.__setitem__, args=(stanje, o))
    return aktivna


def idi_na(kljuc: str, naziv: str) -> None:
    """Za gumbe „Otvori …”: prebaci traku `kljuc` na karticu `naziv` (osnovni naziv)."""
    st.session_state[f"{kljuc}_aktivna"] = naziv


def chip(tekst: str, vrsta: str = "") -> str:
    """vrsta: '' (sivo) · 'o' (narančasto, treba pažnju) · 'g' (zeleno) · 'b' (plavo, info)."""
    kl = f"kc-chip kc-chip-{vrsta}" if vrsta else "kc-chip"
    return f'<span class="{kl}">{html.escape(str(tekst))}</span>'


def redak(lijevo_html: str, desno_html: str = "") -> str:
    return f'<div class="kc-row"><span>{lijevo_html}</span><span class="kc-r">{desno_html}</span></div>'


def kutija(kljuc: str):
    """Bijela kartica s tankim rubom (kao pločice na kartici učenika u CRM-u)."""
    return st.container(key=f"box_{kljuc}")


def html_(s: str) -> None:
    st.markdown(s, unsafe_allow_html=True)
