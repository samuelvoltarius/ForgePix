#!/usr/bin/env python3
"""
core/nina.py — ein vorhandenes N.I.N.A. fernsteuern, über das Plugin „Advanced API“.

Das ist die BRÜCKE, nicht der Ersatz: wer N.I.N.A. am Teleskop schon benutzt, steuert es von
ForgePix aus (Windows, macOS, Linux — N.I.N.A. selbst läuft nur unter Windows, das Plugin
stellt es aber ins Netz). Die eigene Gerätesteuerung ohne N.I.N.A. steht in `alpaca.py`
und `aufnahme.py`.

Adressen und Abfrageparameter stammen aus dem installierten Plugin (ninaAPI.dll 2.2.15.2),
die Antwortform aus Abfragen gegen ein laufendes N.I.N.A. 3.2.0.9001 (22.11.2026):

    {"Response": ..., "Error": "", "StatusCode": 200, "Success": true, "Type": "API"}

`Success: false` wird IMMER zum Fehler mit dem Text aus `Error`. Kein Qt.
"""
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

STANDARD_PORT = 1888

# Die Geräte, die `/equipment/info` meldet, und ihr Pfadname für connect/disconnect/rescan.
GERAETE = {
    "Camera": "camera", "FilterWheel": "filterwheel", "Focuser": "focuser",
    "Mount": "mount", "Guider": "guider", "Rotator": "rotator", "Dome": "dome",
    "FlatDevice": "flatdevice", "Switch": "switch", "SafetyMonitor": "safetymonitor",
    "WeatherData": "weather",
}

_FITS_ANFANG = b"SIMPLE  ="


class NinaFehler(Exception):
    """N.I.N.A. ist nicht erreichbar oder hat eine Anfrage abgelehnt."""


class Nina:
    """Eine Verbindung zu einem laufenden N.I.N.A. mit aktivierter Advanced API."""

    def __init__(self, host="127.0.0.1", port=STANDARD_PORT, timeout=15.0):
        self.host = str(host).strip() or "127.0.0.1"
        self.port = int(port)
        self.timeout = float(timeout)

    @property
    def basis(self):
        return "http://%s:%d/v2/api" % (self.host, self.port)

    def _url(self, pfad, params):
        werte = {k: _wert(v) for k, v in params.items() if v is not None}
        url = self.basis + "/" + pfad.lstrip("/")
        return url + ("?" + urllib.parse.urlencode(werte) if werte else "")

    def _roh(self, pfad, timeout=None, **params):
        url = self._url(pfad, params)
        try:
            with urllib.request.urlopen(url, timeout=timeout or self.timeout) as antwort:
                return antwort.read(), antwort.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            try:
                meldung = json.loads(text).get("Error") or text
            except ValueError:
                meldung = text
            raise NinaFehler("N.I.N.A. lehnt %s ab (HTTP %d): %s" % (pfad, e.code, meldung)) from e
        except (urllib.error.URLError, OSError) as e:
            raise NinaFehler(
                "N.I.N.A. unter %s:%d nicht erreichbar (%s). Läuft N.I.N.A., ist das Plugin "
                "„Advanced API“ installiert und eingeschaltet, und stimmt der Port?"
                % (self.host, self.port, getattr(e, "reason", e))) from e

    def _get(self, pfad, timeout=None, **params):
        daten, _ = self._roh(pfad, timeout=timeout, **params)
        try:
            huelle = json.loads(daten.decode("utf-8"))
        except ValueError as e:
            raise NinaFehler("N.I.N.A. antwortet auf %s nicht mit JSON" % pfad) from e
        if not isinstance(huelle, dict) or "Success" not in huelle:
            raise NinaFehler("Unerwartete Antwort auf %s: %r" % (pfad, str(huelle)[:200]))
        if not huelle.get("Success"):
            raise NinaFehler("N.I.N.A.: %s (%s)" % (huelle.get("Error") or "Fehler ohne Text", pfad))
        return huelle.get("Response")

    # ------------------------------------------------------------------ Abfragen ----------
    def version(self):
        """{'api': '2.2.15.2', 'nina': '3.2.0.9001'}"""
        return {"api": self._get("version"), "nina": self._get("version/nina")}

    def geraete(self):
        """{'Camera': {'verbunden': bool, 'name': str|None, 'daten': {...}}, ...}.
        Der Name fehlt bei getrennten Geräten — dann None, nicht ''."""
        info = self._get("equipment/info") or {}
        aus = {}
        for schluessel, daten in info.items():
            daten = daten if isinstance(daten, dict) else {}
            aus[schluessel] = {"verbunden": bool(daten.get("Connected")),
                               "name": daten.get("DisplayName") or daten.get("Name") or None,
                               "daten": daten}
        return aus

    def geraete_suchen(self, geraet):
        """Verfügbare Treiber für ein Gerät: Liste von {'id', 'name'} (ohne 'No_Device')."""
        liste = self._get("equipment/%s/rescan" % _pfadname(geraet), timeout=60) or []
        return [{"id": d.get("Id"), "name": d.get("DisplayName") or d.get("Name")}
                for d in liste if isinstance(d, dict) and d.get("Id") not in (None, "No_Device")]

    def verbinden(self, geraet, geraete_id=None):
        return self._get("equipment/%s/connect" % _pfadname(geraet), timeout=90, to=geraete_id)

    def trennen(self, geraet):
        return self._get("equipment/%s/disconnect" % _pfadname(geraet), timeout=60)

    # ------------------------------------------------------------------ Aufnahme ----------
    def testaufnahme(self, dauer, ziel, gain=None):
        """Eine Einzelaufnahme mit der verbundenen Kamera und ihr VORSCHAUBILD als PNG.

        Gemessen am 22.11.2026 gegen N.I.N.A. 3.2.0.9001 / Advanced API 2.2.15.2 mit der
        Simulatorkamera: eine Einzelaufnahme über `camera/capture` kommt NICHT in den
        Bildverlauf, und ihr Ergebnis gibt es nur als gestrecktes PNG — auch mit
        `raw_fits=true`. Zum Scharfstellen reicht das, zum Stapeln nicht."""
        dauer = float(dauer)
        if dauer <= 0:
            raise ValueError("Belichtungszeit muss größer als 0 sein, nicht %r" % dauer)
        self._get("equipment/camera/capture", timeout=dauer + 120, duration=dauer,
                  gain=gain, waitForResult=True, omitImage=True)
        daten, _ = self._roh("equipment/camera/capture", timeout=120, getResult=True, stream=True)
        if not daten.startswith(b"\x89PNG"):
            raise NinaFehler("Vorschau kam nicht als PNG an (erste Bytes %r)" % daten[:16])
        _schreiben(ziel, daten)
        return ziel

    def bildverlauf(self):
        """Aufnahmen, die N.I.N.A. in dieser Sitzung gespeichert hat (aus Ablaufplänen)."""
        return self._get("image-history", all=True) or []

    def bild_speichern(self, index, ziel):
        """Aufnahme `index` aus dem Bildverlauf als FITS speichern. Geprüft wird, dass wirklich
        FITS ankommt; ein Vorschaubild unter .fits-Namen sähe sonst wie ein Erfolg aus.
        UNGEPRÜFT gegen ein echtes N.I.N.A.: dazu braucht es einen Ablaufplan, der speichert."""
        daten, art = self._roh("image/%d" % int(index), timeout=120, raw_fits=True, stream=True)
        if "json" in art.lower() or daten[:1] == b"{":
            antwort = json.loads(daten.decode("utf-8"))
            if not antwort.get("Success"):
                raise NinaFehler("N.I.N.A.: %s (Bild %d)" % (antwort.get("Error"), index))
            daten = base64.b64decode(antwort.get("Response") or "")
        if not daten.startswith(_FITS_ANFANG):
            raise NinaFehler("Bild %d kam nicht als FITS an (erste Bytes %r)" % (index, daten[:16]))
        _schreiben(ziel, daten)
        return ziel

    def neue_bilder_holen(self, ordner, schon=None):
        """Alle Aufnahmen aus dem Bildverlauf, die noch nicht in `ordner` liegen, als FITS dort
        ablegen. Gibt die neuen Dateien zurück."""
        schon = set() if schon is None else schon
        neu = []
        for index, eintrag in enumerate(self.bildverlauf()):
            if index in schon:
                continue
            ziel = os.path.join(ordner, _dateiname(index, eintrag))
            if not os.path.exists(ziel):
                self.bild_speichern(index, ziel)
                neu.append(ziel)
            schon.add(index)
        return neu

    # ------------------------------------------------------------------ Ablaufplan --------
    def sequenz_status(self):
        return self._get("sequence/state")

    def sequenz_start(self):
        return self._get("sequence/start")

    def sequenz_stop(self):
        return self._get("sequence/stop")


def sequenz_zusammenfassung(status):
    """Aus `sequence/state` eine kurze Zeile: Container und ihr Zustand."""
    teile = []
    for eintrag in status or []:
        if isinstance(eintrag, dict) and "Name" in eintrag:
            name = str(eintrag["Name"]).replace("_Container", "")
            teile.append("%s: %s (%d Schritte)" % (name, eintrag.get("Status", "?"),
                                                   len(eintrag.get("Items") or [])))
    return "; ".join(teile) or "kein Ablaufplan geladen"


def _schreiben(ziel, daten):
    """Erst fertig schreiben, dann umbenennen — der Live-Stapler liest den Ordner mit."""
    os.makedirs(os.path.dirname(os.path.abspath(ziel)), exist_ok=True)
    zwischen = ziel + ".teil"
    with open(zwischen, "wb") as fh:
        fh.write(daten)
    os.replace(zwischen, ziel)


def _pfadname(geraet):
    if geraet in GERAETE:
        return GERAETE[geraet]
    if geraet in GERAETE.values():
        return geraet
    raise ValueError("Unbekanntes Gerät %r; bekannt: %s" % (geraet, ", ".join(GERAETE)))


def _wert(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    return v


def _dateiname(index, eintrag):
    eintrag = eintrag if isinstance(eintrag, dict) else {}
    teile = ["nina_%05d" % index]
    for schluessel in ("ImageType", "Filter", "ExposureTime"):
        wert = eintrag.get(schluessel)
        if wert not in (None, ""):
            teile.append("".join(c if c.isalnum() or c in ".-" else "_" for c in str(wert)))
    return "_".join(teile) + ".fits"
