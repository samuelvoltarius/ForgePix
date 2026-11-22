@echo off
rem ForgePix starten (Windows). Beim ersten Start und nach jeder Aenderung an
rem requirements.txt richtet einrichten.py die eigene Umgebung .venv ein.
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
    echo Kein Python gefunden. Bitte Python 3.12 von python.org installieren
    echo ^(beim Installieren "Add python.exe to PATH" ankreuzen^).
    pause
    exit /b 1
)

%PY% -c "import einrichten, sys; sys.exit(0 if einrichten.ist_eingerichtet() else 1)" 2>nul
if errorlevel 1 (
    echo ForgePix wird eingerichtet ^(nur beim ersten Start oder nach einem Update^) ...
    %PY% einrichten.py
    if errorlevel 1 (
        echo Einrichtung gescheitert - siehe oben.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" focus_stack_gui.py %*
