"""
CAKI testovi v2 — `zavrsetak.py`
ZAVRŠETAK ISPITA: upozorenje pred kraj, automatska predaja u trenutku isteka i slanje postupka.

Zašto zaseban modul: to su pravila koja moraju vrijediti jednako u pregledu za Cakija i u
stvarnom rješavanju, a provjeravaju se bez Streamlita. Ekran (`ekran_ucenika.py`) samo crta
ono što ovi pomoćnici odrede.

Cakijeva pravila (31.10.2026.):
  1. zadnjih **5 minuta** timer upozorava (blinka) i piše da se bliži kraj pisanja ispita;
  2. kad vrijeme istekne, test se **automatski predaje** — poslije toga nema novih odgovora
     ni naknadne predaje;
  3. nakon predaje učenik pošalje **slike postupka (može više) ili PDF**, ili potvrdi da nema
     što poslati — tek tada je test završen.
"""
from __future__ import annotations

import model
import provedba

PRAG_UPOZORENJA_S = 5 * 60          # zadnjih 5 minuta pisanja

# Što učenik smije priložiti kao postupak (fotografija s mobitela ili sken/PDF).
DOPUSTENE_DATOTEKE = ("png", "jpg", "jpeg", "webp", "heic", "pdf")


# ================================================================ vrijeme

def mmss(sekunde) -> str:
    """„4:59" / „1:02:03" / „0:00" — vrijeme do kraja, nikad negativno."""
    s = max(0, int(model.broj(sekunde)))
    h, ost = divmod(s, 3600)
    m, sec = divmod(ost, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def stanje_vremena(pokusaj: dict, definicija: dict, sada=None) -> dict:
    """Sve o vremenu na jednom mjestu — timer, upozorenje i (ne)dopuštena predaja.

    Vrijeme se računa na poslužitelju iz `pocetak` pokušaja (nikad iz preglednika).
    """
    preostalo = provedba.preostalo_s(pokusaj, definicija, sada)
    return {
        "preostalo_s": preostalo,
        "istekao": preostalo <= 0,
        "blizi_se": 0 < preostalo <= PRAG_UPOZORENJA_S,
        "tekst": "isteklo" if preostalo <= 0 else mmss(preostalo),
    }


def treba_auto_predaju(pokusaj: dict, definicija: dict, sada=None) -> bool:
    """Pokušaj još traje, a vrijeme je isteklo → predaj ga sada (nema naknadnog unosa)."""
    return (model.tekst((pokusaj or {}).get("status")) == provedba.STATUS_U_TIJEKU
            and provedba.je_istekao(pokusaj, definicija, sada))


def je_zavrsen(pokusaj: dict) -> bool:
    """Je li pokušaj zaključen (predan ili predan po isteku)."""
    return model.tekst((pokusaj or {}).get("status")) in (
        provedba.STATUS_PREDANO, provedba.STATUS_PO_ISTEKU)


def predan_po_isteku(pokusaj: dict) -> bool:
    return model.tekst((pokusaj or {}).get("predano_po_roku")).lower() == "da"


# ================================================================ poruke

def tekst_upozorenja(preostalo_s) -> str:
    """Zadnjih 5 minuta — kratko, jasno, bez panike."""
    return ("⏳ **Bliži se završetak pisanja ispita.** Ostalo je još "
            f"**{mmss(preostalo_s)}**. Ne zaboravi predati test — kad vrijeme istekne, test se "
            "predaje automatski i odgovori se više ne mogu mijenjati.")


def tekst_isteka(auto: bool = True) -> str:
    """Poruka kad je vrijeme isteklo."""
    if auto:
        return ("⏰ **Vrijeme je isteklo.** Test je **automatski predan** sa svim odgovorima koji "
                "su bili spremljeni. Nakon isteka odgovori se više ne mogu dopisivati ni test "
                "predati naknadno.")
    return ("⏰ **Vrijeme je isteklo.** Test je predan po isteku roka — odgovori se više ne mogu "
            "mijenjati.")


def tekst_koraka_1(praznih: int = 0, ukupno: int = 0) -> str:
    """Objašnjenje iznad gumba „POŠALJI ODGOVORE”."""
    osnova = ("Provjeri odgovore pa pošalji test. **Nakon predaje odgovori se više ne mogu "
              "mijenjati**, a test se zatvara.")
    if praznih and ukupno:
        return (f"{praznih} od {ukupno} zadataka još nema odgovor (prazni nose 0 bodova). "
                + osnova)
    return osnova


def tekst_koraka_2() -> str:
    """Zašto slati postupak — Cakijeva želja: učenik mora znati da postupak zanima profesora."""
    return ("**Zanima me tvoj postupak, ne samo konačan odgovor.** Slikaj svoj rad — može više "
            "slika — ili pošalji PDF. Slike i PDF profesor pregleda, pa se vidi i **kako** si "
            "došao do rješenja.")


def tekst_zavrseno() -> str:
    return ("✅ **Test je završen.** Hvala! Ako si poslao/la slike postupka, profesor će ih "
            "pregledati.")


def tekst_bez_postupka() -> str:
    return ("✅ **Test je završen.** Zabilježeno je da nemaš postupak za slanje. Ako se ipak "
            "sjetiš slika, javi profesoru — može ih se dodati naknadno.")


# ================================================================ slanje postupka

def _naziv(datoteka: dict, redni: int) -> str:
    naziv = model.tekst((datoteka or {}).get("naziv"))
    if not naziv:
        naziv = f"postupak_{redni}.jpg"
    return naziv


def posalji_postupak(sheet, *, pokusaj: dict, ucenik_id: str, datoteke, folder: str,
                     servis=None, prilozio: str = "") -> dict:
    """Pošalji slike/PDF postupka u Drive i zapiši ih uz pokušaj (tab `Radovi`).

    `datoteke` = [{"naziv": "IMG1.jpg", "bajtovi": b"…"}, …] — može ih biti više.
    `servis` je injektabilan (testovi bez Googlea).

    Vraća {"poslano": [...], "greske": [...], "pokusaj_id": ...}. **Nikad ne puca**: greška
    jedne datoteke ne smije izgubiti ostale (Cakijevo pravilo: rad se ne smije izgubiti).
    """
    import drive
    import radovi

    pid = model.tekst((pokusaj or {}).get("pokusaj_id"))
    if not pid:
        return {"poslano": [], "greske": ["Pokušaj nema ID — slike se ne mogu povezati s testom."],
                "pokusaj_id": ""}

    poslano, greske = [], []
    for redni, d in enumerate(list(datoteke or []), start=1):
        naziv = _naziv(d, redni)
        bajtovi = (d or {}).get("bajtovi") or b""
        try:
            veza, greska = drive.ucitaj(bajtovi, naziv, folder=folder, servis=servis)
            if greska:
                greske.append(f"{naziv}: {greska}")
                continue
            radovi.dodaj_ucenikov_rad(
                sheet, pokusaj_id=pid, ucenik_id=ucenik_id, veza=veza,
                sadrzaj=bajtovi, naziv=naziv)
            poslano.append({"naziv": naziv, "veza": veza})
        except Exception as e:                          # noqa: BLE001 — jedna slika ne ruši ostale
            greske.append(f"{naziv}: {type(e).__name__}: {e}")
    return {"poslano": poslano, "greske": greske, "pokusaj_id": pid}


def posalji_poveznicu(sheet, *, pokusaj: dict, ucenik_id: str, veza: str, naziv: str = "") -> dict:
    """Rezervni put kad upload ne radi: učenik zalijepi poveznicu na fotografiju/sken."""
    import radovi

    pid = model.tekst((pokusaj or {}).get("pokusaj_id"))
    if not pid:
        raise ValueError("Pokušaj nema ID — poveznica se ne može povezati s testom.")
    if not model.tekst(veza):
        raise ValueError("Zalijepi poveznicu na fotografiju ili sken.")
    rad = radovi.dodaj_ucenikov_rad(sheet, pokusaj_id=pid, ucenik_id=ucenik_id,
                                    veza=veza, naziv=naziv or "Postupak (poveznica)")
    return {"rad": rad, "pokusaj_id": pid}
