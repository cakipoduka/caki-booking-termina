# UPDATE 23.11.2026. (večer) — Moj CAKI: rješenja i žalba nakon zatvaranja, slanje rada

Cakijeva prijava s testnog računa OH3229 („Inicijalno testiranje - MATURA A razina (demo2)"):
test zatvoren, a portal kaže „Rješenja će biti dostupna nakon isteka roka". Rješenja se vide samo
u caki-testovi, učenik nema žalbu, a slika poslana 4 puta nije na Driveu.

Glavni opis uzroka je u `caki-testovi/upute/UPDATE_23-11_rjesenja_uklanjanje_radovi.md`.
Ovdje je što se promijenilo u portalu.

## Uzroci specifični za portal

1. **Portalove kopije v2 modula bile su od 5.11.** Sav posao od 20.11. (pregled riješenog testa s
   cijelim zadatkom, žalba po zadatku, brisanje) postojao je samo u caki-testovi.
2. **`zalbe.py` uopće nije postojao u portalu.** Ekran ga uvozi unutar `try … except: pass`, pa
   je obrazac za žalbu tiho nestajao bez ijedne poruke.
3. Zatvoren test nije otvarao rješenja (isti uzrok kao u caki-testovi, `dodjele.stanje_roka`).
4. Slanje rada: zapis bez slike kad Drive odbije, a poruku s razlogom brisao je `st.rerun()`.

## Što je napravljeno

**Osvježene kopije iz caki-testovi** (sadržaj identičan, samo `ekran_ucenika_v2` uvozi
`ai_pomoc_v2` i `slike_zadataka_v2`): `tablice.py`, `definicije.py`, `dodjele.py`, `rjesavanje.py`,
`drive.py`, `radovi_v2.py` (= `radovi.py`), `ekran_ucenika_v2.py` (= `ekran_ucenika.py`).
**Nove kopije:** `zalbe.py`, `banka.py` (pregled ga koristi za 🎬 video uz rješenje).

Provjereno: nijedna funkcija koju je portal imao nije nestala. Te module koristi samo v2 dio
portala (`testovi_v2.py`, `posjete.py`, `provedba.py`). v1 (`testovi_online.py`, `radovi.py`,
`provjera_odgovora.py`) nije diran.

**`testovi_v2.py`:**
* slanje rada ide kroz `radovi.posalji_ucenikov_rad()`: bez slike i bez poveznice nema zapisa,
  a poruka i tehnički razlog (sa servisnim računom) ostaju na ekranu;
* pregled rješenja dobiva jedinstven ključ po dodjeli. Bez toga bi dva riješena testa na istoj
  stranici dala iste ključeve obrazaca za žalbu i Streamlit bi pukao.

## Provjereno u pravom Streamlitu (AppTest, portalova kartica s lažnim Sheetom)

| Slučaj | Prije | Sada |
|---|---|---|
| Test objavljen, učenik dodan danas | „nakon isteka roka" | isto (ispravno, rok je otvoren) |
| Test **zatvoren**, učenik dodan danas | „nakon isteka roka" | oba zadatka u pregledu + polje za žalbu |
| Učenik pošalje žalbu | obrasca nema | redak u `Zalbe` (`podnesena`) |

## Slika na Drive: što napraviti nakon Pusha

Pošalji sliku još jednom s testnog računa i pročitaj „Tehnički detalj (za Cakija)" ispod poruke.
Sada piše razlog i kojim je računom pokušano. Najčešće:

* **račun nije `caki-streamlit-bot@…`**: u Secrets portala postoji
  `GOOGLE_SERVICE_ACCOUNT_JSON_TESTOVI` s drugim računom (Drive ga ima prednost). Ili ga obriši,
  ili tom računu daj Content manager na dijeljenom disku;
* **„Google Drive API nije uključen"**: u Google Cloud projektu `streamlit-sucelje-za-ispite`
  uključi Google Drive API. Sheets API radi zasebno, zato Sheet radi a Drive ne;
* **`notFound`**: račun ne vidi mapu (ID ili članstvo).

## Testovi

```
cd caki-booking-termina
python -m pytest testovi/ -q        → 23 passed
```
Novo: `testovi/test_portal_rjesenja_zalbe_radovi.py` (5, od toga 2 AppTesta kartice) i
`testovi/fake_gspread.py` (lažni Sheet, kopija iz caki-testovi). U
`test_portal_mathlive_i_drive.py` je promijenjeno jedno očekivanje (poruka greške nosi tekst).

## Otvoreno

* Kopije i dalje postoje. Ovo je drugi put u tri dana da popravak u caki-testovi nije stigao do
  učenika. Odluka 23.11.: izvedba B je u planu.
* Ranije poslani „radovi" testnog računa (5 redaka bez slike) ostaju u tabu `Radovi`. Najlakše ih
  je ukloniti uklanjanjem testnog računa s testa (caki-testovi → 👥 Objavi → „obriši i rezultat").

---

📌 COMMIT
* Repo: `caki-booking-termina` · grana `main` · mapa `CAKI_razvoj\caki-booking-termina`
* Datoteke: `testovi_v2.py`, `tablice.py`, `definicije.py`, `dodjele.py`, `rjesavanje.py`,
  `drive.py`, `radovi_v2.py`, `ekran_ucenika_v2.py`, `zalbe.py` (novo), `banka.py` (novo),
  `testovi/test_portal_rjesenja_zalbe_radovi.py` (novo), `testovi/fake_gspread.py` (novo),
  `testovi/test_portal_mathlive_i_drive.py`, `upute/UPDATE_23-11_rjesenja_zalbe_radovi.md`
* Poruka: `Moj CAKI: rješenja i žalba nakon zatvaranja testa, slanje rada bez lažnog zapisa`
* Uživo tek nakon **Push** + **Reboot moj-caki**.
