#!/usr/bin/env python3
"""
einrichten.py — ForgePix aus dem Quellcode einrichten, auf Windows, macOS und Linux.

    python3 einrichten.py            einrichten (oder prüfen und ergänzen)
    python3 einrichten.py --pruefen  nur prüfen, nichts installieren

Was passiert:
  1. Python-Version prüfen (3.10 bis 3.14; mit 3.12 laufen die automatischen Tests).
  2. Eine eigene Umgebung `.venv` im Programmordner anlegen — nichts landet im System-Python.
  3. Die Pakete aus requirements.txt hineininstallieren. Scheitert die Sammelinstallation,
     wird Paket für Paket nachinstalliert und am Ende gesagt, WELCHES fehlt und ob das
     Programm trotzdem startet.
  4. Prüfen, dass die Oberfläche wirklich hochkommt (unter Linux fehlt dafür oft eine
     Systembibliothek; dann steht hier der passende Installationsbefehl).
  5. Optionale Programme (Siril, GraXpert, StarNet, ASTAP) suchen und nur MELDEN.

Die Start-Skripte (run.sh, run.bat, ForgePix.app) rufen das hier beim ersten Start und nach
jeder Änderung an requirements.txt selbst auf. Nur Standardbibliothek.

Bis 22.11.2026 zeigte run.sh fest auf `/Library/Frameworks/Python.framework/Versions/3.13/`
— das gibt es nur auf einem bestimmten Mac. Unter Linux und auf jedem anderen Mac startete
ForgePix darum gar nicht, und run.bat installierte nie Pakete.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
VENV = os.path.join(HIER, ".venv")
MARKE = "forgepix_eingerichtet.txt"
MIN, MAX = (3, 10), (3, 14)

# Ohne diese startet das Programm nicht; alles andere schaltet nur einzelne Funktionen ab.
PFLICHT = {"PySide6": "PySide6", "cv2": "opencv-python-headless", "numpy": "numpy"}
FUNKTIONEN = {
    "rawpy": "RAW-Fotos", "tifffile": "TIFF lesen/schreiben", "imagecodecs": "komprimierte TIFF",
    "astropy": "FITS (Astro)", "scipy": "Mosaik und Feinregistrierung", "PIL": "Daumenkino, EXIF",
    "exifread": "EXIF lesen", "piexif": "EXIF schreiben", "psdtags": "Photoshop-Ebenen",
    "requests": "KI-Server", "onnxruntime": "eigene KI-Modelle",
    "astroquery": "Gaia-Abfrage (optional)", "lensfunpy": "Objektivkorrektur (optional)",
}
EXTERN = {"siril-cli": "Siril", "siril": "Siril", "GraXpert": "GraXpert", "graxpert": "GraXpert",
          "starnet++": "StarNet++", "starnet2": "StarNet++", "astap": "ASTAP (Plate-Solve)"}


def melden(text=""):
    print(text, flush=True)


def venv_python(venv=VENV):
    if os.name == "nt":
        return os.path.join(venv, "Scripts", "python.exe")
    return os.path.join(venv, "bin", "python")


def anforderungen_hash():
    h = hashlib.sha256()
    for name in ("requirements.txt", "requirements-core.txt"):
        pfad = os.path.join(HIER, name)
        if os.path.exists(pfad):
            with open(pfad, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()[:16]


def ist_eingerichtet(venv=VENV):
    """True, wenn .venv da ist UND zu den aktuellen requirements passt."""
    marke = os.path.join(venv, MARKE)
    if not (os.path.exists(venv_python(venv)) and os.path.exists(marke)):
        return False
    with open(marke, encoding="utf-8") as fh:
        return fh.read().strip() == anforderungen_hash()


def version_pruefen(version=None):
    """(ok, text). Zu alt ist ein Fehler; neuer als getestet nur ein Hinweis."""
    v = tuple(version or sys.version_info[:2])
    if v < MIN:
        return False, ("Python %d.%d ist zu alt. ForgePix braucht mindestens %d.%d — bitte "
                       "von python.org installieren." % (v + MIN))
    if v > MAX:
        return True, ("Python %d.%d ist neuer als getestet (bis %d.%d). Falls ein Paket sich "
                      "nicht installieren lässt, Python %d.%d nehmen." % (v + MAX + MAX))
    return True, "Python %d.%d — passt." % v


def pakete_aus(datei):
    """Paketzeilen aus einer requirements-Datei, -r folgend, Kommentare weg."""
    zeilen = []
    with open(os.path.join(HIER, datei), encoding="utf-8") as fh:
        for zeile in fh:
            zeile = zeile.split("#", 1)[0].strip()
            if not zeile:
                continue
            if zeile.startswith("-r "):
                zeilen += pakete_aus(zeile[3:].strip())
            else:
                zeilen.append(zeile)
    return zeilen


def _pip(python, *args):
    return subprocess.call([python, "-m", "pip", "--disable-pip-version-check", *args])


def installieren(python):
    """Sammelinstallation; bei Fehlschlag Paket für Paket. Gibt die gescheiterten zurück."""
    _pip(python, "install", "--upgrade", "pip")
    if _pip(python, "install", "-r", os.path.join(HIER, "requirements.txt")) == 0:
        return []
    melden("\nDie Sammelinstallation ist gescheitert — jetzt Paket für Paket, um das "
           "fehlende zu finden.")
    gescheitert = []
    for paket in pakete_aus("requirements.txt"):
        if _pip(python, "install", paket) != 0:
            gescheitert.append(paket)
    return gescheitert


_PRUEF_SKRIPT = r"""
import importlib, json, sys
pflicht, funktionen = json.loads(sys.argv[1])
fehlt = {}
for modul in list(pflicht) + list(funktionen):
    try:
        importlib.import_module(modul)
    except Exception as e:
        fehlt[modul] = "%s: %s" % (type(e).__name__, e)
print(json.dumps(fehlt))
"""


def module_pruefen(python):
    import json
    aus = subprocess.run([python, "-c", _PRUEF_SKRIPT, json.dumps([list(PFLICHT), list(FUNKTIONEN)])],
                         capture_output=True, text=True)
    if aus.returncode != 0:
        return {"(Python)": aus.stderr.strip()[-300:]}
    return json.loads(aus.stdout.strip().splitlines()[-1])


_GUI_SKRIPT = "from PySide6.QtWidgets import QApplication; a = QApplication([]); print('ok')"


def oberflaeche_pruefen(python):
    """Kommt Qt wirklich hoch? Unter Linux fehlt oft libxcb-cursor0 — PySide6 installiert sich
    dann fehlerfrei und scheitert erst beim Start mit „could not load the Qt platform plugin“."""
    umgebung = dict(os.environ)
    if sys.platform.startswith("linux") and not (umgebung.get("DISPLAY") or umgebung.get("WAYLAND_DISPLAY")):
        umgebung["QT_QPA_PLATFORM"] = "offscreen"     # kein Bildschirm: nur das Laden prüfen
    aus = subprocess.run([python, "-c", _GUI_SKRIPT], capture_output=True, text=True, env=umgebung,
                         timeout=120)
    if aus.returncode == 0 and "ok" in aus.stdout:
        return True, "Oberfläche startet."
    text = (aus.stderr or aus.stdout).strip()
    rat = ""
    if sys.platform.startswith("linux") and ("xcb" in text or "platform plugin" in text):
        rat = ("\n  Unter Linux fehlt meist eine Qt-Systembibliothek:\n"
               "    Debian/Ubuntu:  sudo apt install libxcb-cursor0 libegl1 libxkbcommon-x11-0\n"
               "    Fedora:         sudo dnf install xcb-util-cursor libxkbcommon-x11\n"
               "    Arch:           sudo pacman -S xcb-util-cursor")
    return False, "Oberfläche startet NICHT:\n  " + text[-600:] + rat


def extern_suchen():
    """Dieselbe Suche, die ForgePix beim Arbeiten benutzt (kennt die üblichen
    Installationsordner), dann der Suchpfad. Nur melden, nie installieren."""
    gefunden = {}
    sys.path.insert(0, os.path.join(HIER, "core"))
    try:
        import siril_engine
        import tools_engine
        for name, finder in (("Siril", siril_engine.find_siril), ("GraXpert", tools_engine.find_graxpert),
                             ("StarNet++", tools_engine.find_starnet)):
            try:
                pfad = finder()
            except Exception:                            # Suche ist nur ein Hinweis
                pfad = None
            if pfad:
                gefunden[name] = pfad
    except ImportError:                                  # core braucht numpy — vor der Installation
        pass
    finally:
        sys.path.pop(0)
    for befehl, name in EXTERN.items():
        if name in gefunden:
            continue
        pfad = shutil.which(befehl)
        if pfad and name not in gefunden:
            gefunden[name] = pfad
    return gefunden


def main(argv=None):
    ap = argparse.ArgumentParser(description="ForgePix einrichten (Windows, macOS, Linux)")
    ap.add_argument("--pruefen", action="store_true", help="nur prüfen, nichts installieren")
    ap.add_argument("--venv", default=VENV, help="Ort der eigenen Umgebung (Vorgabe: .venv)")
    ap.add_argument("--still", action="store_true",
                    help="nur ausgeben, wenn etwas fehlt (für die Start-Skripte)")
    args = ap.parse_args(argv)

    ok, text = version_pruefen()
    melden(text)
    if not ok:
        return 2
    venv = os.path.abspath(args.venv)
    python = venv_python(venv)
    if args.pruefen:
        python = python if os.path.exists(python) else sys.executable
    else:
        if not os.path.exists(python):
            melden("Lege die eigene Umgebung an: %s" % venv)
            if subprocess.call([sys.executable, "-m", "venv", venv]) != 0:
                melden("Konnte keine Umgebung anlegen. Unter Debian/Ubuntu fehlt oft das Paket "
                       "„python3-venv“:  sudo apt install python3-venv")
                return 3
        gescheitert = installieren(python)
        if gescheitert:
            melden("\nNicht installierbar: " + ", ".join(gescheitert))

    fehlt = module_pruefen(python)
    pflicht_fehlt = [m for m in PFLICHT if m in fehlt]
    for modul, grund in fehlt.items():
        rolle = "PFLICHT" if modul in PFLICHT else FUNKTIONEN.get(modul, "")
        melden("  fehlt: %-12s (%s) — %s" % (modul, rolle, grund[:160]))
    if pflicht_fehlt:
        melden("\nForgePix kann ohne %s nicht starten." % ", ".join(pflicht_fehlt))
        return 4
    gui_ok, gui_text = oberflaeche_pruefen(python)
    melden(gui_text)
    extern = extern_suchen()
    if not args.still:
        melden("\nOptionale Programme (werden nie automatisch installiert):")
        for name in sorted(set(EXTERN.values())):
            melden("  %-22s %s" % (name, extern.get(name, "nicht gefunden — optional")))
    if not gui_ok:
        return 5
    if not args.pruefen:
        with open(os.path.join(venv, MARKE), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(anforderungen_hash() + "\n")
    melden("\nFertig. %s" % ("Alle Funktionen verfügbar." if not fehlt else
                             "Einzelne Funktionen fehlen (siehe oben), der Rest läuft."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
