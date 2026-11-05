"""
CAKI testovi v2 — `provedba.py`
POKUŠAJ RJEŠAVANJA: početak → autosave → predaja.

Zašto pokušaj, a ne samo rezultat: bez pokušaja nema autosavea (Cakijev zahtjev: prekid ne smije
izgubiti odgovore), nema vremena po zadatku (za mjerenje) i nema ponovnog rješavanja.

Vrijeme se **uvijek** mjeri na poslužitelju (`pocetak` u tablici), nikad u pregledniku.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import definicije
import dodjele
import model
import ocjenjivanje
import tablice

STATUS_U_TIJEKU = "u_tijeku"
STATUS_PREDANO = "predano"
STATUS_PO_ISTEKU = "po_isteku"
STATUSI = (STATUS_U_TIJEKU, STATUS_PREDANO, STATUS_PO_ISTEKU)

GRACE_S = 60                    # tolerancija pri predaji odmah nakon roka


# ------------------------------------------------------------------ čitanje

def pokusaji_ucenika(sheet, dodjela_id: str) -> list[dict]:
    did = model.tekst(dodjela_id)
    return [p for p in tablice.ucitaj(sheet, tablice.TAB_POKUSAJI)
            if model.tekst(p.get("dodjela_id")) == did]


def pokusaj_po_id(sheet, pokusaj_id: str) -> dict | None:
    for p in tablice.ucitaj(sheet, tablice.TAB_POKUSAJI):
        if model.tekst(p.get("pokusaj_id")) == model.tekst(pokusaj_id):
            return p
    return None


def aktivni(sheet, dodjela_id: str) -> dict | None:
    """Pokušaj koji je u tijeku (za nastavak nakon F5/prekida)."""
    for p in pokusaji_ucenika(sheet, dodjela_id):
        if model.tekst(p.get("status")) == STATUS_U_TIJEKU:
            return p
    return None


def zadnji_predani(sheet, dodjela_id: str) -> dict | None:
    for p in pokusaji_ucenika(sheet, dodjela_id):
        if model.tekst(p.get("status")) in (STATUS_PREDANO, STATUS_PO_ISTEKU):
            return p
    return None


def predano(sheet, dodjela_id: str) -> bool:
    return zadnji_predani(sheet, dodjela_id) is not None


# ------------------------------------------------------------------ rok i vrijeme

def smije_poceti(dodjela: dict, definicija: dict, danas=None) -> tuple[bool, str]:
    """Smije li učenik otvoriti test sada. Vraća (smije, razlog ako ne smije)."""
    stanje = dodjele.stanje_roka(dodjela, definicija, danas)
    if stanje == "nije_poceo":
        r = dodjele.rok_dodjele(dodjela, definicija, danas)
        return False, f"Test se otvara {r['od_iso']}."
    if stanje == "zatvoren":
        r = dodjele.rok_dodjele(dodjela, definicija, danas)
        return False, f"Rok je prošao ({r['do_iso']})."
    return True, ""


def _kao_vrijeme(v) -> datetime | None:
    s = model.tekst(v)
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


def vrijeme_isteka(pokusaj: dict, definicija: dict) -> datetime | None:
    pocetak = _kao_vrijeme((pokusaj or {}).get("pocetak"))
    if not pocetak:
        return None
    return pocetak + timedelta(minutes=model.cijeli((definicija or {}).get("trajanje_min"), 45))


def preostalo_s(pokusaj: dict, definicija: dict, sada=None) -> int:
    """Preostale sekunde (može biti negativno — tada je istekao)."""
    rok = vrijeme_isteka(pokusaj, definicija)
    if not rok:
        return 0
    return int((rok - (sada or model.sada())).total_seconds())


def je_istekao(pokusaj: dict, definicija: dict, sada=None) -> bool:
    return preostalo_s(pokusaj, definicija, sada) <= 0


# ------------------------------------------------------------------ početak

def zapocni(sheet, dodjela: dict, definicija: dict, *, sada=None) -> dict:
    """Otvori pokušaj (ili vrati postojeći u tijeku). **Ne dopušta** drugi pokušaj nakon predaje."""
    sada = sada or model.sada()
    did = model.tekst((dodjela or {}).get("dodjela_id"))
    if not did:
        raise ValueError("Dodjela nema ID.")
    if predano(sheet, did):
        raise ValueError("Test je već predan.")

    postoji = aktivni(sheet, did)
    if postoji:
        return postoji

    smije, razlog = smije_poceti(dodjela, definicija, sada.date())
    if not smije:
        raise ValueError(razlog)

    svi = tablice.svi_idovi(sheet, tablice.TAB_POKUSAJI, "pokusaj_id")
    pokusaj_id = tablice.novi_id(svi, "P26-")
    redak = {
        "pokusaj_id": pokusaj_id,
        "dodjela_id": did,
        "definicija_id": model.tekst((dodjela or {}).get("definicija_id")),
        "ucenik_id": model.tekst((dodjela or {}).get("ucenik_id")),
        "pocetak": sada.strftime("%Y-%m-%d %H:%M:%S"),
        "zadnja_aktivnost": sada.strftime("%Y-%m-%d %H:%M:%S"),
        "predaja": "",
        "trajanje_s": 0,
        "odgovori_json": model.u_json({}),
        "bodovi": 0,
        "bodovi_max": model.broj((definicija or {}).get("bodovi_ukupno")),
        "status": STATUS_U_TIJEKU,
        "predano_po_roku": "",
    }
    tablice.dodaj(sheet, tablice.TAB_POKUSAJI, [redak])
    tablice.azuriraj(sheet, tablice.TAB_DODJELE, "dodjela_id", did, {"status": "u_tijeku"})
    return redak


# ------------------------------------------------------------------ autosave

def odgovori(pokusaj: dict) -> dict:
    """Odgovori iz pokušaja kao {redni_broj(str): odgovor}.

    Sprema se kao JSON **objekt** (`{"0": "2"}`), a stariji zapisi mogli su biti lista — zato oba.
    """
    izlaz = model.kao_dict((pokusaj or {}).get("odgovori_json"))
    if izlaz:
        return {k: v for k, v in izlaz.items() if model.tekst(v)}
    lista = model.kao_json((pokusaj or {}).get("odgovori_json"))
    for i, v in enumerate(lista or []):
        if model.tekst(v):
            izlaz[str(i)] = v
    return izlaz


def _svjez(sheet, pokusaj: dict) -> dict:
    """Stanje pokušaja iz Sheeta — dict u sesiji može biti zastario (dva taba, dvostruki klik)."""
    pid = model.tekst((pokusaj or {}).get("pokusaj_id"))
    return pokusaj_po_id(sheet, pid) or (pokusaj or {})


def spremi(sheet, pokusaj: dict, novi_odgovori: dict, *, sada=None) -> bool:
    """Autosave: jedan upis po pozivu (Sheets kvota). Ne dira ništa ako je pokušaj predan."""
    if model.tekst(_svjez(sheet, pokusaj).get("status")) != STATUS_U_TIJEKU:
        return False
    sada = sada or model.sada()
    spojeni = odgovori(pokusaj)
    for k, v in (novi_odgovori or {}).items():
        kljuc = model.tekst(k)
        if kljuc:
            spojeni[kljuc] = v
    ok = tablice.azuriraj(sheet, tablice.TAB_POKUSAJI, "pokusaj_id",
                          model.tekst(pokusaj.get("pokusaj_id")),
                          {"odgovori_json": model.u_json(spojeni),
                           "zadnja_aktivnost": sada.strftime("%Y-%m-%d %H:%M:%S")})
    if ok:
        pokusaj["odgovori_json"] = model.u_json(spojeni)
    return ok


# ------------------------------------------------------------------ predaja

def _zadaci_iz_snimke(pokusaj: dict) -> list:
    """Zadaci iz snimke pokušaja (`zadaci_json`) — što je učenik STVARNO dobio (§12.11.4)."""
    import json

    tekst = model.tekst((pokusaj or {}).get("zadaci_json"))
    if not tekst:
        return []
    try:
        podaci = json.loads(tekst)
    except Exception:                                   # noqa: BLE001
        return []
    return podaci if isinstance(podaci, list) else []


def zamrzni_zadatke(sheet, pokusaj_id: str, zadaci: list) -> bool:
    """Upiši snimku zadataka u pokušaj (jednom). Nikad ne ruši rješavanje."""
    import json

    pid = model.tekst(pokusaj_id)
    if not pid or not zadaci:
        return False
    try:
        for red in tablice.ucitaj(sheet, tablice.TAB_POKUSAJI):
            if model.tekst(red.get("pokusaj_id")) != pid:
                continue
            if model.tekst(red.get("zadaci_json")):
                return True                             # već zamrznuto
            return bool(tablice.azuriraj(
                sheet, tablice.TAB_POKUSAJI, "pokusaj_id", pid,
                {"zadaci_json": json.dumps(zadaci, ensure_ascii=False)}))
    except Exception:                                   # noqa: BLE001
        return False
    return False


def zadaci_za_pokusaj(definicija: dict, dodjela: dict, sheet=None, pokusaj=None) -> list[dict]:
    """Zadaci u redoslijedu koji učenik vidje (A/B miješanje po seedu dodjele).

    **§12.11.4:** ako pokušaj ima snimku (`zadaci_json`), vraća se ONA — promjena definicije više
    ne može promijeniti test ispod učenika. Bez snimke ponašanje je kao prije (uz zamrzavanje kad
    su `sheet` i `pokusaj` zadani).
    """
    snimka = _zadaci_iz_snimke(pokusaj or {})
    if snimka:
        return snimka

    sirovi = definicije.zadaci(definicija)
    try:
        pravilo = model.kao_json((definicija or {}).get("varijanta_pravilo"))
    except Exception:                                   # noqa: BLE001
        pravilo = []
    postavke = pravilo if isinstance(pravilo, dict) else {}
    mijesaj_z = postavke.get("mijesaj_zadatke", True)
    mijesaj_o = postavke.get("mijesaj_odgovore", True)

    if not mijesaj_z and not mijesaj_o:
        izlaz = sirovi
    else:
        seed = (model.tekst((dodjela or {}).get("varijanta_seed"))
                or model.tekst((dodjela or {}).get("ucenik_id")))
        if not mijesaj_z:
            izlaz = definicije.izmijesaj_odgovore(sirovi, seed) if mijesaj_o else sirovi
        else:
            izlaz = definicije.izmijesaj(sirovi, seed, mijesaj_odgovore=mijesaj_o)

    # zamrzni prvi put (samo ako je pisanje dopušteno i pokušaj postoji)
    if sheet is not None and pokusaj:
        try:
            if not _zadaci_iz_snimke(pokusaj):
                zamrzni_zadatke(sheet, pokusaj.get("pokusaj_id"), izlaz)
        except Exception:                               # noqa: BLE001
            pass
    return izlaz


def _zapisi_statistiku(sheet, pokusaj: dict, definicija: dict, zadaci: list[dict],
                       odgovori: dict) -> int:
    """📈 Append u `Statistika_zadataka` nakon predaje (§12.11.3). Nikad ne ruši predaju.

    Jedan redak po zadatku, s vremenskom oznakom — povijest se NE prepisuje (append-only), što je
    preduvjet za kasniju IRT analizu.
    """
    try:
        import statistika

        pid = model.tekst(pokusaj.get("pokusaj_id"))
        ocjene = [r for r in tablice.ucitaj(sheet, tablice.TAB_OCJENE)
                  if model.tekst(r.get("pokusaj_id")) == pid]
        return statistika.zapisi_predaju(
            sheet, pokusaj_id=pid,
            definicija_id=model.tekst(definicija.get("definicija_id")),
            zadaci=zadaci, odgovori=odgovori, ocjene=ocjene)
    except Exception:                                   # noqa: BLE001
        return 0


def predaj(sheet, pokusaj: dict, definicija: dict, *, odgovori_=None, sada=None, pozovi=None,
           dopusti_ai: bool | None = None) -> dict:
    """Ocijeni i zaključi pokušaj. Vraća {"bodovi", "maks", "status", "ceka_profesora", "detalji"}."""
    sada = sada or model.sada()
    if dopusti_ai is None:                              # 💡 AI pomoć je odluka PO TESTU
        try:
            dopusti_ai = bool(definicije.smije_ai(definicija))
        except Exception:                               # noqa: BLE001
            dopusti_ai = False
    if model.tekst(_svjez(sheet, pokusaj).get("status")) != STATUS_U_TIJEKU:
        raise ValueError("Ovaj pokušaj je već zaključen.")

    if odgovori_ is not None:
        spremi(sheet, pokusaj, odgovori_, sada=sada)

    dodjela = next((d for d in tablice.ucitaj(sheet, tablice.TAB_DODJELE)
                    if model.tekst(d.get("dodjela_id")) == model.tekst(pokusaj.get("dodjela_id"))), {})
    zadaci = zadaci_za_pokusaj(definicija, dodjela, sheet=sheet, pokusaj=pokusaj)
    odg = odgovori(pokusaj)
    ocjena = ocjenjivanje.ocjeni_zadatke(
        zadaci, {model.cijeli(k, -1): v for k, v in odg.items()}, pozovi=pozovi, dopusti_ai=dopusti_ai)

    pocetak = _kao_vrijeme(pokusaj.get("pocetak")) or sada
    po_roku = je_istekao(pokusaj, definicija, sada)
    status = STATUS_PO_ISTEKU if po_roku else STATUS_PREDANO

    tablice.azuriraj(sheet, tablice.TAB_POKUSAJI, "pokusaj_id", model.tekst(pokusaj.get("pokusaj_id")), {
        "predaja": sada.strftime("%Y-%m-%d %H:%M:%S"),
        "trajanje_s": max(0, int((sada - pocetak).total_seconds())),
        "bodovi": ocjena["bodovi"],
        "bodovi_max": ocjena["maks"],
        "status": status,
        "predano_po_roku": "Da" if po_roku else "Ne",
    })
    tablice.azuriraj(sheet, tablice.TAB_DODJELE, "dodjela_id", model.tekst(pokusaj.get("dodjela_id")),
                     {"status": "predano"})

    _upisi_ocjene(sheet, pokusaj, ocjena)

    # 📈 statistika zadatka (append) — poslije ocjena, jer se p i distraktori čitaju iz njih
    try:
        _zapisi_statistiku(sheet, pokusaj, definicija, zadaci, odg)
    except Exception:                                   # noqa: BLE001
        pass

    return {"bodovi": ocjena["bodovi"], "maks": ocjena["maks"], "status": status,
            "ceka_profesora": ocjena["ceka_profesora"], "detalji": ocjena["detalji"],
            "postotak": ocjenjivanje.postotak(ocjena["bodovi"], ocjena["maks"])}


def _upisi_ocjene(sheet, pokusaj: dict, ocjena: dict) -> int:
    """Jedan redak po zadatku — osnova za mjerenje kvalitete zadatka (p, r, distraktori)."""
    redci = []
    for d in ocjena.get("detalji") or []:
        redci.append({
            "pokusaj_id": model.tekst(pokusaj.get("pokusaj_id")),
            "zadatak_id": model.tekst(d.get("zadatak_id")),
            "redni_broj": d.get("redni_broj"),
            "odgovor": model.tekst(d.get("odgovor")),
            "tocno": "Da" if d.get("tocno") else "Ne",
            "bodovi": d.get("bodovi"),
            "max": d.get("max"),
            "izvor_ocjene": model.tekst(d.get("izvor")),
            "vrijeme_s": "",
            "komentar": "",
        })
    return tablice.dodaj(sheet, tablice.TAB_OCJENE, redci)


def _preracunaj_pokusaj(sheet, pokusaj_id: str) -> bool:
    """Zbroji `Ocjene_zadataka` i upiši ukupne bodove u `Pokusaji` (G5).

    Prije: ručna ispravka zadatka nije mijenjala ukupe bodove → učenik je vidio stari rezultat.
    """
    pid = model.tekst(pokusaj_id)
    if not pid:
        return False
    try:
        redci = [r for r in tablice.ucitaj(sheet, tablice.TAB_OCJENE)
                 if model.tekst(r.get("pokusaj_id")) == pid]
    except Exception:                                   # noqa: BLE001
        return False
    if not redci:
        return False
    bodovi = sum(model.broj(r.get("bodovi"), 0) for r in redci)
    maks = sum(model.broj(r.get("max"), 0) for r in redci)
    return bool(tablice.azuriraj(sheet, tablice.TAB_POKUSAJI, "pokusaj_id", pid,
                                 {"bodovi": bodovi, "bodovi_max": maks}))


def ocijeni_rucno(sheet, pokusaj_id: str, zadatak_id: str, *, tocno: bool, bodovi=None,
                  komentar: str = "", profesor: str = "",
                  povod: str = "profesor_sam_primijetio") -> bool:
    """Profesor ispravlja ocjenu jednog zadatka.

    **G5 (01.11.2026.):** nakon upisa preračunavaju se **ukupni bodovi pokušaja**; uklonjen je
    mrtvi `placeholder` poziv koji je pisao prazan rječnik.
    `povod` ide u `Izmjene_ocjena` (`zalba` kad ispravak dolazi iz žalbe).
    """
    for r in tablice.ucitaj(sheet, tablice.TAB_OCJENE):
        if (model.tekst(r.get("pokusaj_id")) == model.tekst(pokusaj_id)
                and model.tekst(r.get("zadatak_id")) == model.tekst(zadatak_id)):
            iznos = bodovi if bodovi is not None else (model.broj(r.get("max"), 0) if tocno else 0)
            ok = _upisi_rucno(sheet, r, tocno, iznos, komentar, profesor, povod=povod)
            if ok:
                _preracunaj_pokusaj(sheet, pokusaj_id)
            return ok
    return False


def _kao_bool(vrijednost):
    """„Da"/„da"/True → True; „Ne"/0/False → False; prazno/ostalo → None."""
    tekst = model.tekst(vrijednost).lower()
    if tekst in ("da", "1", "true", "točno", "tocno"):
        return True
    if tekst in ("ne", "0", "false", "netočno", "netocno"):
        return False
    return None


def _upisi_rucno(sheet, redak: dict, tocno: bool, bodovi, komentar: str, profesor: str,
                 povod: str = "profesor_sam_primijetio") -> bool:
    """Pomoćna: upiše ručnu ocjenu u točan redak `Ocjene_zadataka`."""
    ws = tablice.osiguraj(sheet, tablice.TAB_OCJENE)
    zaglavlje = [model.tekst(h) for h in (ws.row_values(1) or [])]
    if not zaglavlje:
        return False
    i_pok = zaglavlje.index("pokusaj_id") if "pokusaj_id" in zaglavlje else 0
    i_zad = zaglavlje.index("zadatak_id") if "zadatak_id" in zaglavlje else 1
    for br, red in enumerate(ws.get_all_values()[1:], start=2):
        if (i_pok < len(red) and model.tekst(red[i_pok]) == model.tekst(redak.get("pokusaj_id"))
                and i_zad < len(red) and model.tekst(red[i_zad]) == model.tekst(redak.get("zadatak_id"))):
            # 📝 TRAG (§12.10/§12.11.2): zapiši izmjenu PRIJE prepisivanja — prijašnja ocjena,
            # bodovi i IZVOR (string/sympy/ai/profesor) se inače nepovratno gube.
            try:
                import izmjene_ocjena as _izmj

                _izmj.zapisi(
                    sheet,
                    pokusaj_id=model.tekst(redak.get("pokusaj_id")),
                    zadatak_id=model.tekst(redak.get("zadatak_id")),
                    ocjena_prije=_kao_bool(redak.get("tocno")),
                    ocjena_poslije=bool(tocno),
                    bodovi_prije=redak.get("bodovi"),
                    bodovi_poslije=bodovi,
                    izvor_prije=model.tekst(redak.get("izvor_ocjene")),
                    razlog=komentar,
                    povod=povod,
                    tko=profesor,
                )
            except Exception:                          # noqa: BLE001 — trag ne smije blokirati ocjenu
                pass
            for polje, vrijednost in (("tocno", "Da" if tocno else "Ne"),
                                      ("bodovi", bodovi),
                                      ("izvor_ocjene", ocjenjivanje.IZVOR_PROFESOR),
                                      ("komentar", model.tekst(komentar))):
                if polje in zaglavlje:
                    ws.update_cell(br, zaglavlje.index(polje) + 1, vrijednost)
            tablice.zapisi_radnju(sheet, profesor, "rucna_ocjena",
                                 f"{redak.get('pokusaj_id')}/{redak.get('zadatak_id')}")
            return True
    return False
