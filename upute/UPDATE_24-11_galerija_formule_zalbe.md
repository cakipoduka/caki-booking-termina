# UPDATE 24.11.2026. (2) — ocjenjivanje uz radove, formule uz test, ispravak žalbe

Caki:
1. „Može li se učitana slika/pdf pregledavati u desnoj polovici prozora dok se na lijevoj vide
   odgovori na zadatke, pa da profesor u jednom prozoru ocjenjuje i pregledava slike?"
2. „U ver1 smo imali opciju dodavanja formula (caki-zadaci…/formule) — kopirati u ver2."
3. „Nemoj konačno zaključavati žalbu — uvijek ostaviti opciju ispravka od strane profesora."

## 1. 🖼️ Ocjenjivanje uz radove (`galerija_radova.py`, `app.py`)

📊 Rezultati → pregled po učeniku → prekidač **„🖼️ Ocjenjuj uz radove"** (uključen sam kad
učenik ima priložen rad):
* **lijevo** su zadaci s odgovorima, bodovima i žalbama, u okviru s vlastitim klizačem (880 px).
  Desna strana zato ostaje na mjestu dok listaš zadatke;
* **desno** je pregled rada. Za Drive datoteke to je Googleov pregled (`…/file/d/<id>/preview`),
  koji prikazuje sliku i PDF, s povećavanjem i listanjem stranica. Ima izbor rada, strelice
  ◀ ▶, „↗ Otvori u novoj kartici" i „✅ Potvrdi pregled ovog rada";
* izravna slika s weba se prikaže, a ostale poveznice (npr. Google Photos) dobiju samo gumb;
* zapisi bez datoteke (stari neuspjeli pokušaji) se navode, ne skrivaju.

Pregled se vidi jer si u pregledniku prijavljen Google računom koji je član dijeljenog diska.
Aplikacija ništa ne preuzima. U drugom pregledniku ili računu Google traži prijavu.

## 2. 📐 Formule uz test (`formule_testa.py`, iz v1)

Isti model kao v1:
* formule se i dalje unose u **bazi zadataka** (📐 Formule u caki-zadaci, tab `Formule`, paketi);
* **caki-testovi → 🧪 Testovi → test → „📐 Formule uz test"**: „Sve aktivne", „Paketi",
  „Pojedinačne formule", pa „💾 Spremi formule uz test". Ispod je popis i „Pogledaj kako ih
  učenik vidi". Može se mijenjati i kad test već ima pokušaje (okvir testa, kao rok);
* u test ide **zamrznuta kopija** (`Definicije_testova.formule_json`);
* **učenik (Moj CAKI)** tijekom testa ima gumb **„📐 Formule (N)"** iznad pitanja. Otvara se
  skočni prozor s formulama. v1 ih je držao u desnoj koloni, ali na mobitelu bi kolona pala ispod
  svakog pitanja. Ako želiš desnu kolonu, to je mala izmjena.

**Novi stupac `formule_json`:** postojeći tab nema stupac. `tablice.azuriraj()` sada dopisuje na
kraj zaglavlja stupac koji sustav traži, a tab ga nema, umjesto da se vrijednost tiho izgubi.
Prvo spremanje formula sam ga doda; ništa ručno.

## 3. ⚖️ Žalba se ne zaključava konačno (`zalbe.ispravi()`, `ekran_ucenika.py`)

Uz zaključenu žalbu profesor ima **„✏️ Ispravi odgovor ili odluku"**, s promijenjenim tekstom i
odlukom („Spremi ispravak" / „Odustani"):
* odluka ista: mijenja se samo tekst;
* priznato u nije priznato: zadatak na 0 b.; nije priznato u priznato: puni bodovi. Trag ide u
  `Izmjene_ocjena` (povod `zalba_ispravak`) i zbroj se preračunava;
* učenik vidi novi odgovor i odluku, ali **drugu žalbu na isti zadatak ne može podnijeti**.

## Testovi

Novo: `test_galerija_radova.py` (8, s pravim rasporedom lijevo/desno), `test_formule_testa.py`
(9, s pravim ekranom rješavanja), u `test_zalbe_odgovor.py` +5 (ispravak). Portal +2.
```
caki-testovi           → 195 passed
caki-booking-termina   →  29 passed
```

## Otvoreno

* Formule se čitaju iz Sheeta `SHEET_ID` (matematika). Formule za fiziku u Sheetu fizike
  caki-testovi zasad ne vidi.

---

📌 COMMIT
* `caki-testovi` · `main`: `app.py`, `zalbe.py`, `ekran_ucenika.py`, `definicije.py`,
  `tablice.py`, `galerija_radova.py` (novo), `formule_testa.py` (novo),
  `testovi/test_zalbe_odgovor.py`, `testovi/test_galerija_radova.py` (novo),
  `testovi/test_formule_testa.py` (novo), `upute/UPDATE_24-11_galerija_formule_zalbe.md`
* `caki-booking-termina` · `main`: `tablice.py`, `definicije.py`, `zalbe.py`,
  `ekran_ucenika_v2.py`, `formule_testa.py` (novo), `testovi/test_portal_rjesenja_zalbe_radovi.py`,
  `upute/UPDATE_24-11_galerija_formule_zalbe.md`
* Poruka: `Ocjenjivanje uz radove (galerija), formule uz test iz v1, ispravak žalbe`
* Uživo nakon **Push** oba repoa + **Reboot caki-testovi i moj-caki**.
