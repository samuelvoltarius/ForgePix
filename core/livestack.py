#!/usr/bin/env python3
"""
core/livestack.py — laufendes Stapeln: jeder neue Frame wird EINMAL verrechnet.

Warum es das braucht: der bisherige Beobachtungsmodus (`--watch`) stapelt bei jedem neuen Sub
den GESAMTEN Bestand neu. Über eine Nacht mit 200 Aufnahmen ist das quadratischer Aufwand —
beim 200. Sub werden 200 Dateien gelesen, obwohl sich genau eine geändert hat. Hier werden
stattdessen laufende Summen fortgeschrieben; ein neuer Frame kostet immer gleich viel.

Was mitgeführt wird (alles je Pixel):
    n      Anzahl der eingegangenen Werte
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

import numpy as np
import cv2

from constants import log_print, imwrite
import astro


class LiveStack:
    """Laufender Stapel mit Registrierung auf einen festen Referenzframe."""

    def __init__(self, referenz=None, kappa=2.5, min_fuer_verwurf=5, gewichten=True,
                 registrieren=True, log=log_print):
        self.kappa = float(kappa)
        self.min_fuer_verwurf = int(min_fuer_verwurf)
        self.gewichten = bool(gewichten)
        self.registrieren = bool(registrieren)
        self.log = log
        self.summe = None          # Σ w·x
        self.quadr = None          # Σ w·x²
        self.gewicht = None        # Σ w   (je Pixel, weil Ausreisser pixelweise wegfallen)
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
        self.ref_pegel = float(np.median(f))
        self.summe = np.zeros(f.shape, np.float32)
        self.quadr = np.zeros(f.shape, np.float32)
        self.gewicht = np.zeros(f.shape[:2], np.float32)

    def _ausrichten(self, f):
        """Auf die Referenz schieben. Gibt None zurück, wenn es nicht geht — ein Frame, der
        sich nicht ausrichten lässt, gehört NICHT unverschoben in den Stapel; er würde die
        Sterne verdoppeln."""
        if not self.registrieren or self.ref_grau is None:
            return f
        try:
            M = astro._estimate_star_shift(self.ref_grau, astro._gray(f))
        except Exception:
            M = None
        if M is None:
            return None
        return cv2.warpAffine(f, M, (f.shape[1], f.shape[0]),
                              flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)

    # ------------------------------------------------------------ öffentlich
    def hinzufuegen(self, bild_oder_pfad):
        """Einen Frame verrechnen. Gibt True zurück, wenn er im Stapel gelandet ist."""
        if isinstance(bild_oder_pfad, str):
            pfad = bild_oder_pfad
            f = astro._read_float(pfad)
            if f is not None and f.ndim == 2:
                f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
        else:
            pfad, f = None, np.asarray(bild_oder_pfad, np.float32)
        if f is None:
            return False
        if self.summe is None:
            self._referenz_setzen(f)
        elif f.shape != self.summe.shape:
            self.log("    Live: Bildgroesse passt nicht (%s statt %s) — uebersprungen"
                     % (f.shape, self.summe.shape))
            self.verworfen += 1
            return False

        g = self._ausrichten(f)
        if g is None:
            self.log("    Live: Frame liess sich nicht ausrichten — uebersprungen")
            self.verworfen += 1
            return False

        # Pegelangleich wie beim Stapeln am Ende: Dunst und Mondaufgang heben den Himmel,
        # ohne dass das Objekt heller wird.
        g = g + (self.ref_pegel - float(np.median(g)))

        w = 1.0
        if self.gewichten:
            sigma = float(astro._bg_sigma(g))
            w = 1.0 / max(sigma * sigma, 1e-12)

        maske = None
        if self.n >= self.min_fuer_verwurf:
            mittel = self.summe / np.maximum(self.gewicht, 1e-9)[..., None]
            var = (self.quadr / np.maximum(self.gewicht, 1e-9)[..., None]) - mittel * mittel
            std = np.sqrt(np.maximum(var, 0.0))
            maske = np.abs(g - mittel) <= (self.kappa * std + 1e-6)

        if maske is None:
            self.summe += g * w
            self.quadr += g * g * w
            self.gewicht += w
        else:
            mw = maske.astype(np.float32) * w
            self.summe += g * mw
            self.quadr += g * g * mw
            # Das Gewicht ist je Pixel, weil ein Ausreisser nur DORT wegfällt. Ein Frame mit
            # einer Satellitenspur soll nicht komplett verloren gehen — nur die Spur.
            self.gewicht += mw.mean(axis=2) if mw.ndim == 3 else mw
        self.n += 1
        if pfad:
            self.pfade.append(pfad)
        return True

    def ergebnis(self):
        """Der aktuelle Stapel als float32-BGR in [0..1], oder None."""
        if self.summe is None or self.n == 0:
            return None
        return np.clip(self.summe / np.maximum(self.gewicht, 1e-9)[..., None], 0, 1)

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
        np.savez_compressed(
            pfad, summe=self.summe, quadr=self.quadr, gewicht=self.gewicht,
            ref_grau=self.ref_grau, n=np.int64(self.n), verworfen=np.int64(self.verworfen),
            ref_pegel=np.float32(self.ref_pegel), pfade=np.array(self.pfade, dtype=object),
            kappa=np.float32(self.kappa))
        return True

    @classmethod
    def laden(cls, pfad, log=log_print):
        """Gesicherten Zustand zurückholen. Gibt None zurück, wenn die Datei unbrauchbar ist —
        ein halb geschriebener Zustand darf nicht als gültiger Stapel durchgehen."""
        try:
            d = np.load(pfad, allow_pickle=True)
            s = cls(log=log)
            s.summe = d["summe"].astype(np.float32)
            s.quadr = d["quadr"].astype(np.float32)
            s.gewicht = d["gewicht"].astype(np.float32)
            s.ref_grau = d["ref_grau"].astype(np.float32)
            s.n = int(d["n"])
            s.verworfen = int(d["verworfen"])
            s.ref_pegel = float(d["ref_pegel"])
            s.kappa = float(d["kappa"])
            s.pfade = [str(p) for p in d["pfade"]]
            return s
        except Exception as e:
            log("    Live: gespeicherter Zustand nicht lesbar (%s)" % e)
            return None

    def bericht(self):
        return ("Live-Stapel: %d Frames verrechnet, %d verworfen%s"
                % (self.n, self.verworfen,
                   ", Ausreisser-Verwurf ab dem %d." % self.min_fuer_verwurf
                   if self.n >= self.min_fuer_verwurf else " (noch ohne Ausreisser-Verwurf)"))


def neue_dateien(ordner, bekannt, endungen=(".fit", ".fits", ".fts", ".tif", ".tiff")):
    """Dateien im Ordner, die noch nicht verrechnet sind — und die fertig geschrieben sind.

    Die Grössenprüfung ist wichtiger, als sie aussieht: eine Aufnahme, die gerade noch von der
    Kamera geschrieben wird, ist halb da und würde als kaputter Frame in den Stapel wandern.
    """
    raus = []
    for name in sorted(os.listdir(ordner)):
        p = os.path.join(ordner, name)
        if p in bekannt or os.path.splitext(name)[1].lower() not in endungen:
            continue
        try:
            if os.path.getsize(p) > 0:
                raus.append(p)
        except OSError:
            pass
    return raus
