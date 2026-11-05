"""
CAKI testovi v2 — `ai_pomoc.py`
💡 POMOĆ TIJEKOM RJEŠAVANJA (bot „kao profesor") — **nikad ne daje konačno rješenje**.

Pravila (Cakijeva odluka 24.10.2026.):
  · bot pomaže razumjeti zadatak, ne rješava ga umjesto učenika,
  · ograničen broj pitanja po zadatku (zadano 3) — sprječava prepisivanje dijaloga,
  · ako AI nije dostupan, učenik i dalje može rješavati (pomoć je dodatak, ne uvjet).

Tajna: `DEEPSEEK_API_KEY` (primarno) ili `ANTHROPIC_API_KEY`.
"""
from __future__ import annotations

import json

import model

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MAX_PITANJA = 3

PRAVILA = (
    "Ti si profesor matematike koji pomaže učeniku srednje škole tijekom testa.\n"
    "STROGA PRAVILA:\n"
    "1. NIKAD ne reci konačan odgovor ni broj koji je rješenje.\n"
    "2. Ne rješavaj zadatak do kraja — daj putokaz, pitanje ili podsjetnik na formulu.\n"
    "3. Najviše 3 rečenice. Bez predgovora i bez ponavljanja zadatka.\n"
    "4. Piši hrvatski, jednostavno, kao da objašnjavaš učeniku koji je zapeo.\n"
    "5. Ako učenik traži rješenje, odbij i ponudi prvi korak.\n"
)


# ------------------------------------------------------------------ dostupnost

def ima_kljuc(secrets) -> str:
    """Vrati koji je ključ dostupan (`deepseek`, `anthropic` ili prazno)."""
    try:
        if model.tekst(secrets.get("DEEPSEEK_API_KEY")):
            return "deepseek"
        if model.tekst(secrets.get("ANTHROPIC_API_KEY")):
            return "anthropic"
    except Exception:                                  # noqa: BLE001
        return ""
    return ""


def moze_jos_pitanja(postojeci: int, maks: int = MAX_PITANJA) -> bool:
    return int(postojeci or 0) < int(maks)


def tekst_ogranicenja(postojeci: int, maks: int = MAX_PITANJA) -> str:
    ostalo = max(0, int(maks) - int(postojeci or 0))
    if ostalo == 0:
        return "Iskoristio si sva pitanja za ovaj zadatak."
    return f"Još {ostalo} " + ("pitanje" if ostalo == 1 else "pitanja") + " za ovaj zadatak."


# ------------------------------------------------------------------ upit

def sastavi_upit(zadatak: dict, pitanje: str, razina: str = "") -> list[dict]:
    """Poruke za AI: pravila + zadatak (bez točnog odgovora!) + pitanje učenika."""
    tekst = model.tekst((zadatak or {}).get("tekst"))
    cjelina = model.tekst((zadatak or {}).get("cjelina"))
    dodatak = f"\nUčenikova razina: {razina}." if model.tekst(razina) else ""
    sadrzaj = (
        f"ZADATAK (ne daj rješenje):\n{tekst}\n"
        + (f"Cjelina: {cjelina}\n" if cjelina else "")
        + f"{dodatak}\nPITANJE UČENIKA:\n{model.tekst(pitanje)}"
    )
    return [{"role": "system", "content": PRAVILA}, {"role": "user", "content": sadrzaj}]


def _odgovor_iz_json(podaci) -> str:
    """Izvuci tekst iz odgovora DeepSeeka ili Anthropica."""
    if not isinstance(podaci, dict):
        return ""
    izbori = podaci.get("choices")
    if isinstance(izbori, list) and izbori:
        poruka = (izbori[0] or {}).get("message") or {}
        if model.tekst(poruka.get("content")):
            return model.tekst(poruka["content"])
    dijelovi = podaci.get("content")
    if isinstance(dijelovi, list):
        return " ".join(model.tekst(d.get("text")) for d in dijelovi if isinstance(d, dict)).strip()
    return ""


def pitaj(poruke: list[dict], *, kljuc: str, tajna: str, timeout: int = 30,
          post=None) -> tuple[str, str]:
    """Pošalji upit AI-ju. Vraća (odgovor, greška). `post` je injektabilan za testove."""
    if not model.tekst(tajna):
        return "", "AI pomoć nije uključena (nema ključa u Secrets)."
    if post is None:                                   # stvarni poziv
        import requests

        def post(url, **kwargs):                       # noqa: ANN001
            return requests.post(url, timeout=timeout, **kwargs)

    try:
        if kljuc == "anthropic":
            r = post(ANTHROPIC_URL, headers={
                "x-api-key": tajna, "anthropic-version": "2023-06-01",
                "content-type": "application/json"},
                data=json.dumps({
                    "model": "claude-3-5-haiku-latest", "max_tokens": 300,
                    "system": PRAVILA,
                    "messages": [{"role": "user", "content": poruke[-1]["content"]}],
                }).encode("utf-8"))
        else:
            r = post(DEEPSEEK_URL, headers={
                "Authorization": f"Bearer {tajna}", "Content-Type": "application/json"},
                data=json.dumps({"model": "deepseek-chat", "messages": poruke,
                                 "max_tokens": 300, "temperature": 0.3}).encode("utf-8"))
        if getattr(r, "status_code", 0) != 200:
            return "", f"AI trenutno ne odgovara (HTTP {getattr(r, 'status_code', '?')})."
        return _odgovor_iz_json(r.json()), ""
    except Exception as e:                             # noqa: BLE001
        return "", f"AI trenutno ne odgovara: {type(e).__name__}."


# ------------------------------------------------------------------ sučelje

def prikazi_pomoc(st, zadatak: dict, *, kljuc_testa: str, secrets, maks: int = MAX_PITANJA) -> None:
    """Sklopivi blok 💡 pomoći uz zadatak. Bez ključa samo kratka napomena (ništa se ne ruši)."""
    k_broj = f"v2ai_broj_{kljuc_testa}"
    k_povijest = f"v2ai_pov_{kljuc_testa}"
    st.session_state.setdefault(k_broj, 0)
    st.session_state.setdefault(k_povijest, [])

    with st.expander("💡 Trebaš pomoć? (bot ne daje rješenje)"):
        vrsta = ima_kljuc(secrets)
        if not vrsta:
            st.caption("Pomoć trenutno nije uključena.")
            return
        st.caption("Bot ti pomaže razumjeti zadatak — **nikad ne kaže konačan odgovor**. "
                   + tekst_ogranicenja(st.session_state[k_broj], maks))

        for red in st.session_state[k_povijest]:
            st.markdown(f"**Ti:** {red['pitanje']}")
            st.markdown(f"**Pomoć:** {red['odgovor']}")

        if not moze_jos_pitanja(st.session_state[k_broj], maks):
            return
        pitanje = st.text_input("Tvoje pitanje", key=f"v2ai_upit_{kljuc_testa}",
                                placeholder="npr. ne znam kako početi")
        if st.button("Pošalji", key=f"v2ai_posalji_{kljuc_testa}", disabled=not model.tekst(pitanje)):
            odgovor, greska = pitaj(sastavi_upit(zadatak, pitanje), kljuc=vrsta,
                                    tajna=model.tekst(secrets.get(
                                        "DEEPSEEK_API_KEY" if vrsta == "deepseek" else "ANTHROPIC_API_KEY")))
            if greska:
                st.warning(greska)
            elif odgovor:
                st.session_state[k_broj] += 1
                st.session_state[k_povijest].append({"pitanje": model.tekst(pitanje),
                                                     "odgovor": odgovor})
                st.rerun()
