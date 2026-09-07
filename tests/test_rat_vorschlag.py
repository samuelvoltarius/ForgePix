#!/usr/bin/env python3
"""
ForgePix — der Vorschlag des Regelwerks in der Oberfläche.

    python3 tests/test_rat_vorschlag.py

Die Pipeline vermisst den fertigen Stapel und meldet ihre Empfehlung als Marker
`RAT:<schalter>`. Im Protokoll steht das auch — aber ein Anfänger liest kein Protokoll und
wüsste mit `--bg-extract` ohnehin nichts anzufangen. Der Balken zeigt den Rat in Worten und
setzt ihn auf Knopfdruck.

Zwei Eigenschaften werden hier festgehalten, weil sie leicht wieder verlorengehen:

1. **Der Knopf setzt wirklich, was er behauptet.** Geprüft wird an den echten Bedienelementen:
   nach dem Klick müssen der Haken und der Wert tatsächlich anders stehen. Ein Knopf, der
   behauptet etwas gesetzt zu haben und es nicht tut, wäre schlimmer als gar kein Knopf.
2. **Was er nicht kann, sagt er.** Ein unbekannter Schalter wird im Text genannt und nicht
   still verschluckt.

Ausserdem: der Vorschlag des letzten Laufs verschwindet beim nächsten Start. Sonst stünde ein
Rat zu einem Bild da, das es nicht mehr gibt.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui_support import stilles_hauptfenster_aufsetzen  # noqa: E402


class _MitFenster(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        stilles_hauptfenster_aufsetzen(self)
        from ui.main_window import MainWindow
        self.w = MainWindow()
        self.addCleanup(self.w.deleteLater)


class TestRatVorschlag(_MitFenster):

    def test_balken_ist_am_anfang_versteckt(self):
        self.assertFalse(self.w.rat_bar.isVisibleTo(self.w))

    def test_bekannte_schalter_werden_in_worte_uebersetzt(self):
        self.w._rat_zeigen("--bg-extract --astro-synthstar")
        t = self.w.rat_lbl.text()
        self.assertIn("Hintergrund", t)
        self.assertIn("Sternformen", t)
        self.assertNotIn("--bg-extract", t, "rohe Schalter gehoeren nicht in den Vorschlagstext")
        self.assertTrue(self.w.rat_btn.isEnabled())

    def test_knopf_setzt_die_bedienelemente_wirklich(self):
        """Der eigentliche Test: nicht der Text zaehlt, sondern der Zustand danach."""
        self.w.astro_bg.setChecked(False)
        self.w.astro_synthstar.setChecked(False)
        self.w.astro_starless_stretch.setValue(-1.0)
        self.w._rat_zeigen("--bg-extract --astro-synthstar --astro-starless-stretch 0.35")
        self.w._rat_uebernehmen()
        self.assertTrue(self.w.astro_bg.isChecked())
        self.assertTrue(self.w.astro_synthstar.isChecked())
        self.assertAlmostEqual(self.w.astro_starless_stretch.value(), 0.35, places=3)

    def test_drizzle_setzt_beide_teile(self):
        self.w.astro_drizzle_true.setChecked(False)
        self.w._rat_zeigen("--astro-drizzle 2 --astro-drizzle-true")
        self.w._rat_uebernehmen()
        self.assertEqual(self.w.astro_drizzle.currentData(), 2)
        self.assertTrue(self.w.astro_drizzle_true.isChecked())

    def test_binning(self):
        self.w._rat_zeigen("--bin 2")
        self.w._rat_uebernehmen()
        self.assertEqual(self.w.astro_bin.currentData(), 2)

    def test_unbekannter_schalter_wird_genannt_nicht_verschluckt(self):
        self.w._rat_zeigen("--bg-extract --voellig-unbekannt")
        t = self.w.rat_lbl.text()
        self.assertIn("--voellig-unbekannt", t,
                      "was der Knopf nicht kann, muss dastehen")
        self.assertIn("Hintergrund", t)

    def test_nur_unbekannte_schalter_lassen_den_knopf_aus(self):
        self.w._rat_zeigen("--nur-unbekannt")
        self.assertFalse(self.w.rat_btn.isEnabled())

    def test_leerer_rat_versteckt_den_balken(self):
        self.w._rat_zeigen("--bg-extract")
        self.w.rat_bar.show()
        self.w._rat_zeigen("")
        self.assertFalse(self.w.rat_bar.isVisibleTo(self.w))

    def test_uebernehmen_versteckt_den_balken(self):
        self.w._rat_zeigen("--bg-extract")
        self.w.rat_bar.show()
        self.w._rat_uebernehmen()
        self.assertFalse(self.w.rat_bar.isVisibleTo(self.w))

    def test_jede_zuordnung_trifft_ein_vorhandenes_bedienelement(self):
        """Wenn ein Bedienelement umbenannt wird, faellt die Zuordnung sonst still aus —
        der Knopf meldete dann "nicht uebernommen", ohne dass jemand die Ursache saehe."""
        for schluessel, (name, braucht_wert, tu) in self.w._rat_zuordnung().items():
            # 1.0 liegt bei jedem wertbehafteten Schalter in der Spanne und ist bei den
            # Auswahlfeldern ein vorhandener Eintrag.
            self.assertTrue(tu(1.0) if braucht_wert else tu(),
                            "%s (%s) findet sein Bedienelement nicht" % (schluessel, name))

    def test_wertschalter_ohne_wert_wird_nicht_stillschweigend_gesetzt(self):
        """Wenn das Modell den Wert vergisst, darf nicht irgendein Standard gesetzt werden —
        der Benutzer bekaeme eine Zahl, die niemand gewaehlt hat."""
        zuordnung = self.w._rat_zuordnung()
        _name, braucht_wert, tu = zuordnung["--astro-saturation"]
        self.assertTrue(braucht_wert)
        self.assertFalse(tu(None), "ohne Wert darf nichts gesetzt werden")

    def test_wert_aus_dem_sprachmodell_wird_uebernommen(self):
        """Das Regelwerk sagt feste Dinge, das Sprachmodell waehlt die Zahl selbst."""
        self.w._rat_zeigen("--astro-saturation 1.4 --astro-denoise 0.3", quelle="modell")
        self.w._rat_uebernehmen()
        self.assertAlmostEqual(self.w.astro_sat.value(), 1.4, places=3)
        self.assertAlmostEqual(self.w.astro_denoise.value(), 0.3, places=3)

    def test_herkunft_steht_im_text(self):
        """Eine Modellantwort neben eine Messung zu stellen, ohne den Unterschied zu benennen,
        waere irrefuehrend."""
        self.w._rat_zeigen("--bg-extract", quelle="regelwerk")
        self.assertIn("vermessen", self.w.rat_lbl.text())
        self.w._rat_zeigen("--bg-extract", quelle="modell")
        self.assertIn("nicht gemessen", self.w.rat_lbl.text())


class TestMarkerAusDerPipeline(_MitFenster):
    """Das Regelwerk und die Oberflaeche muessen dieselbe Sprache sprechen."""

    def test_alles_was_das_regelwerk_sagen_kann_ist_zugeordnet(self):
        import inspect
        import re

        import regeln
        quelle = inspect.getsource(regeln.pruefen)
        aussagbar = set()
        for treffer in re.findall(r'"(--[a-z0-9-]+(?: [^"]*)?)"', quelle):
            aussagbar.add(treffer)
        self.assertTrue(aussagbar)
        zuordnung = set(self.w._rat_zuordnung())
        # Je SCHALTER pruefen, nicht je fertiger Zeichenkette: "--bin 2" zerfaellt in den
        # Schalter "--bin" und den Wert 2.
        bestandteile = set()
        for a in aussagbar:
            bestandteile.update(t for t in a.split() if t.startswith("--"))
        fehlend = sorted(bestandteile - zuordnung)
        self.assertEqual(fehlend, [],
                         "Das Regelwerk empfiehlt etwas, das der Knopf nicht setzen kann: %s"
                         % fehlend)


if __name__ == "__main__":
    unittest.main(verbosity=2)
