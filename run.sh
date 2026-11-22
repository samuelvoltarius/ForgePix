#!/usr/bin/env bash
# ForgePix starten (macOS / Linux). Beim ersten Start und nach jeder Änderung an
# requirements.txt richtet einrichten.py die eigene Umgebung .venv ein.
cd "$(dirname "$0")" || exit 1

# Aus dem Finder gestartet sieht ein Programm nur /usr/bin:/bin — dort liegt höchstens Apples
# Platzhalter-python3. python.org und Homebrew installieren woanders hin.
if [ "$(uname)" = "Darwin" ]; then
    PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/Current/bin:$PATH"
fi

PY=""
for kandidat in python3.12 python3.13 python3.14 python3.11 python3.10 python3 python; do
    if command -v "$kandidat" >/dev/null 2>&1; then
        PY="$(command -v "$kandidat")"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "Kein Python gefunden. Bitte Python 3.12 installieren (python.org oder Paketverwaltung)." >&2
    exit 1
fi

VPY=".venv/bin/python"
if ! "$PY" -c "import einrichten, sys; sys.exit(0 if einrichten.ist_eingerichtet() else 1)" 2>/dev/null; then
    echo "ForgePix wird eingerichtet (nur beim ersten Start oder nach einem Update) ..."
    "$PY" einrichten.py || { echo "Einrichtung gescheitert — siehe oben." >&2; exit 1; }
fi
exec "$VPY" focus_stack_gui.py "$@"
