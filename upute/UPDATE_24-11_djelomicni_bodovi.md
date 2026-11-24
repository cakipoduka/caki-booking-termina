# UPDATE 24.11.2026. (3) — djelomični bodovi (kao v1) + uklonjen „Priloži rad"

Caki:
1. „Funkcionalnosti v1 modula ‚Provjera i ispravak ocjena' su veće nego u v2 — mogu se dodijeliti
   djelomični bodovi."
2. „Ukloniti u caki-testovi opciju dodavanja rada ili poveznice — to je u Moj CAKI, profesor ne
   prilaže radove."

## 1. ✏️ Ocjena po zadatku: ostavi · točno · 🟡 djelomično · netočno

Isti izbor kao v1 (`caki-baza-zadataka/provjera_ocjena.py` → „Ispravak po zadatku"):
* **gdje:** 📊 Rezultati → pregled po učeniku, uz svaki zadatak (i kad ocjenjuješ uz radove),
  te u „✏️ Ručna provjera po zadacima", gdje zamjenjuje stari „☐ Točno + Bodovi";
* **obrazac:** „Nova odluka" (— ostavi kako je — / ✅ točno / 🟡 djelomično / ❌ netočno),
  „Bodovi (samo za djelomično)" (korak 0,5, zadano pola), „Komentar (vidi ga učenik)",
  „💾 Spremi ocjenu";
* „ostavi kako je" + novi komentar: mijenja se samo komentar;
* djelomično mora biti **više od 0 i manje od maksimuma** (inače točno/netočno);
* djelomično se zapisuje kao u v1: netočno + upisani bodovi. Trag ide u `Izmjene_ocjena`,
  ukupni bodovi se preračunavaju;
* **prikaz** (profesor i učenik u Moj CAKI): „Zadatak 2 — 🟡 djelomično · 0.5/1 boda" (prije
  „✘ netočno · 0.5/1"). Komentar učenik vidi ispod zadatka.

Kod: `provedba.ocijeni_odlukom()`, `ekran_ucenika.prikazi_ispravak_ocjene()`.

**Napomena:** 📋 Matrica odgovora i dalje boja samo točno (zeleno) i netočno (crveno), pa je
djelomično u njoj crveno.

## 2. Uklonjen „Poveznica na sken / Naziv / 📎 Priloži rad"

Iz pregleda po učeniku u caki-testovi. Profesor radove samo pregledava i potvrđuje (popis,
„✅ Potvrdi pregled", galerija), a prilaže ih učenik u Moj CAKI.

## Testovi

Novo: `testovi/test_djelomicni_bodovi.py` (6, od toga 3 kroz pravo sučelje).
```
caki-testovi           → 201 passed
caki-booking-termina   →  29 passed
```

---

📌 COMMIT
* `caki-testovi` · `main`: `provedba.py`, `ekran_ucenika.py`, `app.py`,
  `testovi/test_djelomicni_bodovi.py` (novo), `upute/UPDATE_24-11_djelomicni_bodovi.md`
* `caki-booking-termina` · `main`: `provedba.py`, `ekran_ucenika_v2.py`,
  `upute/UPDATE_24-11_djelomicni_bodovi.md`
* Poruka: `Djelomični bodovi po zadatku (kao v1); uklonjen Priloži rad u caki-testovi`
* Uživo nakon **Push** oba repoa + **Reboot caki-testovi i moj-caki**.
