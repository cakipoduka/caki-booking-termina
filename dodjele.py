"""
CAKI testovi v2 — `dodjele.py`
KOME JE TEST POSLAN — i zašto to više nije „N redaka s istom serijom".

Cakijev bug 24.10.: test objavljen grupi nije se mogao dopuniti pojedinačnim učenicima. Uzrok nije
bio u sučelju, nego u modelu: nije postojalo mjesto koje pamti **kome je test poslan**. Ovdje je to
mjesto — jedan redak u `Dodjele` po učeniku. Dodavanje učenika je zato **nova dodjela**, a ne
ponovna objava (koja je prije mogla napraviti duplikat).
"""
from __future__ import annotations

from datetime import timedelta

import model
import tablice

STATUSI = ("dodijeljeno", "u_tijeku", "predano", "ocijenjeno")


def _seed(definicija_id: str, ucenik_id: str) -> str:
    """Stabilan seed za A/B miješanje: isti učenik uvijek dobije isti redoslijed."""
    return f"{model.tekst(definicija_id)}:{model.tekst(ucenik_id).upper()}"


def nova_dodjela(*, dodjela_id: str, definicija_id: str, ucenik_id: str, ime_djeteta: str = "",
                 grupa: str = "", rok_od: str = "", rok_do: str = "", dodijelio: str = "",
                 status: str = "dodijeljeno") -> dict:
    uid = model.tekst(ucenik_id).upper()
    return {
        "dodjela_id": model.tekst(dodjela_id),
        "definicija_id": model.tekst(definicija_id),
        "ucenik_id": uid,
        "ime_djeteta": model.tekst(ime_djeteta),
        "grupa": model.tekst(grupa),
        "rok_od": model.iso_datum(rok_od),
        "rok_do": model.iso_datum(rok_do),
        "varijanta_seed": _seed(definicija_id, uid),
        "status": status if status in STATUSI else "dodijeljeno",
        "dodijelio": model.tekst(dodijelio),
        "dodijeljeno": model.sada_iso(),
    }


def _kljuc(dodjela) -> tuple[str, str]:
    return (model.tekst((dodjela or {}).get("definicija_id")),
            model.tekst((dodjela or {}).get("ucenik_id")).upper())


def postojece(sheet, definicija_id: str) -> dict[str, dict]:
    """{ucenik_id: dodjela} — za provjeru duplikata i za prikaz „kome je već poslan"."""
    izlaz = {}
    for d in tablice.ucitaj(sheet, tablice.TAB_DODJELE):
        if model.tekst(d.get("definicija_id")) == model.tekst(definicija_id):
            uid = model.tekst(d.get("ucenik_id")).upper()
            if uid:
                izlaz[uid] = d
    return izlaz


def dodaj(sheet, definicija: dict, ucenici, *, grupa: str = "", rok_od: str = "", rok_do: str = "",
          dodijelio: str = "") -> dict:
    """Dodijeli test nizu učenika. **Idempotentno**: tko ga već ima, preskače se.

    `ucenici` = [{"ucenik_id", "ime_djeteta"}] ili popis šifri.
    Vraća {"dodano": Int, "preskoceno": [ime/šifra], "dodjele": [novi retci]}.
    """
    definicija_id = model.tekst((definicija or {}).get("definicija_id"))
    if not definicija_id:
        raise ValueError("Nedostaje definicija_id.")
    if model.tekst((definicija or {}).get("status")) == "arhiviran":
        raise ValueError("Arhiviranom testu se ne mogu dodavati učenici.")

    ima = postojece(sheet, definicija_id)
    svi = tablice.svi_idovi(sheet, tablice.TAB_DODJELE, "dodjela_id")
    prefiks = "D" + (definicija_id[1:3] if len(definicija_id) > 2 else "26") + "-"

    novi, preskoceno = [], []
    for u in ucenici or ():
        if isinstance(u, dict):
            uid = model.tekst(u.get("ucenik_id")).upper()
            ime = model.tekst(u.get("ime_djeteta"))
        else:
            uid, ime = model.tekst(u).upper(), ""
        if not uid:
            continue
        if uid in ima:
            preskoceno.append(ime or uid)
            continue
        tablice_id = tablice.novi_id(svi, prefiks)
        svi.append(tablice_id)
        redak = nova_dodjela(dodjela_id=tablice_id, definicija_id=definicija_id, ucenik_id=uid,
                             ime_djeteta=ime, grupa=grupa, rok_od=rok_od, rok_do=rok_do,
                             dodijelio=dodijelio)
        novi.append(redak)
        ima[uid] = redak

    if novi:
        tablice.dodaj(sheet, tablice.TAB_DODJELE, novi)
        tablice.zapisi_radnju(sheet, dodijelio, "dodjela", definicija_id,
                             f"{len(novi)} učenika" + (f" · {grupa}" if grupa else ""))
    return {"dodano": len(novi), "preskoceno": preskoceno, "dodjele": novi}


def ukloni(sheet, definicija_id: str, ucenik_id: str, *, korisnik: str = "") -> tuple[bool, str]:
    """Ukloni učenika s testa. **Ne dopušta** ako je već predao (rezultat je dokaz)."""
    from provedba import pokusaji_ucenika  # lokalni uvoz: nema kružne ovisnosti na razini modula

    uid = model.tekst(ucenik_id).upper()
    dodjela = postojece(sheet, definicija_id).get(uid)
    if not dodjela:
        return False, "Taj učenik nema ovaj test."
    pokusaji = pokusaji_ucenika(sheet, model.tekst(dodjela.get("dodjela_id")))
    if any(model.tekst(p.get("status")) in ("predano", "po_isteku") for p in pokusaji):
        return False, "Učenik je već predao — dodjela se ne može obrisati (rezultat ostaje)."
    ok = tablice.obrisi(sheet, tablice.TAB_DODJELE, "dodjela_id", model.tekst(dodjela.get("dodjela_id")))
    if ok:
        tablice.zapisi_radnju(sheet, korisnik, "uklonjen", f"{definicija_id}/{uid}")
    return ok, "Uklonjeno." if ok else "Nije uspjelo."


def za_definiciju(sheet, definicija_id: str) -> list[dict]:
    return [d for d in tablice.ucitaj(sheet, tablice.TAB_DODJELE)
            if model.tekst(d.get("definicija_id")) == model.tekst(definicija_id)]


def za_ucenika(sheet, ucenik_id: str) -> list[dict]:
    uid = model.tekst(ucenik_id).upper()
    return [d for d in tablice.ucitaj(sheet, tablice.TAB_DODJELE)
            if model.tekst(d.get("ucenik_id")).upper() == uid]


def jedna(sheet, definicija_id: str, ucenik_id: str) -> dict | None:
    return postojece(sheet, definicija_id).get(model.tekst(ucenik_id).upper())


def rok_dodjele(dodjela: dict, definicija: dict, danas=None) -> dict:
    """Rok za TOG učenika (Cakijeve odluke 1, 2 i 5).

    - prednost ima rok na dodjeli (po grupi/učeniku), inače rok s definicije;
    - **ako je učenik dodan nakon isteka roka, prozor mu počinje danom dodjele** i traje taj dan
      („dodavanje poslije roka — teče od dodjele");
    - vraća i `produzen` da sučelje može pokazati „ovaj učenik ima poseban rok".
    """
    d_od = model.datum((dodjela or {}).get("rok_od"))
    d_do = model.datum((dodjela or {}).get("rok_do"))
    def_od = model.datum((definicija or {}).get("rok_od"))
    def_do = model.datum((definicija or {}).get("rok_do"))
    dodijeljeno = model.datum((dodjela or {}).get("dodijeljeno")) or model.datum(danas) or model.sada().date()

    od = d_od or def_od or dodijeljeno
    do = d_do or def_do
    produzen = bool(d_od or d_do)
    if do is None:
        do = od
    # Ključno (odluka 2): ako je učenik dodan NAKON isteka roka, prozor mu počinje danom dodjele.
    if dodijeljeno > do:
        od = dodijeljeno
        do = dodijeljeno
        produzen = True
    return {"od": od, "do": do, "produzen": produzen,
            "od_iso": od.strftime("%Y-%m-%d"), "do_iso": do.strftime("%Y-%m-%d")}


def stanje_roka(dodjela: dict, definicija: dict, danas=None) -> str:
    """`nije_poceo` · `otvoren` · `zatvoren` — za popis testova i za blokadu rješavanja."""
    danas = model.datum(danas) or model.sada().date()
    r = rok_dodjele(dodjela, definicija, danas)
    if danas < r["od"]:
        return "nije_poceo"
    if danas > r["do"]:
        return "zatvoren"
    return "otvoren"


def rokovi_do(dodjela: dict, definicija: dict) -> tuple:
    r = rok_dodjele(dodjela, definicija)
    return r["od"], r["do"]


def datumi_za_dodjelu(dodjela: dict, definicija: dict) -> dict:
    """Pomoćno: sve što UI treba o roku na jednom mjestu."""
    r = rok_dodjele(dodjela, definicija)
    trajanje = model.cijeli((definicija or {}).get("trajanje_min"), 45)
    return {**r, "trajanje_min": trajanje,
            "duljina": model.minuta_tekst(trajanje),
            "zadnji_dan": r["do"] + timedelta(days=0)}

# ------------------------------------------------------------------ ciljna publika (iz app.py)

def _normal_ucenik(uid: str, ime: str = "") -> dict:
    return {"ucenik_id": model.tekst(uid).upper(), "ime_djeteta": model.tekst(ime)}


def ucenici_programa(grupe_: list[dict], program: str) -> list[dict]:
    """Svi učenici grupa čiji je `program` jednak traženom (matura / instrukcije / upisi)."""
    cilj_program = model.tekst(program).lower()
    izlaz, videno = [], set()
    for g in grupe_ or []:
        if model.tekst(g.get("program")).lower() != cilj_program:
            continue
        for u in (g.get("ucenici") or []):
            uid = model.tekst(u.get("ucenik_id")).upper()
            if not uid or uid in videno:
                continue
            videno.add(uid)
            izlaz.append(_normal_ucenik(uid, u.get("ime_djeteta")))
    return izlaz


def sastavi_cilj(publika: str, *, grupe_odabrane=None, ucenici_odabrani=None,
                 rucne_sifre: str = "", grupe_sve=None, program: str = "") -> list[dict]:
    """Složi popis učenika za dodjelu iz odabrane publike.

    `publika`: `grupa` | `ucenici` | `svi` | `nacrt` (vraća prazno — nacrt se ne objavljuje).
    Duplikati se uklanjaju (učenik može biti u dvije kante ili i u popisu i u šiframa).
    """
    publika = model.tekst(publika).lower()
    izlaz: list[dict] = []
    videno: set[str] = set()

    def _dodaj(uid, ime=""):
        uid = model.tekst(uid).upper()
        if not uid or uid in videno:
            return
        videno.add(uid)
        izlaz.append(_normal_ucenik(uid, ime))

    if publika == "grupa":
        for g in (grupe_odabrane or []):
            for u in (g.get("ucenici") or []):
                _dodaj(u.get("ucenik_id"), u.get("ime_djeteta"))

    elif publika == "ucenici":
        for u in (ucenici_odabrani or []):
            if isinstance(u, dict):
                _dodaj(u.get("ucenik_id"), u.get("ime_djeteta") or u.get("ime"))
            else:
                _dodaj(u)
        for sifra in [x.strip() for x in model.tekst(rucne_sifre).split(",") if x.strip()]:
            _dodaj(sifra)

    elif publika == "svi":
        for u in ucenici_programa(grupe_sve or [], program):
            _dodaj(u.get("ucenik_id"), u.get("ime_djeteta"))

    return izlaz

# ------------------------------------------------------------------ migracija (01.11.2026.)

def premjesti_iz_crm_taba(sheet) -> dict:
    """Premjesti v2 retke iz CRM taba `Dodjele` u `Dodjele_ispita` (bez brisanja!).

    Vraća {"nadeno", "premjesteno", "preskoceno", "greska"}.
    Prepoznaje v2 retke po: `Dodjela_id` počinje s `D2` **ili** postoji `definicija_id`.
    CRM retci (`DJ-…` s profesorom/predmetom) **ostaju netaknuti**.
    """
    izlaz = {"nadeno": 0, "premjesteno": 0, "preskoceno": 0, "greska": ""}
    try:
        redci = tablice.ucitaj(sheet, tablice.TAB_DODJELE_CRM)
    except Exception as e:                              # noqa: BLE001
        izlaz["greska"] = str(e)
        return izlaz

    nasa = []
    for r in redci:
        did = model.tekst(r.get("dodjela_id"))
        if did.upper().startswith("D2") or model.tekst(r.get("definicija_id")):
            nasa.append(r)
    izlaz["nadeno"] = len(nasa)
    if not nasa:
        return izlaz

    # već premješteno?
    try:
        postojece = {model.tekst(x.get("dodjela_id"))
                     for x in tablice.ucitaj(sheet, tablice.TAB_DODJELE)}
    except Exception:                                   # noqa: BLE001
        postojece = set()

    novi = [r for r in nasa if model.tekst(r.get("dodjela_id")) not in postojece]
    izlaz["preskoceno"] = len(nasa) - len(novi)
    if novi:
        zaglavlje = tablice.ZAGLAVLJA[tablice.TAB_DODJELE]
        tablice.dodaj(sheet, tablice.TAB_DODJELE,
                      [{k: model.tekst(r.get(k)) for k in zaglavlje} for r in novi])
        izlaz["premjesteno"] = len(novi)
    return izlaz

# ---------------------------------------------------------------- čišćenje (zadatak 06)
def obrisi_dodjelu(sheet, dodjela_id: str, *, sila: bool = False) -> dict:
    """Obriši jednu dodjelu. Bez `sila` odbija ako za nju postoji pokušaj."""
    did = model.tekst(dodjela_id)
    izlaz = {"obrisano": False, "razlog": ""}
    if not did:
        izlaz["razlog"] = "Nedostaje dodjela_id."
        return izlaz

    pokusaji = [p for p in tablice.ucitaj(sheet, tablice.TAB_POKUSAJI)
                if model.tekst(p.get("dodjela_id")) == did]
    if pokusaji and not sila:
        izlaz["razlog"] = (f"Dodjela {did} ima {len(pokusaji)} pokušaj(a) — brisanje bi "
                           "izgubilo rezultat. Obriši pokušaje ili potvrdi silu.")
        return izlaz

    try:
        ok = tablice.obrisi(sheet, tablice.TAB_DODJELE, "dodjela_id", did)
    except Exception as e:                              # noqa: BLE001
        izlaz["razlog"] = f"Brisanje nije uspjelo: {e}"
        return izlaz
    izlaz["obrisano"] = bool(ok)
    if not ok:
        izlaz["razlog"] = f"Dodjela {did} nije nađena."
    return izlaz


def pocisti_neispravne(sheet, poznati_ucenici) -> dict:
    """Obriši dodjele čija šifra ne postoji u popisu učenika (prazno / prekratko / nepoznato).

    `poznati_ucenici` = skup/map šifri koje stvarno postoje (CRM `Učenici`).
    Vraća {"obrisano": n, "popis": [{dodjela_id, ucenik_id, definicija_id}], "preskoceno": n}.
    """
    poznati = {model.tekst(u).upper() for u in (poznati_ucenici or []) if model.tekst(u)}
    izlaz = {"obrisano": 0, "popis": [], "preskoceno": 0}
    if not poznati:
        return izlaz

    for d in tablice.ucitaj(sheet, tablice.TAB_DODJELE):
        uid = model.tekst(d.get("ucenik_id")).upper()
        if uid and uid in poznati:
            continue
        did = model.tekst(d.get("dodjela_id"))
        rez = obrisi_dodjelu(sheet, did)
        if rez["obrisano"]:
            izlaz["obrisano"] += 1
            izlaz["popis"].append({"dodjela_id": did, "ucenik_id": uid,
                                   "definicija_id": model.tekst(d.get("definicija_id"))})
        else:
            izlaz["preskoceno"] += 1
    return izlaz
