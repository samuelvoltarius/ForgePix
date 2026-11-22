"""Arbeitsplatz-Fenster über die echten Knöpfe: öffnen, Werkzeug wählen, Maske, anwenden,
rückgängig, speichern. Ein Knopf, der nichts tut, sieht genauso aus wie einer, der geht."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from PySide6.QtWidgets import QApplication, QMenu

from test_prozesse import sternfeld  # noqa: E402


class ArbeitsplatzUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from astropy.io import fits
        self.d = tempfile.mkdtemp()
        self.pfad = os.path.join(self.d, "stapel.fits")
        b = sternfeld()
        fits.writeto(self.pfad, np.ascontiguousarray(b[..., ::-1].transpose(2, 0, 1)), fits.Header({"OBJECT": "Test"}))
        import ui.arbeitsplatz as ap
        self._warnung = ap.QMessageBox.warning
        self.warnungen = []
        ap.QMessageBox.warning = staticmethod(lambda *a, **k: self.warnungen.append(a[-1]))

    def tearDown(self):
        import ui.arbeitsplatz as ap
        ap.QMessageBox.warning = self._warnung
        shutil.rmtree(self.d, ignore_errors=True)

    def _warten(self, f, sekunden=60):
        ende = time.monotonic() + sekunden
        while f._worker is not None and f._worker.isRunning():
            self.app.processEvents(); time.sleep(0.02)
            self.assertLess(time.monotonic(), ende)
        self.app.processEvents()

    def _waehlen(self, f, pid):
        for i in range(f.baum.topLevelItemCount()):
            knoten = f.baum.topLevelItem(i)
            for j in range(knoten.childCount()):
                if knoten.child(j).data(0, 0x0100) == pid:      # Qt.UserRole
                    f.baum.setCurrentItem(knoten.child(j))
                    return
        self.fail("Werkzeug %s nicht im Baum" % pid)

    def test_ablauf(self):
        from ui.arbeitsplatz import Arbeitsplatz
        uebernommen = []
        f = Arbeitsplatz(None, pfad=self.pfad, uebernehmen=lambda out, vorher: uebernommen.append(out))
        try:
            self.assertFalse(f.flaeche.pixmap().isNull())
            self._waehlen(f, "tv")
            self.assertTrue(f.k_anwenden.isEnabled())
            f.m_art.setCurrentIndex(f.m_art.findData("Sterne"))
            f.anwenden(); self._warten(f)
            self.assertEqual(self.warnungen, [])
            self.assertEqual(f.arbeit.stand, 1)
            self.assertEqual(f.verlauf.count(), 2)
            self.assertIn("Maske", f.verlauf.item(1).text())
            f.rueckgaengig()
            self.assertEqual(f.arbeit.stand, 0)
            self.assertTrue(f.k_vor.isEnabled())
            f.wiederholen()
            ziel = os.path.join(self.d, "ergebnis.fits")
            f.speichern(ziel)
            self.assertTrue(os.path.exists(ziel))
            self.assertEqual(uebernommen, [ziel])
        finally:
            f.close(); f.deleteLater(); self.app.processEvents()

    def test_suche_findet_pixinsight_namen(self):
        from ui.arbeitsplatz import Arbeitsplatz
        f = Arbeitsplatz(None)
        try:
            f.suche.setText("HistogramTransformation")
            namen = [f.baum.topLevelItem(i).child(j).data(0, 0x0100)
                     for i in range(f.baum.topLevelItemCount())
                     for j in range(f.baum.topLevelItem(i).childCount())]
            self.assertEqual(namen, ["mtf"])
        finally:
            f.close(); f.deleteLater()

    def test_experimentell_ohne_zusage_rechnet_nicht(self):
        import ui.arbeitsplatz as ap
        hinweise = []
        alt = ap.QMessageBox.information
        ap.QMessageBox.information = staticmethod(lambda *a, **k: hinweise.append(a[-1]))
        f = ap.Arbeitsplatz(None, pfad=self.pfad)
        try:
            self._waehlen(f, "ki_entrauschen")
            self.assertTrue(f.p_experimentell.isVisibleTo(f))
            f.anwenden(); self._warten(f)
            self.assertEqual(f.arbeit.stand, 0)
            self.assertTrue(hinweise)
        finally:
            ap.QMessageBox.information = alt
            f.close(); f.deleteLater()

    def test_kurve_und_textfeld_sind_eins(self):
        from ui.arbeitsplatz import Arbeitsplatz
        f = Arbeitsplatz(None, pfad=self.pfad)
        try:
            self._waehlen(f, "kurven")
            self.assertTrue(f.kurve.isVisibleTo(f))
            f._kurve_geaendert([[0.0, 0.0], [0.5, 0.7], [1.0, 1.0]])
            self.assertEqual(f.werte()["punkte"], "0.000,0.000; 0.500,0.700; 1.000,1.000")
            f.anwenden(); self._warten(f)
            self.assertEqual(self.warnungen, [])
            self.assertEqual(f.arbeit.schritte[-1]["werte"]["punkte"], "0.000,0.000; 0.500,0.700; 1.000,1.000")
        finally:
            f.close(); f.deleteLater()

    def test_probe_aendert_nichts(self):
        from ui.arbeitsplatz import Arbeitsplatz
        f = Arbeitsplatz(None, pfad=self.pfad)
        try:
            self._waehlen(f, "mtf")
            f.probieren(kante=40); self._warten(f)
            vorher, nachher = f._probe
            self.assertEqual(vorher.shape, (40, 40, 3))
            self.assertFalse(np.array_equal(vorher, nachher))
            self.assertEqual(f.arbeit.stand, 0, "eine Probe darf nichts übernehmen")
            f.anwenden(); self._warten(f)
            self.assertIsNone(f._probe, "nach dem Anwenden zeigt die Fläche wieder das Bild")
        finally:
            f.close(); f.deleteLater()

    def test_zweites_bild_ueber_das_feld(self):
        from astropy.io import fits
        from ui.arbeitsplatz import Arbeitsplatz
        mono = os.path.join(self.d, "ha.fits")
        fits.writeto(mono, np.full((96, 128), 0.5, np.float32))
        f = Arbeitsplatz(None, pfad=self.pfad)
        try:
            self._waehlen(f, "kanal")
            f._felder["quelle"].pfad.setText(mono)
            f.anwenden(); self._warten(f)
            self.assertEqual(self.warnungen, [])
            np.testing.assert_array_equal(f.arbeit.bild[..., 2], 0.5)
        finally:
            f.close(); f.deleteLater()

    def test_nicht_installiertes_programm(self):
        import prozesse
        from ui.arbeitsplatz import Arbeitsplatz
        p = prozesse.NACH_ID["cosmic"]
        alt, p.extern = p.extern, (lambda: None)
        f = Arbeitsplatz(None, pfad=self.pfad)
        try:
            self._waehlen(f, "cosmic")
            self.assertFalse(f.k_anwenden.isEnabled())
            self.assertIn("nicht installiert", f.p_extern.text())
        finally:
            p.extern = alt
            f.close(); f.deleteLater()

    def test_menue_im_hauptfenster(self):
        from ui.main_window import MainWindow
        from gui_support import stilles_hauptfenster
        with stilles_hauptfenster():
            w = MainWindow()
            try:
                bearbeitung = [m for m in w.menuBar().findChildren(QMenu) if m.title() == "Bearbeitung"][0]
                self.assertIn(w.arbeitsplatz_action, bearbeitung.actions())
            finally:
                w.deleteLater(); self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
