#!/usr/bin/env python3
"""
core/indi.py — Astro-Geräte über INDI ansprechen (die Treiberwelt von Linux und macOS).

INDI ist unter Linux und macOS das, was ASCOM unter Windows ist: ein `indiserver` am
Teleskop-Rechner (Raspberry Pi, Mini-PC, Astroberry, StellarMate, KStars/Ekos) lädt die
Treiber — `indi_asi_ccd` für ZWO-Kameras, `indi_asi_focuser`/`indi_asi_wheel` für EAF/EFW,
`indi_eqmod_telescope`, `indi_lx200*`, `indi_ioptron*` usw. — und spricht über TCP (Port
7624) mit jedem Programm. ForgePix ist hier ein INDI-Client, wie KStars/Ekos oder PHD2.

Umgesetzt nach der veröffentlichten INDI-Protokollbeschreibung (Version 1.7): XML-Elemente
ohne Wurzel über TCP; `getProperties` fragt, `def…Vector` beschreibt, `set…Vector` meldet
Änderungen, `new…Vector` setzt, Bilder kommen als `setBLOBVector` (base64-FITS) nach
`enableBLOB`. Kein fremder Code; nur Standardbibliothek, numpy und astropy (für FITS), kein Qt.

Die Geräteklassen haben dieselben Methoden wie die in `alpaca.py`, damit der Ablaufplan
(`aufnahme.py`) beide gleich benutzt.
"""
import base64
import io
import socket
import threading
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

import numpy as np

STANDARD_PORT = 7624

# DRIVER_INFO/DRIVER_INTERFACE (Bitmaske der INDI-Basisgeräte) → ForgePix-Gerätetyp.
_SCHNITTSTELLE = {1 << 0: "telescope", 1 << 1: "camera", 1 << 3: "focuser", 1 << 4: "filterwheel"}
# Ohne DRIVER_INFO: am typischen Merkmal erkennen.
_MERKMAL = {"CCD_EXPOSURE": "camera", "FILTER_SLOT": "filterwheel",
            "ABS_FOCUS_POSITION": "focuser", "EQUATORIAL_EOD_COORD": "telescope"}
_BILDTYP = {"Light": "FRAME_LIGHT", "Dark": "FRAME_DARK", "Bias": "FRAME_BIAS",
            "Flat": "FRAME_FLAT", "DarkFlat": "FRAME_DARK"}


class IndiFehler(Exception):
    """INDI-Server nicht erreichbar, Gerät/Eigenschaft fehlt oder Gerät meldet Alert."""


def _zahl(text):
    """INDI-Zahlen dürfen sexagesimal sein ("12:30:00" = 12,5)."""
    text = (text or "").strip()
    if ":" in text:
        teile = [float(t) for t in text.replace(" ", ":").split(":") if t]
        vorzeichen = -1.0 if text.startswith("-") else 1.0
        wert = 0.0
        for i, t in enumerate(teile):
            wert += abs(t) / (60.0 ** i)
        return vorzeichen * wert
    return float(text)


class Vektor:
    """Eine INDI-Eigenschaft: Art (Number/Switch/Text/Light/BLOB), Zustand und ihre Werte."""

    def __init__(self, art, geraet, name, zustand, regel=None):
        self.art, self.geraet, self.name = art, geraet, name
        self.zustand, self.regel = zustand, regel
        self.werte = {}

    def __repr__(self):
        return "<%s %s.%s %s %r>" % (self.art, self.geraet, self.name, self.zustand, self.werte)


class Server:
    """Verbindung zu einem indiserver. Ein Lesefaden sammelt alle Eigenschaften."""

    def __init__(self, host="127.0.0.1", port=STANDARD_PORT, timeout=15.0):
        self.host, self.port = str(host).strip() or "127.0.0.1", int(port)
        self.timeout = float(timeout)
        self._sock = None
        self._lesen = None
        self._zustand = threading.Condition()
        self.vektoren = {}                  # (gerät, name) -> Vektor
        self.blobs = {}                     # gerät -> (zähler, name, format, bytes)
        self.meldungen = []                 # (gerät, text) — die Geräte reden mit dem Nutzer
        self._fehler = None

    # ------------------------------------------------------------------ Verbindung --------
    def _sicherstellen(self):
        if self._sock is not None:
            return
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as e:
            raise IndiFehler("INDI-Server %s:%d nicht erreichbar (%s). Läuft dort `indiserver` "
                             "mit den Treibern?" % (self.host, self.port, e)) from e
        self._sock.settimeout(None)
        self._lesen = threading.Thread(target=self._leseschleife, daemon=True)
        self._lesen.start()
        self._senden('<getProperties version="1.7"/>')

    def schliessen(self):
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()
            self._sock = None

    def _senden(self, xml):
        try:
            self._sock.sendall(xml.encode("utf-8") + b"\n")
        except OSError as e:
            raise IndiFehler("Verbindung zum INDI-Server verloren: %s" % e) from e

    def _leseschleife(self):
        parser = ET.XMLPullParser(events=("start", "end"))
        parser.feed("<indi>")
        tiefe = 0
        try:
            while True:
                daten = self._sock.recv(65536) if self._sock else b""
                if not daten:
                    break
                parser.feed(daten)
                for ereignis, element in parser.read_events():
                    if ereignis == "start":
                        tiefe += 1
                    else:
                        tiefe -= 1
                        if tiefe == 1:              # ein vollständiges Element unter der Wurzel
                            self._verarbeiten(element)
                            element.clear()
        except (OSError, ET.ParseError) as e:
            self._fehler = "INDI-Verbindung beendet: %s" % e
        finally:
            with self._zustand:
                if self._fehler is None:
                    self._fehler = "INDI-Server hat die Verbindung geschlossen."
                self._zustand.notify_all()

    def _verarbeiten(self, el):
        tag, geraet, name = el.tag, el.get("device"), el.get("name")
        if tag == "message" or el.get("message"):
            if el.get("message"):
                self.meldungen.append((geraet, el.get("message")))
        if tag == "delProperty":
            with self._zustand:
                for schluessel in [k for k in self.vektoren
                                   if k[0] == geraet and (name is None or k[1] == name)]:
                    del self.vektoren[schluessel]
                self._zustand.notify_all()
            return
        if not (tag.startswith("def") or tag.startswith("set")) or not tag.endswith("Vector"):
            return
        art = tag[3:-6]                              # Number, Switch, Text, Light, BLOB
        with self._zustand:
            v = self.vektoren.get((geraet, name))
            if v is None or tag.startswith("def"):
                v = Vektor(art, geraet, name, el.get("state"), el.get("rule"))
                self.vektoren[(geraet, name)] = v
            if el.get("state"):
                v.zustand = el.get("state")
            for kind in el:
                text = kind.text or ""
                if art == "Number":
                    try:
                        v.werte[kind.get("name")] = _zahl(text)
                    except ValueError:
                        v.werte[kind.get("name")] = None    # unlesbar → None, nicht 0
                elif art == "Switch":
                    v.werte[kind.get("name")] = text.strip() == "On"
                elif art == "BLOB" and tag.startswith("set"):
                    roh = base64.b64decode("".join(text.split())) if text.strip() else b""
                    alt = self.blobs.get(geraet, (0,))[0]
                    self.blobs[geraet] = (alt + 1, kind.get("name"), kind.get("format"), roh)
                else:
                    v.werte[kind.get("name")] = text.strip()
            self._zustand.notify_all()

    def warten(self, bedingung, sekunden, was):
        """Warten, bis `bedingung()` wahr wird; sonst IndiFehler mit `was`."""
        self._sicherstellen()
        ende = time.monotonic() + sekunden
        with self._zustand:
            while True:
                ergebnis = bedingung()
                if ergebnis:
                    return ergebnis
                if self._fehler:
                    raise IndiFehler(self._fehler)
                rest = ende - time.monotonic()
                if rest <= 0:
                    raise IndiFehler("Zeitüberschreitung: %s" % was)
                self._zustand.wait(min(rest, 0.5))

    # ------------------------------------------------------------------ Abfragen ----------
    def vektor(self, geraet, name, warten=10.0):
        return self.warten(lambda: self.vektoren.get((geraet, name)), warten,
                           "Eigenschaft %s von %s nicht gemeldet" % (name, geraet))

    def hat(self, geraet, name):
        self._sicherstellen()
        with self._zustand:
            return (geraet, name) in self.vektoren

    def geraete(self, warten=3.0):
        """Gemeldete Geräte mit Typ, gleiche Form wie alpaca.Server.geraete(). Ein Gerät mit
        mehreren Rollen (Kamera mit eingebautem Filterrad) erscheint je Rolle einmal."""
        self._sicherstellen()
        try:                                   # die Beschreibungen kommen nach und nach
            self.warten(lambda: False, warten, "")
        except IndiFehler as e:
            if "Zeitüberschreitung" not in str(e):
                raise
        with self._zustand:
            namen = sorted({g for g, _ in self.vektoren})
            liste = []
            for g in namen:
                typen = set()
                info = self.vektoren.get((g, "DRIVER_INFO"))
                maske = None
                if info is not None:
                    try:
                        maske = int(info.werte.get("DRIVER_INTERFACE") or "")
                    except ValueError:
                        maske = None
                if maske is not None:
                    typen = {t for bit, t in _SCHNITTSTELLE.items() if maske & bit}
                for merkmal, typ in _MERKMAL.items():
                    if (g, merkmal) in self.vektoren:
                        typen.add(typ)
                for typ in sorted(typen):
                    liste.append({"name": g, "typ": typ, "nummer": g, "id": g})
        return liste

    def neu(self, geraet, name, werte):
        """new…Vector senden. Switch-Vektoren mit Regel OneOfMany bekommen alle Glieder
        mitgeschickt (das gewählte On, die anderen Off), wie es die Beschreibung empfiehlt."""
        v = self.vektor(geraet, name)
        if v.art == "Switch" and v.regel == "OneOfMany" and any(werte.values()):
            werte = {k: (k in werte and werte[k]) for k in v.werte}
        glied = {"Number": "oneNumber", "Switch": "oneSwitch", "Text": "oneText"}[v.art]
        teile = []
        for k, w in werte.items():
            if v.art == "Switch":
                inhalt = "On" if w else "Off"
            elif v.art == "Number":
                inhalt = "%.10g" % float(w)
            else:
                inhalt = escape(str(w))
            teile.append("<%s name=%s>%s</%s>" % (glied, quoteattr(k), inhalt, glied))
        with self._zustand:
            # VOR dem Senden: antwortet das Gerät schneller, als diese Zeile liefe, überschriebe
            # „Busy“ sonst sein „Ok“ — und `fertig` wartete bis zur Zeitüberschreitung.
            v.zustand = "Busy"
        self._senden("<new%sVector device=%s name=%s>%s</new%sVector>"
                     % (v.art, quoteattr(geraet), quoteattr(name), "".join(teile), v.art))
        return v

    def fertig(self, geraet, name, sekunden, was):
        """Warten, bis die Eigenschaft nicht mehr Busy ist. Alert ist ein Fehler."""
        v = self.vektor(geraet, name)
        self.warten(lambda: v.zustand != "Busy", sekunden, was)
        if v.zustand == "Alert":
            letzte = [t for g, t in self.meldungen if g == geraet][-1:]
            raise IndiFehler("%s meldet Fehler bei %s%s" % (geraet, name,
                                                              (": " + letzte[0]) if letzte else ""))
        return v

    def blob_aktivieren(self, geraet):
        self._senden("<enableBLOB device=%s>Also</enableBLOB>" % quoteattr(geraet))


class Geraet:
    def __init__(self, server, nummer):
        self.server, self.geraet = server, str(nummer)

    @property
    def name(self):
        return self.geraet

    def verbinden(self, sekunden=60.0):
        s = self.server
        v = s.vektor(self.geraet, "CONNECTION")
        if not v.werte.get("CONNECT"):
            s.neu(self.geraet, "CONNECTION", {"CONNECT": True})
            s.fertig(self.geraet, "CONNECTION", sekunden, "%s verbinden" % self.geraet)
        return bool(v.werte.get("CONNECT"))

    def trennen(self):
        s = self.server
        s.neu(self.geraet, "CONNECTION", {"DISCONNECT": True})
        s.fertig(self.geraet, "CONNECTION", 30, "%s trennen" % self.geraet)
        return not s.vektor(self.geraet, "CONNECTION").werte.get("CONNECT")

    @property
    def verbunden(self):
        return bool(self.server.vektor(self.geraet, "CONNECTION").werte.get("CONNECT"))

    def _wert(self, eigenschaft, glied, warten=2.0):
        """Ein Wert oder None, wenn der Treiber die Eigenschaft nicht hat."""
        try:
            return self.server.vektor(self.geraet, eigenschaft, warten=warten).werte.get(glied)
        except IndiFehler:
            return None


class Kamera(Geraet):
    def info(self):
        cfa = self._wert("CCD_CFA", "CFA_TYPE", warten=0.5)
        gain = self._wert("CCD_CONTROLS", "Gain", warten=0.5)       # ZWO-Treiber
        if gain is None:
            gain = self._wert("CCD_GAIN", "GAIN", warten=0.5)
        offset = self._wert("CCD_CONTROLS", "Offset", warten=0.5)
        if offset is None:
            offset = self._wert("CCD_OFFSET", "OFFSET", warten=0.5)
        return {
            "name": self.geraet,
            "breite": self._wert("CCD_INFO", "CCD_MAX_X"),
            "hoehe": self._wert("CCD_INFO", "CCD_MAX_Y"),
            "pixel_um": self._wert("CCD_INFO", "CCD_PIXEL_SIZE"),
            "sensortyp": None,
            "bayer": cfa or None,
            "gain": gain, "offset": offset,
            "temperatur": self.temperatur(),
            "binning": self._wert("CCD_BINNING", "HOR_BIN", warten=0.5),
        }

    def temperatur(self):
        return self._wert("CCD_TEMPERATURE", "CCD_TEMPERATURE_VALUE", warten=0.5)

    def belichten(self, dauer, licht=True, abbruch=None, max_warten=None, typ=None):
        """Belichten und das FITS-Bild aus dem BLOB als numpy-Array liefern."""
        from astropy.io import fits
        s, g = self.server, self.geraet
        dauer = float(dauer)
        if dauer < 0:
            raise ValueError("Belichtungszeit darf nicht negativ sein: %r" % dauer)
        bildtyp = _BILDTYP.get(typ) or ("FRAME_LIGHT" if licht else "FRAME_DARK")
        if s.hat(g, "CCD_FRAME_TYPE"):
            s.neu(g, "CCD_FRAME_TYPE", {bildtyp: True})
            s.fertig(g, "CCD_FRAME_TYPE", 10, "Bildtyp setzen")
        s.blob_aktivieren(g)
        vorher = s.blobs.get(g, (0,))[0]
        s.neu(g, "CCD_EXPOSURE", {"CCD_EXPOSURE_VALUE": dauer})
        grenze = dauer + (max_warten if max_warten is not None else 120 + dauer)

        def bild_da():
            if abbruch is not None and abbruch.is_set():
                return "abbruch"
            return s.blobs.get(g, (0,))[0] > vorher
        ergebnis = s.warten(bild_da, grenze, "kein Bild von %s nach %.0f s" % (g, grenze))
        if ergebnis == "abbruch":
            if s.hat(g, "CCD_ABORT_EXPOSURE"):
                s.neu(g, "CCD_ABORT_EXPOSURE", {"ABORT": True})
            raise IndiFehler("Belichtung abgebrochen")
        _, _, format_, roh = s.blobs[g]
        if not (format_ or "").lower().startswith(".fits") or not roh.startswith(b"SIMPLE"):
            raise IndiFehler("Kamera schickte kein FITS (Format %r). Im Treiber „FITS“ als "
                             "Ausgabeformat wählen." % format_)
        with fits.open(io.BytesIO(roh)) as h:
            bild = np.asarray(h[0].data)
        if bild.ndim == 3:                             # RGB-Ebenen (3, H, B) → (H, B, 3)
            bild = np.moveaxis(bild, 0, -1)
        if np.issubdtype(bild.dtype, np.floating) or bild.min() < 0 or bild.max() > 65535:
            return bild.astype(np.float32)
        return bild.astype(np.uint16)


class Filterrad(Geraet):
    def namen(self):
        """Filternamen in Fachreihenfolge. Wartet auf die Beschreibung — direkt nach dem
        Verbinden ist sie oft noch nicht da, und eine leere Liste sähe aus wie „keine Filter“."""
        try:
            v = self.server.vektor(self.geraet, "FILTER_NAME", warten=5.0)
        except IndiFehler:
            return []                                   # Treiber ohne Namen: nur Fachnummern
        def nummer(k):
            ziffern = "".join(c for c in k if c.isdigit())
            return int(ziffern) if ziffern else 0
        return [v.werte[k] for k in sorted(v.werte, key=nummer)]

    def position(self):
        """0-basiert wie bei Alpaca; INDI zählt die Fächer ab 1."""
        wert = self._wert("FILTER_SLOT", "FILTER_SLOT_VALUE")
        return None if wert is None else int(round(wert)) - 1

    def wechseln(self, ziel, max_warten=60.0):
        if isinstance(ziel, str):
            namen = self.namen()
            if ziel not in namen:
                raise IndiFehler("Filter %r nicht im Rad; vorhanden: %s" % (ziel, ", ".join(namen)))
            ziel = namen.index(ziel)
        self.server.neu(self.geraet, "FILTER_SLOT", {"FILTER_SLOT_VALUE": int(ziel) + 1})
        self.server.fertig(self.geraet, "FILTER_SLOT", max_warten, "Filterrad drehen")
        if self.position() != int(ziel):
            raise IndiFehler("Filterrad steht auf %r statt %d" % (self.position(), ziel))
        return int(ziel)


class Fokussierer(Geraet):
    def position(self):
        return self._wert("ABS_FOCUS_POSITION", "FOCUS_ABSOLUTE_POSITION")

    def fahren(self, ziel, max_warten=120.0):
        self.server.neu(self.geraet, "ABS_FOCUS_POSITION", {"FOCUS_ABSOLUTE_POSITION": int(ziel)})
        self.server.fertig(self.geraet, "ABS_FOCUS_POSITION", max_warten, "Fokussierer fahren")
        return self.position()


class Montierung(Geraet):
    def position(self):
        """(RA in Stunden, Dec in Grad) — Epoche des Datums, wie INDI sie meldet."""
        v = self.server.vektor(self.geraet, "EQUATORIAL_EOD_COORD")
        return float(v.werte["RA"]), float(v.werte["DEC"])

    def schwenken(self, ra_stunden, dec_grad, max_warten=300.0):
        s, g = self.server, self.geraet
        if s.hat(g, "ON_COORD_SET"):
            s.neu(g, "ON_COORD_SET", {"TRACK": True})
            s.fertig(g, "ON_COORD_SET", 10, "Schwenkart setzen")
        s.neu(g, "EQUATORIAL_EOD_COORD", {"RA": float(ra_stunden), "DEC": float(dec_grad)})
        s.fertig(g, "EQUATORIAL_EOD_COORD", max_warten, "Schwenk")
        return self.position()

    def nachfuehrung(self):
        return bool(self.server.vektor(self.geraet, "TELESCOPE_TRACK_STATE").werte.get("TRACK_ON"))

    def synchronisieren(self, ra_stunden, dec_grad):
        s, g = self.server, self.geraet
        s.neu(g, "ON_COORD_SET", {"SYNC": True})
        s.fertig(g, "ON_COORD_SET", 10, "Sync wählen")
        s.neu(g, "EQUATORIAL_EOD_COORD", {"RA": float(ra_stunden), "DEC": float(dec_grad)})
        s.fertig(g, "EQUATORIAL_EOD_COORD", 30, "Sync")
        s.neu(g, "ON_COORD_SET", {"TRACK": True})      # danach wieder normal schwenken
        s.fertig(g, "ON_COORD_SET", 10, "Schwenkart zurücksetzen")
        return self.position()

    def stundenwinkel(self):
        lst = self._wert("TIME_LST", "LST", warten=1.0)
        if lst is None:
            return None
        return (float(lst) - self.position()[0] + 12.0) % 24.0 - 12.0

    def seite(self):
        v = self.server.vektoren.get((self.geraet, "TELESCOPE_PIER_SIDE"))
        if v is None:
            return None
        if v.werte.get("PIER_EAST"):
            return "Ost"
        if v.werte.get("PIER_WEST"):
            return "West"
        return None

    def nachfuehren(self, an=True):
        s, g = self.server, self.geraet
        s.neu(g, "TELESCOPE_TRACK_STATE", {"TRACK_ON" if an else "TRACK_OFF": True})
        s.fertig(g, "TELESCOPE_TRACK_STATE", 10, "Nachführung schalten")
        return bool(s.vektor(g, "TELESCOPE_TRACK_STATE").werte.get("TRACK_ON"))

    def parken(self):
        self.server.neu(self.geraet, "TELESCOPE_PARK", {"PARK": True})
        return self.server.fertig(self.geraet, "TELESCOPE_PARK", 300, "Parken")

    def stopp(self):
        self.server.neu(self.geraet, "TELESCOPE_ABORT_MOTION", {"ABORT": True})
