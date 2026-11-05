"""
CAKI testovi v2 — `tabele.py`
📊 TABLICE U ZADACIMA — podaci zadani tablično (vjerojatnost, statistika, histogrami…) prikazuju se
kao **prava tablica**, a ne kao sirovi `| a | b |` (Cakijeva prijava 29.10.2026.).

Claude je isto riješio za **PDF skriptu** (PreTeXt `<tabular>`, `baza_zadataka_pipeline.py`,
TRACKER 29.10.). Ovo je isti posao za **v2**: web prikaz (Streamlit) i **v2 PDF** (LaTeX tabular).

Format u bazi: Markdown **pipe tablica**:

    | Razred | Frekvencija |
    |---|---|
    | 1 | 5 |
    | 2 | 8 |

Ključna zaštita: zadatak **bez tablice** mora dati **znak za znak isti** izlaz kao prije.
"""
from __future__ import annotations

import model

# Pravilo iz Claudeovog rješenja: crta za zaglavlje = red sa SAMO `---`/`:--:` ćelijama
_SEPARATOR = set("|:- ")


def _je_separator(redak: str) -> bool:
    s = model.tekst(redak).strip()
    return bool(s) and "|" in s and set(s) <= _SEPARATOR and "-" in s


def _celije(redak: str) -> list[str]:
    """Podijeli redak na ćelije; `\\|` je escapeano (ostaje u ćeliji)."""
    s = model.tekst(redak).strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    celije, trenutna, i = [], "", 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            trenutna += "|"
            i += 2
            continue
        if s[i] == "|":
            celije.append(trenutna.strip())
            trenutna = ""
        else:
            trenutna += s[i]
        i += 1
    celije.append(trenutna.strip())
    return celije


def pronadji_tabele(tekst) -> list[dict]:
    """Vrati [{od, do, redci}] — svaka pipe tablica u tekstu (indeksi redaka u `tekst`)."""
    linije = model.tekst(tekst).split("\n")
    tabele = []
    i = 0
    while i < len(linije):
        # tablica = barem 3 retka: zaglavlje, separator, jedan redak podataka
        if ("|" in linije[i] and i + 2 < len(linije)
                and _je_separator(linije[i + 1]) and "|" in linije[i + 2]):
            pocetak = i
            redci = [_celije(linije[i])]
            i += 2                                        # preskoči separator
            while i < len(linije) and "|" in linije[i] and not _je_separator(linije[i]):
                redci.append(_celije(linije[i]))
                i += 1
            sirina = max(len(r) for r in redci)
            redci = [r + [""] * (sirina - len(r)) for r in redci]
            tabele.append({"od": pocetak, "do": i - 1, "redci": redci})
            continue
        i += 1
    return tabele


def ima_tabelu(tekst) -> bool:
    return bool(pronadji_tabele(tekst))


# ------------------------------------------------------------------ web (Streamlit)

def html_tabela(redci: list[list[str]], *, zaglavlje: bool = True) -> str:
    """HTML tablica s Cakijevim bojama (brend) — čitljiva i na mobitelu."""
    if not redci:
        return ""
    dijelovi = ['<table style="border-collapse:collapse;margin:6px 0;font-size:0.95em;">']
    for broj, red in enumerate(redci):
        je_zag = zaglavlje and broj == 0
        oznaka = "th" if je_zag else "td"
        stil = ("padding:4px 10px;border:1px solid #c9c9c9;"
                + ("background:#f3ede4;font-weight:600;" if je_zag else ""))
        celije = "".join(f'<{oznaka} style="{stil}">{model.tekst(c)}</{oznaka}>' for c in red)
        dijelovi.append(f"<tr>{celije}</tr>")
    dijelovi.append("</table>")
    return "".join(dijelovi)


def podijeli(tekst) -> list[dict]:
    """Podijeli tekst na dijelove: {"tip": "tekst"|"tabela", "sadrzaj"} — za prikaz u Streamlitu."""
    linije = model.tekst(tekst).split("\n")
    tabele = pronadji_tabele(tekst)
    if not tabele:
        return [{"tip": "tekst", "sadrzaj": model.tekst(tekst)}]

    dijelovi, i = [], 0
    po_pocetku = {t["od"]: t for t in tabele}
    while i < len(linije):
        if i in po_pocetku:
            t = po_pocetku[i]
            if t["redci"]:
                dijelovi.append({"tip": "tabela", "sadrzaj": t["redci"]})
            i = t["do"] + 1
            continue
        dijelovi.append({"tip": "tekst", "sadrzaj": linije[i]})
        i += 1
    return _spoji_tekst(dijelovi)


def _spoji_tekst(dijelovi: list[dict]) -> list[dict]:
    izlaz = []
    for dio in dijelovi:
        if (dio["tip"] == "tekst" and izlaz and izlaz[-1]["tip"] == "tekst"):
            izlaz[-1]["sadrzaj"] += "\n" + dio["sadrzaj"]
        elif dio["tip"] == "tekst" and not model.tekst(dio["sadrzaj"]).strip():
            continue
        else:
            izlaz.append(dio)
    return izlaz


# ------------------------------------------------------------------ PDF (LaTeX)

def latex_tabela(redci: list[list[str]], *, escape=None) -> str:
    """LaTeX `tabular` s tri crte (booktabs stil) — isto kao Claudeovo `<tabular booktabs>`.

    Ćelije: kratki brojevi i izrazi u `$…$`, riječi ostaju običan tekst (inače hrvatska slova
    ispadnu iz matematičkog fonta — Claudeov nalaz 29.10.: „Missing character: There is no ž").
    """
    if not redci:
        return ""
    if escape is None:
        def escape(s):
            return s

    sirina = max(len(r) for r in redci)
    zag = " ".join(["c"] * sirina)
    dijelovi = [r"\begin{center}\begin{tabular}{" + zag + "}", r"\toprule"]
    for broj, red in enumerate(redci):
        celije = []
        for c in red:
            celije.append(_celija_tex(c, escape))
        dijelovi.append(" & ".join(celije) + r" \\")
        if broj == 0:
            dijelovi.append(r"\midrule")
    dijelovi += [r"\bottomrule", r"\end{tabular}\end{center}"]
    return "\n".join(dijelovi)


def _celija_tex(celija, escape) -> str:
    """Broj/izraz → matematika; riječ s hrvatskim slovima → običan tekst."""
    s = model.tekst(celija)
    if not s:
        return ""
    if "$" in s:
        return escape(s)
    import re

    if re.fullmatch(r"[-+]?\d+([.,]\d+)?", s):
        return f"${s.replace(',', '{,}')}$"
    if re.fullmatch(r"[A-Za-z0-9\s+\-*/^().=<>%,]+", s) and re.search(r"[A-Za-z]", s):
        # sadrži slovo — ako ima hrvatskih slova ili više riječi, običan tekst
        if re.search(r"[čćžšđČĆŽŠĐ]", s):
            return escape(s)
    return escape(s)


def zamijeni_u_tekstu(tekst, escape=None) -> str:
    """Zamijeni pipe tablice LaTeX tabularom; tekst bez tablice vraća **nepromijenjen**."""
    if not ima_tabelu(tekst):
        return tekst
    dijelovi = podijeli(tekst)
    izlaz = []
    for dio in dijelovi:
        if dio["tip"] == "tabela":
            izlaz.append(latex_tabela(dio["sadrzaj"], escape=escape))
        else:
            izlaz.append(dio["sadrzaj"])
    return "\n".join(izlaz)
