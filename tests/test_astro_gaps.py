#!/usr/bin/env python3
"""Tests für die offenen Astro-Stacking-Lücken in core/astro.py (A3–A6).

Synthetische Sternfelder (mit Rotation/Spiegelung für A3), verrauschter Hintergrund (A4),
verschwommenes Bild (A5) und Sterne+Nebel (A6). Reine OpenCV/NumPy/scipy-Pfade.

Ausführen:  python3 tests/test_astro_gaps.py
"""
import os
import sys
import shutil
import tempfile
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
# auch wenn aus dem Repo-Root oder aus tests/ gestartet
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core"))

import astro  # noqa: E402


def _make_star_field(n_stars=40, size=256, seed=0, fluxes=None):
    """Zufälliges Sternfeld: Punktquellen mit Gauss-Profil. Gibt (bild_gray, sternpositionen)."""
    rng = np.random.default_rng(seed)
    img = np.zeros((size, size), np.float32)
    pts = rng.uniform(30, size - 30, size=(n_stars, 2)).astype(np.float32)
    for k, (x, y) in enumerate(pts):
        flux = fluxes[k] if fluxes is not None else rng.uniform(0.4, 1.0)
        xi, yi = int(x), int(y)
        for dy in range(-3, 4):
            for dx in range(-3, 4):
                yy, xx = yi + dy, xi + dx
                if 0 <= yy < size and 0 <= xx < size:
                    img[yy, xx] += flux * np.exp(-(dx * dx + dy * dy) / 3.0)
    return np.clip(img, 0, 1), pts


def _to_bgr(g):
    return cv2.cvtColor((np.clip(g, 0, 1)).astype(np.float32), cv2.COLOR_GRAY2BGR)


class TestA3Triangles(unittest.TestCase):
    def test_match_under_rotation(self):
        """Dreiecks-Matching findet Korrespondenzen trotz großer Feldrotation."""
        g, pts = _make_star_field(n_stars=35, seed=1)
        # 35° drehen um die Bildmitte
        ang = np.deg2rad(35.0)
        c = 128.0
        rot = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]], np.float32)
        rpts = (pts - c) @ rot.T + c
        src, dst = astro.match_stars_triangles(pts, rpts)
        self.assertIsNotNone(src, "kein Match unter Rotation")
        self.assertGreaterEqual(len(src), 6)
        # Validieren: geschätzte Affine bildet src→dst klein-residual ab
        M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC)
        self.assertIsNotNone(M)
        self.assertGreaterEqual(int(inl.sum()), 6)

    def test_match_under_mirror(self):
        """Spiegelung (negative Skalierung) bricht das invariante Matching nicht."""
        g, pts = _make_star_field(n_stars=35, seed=2)
        mpts = pts.copy()
        mpts[:, 0] = 256 - mpts[:, 0]            # horizontal spiegeln
        src, dst = astro.match_stars_triangles(pts, mpts)
        self.assertIsNotNone(src, "kein Match unter Spiegelung")
        self.assertGreaterEqual(len(src), 6)

    def test_robust_transform_rotation(self):
        """_estimate_star_transform_robust richtet ein rotiertes Feld aus (translationsfrei)."""
        g, pts = _make_star_field(n_stars=45, seed=3)
        ang = np.deg2rad(25.0)
        c = 128.0
        M_true = cv2.getRotationMatrix2D((c, c), -np.rad2deg(ang), 1.0).astype(np.float32)
        gr = cv2.warpAffine(g, M_true, (256, 256))
        M = astro._estimate_star_transform_robust(g, gr)
        self.assertIsNotNone(M, "robuste Transform lieferte None")
        # gr mit M zurück ausrichten → sollte g ähneln (Sterne überlappen)
        back = cv2.warpAffine(gr, M, (256, 256))
        # Korrelation der hellen Bereiche soll hoch sein
        a, b = g.ravel(), back.ravel()
        corr = float(np.corrcoef(a, b)[0, 1])
        self.assertGreater(corr, 0.5, f"Ausrichtung schlecht (corr={corr:.2f})")


class TestA4Weighting(unittest.TestCase):
    def _write_frames(self, tmp, base, noises, seed=10):
        """Frames = base + gaußsches Rauschen je Frame; manche stark verrauscht (schlechte
        Transparenz simuliert)."""
        rng = np.random.default_rng(seed)
        paths = []
        for i, nz in enumerate(noises):
            f = base + rng.normal(0, nz, base.shape).astype(np.float32)
            f = np.clip(f, 0, 1)
            bgr = _to_bgr(f)
            p = os.path.join(tmp, f"f_{i:03d}.tif")
            cv2.imwrite(p, (bgr * 65535).astype(np.uint16))
            paths.append(p)
        return paths

    def test_weighting_improves_snr(self):
        """Gewichtetes Mittel (1/σ²) hat besseres SNR als ungewichtetes bei gemischter Transparenz."""
        size = 128
        base = np.full((size, size), 0.3, np.float32)
        base[40:88, 40:88] = 0.6                 # konstantes "Nebel"-Signal
        # Mischung: einige sehr saubere, einige sehr verrauschte Frames
        noises = [0.01, 0.01, 0.01, 0.01, 0.20, 0.20, 0.20, 0.20]
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_frames(tmp, base, noises)
            unw = astro.stack(paths, method="average", normalize=False, weight=False, log=lambda *a: None)
            wt = astro.stack(paths, method="average", normalize=False, weight=True, log=lambda *a: None)

        def _bg_noise(img):
            g = astro._gray(img)
            return float(np.std(g[:30, :30]))    # Ecke = Hintergrund

        self.assertLess(_bg_noise(wt), _bg_noise(unw) * 0.95,
                        "Gewichtung senkte das Hintergrundrauschen nicht")
        # Signal (Nebelregion) bleibt erhalten (Helligkeit ~unverändert)
        sig_w = float(astro._gray(wt)[50:78, 50:78].mean())
        self.assertGreater(sig_w, 0.5)

    def test_sigma_iters_default_safe(self):
        """sigma_iters>1 läuft durch und gibt ein plausibles Ergebnis (kein Crash, im Range)."""
        size = 96
        base = np.full((size, size), 0.4, np.float32)
        noises = [0.03] * 6
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._write_frames(tmp, base, noises, seed=20)
            r1 = astro.stack(paths, method="sigma", sigma_iters=1, normalize=False, log=lambda *a: None)
            r2 = astro.stack(paths, method="sigma", sigma_iters=2, normalize=False, log=lambda *a: None)
        self.assertEqual(r1.shape, r2.shape)
        self.assertTrue(np.all(np.isfinite(r2)))
        self.assertGreater(float(astro._gray(r2).mean()), 0.3)


class TestA5Deconv(unittest.TestCase):
    def test_deconv_sharpens_without_overshoot(self):
        """Regularisierte Deconv schärft eine verschwommene Kante, ohne starkes Overshoot."""
        size = 128
        g = np.zeros((size, size), np.float32)
        g[:, 64:] = 0.7                          # Kante
        # ein paar Sterne, damit estimate_psf eine PSF findet
        _, pts = _make_star_field(n_stars=30, size=size, seed=5)
        for x, y in pts:
            xi, yi = int(x), int(y)
            if 4 < xi < size - 4 and 4 < yi < size - 4:
                g[yi, xi] = 0.9
        blurred = cv2.GaussianBlur(g, (0, 0), 1.6)
        bgr = _to_bgr(blurred)
        out = astro.deconvolve(bgr, iterations=12, regularize=0.1, deringing=True,
                               star_protect=1.0, log=lambda *a: None)
        og = astro._gray(out)
        bg = astro._gray(bgr)
        # Schärfe (Gradientenenergie an der Kante) soll steigen
        gx_out = float(np.abs(np.diff(og[:, 60:70], axis=1)).sum())
        gx_blur = float(np.abs(np.diff(bg[:, 60:70], axis=1)).sum())
        self.assertGreater(gx_out, gx_blur, "Deconv schärfte die Kante nicht")
        # kein massives Overshoot: Wertebereich bleibt im Rahmen
        self.assertLessEqual(float(og.max()), 1.0 + 1e-5)
        self.assertGreaterEqual(float(og.min()), -1e-5)
        # Overshoot direkt an der Kante moderat (nicht > deutlich über Plateau)
        self.assertLess(float(og[:, 70:].max()), 1.0 + 1e-5)

    def test_deconv_tiled_runs(self):
        """tiled_psf-Pfad läuft durch und liefert gültiges Bild."""
        size = 96
        _, pts = _make_star_field(n_stars=40, size=size, seed=6)
        g, _ = _make_star_field(n_stars=40, size=size, seed=6)
        blurred = cv2.GaussianBlur(g, (0, 0), 1.4)
        out = astro.deconvolve(_to_bgr(blurred), iterations=6, tiled_psf=True, tiles=2,
                               star_protect=1.0, log=lambda *a: None)
        self.assertEqual(out.shape, (size, size, 3))
        self.assertTrue(np.all(np.isfinite(out)))


class TestA6StarRemoval(unittest.TestCase):
    def test_removes_star_energy_keeps_nebula(self):
        """Star-Removal senkt die Sternenergie deutlich und erhält den Nebel weitgehend."""
        size = 160
        # ausgedehnter "Nebel": glatter heller Fleck
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
        neb = 0.45 * np.exp(-((xx - 80) ** 2 + (yy - 80) ** 2) / (2 * 35.0 ** 2))
        # kleine/mittlere Sterne drauf
        stars, pts = _make_star_field(n_stars=30, size=size, seed=7,
                                      fluxes=np.full(30, 0.9, np.float32))
        scene = np.clip(neb + stars, 0, 1)
        bgr = _to_bgr(scene)

        starless, mask = astro.remove_stars(bgr, log=lambda *a: None)
        self.assertEqual(starless.shape, bgr.shape)
        self.assertIsNotNone(mask)

        # Sternenergie an den Sternorten sinkt deutlich
        sg = astro._gray(scene)
        rg = astro._gray(starless)
        star_before, star_after, cnt = 0.0, 0.0, 0
        for x, y in pts:
            xi, yi = int(x), int(y)
            if 2 <= xi < size - 2 and 2 <= yi < size - 2:
                star_before += float(sg[yi, xi]); star_after += float(rg[yi, xi]); cnt += 1
        self.assertGreater(cnt, 0)
        self.assertLess(star_after, star_before * 0.85,
                        "Sternenergie nicht ausreichend gesenkt")

        # Nebel-Hintergrund (sternfreie Region nahe Zentrum) bleibt weitgehend erhalten
        # eine Region wählen, in der kein Stern liegt
        def _star_near(px, py, rad=6):
            return any(abs(px - x) < rad and abs(py - y) < rad for x, y in pts)
        ref_val, kept_val, k = 0.0, 0.0, 0
        for (px, py) in [(80, 80), (70, 90), (90, 70), (60, 80), (80, 60)]:
            if not _star_near(px, py):
                ref_val += float(sg[py, px]); kept_val += float(rg[py, px]); k += 1
        if k > 0:
            ratio = kept_val / max(ref_val, 1e-6)
            self.assertGreater(ratio, 0.7, f"Nebel zu stark beschädigt (ratio={ratio:.2f})")


class TestWinsorRejection(unittest.TestCase):
    """A7 — `winsor` muss Ausreißer wirklich beschneiden.

    Es rechnete mit den Schwellen des ERSTEN, unbereinigten Durchlaufs. Ein Ausreißer bläht
    die Streuung aber selbst auf und landet damit innerhalb seiner eigenen Schwelle.
    Nachgerechnet an 9× 0.06 + 1× 1.00: mean=0.154, std=0.282 → hi=0.859, also praktisch
    kein Beschnitt; Ergebnis 0.140 statt 0.060 (133 % zu hell). Am echten Stack blieben
    16.7 % eines kosmischen Treffers stehen — fast so viel wie beim simplen Mittelwert
    (19.6 %), obwohl winsor ein Rejection-Verfahren ist."""

    def _stapel(self, n=10, stoer_index=5, h=120, w=160):
        """n Subs, in einem davon 40 kosmische Treffer. Gibt (pfade, trefferliste, tempdir)."""
        rng = np.random.default_rng(31)
        d = tempfile.mkdtemp(prefix="fp_winsor_")
        sx = rng.integers(15, w - 15, 30); sy = rng.integers(15, h - 15, 30)
        mag = rng.uniform(0.3, 0.9, 30)
        pfade, treffer = [], []
        for i in range(n):
            f = np.full((h, w), 0.06, np.float32)
            for x, y, m in zip(sx, sy, mag):
                cv2.circle(f, (int(x), int(y)), 2, float(m), -1)
            f = cv2.GaussianBlur(f, (0, 0), 1.1) + rng.normal(0, 0.008, (h, w)).astype(np.float32)
            if i == stoer_index:
                for _ in range(40):
                    px, py = int(rng.integers(5, w - 5)), int(rng.integers(5, h - 5))
                    cv2.circle(f, (px, py), 1, 1.0, -1)
                    treffer.append((px, py))
            bgr = np.clip(np.dstack([f, f, f]), 0, 1)
            p = os.path.join(d, "s_%02d.tif" % i)
            cv2.imencode(".tif", (bgr * 65535).astype(np.uint16))[1].tofile(p)
            pfade.append(p)
        return pfade, treffer, d

    def _rest(self, pfade, treffer, method):
        """Restamplitude der Treffer im Stack, in % der Bildspanne. DIREKT an den
        Trefferpositionen — ein Helligkeitsfilter wuerde genau sie ausschliessen."""
        out = astro.stack(pfade, method=method, kappa=2.5, log=lambda *a: None)
        out = np.asarray(out[0] if isinstance(out, tuple) else out, np.float32)
        g = out[..., 1] if out.ndim == 3 else out
        werte = []
        for px, py in treffer:
            kern = float(g[py, px])
            ring = float(np.median(g[max(0, py - 4):py + 5, max(0, px - 4):px + 5]))
            werte.append(kern - ring)
        spanne = float(np.percentile(g, 99.9) - np.percentile(g, 1))
        return float(np.median(werte)) / max(spanne, 1e-9) * 100

    def test_a7_winsor_entfernt_ausreisser(self):
        pfade, treffer, d = self._stapel()
        try:
            rest = self._rest(pfade, treffer, "winsor")
            self.assertLess(rest, 3.0,
                            f"winsor laesst {rest:.1f} % des Ausreissers stehen — "
                            "rechnet es wieder mit unbereinigten Schwellen?")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_a7_winsor_so_gut_wie_sigma(self):
        """Beide sind Rejection-Verfahren und muessen in derselben Groessenordnung landen."""
        pfade, treffer, d = self._stapel()
        try:
            w = self._rest(pfade, treffer, "winsor")
            sg = self._rest(pfade, treffer, "sigma")
            self.assertLess(abs(w), abs(sg) + 3.0, f"winsor {w:.2f} % vs sigma {sg:.2f} %")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_a7_average_und_max_behalten_ihr_verhalten(self):
        """Gegenprobe: die Aenderung darf NUR winsor betreffen. `average` mittelt den Treffer
        auf ~1/n herunter, `max` behaelt ihn per Definition — beides ist kein Fehler."""
        pfade, treffer, d = self._stapel()
        try:
            self.assertGreater(self._rest(pfade, treffer, "average"), 5.0,
                               "average darf nicht heimlich zum Rejection-Verfahren werden")
            self.assertGreater(self._rest(pfade, treffer, "max"), 50.0,
                               "max muss den hellsten Wert behalten")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TestReferenzwahl(unittest.TestCase):
    """A8 — die Registrier-Referenz soll das BESTE Sub sein, nicht einfach das mittlere.

    Die Referenz bestimmt, worauf alle Frames gefittet werden. Die Sub-Bewertung sortiert nur
    Ausreißer aus, nicht das Mittelmaß — ein schwaches Sub (Dunst, leichter Guidingfehler)
    kann also Referenz werden und die Passung der ganzen Serie verschlechtern.
    Gemessen: bei gleichwertigen Subs ±0 %, bei schwachem mittleren Sub 7 % kompaktere
    Sterne im Ergebnis. Siril macht das in seiner Zwei-Pass-Registrierung genauso."""

    def _frames(self, werte):
        """werte: Liste (name, sterne, fwhm, ecc, keep)."""
        return [{"path": f"/x/{n}.fit", "name": n, "stars": st, "fwhm": fw,
                 "ecc": ec, "keep": k} for n, st, fw, ec, k in werte]

    def test_a8_waehlt_das_beste_sub(self):
        import astro_quality
        f = self._frames([("a", 50, 3.4, 1.30, True),
                          ("b", 90, 2.1, 1.02, True),      # klar das beste
                          ("c", 60, 3.0, 1.10, True)])
        self.assertEqual(astro_quality.best_reference(f), "/x/b.fit")

    def test_a8_ignoriert_aussortierte_subs(self):
        """Ein verworfenes Sub darf nie Referenz werden, auch wenn seine Zahlen gut aussehen."""
        import astro_quality
        f = self._frames([("gut", 80, 2.2, 1.03, True),
                          ("raus", 200, 1.0, 1.00, False)])
        self.assertEqual(astro_quality.best_reference(f), "/x/gut.fit")

    def test_a8_ohne_brauchbare_subs_none(self):
        import astro_quality
        self.assertIsNone(astro_quality.best_reference([]))
        self.assertIsNone(astro_quality.best_reference(self._frames([("x", 9, 2.0, 1.0, False)])))

    def test_a8_rundheit_schlaegt_reine_sternzahl(self):
        """Ein Sub mit etwas mehr Sternen, aber deutlich länglichen (Guidingfehler), ist die
        schlechtere Referenz — daran fittet die ganze Serie schief."""
        import astro_quality
        f = self._frames([("laenglich", 100, 2.5, 1.60, True),
                          ("rund", 88, 2.5, 1.00, True)])
        self.assertEqual(astro_quality.best_reference(f), "/x/rund.fit")

    def test_a8_ref_path_wird_beachtet_und_faellt_sauber_zurueck(self):
        """astro._ref_path: übergebener Pfad gewinnt; unbekannter oder None → mittleres Sub
        (das bisherige Verhalten bleibt damit unverändert)."""
        import astro
        pfade = ["/a.fit", "/b.fit", "/c.fit", "/d.fit", "/e.fit"]
        self.assertEqual(astro._ref_path(pfade, "/b.fit"), "/b.fit")
        self.assertEqual(astro._ref_path(pfade, None), pfade[len(pfade) // 2])
        self.assertEqual(astro._ref_path(pfade, "/gibtsnicht.fit"), pfade[len(pfade) // 2])


class TestBanding(unittest.TestCase):
    """A9 — Zeilen-Banding entfernen (Sensor-Ausleseversatz).

    Viele Kameras legen ein zeilenweise konstantes Offset über das Bild. Dark/Flat/Bias
    beseitigen das NICHT: der Versatz ist je Aufnahme anders, mittelt sich also auch im
    Stack nicht weg, sondern bleibt als Streifenmuster im gestreckten Bild.
    Gemessen gegen die bekannte Wahrheit: Banding um Faktor 4–12 reduziert, der echte
    Gradient bleibt erhalten."""

    def _szene(self, h=200, w=260, seed=13):
        """Sternfeld + echter Gradient + Nebel, OHNE Banding."""
        rng = np.random.default_rng(seed)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        wahr = (0.05 + 0.08 * xx / w + 0.03 * yy / h).astype(np.float32)
        wahr += cv2.GaussianBlur(0.15 * np.exp(-(((xx - w / 2) / (w / 4)) ** 2
                                                 + ((yy - h / 2) / (h / 4)) ** 2)), (0, 0), 7)
        for _ in range(50):
            cv2.circle(wahr, (int(rng.integers(10, w - 10)), int(rng.integers(10, h - 10))),
                       2, float(rng.uniform(0.3, 0.9)), -1)
        return cv2.GaussianBlur(wahr, (0, 0), 1.1).astype(np.float32), rng

    def _bandstaerke(self, img):
        z = np.median(img, axis=1).astype(np.float32)
        return float(np.std(z - astro._rolling_median(z, 31)))

    def test_a9_entfernt_zeilen_banding(self):
        wahr, rng = self._szene()
        band = rng.normal(0, 0.006, wahr.shape[0]).astype(np.float32)
        mit = np.clip(wahr + band[:, None], 0, 1)
        ohne = astro.fix_banding(mit, strength=1.0)
        vor, nach = self._bandstaerke(mit), self._bandstaerke(ohne)
        self.assertLess(nach, vor / 3.0, f"Banding kaum reduziert: {vor:.5f} -> {nach:.5f}")

    def test_a9_echter_gradient_bleibt(self):
        """Der grossflaechige Helligkeitsverlauf gehoert NICHT zum Banding — dafuer ist
        background_extract da. fix_banding darf ihn nicht anfassen."""
        wahr, rng = self._szene()
        band = rng.normal(0, 0.006, wahr.shape[0]).astype(np.float32)
        mit = np.clip(wahr + band[:, None], 0, 1)
        ohne = astro.fix_banding(mit, strength=1.0)
        for name, a, b in (("links/rechts", mit[:, :40], ohne[:, :40]),
                           ("rechts", mit[:, -40:], ohne[:, -40:])):
            self.assertAlmostEqual(float(np.median(a)), float(np.median(b)), places=2,
                                   msg=f"Gradient bei {name} veraendert")

    def test_a9_sauberes_bild_bleibt_nahezu_unveraendert(self):
        wahr, _ = self._szene()
        ohne = astro.fix_banding(wahr, strength=1.0)
        spanne = float(np.percentile(wahr, 99) - np.percentile(wahr, 1))
        self.assertLess(float(np.abs(ohne - wahr).mean()) / spanne, 0.01,
                        "bandingfreies Bild wird zu stark veraendert")

    def test_a9_staerke_null_ist_identitaet(self):
        wahr, _ = self._szene()
        self.assertIs(astro.fix_banding(wahr, strength=0.0), wahr)
        self.assertIsNone(astro.fix_banding(None, strength=1.0))

    def test_a9_farbe_und_grau_und_vertikal(self):
        """Form und Wertebereich muessen erhalten bleiben — 2D wie 3D, beide Richtungen."""
        wahr, rng = self._szene()
        bgr = np.dstack([wahr, wahr, wahr])
        for name, bild in (("grau", wahr), ("bgr", bgr)):
            for vert in (False, True):
                out = astro.fix_banding(bild, strength=1.0, vertical=vert)
                with self.subTest(bild=name, vertikal=vert):
                    self.assertEqual(out.shape, bild.shape)
                    self.assertGreaterEqual(float(out.min()), 0.0)

    def test_a9_spalten_banding_mit_vertical(self):
        wahr, rng = self._szene()
        band = rng.normal(0, 0.006, wahr.shape[1]).astype(np.float32)
        mit = np.clip(wahr + band[None, :], 0, 1)
        ohne = astro.fix_banding(mit, strength=1.0, vertical=True)
        def staerke(img):
            z = np.median(img, axis=0).astype(np.float32)
            return float(np.std(z - astro._rolling_median(z, 31)))
        self.assertLess(staerke(ohne), staerke(mit) / 3.0)


class TestFarbigerHintergrund(unittest.TestCase):
    """A10 — die Hintergrund-Entfernung muss FARBIGE Verläufe kanalweise modellieren.

    Vorher wurde EINE Graustufen-Fläche geschätzt und von allen drei Kanälen gleich abgezogen.
    Ein farbiger Hintergrund ist damit grundsätzlich nicht zu entfernen — und das ist der
    Normalfall: Lichtverschmutzung ist rot/orange, das Amp-Glow der ZWO ASI294MC Pro (IMX294)
    ist blau. Gemessen an einem blauen Ecken-Glow blieb im Blaukanal +0.0913 stehen, während
    Rot mit −0.0541 ÜBERkorrigiert wurde: statt eines sauberen Bildes ein neuer Farbstich."""

    def _szene(self, h=200, w=280):
        rng = np.random.default_rng(17)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        # Amp-Glow-artig: weicher Anstieg zur oberen rechten Ecke, BLAU am stärksten
        d = np.sqrt(((xx - w) / w * 1.5) ** 2 + (yy / h * 1.5) ** 2)
        gf = np.clip(0.35 * np.exp(-d * 1.6), 0, None).astype(np.float32)
        glow = np.dstack([gf * 1.0, gf * 0.45, gf * 0.30])       # BGR
        sky = np.full((h, w), 0.05, np.float32)
        for _ in range(60):
            cv2.circle(sky, (int(rng.integers(10, w - 10)), int(rng.integers(10, h - 10))),
                       2, float(rng.uniform(0.3, 0.9)), -1)
        sky = cv2.GaussianBlur(sky, (0, 0), 1.1)
        return np.dstack([sky, sky, sky]), np.clip(np.dstack([sky, sky, sky]) + glow, 0, 1)

    def _glow(self, img, c, h=200, w=280):
        """Pegelunterschied Glow-Ecke minus Gegenecke in Kanal c."""
        ecke = img[0:50, w - 60:w, c]
        gegen = img[h - 50:h, 0:60, c]
        return float(np.median(ecke) - np.median(gegen))

    def test_a10_farbiges_glow_wird_in_allen_kanaelen_entfernt(self):
        wahr, mit = self._szene()
        ohne = astro.background_extract(mit, log=lambda *a: None)
        for c, name in ((0, "Blau"), (1, "Gruen"), (2, "Rot")):
            vor, nach = self._glow(mit, c), self._glow(ohne, c)
            with self.subTest(kanal=name):
                self.assertLess(abs(nach), abs(vor) * 0.25,
                                f"{name}: {vor:+.4f} -> {nach:+.4f} (zu wenig entfernt)")

    def test_a10_kein_neuer_farbstich(self):
        """Der eigentliche Fehler des Graustufen-Modells: es UEBERkorrigiert die schwachen
        Kanäle. Nach der Korrektur duerfen die Rest-Pegel nicht ins Negative kippen."""
        wahr, mit = self._szene()
        ohne = astro.background_extract(mit, log=lambda *a: None)
        reste = [self._glow(ohne, c) for c in range(3)]
        spanne = max(reste) - min(reste)
        self.assertLess(spanne, 0.03,
                        f"Kanaele driften auseinander (Rest-Glow B/G/R = {reste}) — Farbstich")

    def test_a10_graustufenbild_funktioniert_weiter(self):
        """Der 2D-Pfad darf durch die Kanaltrennung nicht verloren gehen."""
        wahr, mit = self._szene()
        grau = mit[..., 1]
        out = astro.background_extract(grau, log=lambda *a: None)
        self.assertEqual(out.shape, grau.shape)
        self.assertLess(abs(self._glow(out[..., None], 0)), abs(self._glow(grau[..., None], 0)) * 0.35)


class TestSternkerneEntsaettigen(unittest.TestCase):
    """A11 — `unclip_stars`: die Farbe ausgefressener Sternkerne aus den Flanken zurückholen.

    Bei hellen Sternen laufen alle drei Kanäle in die Sättigung, der Kern wird reinweiß und die
    Sternfarbe ist dort verloren — obwohl sie in den nicht gesättigten Flanken vollständig
    vorliegt. Gemessen an Sternen mit BEKANNTER Farbe: vorher 12 von 16 Kernen farblos,
    mittlerer Farbfehler 0.226; danach 0 farblose Kerne, Farbfehler 0.040 (−82 %)."""

    def _feld(self, h=260, w=340):
        rng = np.random.default_rng(29)
        farben = [np.array(c, np.float32) for c in
                  ((1.00, 0.72, 0.45), (0.45, 0.70, 1.00), (0.70, 0.85, 0.95), (0.40, 0.65, 1.00))]
        bild = np.full((h, w, 3), 0.04, np.float32)
        pos, soll = [], []
        for i in range(18):
            x, y = int(rng.integers(25, w - 25)), int(rng.integers(25, h - 25))
            if any(abs(x - px) < 30 and abs(y - py) < 30 for px, py in pos):
                continue
            c = farben[i % len(farben)]
            st = np.zeros((h, w), np.float32); cv2.circle(st, (x, y), 1, 1.0, -1)
            st = cv2.GaussianBlur(st, (0, 0), 2.2); st /= st.max()
            bild += st[..., None] * c.reshape(1, 1, 3) * float(rng.uniform(1.8, 3.0))
            pos.append((x, y)); soll.append(c / c.max())
        return np.clip(bild, 0, 1), pos, soll

    def _farbfehler(self, img, pos, soll):
        fehler, farblos = [], 0
        for (x, y), s in zip(pos, soll):
            kern = img[y - 1:y + 2, x - 1:x + 2].reshape(-1, 3).mean(0) - 0.04
            if kern.max() <= 1e-6:
                continue
            ist = kern / kern.max()
            fehler.append(float(np.abs(ist - s).mean()))
            if (ist.max() - ist.min()) < 0.10:
                farblos += 1
        return float(np.mean(fehler)), farblos

    def test_a11_holt_die_sternfarbe_zurueck(self):
        geclippt, pos, soll = self._feld()
        vor_f, vor_w = self._farbfehler(geclippt, pos, soll)
        self.assertGreater(vor_w, 0, "Vorbedingung: es muss farblose Kerne geben")
        rein = astro.unclip_stars(geclippt, log=lambda *a: None)
        nach_f, nach_w = self._farbfehler(rein, pos, soll)
        self.assertLess(nach_f, vor_f * 0.5, f"Farbfehler {vor_f:.3f} -> {nach_f:.3f}")
        self.assertLess(nach_w, vor_w, f"farblose Kerne {vor_w} -> {nach_w}")

    def test_a11_helligkeit_bleibt(self):
        """Es wird nur die FARBE korrigiert — die Helligkeit darf sich nicht verschieben."""
        geclippt, _, _ = self._feld()
        rein = astro.unclip_stars(geclippt, log=lambda *a: None)
        self.assertAlmostEqual(float(np.median(geclippt)), float(np.median(rein)), places=3)

    def test_a11_bild_ohne_gesaettigte_sterne_bleibt_unveraendert(self):
        """Kein gesättigter Kern -> nichts anfassen. Sonst wäre es ein Filter, der immer wirkt."""
        rng = np.random.default_rng(5)
        h, w = 200, 260
        f = np.full((h, w, 3), 0.05, np.float32)
        for _ in range(30):
            st = np.zeros((h, w), np.float32)
            cv2.circle(st, (int(rng.integers(20, w - 20)), int(rng.integers(20, h - 20))), 1, 1.0, -1)
            f += cv2.GaussianBlur(st, (0, 0), 2.0)[..., None] * 0.35
        f = np.clip(f, 0, 0.7)
        out = astro.unclip_stars(f, log=lambda *a: None)
        self.assertLess(float(np.abs(out - f).max()), 1e-5, "unveraendertes Bild wurde angefasst")

    def test_a11_graustufen_und_none_sind_no_op(self):
        self.assertIsNone(astro.unclip_stars(None, log=lambda *a: None))
        grau = np.full((60, 80), 0.5, np.float32)
        self.assertIs(astro.unclip_stars(grau, log=lambda *a: None), grau)


class TestStrecken(unittest.TestCase):
    """A12 — Starless-Streckung, Sternreduktion und Divisions-Korrektur.

    Kern-Erkenntnis aus echten Dual-Band-Daten (NGC7380, ASI294MC Pro, 13x120 s): der Weisspunkt
    einer Streckung wird IMMER von einem Stern bestimmt, nie vom Nebel. Das Nebelsignal lag dort
    nur 6 % ueber dem Himmel; nach Normierung auf das 99.9-%-Quantil (= ein Stern) blieb der Nebel
    bei 3.5 % des Wertebereichs. Zu helle Sterne UND zu schwacher Nebel haben also DIESELBE
    Ursache. Gemessen: direkt strecken -> Nebel 0.513 / 0.573 % ausgebrannt;
    starless mit 80 % Sternen -> Nebel 0.628 / 0.041 % ausgebrannt."""

    def _nebel_mit_sternen(self, h=220, w=300):
        rng = np.random.default_rng(41)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        neb = 0.10 * np.exp(-(((xx - w / 2) / (w / 4)) ** 2 + ((yy - h / 2) / (h / 4)) ** 2))
        f = np.full((h, w), 0.03, np.float32) + cv2.GaussianBlur(neb, (0, 0), 9)
        for _ in range(40):                       # helle Sterne, die den Weisspunkt an sich reissen
            st = np.zeros((h, w), np.float32)
            cv2.circle(st, (int(rng.integers(12, w - 12)), int(rng.integers(12, h - 12))), 1, 1.0, -1)
            f = f + cv2.GaussianBlur(st, (0, 0), 1.6) * float(rng.uniform(0.5, 1.0))
        return np.clip(np.dstack([f, f, f]), 0, 1)

    def test_a12_starless_hebt_nebel_und_senkt_ausgebrannte_sterne(self):
        bild = self._nebel_mit_sternen()
        strecken = lambda x: astro.mtf_stretch(x)
        direkt = strecken(bild)
        starless = astro.stretch_starless(bild, strecken, star_strength=0.8, log=lambda *a: None)
        def nebel(v): return float(np.percentile(v.mean(axis=2), 85))
        def brand(v): return float((v.max(axis=2) >= 0.99).mean())
        self.assertGreater(nebel(starless), nebel(direkt) * 0.98, "Nebel darf nicht schwaecher werden")
        self.assertLess(brand(starless), brand(direkt) + 1e-9, "ausgebrannte Pixel duerfen nicht zunehmen")

    def test_a12_starless_ohne_sterne_faellt_zurueck(self):
        """Findet das Star-Removal nichts, muss normal gestreckt werden — nicht scheitern."""
        flach = np.full((80, 100, 3), 0.2, np.float32)
        out = astro.stretch_starless(flach, lambda x: astro.mtf_stretch(x),
                                     star_strength=0.8, log=lambda *a: None)
        self.assertEqual(out.shape, flach.shape)
        self.assertTrue(np.all(np.isfinite(out)))

    def test_a12_sternreduktion_schrumpft_sterne_nicht_den_nebel(self):
        bild = self._nebel_mit_sternen()
        v = astro.mtf_stretch(bild)
        red = astro.reduce_stars(v, strength=0.7)
        # Sternspitzen ueber das 99.9-Perzentil messen — eine feste Schwelle wie 0.9 traf im
        # synthetischen Bild GAR KEINE Pixel, der Test haette dann nichts geprueft.
        spitze_vor = float(np.percentile(v.max(axis=2), 99.9))
        spitze_nach = float(np.percentile(red.max(axis=2), 99.9))
        self.assertGreater(spitze_vor, np.percentile(v.mean(axis=2), 60),
                           "Vorbedingung: es muss ueberhaupt Sternspitzen geben")
        self.assertLess(spitze_nach, spitze_vor, "Sternspitzen wurden nicht schwaecher")
        neb_vor = float(np.percentile(v.mean(axis=2), 60))
        neb_nach = float(np.percentile(red.mean(axis=2), 60))
        self.assertGreater(neb_nach, neb_vor * 0.85, "Nebel zu stark mitgenommen")

    def test_a12_sternreduktion_null_ist_identitaet(self):
        bild = self._nebel_mit_sternen()
        self.assertIs(astro.reduce_stars(bild, strength=0.0), bild)

    def test_a12_divisions_korrektur(self):
        """korrektur='div' teilt statt abzuziehen — richtig fuer multiplikative Vignettierung."""
        h, w = 120, 160
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        vign = 1.0 - 0.4 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
        flaeche = (0.2 * vign).astype(np.float32)
        bild = flaeche.copy()
        sub = astro._bg_anwenden(bild, flaeche, "sub")
        div = astro._bg_anwenden(bild, flaeche, "div")
        # nach 'div' muss das Bild FLACH sein (Faktor herausgerechnet)
        self.assertLess(float(div.max() - div.min()), 0.02, "Division hat die Vignette nicht entfernt")
        self.assertLess(float(sub.max() - sub.min()), 0.02, "Subtraktion hat sie nicht entfernt")
        # Division darf den Pegel nicht auf Null ziehen
        self.assertGreater(float(np.median(div)), 0.05)


if __name__ == "__main__":
    unittest.main(verbosity=2)
