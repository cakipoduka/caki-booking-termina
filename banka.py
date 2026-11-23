"""
ZA SLJEDEĆEG AGENTA: BANKA: baza zadataka → zamrznuti zadatak. Aliasi (`max_bodovi`, `biblioteka_izvora`), opcije u 5 formata + LaTeX zaštita, prikaz opcija preuzet iz pipelinea.

CAKI testovi v2 — `banka.py`
ČITANJE POSTOJEĆE BAZE ZADATAKA (20.000+ zadataka) — **samo čitanje**, baza se ne dira.

Baza ostaje tamo gdje je (`Zadaci` u `caki-baza-zadataka`), a novi sustav iz nje uzima zadatke i
**zamrzava ih u test**. Time izmjena u bazi nikad ne mijenja test koji je već objavljen.

Novo u v2 (Cakijev zahtjev 24.10.): **🎬 video uz rješenje** (`video_url`, `video_naslov`) — prikazuje
se učeniku **nakon testa**, nikad tijekom rješavanja.
"""
from __future__ import annotations

import re as _re

import re
import model
import tablice

TAB_ZADACI = "Zadaci"
STUPAC_VIDEO = "video_url"
STUPAC_VIDEO_NASLOV = "video_naslov"


# ------------------------------------------------------------------ video (samo čitanje!)

def stupci_videa(sheet) -> dict:
    """Postoji li `video_url` u bazi? **Ne dodaje ništa** — živa baza se ne mijenja.

    Cakijeva napomena 25.10.2026.: video rješenja su **već planirana u bazi** (stupac `video_url`
    postoji u shemi), samo još nisu snimljena. Zato novi sustav taj stupac samo čita.
    """
    try:
        ws = sheet.worksheet(TAB_ZADACI)
    except Exception:                                   # noqa: BLE001
        return {"postoji": False, "stupac": STUPAC_VIDEO, "stupac_naslov": ""}
    zaglavlje = [model.tekst(h) for h in (ws.row_values(1) or [])]
    return {
        "postoji": STUPAC_VIDEO in zaglavlje,
        "stupac": STUPAC_VIDEO,
        "stupac_naslov": STUPAC_VIDEO_NASLOV if STUPAC_VIDEO_NASLOV in zaglavlje else "",
        "stupaca": len(zaglavlje),
    }


# ------------------------------------------------------------------ čitanje

def ucitaj(sheet) -> list[dict]:
    """Svi zadaci iz baze (retci taba `Zadaci`)."""
    return tablice.ucitaj(sheet, TAB_ZADACI)


def _zakrpi_latex(tekst: str) -> str:
    """Udvostruči pojedinačne backslashe da JSON ne pojede `\\frac`, `\\alpha`…"""
    import re

    return re.sub(r"(?<!\\)\\(?!\\)", r"\\\\", tekst)


def _ima_kontrolne(tekst: str) -> bool:
    return any(ord(z) < 32 and z not in "\n\r\t" for z in str(tekst or ""))


def _opcije_za_zadatak(opcije, visestruki: bool, redak: dict) -> list:
    """Ako su opcije placeholder „slika A"… → vrati **imena slika** redom (A, B, C, D).

    Preuzeto pravilo iz v1 (`_opcije_su_slike_info`, 28.10.2026.): samo kad SVE opcije odgovaraju
    obrascu; inače opcije ostaju kakve jesu (tekst).
    """
    if not visestruki:
        return opcije
    je_slike, _slika_pitanja, nazivi = opcije_su_slike_info(
        opcije, "visestruki_izbor", redak.get("slika_putanja") or redak.get("slika"))
    return nazivi if je_slike else opcije


def _opcije(retak: dict) -> list[str]:
    """Ponuđeni odgovori u svim oblicima: JSON lista, Python lista, `;`, prijelomi, „A) …”.

    Preuzeto pravilo iz pipelinea (točka 13): baza drži JSON listu **bez** oznaka A/B/C/D —
    ali stariji zapisi i ručni unos imaju druge oblike, pa se svi prihvaćaju.
    """
    sirovo = (retak or {}).get("ponudjeni_odgovori")
    if isinstance(sirovo, (list, tuple)):
        return [model.tekst(o) for o in sirovo if model.tekst(o)]
    tekst = model.tekst(sirovo)
    if not tekst:
        return []

    # 1) JSON lista — UVIJEK preko `_zakrpi_latex` (JSON inače pojede `\frac`, `\alpha`…)
    import json

    for pokusaj in (tekst, tekst.replace("'", '"')):
        for kandidat in (_zakrpi_latex(pokusaj), pokusaj):
            try:
                podaci = json.loads(kandidat)
            except Exception:                          # noqa: BLE001
                podaci = None
            if isinstance(podaci, list):
                ocisceno = [model.tekst(o) for o in podaci if model.tekst(o)]
                if ocisceno and not any(_ima_kontrolne(o) for o in ocisceno):
                    return ocisceno
            elif isinstance(podaci, str) and podaci.strip() and podaci != tekst:
                tekst = pokusaj = podaci.strip()
                break

    # 2) Python literal (npr. "['x=1', 'x=2']")
    import ast

    try:
        podaci = ast.literal_eval(tekst)
        if isinstance(podaci, (list, tuple)):
            ocisceno = [model.tekst(o) for o in podaci if model.tekst(o)]
            if ocisceno:
                return ocisceno
    except Exception:                                  # noqa: BLE001
        pass

    # 3) tekst: `;`, prijelomi redaka ili `|`
    sirovi_dijelovi = []
    for sep in (";", "\n", "|"):
        if sep in tekst:
            sirovi_dijelovi = tekst.split(sep)
            break
    if not sirovi_dijelovi:
        sirovi_dijelovi = [tekst]

    izlaz = []
    for dio in sirovi_dijelovi:
        d = model.tekst(dio)
        if not d:
            continue
        # skini oznaku „A)", „b.", „C:”
        if len(d) > 2 and d[0].upper() in "ABCDEFGHIJ" and d[1] in ")]:.-":
            d = model.tekst(d[2:])
        if d:
            izlaz.append(d)
    return izlaz


def zadatak_iz_retka(retak: dict) -> dict | None:
    """Bazin redak → zamrznuti zadatak za test. None ako zadatak nije upotrebljiv."""
    r = retak or {}
    zid = model.tekst(r.get("id"))
    tekst = model.tekst(prvo(r, "tekst_zadatka_latex"))
    if not zid or not tekst:
        return None
    odgovor = model.tekst(prvo(r, "konacan_odgovor"))
    opcije = _opcije(r)
    _tip_tekst = " ".join(model.tekst(prvo(r, "tip_zadatka")).lower().split())
    _izgleda_kao_izbor = (not _tip_tekst
                          or "izbor" in _tip_tekst
                          or "vise" in _tip_tekst
                          or "više" in _tip_tekst
                          or "multiple" in _tip_tekst)
    visestruki = (len(opcije) >= 2 and _izgleda_kao_izbor)
    return {
        "id": zid,
        "tekst": tekst,
        "tip": "visestruki_izbor" if visestruki else "kratki_odgovor",
        "opcije": _opcije_za_zadatak(opcije, visestruki, r),
        "odgovor": odgovor,
        "bodovi": model.broj(prvo(r, "bodovi", 1), 1) or 1,
        "slika": model.tekst(prvo(r, "slika_putanja")),
        "video_url": model.tekst(r.get(STUPAC_VIDEO)),
        "video_naslov": model.tekst(r.get(STUPAC_VIDEO_NASLOV)),
        "cjelina": model.tekst(r.get("cjelina")),
        "potpoglavlje": model.tekst(r.get("potpoglavlje")),
        "tezina": model.tekst(r.get("tezina")),
        "bloom": model.tekst(prvo(r, "bloom")),
        "izvor": model.tekst(prvo(r, "izvor")),
        "razred": model.tekst(r.get("razred")),
    }


def svi_zadaci(sheet) -> list[dict]:
    """Svi upotrebljivi zadaci, normalizirani (preskače skupine i prazne)."""
    izlaz = []
    for r in ucitaj(sheet):
        if model.tekst(r.get("uloga")).lower() == "skupina":
            continue
        z = zadatak_iz_retka(r)
        if z:
            izlaz.append(z)
    return izlaz


def po_id(zadaci: list[dict]) -> dict[str, dict]:
    return {model.tekst(z.get("id")): z for z in zadaci or [] if model.tekst(z.get("id"))}



# ------------------------------------------------------------------ štit za shemu

# Stupci koje v2 STVARNO čita iz taba `Zadaci`. Ako se neki preimenuje ili obriše,
# `provjeri_shemu()` to javi — bolje nego da polja tiho postanu prazna.
# STVARNO obavezno: bez ovoga zadatak nije upotrebljiv.
# ------------------------------------------------------------------ aliasi stupaca

# Baza je mijenjana kroz vrijeme, pa isti podatak ima različita imena. Umjesto tvrdog naziva —
# **prvi koji postoji**. Tako radi i sa starom i s novom shemom.
ALIASI = {
    "bodovi": ("bodovi", "max_bodovi", "poeni", "bod", "vrijednost_bodova"),
    "bloom": ("bloom", "bloom_razina", "kognitivna_razina", "kognitivno"),
    "tekst_zadatka_latex": ("tekst_zadatka_latex", "tekst_zadatka_mathjax", "tekst"),
    "konacan_odgovor": ("konacan_odgovor", "odgovor", "rjesenje_kratko"),
    "tip_zadatka": ("tip_zadatka", "tip"),
    "slika_putanja": ("slika_putanja", "slika"),
    "izvor": ("biblioteka_izvora", "izvor_naziv", "izvor"),
}


def prvo(retak: dict, kljuc: str, zadano=""):
    """Prva neprazna vrijednost među aliasima za `kljuc` (npr. `bodovi` ili `max_bodovi`)."""
    r = retak or {}
    for ime in ALIASI.get(kljuc, (kljuc,)):
        vrijednost = model.tekst(r.get(ime))
        if vrijednost:
            return r.get(ime)
    return zadano


STUPCI_KOJE_CITAMO = ["id", "tekst_zadatka_latex", "konacan_odgovor"]
# Poželjno, ali se čita kroz aliasе (npr. `max_bodovi` umjesto `bodovi`) — ne blokira rad.
STUPCI_S_ALIASIMA = {
    "bodovi": ALIASI["bodovi"],
    "bloom": ALIASI["bloom"],
    "tip_zadatka": ALIASI["tip_zadatka"],
    "ponudjeni_odgovori": ("ponudjeni_odgovori",),
    "slika_putanja": ALIASI["slika_putanja"],
    "cjelina": ("cjelina",),
    "potpoglavlje": ("potpoglavlje",),
    "tezina": ("tezina",),
    "video_url": ("video_url",),
}
# Neobavezni (ako ih nema, sustav radi dalje)
STUPCI_NEOBAVEZNI = ["uloga", "izvor_naziv", "razred", "max_bodovi", "rjesenje"]


# ------------------------------------------------------------------ skupine (a), b), c) — v1

def _zamrzni_skupinu(jed: dict) -> dict | None:
    """Skupina (uvod + stavke) → zamrznuti zadatak s `stavke` za PDF."""
    import skupine as _sk

    glavni = jed.get("glavni") or {}
    z = zadatak_iz_retka(glavni)
    if not z:
        return None
    stavke = []
    for st in jed.get("stavke") or []:
        s = zadatak_iz_retka(st)
        if not s:
            continue
        s["oznaka_stavke"] = model.tekst(st.get("oznaka_stavke"))
        # `izgradi_stavke_blok` traži ovo polje
        s["tekst_zadatka_latex"] = model.tekst(st.get("tekst_zadatka_latex")) \
            or model.tekst(st.get("tekst"))
        stavke.append(s)
    if not stavke:
        return z                                        # nema stavki → običan zadatak
    z["stavke"] = stavke
    z["bodovi"] = model.broj(_sk.zbroji_bodove(jed.get("stavke") or []), z.get("bodovi") or 1) or 1
    return z


def svi_zadaci_grupirani(sheet) -> list[dict]:
    """Zadaci kao JEDINICE: samostalni zadatak ili skupina sa stavkama (a, b, c…).

    Koristi preuzeti `skupine.grupiraj` (isto kao v1) — jedinica je ono što profesor dodaje u test.
    """
    import skupine as _sk

    redci = ucitaj(sheet)
    jedinice, _upozorenja = _sk.grupiraj(redci)
    izlaz = []
    for jed in jedinice:
        if (jed or {}).get("tip") == _sk.ULOGA_SKUPINA:
            z = _zamrzni_skupinu(jed)
            if z:
                izlaz.append(z)
        else:
            z = zadatak_iz_retka(jed.get("glavni") or {})
            if z:
                izlaz.append(z)
    return izlaz


def provjeri_shemu(sheet) -> dict:
    """Koje od očekivanih stupaca baza ima, a koji nedostaju. Ne mijenja ništa.

    Vraća {"postoji", "stupaca", "nedostaju": [...], "neobavezni_nedostaju": [...], "zaglavlje": [...]}
    """
    try:
        ws = sheet.worksheet(TAB_ZADACI)
        zagl = [model.tekst(h) for h in (ws.row_values(1) or [])]
    except Exception:                                   # noqa: BLE001
        return {"postoji": False, "stupaca": 0, "nedostaju": list(STUPCI_KOJE_CITAMO),
                "neobavezni_nedostaju": list(STUPCI_NEOBAVEZNI), "zaglavlje": []}
    ima = set(zagl)
    # nedostaje = nema ni jedan od aliasa
    nedostaju = [s for s in STUPCI_KOJE_CITAMO if s not in ima]
    bez_aliasa = [k for k, imena in STUPCI_S_ALIASIMA.items() if not any(i in ima for i in imena)]
    return {
        "postoji": True,
        "stupaca": len(zagl),
        "nedostaju": nedostaju,
        "neobavezni_nedostaju": bez_aliasa,
        "zaglavlje": zagl,
    }


# ------------------------------------------------------------------ pretraga

def filtriraj(zadaci: list[dict], *, tekst: str = "", cjelina: str = "", potpoglavlje: str = "",
              tezina: str = "", tip: str = "", bloom: str = "", ima_video=None,
              ima_sliku=None) -> list[dict]:
    """Filtriranje baze za slaganje testa. Prazan filtar ne ograničava."""
    t = model.tekst(tekst).lower()
    izlaz = []
    for z in zadaci or []:
        if t and t not in (model.tekst(z.get("tekst")) + " " + model.tekst(z.get("id"))).lower():
            continue
        if cjelina and model.tekst(z.get("cjelina")) != cjelina:
            continue
        if potpoglavlje and model.tekst(z.get("potpoglavlje")) != potpoglavlje:
            continue
        if tezina and model.tekst(z.get("tezina")) != tezina:
            continue
        if tip and model.tekst(z.get("tip")) != tip:
            continue
        if bloom and model.tekst(z.get("bloom")) != bloom:
            continue
        if ima_video is True and not model.tekst(z.get("video_url")):
            continue
        if ima_video is False and model.tekst(z.get("video_url")):
            continue
        if ima_sliku is True and not model.tekst(z.get("slika")):
            continue
        izlaz.append(z)
    return izlaz


def vrijednosti(zadaci: list[dict], polje: str) -> list[str]:
    """Jedinstvene vrijednosti polja (za padajuće izbornike), sortirane."""
    return sorted({model.tekst((z or {}).get(polje)) for z in zadaci or [] if model.tekst((z or {}).get(polje))})


def brojevi(zadaci: list[dict]) -> dict:
    """Sazetak baze po cjelinama/težinama — za „ima li dovoljno zadataka" prije slaganja."""
    po_cjelini, po_tezini = {}, {}
    for z in zadaci or []:
        cj = model.tekst(z.get("cjelina")) or "— bez cjeline —"
        te = model.tekst(z.get("tezina")) or "— bez težine —"
        po_cjelini[cj] = po_cjelini.get(cj, 0) + 1
        po_tezini[te] = po_tezini.get(te, 0) + 1
    return {"ukupno": len(zadaci or []), "po_cjelini": po_cjelini, "po_tezini": po_tezini,
            "sa_videom": sum(1 for z in zadaci or [] if model.tekst(z.get("video_url")))}


# ------------------------------------------------------------------ video

def video_za(zadatak: dict) -> dict | None:
    """🎬 Video uz zadatak (za prikaz NAKON testa). None ako ga nema."""
    url = model.tekst((zadatak or {}).get("video_url"))
    if not url:
        return None
    return {"url": url, "naslov": model.tekst((zadatak or {}).get("video_naslov")) or "Objašnjenje zadatka"}


def postavi_video(sheet, zadatak_id: str, url: str, naslov: str = "") -> tuple[bool, str]:
    """Upiše video u **postojeći** stupac `video_url`. Nikad ne dodaje stupac u živu bazu.

    Vraća (uspjelo, poruka). Ako stupca nema — Caki ga treba dodati ručno u Sheetu.
    """
    info = stupci_videa(sheet)
    if not info["postoji"]:
        return False, (f"U bazi nema stupca `{STUPAC_VIDEO}`. Dodaj ga ručno u tab `Zadaci` "
                       "(novi zadnji stupac) — sustav ga ne dodaje sam u živu bazu.")
    ws = sheet.worksheet(TAB_ZADACI)
    zaglavlje = [model.tekst(h) for h in (ws.row_values(1) or [])]
    if "id" not in zaglavlje:
        return False, "Baza nema stupac `id`."
    i_id = zaglavlje.index("id")
    for br, red in enumerate(ws.get_all_values()[1:], start=2):
        if i_id < len(red) and model.tekst(red[i_id]) == model.tekst(zadatak_id):
            ws.update_cell(br, zaglavlje.index(STUPAC_VIDEO) + 1, model.tekst(url))
            if naslov and info["stupac_naslov"]:
                ws.update_cell(br, zaglavlje.index(STUPAC_VIDEO_NASLOV) + 1, model.tekst(naslov))
            return True, "Snimljeno."
    return False, "Zadatak nije nađen u bazi."
    i_id = zaglavlje.index("id")
    for br, red in enumerate(ws.get_all_values()[1:], start=2):
        if i_id < len(red) and model.tekst(red[i_id]) == model.tekst(zadatak_id):
            ws.update_cell(br, zaglavlje.index(STUPAC_VIDEO) + 1, model.tekst(url))
            if STUPAC_VIDEO_NASLOV in zaglavlje:
                ws.update_cell(br, zaglavlje.index(STUPAC_VIDEO_NASLOV) + 1, model.tekst(naslov))
            return True
    return False

# ------------------------------------------------------------------ prikaz opcija
# PREUZETO iz `caki-baza-zadataka/baza_zadataka_pipeline.py` (isti prikaz kao u bazi).
# 05.11.2026. (Claudeov nalaz iz TRACKER-a, primijenio DeepSeek): prije brojanja slova BRIŠU
# se LaTeX naredbe (`\rangle`, `\cap`, `\langle`…). Bez toga `[-1,1\rangle \cap\langle 3,5]`
# ima 15 „slova" naspram 14 ostalih znakova → heuristika ga proglasi rečenicom i opcija se
# prikaže doslovno, bez renderiranja.
_LATEX_NAREDBA_RE = re.compile(r"\\[a-zA-Z]+")


def _izgleda_kao_recenica(raw):
    """Heuristika: ako sadrži razmak I ima više slova nego brojeva/simbola, vjerojatno je
    obična rečenica (npr. 'ne može se odrediti'), a ne matematički izraz.

    LaTeX naredbe se prije brojanja uklanjaju — one nisu riječi. Prava rečenica s pokojom
    naredbom („ne postoji \\infty rješenje") i dalje ostaje rečenica.
    """
    tekst = model.tekst(raw)
    if " " not in tekst:
        return False
    bez_naredbi = _LATEX_NAREDBA_RE.sub("", tekst)
    slova = sum(c.isalpha() for c in bez_naredbi)
    ostalo = len(bez_naredbi) - slova
    return slova > ostalo

SLOVA_PONUDJENIH_ODGOVORA = ["A", "B", "C", "D", "E", "F", "G", "H"]


def prikazi_opcije_markdown(ponudjeni_odgovori) -> str:
    """Vraća Markdown string za PREGLED ponuđenih odgovora (višestruki izbor) u Streamlit
    sučelju (ne za LaTeX!) - Streamlitov st.markdown zna renderirati $...$ preko KaTeX-a.
    Baza sprema opcije BEZ $ omotača (čist LaTeX), pa ih ovdje samo omatamo radi prikaza -
    isto načelo kao formatiraj_opciju() u pages/2_test_builder.py, ali za Streamlit prikaz,
    ne za LaTeX izlaz. Zajednička funkcija za baza_zadataka_app.py (stranica 'Uredi zadatak')
    i pages/2_test_builder.py (pregled u pretrazi/odabiru) - da se prikaz opcija ne dupllicira
    na dva mjesta i ne razmimoiđe (npr. broj podržanih slova A-?).

    POPRAVAK (11.9.2026.): opcija se više NE omata bezuvjetno u $...$ kad nema eksplicitnog
    $ znaka - to je uzrokovalo da običan tekst (npr. "ne postoji rješenje") KaTeX renderira
    kao matematiku, gdje se razmaci između riječi ignoriraju (riječi se prikazuju spojene i
    kurzivom - vidi prijavljeni bug, 11.9.2026.). Umjesto toga koristi se ista heuristika kao
    _pretext_math_or_text/_izgleda_kao_recenica niže u ovoj datoteci (PreTeXt izlaz): ako
    opcija izgleda kao rečenica (ima razmak i pretežno je od slova), tretira se kao OBIČAN
    TEKST, bez $...$ omota; inače (kratak matematički izraz, npr. "3x-9" ili "√2") i dalje se
    omata u $...$ kao dosad. Ovo je heuristika, ne savršena - za rubne slučajeve gdje
    heuristika promaši, autor može ručno upisati $ znakove izravno u opciju (grana "$" in
    opcija iznad uvijek ima prednost)."""
    dijelovi = []
    for i, opcija in enumerate(ponudjeni_odgovori):
        opcija = (opcija or "").strip()
        if not opcija:
            continue
        if "$" in opcija:
            prikaz = opcija
        elif _izgleda_kao_recenica(opcija):
            prikaz = opcija
        else:
            prikaz = f"${opcija}$"
        slovo = SLOVA_PONUDJENIH_ODGOVORA[i] if i < len(SLOVA_PONUDJENIH_ODGOVORA) else str(i + 1)
        dijelovi.append(f"**{slovo})** {prikaz}")
    return "  ".join(dijelovi)


# ------------------------------------------------------------------ opcije koje su SLIKE

# Obrazac iz v1 (`_SLIKA_OPCIJA_RE`): placeholder koji AI upisuje pri uvozu — „slika A", „Slika B"…
_SLIKA_OPCIJA_RE = _re.compile(r"^slika\s*[A-Ha-h]$", _re.IGNORECASE)


def opcije_su_slike_info(opcije, tip_zadatka: str, slika_putanja) -> tuple:
    """Preuzeto iz v1 (`_opcije_su_slike_info`, 28.10.2026.).

    Vraća `(jesu_li_slike, slika_pitanja_ili_None, [nazivi_slika_opcija])`.
    Prepoznaje se **samo** kad SVE opcije odgovaraju obrascu „slika X" — običan tekst i brojevi
    ovo nikad ne pogode. Ako se broj slika ne poklapa s brojem opcija → siguran fallback (False).
    """
    if tip_zadatka != "visestruki_izbor" or len(opcije or []) < 2:
        return False, None, []
    if not all(_SLIKA_OPCIJA_RE.match(model.tekst(o).strip()) for o in opcije):
        return False, None, []
    import re as _re2

    nazivi = [x.strip() for x in _re2.split(r"[|,]", model.tekst(slika_putanja)) if x.strip()]
    if len(nazivi) == len(opcije):
        return True, None, nazivi
    if len(nazivi) == len(opcije) + 1:
        return True, nazivi[0], nazivi[1:]
    return False, None, []


def je_url_slika(opcija) -> bool:
    """Je li ponuđeni odgovor zapravo URL slike (Mathpix crop i sl.)?"""
    t = model.tekst(opcija).lower()
    return (t.startswith("http://") or t.startswith("https://")) and any(
        t.split("?")[0].endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp")
    )


def opcije_markdown(zadatak: dict) -> str:
    """Markdown s ponuđenim odgovorima A) … — radi i za **bazu** i za **zamrznuti** zadatak."""
    z = zadatak or {}
    opcije = z.get("opcije")
    if not isinstance(opcije, (list, tuple)):
        opcije = _opcije(z)
    opcije = [model.tekst(o) for o in (opcije or []) if model.tekst(o)]
    if not opcije:
        return ""
    if any(je_url_slika(o) for o in opcije):
        dijelovi = []
        for i, o in enumerate(opcije):
            slovo = chr(65 + i)
            if je_url_slika(o):
                dijelovi.append(f"**{slovo})** <img src='{o}' style='max-height:70px'>")
            else:
                dijelovi.append(f"**{slovo})** {o}")
        return " &nbsp; ".join(dijelovi)
    try:
        return prikazi_opcije_markdown(opcije)
    except Exception:                                  # noqa: BLE001
        return "  ".join(f"**{chr(65 + i)})** {o}" for i, o in enumerate(opcije))
