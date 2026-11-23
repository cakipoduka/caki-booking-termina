# UPDATE 24.11.2026. — slanje postupka nakon testa u Moj CAKI + čišćenje testova

Caki (testni račun, nakon Pusha od 23.11.):
`Nije poslano — C..jpg: AttributeError: module 'radovi' has no attribute 'dodaj_ucenikov_rad'`

## Uzrok

`zavrsetak.py` (slanje slika postupka **nakon** završetka testa) radio je `import radovi`. U Moj
CAKI je `radovi.py` stari v1 modul, a v2 je kopiran kao `radovi_v2.py`. Slika je **već bila na
Driveu** (`C..jpg`, 02_Radovi_ucenika, 23.11. 00:06), a pukao je zapis u tab `Radovi`.

**Drive sada radi.** Scope `drive` i servisni račun su u redu.

Ista zamka u `ocjenjivanje.py`: `import ai_pomoc` je u portalu učitavao v1 modul bez `pitaj`.
AI sloj ocjenjivanja u portalu zato nikad nije radio (greška se tiho gutala, pa su sve „sumnje"
išle profesoru).

## Popravak (datoteke identične u oba repoa)

* `zavrsetak._radovi_modul()`: prvo `radovi_v2`, inače `radovi`.
* `ocjenjivanje.ai_provjeri_izraz`: prvo `ai_pomoc_v2`, inače `ai_pomoc`.

## Testovi: curenje predmemorije

`tablice.py` ima vlastitu predmemoriju s ključem `id(sheet)`. Python ponovo koristi isti `id`
kad stari lažni Sheet nestane, pa je test znao dobiti retke prethodnog testa. `conftest.py` je
čistio samo Streamlitovu predmemoriju. Sada čisti i `tablice._ocisti_cache()`.

**Posljedica:** dva pada u `test_brisanje_i_arhiva.py`, prijavljivana od 21.11. kao „od prije",
bila su upravo to. Kod brisanja je ispravan.

```
caki-testovi           python -m pytest testovi/ -q   → 162 passed
caki-booking-termina   python -m pytest testovi/ -q   →  27 passed
```

## Otvoreno

* Portalov `ocjenjivanje._provjera()` (rezerva za normalizaciju zapisa) učitava portalov **v1**
  `provjera_odgovora.py`. Bodovanje je provjereno i točno (prvi sloj ima vlastitu provjeru), ali
  normalizacija u portalu i u caki-testovi nije ista funkcija. Rješava se izvedbom B.
* `C..jpg` je na Driveu bez retka u `Radovi`. Poveznica:
  https://drive.google.com/file/d/1OWV10nWCsQns1HyGQNsLqIe9uyTQyGMT/view
  Dodaje se ručno („Priloži rad" u pregledu po učeniku), ili se rad pošalje ponovo.

---

📌 COMMIT (dva repoa)
* `caki-testovi` · `main`: `zavrsetak.py`, `ocjenjivanje.py`, `testovi/conftest.py`,
  `testovi/test_slanje_rada.py`, `upute/UPDATE_24-11_slanje_postupka.md`
* `caki-booking-termina` · `main`: `zavrsetak.py`, `ocjenjivanje.py`,
  `testovi/test_portal_rjesenja_zalbe_radovi.py`, `upute/UPDATE_24-11_slanje_postupka.md`
* Poruka: `Slanje postupka nakon testa: v2 radovi/ai_pomoc u portalu; testovi čiste predmemoriju tablica`
* Uživo nakon **Push** + **Reboot** (moj-caki je bitan; caki-testovi samo zbog istovjetnosti).
