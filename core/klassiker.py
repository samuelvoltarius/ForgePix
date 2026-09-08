#!/usr/bin/env python3
"""
core/klassiker.py — klassische Astro-Werkzeuge ohne KI.

Vier Verfahren, die es in PixInsight gibt und die ForgePix bisher fehlten. Alle rein
rechnerisch, kein Modell, keine Gewichte, nachvollziehbar:

* **Superbias** — aus wenigen Bias-Aufnahmen ein rauschARMES Bias-Modell bauen.
* **Larson-Sekanina** — der Rotationsgradient, mit dem Kometenschweifstrukturen sichtbar
  werden.
* **Periodische Muster entfernen** — Fourier-Kerbfilter gegen Streifen aus der Ausleseelektronik
  oder aus der Nachfuehrung.
* **Blink** — viele Aufnahmen schnell nacheinander ansehen, um Ausreisser zu finden.

Jedes Verfahren nennt in seiner Beschreibung, was es NICHT kann.
"""
import os

import numpy as np
import cv2

try:
    from constants import log_print
except ImportError:                                     # eigenstaendig aufrufbar
    def log_print(*a, **k):
        print(*a, **k)


# --------------------------------------------------------------------------- Superbias -----
def superbias(bias_bilder, spalten=True, zeilen=True, glatt=8.0, log=log_print):
    """Aus wenigen Bias-Aufnahmen ein rauscharmes Bias-MODELL bauen.

    Ein Master-Bias aus N Aufnahmen hat noch 1/sqrt(N) des Einzelrauschens — bei 20 Aufnahmen
    also 22 %. Dieses Rauschen wird beim Kalibrieren in JEDE Aufnahme hineingerechnet.

    Ein Bias besteht aber fast nur aus STRUKTUR: einem Sockel, Spalten- und Zeilenmustern der
    Ausleseelektronik, und einer glatten Flaeche. Zufaelliges Rauschen gehoert nicht dazu.
    Genau das nutzt Superbias: es behaelt die Struktur und wirft den Rest weg.

    Verfahren: Median ueber die Aufnahmen, dann Zerlegung in
        Sockel + Spaltenmuster + Zeilenmuster + glatte Restflaeche.
    Alles, was danach uebrig bleibt, ist Rauschen und wird verworfen.

    GRENZE: Hotpixel sind PUNKTE, keine Struktur — sie fallen bei dieser Zerlegung heraus.
    Wer sie braucht, nimmt das Dark oder die kosmetische Korrektur. Superbias ersetzt kein
    Dark; es modelliert nur den Ausleseversatz.

    Args:
        bias_bilder: Liste von 2D- oder 3D-Arrays (float, gleiche Form).
        spalten/zeilen: die jeweiligen Muster mitmodellieren.
        glatt: Sigma der Glaettung fuer die Restflaeche (Pixel).

    Returns:
        (modell, bericht) — modell in derselben Form wie die Eingaben.
    """
    stapel = np.stack([np.asarray(b, np.float32) for b in bias_bilder])
    if stapel.ndim not in (3, 4):
        raise ValueError("Bias-Aufnahmen muessen 2D oder 3D sein")
    roh = np.median(stapel, axis=0).astype(np.float32)
    einzel_sigma = float(np.median(np.abs(stapel[0] - np.median(stapel[0])))) * 1.4826
    master_sigma = float(np.median(np.abs(roh - np.median(roh)))) * 1.4826

    def _eine_ebene(m):
        sockel = float(np.median(m))
        rest = m - sockel
        sp = np.zeros_like(rest)
        ze = np.zeros_like(rest)
        if spalten:
            sp = np.median(rest, axis=0)[None, :] * np.ones((rest.shape[0], 1), np.float32)
            rest = rest - sp
        if zeilen:
            ze = np.median(rest, axis=1)[:, None] * np.ones((1, rest.shape[1]), np.float32)
            rest = rest - ze
        flaeche = cv2.GaussianBlur(rest, (0, 0), float(glatt)) if glatt > 0 else rest * 0
        return sockel + sp + ze + flaeche

    if roh.ndim == 3:
        modell = np.stack([_eine_ebene(roh[..., k]) for k in range(roh.shape[2])], axis=-1)
    else:
        modell = _eine_ebene(roh)
    modell_sigma = float(np.median(np.abs(modell - np.median(modell)))) * 1.4826
    bericht = dict(aufnahmen=len(stapel), rauschen_einzeln=einzel_sigma,
                   rauschen_master=master_sigma, rauschen_modell=modell_sigma,
                   minderung_gegen_master=(master_sigma / modell_sigma) if modell_sigma > 0
                   else float("inf"))
    log("    Superbias aus %d Aufnahmen: Rauschen %.6f (einzeln) -> %.6f (Median) -> "
        "%.6f (Modell)" % (len(stapel), einzel_sigma, master_sigma, modell_sigma))
    return modell.astype(np.float32), bericht


# --------------------------------------------------------------- Larson-Sekanina -----------
def larson_sekanina(bild, zentrum=None, winkel=15.0, radius=0.0, staerke=1.0):
    """Rotationsgradient nach Larson-Sekanina — macht Kometenstrukturen sichtbar.

    Ein Komet ist eine helle, glatte Kugel mit schwachen Strahlen und Schalen darin. Die
    Kugel uebertoent alles. Larson-Sekanina zieht vom Bild zwei um `winkel` GEDREHTE Kopien
    ab (im und gegen den Uhrzeigersinn):

        Ergebnis = 2*Bild - Bild(+Winkel) - Bild(-Winkel)

    Alles Rotationssymmetrische — also die Kugel — faellt heraus. Was bleibt, sind die
    Abweichungen davon: Strahlen, Schalen, Jets. Mit `radius` laesst sich zusaetzlich
    radial verschieben (fuer Schalen statt Strahlen).

    GRENZE: das ist ein SICHTBARMACHER, kein photometrisches Verfahren. Die Helligkeiten im
    Ergebnis sind Differenzen und haben keine physikalische Bedeutung mehr. Ein damit
    bearbeitetes Bild taugt nicht zur Messung, nur zum Ansehen.

    Args:
        bild: float [0..1].
        zentrum: (x, y) des Kometenkerns. Ohne Angabe die hellste Stelle.
        winkel: Drehung in Grad (typisch 5 bis 30).
        radius: radiale Verschiebung in Pixeln (0 = nur Rotation).
        staerke: 0 = Original, 1 = voller Gradient.
    """
    a = np.asarray(bild, np.float32)
    grau = a.mean(axis=2) if a.ndim == 3 else a
    if zentrum is None:
        weich = cv2.GaussianBlur(grau, (0, 0), 3.0)
        y, x = np.unravel_index(int(np.argmax(weich)), weich.shape)
        zentrum = (float(x), float(y))
    cx, cy = float(zentrum[0]), float(zentrum[1])
    h, w = grau.shape

    def _drehen(m, grad):
        M = cv2.getRotationMatrix2D((cx, cy), grad, 1.0)
        return cv2.warpAffine(m, M, (w, h), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REPLICATE)

    def _radial(m, dr):
        if abs(dr) < 1e-6:
            return m
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        dx, dy = xx - cx, yy - cy
        r = np.sqrt(dx * dx + dy * dy)
        f = np.where(r > 1e-3, (r + dr) / np.maximum(r, 1e-3), 1.0)
        return cv2.remap(m, (cx + dx * f).astype(np.float32),
                         (cy + dy * f).astype(np.float32),
                         cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    def _eine(m):
        gedreht = _drehen(m, winkel) + _drehen(m, -winkel)
        if abs(radius) > 1e-6:
            gedreht = gedreht + _radial(m, radius) + _radial(m, -radius)
            gradient = 4.0 * m - gedreht
        else:
            gradient = 2.0 * m - gedreht
        return m * (1.0 - staerke) + (m + gradient) * staerke

    if a.ndim == 3:
        return np.clip(np.stack([_eine(a[..., k]) for k in range(a.shape[2])], axis=-1), 0, 1)
    return np.clip(_eine(a), 0, 1)


# ------------------------------------------------------ periodische Muster ------------------
def periodisch_entfernen(bild, staerke=1.0, min_abstand=3, schwelle=4.0, kerbe=1,
                         log=log_print):
    """Periodische Streifen ueber ein Fourier-Kerbfilter entfernen.

    Streifen aus der Ausleseelektronik oder aus einer periodisch schwankenden Nachfuehrung
    sind im Ortsraum ueber das ganze Bild verteilt und darum schwer zu fassen. Im
    FREQUENZRAUM sind sie einzelne helle Punkte. Genau die werden hier gesucht und gedaempft
    ("Kerbfilter"), der Rest bleibt unangetastet.

    Gefunden werden Punkte, die `schwelle` mal ueber dem lokalen Mittel ihrer Umgebung liegen
    — nicht ueber einer festen Grenze, sonst haengt das Ergebnis an der Bildhelligkeit. Die
    Bildmitte (die niedrigen Frequenzen, also der grossflaechige Verlauf) bleibt immer
    verschont; sonst wuerde das Bild flach.

    GRENZE: hilft gegen PERIODISCHE Muster. Ein einzelner Streifen, eine Satellitenspur oder
    ein Gradient sind nicht periodisch und bleiben stehen — dafuer gibt es andere Werkzeuge.

    Args:
        staerke: 0 = aus, 1 = Spitzen ganz auf das lokale Mittel druecken.
        min_abstand: Radius um die Bildmitte, der unangetastet bleibt (Pixel im Frequenzbild).
        schwelle: ab welchem Vielfachen des lokalen Mittels ein Punkt als Stoerung gilt.
        kerbe: wieviele Nachbarpunkte um jede gefundene Stoerung mitgedaempft werden
            (0 = nur die Spitze). Ohne das bleibt rund die Haelfte der Stoerung stehen,
            weil eine Frequenz selten genau auf einem Rasterpunkt liegt.

    Returns:
        (ergebnis, bericht)
    """
    a = np.asarray(bild, np.float32)

    def _eine(m):
        f = np.fft.fftshift(np.fft.fft2(m))
        betrag = np.abs(f)
        # Lokales Mittel im Frequenzbild — ein Median waere hier zu langsam.
        umfeld = cv2.blur(betrag, (9, 9))
        auffaellig = betrag > np.maximum(umfeld, 1e-12) * float(schwelle)
        h, w = m.shape
        yy, xx = np.mgrid[0:h, 0:w]
        mitte = ((yy - h // 2) ** 2 + (xx - w // 2) ** 2) <= float(min_abstand) ** 2
        auffaellig &= ~mitte
        # Die NACHBARN mitnehmen. Eine Stoerfrequenz liegt selten genau auf einem Rasterpunkt;
        # sie verschmiert ueber mehrere (Spektralleckage), und ein Kerbfilter, der nur die
        # Spitze trifft, laesst den Rest stehen. Gemessen an aufgepraegten Streifen mit
        # Periode 9 und 13 px: ohne Aufweitung blieben 48 % des Fehlers stehen, egal bei
        # welcher Schwelle oder Fenstergroesse — das war die Grenze des Verfahrens, nicht der
        # Einstellung.
        if kerbe > 0:
            k = int(2 * kerbe + 1)
            auffaellig = cv2.dilate(auffaellig.astype(np.uint8),
                                    np.ones((k, k), np.uint8)).astype(bool)
            auffaellig &= ~mitte
        if not auffaellig.any():
            return m, 0
        ziel = umfeld[auffaellig]
        skala = np.where(betrag[auffaellig] > 1e-12, ziel / betrag[auffaellig], 1.0)
        skala = 1.0 - float(staerke) * (1.0 - skala)
        f[auffaellig] = f[auffaellig] * skala
        aus = np.real(np.fft.ifft2(np.fft.ifftshift(f))).astype(np.float32)
        return aus, int(auffaellig.sum())

    if a.ndim == 3:
        ebenen, n = [], 0
        for k in range(a.shape[2]):
            e, c = _eine(a[..., k])
            ebenen.append(e)
            n += c
        ergebnis = np.stack(ebenen, axis=-1)
    else:
        ergebnis, n = _eine(a)
    log("    Periodische Muster: %d Frequenzpunkte gedaempft" % n)
    return np.clip(ergebnis, 0, 1), dict(punkte=n, staerke=float(staerke))


# ------------------------------------------------------------------------- Blink -----------
def blink(pfade, ziel, groesse=900, dauer_ms=200, beschriften=True, log=log_print):
    """Viele Aufnahmen als Daumenkino zusammenlegen, um Ausreisser zu finden.

    Der schnellste Weg, eine Serie zu beurteilen: Wolken, Nachfuehrfehler, Satellitenspuren
    und Fokusdrift sieht man im Wechsel sofort, waehrend sie in Einzelbildern untergehen.
    Geschrieben wird ein animiertes GIF — das laesst sich ueberall ansehen, ohne ForgePix.

    GRENZE: das ist eine ANSICHT, keine Messung. Was hier auffaellt, gehoert danach mit der
    Sub-Bewertung nachgemessen; das Auge taeuscht sich bei Helligkeitsunterschieden.
    """
    import astro
    from PIL import Image
    bilder = []
    for i, p in enumerate(pfade):
        try:
            f = astro._read_float(p)
        except Exception as e:
            log("    uebersprungen (%s): %s" % (type(e).__name__, os.path.basename(p)))
            continue
        if f is None:
            continue
        g = astro._gray(f) if f.ndim == 3 else f
        g = astro.autostretch(np.dstack([g] * 3)).mean(axis=2)
        h, w = g.shape
        s = groesse / float(max(h, w))
        klein = cv2.resize(g, (max(1, int(w * s)), max(1, int(h * s))))
        bild = (np.clip(klein, 0, 1) * 255).astype(np.uint8)
        bild = cv2.cvtColor(bild, cv2.COLOR_GRAY2BGR)
        if beschriften:
            cv2.putText(bild, "%d/%d  %s" % (i + 1, len(pfade), os.path.basename(p)[:40]),
                        (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        bilder.append(Image.fromarray(cv2.cvtColor(bild, cv2.COLOR_BGR2RGB)))
    if not bilder:
        raise ValueError("Keine lesbare Aufnahme fuer das Daumenkino")
    bilder[0].save(ziel, save_all=True, append_images=bilder[1:], duration=int(dauer_ms),
                   loop=0)
    log("    Daumenkino: %d Aufnahmen -> %s" % (len(bilder), ziel))
    return dict(aufnahmen=len(bilder), datei=ziel)
