#!/usr/bin/env python3
"""
i18n.py — winzige Mehrsprachigkeit für ForgePix.

Prinzip: der deutsche Text IST der Schlüssel. `tr("Starten")` gibt in der aktiven
Sprache die Übersetzung zurück; fehlt sie, kommt der deutsche Text.

Sprachen liegen als JSON in `lang/<code>.json` ( {"Deutscher Text": "Translation", ...} ).
Eigene Sprache hinzufügen: `lang/de.json` kopieren, Werte übersetzen, Datei z.B.
`lang/fr.json` nennen — taucht automatisch in der Sprachauswahl auf.
"""
import json
import os

_d = os.path.dirname(os.path.abspath(__file__))
# lang/ liegt im gebündelten Binary neben i18n (_MEIPASS/lang), im Quellcode im Projekt-Root
# (i18n.py liegt jetzt in core/ → ein Verzeichnis höher).
_LANG_DIR = os.path.join(_d, "lang")
if not os.path.isdir(_LANG_DIR):
    _LANG_DIR = os.path.join(os.path.dirname(_d), "lang")
_current = "de"
_table = {}
_warned = set()                     # je Sprachdatei nur EINMAL warnen


def available_languages():
    """Liste (code, Anzeigename) aller vorhandenen Sprachdateien."""
    names = {"de": "Deutsch", "en": "English", "fr": "Français", "es": "Español",
             "it": "Italiano"}
    out = []
    if os.path.isdir(_LANG_DIR):
        for f in sorted(os.listdir(_LANG_DIR)):
            if f.endswith(".json"):
                code = f[:-5]
                out.append((code, names.get(code, code.upper())))
    return out or [("de", "Deutsch")]


def set_language(code):
    global _current, _table
    _current = code or "de"
    _table = {}
    path = os.path.join(_LANG_DIR, f"{_current}.json")
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                _table = json.load(fh)
        except Exception as e:      # kaputte Sprachdatei nicht still schlucken — einmalig warnen
            if path not in _warned:
                print(f"i18n: Sprachdatei {path} nicht lesbar ({e}) — Fallback auf Deutsch")
                _warned.add(path)
            _table = {}


def current_language():
    return _current


def tr(text):
    """Deutschen Text in die aktive Sprache übersetzen (Fallback: deutscher Text)."""
    if _current == "de":
        return text
    return _table.get(text, text)
