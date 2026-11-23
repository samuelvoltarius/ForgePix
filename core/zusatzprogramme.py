#!/usr/bin/env python3
"""
core/zusatzprogramme.py — welche fremden Programme ForgePix nutzen kann, ob sie da sind, und wo
man sie herunterlädt.

Keines wird mitgeliefert oder selbst installiert: die Lizenzen erlauben es nicht (GraXpert-,
StarNet-Modelle nicht-kommerziell, StarNet2 und Cosmic Clarity ohne Weitergaberecht) oder es
sind eigene große Programme (N.I.N.A., Siril, PHD2). ForgePix ruft sie nur auf. Die Links führen
auf die offiziellen Seiten — am 23.11.2026 alle mit HTTP 200 erreichbar. Kein Qt.
"""
import os
import shutil
import sys


def _windows(*teile):
    for basis in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                  os.environ.get("LOCALAPPDATA")):
        if basis:
            pfad = os.path.join(basis, *teile)
            if os.path.isfile(pfad):
                return pfad
    return None


def _siril():
    import siril_engine
    return siril_engine.find_siril()


def _graxpert():
    import tools_engine
    return tools_engine.find_graxpert()


def _starnet():
    import tools_engine
    return tools_engine.find_starnet()


def _cosmic():
    import cosmicclarity_engine
    return cosmicclarity_engine.find_cli()


def _astap():
    import astap
    return astap.finden()


def _phd2():
    return (shutil.which("phd2") or _windows("PHDGuiding2", "phd2.exe")
            or ("/Applications/PHD2.app/Contents/MacOS/PHD2" if os.path.isfile("/Applications/PHD2.app/Contents/MacOS/PHD2") else None))


def _nina():
    return _windows("N.I.N.A. - Nighttime Imaging 'N' Astronomy", "NINA.exe")


def _ascom():
    if sys.platform != "win32":
        return None
    for basis in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if basis and os.path.isdir(os.path.join(basis, "ASCOM")):
            return os.path.join(basis, "ASCOM")
    return None


def _indi():
    return shutil.which("indiserver")


def _solve_field():
    return shutil.which("solve-field")


PROGRAMME = [
    # (id, Name, wofür, Download, Finder, Systeme, Hinweis)
    ("astap", "ASTAP", "Plate-Solve, auch blind (ohne bekannte Himmelsposition)",
     "https://www.hnsky.org/astap.htm", _astap, "Windows, macOS, Linux",
     "Dazu eine Sterndatenbank laden: D50 für Bildfelder 0,2–6° (z. B. Seestar)."),
    ("graxpert", "GraXpert", "Hintergrund und Entrauschen mit KI", "https://www.graxpert.com/",
     _graxpert, "Windows, macOS, Linux", ""),
    ("siril", "Siril", "Stapeln, SPCC (Spektralkalibrierung), Skripte", "https://siril.org/download/",
     _siril, "Windows, macOS, Linux", ""),
    ("starnet", "StarNet2", "Sterne entfernen mit KI", "https://starnetastro.com/",
     _starnet, "Windows, macOS, Linux", "Kostenlos, darf aber nicht mitgeliefert werden."),
    ("cosmic", "Cosmic Clarity (SetiAstro)", "Schärfen, Entrauschen mit KI",
     "https://www.setiastro.com/cosmic-clarity", _cosmic, "Windows, macOS, Linux", ""),
    ("phd2", "PHD2", "Nachführung und Dithern", "https://openphdguiding.org/downloads/",
     _phd2, "Windows, macOS, Linux", "Im Programm „Werkzeuge → Server aktivieren“ einschalten."),
    ("nina", "N.I.N.A.", "Aufnahme fernsteuern (über das Plugin „Advanced API“)",
     "https://nighttime-imaging.eu/download/", _nina, "nur Windows",
     "Das Plugin „Advanced API“ in N.I.N.A. unter Plugins installieren."),
    ("ascom", "ASCOM Platform", "Gerätetreiber unter Windows (mit „ASCOM Remote“ als Alpaca)",
     "https://ascom-standards.org/Downloads/Index.htm", _ascom, "nur Windows", ""),
    ("indi", "INDI", "Gerätetreiber unter Linux und macOS (indiserver)",
     "https://www.indilib.org/download.html", _indi, "Linux, macOS", ""),
    ("gpr", "GoPro GPR-Werkzeuge (gpr_tools)", "GoPro-RAW (.gpr) in DNG umwandeln",
     "https://github.com/gopro/gpr", lambda: shutil.which("gpr_tools"), "Windows, macOS, Linux (selbst bauen)",
     "Frei (MIT/Apache). Die eingebaute RAW-Bibliothek liest .gpr nicht."),
    ("astrometry", "astrometry.net", "Plate-Solve blind, als Alternative zu ASTAP",
     "https://astrometry.net/use.html", _solve_field, "Linux, macOS (Windows über WSL)", ""),
]


def stand():
    """Liste von Dicts: id, name, wofuer, url, systeme, hinweis, pfad (None = nicht gefunden)."""
    aus = []
    for pid, name, wofuer, url, finder, systeme, hinweis in PROGRAMME:
        try:
            pfad = finder()
        except Exception:                                # Suche ist nur ein Hinweis
            pfad = None
        aus.append({"id": pid, "name": name, "wofuer": wofuer, "url": url, "systeme": systeme,
                    "hinweis": hinweis, "pfad": pfad})
    return aus


def link(pid):
    for p in PROGRAMME:
        if p[0] == pid:
            return p[3]
    raise KeyError(pid)
