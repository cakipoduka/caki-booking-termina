# UPDATE 23.11.2026. — Moj CAKI: MathLive u v2 testovima + slanje rada u Drive

Isti popravak kao `caki-testovi/upute/UPDATE_21-11_mathlive_i_drive.md`, prenesen u portal.
Učenici v2 testove rješavaju **samo ovdje** (odluka 05.11.2026.), pa popravak u `caki-testovi`
učenicima nije ništa promijenio. Caki 23.11.: „Učenici ne vide MathLive — NISU VIDLJIVE".

## Što je bilo

| Datoteka | Tko je koristi | Greška |
|---|---|---|
| `unos_odgovora.py` | v2 testovi (`ekran_ucenika_v2.py`) | `mathfield(default_mode=…, height=…)`. Verzija 0.0.3 te argumente ne prima, pa nastaje `TypeError`, tihi fallback i učenik nikad ne vidi editor. Uz to `str([latex, mathml])` bi se spremao kao odgovor |
| `drive.py` | v2 „📷 Priloži svoj rad" (`testovi_v2.py`) | scope `drive.file` ne smije pisati u ručno napravljenu mapu `02_Radovi_ucenika`, pa nastaje poruka „Fotografija trenutno nije poslana na Drive…". Greška je glasila samo `HttpError` |
| `kratki_odgovor_unos.py` | v1 testovi (`testovi_online.py`) | **nije pokvaren**: zove `mathfield(title, value, key)`, što 0.0.3 prima. Nije diran |

## Što je napravljeno

* `unos_odgovora.py` i `drive.py` zamijenjeni ispravljenim verzijama iz `caki-testovi`
  (sadržaj identičan, da se kopije ne raziđu).
* Novo: `testovi/test_portal_mathlive_i_drive.py`, **19 testova, svi prolaze** na portalovom kodu.
  Ime je drukčije nego u `caki-testovi` namjerno, jer dvije test-datoteke istog imena ruše pytest
  kad se pokreće iz `CAKI_razvoj`.
* Provjereno u pravom Streamlitu (AppTest) sa stvarnim paketom `streamlit-mathlive` 0.0.3:
  nema tekstualnog polja, a postojeći odgovor `x=3` ostaje.

## Ručno (Caki)

1. Push `caki-booking-termina`, pa **Reboot aplikacije moj-caki** na Streamlit Cloudu.
2. Servisni račun portala mora biti član dijeljenog diska s mapom `02_Radovi_ucenika`
   (uloga *Contributor* ili jača), a `RADOVI_FOLDER_ID` u Secrets portala mora biti ID te mape.
   Ako slanje i dalje ne uspije, „Tehnički detalj (za Cakija)" ispod poruke sada piše točan razlog
   (`notFound`, `storageQuotaExceeded`, `insufficientFilePermissions` …).

## Otvoreno

* Portal ima **kopije** 15 modula iz `caki-testovi` (v. zaglavlje `testovi_v2.py`). Ova greška je
  nastala upravo zato: ispravak u jednoj kopiji ne stiže u drugu. Dugoročno rješenje je jedan izvor
  (v. raspravu 23.11. o pristupu testovima).
* `pyflakes`: `ekran_ucenika_v2.py:320` (`_traka` definiran dvaput), bezopasno, od prije.

---

📌 COMMIT
* Repo: `caki-booking-termina` · grana `main` · mapa `CAKI_razvoj\caki-booking-termina`
* Datoteke: `unos_odgovora.py`, `drive.py`, `testovi/test_portal_mathlive_i_drive.py`,
  `upute/UPDATE_23-11_mathlive_i_drive.md`
* Poruka: `Moj CAKI: MathLive u v2 testovima + upload rada u Drive (scope, razlog greške)`
* Uživo tek nakon **Push** + **Reboot moj-caki**.
