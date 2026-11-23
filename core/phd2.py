#!/usr/bin/env python3
"""
core/phd2.py — Nachführung mit PHD2 steuern: Zustand, Guiding starten/stoppen, Dithern.

PHD2 (frei, Windows/macOS/Linux) hat einen Ereignis-Server auf TCP 4400: zeilenweise JSON,
Ereignisse ({"Event": "AppState", ...}) und Aufrufe im JSON-RPC-Stil
({"method": "dither", "params": {...}, "id": 1}). Umgesetzt nach PHD2s veröffentlichter
Beschreibung („EventMonitoring“); kein fremder Code. Kein Qt.

Dithern heißt: zwischen zwei Aufnahmen die Montierung ein paar Pixel versetzen lassen, damit
Hotpixel und Muster beim Stapeln nicht übereinander liegen. PHD2 meldet danach „SettleDone“ —
erst dann darf die nächste Belichtung beginnen. Ein Status ungleich 0 dort ist ein Fehler.
"""
import itertools
import json
import socket
import threading
import time

STANDARD_PORT = 4400


class Phd2Fehler(Exception):
    pass


class Phd2:
    def __init__(self, host="127.0.0.1", port=STANDARD_PORT, timeout=10.0):
        self.host, self.port, self.timeout = str(host).strip() or "127.0.0.1", int(port), float(timeout)
        self._sock = None
        self._ids = itertools.count(1)
        self._zustand = threading.Condition()
        self._antworten = {}
        self.ereignisse = []
        self.app_state = None
        self._fehler = None

    def _sicherstellen(self):
        if self._sock is not None:
            return
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise Phd2Fehler("PHD2 unter %s:%d nicht erreichbar (%s). Läuft PHD2, und ist unter "
                             "„Werkzeuge → Server aktivieren“ der Server an?" % (self.host, self.port, e)) from e
        self._sock.settimeout(None)
        threading.Thread(target=self._lesen, daemon=True).start()

    def schliessen(self):
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
            self._sock = None

    def _lesen(self):
        rest = b""
        try:
            while True:
                daten = self._sock.recv(65536) if self._sock else b""
                if not daten:
                    break
                rest += daten
                while b"\n" in rest:
                    zeile, rest = rest.split(b"\n", 1)
                    if zeile.strip():
                        self._verarbeiten(json.loads(zeile.decode("utf-8")))
        except (OSError, ValueError) as e:
            self._fehler = "PHD2-Verbindung beendet: %s" % e
        finally:
            with self._zustand:
                self._fehler = self._fehler or "PHD2 hat die Verbindung geschlossen."
                self._zustand.notify_all()

    def _verarbeiten(self, nachricht):
        with self._zustand:
            if "Event" in nachricht:
                self.ereignisse.append(nachricht)
                if nachricht["Event"] == "AppState":
                    self.app_state = nachricht.get("State")
            elif "id" in nachricht:
                self._antworten[nachricht["id"]] = nachricht
            self._zustand.notify_all()

    def _warten(self, bedingung, sekunden, was):
        ende = time.monotonic() + sekunden
        with self._zustand:
            while True:
                ergebnis = bedingung()
                if ergebnis:
                    return ergebnis
                if self._fehler:
                    raise Phd2Fehler(self._fehler)
                rest = ende - time.monotonic()
                if rest <= 0:
                    raise Phd2Fehler("Zeitüberschreitung: %s" % was)
                self._zustand.wait(min(rest, 0.5))

    def aufrufen(self, methode, params=None, sekunden=None):
        self._sicherstellen()
        nummer = next(self._ids)
        nachricht = {"method": methode, "id": nummer}
        if params is not None:
            nachricht["params"] = params
        self._sock.sendall((json.dumps(nachricht) + "\r\n").encode("utf-8"))
        antwort = self._warten(lambda: self._antworten.pop(nummer, None), sekunden or self.timeout,
                               "PHD2 antwortet nicht auf %s" % methode)
        if "error" in antwort:
            fehler = antwort["error"]
            raise Phd2Fehler("PHD2 lehnt %s ab: %s" % (methode, fehler.get("message", fehler)
                                                       if isinstance(fehler, dict) else fehler))
        return antwort.get("result")

    # ------------------------------------------------------------------ Befehle -----------
    def zustand(self):
        """'Stopped', 'Selected', 'Calibrating', 'Guiding', 'LostLock', 'Paused', 'Looping'."""
        return self.aufrufen("get_app_state")

    def guiding_starten(self, pixel=1.5, zeit=10, timeout=120):
        self._sicherstellen()
        vorher = len(self.ereignisse)            # VOR dem Aufruf: SettleDone kann sofort kommen
        self.aufrufen("guide", {"settle": {"pixels": pixel, "time": zeit, "timeout": timeout},
                                "recalibrate": False})
        return self._einschwingen(timeout + 30, ab=vorher)

    def stoppen(self):
        return self.aufrufen("stop_capture")

    def dithern(self, betrag=3.0, nur_ra=False, pixel=1.5, zeit=10, timeout=120):
        """Versetzen und warten, bis PHD2 wieder ruhig führt."""
        if self.zustand() != "Guiding":
            raise Phd2Fehler("Dithern geht nur während PHD2 führt (Zustand: %s)" % self.app_state)
        vorher = len(self.ereignisse)
        self.aufrufen("dither", {"amount": float(betrag), "raOnly": bool(nur_ra),
                                 "settle": {"pixels": pixel, "time": zeit, "timeout": timeout}})
        return self._einschwingen(timeout + 30, ab=vorher)

    def _einschwingen(self, sekunden, ab=None):
        ab = len(self.ereignisse) if ab is None else ab

        def fertig():
            for e in self.ereignisse[ab:]:
                if e.get("Event") == "SettleDone":
                    return e
            return None
        e = self._warten(fertig, sekunden, "PHD2 meldet kein SettleDone")
        if e.get("Status", 0) != 0:
            raise Phd2Fehler("PHD2 kam nicht zur Ruhe: %s" % (e.get("Error") or e))
        return e
