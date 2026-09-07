#!/usr/bin/env python3
"""
ForgePix — der Astro-Zuschnitt auf die volle Beitragszahl.

    python3 tests/test_astro_zuschnitt.py

Beim Ausrichten wandern die Aufnahmen gegeneinander. Am Bildrand tragen darum nur wenige Subs
bei, und diese Pixel rauschen entsprechend staerker — das Rauschen geht mit 1/Wurzel(n). An
einem echten Stapel gemessen (IC 434, 133 von 224 Subs, Seestar S30): die aeusseren 5 px
rauschten **1,6-mal** so stark wie die Mitte, bei 80 px noch 1,3-mal. Nach dem Strecken ein
deutlich sichtbarer blau-roter Saum.

Der Saum verdirbt nicht nur den Anblick, er verdirbt die **Messung**. Am ausgelieferten Bild
nachgerechnet:

    ganzes Bild           Gradient 41,9 %     Rand oben  G/R 0,680
    40 px Rand abgezogen  Gradient 24,7 %     Mitte      G/R 0,963

Darum wird zugeschnitten, BEVOR der Messbericht entsteht.

**Zwei Anlaeufe waren falsch, beide sind hier als Test festgehalten.**

1. Zeilen nehmen, in denen JEDES Pixel genug Beitraege hat (`_gut.all(axis=1)`). Die
   Sigma-Rejection verwirft aber ueberall verstreute Einzelpixel — damit qualifizierte sich
   keine einzige Zeile, und der Zuschnitt tat **wortlos nichts**.

2. Der Median je Zeile und je Spalte. Der ist robust gegen die verstreuten Loecher, sieht aber
   bei **Bildfeldrotation** die duenne Stelle nicht: der Seestar steht azimutal, das Feld dreht
   sich, und die Schnittmenge aller Aufnahmen ist dann kein achsenparalleles Rechteck mehr. Die
   duennen Stellen sitzen an den ENDEN der Zeilen, der Median in ihrer Mitte merkt davon
   nichts. An einer nachgebauten Beitragskarte (133 Aufnahmen, 8 Grad Rotation) gemessen:

       ohne Zuschnitt          100,0 % Flaeche   Rauschen am duennsten Punkt 1,83-fach
       Median, Schwelle 0,80    90,6 %                                       1,44-fach
       Median, Schwelle 0,95    86,2 %                                       1,24-fach
       5. Perzentil je Zeile    21,3 %                                       1,00-fach
       Schrumpfen (jetzt)       73,6 %                                       1,11-fach

   Das reine Perzentil je Zeile wirft vier Fuenftel des Bildes weg.

3. Von aussen die duennste der vier Kanten abtragen, bis die duennste Stelle im Kasten passt.
   Klingt richtig, ist es aber nicht: eine duenne **Ecke** gehoert zu ZWEI Kanten. Die
   betroffene Kante sieht darum dauerhaft schlecht aus und wird bis zur Flaechengrenze
   abgetragen, waehrend die Ecke bleibt. An einer Karte ganz OHNE Rotation gemessen kam ein
   Streifen von Spalte 122 bis 256 heraus statt des vollen Bildes.

Richtig — und exakt statt geraten — ist das **groesste achsenparallele Rechteck** innerhalb der
gut abgedeckten Flaeche (Histogramm-Verfahren, O(h*w)). Damit steuert die Schwelle die
QUALITAET, und die Flaeche ergibt sich:

       Rotation  0 Grad   90,9 % Flaeche   Rauschen 1,14-fach
       Rotation  8 Grad   78,1 %                    1,15-fach
       Rotation 20 Grad   58,3 %                    1,14-fach
"""
import os
import sys
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))


ANTEIL = 0.8


def _glaetten(voll):
    """Verstreute Rejection-Loecher wegraeumen, den geometrischen Abfall behalten."""
    return cv2.medianBlur(np.asarray(voll, np.float32), 3)


def _groesstes_rechteck(maske):
    """Dieselbe Rechnung wie in `focus_cull_stack._groesstes_rechteck`."""
    h, w = maske.shape[:2]
    hoehen = np.zeros(w, np.int32)
    bestes = (0, 0, 0, 0, 0)
    for y in range(h):
        hoehen = np.where(maske[y], hoehen + 1, 0)
        stapel = []
        for x in range(w + 1):
            hier = int(hoehen[x]) if x < w else 0
            start = x
            while stapel and stapel[-1][1] >= hier:
                sx, sh = stapel.pop()
                flaeche = sh * (x - sx)
                if flaeche > bestes[0]:
                    bestes = (flaeche, y - sh + 1, y + 1, sx, x)
                start = sx
            stapel.append((start, hier))
    return bestes[1:] if bestes[0] else None


def _schrumpfen(voll, anteil=ANTEIL):
    """Der Zuschnitt, wie ihn die Pipeline rechnet."""
    glatt = _glaetten(voll)
    h, w = glatt.shape[:2]
    grenze = anteil * float(np.percentile(glatt, 99.0))
    k = max(1, min(h, w) // 300)
    maske = (glatt >= grenze).astype(np.uint8)
    if k > 1:
        maske = cv2.erode(maske, np.ones((k, k), np.uint8))[::k, ::k]
    kasten = _groesstes_rechteck(maske.astype(bool))
    if kasten is None:
        return None
    return (kasten[0] * k, min(kasten[1] * k, h), kasten[2] * k, min(kasten[3] * k, w))


def _rauschfaktor(voll, kasten):
    """Um welchen Faktor rauscht die duennste Stelle im Kasten staerker als die Mitte?"""
    y0, y1, x0, x1 = kasten[:4]
    glatt = _glaetten(voll)
    h, w = glatt.shape[:2]
    mitte = float(np.median(glatt[h // 3:2 * h // 3, w // 3:2 * w // 3]))
    duenn = float(glatt[y0:y1, x0:x1].min())
    return (mitte / max(duenn, 1e-9)) ** 0.5


def _flaeche(voll, kasten):
    y0, y1, x0, x1 = kasten[:4]
    h, w = voll.shape[:2]
    return 100.0 * (y1 - y0) * (x1 - x0) / (h * w)


def _karte(rotation_grad=0.0, drift_px=6, n=60, h=480, w=270, loecher=True, seed=3):
    """Eine Beitragskarte, wie sie beim Stapeln entsteht: gedrehte und verschobene
    Vollbild-Masken aufsummiert, plus verstreute Rejection-Loecher."""
    rng = np.random.default_rng(seed)
    acc = np.zeros((h, w), np.float32)
    eins = np.ones((h, w), np.float32)
    for i in range(n):
        grad = rotation_grad * (i / (n - 1.0) - 0.5) * 2.0 if n > 1 else 0.0
        M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), grad, 1.0)
        M[0, 2] += rng.normal(0, drift_px)
        M[1, 2] += rng.normal(0, drift_px)
        acc += cv2.warpAffine(eins, M, (w, h), flags=cv2.INTER_NEAREST,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    if loecher:
        ys = rng.integers(0, h, h * w // 30)
        xs = rng.integers(0, w, h * w // 30)
        acc[ys, xs] *= 0.3
    return acc


class TestOhneRotation(unittest.TestCase):

    def test_der_rand_wird_gefunden_und_der_rest_bleibt(self):
        voll = _karte(rotation_grad=0.0)
        kasten = _schrumpfen(voll)
        self.assertGreater(kasten[0], 0, "oben wurde gar nichts abgetragen")
        self.assertGreater(_flaeche(voll, kasten), 85.0,
                           "ohne Rotation darf kaum Flaeche verlorengehen")
        self.assertLess(_rauschfaktor(voll, kasten), 1.20)

    def test_das_greedy_verfahren_fraesst_sich_fest(self):
        """Der dritte falsche Anlauf, als Test festgehalten. Immer die duennste Kante
        abtragen heisst: eine duenne ECKE laesst ihre beiden Kanten dauerhaft schlecht
        aussehen. Hier, ganz ohne Rotation, blieb davon ein senkrechter Streifen uebrig."""
        voll = _karte(rotation_grad=0.0)
        glatt = _glaetten(voll)
        h, w = glatt.shape
        grenze = ANTEIL * float(np.percentile(glatt, 99.0))
        y0, y1, x0, x1 = 0, h, 0, w
        schritt = max(2, min(h, w) // 200)
        while float(glatt[y0:y1, x0:x1].min()) < grenze:
            if (y1 - y0) * (x1 - x0) <= 0.5 * h * w:
                break
            kanten = ((float(glatt[y0:y0 + schritt, x0:x1].min()), "y0"),
                      (float(glatt[y1 - schritt:y1, x0:x1].min()), "y1"),
                      (float(glatt[y0:y1, x0:x0 + schritt].min()), "x0"),
                      (float(glatt[y0:y1, x1 - schritt:x1].min()), "x1"))
            welche = min(kanten)[1]
            if welche == "y0":
                y0 += schritt
            elif welche == "y1":
                y1 -= schritt
            elif welche == "x0":
                x0 += schritt
            else:
                x1 -= schritt
        seitenverhaeltnis = (x1 - x0) / float(y1 - y0)
        self.assertLess(seitenverhaeltnis, 0.45,
                        "die Gegenprobe traegt nicht: das greedy-Verfahren muss hier zu "
                        "einem Streifen entarten, sonst prueft der Test nichts")
        neu = _schrumpfen(voll)
        self.assertGreater((neu[3] - neu[2]) / float(neu[1] - neu[0]), 0.45,
                           "das neue Verfahren entartet genauso")

    def test_verstreute_rejection_verhindert_den_zuschnitt_nicht(self):
        """Der erste falsche Anlauf. Mit `all()` statt eines Perzentils war hier keine
        einzige Zeile brauchbar — und die Pipeline schnitt wortlos gar nichts."""
        voll = _karte(rotation_grad=0.0)
        streng = voll >= 0.8 * voll.max()
        self.assertEqual(len(np.where(streng.all(axis=1))[0]), 0,
                         "die Gegenprobe traegt nicht: hier muss die strenge Variante "
                         "versagen, sonst prueft der Test nichts")
        self.assertLess(_rauschfaktor(voll, _schrumpfen(voll)), 1.20)

    def test_ein_vollflaechiger_stapel_wird_nicht_beschnitten(self):
        """Die Gegenprobe: ohne Randabfall darf nichts wegfallen."""
        voll = np.full((300, 200), 60.0, np.float32)
        rng = np.random.default_rng(1)
        voll[rng.integers(0, 300, 2000), rng.integers(0, 200, 2000)] *= 0.3
        self.assertGreater(_flaeche(voll, _schrumpfen(voll)), 97.0,
                           "eine gleichmaessige Karte darf praktisch nichts verlieren")


class TestMitFeldrotation(unittest.TestCase):
    """Der zweite falsche Anlauf, und warum er falsch war."""

    def setUp(self):
        self.voll = _karte(rotation_grad=8.0)

    def _median_verfahren(self, voll, anteil=ANTEIL):
        """Das abgeloeste Verfahren, zum Vergleich."""
        zp = np.median(voll, axis=1)
        sp = np.median(voll, axis=0)
        grenze = anteil * float(max(zp.max(), sp.max()))
        z = np.where(zp >= grenze)[0]
        s = np.where(sp >= grenze)[0]
        return int(z[0]), int(z[-1]) + 1, int(s[0]), int(s[-1]) + 1

    def test_der_median_sieht_die_duenne_stelle_nicht(self):
        """Die Begruendung fuer den Umbau. Der Median je Zeile laesst bei Rotation eine
        Stelle stehen, die deutlich staerker rauscht — genau der Rest-Farbstich, der am
        fertigen IC-434-Bild links und rechts noch zu sehen war (G/B 0,78 gegen 1,00 in der
        Mitte)."""
        alt = self._median_verfahren(self.voll)
        self.assertGreater(_rauschfaktor(self.voll, alt), 1.25,
                           "die Gegenprobe traegt nicht: das alte Verfahren muss hier "
                           "sichtbar danebenliegen")

    def test_das_neue_verfahren_erreicht_die_schwelle(self):
        neu = _schrumpfen(self.voll)
        self.assertLess(_rauschfaktor(self.voll, neu), 1.20,
                        "die duennste Stelle rauscht immer noch zu stark")

    def test_es_bleibt_genug_bild_uebrig(self):
        """Die Gegenprobe zur vorigen: sauber waere auch ein 10x10-Ausschnitt. Das reine
        Perzentil je Zeile lieferte hier 21 % der Flaeche — unbrauchbar."""
        self.assertGreater(_flaeche(self.voll, _schrumpfen(self.voll)), 70.0)

    def test_starke_rotation_kostet_flaeche_aber_bleibt_sauber(self):
        """Bei starker Rotation ist die Schnittmenge klein — dann MUSS Flaeche fallen. Die
        Qualitaet bleibt trotzdem: die Schwelle steuert das Rauschen, nicht die Groesse."""
        voll = _karte(rotation_grad=25.0)
        kasten = _schrumpfen(voll)
        self.assertLess(_flaeche(voll, kasten), 70.0,
                        "bei 25 Grad Rotation kann nicht fast alles bleiben")
        self.assertLess(_rauschfaktor(voll, kasten), 1.20)


class TestPhysik(unittest.TestCase):

    def test_weniger_beitraege_heisst_mehr_rauschen(self):
        """Die Begruendung des ganzen Zuschnitts, nachgerechnet: das Rauschen des Mittelwerts
        geht mit 1/Wurzel(n)."""
        rng = np.random.default_rng(11)
        mitte = rng.normal(0, 1.0, (133, 5000)).mean(axis=0).std()
        rand = rng.normal(0, 1.0, (20, 5000)).mean(axis=0).std()
        self.assertAlmostEqual(rand / mitte, (133 / 20.0) ** 0.5, delta=0.15)


class TestInDerPipeline(unittest.TestCase):

    def _quelle(self):
        import io
        pfad = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core",
                            "focus_cull_stack.py")
        with io.open(pfad, encoding="utf-8") as fh:
            return fh.read()

    def test_der_astro_modus_wendet_autocrop_an(self):
        self.assertIn('stack_info.get("beitraege")', self._quelle(),
                      "der Astro-Modus nutzt die Beitragszahl nicht")

    def test_zugeschnitten_wird_vor_dem_messbericht(self):
        """Sonst misst der Bericht weiter ueber den verrauschten Rand — und das Regelwerk
        gibt seinen Rat auf verdorbenen Zahlen."""
        q = self._quelle()
        schnitt = q.index("result, stack_info, drizzle_info = _zuschnitt_auf_beitraege(")
        schreiben = q.index("out = _astro_write(", schnitt)
        bericht = q.index("_b = messbericht.erstellen(")
        self.assertLess(schnitt, schreiben, "erst schneiden, dann schreiben")
        self.assertLess(schnitt, bericht, "erst schneiden, dann messen")

    def test_kein_stiller_verzicht(self):
        """Jeder Weg, auf dem NICHT zugeschnitten wird, muss das sagen."""
        q = self._quelle().split("def _zuschnitt_auf_beitraege")[1].split("\ndef ")[0]
        self.assertIn("Zuschnitt nicht moeglich: das Stapelverfahren liefert keine", q)
        self.assertIn("Zuschnitt nicht moeglich: die Beitragszahl enthaelt keine", q)
        self.assertIn("Zuschnitt uebersprungen: nirgends erreichen die Beitraege", q)

    def test_das_protokoll_nennt_das_restrauschen(self):
        """Eine Zahl, die der Benutzer beurteilen kann: wie stark rauscht die duennste
        behaltene Stelle noch gegenueber der Mitte?"""
        q = self._quelle().split("def _zuschnitt_auf_beitraege")[1].split("\ndef ")[0]
        self.assertIn("Duennste Stelle jetzt", q)
        self.assertIn("-fache", q)

    def test_die_stapelfunktion_liefert_die_beitraege(self):
        import astro
        import inspect
        quelle = inspect.getsource(astro.stack)
        self.assertIn("beitraege=cnt", quelle,
                      "der sigma/winsor-Weg gibt die Beitragszahl nicht zurueck")
        self.assertIn("beitraege=anzahl_out", quelle,
                      "der linearfit-Weg gibt die Beitragszahl nicht zurueck")


if __name__ == "__main__":
    unittest.main(verbosity=2)
