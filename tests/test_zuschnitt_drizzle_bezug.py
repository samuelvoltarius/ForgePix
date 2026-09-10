"""Der Zuschnitt nach Drizzle schnitt zwei Drittel des Feldes weg — wegen des Bezugswerts.

An M51 (203 Aufnahmen, echtes Drizzle 2x) behielt der Zuschnitt 30,4 % des Feldes, und die
Galaxie lag ausserhalb. Die Geometrie der 203 Registrierungen erlaubte 93,3 %. Ursache: die
Schwelle war 80 % des 99. PERZENTILS. Bei der glatten Beitragszahl des normalen Stapels ist das
der echte Hoechstwert; bei den Drizzle-Gewichten lag das 99. Perzentil 10 % ueber dem typischen
Wert (12,82 gegen Median 11,63). 80 % davon sind 88 % des Typischen — ganze Bereiche mit leicht
weniger Gewicht fielen darunter.

Das Modell hier bildet genau diese Lage nach: ein kleiner Bereich 12 % ueber dem Typischen,
ein grosser bei 85 % (zwischen 80 und 88 %), ein duenner Rand bei 20 %.
"""
import os
import sys
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))
import focus_cull_stack as fcs


def _karte():
    h, w = 600, 900
    g = np.full((h, w), 10.0, np.float32)          # typischer Wert
    g[250:350, 350:550] = 11.2                      # oberer Rand der Verteilung, 12 % darueber
    g[:, 600:] = 8.5                                # grosser Bereich bei 85 %
    g[:20, :] = g[-20:, :] = 2.0                    # echter duenner Rand
    g[:, :20] = g[:, -20:] = 2.0
    return g


def _zuschneiden(gewichte, mit_drizzle=True):
    h, w = gewichte.shape
    ergebnis = np.zeros((h, w, 3), np.float32)
    args = types.SimpleNamespace(autocrop=True)
    if mit_drizzle:
        info = {"weights": np.repeat(gewichte[..., None], 3, axis=2),
                "coverage_channels": np.ones((h, w, 3), bool),
                "coverage": np.ones((h, w), bool)}
        aus, _s, _d = fcs._zuschnitt_auf_beitraege(ergebnis, None, args, info)
    else:
        aus, _s, _d = fcs._zuschnitt_auf_beitraege(
            ergebnis, {"beitraege": gewichte, "coverage": np.ones((h, w), np.uint8)}, args, None)
    return aus.shape[:2]


class DrizzleBezug(unittest.TestCase):
    def test_der_bereich_bei_85_prozent_bleibt(self):
        h, w = _zuschneiden(_karte())
        # Mit dem alten Bezug (99. Perzentil = 11,2 -> Schwelle 8,96) fiele der Bereich ab
        # Spalte 600 weg; die Breite laege unter 600. Mit dem Median (10 -> Schwelle 8) bleibt er.
        self.assertGreater(w, 800, "der Bereich bei 85 %% wurde weggeschnitten (Breite %d)" % w)
        self.assertGreater(h, 500)

    def test_ein_echter_duenner_rand_faellt_weiter(self):
        # Gegenprobe: der Fix darf den Zuschnitt nicht abschalten.
        h, w = _zuschneiden(_karte())
        self.assertLessEqual(w, 900 - 2 * 18)
        self.assertLessEqual(h, 600 - 2 * 18)

    def test_der_normale_stapel_bleibt_beim_alten_bezug(self):
        # Beim normalen Stapel ist die Beitragszahl glatt und das 99. Perzentil der echte
        # Hoechstwert; v20 behielt damit belegte 92 %. Dort aendert sich nichts: dieselbe
        # Karte als Beitragszahl verliert den 85-%-Bereich weiterhin.
        h, w = _zuschneiden(_karte(), mit_drizzle=False)
        self.assertLess(w, 620)


if __name__ == "__main__":
    unittest.main()


class DuennsteStelle(unittest.TestCase):
    """Die Berichtszeile "Duennste Stelle jetzt X % der Mitte" darf nicht von Pixeln AUSSERHALB
    des behaltenen Bereichs heruntergezogen werden.

    Gemessen wurde auf dem 3x3-Median bis exakt an den Rand. An einer Ecke, an der zwei
    Randstreifen zusammenstossen, stellen die Aussenpixel 5 von 9 Werten — an dieser Karte kam
    "20 % der Mitte" heraus, obwohl im Rechteck kein Pixel unter 85 % lag.
    """

    def test_die_zeile_nennt_den_wert_im_rechteck(self):
        import contextlib
        import io
        import re
        puffer = io.StringIO()
        with contextlib.redirect_stdout(puffer):
            _zuschneiden(_karte())
        treffer = re.search(r"Duennste Stelle jetzt (\d+) %", puffer.getvalue())
        self.assertIsNotNone(treffer, puffer.getvalue())
        self.assertGreaterEqual(int(treffer.group(1)), 80, puffer.getvalue())
