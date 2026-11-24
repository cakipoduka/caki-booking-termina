"""
CAKI testovi v2 — `definicije.py`
TEST KAO ZAPIS (ono što danas ne postoji).

Danas je „test" samo N redaka po učenicima s istom oznakom `serija` — zato se učenik ne može dodati
nakon objave i zato se ne zna što je točno bio test. Ovdje test postaje **jedan zapis** koji nosi
zadatke, pravila i način na koji se rezultat prikazuje.

Sve u ovom modulu su čiste funkcije (bez Streamlita i bez Googlea) — zato se mogu testirati.
"""
from __future__ import annotations

import random

import model
import tablice

# ------------------------------------------------------------------ riječnik

STANJA = ("nacrt", "objavljen", "zatvoren", "arhiviran")
VRSTE = ("vjezba", "ocjena")
VRSTA_NAZIV = {"vjezba": "Vježba", "ocjena": "Ocjena"}

STUPNJEVI = ("nikad", "pri_predaji", "uvijek")
STUPANJ_NAZIV = {
    "nikad": "Nikad",
    "pri_predaji": "Poslije",
    "uvijek": "Uvijek",
}

# 6 resursa koje učenik može vidjeti (Cakijeva odluka: Student View PO TESTU).
# `pri_predaji` za rješenja i video znači „nakon isteka roka" — do tada se ne smiju vidjeti jer bi
# učenik koji prvi preda podijelio odgovore ostalima (odluka 21.10.2026., zadržana).
RESURSI = {
    "bodovi": {"naziv": "Bodovanje po pitanju", "poslije_roka": False},
    "rjesenja": {"naziv": "Točna rješenja i objašnjenja", "poslije_roka": True},
    "video": {"naziv": "🎬 Video uz rješenje", "poslije_roka": True},
    "komentari": {"naziv": "Komentari profesora", "poslije_roka": False},
    "rezultat": {"naziv": "Ukupni rezultat, rang i prosjek", "poslije_roka": False},
    "pdf": {"naziv": "PDF izvoz rezultata", "poslije_roka": False},
}


def student_view_zadano() -> dict:
    """Zadano za novi test: bodove i rezultat vidi poslije predaje, rješenja i video nakon roka."""
    return {"bodovi": "pri_predaji", "rjesenja": "pri_predaji", "video": "pri_predaji",
            "komentari": "pri_predaji", "rezultat": "pri_predaji", "pdf": "uvijek"}


def _view_iz_jsona(v) -> dict:
    """Student View iz JSON-a, s dopunom zadanih vrijednosti (stariji zapisi)."""
    zadano = student_view_zadano()
    if isinstance(v, dict):
        ucitano = v
    else:
        tekst = model.tekst(v)
        ucitano = {}
        if tekst:
            try:
                import json
                objekt = json.loads(tekst)
                if isinstance(objekt, dict):
                    ucitano = objekt
            except Exception:                       # noqa: BLE001 — pokvaren JSON = zadano
                ucitano = {}
    izlaz = dict(zadano)
    for k in RESURSI:
        if model.tekst(ucitano.get(k)) in STUPNJEVI:
            izlaz[k] = model.tekst(ucitano.get(k))
    return izlaz


# ------------------------------------------------------------------ Student View

def smije_vidjeti(student_view, resurs: str, *, predano: bool = False,
                  rok_prosao: bool = False) -> bool:
    """Smije li učenik vidjeti `resurs` sada?

    - `nikad` → ne
    - `uvijek` → da
    - `pri_predaji` → za rješenja i video: **tek kad rok prođe**; za ostalo: kad preda
    """
    if resurs not in RESURSI:
        return False
    stupanj = _view_iz_jsona(student_view).get(resurs, "nikad")
    if stupanj == "nikad":
        return False
    if stupanj == "uvijek":
        return True
    if RESURSI[resurs]["poslije_roka"]:
        return bool(rok_prosao)
    return bool(predano)


def sto_vidi(student_view) -> list[dict]:
    """Za prikaz u administraciji: koji resurs, koja razina, što to znači."""
    izlaz = []
    for kljuc, opis in RESURSI.items():
        stupanj = _view_iz_jsona(student_view).get(kljuc, "nikad")
        izlaz.append({"kljuc": kljuc, "naziv": opis["naziv"], "stupanj": stupanj,
                      "znaci": ("ne vidi" if stupanj == "nikad"
                                else ("poslije roka" if (stupanj == "pri_predaji" and opis["poslije_roka"])
                                      else ("poslije predaje" if stupanj == "pri_predaji" else "uvijek")))})
    return izlaz


# ------------------------------------------------------------------ zadaci

def drugi_kljuc(zadatak: dict) -> str:
    return model.tekst((zadatak or {}).get("tip"))


def zadaci(definicija) -> list[dict]:
    return [z for z in model.kao_json((definicija or {}).get("zadaci_json")) if isinstance(z, dict)]


def bodovi_ukupno(zadaci_: list[dict]) -> float:
    return round(sum(model.broj((z or {}).get("bodovi"), 1) for z in zadaci_ or []), 2)


def _slovo(index: int) -> str:
    return chr(65 + index) if 0 <= index < 26 else ""


def _indeks_slova(slovo: str) -> int:
    s = model.tekst(slovo).upper()[:1]
    return ord(s) - 65 if "A" <= s <= "Z" else -1


def izmijesaj_odgovore(zadaci_: list[dict], seed) -> list[dict]:
    """Miješa SAMO ponuđene odgovore (redoslijed zadataka ostaje kakav je).

    Kod miješanja se **prepisuje točan odgovor u novo slovo** — inače bi ocjenjivanje bilo pogrešno
    (učenik odabere „C", a to je sada drugi tekst).
    """
    popis = [dict(z) for z in zadaci_ or []]
    lokalni = random.Random(f"{seed}|odgovori" if seed not in (None, "") else "caki")
    for z in popis:
        opcije = [model.tekst(o) for o in (z.get("opcije") or [])]
        if len(opcije) < 2:
            continue
        indeks_tocnog = _indeks_slova(model.tekst(z.get("odgovor")))
        if indeks_tocnog < 0 or indeks_tocnog >= len(opcije):
            continue                        # ključ nije slovo — ne diraj odgovore
        redoslijed = list(range(len(opcije)))
        lokalni.shuffle(redoslijed)
        z["opcije"] = [opcije[i] for i in redoslijed]
        z["odgovor"] = _slovo(redoslijed.index(indeks_tocnog))
    return popis


def izmijesaj(zadaci_: list[dict], seed, mijesaj_odgovore: bool = True) -> list[dict]:
    """A/B miješanje (Cakijeva odluka): ISTI sadržaj, drugi redoslijed zadataka i odgovora.

    Deterministički — isti `seed` uvijek daje isti test (važno za obranu od prigovora i za
    ponovni prikaz). Kod miješanja odgovora **prepisuje se točan odgovor** u novo slovo, inače bi
    ocijenjivanje bilo pogrešno.
    """
    popis = [dict(z) for z in zadaci_ or []]
    rnd = random.Random(str(seed) if seed not in (None, "") else "caki")
    rnd.shuffle(popis)
    if not mijesaj_odgovore:
        return popis
    return izmijesaj_odgovore(popis, seed)


def izbor_po_pravilima(banka: list[dict], pravila: list[dict], seed="") -> tuple[list[dict], list[str]]:
    """Slaganje testa po kvotama (npr. 4 iz algebre, 2 laka iz geometrije).

    `pravila` = [{"cjelina": "…", "tezina": "…", "broj": 4}] — prazno polje = ne filtrira.
    Vraća (odabrani, upozorenja). **Nikad ne vraća više nego što pravilo traži**, a ako nema
    dovoljno zadataka — kaže koliko fali (umjesto da tiho složi kraći test).
    """
    rnd = random.Random(str(seed) if seed not in (None, "") else "caki")
    odabrani: list[dict] = []
    upozorenja: list[str] = []
    iskoristeni: set[str] = set()

    for i, p in enumerate(pravila or [], start=1):
        cjelina = model.tekst((p or {}).get("cjelina"))
        tezina = model.tekst((p or {}).get("tezina"))
        tip = model.tekst((p or {}).get("tip"))
        trazi = model.cijeli((p or {}).get("broj"), 0)
        if trazi <= 0:
            continue
        kandidati = [
            z for z in banka or []
            if model.tekst(z.get("id")) not in iskoristeni
            and (not cjelina or model.tekst(z.get("cjelina")) == cjelina)
            and (not tezina or model.tekst(z.get("tezina")) == tezina)
            and (not tip or model.tekst(z.get("tip")) == tip)
        ]
        rnd.shuffle(kandidati)
        uzeto = kandidati[:trazi]
        for z in uzeto:
            iskoristeni.add(model.tekst(z.get("id")))
        odabrani += uzeto
        if len(uzeto) < trazi:
            opis = " · ".join(x for x in (cjelina, tezina, tip) if x) or f"pravilo {i}"
            upozorenja.append("„%s”: traženo %d, nađeno %d" % (opis, trazi, len(uzeto)))
    return odabrani, upozorenja


# ------------------------------------------------------------------ zapis testa

def nova_definicija(*, definicija_id: str, naziv: str, predmet: str, zadaci_: list[dict],
                    trajanje_min: int = 45, rok_od: str = "", rok_do: str = "",
                    vrsta: str = "ocjena", razina: str = "", autor: str = "",
                    ustanova_id: str = "caki", napomena: str = "",
                    student_view=None, varijanta_pravilo=None,
                    status: str = "nacrt",
    ai_pomoc: str = "da") -> dict:
    """Sastavi zapis testa (dict spreman za `tablice.dodaj`)."""
    if status not in STANJA:
        raise ValueError(f"Nepoznato stanje: {status}")
    if vrsta not in VRSTE:
        raise ValueError(f"Nepoznata vrsta: {vrsta}")
    return {
        "definicija_id": model.tekst(definicija_id),
        "ustanova_id": model.tekst(ustanova_id) or "caki",
        "naziv": model.tekst(naziv),
        "predmet": model.tekst(predmet),
        "razina": model.tekst(razina),
        "vrsta": vrsta,
        "zadaci_json": model.u_json(zadaci_ or []),
        "broj_zadataka": len(zadaci_ or []),
        "bodovi_ukupno": bodovi_ukupno(zadaci_),
        "trajanje_min": model.cijeli(trajanje_min, 45),
        "rok_od": model.iso_datum(rok_od),
        "rok_do": model.iso_datum(rok_do),
        "status": status,
        "student_view_json": model.u_json(_view_iz_jsona(student_view)),
        "varijanta_pravilo": model.u_json(varijanta_pravilo or {"mijesaj_zadatke": True,
                                                                "mijesaj_odgovore": True}),
        "pdf_verzija": "",
        "autor": model.tekst(autor),
        "kreirano": model.sada_iso(),
        "napomena": model.tekst(napomena),
        "ai_pomoc": "da" if model.tekst(ai_pomoc).lower() in ("da", "1", "true") else "ne",
    }


def validiraj(d: dict) -> list[str]:
    """Što sprječava objavu. Vraća popis razloga (prazno = može se objaviti)."""
    greske = []
    if not model.tekst((d or {}).get("naziv")):
        greske.append("Test nema naziv.")
    zadaci_ = zadaci(d)
    if not zadaci_:
        greske.append("Test nema nijedan zadatak.")
    if model.cijeli((d or {}).get("trajanje_min"), 0) <= 0:
        greske.append("Vrijeme rješavanja mora biti veće od 0.")
    if bodovi_ukupno(zadaci_) <= 0:
        greske.append("Zadaci ne nose nijedan bod.")
    for i, z in enumerate(zadaci_, start=1):
        if not model.tekst((z or {}).get("id")):
            greske.append(f"Zadatak {i} nema ID.")
        if not model.tekst((z or {}).get("tekst")):
            greske.append(f"Zadatak {i} nema tekst.")
        if model.tekst((z or {}).get("tip")) == "visestruki_izbor" and len(z.get("opcije") or []) < 2:
            greske.append(f"Zadatak {i} je višestruki izbor, a nema barem dva odgovora.")
    od, do = model.datum((d or {}).get("rok_od")), model.datum((d or {}).get("rok_do"))
    if od and do and do < od:
        greske.append("Rok „do” je prije roka „od”.")
    return greske


def promijeni_status(sheet, definicija_id: str, novo: str, *, korisnik: str = "") -> bool:
    if novo not in STANJA:
        raise ValueError(f"Nepoznato stanje: {novo}")
    ok = tablice.azuriraj(sheet, tablice.TAB_DEFINICIJE, "definicija_id", definicija_id,
                          {"status": novo})
    if ok:
        tablice.zapisi_radnju(sheet, korisnik, f"status:{novo}", definicija_id)
    return ok


def ucitaj_sve(sheet) -> list[dict]:
    return tablice.ucitaj(sheet, tablice.TAB_DEFINICIJE)


def po_id(sheet, definicija_id: str) -> dict | None:
    for d in ucitaj_sve(sheet):
        if model.tekst(d.get("definicija_id")) == model.tekst(definicija_id):
            return d
    return None


def je_objavljen(d: dict | None) -> bool:
    return model.tekst((d or {}).get("status")) in ("objavljen", "zatvoren")


def nacrti(sheet) -> list[dict]:
    return [d for d in ucitaj_sve(sheet) if model.tekst(d.get("status")) == "nacrt"]


# ------------------------------------------------------------------ uređivanje (Cakijevo pitanje 26.10.2026.)

def _danas(vrijednost=None):
    """Današnji datum kao `date` (ili zadani string pretvoren u datum)."""
    from datetime import date, datetime

    if vrijednost is None:
        return date.today()
    if isinstance(vrijednost, date):
        return vrijednost
    tekst = model.tekst(vrijednost)
    for obrazac in ("%Y-%m-%d", "%d.%m.%Y.", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(tekst, obrazac).date()
        except ValueError:
            continue
    return date.today()


def rok_dijela(definicija: dict):
    """(rok_od, rok_do) kao `date` ili (None, None) — iz definicije testa i dodjele."""
    d = definicija or {}
    od = _danas(d.get("rok_od")) if model.tekst(d.get("rok_od")) else None
    do = _danas(d.get("rok_do")) if model.tekst(d.get("rok_do")) else None
    return od, do


def pokusaji_testa(sheet, definicija_id: str) -> list[dict]:
    """Svi pokušaji testa — preko `Dodjele` (ključ je `dodjela_id`, ne `definicija_id`).

    Ovo je popravak MASTER §12.4.1: prije se tražilo po `definicija_id` i rezultat se ignorirao.
    """
    did = model.tekst(definicija_id)
    if not did or sheet is None:
        return []
    try:
        dodjele_testa = [model.tekst(r.get("dodjela_id"))
                         for r in tablice.ucitaj(sheet, tablice.TAB_DODJELE)
                         if model.tekst(r.get("definicija_id")) == did]
    except Exception:                                  # noqa: BLE001
        return []
    if not dodjele_testa:
        return []
    try:
        return [r for r in tablice.ucitaj(sheet, tablice.TAB_POKUSAJI)
                if model.tekst(r.get("dodjela_id")) in dodjele_testa]
    except Exception:                                  # noqa: BLE001
        return []


def smije_urediti(sheet, definicija: dict, *, danas=None) -> tuple[bool, str]:
    """Smije li se test mijenjati sada? Vraća (smije, razlog).

    Redoslijed (popravljeno 30.10.2026., MASTER §12.4.1):
      1. **arhiviran** → ne;
      2. **postoji ijedan pokušaj** (u tijeku ili predan) → **ne** — bez obzira na status, jer bi
         učenici dobili drugi test od onoga što su počeli (dokaz se ne može rekonstruirati);
      3. **nacrt / zatvoren bez pokušaja** → da;
      4. **objavljen, rok nije počeo** → da; **rok je počeo, a nitko nije otvorio test**
         → **da** (20.11.2026., Caki: prije je ovdje bilo `ne`, pa se test nije mogao
         popraviti ni kad ga nitko nije ni vidio).
    """
    d = definicija or {}
    did = model.tekst(d.get("definicija_id"))
    status = model.tekst(d.get("status"))

    if status == "arhiviran":
        return False, "Test je arhiviran — ne mijenja se."

    pokusaji = pokusaji_testa(sheet, did)
    if pokusaji:
        predanih = sum(1 for p in pokusaji
                       if model.je_predan(p))
        detalj = (f"{predanih} predanih" if predanih else
                  f"{len(pokusaji)} u tijeku")
        return False, (f"Test ima **{len(pokusaji)} pokušaja** ({detalj}) — mijenjanje bi "
                       "promijenilo test onima koji su ga već počeli rješavati.")

    if status in ("nacrt", "zatvoren"):
        return True, ("Nacrt — mijenja se slobodno." if status == "nacrt"
                      else "Nedostupan je učenicima i nitko ga nije počeo — mijenja se slobodno.")

    od, _do = rok_dijela(d)
    danas = _danas(danas)
    if od and danas and danas >= od:
        # 20.11.2026. (Caki): prije je ovdje stajao `return False` i test se nije mogao
        # popraviti ni kad ga NITKO nije otvorio. Dokaz čuva `Pokusaji.zadaci_json` (snimka
        # pitanja koja je učenik stvarno vidio), a bez ijednog pokušaja nema što pokvariti.
        return True, (f"⚠️ Rok je počeo {model.datum_hr(od)}, ali **nitko nije otvorio test** — "
                      "smije se mijenjati. Tko ga počne poslije izmjene, dobiva novu "
                      "verziju.")
    return True, ("Rok još nije počeo — smije se mijenjati."
                  if od else "Bez roka i bez pokušaja — smije se mijenjati.")



# 24.11.2026.: + `formule_json` (📐 formule uz test — okvir testa, kao rok; pokušaji ga ne zaključavaju)
META_POLJA = ("naziv", "trajanje_min", "rok_od", "rok_do", "ai_pomoc", "napomena", "status",
              "formule_json")


def smije_urediti_metapodatke(sheet, definicija: dict, *, danas=None) -> tuple[bool, str]:
    """Smiju li se mijenjati OKVIRNI podaci testa (`META_POLJA`): naziv, trajanje, rok, AI?

    Razlika prema `smije_urediti` (ona čuva ZADATKE): ovdje se zadaci ne diraju, pa pokušaji
    ne blokiraju. Produljiti rok testu koji učenici pišu je normalan posao, a ne kvarenje
    dokaza (20.11.2026., Caki: prije je obrazac bio zaključan skroz).

      1. **arhiviran** → ne (prvo "Vrati iz arhive");
      2. sve ostalo → da; ako ima pokušaja, poruka je upozorenje, ne zabrana.
    """
    d = definicija or {}
    if model.tekst(d.get("status")) == "arhiviran":
        return False, "Test je u arhivi — vrati ga iz arhive pa ga onda mijenjaj."
    pokusaji = pokusaji_testa(sheet, model.tekst(d.get("definicija_id")))
    if pokusaji:
        return True, (f"⚠️ Test ima **{len(pokusaji)} pokušaja** — smiju se mijenjati naziv, "
                      "rok, trajanje i AI pomoć, ali **ne zadaci**.")
    return True, "Nema pokušaja — okvirni podaci se mijenjaju slobodno."


def arhiviraj(sheet, definicija_id: str, *, korisnik: str = "") -> tuple[bool, str]:
    """🗄️ U arhivu (biblioteka predložaka): test se ne zadaje i ne mijenja, ali ostaje cijel.

    Arhiva NIJE brisanje — dodjele, pokušaji i ocjene ostaju. Iz arhive se test kopira u
    🧱 Složi test i uredi kao novi, ili se vrati natrag s `vrati_iz_arhive`.
    """
    did = model.tekst(definicija_id)
    d = po_id(sheet, did)
    if not d:
        return False, "Test ne postoji."
    if model.tekst(d.get("status")) == "arhiviran":
        return False, "Test je već u arhivi."
    if not promijeni_status(sheet, did, "arhiviran", korisnik=korisnik or "caki"):
        return False, "Status nije upisan (redak nije nađen)."
    return True, f"Test `{did}` je u arhivi — ostaje kao predložak, učenicima nije dostupan."


def vrati_iz_arhive(sheet, definicija_id: str, *, korisnik: str = "",
                    novi_status: str = "zatvoren") -> tuple[bool, str]:
    """↩️ Iz arhive natrag u rad. Zadano `zatvoren`: Caki ga vidi i smije mijenjati, učenik ne.

    Namjerno NE ide odmah u `objavljen` — objava znači dodjele i ide kroz 👥 Objavi.
    Arhiviranje je time povratno: arhiva iz koje se ne može natrag bila bi zamka.
    """
    did = model.tekst(definicija_id)
    d = po_id(sheet, did)
    if not d:
        return False, "Test ne postoji."
    if model.tekst(d.get("status")) != "arhiviran":
        return False, "Test nije u arhivi."
    if novi_status not in ("nacrt", "zatvoren"):
        return False, "Iz arhive se vraća kao `nacrt` ili `zatvoren`."
    if not promijeni_status(sheet, did, novi_status, korisnik=korisnik or "caki"):
        return False, "Status nije upisan (redak nije nađen)."
    return True, (f"Test `{did}` je vraćen iz arhive (status `{novi_status}`) — sad se smije "
                  "mijenjati; za učenike ga objavi u 👥 Objavi.")


def _prebroji(sheet, tab: str, uvjet) -> int:
    """Koliko redaka u tabu zadovoljava uvjet. Nedostupan tab = 0, ne greška."""
    try:
        return sum(1 for r in tablice.ucitaj(sheet, tab) if uvjet(r))
    except Exception:                                   # noqa: BLE001
        return 0


def opseg_brisanja(sheet, definicija_id: str) -> dict:
    """Koliko bi redaka brisanje odnijelo — brojevi koje sučelje pokazuje PRIJE klika.

    Read-only; ništa ne mijenja. Postoji zato da dijalog brisanja može napisati točan opseg i
    zaključati gumb s objašnjenjem, umjesto da korisnik klikne i tek onda dobije odbijenicu
    (UX pravilo 4: „ako je gumb zaključan — napiši zašto").

    Ključ `smije_bez_rezultata` kaže smije li se test obrisati uz odgovor „rezultati: NE".
    """
    did = model.tekst(definicija_id)
    prazno = {"definicija_id": did, "postoji": False, "naziv": "", "status": "",
              "pokusaji": 0, "ocjene": 0, "dodjele": 0, "izmjene": 0, "zalbe": 0,
              "statistika": 0, "rezultata_ukupno": 0, "ima_pokusaje": False,
              "smije_bez_rezultata": False, "razlog": "Test ne postoji."}
    if not did:
        return dict(prazno, razlog="Nedostaje ID testa.")
    d = po_id(sheet, did)
    if not d:
        return prazno

    pokusaji = pokusaji_testa(sheet, did)
    pids = {model.tekst(p.get("pokusaj_id")) for p in pokusaji
            if model.tekst(p.get("pokusaj_id"))}

    opseg = {
        "definicija_id": did,
        "postoji": True,
        "naziv": model.tekst(d.get("naziv")),
        "status": model.tekst(d.get("status")),
        "pokusaji": len(pokusaji),
        "dodjele": _prebroji(sheet, tablice.TAB_DODJELE,
                             lambda r: model.tekst(r.get("definicija_id")) == did),
        "ocjene": _prebroji(sheet, tablice.TAB_OCJENE,
                            lambda r: model.tekst(r.get("pokusaj_id")) in pids) if pids else 0,
        "izmjene": _prebroji(sheet, tablice.TAB_IZMJENE_OCJENA,
                             lambda r: model.tekst(r.get("pokusaj_id")) in pids) if pids else 0,
        "zalbe": _prebroji(sheet, tablice.TAB_ZALBE,
                           lambda r: model.tekst(r.get("pokusaj_id")) in pids) if pids else 0,
        "statistika": _prebroji(sheet, tablice.TAB_STATISTIKA,
                                lambda r: model.tekst(r.get("definicija_id")) == did),
    }
    opseg["ima_pokusaje"] = opseg["pokusaji"] > 0
    opseg["smije_bez_rezultata"] = not opseg["ima_pokusaje"]
    opseg["rezultata_ukupno"] = (opseg["pokusaji"] + opseg["ocjene"] + opseg["izmjene"]
                                 + opseg["zalbe"] + opseg["statistika"])
    opseg["razlog"] = "" if opseg["smije_bez_rezultata"] else (
        f"Test ima {opseg['pokusaji']} pokušaja — uz „rezultati: NE” se ne briše, jer je "
        "rezultat dokaz. Odaberi „rezultati: DA” ili ga arhiviraj.")
    return opseg


def obrisi(sheet, definicija_id: str, *, korisnik: str = "",
           sila: bool = False) -> tuple[bool, str]:
    """Obriši test. Vraća (uspjeh, razlog).

    Pravila:
      · **ima pokušaja** i `sila=False` → NE briše se (dokaz; predlaži arhiviranje),
      · **ima pokušaja** i `sila=True` → briše se test **i svi njegovi rezultati** (nepovratno),
      · ima dodjela bez pokušaja → brišu se dodjele, zatim test,
      · svaka radnja se zapisuje u `Dnevnik_radnji`.
    """
    did = model.tekst(definicija_id)
    if not did:
        return False, "Nedostaje ID testa."
    d = po_id(sheet, did)
    if not d:
        return False, "Test ne postoji."

    pokusaji = pokusaji_testa(sheet, did)
    if pokusaji and sila:
        return _obrisi_s_rezultatima(sheet, did, pokusaji, korisnik=korisnik)
    if pokusaji:
        return False, (f"Test ima **{len(pokusaji)} pokušaja** — ne briše se (to je dokaz). "
                       "Predlažem **arhiviranje** (status `arhiviran`) ili brisanje s rezultatima "
                       "(`sila=True`, nepovratno).")

    # 20.11.2026.: jedno čitanje taba umjesto jednog po dodjeli (prije: `obrisi()` u petlji).
    try:
        obrisane_dodjele = tablice.obrisi_gdje(sheet, tablice.TAB_DODJELE,
                                               {"definicija_id": did})
    except Exception as e:                              # noqa: BLE001
        return False, f"Dodjele nije moguće obrisati: {e}"

    if not tablice.obrisi(sheet, tablice.TAB_DEFINICIJE, "definicija_id", did):
        return False, "Test nije obrisan (redak nije nađen)."

    try:
        tablice.zapisi_radnju(sheet, korisnik or "caki", "obrisan_test", did,
                              f"{model.tekst(d.get('naziv'))}; dodjela obrisano: {obrisane_dodjele}")
    except Exception:                                   # noqa: BLE001
        pass
    return True, ("Test obrisan." + (f" Uz njega i {obrisane_dodjele} dodjela."
                                      if obrisane_dodjele else ""))


def izmijeni(sheet, definicija: dict, promjene: dict, *, korisnik: str = "") -> tuple[bool, str]:
    """Izmijeni test kakav ga učenik vidi (kao v1 `testovi_admin` L2071–2121).

    Dopuštena polja: `naziv`, `trajanje_min`, `rok_od`, `rok_do`, `ai_pomoc`, `napomena`, `status`.
    **Ne mijenja** zadatke (`zadaci_json`) — to je drugi posao. Zato se blokira samo ako je
    test arhiviran (`smije_urediti_metapodatke`); pokušaji NE blokiraju okvirne podatke.
    """
    d = definicija or {}
    did = model.tekst(d.get("definicija_id"))
    if not did:
        return False, "Nedostaje ID testa."

    # 20.11.2026.: ova funkcija NIKAD ne dira `zadaci_json`, pa je dovoljna provjera okvirnih
    # podataka — test s pokušajima smije dobiti novi rok ili naziv.
    smije, razlog = smije_urediti_metapodatke(sheet, d)
    if not smije:
        return False, razlog

    dopusteno = META_POLJA
    polja = {k: v for k, v in (promjene or {}).items() if k in dopusteno}
    if not polja:
        return False, "Nema dopuštenih polja za izmjenu."

    if "naziv" in polja and not model.tekst(polja["naziv"]):
        return False, "Naziv ne smije biti prazan."
    if "trajanje_min" in polja:
        try:
            polja["trajanje_min"] = max(5, int(float(polja["trajanje_min"])))
        except (TypeError, ValueError):
            return False, "Trajanje mora biti broj minuta."
    if "ai_pomoc" in polja:
        polja["ai_pomoc"] = "da" if model.tekst(polja["ai_pomoc"]).lower() in (
            "da", "1", "true", "✅") else "ne"
    if "status" in polja and model.tekst(polja["status"]) not in (
            "nacrt", "objavljen", "zatvoren", "arhiviran"):
        return False, "Nepoznat status."

    try:
        ok = tablice.azuriraj(sheet, tablice.TAB_DEFINICIJE, "definicija_id", did, polja)
    except Exception as e:                              # noqa: BLE001
        return False, f"Izmjena nije upisana: {e}"
    if ok and korisnik:
        try:
            tablice.zapisi_radnju(sheet, korisnik, "izmjena_testa", did,
                                  ", ".join(sorted(polja)))
        except Exception:                               # noqa: BLE001
            pass
    return bool(ok), "Spremljeno." if ok else "Redak nije nađen."


def postavi_student_view(sheet, definicija: dict, izbor: dict,
                         *, korisnik: str = "") -> tuple[bool, str]:
    """Postavi što učenik vidi — po testu. Vraća (uspjeh, poruka).

    **Zašto zasebna funkcija, a ne `izmijeni()`:** `student_view_json` namjerno nije u
    `META_POLJA`. `izmijeni()` upisuje vrijednosti kakve dobije, a ovdje to ne valja — nepoznat
    resurs ili razina ne smiju doći do baze, jer bi ih `_view_iz_jsona()` tiho preskočio i
    učeniku bi se, bez ijedne greške, prikazalo nešto drugo nego što je profesor postavio.
    Zato se najprije provjeri svaki ključ i svaka razina, pa tek onda serijalizira.

    **Pokušaji NE blokiraju ovu izmjenu.** Otvoriti rješenja nakon isteka roka normalan je
    posao i ne dira ni jedan predani odgovor. Arhiviran test se ne mijenja — ista provjera kao
    za okvirne podatke (`smije_urediti_metapodatke`).
    """
    d = definicija or {}
    did = model.tekst(d.get("definicija_id"))
    if not did:
        return False, "Nedostaje ID testa."

    smije, razlog = smije_urediti_metapodatke(sheet, d)
    if not smije:
        return False, razlog

    trazeno = izbor or {}
    if not isinstance(trazeno, dict):
        return False, "Očekivan je rječnik resurs → razina."
    for kljuc, vrijednost in trazeno.items():
        if kljuc not in RESURSI:
            return False, (f"Nepoznat resurs `{model.tekst(kljuc)}`. "
                           f"Dopušteni su: {', '.join(RESURSI)}.")
        if model.tekst(vrijednost) not in STUPNJEVI:
            return False, (f"Nepoznata razina `{model.tekst(vrijednost)}` za `{kljuc}`. "
                           f"Dopuštene su: {', '.join(STUPNJEVI)}.")

    # Krene se od onoga što je već zapisano, pa se promijeni samo ono što je poslano —
    # tako djelomičan izbor ne obriše ostale resurse.
    novi = _view_iz_jsona(d.get("student_view_json"))
    for kljuc, vrijednost in trazeno.items():
        novi[kljuc] = model.tekst(vrijednost)

    if not tablice.azuriraj(sheet, tablice.TAB_DEFINICIJE, "definicija_id", did,
                            {"student_view_json": model.u_json(novi)}):
        return False, "Postavke nisu upisane (redak nije nađen)."

    try:
        tablice.zapisi_radnju(
            sheet, korisnik or "caki", "student_view", did,
            ", ".join(f"{k}={novi[k]}" for k in RESURSI))
    except Exception:                                   # noqa: BLE001
        pass
    return True, "Spremljeno — učenici od sada vide točno ovo."


def postavi_aktivan(sheet, definicija_id: str, aktivan: bool, *, korisnik: str = "") -> tuple[bool, str]:
    """v1 „Aktivan / Deaktiviraj": učenik ga vidi ili ne (rezultati ostaju)."""
    d = po_id(sheet, definicija_id)
    if not d:
        return False, "Test ne postoji."
    return izmijeni(sheet, d, {"status": "objavljen" if aktivan else "zatvoren"},
                    korisnik=korisnik)


def zatvori_odmah(sheet, definicija_id: str, *, korisnik: str = "") -> tuple[bool, str]:
    """v1 „Zatvori test odmah" (L2137): rok se postavlja na **jučer** → nitko novi ne piše, a
    predani odmah vide rješenja.

    23.11.2026.: postavlja i `status = zatvoren`. Sam datum nije bio dovoljan: učenik kojem je
    test dodijeljen danas (pravilo „dodan poslije roka → rok je dan dodjele") i dalje je imao
    otvoren rok, pa nije vidio rješenja. `dodjele.stanje_roka()` sada status poštuje.
    Arhivirani test ostaje arhiviran.
    """
    from datetime import date, timedelta

    d = po_id(sheet, definicija_id)
    if not d:
        return False, "Test ne postoji."
    jučer = (date.today() - timedelta(days=1)).isoformat()
    promjene = {"rok_do": jučer}
    if model.tekst(d.get("status")) != "arhiviran":
        promjene["status"] = "zatvoren"
    ok, razlog = izmijeni(sheet, d, promjene, korisnik=korisnik)
    if ok:
        try:
            tablice.zapisi_radnju(sheet, korisnik or "caki", "zatvori_odmah",
                                  model.tekst(definicija_id), f"rok_do={jučer}")
        except Exception:                               # noqa: BLE001
            pass
    return ok, "Test zatvoren — rješenja su otvorena." if ok else razlog


def kloniraj(sheet, definicija_id: str, *, autor: str = "") -> tuple[dict | None, str]:
    """v1 „Kloniraj" (L2154): novi test s ISTIM zadacima; izvorni i rezultati se ne diraju.

    Razlika prema v1 (namjerno): v1 klon odmah objavi, a v2 klon ostaje **nacrt** — u v2 objava
    znači dodjele, pa se klon objavljuje kroz 👥 Objavi.
    """
    d = po_id(sheet, definicija_id)
    if not d:
        return None, "Test ne postoji."
    postojeci = tablice.svi_idovi(sheet, tablice.TAB_DEFINICIJE, "definicija_id")
    novi_id = tablice.novi_id(postojeci, "T26-")
    novi = dict(d)
    novi.update({
        "definicija_id": novi_id,
        "naziv": (model.tekst(d.get("naziv")) + " (kopija)")[:120],
        "status": "nacrt",
        "autor": model.tekst(autor) or model.tekst(d.get("autor")),
        "kreirano": model.sada_iso(),
    })
    zaglavlje = tablice.ZAGLAVLJA[tablice.TAB_DEFINICIJE]
    try:
        tablice.dodaj(sheet, tablice.TAB_DEFINICIJE,
                      [{k: novi.get(k, "") for k in zaglavlje}])
    except Exception as e:                              # noqa: BLE001
        return None, f"Klon nije spremljen: {e}"
    try:
        tablice.zapisi_radnju(sheet, model.tekst(autor) or "caki", "kloniran_test",
                              novi_id, f"izvorni={model.tekst(definicija_id)}")
    except Exception:                                   # noqa: BLE001
        pass
    return novi, f"Novi test `{novi_id}` s istim zadacima (status: nacrt)."



def smije_ai(definicija: dict) -> bool:
    """Je li AI pomoć učeniku dopuštena za OVAJ test? (Cakijeva odluka pri objavi.)

    Prazno = ne — bolje da pomoć bude isključena nego da se uključi slučajno.
    """
    vrijednost = model.tekst((definicija or {}).get("ai_pomoc")).lower()
    return vrijednost in ("da", "1", "true", "tocno", "točno")


def _obrisi_s_rezultatima(sheet, definicija_id: str, pokusaji: list[dict], *,
                          korisnik: str = "") -> tuple[bool, str]:
    """Nepovratno: obriši test i SVE njegove rezultate. Vraća (uspjeh, poruka s brojevima).

    Red je od lišća prema korijenu, da nijedan redak ne ostane bez svog testa:
    ocjene/izmjene/žalbe po pokušaju → pokušaj → statistika → dodjele → test.

    Tri popravka 20.11.2026. (nađena pri provjeri, prije nego je sučelje postalo dostupno):

    1. **Statistika se prije nije brisala.** Uvjet je tražio stupac `statistika_id`, a tab
       `Statistika_zadataka` ga ne poznaje (ključ je `zadatak_id` + `definicija_id`), pa je izraz
       uvijek bio 0 i redci su ostajali kao siročići.
    2. **Pokušaji se brišu po `pokusaj_id`, ne po `definicija_id`.** `Pokusaji` ima oba stupca, ali
       `definicija_id` smije biti prazan — zato `pokusaji_testa()` i traži preko `dodjela_id`.
       Brisanje po `definicija_id` promašilo bi upravo te retke.
    3. **Dnevnik je dobivao prazan redak.** Upisivalo se ključevima `radnja_id`/`kada`/`tko`/
       `detalji`, a tab `Dnevnik_radnji` ima `kad`/`korisnik`/`radnja`/`sto`/`detalj`. Nijedan se
       nije poklopio, pa je najrazornija radnja u sustavu ostavljala prazan trag. Sada ide kroz
       `tablice.zapisi_radnju()`, koja piše ispravnim imenima stupaca.
    """
    did = model.tekst(definicija_id)
    pids = [model.tekst(p.get("pokusaj_id")) for p in (pokusaji or [])
            if model.tekst(p.get("pokusaj_id"))]
    brojevi = {"ocjene": 0, "izmjene": 0, "zalbe": 0, "pokusaji": 0,
               "statistika": 0, "dodjele": 0}

    def _brisi(tab: str, uvjeti: dict) -> int:
        try:
            return tablice.obrisi_gdje(sheet, tab, uvjeti)
        except Exception:                               # noqa: BLE001 — jedan tab ne ruši ostatak
            return 0

    for pid in pids:
        brojevi["ocjene"] += _brisi(tablice.TAB_OCJENE, {"pokusaj_id": pid})
        brojevi["izmjene"] += _brisi(tablice.TAB_IZMJENE_OCJENA, {"pokusaj_id": pid})
        brojevi["zalbe"] += _brisi(tablice.TAB_ZALBE, {"pokusaj_id": pid})
        brojevi["pokusaji"] += _brisi(tablice.TAB_POKUSAJI, {"pokusaj_id": pid})

    brojevi["statistika"] = _brisi(tablice.TAB_STATISTIKA, {"definicija_id": did})
    brojevi["dodjele"] = _brisi(tablice.TAB_DODJELE, {"definicija_id": did})

    try:
        tablice.obrisi(sheet, tablice.TAB_DEFINICIJE, "definicija_id", did)
    except Exception as e:                              # noqa: BLE001
        return False, f"Rezultati su obrisani, ali test nije: {e}"

    tablice.zapisi_radnju(
        sheet, korisnik or "caki", "obrisan_test_s_rezultatima", did,
        f"pokušaji {brojevi['pokusaji']}, ocjene {brojevi['ocjene']}, "
        f"dodjele {brojevi['dodjele']}, izmjene {brojevi['izmjene']}, "
        f"žalbe {brojevi['zalbe']}, statistika {brojevi['statistika']}")

    return True, (f"**Obrisano nepovratno:** test `{did}`, pokušaji **{brojevi['pokusaji']}**, "
                  f"ocjene **{brojevi['ocjene']}**, dodjele **{brojevi['dodjele']}**, "
                  f"izmjene {brojevi['izmjene']}, žalbe {brojevi['zalbe']}, "
                  f"statistika {brojevi['statistika']}.")


# ------------------------------------------------------------------ više testova odjednom

def _zbirno(uspjeli: list, odbijeni: list, glagol: str) -> str:
    """Jedna rečenica za sučelje: koliko je prošlo, koliko nije i zašto (UX pravilo 4)."""
    dijelovi = []
    if uspjeli:
        dijelovi.append(f"{glagol} **{len(uspjeli)}**: " + ", ".join(f"`{x}`" for x in uspjeli))
    if odbijeni:
        dijelovi.append(f"nije prošlo **{len(odbijeni)}**: "
                        + "; ".join(f"`{oznaka}` — {razlog}" for oznaka, razlog in odbijeni))
    return " · ".join(dijelovi) or "Nije odabran nijedan test."


def obrisi_vise(sheet, oznake, *, sila: bool = False, korisnik: str = "") -> dict:
    """Obriši više testova odjednom (za višestruki odabir u arhivi).

    Svaki test ide kroz `obrisi()`, pa vrijede ista pravila — test s pokušajima se bez
    `sila=True` ne briše. **Jedan odbijeni test ne zaustavlja ostale**: tko se smije obrisati,
    obriše se, a za ostale se vrati razlog. Zato se ne vraća (bool, str) nego rječnik.
    """
    obrisani: list = []
    odbijeni: list = []
    for oznaka_sirova in (oznake or ()):
        oznaka = model.tekst(oznaka_sirova)
        if not oznaka:
            continue
        try:
            ok, razlog = obrisi(sheet, oznaka, korisnik=korisnik, sila=sila)
        except Exception as e:                          # noqa: BLE001
            ok, razlog = False, f"greška: {e}"
        if ok:
            obrisani.append(oznaka)
        else:
            odbijeni.append((oznaka, razlog))
    return {"obrisani": obrisani, "odbijeni": odbijeni,
            "poruka": _zbirno(obrisani, odbijeni, "Obrisano")}


def vrati_vise_iz_arhive(sheet, oznake, *, korisnik: str = "",
                         novi_status: str = "zatvoren") -> dict:
    """Vrati više testova iz arhive odjednom. Isti oblik odgovora kao `obrisi_vise()`."""
    vraceni: list = []
    odbijeni: list = []
    for oznaka_sirova in (oznake or ()):
        oznaka = model.tekst(oznaka_sirova)
        if not oznaka:
            continue
        try:
            ok, razlog = vrati_iz_arhive(sheet, oznaka, korisnik=korisnik,
                                         novi_status=novi_status)
        except Exception as e:                          # noqa: BLE001
            ok, razlog = False, f"greška: {e}"
        if ok:
            vraceni.append(oznaka)
        else:
            odbijeni.append((oznaka, razlog))
    return {"vraceni": vraceni, "odbijeni": odbijeni,
            "poruka": _zbirno(vraceni, odbijeni, "Vraćeno iz arhive")}
