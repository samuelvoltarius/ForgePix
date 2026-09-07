#!/usr/bin/env python3
"""
ForgePix — Tests für die Windows-/Portierungslücken (W1–W4).

Eigenständig lauffähig:

    python3 tests/test_windows_gaps.py      # oder: python3 -m unittest discover -s tests

ForgePix wurde auf einem Mac gebaut, wo Pfade und Konsole UTF-8 sind. Unter Windows gilt
stattdessen die Locale-Codepage (deutsch: cp1252). Vier Fehler, die daraus folgten und hier
gegen Rückfall abgesichert werden:
  • W1 imread   → cv2.imread lieferte bei JEDEM Nicht-ASCII-Pfad None (schon bei „Blüte.jpg")
  • W2 imwrite  → cv2.imwrite meldete True, schrieb aber KEINE Datei (Ergebnis still verloren)
  • W3 log_print→ „→/σ" in einer Logzeile warf UnicodeEncodeError und riss den Lauf ab
  • W4 force_utf8_stdio → stdout muss danach UTF-8 sein, ohne bei Ersatz-Streams zu werfen

Die Tests sind bewusst plattformunabhängig formuliert: sie prüfen die ZUGESICHERTE
Semantik (Bild kommt zurück / Datei liegt da / kein Absturz), die unter macOS und Linux
ohnehin galt und unter Windows vorher verletzt war.
"""
import io
import os
import sys
import tempfile
import shutil
import unittest

import numpy as np
import cv2

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from constants import imread, imwrite, log_print, force_utf8_stdio  # noqa: E402


# Namen mit Zeichen, die die Windows-Codepage cp1252 NICHT kennt (ł, ě) bzw. die cv2
# schon bei reinem ASCII-Verlassen zerlegt (ü). Alle drei sind realistische Fotonamen.
UNICODE_NAMEN = ["Blüte_01.jpg", "Motyl_skrzydło.jpg", "kvetina_ě.jpg"]


class TestUnicodeBildIO(unittest.TestCase):
    """W1/W2 — Bild-Ein-/Ausgabe muss bei Nicht-ASCII-Pfaden funktionieren."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="fp_uni_")
        self.img = (np.random.RandomState(5).rand(24, 32, 3) * 255).astype(np.uint8)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_w1_imread_liest_unicode_pfade(self):
        """imread muss ein Bild liefern — cv2.imread gab hier None zurück."""
        for name in UNICODE_NAMEN:
            p = os.path.join(self.d, name)
            cv2.imencode(".jpg", self.img)[1].tofile(p)     # unabhängig vom Kandidaten schreiben
            self.assertTrue(os.path.isfile(p), f"Vorbedingung: {name} existiert")
            got = imread(p)
            self.assertIsNotNone(got, f"imread lieferte None für {name!r}")
            self.assertEqual(got.shape, self.img.shape, name)

    def test_w2_imwrite_schreibt_unicode_pfade_wirklich(self):
        """imwrite darf True nur melden, wenn auch eine Datei entsteht.
        cv2.imwrite meldete bei Umlautpfaden True OHNE Datei — der stille Ergebnisverlust."""
        for name in UNICODE_NAMEN:
            p = os.path.join(self.d, "out_" + name)
            ok = imwrite(p, self.img)
            self.assertTrue(ok, f"imwrite meldete Fehlschlag für {name!r}")
            self.assertTrue(os.path.isfile(p), f"imwrite meldete True, aber es gibt keine Datei: {name!r}")
            self.assertIsNotNone(imread(p), f"geschriebene Datei nicht wieder lesbar: {name!r}")

    def test_w1_imread_fehlende_datei_gibt_none(self):
        """imread-Semantik bewahren: fehlend/kaputt → None, KEINE Ausnahme
        (die Aufrufer prüfen überall `is None`)."""
        self.assertIsNone(imread(os.path.join(self.d, "gibtsnicht.jpg")))
        leer = os.path.join(self.d, "leer.jpg")
        open(leer, "wb").close()
        self.assertIsNone(imread(leer))

    def test_w2_imwrite_meldet_fehlschlag_ehrlich(self):
        """Nicht schreibbares Ziel → False (und keine Ausnahme)."""
        self.assertFalse(imwrite(os.path.join(self.d, "fehlt", "x.jpg"), self.img))

    def test_w2_imwrite_16bit_bleibt_16bit(self):
        """Bit-Tiefe darf beim Umweg über imencode nicht verloren gehen (PNG/TIF 16-bit)."""
        img16 = (np.random.RandomState(6).rand(16, 20, 3) * 65535).astype(np.uint16)
        p = os.path.join(self.d, "tief_ü.png")
        self.assertTrue(imwrite(p, img16))
        back = imread(p, cv2.IMREAD_UNCHANGED)
        self.assertIsNotNone(back)
        self.assertEqual(back.dtype, np.uint16, "16-bit wurde auf 8-bit reduziert")


class TestLogRobustheit(unittest.TestCase):
    """W3 — eine Logzeile darf eine laufende Berechnung nie abbrechen."""

    def test_w3_log_print_ueberlebt_enge_codepage(self):
        """stdout, das nur ASCII kann, darf keinen UnicodeEncodeError auslösen.
        Genau daran starb vorher der HDR-Lauf („→" in der ersten Logzeile)."""
        alt = sys.stdout
        puffer = io.TextIOWrapper(io.BytesIO(), encoding="ascii", errors="strict")
        try:
            sys.stdout = puffer
            log_print("HDR: 3 Aufnahmen → 1 Reihe, γ=1.20, σ=4")   # darf NICHT werfen
        finally:
            sys.stdout = alt
        puffer.flush()
        text = puffer.buffer.getvalue().decode("ascii", "replace")
        self.assertIn("HDR", text, "Zeile ging komplett verloren")

    def test_w3_engine_default_logger_ist_nicht_das_nackte_print(self):
        """Regressionsschutz: die Engine-Funktionen dürfen `print` nicht als Vorgabe führen."""
        import inspect
        import hdr
        vorgabe = inspect.signature(hdr.tonemap_local).parameters["log"].default
        self.assertIsNot(vorgabe, print, "log=print ist unter Windows ein Absturzrisiko")

    def test_w4_force_utf8_stdio_ist_idempotent_und_wirft_nie(self):
        """Muss auch mit einem Ersatz-Stream ohne reconfigure() klaglos durchlaufen."""
        alt = sys.stdout
        try:
            sys.stdout = io.StringIO()          # hat kein reconfigure()
            force_utf8_stdio()
            force_utf8_stdio()
        finally:
            sys.stdout = alt


class TestSubprozessDekodierung(unittest.TestCase):
    """Externe Tools (Siril/GraXpert/exiftool) geben UTF-8 aus — nicht die Locale-Codepage."""

    # Frueher war das eine Zeilensuche per regulaerem Ausdruck: `text=True`, dem nicht
    # unmittelbar `, encoding` folgt. Die sah einen mehrzeiligen Aufruf nicht — sie meldete
    # einen korrekten Aufruf, dessen `encoding=` in der naechsten Zeile stand, und haette
    # umgekehrt einen wirklich fehlenden Parameter uebersehen, wenn `text=True` am Zeilenende
    # stand. Jetzt wird der Aufruf selbst untersucht, nicht seine Schreibweise.
    @staticmethod
    def _nackte_aufrufe(datei):
        import ast
        with open(datei, encoding="utf-8") as fh:
            baum = ast.parse(fh.read())
        raus = []
        for k in ast.walk(baum):
            if not isinstance(k, ast.Call):
                continue
            name = k.func.attr if isinstance(k.func, ast.Attribute) else getattr(
                k.func, "id", "")
            if name not in ("run", "Popen", "check_output", "call", "check_call"):
                continue
            schluessel = {w.arg for w in k.keywords if w.arg}
            textmodus = any(
                w.arg in ("text", "universal_newlines")
                and isinstance(w.value, ast.Constant) and w.value.value is True
                for w in k.keywords)
            if textmodus and "encoding" not in schluessel:
                raus.append(k.lineno)
        return raus

    def test_w3_engines_dekodieren_externe_ausgabe_als_utf8(self):
        """`text=True` ohne `encoding=` nimmt die Locale-Codepage: „Frühling→" kam unter
        Windows als „FrÃ¼hlingâ†'" an. Alle subprocess-Aufrufe müssen utf-8 festlegen."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        core = os.path.join(root, "core")
        nackt = []
        for fn in sorted(os.listdir(core)):
            if fn.endswith(".py"):
                nackt += ["core/%s:%d" % (fn, z)
                          for z in self._nackte_aufrufe(os.path.join(core, fn))]
        self.assertEqual(nackt, [], "subprocess ohne encoding='utf-8': " + ", ".join(nackt))

    def test_die_pruefung_faengt_einen_echten_verstoss(self):
        """Gegenprobe. Ohne sie waere nicht zu unterscheiden, ob oben nichts gefunden wurde
        oder ob gar nichts geprueft wird."""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            gut = os.path.join(d, "gut.py")
            zeilen_gut = ["import subprocess",
                          "subprocess.run(['x'], text=True,",
                          "               encoding='utf-8')"]
            with open(gut, "w", encoding="utf-8") as fh:
                fh.write(chr(10).join(zeilen_gut))
            self.assertEqual(self._nackte_aufrufe(gut), [],
                             "mehrzeiliger, korrekter Aufruf wurde faelschlich gemeldet")
            schlecht = os.path.join(d, "schlecht.py")
            zeilen_schlecht = ["import subprocess",
                               "subprocess.run(['x'],",
                               "               text=True)"]
            with open(schlecht, "w", encoding="utf-8") as fh:
                fh.write(chr(10).join(zeilen_schlecht))
            self.assertEqual(self._nackte_aufrufe(schlecht), [2],
                             "ein echter Verstoss wurde nicht gefunden")


class TestFremdtoolSuche(unittest.TestCase):
    """W5 — die Sucher für Siril/GraXpert/StarNet kannten NUR macOS-Pfade.

    Auf dem Testrechner war Siril 1.4.2 unter „C:\Program Files\Siril\bin" installiert und
    ForgePix fand es trotzdem nie: Windows-Installer tragen sich üblicherweise nicht in den
    PATH ein, und /Applications gibt es dort nicht."""

    def test_w5_windows_kandidaten_nur_unter_windows(self):
        import siril_engine
        c = siril_engine._windows_cands("Siril", ("bin/siril-cli.exe",))
        if os.name == "nt":
            self.assertTrue(c, "unter Windows müssen Kandidaten entstehen")
            self.assertTrue(all(x.endswith(".exe") for x in c))
            self.assertTrue(any("Program Files" in x or "Programs" in x for x in c))
        else:
            self.assertEqual(c, [], "auf macOS/Linux darf nichts erzeugt werden")

    def test_w5_alle_sucher_liefern_pfad_oder_none(self):
        """Zugesicherte Semantik: existierender Dateipfad oder None — nie ein Ordner,
        nie ein Pfad, der gar nicht da ist."""
        import siril_engine
        import tools_engine
        import graxpert_engine
        import cosmicclarity_engine
        for name, fn in [("siril", siril_engine.find_siril),
                         ("graxpert", tools_engine.find_graxpert),
                         ("starnet", tools_engine.find_starnet),
                         ("graxpert_engine", graxpert_engine.find_cli),
                         ("cosmicclarity", cosmicclarity_engine.find_cli)]:
            r = fn()
            with self.subTest(tool=name):
                self.assertTrue(r is None or os.path.isfile(r), f"{name}: {r!r}")

    def test_w5_graxpert_sucher_sind_deckungsgleich(self):
        """Es gab zwei getrennte GraXpert-Kandidatenlisten mit verschiedenem Inhalt —
        wer eine ergänzte, reparierte nur die Hälfte."""
        import tools_engine
        import graxpert_engine
        self.assertEqual(graxpert_engine.find_cli(), tools_engine.find_graxpert())


class TestEhrlicherExitCode(unittest.TestCase):
    """W6 — ein Lauf ohne Ergebnis darf nicht als Erfolg enden.

    `process()` gibt bei „alle Frames aussortiert" None zurück, `main()` wertete das nicht
    aus → Exit-Code 0. Die GUI zeigt bei 0 grün „Fertig ✓" und meldet „Stack fertig 🎉",
    obwohl nichts entstanden war."""

    def test_w6_main_wertet_prozess_ergebnis_aus(self):
        """Quelltext-Prüfung statt Vollstart: main() muss den Rückgabewert von process()
        prüfen und bei None (ausser --no-stack) mit sys.exit(1) enden."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "core", "focus_cull_stack.py"), encoding="utf-8") as fh:
            quelle = fh.read()
        self.assertIn("if process(args, input_dir, work_dir) is None", quelle,
                      "main() ignoriert wieder, ob process() ein Ergebnis lieferte")
        self.assertIn('not getattr(args, "no_stack", False)', quelle,
                      "--no-stack muss weiterhin als Erfolg gelten")


class TestVerstaendlicheFehler(unittest.TestCase):
    """W7 — fehlende OPTIONALE Bibliotheken müssen eine Handlungsanweisung liefern.

    Vorher: wer FITS-Dateien ohne astropy stackte, bekam eine 20-zeilige Traceback-Wand,
    die mit „ModuleNotFoundError: No module named 'astropy'" endete — ohne Hinweis, dass
    FITS die Ursache ist oder wie man es behebt."""

    def test_w7_astropy_meldung_nennt_grund_und_loesung(self):
        from constants import require_astropy, ForgePixFehler
        try:
            import astropy.io.fits  # noqa: F401
            self.skipTest("astropy ist installiert — der Fehlerpfad ist hier nicht prüfbar")
        except ImportError:
            pass
        with self.assertRaises(ForgePixFehler) as ctx:
            require_astropy("FITS-Subs bewerten")
        text = str(ctx.exception)
        self.assertIn("FITS-Subs bewerten", text, "der Zweck fehlt")
        self.assertIn("pip install astropy", text, "die Loesung fehlt")
        self.assertIn("JPG", text, "der Hinweis auf die nicht betroffenen Formate fehlt")

    def test_w7_forgepixfehler_ist_von_runtimeerror_abgeleitet(self):
        """Bestehende `except RuntimeError`-Stellen (z. B. die Engine-Rueckfaelle) muessen
        weiter greifen — sonst wuerde ein sauberer Fallback plötzlich durchschlagen."""
        from constants import ForgePixFehler
        self.assertTrue(issubclass(ForgePixFehler, RuntimeError))

    def test_w7_cli_faengt_erwartete_fehler_klartextlich_ab(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "core", "focus_cull_stack.py"), encoding="utf-8") as fh:
            quelle = fh.read()
        self.assertIn("except ForgePixFehler as e:", quelle)
        self.assertIn("except KeyboardInterrupt:", quelle, "Strg-C soll nicht als Traceback enden")


if __name__ == "__main__":
    unittest.main(verbosity=2)
