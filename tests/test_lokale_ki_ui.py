#!/usr/bin/env python3
"""
ForgePix — die lokale KI in der Oberfläche (Stufe 4).

    python3 tests/test_lokale_ki_ui.py

Der Knopf „Lokale KI suchen" soll jemandem, der Ollama, llama.cpp, LM Studio oder vLLM laufen
hat, das Eintippen abnehmen: Adresse und Modell werden gefunden und gesetzt.

**Nichts davon darf etwas herunterladen.** Ein Modell ist mehrere hundert Megabyte. Ein Programm,
das so etwas von selbst holt, weil es gerade praktisch wäre, ist ein Programm, dem man nicht mehr
traut — deshalb steht der Download hinter einer ausdrücklichen Rückfrage, und deshalb prüft
`test_suchen_laedt_nichts` genau das.

Hier greift nichts ins Netz und es wird kein Ollama gestartet: die Suchfunktion ist ersetzt.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from gui_support import stilles_hauptfenster_aufsetzen  # noqa: E402

import lokales_modell  # noqa: E402


class TestLokaleKiUI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        stilles_hauptfenster_aufsetzen(self)
        from ui.main_window import MainWindow
        self.w = MainWindow()
        self.addCleanup(self.w.deleteLater)
        # Keine Meldungsfenster im Test.
        for name in ("information", "warning"):
            echt = getattr(QMessageBox, name)
            setattr(QMessageBox, name, staticmethod(lambda *a, **k: None))
            self.addCleanup(lambda n=name, e=echt: setattr(QMessageBox, n, e))

    def _lage(self, server=None, ollama=None, gestartet=None):
        for name, wert in (("server_suchen",
                            lambda zusaetzlich=None, log=None, timeout=2.0: server),
                           ("ollama_pfad", lambda: ollama),
                           ("ollama_starten", lambda log=None, timeout=20: gestartet),
                           ("ollama_modelle", lambda log=None: []),
                           ("bericht", lambda log=None: "Bericht")):
            echt = getattr(lokales_modell, name)
            setattr(lokales_modell, name, wert)
            self.addCleanup(lambda n=name, e=echt: setattr(lokales_modell, n, e))

    def _keine_frage(self, antwort=QMessageBox.No):
        gefragt = []
        echt = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: (gefragt.append(a), antwort)[1])
        self.addCleanup(lambda: setattr(QMessageBox, "question", echt))
        return gefragt

    def test_gefundener_server_wird_eingetragen(self):
        self._lage(server={"name": "Ollama", "url": "http://localhost:11434/v1",
                           "modelle": ["qwen2.5:1.5b-instruct", "anderes"]})
        self.w._lokale_ki_suchen()
        self.assertEqual(self.w.vlm_ep.text(), "http://localhost:11434/v1")
        self.assertEqual(self.w.vlm_model.text(), "qwen2.5:1.5b-instruct")
        self.assertTrue(self.w.vlm_group.isChecked())

    def test_kein_schluessel_bei_lokalem_server(self):
        """Ein lokaler Server braucht keinen API-Schluessel. Bliebe dort ein alter Cloud-
        Schluessel stehen, ginge er als Authorization-Kopfzeile an den eigenen Rechner."""
        self.w.vlm_key.setText("sk-alterschluessel")
        self._lage(server={"name": "Ollama", "url": "http://localhost:11434/v1",
                           "modelle": ["m"]})
        self.w._lokale_ki_suchen()
        self.assertEqual(self.w.vlm_key.text(), "")

    def test_ollama_wird_gestartet_wenn_installiert(self):
        """Der haeufigste Fall: installiert, aber nicht gestartet."""
        zustand = {"lauf": 0}

        def suchen(zusaetzlich=None, log=None, timeout=2.0):
            zustand["lauf"] += 1
            if zustand["lauf"] == 1:
                return None
            return {"name": "Ollama", "url": "http://localhost:11434/v1", "modelle": ["m"]}

        self._lage(ollama="C:/x/ollama.exe", gestartet="http://localhost:11434/v1")
        lokales_modell.server_suchen = suchen
        self.w._lokale_ki_suchen()
        self.assertEqual(self.w.vlm_model.text(), "m")

    def test_suchen_laedt_nichts(self):
        """Der wichtigste Test: ohne ausdrueckliche Zustimmung faellt kein Download an."""
        geladen = []
        echt = self.w._modell_laden
        self.w._modell_laden = lambda name: geladen.append(name)
        self.addCleanup(lambda: setattr(self.w, "_modell_laden", echt))
        self._lage(server=None, ollama="C:/x/ollama.exe", gestartet=None)
        self._keine_frage(QMessageBox.No)
        self.w._lokale_ki_suchen()
        self.assertEqual(geladen, [], "es wurde ohne Zustimmung heruntergeladen")

    def test_bei_zustimmung_wird_geladen(self):
        geladen = []
        echt = self.w._modell_laden
        self.w._modell_laden = lambda name: geladen.append(name)
        self.addCleanup(lambda: setattr(self.w, "_modell_laden", echt))
        self._lage(server=None, ollama="C:/x/ollama.exe", gestartet=None)
        gefragt = self._keine_frage(QMessageBox.Yes)
        self.w._lokale_ki_suchen()
        self.assertTrue(gefragt, "es wurde gar nicht gefragt")
        self.assertEqual(geladen, [lokales_modell.EMPFOHLEN[0][0]])

    def test_ohne_ollama_wird_gar_nicht_erst_gefragt(self):
        """Ohne Ollama gaebe es nichts zu laden — eine Rueckfrage waere sinnlos."""
        self._lage(server=None, ollama=None)
        gefragt = self._keine_frage(QMessageBox.Yes)
        self.w._lokale_ki_suchen()
        self.assertEqual(gefragt, [])

    def test_knopf_bleibt_bedienbar(self):
        """Der Knopf wird waehrend der Suche gesperrt. Bleibt er gesperrt haengen, ist die
        Funktion nach einem Fehlversuch tot."""
        self._lage(server=None, ollama=None)
        self._keine_frage()
        self.w._lokale_ki_suchen()
        self.assertTrue(self.w.lokale_ki_btn.isEnabled())


if __name__ == "__main__":
    unittest.main(verbosity=2)
