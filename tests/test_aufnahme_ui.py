"""Aufnahme-Fenster und Astro-Werkzeug-Menü — über die echten Knöpfe, gegen ein nachgebautes
Alpaca-Gerät (tests/test_alpaca_aufnahme.py).

Geprüft wird der Weg, den jemand in der Oberfläche geht: Geräte laden → Verbinden →
Testaufnahme → Ablaufplan starten. Am Ende müssen FITS-Dateien im Zielordner liegen und der
Ordner als Eingabe übernommen sein — sonst ist „Start" nur ein Knopf, der nichts tut."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import shutil
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PySide6.QtWidgets import QApplication, QMenu

import test_alpaca_aufnahme as geraet  # noqa: E402


class AufnahmeUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), geraet._Geraet)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        geraet._Geraet.zustand = {}
        self.ziel = tempfile.mkdtemp()
        # Ein modales Fehlerfenster wartet offscreen ewig — Fehler sollen im Protokoll stehen
        # und den Test scheitern lassen, nicht ihn anhalten. Echte Funktion statt MagicMock.
        import ui.aufnahme_dialog as ad
        self._warnung = ad.QMessageBox.warning
        self.warnungen = []
        ad.QMessageBox.warning = staticmethod(lambda *a, **k: self.warnungen.append(a[-1]))

    def tearDown(self):
        import ui.aufnahme_dialog as ad
        ad.QMessageBox.warning = self._warnung
        shutil.rmtree(self.ziel, ignore_errors=True)

    def _warten(self, dialog, sekunden=30):
        ende = time.monotonic() + sekunden
        while dialog._worker is not None and dialog._worker.isRunning():
            self.app.processEvents()
            time.sleep(0.02)
            self.assertLess(time.monotonic(), ende, "Hintergrund-Vorgang hängt")
        self.app.processEvents()

    def test_ablaufplan_ueber_die_knoepfe(self):
        from ui.aufnahme_dialog import AufnahmeDialog
        uebernommen = []
        d = AufnahmeDialog(None, ordner_uebernehmen=uebernommen.append)
        try:
            d.a_port.setValue(self.server.server_address[1])
            d._alpaca_laden(); self._warten(d)
            self.assertEqual(d.a_wahl["camera"].currentData(), 0)
            d._alpaca_verbinden(); self._warten(d)
            self.assertIn("camera", d._geraete)
            d._alpaca_test(); self._warten(d)
            self.assertFalse(d.vorschau.pixmap().isNull(), "Testaufnahme ohne Vorschau")
            d.a_ordner.setText(self.ziel)
            d.plan.cellWidget(0, 0).setValue(2)
            d.plan.cellWidget(0, 1).setValue(0.0)
            d._alpaca_start(); self._warten(d)
            dateien = sorted(f for f in os.listdir(self.ziel) if f.endswith(".fits"))
            self.assertEqual(len(dateien), 2, d.log.toPlainText())
            self.assertEqual(uebernommen, [self.ziel])
            self.assertTrue(d.a_start.isEnabled(), "Start bleibt nach dem Lauf gesperrt")
        finally:
            d.close(); d.deleteLater(); self.app.processEvents()

    def test_ablaufplan_ueber_indi(self):
        """Derselbe Weg mit INDI statt Alpaca — gegen den Nachbau aus test_indi."""
        import test_indi
        from ui.aufnahme_dialog import AufnahmeDialog
        tcp = test_indi._Server(("127.0.0.1", 0), test_indi._Handler)
        threading.Thread(target=tcp.serve_forever, daemon=True).start()
        d = AufnahmeDialog(None)
        try:
            d.a_art.setCurrentIndex(d.a_art.findData("indi"))
            self.assertEqual(d.a_port.value(), 7624)
            d.a_port.setValue(tcp.server_address[1])
            d._alpaca_laden(); self._warten(d)
            self.assertEqual(d.a_wahl["camera"].currentData(), "CCD Simulator", self.warnungen)
            d._alpaca_verbinden(); self._warten(d)
            self.assertEqual(d._filter_namen, ["L", "R", "Ha"])
            d.a_ordner.setText(self.ziel)
            d.plan.cellWidget(0, 0).setValue(1)
            d.plan.cellWidget(0, 1).setValue(0.0)
            d._alpaca_start(); self._warten(d)
            self.assertEqual(len([f for f in os.listdir(self.ziel) if f.endswith(".fits")]), 1,
                             d.log.toPlainText())
        finally:
            d.close(); d.deleteLater(); self.app.processEvents()
            tcp.shutdown(); tcp.server_close()

    def test_menues_im_hauptfenster(self):
        from ui.main_window import MainWindow
        from gui_support import stilles_hauptfenster
        with stilles_hauptfenster():
            w = MainWindow()
            try:
                menues = {m.title(): [a.text() for a in m.actions()]
                          for m in w.menuBar().findChildren(QMenu)}
                self.assertEqual(len(menues.get("Astro-Werkzeuge", [])), 7)
                self.assertIn("Aufnahme", menues)
                w.open_aufnahme()
                self.assertTrue(w._aufnahme_dialog.isVisible())
                w._aufnahme_dialog.close()
            finally:
                w.deleteLater()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
