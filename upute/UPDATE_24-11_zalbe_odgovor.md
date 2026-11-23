# UPDATE 24.11.2026. — žalba: profesor odgovara jednom i odlučuje o bodovima

Caki:
> Nakon slanja žalbe učenika, ona nigdje nije vidljiva na profesorovom portalu niti postoji
> mogućnost odgovora. […] Samo jednom, bez dugačke rasprave; nakon odgovora traži se odluka o
> bodovima — priznaju se ili ne — i zaključuje se konačno stanje bodova na tom zadatku.
> […] Opcija „Žalba na ocjenu ovog zadatka" nije potrebna na caki-testovi — treba je maknuti.

## Što je bilo

* U pregledu po učeniku (📊 Rezultati) profesor je vidio **učenikov** obrazac „Žalba na ocjenu".
  Pregled je isti ekran kao u Moj CAKI i nije znao tko gleda.
* Odgovor je postojao samo u zatvorenom expanderu „Žalbe na ocjenu" na vrhu Rezultata, i to
  samo sa šiframa (`Z26-…`, `P26-…`). Praktički se nije vidio.
* Nakon odgovora učenik je mogao podnijeti novu žalbu na isti zadatak, a odgovor nije vidio.

## Kako radi sada

**Učenik (Moj CAKI)**, uz svaki zadatak:
* nema žalbe: obrazac (prazna žalba se ne šalje); napomena „jednom po zadatku";
* žalba čeka: njegov tekst + „Čeka odgovor profesora.";
* žalba zaključena: njegov tekst + **odgovor profesora** + **odluka** („bodovi priznati" /
  „bodovi nisu priznati"). Nova žalba na taj zadatak više nije moguća.

**Profesor (caki-testovi → 📊 Rezultati)**
* Na vrhu: žuta obavijest „N žalbi čeka tvoj odgovor" i otvoren popis s imenom učenika, testom,
  rednim brojem zadatka i početkom teksta zadatka.
* U pregledu po učeniku: **nema više obrasca za žalbu**. Uz zadatak sa žalbom stoji učenikov
  tekst i obrazac s:
  1. odgovorom učeniku (obavezno),
  2. odlukom: ✅ Priznajem bodove (n b.) / ❌ Ne priznajem (mora se odabrati),
  3. gumbom „Odgovori i zaključi žalbu".
* Nakon zaključenja stoji samo zapis (žalba, odgovor, odluka, datum). Promjena nije moguća.

**Bodovi:** „priznajem" daje pune bodove tom zadatku (`provedba.ocijeni_rucno`, povod
`zalba`), upisuje trag u `Izmjene_ocjena` i preračunava zbroj pokušaja. „Ne priznajem"
bodove ne dira.

## Kod

* `zalbe.py`: `za_zadatak()`, `je_otvorena()`, `opis_odluke()`, `zakljuci()` (jednom, s
  obaveznim odgovorom). `moze_podnijeti()` odbija svaku drugu žalbu na isti zadatak.
  `podnesi()` odbija praznu žalbu.
* `ekran_ucenika.py`: `prikazi_pregled_rjesenja(..., uloga="ucenik"|"profesor")`, zatim
  `_zalba_ucenik()`, `_zalba_profesor()` i `prikazi_zalbu_profesoru()` (koristi je i popis).
* `app.py`: pregled po učeniku šalje `uloga="profesor"`; novi popis otvorenih žalbi.
* Portal: `zalbe.py` i `ekran_ucenika_v2.py` su osvježene kopije (identične, uz v2 uvoze).

## Testovi

`testovi/test_zalbe_odgovor.py`: 11 testova (7 pravila + 4 AppTesta stvarnog prikaza za
profesora i učenika).
```
caki-testovi           → 173 passed
caki-booking-termina   →  27 passed
```

---

📌 COMMIT
* `caki-testovi` · `main`: `zalbe.py`, `ekran_ucenika.py`, `app.py`,
  `testovi/test_zalbe_odgovor.py`, `upute/UPDATE_24-11_zalbe_odgovor.md`
* `caki-booking-termina` · `main`: `zalbe.py`, `ekran_ucenika_v2.py`,
  `upute/UPDATE_24-11_zalbe_odgovor.md`
* Poruka: `Žalba: profesor jednom odgovara i odlučuje o bodovima; obrazac žalbe samo za učenika`
* Uživo nakon **Push** oba repoa + **Reboot caki-testovi i moj-caki**.
