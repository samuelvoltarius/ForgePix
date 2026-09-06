#!/usr/bin/env python3
"""
core/livestack.py — laufendes Stapeln: jeder neue Frame wird EINMAL verrechnet.

Warum es das braucht: der bisherige Beobachtungsmodus (`--watch`) stapelt bei jedem neuen Sub
den GESAMTEN Bestand neu. Über eine Nacht mit 200 Aufnahmen ist das quadratischer Aufwand —
beim 200. Sub werden 200 Dateien gelesen, obwohl sich genau eine geändert hat. Hier werden
stattdessen laufende Summen fortgeschrieben; ein neuer Frame kostet immer gleich viel.

Was mitgeführt wird (alles je Pixel):
    anzahl Anzahl der tatsächlich angenommenen Werte je Farbkanal
    summe  Σ w·x        → Mittel = summe / gewicht
    quadr  Σ w·x²       → Streuung, für die Ausreisser-Erkennung

Die Ausreisser-Erkennung ist die eine echte Einschränkung gegenüber dem Stapeln am Ende: dort
sind alle Werte gleichzeitig da, hier wird ein neuer Wert gegen die Statistik der BISHERIGEN
geprüft. Solange genug Frames beisammen sind, kommt fast dasselbe heraus (an echten Daten
gemessen, s. tests/test_livestack.py); bei den ersten Frames ist die Statistik noch dünn, darum
wird erst ab `min_fuer_verwurf` überhaupt verworfen.

Der Zustand lässt sich speichern und wieder laden. Ein Absturz um drei Uhr nachts kostet dann
nicht die halbe Nacht.
"""
import os
import tempfile
import time

import numpy as np
import cv2

from constants import log_print, imwrite
import astro


class LiveStack:
    """Laufender Stapel mit Registrierung auf einen festen Referenzframe."""

    def __init__(self, referenz=None, kappa=2.5, min_fuer_verwurf=5, gewichten=True,
                 registrieren=True, log=log_print, context_id=""):
        self.kappa = float(kappa)
        self.min_fuer_verwurf = int(min_fuer_verwurf)
        self.gewichten = bool(gewichten)
        self.registrieren = bool(registrieren)
        self.log = log
        self.context_id = str(context_id)
        self.reader = astro._read_float
        self.summe = None          # Σ w·x
        self.quadr = None          # Σ w·x²
        self.gewicht = None        # Σ w je Pixel und Farbkanal
        self.anzahl = None         # tatsächlich angenommene Werte je Pixel/Farbkanal
        self.n = 0                 # eingegangene Frames
        self.verworfen = 0         # Frames, die sich nicht ausrichten liessen
        self.ref_grau = None
        self.ref_pegel = None
        self.pfade = []
        if referenz is not None:
            self._referenz_setzen(referenz)

    # ---------------------------------------------------------------- intern
    def _referenz_setzen(self, bild):
        f = np.asarray(bild, np.float32)
        self.ref_grau = astro._gray(f)
        self.ref_pegel = float(np.median(self.ref_grau))
        self.summe = np.zeros(f.shape, np.float32)
        self.quadr = np.zeros(f.shape, np.float32)
        self.gewicht = np.zeros(f.shape, np.float32)
        self.anzahl = np.zeros(f.shape, np.uint32)

    def _ausrichten(self, f):
        """Bild und gültige Abdeckung auf die Referenz schieben. None bei Fehlschlag: ein Frame, der
        sich nicht ausrichten lässt, gehört NICHT unverschoben in den Stapel; er würde die
        Sterne verdoppeln."""
        if not self.registrieren or self.ref_grau is None:
            return f, np.ones(f.shape[:2], dtype=bool)
        try:
            M = astro._estimate_star_shift(self.ref_grau, astro._gray(f))
        except Exception:
            M = None
        if M is None:
            return None
        M = np.asarray(M, dtype=np.float64)
        if M.shape != (2, 3) or not np.isfinite(M).all():
            return None
        # Lanczos4 greift auf bis zu acht Quellpixel je Achse zu. Ein nur nach
        # Mittelpunkt gewarptes Rechteck würde deshalb erfundene Randwerte als
        # Himmel zählen. Der konservative Vier-Pixel-Saum schützt den gesamten
        # Interpolationskern; reine ganzzahlige Verschiebungen brauchen ihn nicht.
        ganzzahlig = (np.array_equal(M[:, :2], np.eye(2))
                      and np.array_equal(M[:, 2], np.rint(M[:, 2])))
        quelle = np.ones(f.shape[:2], np.uint8) if ganzzahlig else np.zeros(f.shape[:2], np.uint8)
        if not ganzzahlig:
            quelle[4:-4, 4:-4] = 1
        groesse = (f.shape[1], f.shape[0])
        deckung = cv2.warpAffine(quelle, M, groesse, flags=cv2.INTER_NEAREST,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=0).astype(bool)
        if not deckung.any():
            return None
        g = cv2.warpAffine(f, M, groesse, flags=cv2.INTER_LANCZOS4,
                           borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        return g, deckung

    # ------------------------------------------------------------ öffentlich
    def hinzufuegen(self, bild_oder_pfad):
        """Einen Frame verrechnen. Gibt True zurück, wenn er im Stapel gelandet ist."""
        if isinstance(bild_oder_pfad, str):
            pfad = bild_oder_pfad
            try:
                f = self.reader(pfad)
            except (OSError, ValueError, RuntimeError) as e:
                self.log("    Live: Aufnahme noch nicht lesbar, wird erneut versucht: %s (%s)" % (pfad, e))
                return False
            if f is not None and f.ndim == 2:
                f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
        else:
            pfad, f = None, np.asarray(bild_oder_pfad, np.float32)
        if f is None:
            return False
        if f.size == 0 or not np.isfinite(f).all():
            self.log("    Live: Aufnahme enthält leere oder ungültige Pixel — übersprungen")
            self.verworfen += 1
            return False
        neue_referenz = self.summe is None
        if neue_referenz:
            self._referenz_setzen(f)
        elif f.shape != self.summe.shape:
            self.log("    Live: Bildgroesse passt nicht (%s statt %s) — uebersprungen"
                     % (f.shape, self.summe.shape))
            self.verworfen += 1
            return False

        ausgerichtet = ((f, np.ones(f.shape[:2], dtype=bool)) if neue_referenz
                        else self._ausrichten(f))
        if ausgerichtet is None:
            self.log("    Live: Frame liess sich nicht ausrichten — uebersprungen")
            self.verworfen += 1
            return False
        g, deckung = ausgerichtet

        # Pegelangleich wie beim Stapeln am Ende: Dunst und Mondaufgang heben den Himmel,
        # ohne dass das Objekt heller wird.
        # Bei Dithering stets dieselbe Himmelsregion vergleichen. Weder fehlende
        # Ränder noch ein anderer Ausschnitt eines Gradienten dürfen den Pegel
        # oder das Rauschgewicht des ganzen Frames verändern.
        grau = astro._gray(g)
        g = g + (float(np.median(self.ref_grau[deckung])) - float(np.median(grau[deckung])))

        w = 1.0
        if self.gewichten:
            sigma = float(astro._bg_sigma(grau[deckung]))
            w = 1.0 / max(sigma * sigma, 1e-12)

        maske = np.broadcast_to(deckung[..., None], g.shape) if g.ndim == 3 else deckung
        if self.n >= self.min_fuer_verwurf:
            mittel = self.summe / np.maximum(self.gewicht, 1e-9)
            var = (self.quadr / np.maximum(self.gewicht, 1e-9)) - mittel * mittel
            std = np.sqrt(np.maximum(var, 0.0))
            maske = maske & ((self.anzahl < self.min_fuer_verwurf)
                             | (np.abs(g - mittel) <= (self.kappa * std + 1e-6)))

        mw = maske.astype(np.float32) * w
        self.summe += g * mw
        self.quadr += g * g * mw
        # Abdeckung UND Kanalverwurf müssen für Zähler und Nenner gleich sein.
        self.gewicht += mw
        self.anzahl += maske
        self.n += 1
        if pfad:
            self.pfade.append(pfad)
        return True

    def ergebnis(self):
        """Der aktuelle Stapel als float32-BGR in [0..1], oder None."""
        if self.summe is None or self.n == 0:
            return None
        return np.clip(self.summe / np.maximum(self.gewicht, 1e-9), 0, 1)

    def vorschau_schreiben(self, pfad, strecken=True, skala=0.5):
        """Zwischenstand als JPG — das ist der Sinn des Ganzen: beim Aufnehmen zusehen."""
        erg = self.ergebnis()
        if erg is None:
            return False
        v = astro.autostretch(erg) if strecken else erg
        if skala and skala != 1.0:
            v = cv2.resize(v, (0, 0), fx=skala, fy=skala)
        return bool(imwrite(pfad, np.clip(v * 255, 0, 255).astype(np.uint8),
                            [int(cv2.IMWRITE_JPEG_QUALITY), 88]))

    def speichern(self, pfad):
        """Zustand sichern. Ein Absturz um drei Uhr nachts kostet dann nicht die halbe Nacht."""
        if self.summe is None:
            return False
        target = os.path.abspath(os.fspath(pfad))
        if not target.endswith(".npz"):
            target += ".npz"
        fd, temp = tempfile.mkstemp(prefix=".live-", suffix=".npz", dir=os.path.dirname(target))
        try:
            with os.fdopen(fd, "wb") as out:
                np.savez_compressed(
                    out, version=np.int64(3), summe=self.summe, quadr=self.quadr,
                    anzahl=self.anzahl, context_id=np.str_(self.context_id),
                    gewicht=self.gewicht, ref_grau=self.ref_grau, n=np.int64(self.n),
                    verworfen=np.int64(self.verworfen), ref_pegel=np.float32(self.ref_pegel),
                    pfade=np.asarray(self.pfade, dtype=str), kappa=np.float64(self.kappa),
                    registrieren=self.registrieren, gewichten=self.gewichten,
                    min_fuer_verwurf=np.int64(self.min_fuer_verwurf))
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return True

    @classmethod
    def laden(cls, pfad, log=log_print):
        """Versionierten Zustand laden; alte Zustände müssen neu aufgebaut werden."""
        try:
            with np.load(pfad, allow_pickle=False) as d:
                if "version" not in d or int(d["version"]) != 3:
                    raise ValueError("alter Zustand ohne gueltige Randabdeckung; Frames neu einlesen")
                s = cls(log=log, kappa=float(d["kappa"]),
                        registrieren=bool(d["registrieren"]), gewichten=bool(d["gewichten"]),
                        min_fuer_verwurf=int(d["min_fuer_verwurf"]),
                        context_id=str(d["context_id"]) if "context_id" in d else "")
                s.summe = d["summe"].astype(np.float32)
                s.quadr = d["quadr"].astype(np.float32)
                s.gewicht = d["gewicht"].astype(np.float32)
                s.ref_grau = d["ref_grau"].astype(np.float32)
                s.n = int(d["n"])
                counts = d["anzahl"]
                if (not np.issubdtype(counts.dtype, np.integer)
                        or np.any(counts < 0) or np.any(counts > s.n)):
                    raise ValueError("ungueltige Anzahl angenommener Pixel")
                s.anzahl = counts.astype(np.uint32)
                s.verworfen = int(d["verworfen"])
                s.ref_pegel = float(d["ref_pegel"])
                s.pfade = [str(p) for p in d["pfade"]]
                if (s.quadr.shape != s.summe.shape or s.gewicht.shape != s.summe.shape
                        or s.anzahl.shape != s.summe.shape
                        or s.ref_grau.shape != s.summe.shape[:2]):
                    raise ValueError("unpassende Array-Dimensionen")
                if any(not np.isfinite(a).all() for a in
                       (s.summe, s.quadr, s.gewicht, s.ref_grau)):
                    raise ValueError("ungueltige Summen/Gewichte")
                if (s.summe.size == 0 or s.n < 0 or s.verworfen < 0
                        or np.any(s.gewicht < 0) or np.any(s.quadr < 0)
                        or np.any((s.anzahl == 0) != (s.gewicht == 0))
                        or not np.isfinite(s.ref_pegel) or not np.isfinite(s.kappa)
                        or s.kappa <= 0 or s.min_fuer_verwurf < 1):
                    raise ValueError("ungueltige Statistik oder Referenz")
                return s
        except Exception as e:
            log("    Live: gespeicherter Zustand nicht lesbar (%s)" % e)
            return None

    def bericht(self):
        return ("Live-Stapel: %d Frames verrechnet, %d verworfen%s"
                % (self.n, self.verworfen,
                   ", Ausreisser-Verwurf ab dem %d." % self.min_fuer_verwurf
                   if self.n >= self.min_fuer_verwurf else " (noch ohne Ausreisser-Verwurf)"))


def neue_dateien(ordner, bekannt, endungen=(".fit", ".fits", ".fts", ".tif", ".tiff"),
                 *, beobachtet=None, settle=2.0, jetzt=None):
    """Nur Dateien liefern, deren Größe und mtime über das Ruheintervall stabil sind.

    Der Aufrufer behält `beobachtet` zwischen Abfragen. Ohne Verlauf ist noch
    keine Datei nachweislich fertig und es werden keine Kandidaten geliefert.
    """
    jetzt = time.monotonic() if jetzt is None else jetzt
    beobachtet = {} if beobachtet is None else beobachtet
    raus, vorhanden = [], set()
    for name in sorted(os.listdir(ordner)):
        p = os.path.join(ordner, name)
        if p in bekannt or os.path.splitext(name)[1].lower() not in endungen:
            continue
        try:
            if not os.path.isfile(p):
                continue
            st = os.stat(p)
            vorhanden.add(p)
            sig = (st.st_size, st.st_mtime_ns)
            alt = beobachtet.get(p)
            if alt is None or alt[:2] != sig:
                beobachtet[p] = (*sig, jetzt)
            elif st.st_size > 0 and jetzt - alt[2] >= settle:
                raus.append(p)
        except OSError:
            continue
    for p in set(beobachtet) - vorhanden:
        del beobachtet[p]
    return raus
