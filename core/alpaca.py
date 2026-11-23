#!/usr/bin/env python3
"""
core/alpaca.py — Astro-Geräte direkt ansprechen, über ASCOM Alpaca.

Alpaca ist die Netzwerkform von ASCOM: jedes Gerät antwortet auf HTTP, unabhängig vom
Betriebssystem. Damit spricht ForgePix unter Windows, macOS und Linux dieselben Geräte an:

* Geräte mit eigenem Alpaca (z. B. die Seestar, viele neue Montierungen),
* jedes klassische ASCOM-Gerät unter Windows über „ASCOM Remote“ als Brücke,
* die ASCOM-Simulatoren („OmniSim“) zum Üben ohne Teleskop.

Umgesetzt nach der veröffentlichten ASCOM-Alpaca-Schnittstellenbeschreibung (Version 1);
kein fremder Code. Nur Standardbibliothek und numpy, kein Qt.

Jede Antwort hat die Form {"Value": …, "ErrorNumber": 0, "ErrorMessage": "", …}. Eine
ErrorNumber ungleich 0 wird IMMER zum Fehler mit dem Text des Geräts.
"""
import itertools
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

DISCOVERY_PORT = 32227
DISCOVERY_TEXT = b"alpacadiscovery1"
NICHT_UMGESETZT = 0x400            # ASCOM: Eigenschaft/Methode vom Treiber nicht umgesetzt

# ASCOM SensorType: 2 = Bayer RGGB; der Versatz verschiebt das Muster.
_BAYER = {(0, 0): "RGGB", (1, 0): "GRBG", (0, 1): "GBRG", (1, 1): "BGGR"}

_transaktion = itertools.count(1)


class AlpacaFehler(Exception):
    """Gerät nicht erreichbar oder Anfrage vom Gerät abgelehnt."""

    def __init__(self, text, nummer=None):
        super().__init__(text)
        self.nummer = nummer


def suchen(warten=2.0, port=DISCOVERY_PORT):
    """Alpaca-Server im lokalen Netz finden (UDP-Rundruf). Liste von (host, port).

    Ein Netz, das Rundrufe sperrt (manche WLANs, VPNs), findet hier nichts — dann die Adresse
    von Hand eintragen. Leer heißt also „nichts geantwortet", nicht „nichts da"."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(0.3)
    gefunden = set()
    try:
        for ziel in ("255.255.255.255", "127.0.0.1"):
            try:
                s.sendto(DISCOVERY_TEXT, (ziel, port))
            except OSError:
                pass
        ende = time.monotonic() + warten
        while time.monotonic() < ende:
            try:
                daten, (host, _) = s.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:                  # Windows meldet ICMP „unerreichbar" als Fehler
                continue
            try:
                gefunden.add((host, int(json.loads(daten.decode())["AlpacaPort"])))
            except (ValueError, KeyError, TypeError):
                continue
    finally:
        s.close()
    return sorted(gefunden)


class Server:
    """Ein Alpaca-Server (ein Rechner, ein Port) mit seinen Geräten."""

    def __init__(self, host="127.0.0.1", port=11111, timeout=15.0, client_id=4711):
        self.host, self.port = str(host).strip() or "127.0.0.1", int(port)
        self.timeout, self.client_id = float(timeout), int(client_id)

    @property
    def basis(self):
        return "http://%s:%d" % (self.host, self.port)

    def _anfrage(self, pfad, daten=None, timeout=None):
        url = self.basis + pfad
        params = {"ClientID": self.client_id, "ClientTransactionID": next(_transaktion)}
        if daten is None:
            req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params))
        else:
            params.update(daten)
            req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(),
                                         method="PUT")
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as antwort:
                text = antwort.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise AlpacaFehler("Alpaca lehnt %s ab (HTTP %d): %s"
                               % (pfad, e.code, e.read().decode("utf-8", "replace")[:200])) from e
        except (urllib.error.URLError, OSError) as e:
            raise AlpacaFehler("Alpaca-Server %s:%d nicht erreichbar (%s)"
                               % (self.host, self.port, getattr(e, "reason", e))) from e
        try:
            huelle = json.loads(text)
        except ValueError as e:
            raise AlpacaFehler("Keine JSON-Antwort auf %s" % pfad) from e
        nummer = int(huelle.get("ErrorNumber") or 0)
        if nummer:
            raise AlpacaFehler("Gerät meldet Fehler %d bei %s: %s"
                               % (nummer, pfad, huelle.get("ErrorMessage") or "ohne Text"), nummer)
        return huelle.get("Value")

    def geraete(self):
        """Konfigurierte Geräte: Liste von {'name', 'typ', 'nummer', 'id'}."""
        liste = self._anfrage("/management/v1/configureddevices") or []
        return [{"name": d.get("DeviceName"), "typ": str(d.get("DeviceType", "")).lower(),
                 "nummer": int(d.get("DeviceNumber", 0)), "id": d.get("UniqueID")}
                for d in liste]

    def beschreibung(self):
        return self._anfrage("/management/v1/description") or {}


class Geraet:
    TYP = None

    def __init__(self, server, nummer=0):
        self.server, self.nummer = server, int(nummer)

    def _pfad(self, methode):
        return "/api/v1/%s/%d/%s" % (self.TYP, self.nummer, methode.lower())

    def lesen(self, eigenschaft, timeout=None):
        return self.server._anfrage(self._pfad(eigenschaft), timeout=timeout)

    def lesen_oder_none(self, eigenschaft):
        """Für Eigenschaften, die viele Treiber nicht haben: None statt Fehler — aber nur
        bei „nicht umgesetzt", jeder andere Fehler bleibt ein Fehler."""
        try:
            return self.lesen(eigenschaft)
        except AlpacaFehler as e:
            if e.nummer in (NICHT_UMGESETZT, 0x401, 0x402):
                return None
            raise

    def setzen(self, methode, timeout=None, **werte):
        return self.server._anfrage(self._pfad(methode), daten={k: _wert(v) for k, v in werte.items()},
                                    timeout=timeout)

    def verbinden(self):
        self.setzen("connected", Connected=True)
        return bool(self.lesen("connected"))

    def trennen(self):
        self.setzen("connected", Connected=False)
        return not bool(self.lesen("connected"))

    @property
    def verbunden(self):
        return bool(self.lesen("connected"))

    @property
    def name(self):
        return self.lesen_oder_none("name")


class Kamera(Geraet):
    TYP = "camera"

    def info(self):
        """Was das Bild später im FITS-Kopf braucht. Fehlende Werte sind None."""
        typ = self.lesen_oder_none("sensortype")
        bx = self.lesen_oder_none("bayeroffsetx") if typ == 2 else None
        by = self.lesen_oder_none("bayeroffsety") if typ == 2 else None
        return {
            "name": self.name,
            "breite": self.lesen_oder_none("cameraxsize"),
            "hoehe": self.lesen_oder_none("cameraysize"),
            "pixel_um": self.lesen_oder_none("pixelsizex"),
            "sensortyp": typ,
            "bayer": _BAYER.get((int(bx or 0), int(by or 0))) if typ == 2 else None,
            "gain": self.lesen_oder_none("gain"),
            "offset": self.lesen_oder_none("offset"),
            "temperatur": self.lesen_oder_none("ccdtemperature"),
            "binning": self.lesen_oder_none("binx"),
        }

    def temperatur(self):
        return self.lesen_oder_none("ccdtemperature")

    def belichten(self, dauer, licht=True, abbruch=None, max_warten=None, typ=None):
        """Eine Aufnahme machen und das Bild als numpy-Array (Zeilen × Spalten) liefern.

        `typ` (Light/Dark/Flat/Bias) kennt Alpaca nicht — nur hell oder dunkel über `licht`.

        `abbruch`: threading.Event — gesetzt bricht die Belichtung ab (abortexposure).
        Alpaca liefert ImageArray als [x][y]; hier wird auf [y][x] gedreht, wie FITS und
        numpy es erwarten."""
        dauer = float(dauer)
        if dauer < 0:
            raise ValueError("Belichtungszeit darf nicht negativ sein: %r" % dauer)
        self.setzen("startexposure", Duration=dauer, Light=bool(licht))
        ende = time.monotonic() + dauer + (max_warten if max_warten is not None else 120 + dauer)
        while not self.lesen("imageready"):
            if abbruch is not None and abbruch.is_set():
                try:
                    self.setzen("abortexposure")
                except AlpacaFehler:
                    pass
                raise AlpacaFehler("Belichtung abgebrochen")
            if time.monotonic() > ende:
                raise AlpacaFehler("Kamera meldet nach %.0f s kein fertiges Bild" % (dauer + 120))
            time.sleep(0.2)
        werte = self.lesen("imagearray", timeout=max(60.0, self.server.timeout))
        bild = np.asarray(werte)
        if bild.ndim not in (2, 3) or bild.size == 0:
            raise AlpacaFehler("Kamera lieferte kein Bild (Form %r)" % (bild.shape,))
        bild = np.swapaxes(bild, 0, 1)                  # [x][y] -> [y][x]
        if bild.min() < 0 or bild.max() > 65535:
            return bild.astype(np.float32)               # nie still in 16 bit pressen
        return bild.astype(np.uint16)


class Filterrad(Geraet):
    TYP = "filterwheel"

    def namen(self):
        return list(self.lesen("names") or [])

    def position(self):
        return self.lesen("position")

    def wechseln(self, ziel, max_warten=60.0):
        """Auf Position (Zahl) oder Filternamen wechseln und warten, bis das Rad steht."""
        if isinstance(ziel, str):
            namen = self.namen()
            if ziel not in namen:
                raise AlpacaFehler("Filter %r nicht im Rad; vorhanden: %s" % (ziel, ", ".join(namen)))
            ziel = namen.index(ziel)
        self.setzen("position", Position=int(ziel))
        ende = time.monotonic() + max_warten
        while self.position() != int(ziel):              # -1 heißt „dreht noch"
            if time.monotonic() > ende:
                raise AlpacaFehler("Filterrad hat Position %d nach %.0f s nicht erreicht"
                                   % (ziel, max_warten))
            time.sleep(0.2)
        return int(ziel)


class Fokussierer(Geraet):
    TYP = "focuser"

    def position(self):
        return self.lesen("position")

    def fahren(self, ziel, max_warten=120.0):
        self.setzen("move", Position=int(ziel))
        ende = time.monotonic() + max_warten
        while self.lesen("ismoving"):
            if time.monotonic() > ende:
                raise AlpacaFehler("Fokussierer steht nach %.0f s noch nicht" % max_warten)
            time.sleep(0.2)
        return self.position()


class Montierung(Geraet):
    TYP = "telescope"

    def position(self):
        """(RA in Stunden, Dec in Grad)."""
        return float(self.lesen("rightascension")), float(self.lesen("declination"))

    def schwenken(self, ra_stunden, dec_grad, max_warten=300.0):
        self.setzen("slewtocoordinatesasync", RightAscension=float(ra_stunden),
                    Declination=float(dec_grad))
        ende = time.monotonic() + max_warten
        while self.lesen("slewing"):
            if time.monotonic() > ende:
                self.setzen("abortslew")
                raise AlpacaFehler("Schwenk nach %.0f s abgebrochen" % max_warten)
            time.sleep(0.5)
        return self.position()

    def nachfuehrung(self):
        return bool(self.lesen("tracking"))

    def nachfuehren(self, an=True):
        self.setzen("tracking", Tracking=bool(an))
        return bool(self.lesen("tracking"))

    def parken(self):
        return self.setzen("park", timeout=300)

    def stopp(self):
        return self.setzen("abortslew")


def _wert(v):
    if isinstance(v, bool):
        return "True" if v else "False"
    return v
