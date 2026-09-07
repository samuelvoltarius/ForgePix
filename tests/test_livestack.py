#!/usr/bin/env python3
"""
ForgePix — Tests für das inkrementelle Live-Stacking (core/livestack.py).

    python3 tests/test_livestack.py     # oder: python3 -m unittest discover -s tests

Der bisherige Beobachtungsmodus stapelt bei jeder neuen Aufnahme den GESAMTEN Bestand neu — beim
200. Sub werden 200 Dateien gelesen, obwohl sich genau eine geändert hat. Hier werden laufende
Summen fortgeschrieben.

An echten Daten gegengeprüft (10 bzw. 12 Subs M27, ASI294MC Pro):
    mittlere Abweichung zum Stapeln am Ende: 0,000832 = 0,077 % der Bildspanne
    SNR live 62,90 gegen 62,94 am Ende
    Ergebnis nach jedem Sub: 2,8 s live gegen 7,5 s jedes Mal neu (Faktor 2,6 bei 12 Subs,
    und der Abstand wächst, weil das Neustapeln quadratisch zulegt)
    gespeicherter und wieder geladener Zustand: bitgleich

Die eine echte Einschränkung ist die Ausreisser-Erkennung: am Ende sind alle Werte gleichzeitig
da, hier wird ein neuer Wert gegen die Statistik der bisherigen geprüft. Darum wird erst ab
`min_fuer_verwurf` überhaupt verworfen.
"""
import os
import sys
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import astro       # noqa: E402
import livestack   # noqa: E402
from constants import imwrite  # noqa: E402


def _stille(*a, **k):
    pass


class TestFeldrotationUndWiederholung(unittest.TestCase):
    """Zwei Fehler, die am echten Live-Lauf aufgefallen sind (IC 417, 10 Seestar-Aufnahmen).

    1. **Ausrichtung nur als Verschiebung.** Der Live-Stapler nahm `_estimate_star_shift`.
       Der Seestar steht azimutal, sein Bildfeld dreht sich im Lauf der Nacht — es kamen
       4 von 10 Aufnahmen in den Stapel, der Rest wurde abgelehnt.
    2. **Endloses Wiederholen.** Der Beobachtungsmodus merkte sich nur ERFOLGREICHE
       Aufnahmen. Ein Frame, der sich nie ausrichten laesst, wurde damit alle zwei Sekunden
       neu versucht: **231 identische Meldungen** im Protokoll fuer zehn Dateien.
    """

    def _sternfeld(self, seed=5, winkel=0.0):
        rng = np.random.default_rng(seed)
        h = w = 160
        g = np.full((h, w), 0.03, np.float32)
        for _ in range(60):
            p = np.zeros((h, w), np.float32)
            p[int(rng.integers(20, h - 20)), int(rng.integers(20, w - 20))] = 1.0
            g += cv2.GaussianBlur(p, (0, 0), 1.6) * float(rng.uniform(2, 8))
        g = np.clip(g, 0, 1)
        if winkel:
            M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), winkel, 1.0)
            g = cv2.warpAffine(g, M, (w, h), flags=cv2.INTER_LANCZOS4,
                               borderMode=cv2.BORDER_REPLICATE)
        return np.dstack([g] * 3).astype(np.float32)

    def test_gedrehter_frame_kommt_in_den_stapel(self):
        s = livestack.LiveStack(gewichten=False, log=_stille)
        self.assertTrue(s.hinzufuegen(self._sternfeld()))
        self.assertTrue(s.hinzufuegen(self._sternfeld(winkel=8.0)),
                        "ein gedrehter Frame wurde abgelehnt — Feldrotation nicht behandelt")
        self.assertEqual(s.n, 2)

    def test_gegenprobe_reine_verschiebung_registriert_falsch(self):
        """Die Gegenprobe — und zugleich der schlimmere Teil des Befunds.

        Bei 8 Grad Drehung gibt `_estimate_star_shift` nicht etwa None zurueck, sondern eine
        VERSCHIEBUNG (gemessen: 3,8 / 6,3 px). Es lehnt den Frame also nicht ab, es registriert
        ihn falsch — und der Stapel bekommt doppelte Sterne, ohne dass sich irgendwo etwas
        meldet. Geprueft wird darum am Ergebnis: der Stapel mit reiner Verschiebung muss
        deutlich schlechter zur Referenz passen als der mit Drehung.
        """
        ref_bild = self._sternfeld()
        gedreht = self._sternfeld(winkel=8.0)
        ref_grau = astro._gray(ref_bild)

        def guete(schaetzer):
            s = livestack.LiveStack(gewichten=False, log=_stille)
            s.hinzufuegen(ref_bild)
            with patch("livestack.astro._estimate_star_transform_robust", schaetzer):
                s.hinzufuegen(gedreht)
            e = astro._gray(s.ergebnis())
            a, b = ref_grau.ravel() - ref_grau.mean(), e.ravel() - e.mean()
            return float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-12))

        mit_drehung = guete(astro._estimate_star_transform_robust)
        nur_schiebung = guete(astro._estimate_star_shift)
        self.assertGreater(mit_drehung, nur_schiebung + 0.05,
                           "mit Drehung %.3f, ohne %.3f — die Testszene dreht sich nicht genug"
                           % (mit_drehung, nur_schiebung))

    def test_nicht_ausrichtbar_ist_endgueltig_nicht_vorlaeufig(self):
        """False heisst "entschieden", None heisst "spaeter noch einmal". Ohne diesen
        Unterschied wiederholt der Beobachtungsmodus endlos."""
        s = livestack.LiveStack(gewichten=False, log=_stille)
        self.assertTrue(s.hinzufuegen(self._sternfeld()))
        leer = np.full((160, 160, 3), 0.03, np.float32)      # keine Sterne, nicht ausrichtbar
        self.assertIs(s.hinzufuegen(leer), False,
                      "ein nicht ausrichtbarer Frame muss endgueltig abgelehnt werden")

    def test_unlesbare_datei_wird_spaeter_erneut_versucht(self):
        """Eine halb geschriebene Datei ist etwas anderes — die muss wiederkommen duerfen."""
        def kaputt(_p):
            raise OSError("noch im Schreiben")
        s = livestack.LiveStack(gewichten=False, log=_stille)
        s.reader = kaputt
        self.assertIsNone(s.hinzufuegen("egal.fit"),
                          "eine noch nicht lesbare Datei darf nicht endgueltig abgelehnt werden")

    def test_falsche_bildgroesse_ist_endgueltig(self):
        s = livestack.LiveStack(gewichten=False, log=_stille)
        self.assertTrue(s.hinzufuegen(self._sternfeld()))
        self.assertIs(s.hinzufuegen(np.full((80, 80, 3), 0.03, np.float32)), False)


class TestLiveStack(unittest.TestCase):
    def test_registered_border_keeps_original_sky_and_weight(self):
        # The missing left eight columns must keep the reference alone. A
        # gradient also catches level normalization over different sky regions.
        x = np.arange(32, dtype=np.float32)[None, :, None] * .01
        reference = np.broadcast_to(x + np.array([.1, .2, .3], np.float32), (32, 32, 3)).copy()
        frame = np.full_like(reference, .9)
        frame[:, :24] = reference[:, 8:]
        s = livestack.LiveStack(gewichten=False, log=_stille)
        self.assertTrue(s.hinzufuegen(reference))
        shift = np.array([[1., 0., 8.], [0., 1., 0.]])
        with patch("livestack.astro._estimate_star_transform_robust", return_value=shift):
            self.assertTrue(s.hinzufuegen(frame))
        np.testing.assert_allclose(s.ergebnis(), reference, atol=1e-7)
        np.testing.assert_array_equal(s.gewicht[:, :8], 1)
        np.testing.assert_array_equal(s.gewicht[:, 8:], 2)
        np.testing.assert_array_equal(s.anzahl, s.gewicht)

    def test_lanczos_footprint_excludes_edges_from_signal_and_noise(self):
        reference = np.full((40, 40, 3), [.1, .2, .3], np.float32)
        frame = reference + .1
        frame[:2] = .95
        frame[-2:] = .95
        frame[:, :2] = .95
        frame[:, -2:] = .95
        s = livestack.LiveStack(log=_stille)
        self.assertTrue(s.hinzufuegen(reference))
        before_weight = s.gewicht.copy()
        shift = np.array([[1., 0., .5], [0., 1., .5]])
        with patch("livestack.astro._estimate_star_transform_robust", return_value=shift):
            self.assertTrue(s.hinzufuegen(frame))
        # The central sky has identical noise and a removable +0.1 pedestal;
        # bright edges and zero padding must affect neither its level nor weight.
        np.testing.assert_allclose(s.ergebnis()[10:30, 10:30], reference[10:30, 10:30], atol=1e-6)
        np.testing.assert_allclose(s.gewicht[15, 15], 2 * before_weight[15, 15], rtol=1e-6)
        np.testing.assert_array_equal(s.gewicht[0], before_weight[0])
        np.testing.assert_allclose(s.ergebnis()[0], reference[0], atol=1e-7)
        np.testing.assert_array_equal(s.anzahl[0], 1)

    def test_newly_covered_pixels_are_not_rejected_and_resume_keeps_counts(self):
        reference = np.full((32, 32, 3), .2, np.float32)
        s = livestack.LiveStack(gewichten=False, log=_stille, context_id="calibration-and-options-hash")
        s.hinzufuegen(reference)
        shift = np.array([[1., 0., 12.], [0., 1., 0.]])
        with patch("livestack.astro._estimate_star_transform_robust", return_value=shift):
            for _ in range(5):
                self.assertTrue(s.hinzufuegen(reference))
        path = os.path.join(self.d, "coverage.npz")
        s.speichern(path)
        resumed = livestack.LiveStack.laden(path, log=_stille)
        self.assertIsNotNone(resumed)
        self.assertEqual(resumed.context_id, "calibration-and-options-hash")
        np.testing.assert_array_equal(resumed.anzahl, s.anzahl)
        next_frame = reference.copy()
        next_frame[16, 2, 0] = .4  # only its second actual sample: not enough to reject
        next_frame[16, 20, 0] = .9  # seventh sample: reject this one channel
        identity = np.array([[1., 0., 0.], [0., 1., 0.]])
        with patch("livestack.astro._estimate_star_transform_robust", return_value=identity):
            for state in (s, resumed):
                self.assertTrue(state.hinzufuegen(next_frame))
        np.testing.assert_allclose(s.ergebnis()[16, 2], [.3, .2, .2], atol=1e-6)
        np.testing.assert_allclose(s.ergebnis()[16, 20], [.2, .2, .2], atol=1e-6)
        np.testing.assert_array_equal(s.anzahl[16, 2], [2, 2, 2])
        np.testing.assert_array_equal(s.anzahl[16, 20], [6, 7, 7])
        for attribute in ("summe", "quadr", "gewicht", "anzahl"):
            np.testing.assert_array_equal(getattr(s, attribute), getattr(resumed, attribute))

    def test_registration_without_overlap_does_not_change_stack(self):
        s = livestack.LiveStack(gewichten=False, log=_stille)
        reference = np.full((32, 32, 3), .2, np.float32)
        s.hinzufuegen(reference)
        shift = np.array([[1., 0., 100.], [0., 1., 0.]])
        with patch("livestack.astro._estimate_star_transform_robust", return_value=shift):
            self.assertFalse(s.hinzufuegen(reference))
        self.assertEqual((s.n, s.verworfen), (1, 1))
        np.testing.assert_array_equal(s.anzahl, 1)
        np.testing.assert_array_equal(s.ergebnis(), reference)

    def test_checkpoint_without_coverage_counts_requires_rebuild(self):
        s = livestack.LiveStack(registrieren=False, gewichten=False, log=_stille)
        s.hinzufuegen(np.full((12, 12, 3), .2, np.float32))
        path = os.path.join(self.d, "old-coverage.npz")
        s.speichern(path)
        with np.load(path, allow_pickle=False) as archive:
            original = {key: archive[key].copy() for key in archive.files}
        for value in (-np.ones_like(s.anzahl, dtype=np.int32), s.anzahl + 1,
                      np.zeros_like(s.anzahl)):
            np.savez(path, **dict(original, anzahl=value))
            self.assertIsNone(livestack.LiveStack.laden(path, log=_stille))
        np.savez(path, **dict(original, version=np.int64(2)))
        self.assertIsNone(livestack.LiveStack.laden(path, log=_stille))

    def test_invalid_pixels_do_not_poison_running_stack(self):
        s = livestack.LiveStack(registrieren=False, gewichten=False, log=_stille)
        good = np.full((12, 12, 3), .2, np.float32)
        bad = good.copy()
        bad[3, 4, 0] = np.nan
        self.assertFalse(s.hinzufuegen(bad))
        self.assertIsNone(s.summe)
        self.assertTrue(s.hinzufuegen(good))
        before = s.ergebnis().copy()
        self.assertFalse(s.hinzufuegen(bad))
        self.assertEqual(s.n, 1)
        np.testing.assert_array_equal(s.ergebnis(), before)

    def test_corrupt_checkpoint_statistics_are_rejected(self):
        s = livestack.LiveStack(registrieren=False, gewichten=False, log=_stille)
        s.hinzufuegen(np.full((12, 12, 3), .2, np.float32))
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "state.npz")
            s.speichern(path)
            with np.load(path, allow_pickle=False) as archive:
                original = {key: archive[key].copy() for key in archive.files}
            for key, value in (("ref_pegel", np.nan), ("kappa", np.inf),
                               ("n", -1), ("gewicht", -np.ones_like(s.gewicht)),
                               ("ref_grau", np.full_like(s.ref_grau, np.nan))):
                data = dict(original)
                data[key] = value
                np.savez(path, **data)
                self.assertIsNone(livestack.LiveStack.laden(path, log=_stille), key)


    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_live_")
        self.h = self.w = 160
        rng = np.random.default_rng(5)
        g = np.full((self.h, self.w), 0.06, np.float32)
        neb = np.zeros((self.h, self.w), np.float32)
        cv2.circle(neb, (self.w // 2, self.h // 2), 30, 1.0, -1)
        g += cv2.GaussianBlur(neb, (0, 0), 12) * 0.05
        self.sterne = [(int(rng.integers(20, self.w - 20)), int(rng.integers(20, self.h - 20)))
                       for _ in range(25)]
        for x, y in self.sterne:
            p = np.zeros((self.h, self.w), np.float32)
            p[y, x] = 1.0
            g += cv2.GaussianBlur(p, (0, 0), 1.5) * float(rng.uniform(3, 9))
        self.wahr = np.clip(g, 0, 1)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _serie(self, n=10, unter="a", satellit_in=None, seed=7):
        rng = np.random.default_rng(seed)
        d = os.path.join(self.d, unter)
        os.makedirs(d, exist_ok=True)
        pfade = []
        for i in range(n):
            f = np.clip(self.wahr
                        + rng.normal(0, 0.004, (self.h, self.w)).astype(np.float32), 0, 1)
            if satellit_in is not None and i == satellit_in:
                cv2.line(f, (10, 20), (self.w - 10, self.h - 20), 0.9, 2)
            p = os.path.join(d, "s_%02d.tif" % i)
            imwrite(p, np.clip(np.dstack([f] * 3) * 65535, 0, 65535).astype(np.uint16))
            pfade.append(p)
        return pfade

    def test_ergebnis_entspricht_dem_stapeln_am_ende(self):
        """Der Punkt, an dem alles hängt: schneller darf es sein, anders nicht."""
        pfade = self._serie()
        ls = livestack.LiveStack(registrieren=False, gewichten=False, log=_stille)
        for p in pfade:
            ls.hinzufuegen(p)
        live = ls.ergebnis()
        ende = np.mean(np.stack([astro._read_float(p) for p in pfade]), axis=0)
        abw = float(np.abs(live - ende).mean())
        spanne = float(ende.max() - ende.min())
        self.assertLess(abw / max(spanne, 1e-9), 0.01,
                        "Abweichung %.5f = %.2f %% der Bildspanne"
                        % (abw, 100 * abw / max(spanne, 1e-9)))

    def test_satellit_wird_verworfen(self):
        """Ausreisser-Verwurf gegen die laufende Statistik — der Satellit sitzt bewusst SPÄT
        in der Serie, denn vorher ist die Statistik noch zu dünn."""
        pfade = self._serie(n=12, unter="sat", satellit_in=9)
        ls = livestack.LiveStack(registrieren=False, log=_stille)
        for p in pfade:
            ls.hinzufuegen(p)
        erg = astro._gray(ls.ergebnis())
        spur = np.zeros((self.h, self.w), np.uint8)
        cv2.line(spur, (10, 20), (self.w - 10, self.h - 20), 1, 2)
        rest = float(erg[spur > 0].mean() - erg[spur == 0].mean())
        wahr_rest = float(self.wahr[spur > 0].mean() - self.wahr[spur == 0].mean())
        self.assertLess(rest - wahr_rest, 0.02, "Satellit steht noch mit %.4f drin" % rest)

    def test_ohne_genug_frames_wird_nicht_verworfen(self):
        """Bei drei Frames ist jede Statistik Zufall — dann darf nichts verworfen werden,
        sonst frisst der Stapel echtes Signal."""
        pfade = self._serie(n=3, unter="kurz")
        ls = livestack.LiveStack(registrieren=False, gewichten=False, min_fuer_verwurf=5,
                                 log=_stille)
        for p in pfade:
            ls.hinzufuegen(p)
        ende = np.mean(np.stack([astro._read_float(p) for p in pfade]), axis=0)
        self.assertTrue(np.allclose(ls.ergebnis(), ende, atol=1e-4))

    def test_zustand_speichern_und_fortsetzen(self):
        """Ein Absturz um drei Uhr nachts darf nicht die halbe Nacht kosten."""
        pfade = self._serie(n=8, unter="save")
        ls = livestack.LiveStack(registrieren=False, log=_stille)
        for p in pfade[:5]:
            ls.hinzufuegen(p)
        z = os.path.join(self.d, "zustand.npz")
        self.assertTrue(ls.speichern(z))
        weiter = livestack.LiveStack.laden(z, log=_stille)
        self.assertIsNotNone(weiter)
        self.assertEqual(weiter.n, 5)
        self.assertTrue(np.array_equal(weiter.ergebnis(), ls.ergebnis()))
        self.assertFalse(weiter.registrieren)
        for p in pfade[5:]:
            ls.hinzufuegen(p)
            weiter.hinzufuegen(p)
        self.assertTrue(np.allclose(weiter.ergebnis(), ls.ergebnis(), atol=1e-6))

    def test_kaputter_zustand_gibt_none(self):
        z = os.path.join(self.d, "muell.npz")
        with open(z, "wb") as fh:
            fh.write(b"kein numpy")
        self.assertIsNone(livestack.LiveStack.laden(z, log=_stille))

    def test_versetzte_frames_werden_ausgerichtet(self):
        """Ohne Ausrichtung würden die Sterne doppelt stehen."""
        d = os.path.join(self.d, "shift")
        os.makedirs(d, exist_ok=True)
        rng = np.random.default_rng(3)
        pfade = []
        for i in range(6):
            f = np.clip(self.wahr + rng.normal(0, 0.003, (self.h, self.w)).astype(np.float32), 0, 1)
            M = np.array([[1, 0, 3.0 * i], [0, 1, -2.0 * i]], np.float32)
            f = cv2.warpAffine(f, M, (self.w, self.h), borderMode=cv2.BORDER_REPLICATE)
            p = os.path.join(d, "v_%02d.tif" % i)
            imwrite(p, np.clip(np.dstack([f] * 3) * 65535, 0, 65535).astype(np.uint16))
            pfade.append(p)
        mit = livestack.LiveStack(registrieren=True, gewichten=False, log=_stille)
        ohne = livestack.LiveStack(registrieren=False, gewichten=False, log=_stille)
        for p in pfade:
            mit.hinzufuegen(p)
            ohne.hinzufuegen(p)

        def spitze(a):
            g = astro._gray(a)
            hg = cv2.medianBlur((np.clip(g, 0, 1) * 255).astype(np.uint8), 31).astype(np.float32) / 255
            return float((g - hg).max())

        self.assertGreater(spitze(mit.ergebnis()), spitze(ohne.ergebnis()) * 1.2,
                           "ausgerichtet muessten die Sterne deutlich spitzer sein")

    def test_unpassende_groesse_wird_abgelehnt(self):
        ls = livestack.LiveStack(registrieren=False, log=_stille)
        ls.hinzufuegen(np.full((60, 60, 3), 0.2, np.float32))
        self.assertFalse(ls.hinzufuegen(np.full((40, 40, 3), 0.2, np.float32)))
        self.assertEqual(ls.n, 1)
        self.assertEqual(ls.verworfen, 1)

    def test_leerer_stapel(self):
        ls = livestack.LiveStack(log=_stille)
        self.assertIsNone(ls.ergebnis())
        self.assertFalse(ls.vorschau_schreiben(os.path.join(self.d, "x.jpg")))
        self.assertFalse(ls.speichern(os.path.join(self.d, "x.npz")))

    def test_neue_dateien_uebergeht_bekannte_und_fremde(self):
        pfade = self._serie(n=3, unter="nd")
        d = os.path.dirname(pfade[0])
        with open(os.path.join(d, "notiz.txt"), "w", encoding="utf-8") as fh:
            fh.write("kein Bild")
        gesehen = {}
        self.assertEqual(livestack.neue_dateien(d, set(pfade[:1]), beobachtet=gesehen, jetzt=0), [])
        raus = livestack.neue_dateien(d, set(pfade[:1]), beobachtet=gesehen, jetzt=3)
        self.assertEqual(len(raus), 2)
        self.assertTrue(all(p.endswith(".tif") for p in raus))


if __name__ == "__main__":
    unittest.main(verbosity=2)
