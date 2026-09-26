"""Nach der Registrierung weniger als zwei Aufnahmen: klare Meldung statt Traceback.

Befund vom 26.09.2026: vier sternlose FITS-Lights, `--astro`. Das Protokoll meldete
„registriert 0/4 (Pass 1)“, ging in PHASE:stack und starb an
`max(_zeiten) / min(_zeiten)` mit `ValueError: max() iterable argument is empty` — `aligned`
war leer, und `all([])` ist True. An echten Daten passiert das bei Wolken oder im falschen
Ordner.

Nachgemessen kamen zwei Geschwister dazu: der Drizzle-Zweig meldete an denselben Daten
„Fertig“ mit einem Stapel aus der Referenz allein (die richtet sich immer an sich selbst aus),
und der Hybrid-Weg (Fokus+Astro) starb an `astro.stack([])` mit RuntimeError.
"""
import os
import sys
import tempfile
import unittest

import numpy as np
from astropy.io import fits

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [WURZEL, os.path.join(WURZEL, "core")]
import prozesshilfe  # noqa: E402
import focus_cull_stack as pipeline  # noqa: E402


def _flach(pfad, wert):
    """Gleichmaessige Flaeche ohne jeden Stern — wie eine zugezogene Nacht."""
    kopf = fits.Header()
    kopf["EXPTIME"] = 60.0
    fits.writeto(pfad, np.full((64, 64), wert, np.uint16), kopf, overwrite=True)


def _sternfeld(pfad, saat, n=40, groesse=128):
    """Zufaelliges Sternfeld: Gauss-Sterne auf verrauschtem Himmel."""
    rng = np.random.default_rng(saat)
    bild = rng.normal(1000.0, 5.0, (groesse, groesse))
    yy, xx = np.mgrid[0:groesse, 0:groesse]
    for _ in range(n):
        x, y = rng.uniform(8, groesse - 8, 2)
        bild += rng.uniform(2000, 8000) * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.5 ** 2))
    fits.writeto(pfad, np.clip(bild, 0, 65535).astype(np.uint16), overwrite=True)


def _lauf(*argumente):
    return prozesshilfe.lauf(
        [sys.executable, "-X", "utf8", "-u", os.path.join(WURZEL, "core", "focus_cull_stack.py"),
         *argumente],
        capture_output=True, text=True, encoding="utf-8", cwd=WURZEL, timeout=600)


class TestZuWenigAusgerichtet(unittest.TestCase):

    def test_sternlos_bricht_vor_dem_stapeln_mit_meldung_ab(self):
        """Keine Aufnahme ausrichtbar: Abbruch mit „0 von 4“ und dem Grund, kein Traceback.

        Vorher: PHASE:stack, dann `ValueError: max() iterable argument is empty`. Die
        Oberflaeche sah einen Absturz und niemand erfuhr, dass es an den Sternen lag."""
        with tempfile.TemporaryDirectory() as d:
            ein = os.path.join(d, "lights")
            os.makedirs(ein)
            for i in range(4):
                _flach(os.path.join(ein, "l%d.fits" % i), 1000 + i)
            r = _lauf("--input", ein, "--work", os.path.join(d, "work"), "--astro")
        self.assertEqual(r.returncode, 1, r.stdout[-2000:] + r.stderr[-2000:])
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("Nur 0 von 4 Aufnahmen", r.stderr)
        self.assertIn("nur 0 Sterne gefunden", r.stderr)
        self.assertNotIn("PHASE:stack", r.stdout)

    def test_drizzle_meldet_nicht_fertig_mit_der_referenz_allein(self):
        """Echtes Drizzle, nichts ausrichtbar: Abbruch statt „Fertig“ mit einem Einzelbild.

        Die Referenz richtet sich immer an sich selbst aus. Vorher lief der Lauf mit dieser
        einen Aufnahme bis RESULT: durch, und das Regelwerk gab sogar Rat zu ihr."""
        with tempfile.TemporaryDirectory() as d:
            ein = os.path.join(d, "lights")
            os.makedirs(ein)
            for i in range(4):
                _flach(os.path.join(ein, "l%d.fits" % i), 1000 + i)
            r = _lauf("--input", ein, "--work", os.path.join(d, "work"), "--astro",
                      "--astro-drizzle-true")
        self.assertEqual(r.returncode, 1, r.stdout[-2000:] + r.stderr[-2000:])
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("Nur 1 von 4 Aufnahmen", r.stderr)
        self.assertNotIn("RESULT:", r.stdout)

    def test_hybrid_ohne_ausrichtbare_shots_bricht_mit_meldung_ab(self):
        """Hybrid Fokus+Astro: eine Position ohne ausrichtbare Shots meldet sich, statt
        mit `RuntimeError: keine Frames zum Stapeln` als Traceback zu sterben."""
        with tempfile.TemporaryDirectory() as d:
            ein = os.path.join(d, "hybrid")
            for p in range(2):
                os.makedirs(os.path.join(ein, "p%d" % p))
                for i in range(2):
                    _flach(os.path.join(ein, "p%d" % p, "l%d.fits" % i), 1000 + i)
            r = _lauf("--input", ein, "--work", os.path.join(d, "work"), "--hybrid-fa")
        self.assertEqual(r.returncode, 1, r.stdout[-2000:] + r.stderr[-2000:])
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("Position 1 (p0)", r.stderr)
        self.assertIn("--no-register", r.stderr)

    def test_diagnose_zaehlt_mit_dem_sternsucher_der_registrierung(self):
        """Die Meldung unterscheidet „zu wenig Sterne“ von „Aufnahmen passen nicht“.

        Gezaehlt wird mit `_star_centroids`, dem Sternsucher der Registrierung — ihre Grenze
        von 8 Sternen ist die, an der es scheitert. Hat die Referenz genug Sterne, darf die
        Meldung keine Wolken behaupten, sondern muss auf Ziel/Kamera/Ausrichtung zeigen."""
        with tempfile.TemporaryDirectory() as d:
            leer = os.path.join(d, "leer.fits")
            sterne = os.path.join(d, "sterne.fits")
            _flach(leer, 1000)
            _sternfeld(sterne, saat=1)
            m_leer = pipeline._zu_wenig_ausgerichtet(0, [leer, sterne], leer, "rotate")
            m_rotate = pipeline._zu_wenig_ausgerichtet(1, [leer, sterne], sterne, "rotate")
            m_shift = pipeline._zu_wenig_ausgerichtet(1, [leer, sterne], sterne, "shift")
        self.assertIn("nur 0 Sterne gefunden", m_leer)
        for m in (m_rotate, m_shift):
            self.assertIn("Nur 1 von 2", m)
            self.assertNotIn("Wolken, Dunst", m)
        self.assertIn("passen aber nicht dazu", m_rotate)
        self.assertIn("--astro-align rotate", m_shift)


if __name__ == "__main__":
    unittest.main()
