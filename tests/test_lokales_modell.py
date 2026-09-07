#!/usr/bin/env python3
"""
ForgePix — Tests für die lokale KI (core/lokales_modell.py), Stufe 4.

    python3 tests/test_lokales_modell.py

Diese Tests gehen **nicht ins Netz** und starten **kein** Ollama. Alles, was nach draußen
greifen würde, wird ersetzt.

Der wichtigste Test hier ist `test_suchen_laedt_nichts_herunter`. Ein Modell ist mehrere hundert
Megabyte; ein Programm, das so etwas von selbst holt, weil es gerade praktisch wäre, ist ein
Programm, dem man nicht mehr traut. Herunterladen darf ausschließlich passieren, wenn jemand es
ausdrücklich anfordert — nicht beim Start, nicht beim Suchen, nicht als stiller Rückfall.
"""
import os
import sys
import unittest

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import lokales_modell  # noqa: E402


def _stille(*a, **k):
    pass


class TestServerSuchen(unittest.TestCase):

    def _antworten(self, tabelle):
        """`_antwortet` durch eine Tabelle url -> modelle (oder None) ersetzen."""
        echt = lokales_modell._antwortet
        lokales_modell._antwortet = lambda url, timeout=2.0: tabelle.get(url.rstrip("/"))
        self.addCleanup(lambda: setattr(lokales_modell, "_antwortet", echt))

    def test_findet_den_ersten_der_antwortet(self):
        self._antworten({"http://localhost:11434/v1": ["qwen2.5:1.5b"]})
        g = lokales_modell.server_suchen(log=_stille)
        self.assertEqual(g["name"], "Ollama")
        self.assertEqual(g["modelle"], ["qwen2.5:1.5b"])

    def test_findet_auch_die_spaeteren(self):
        """Wer llama.cpp oder LM Studio laufen hat, soll nichts einstellen muessen."""
        self._antworten({"http://localhost:1234/v1": ["mein-modell"]})
        g = lokales_modell.server_suchen(log=_stille)
        self.assertEqual(g["name"], "LM Studio")

    def test_eigene_adresse_hat_vorrang(self):
        self._antworten({"http://localhost:11434/v1": ["a"], "http://anderswo:9/v1": ["b"]})
        g = lokales_modell.server_suchen(zusaetzlich="http://anderswo:9/v1", log=_stille)
        self.assertEqual(g["url"], "http://anderswo:9/v1")

    def test_keiner_da_gibt_None(self):
        self._antworten({})
        self.assertIsNone(lokales_modell.server_suchen(log=_stille))

    def test_server_ohne_modelle_zaehlt_als_gefunden(self):
        """Ein laufender Server ohne geladenes Modell ist etwas anderes als kein Server —
        der Unterschied entscheidet, was dem Benutzer geraten wird."""
        self._antworten({"http://localhost:11434/v1": []})
        g = lokales_modell.server_suchen(log=_stille)
        self.assertIsNotNone(g)
        self.assertEqual(g["modelle"], [])

    def test_suchen_laedt_nichts_herunter(self):
        """Der wichtigste Test. Ein Modell ist mehrere hundert Megabyte; nichts davon darf
        beilaeufig passieren."""
        self._antworten({})
        gerufen = []
        echt = lokales_modell.modell_holen
        lokales_modell.modell_holen = lambda *a, **k: gerufen.append(a)
        self.addCleanup(lambda: setattr(lokales_modell, "modell_holen", echt))
        lokales_modell.server_suchen(log=_stille)
        lokales_modell.bericht(log=_stille)
        self.assertEqual(gerufen, [], "es wurde ungefragt ein Download angestossen")


class TestBericht(unittest.TestCase):

    def _lage(self, server=None, ollama=None, modelle=()):
        for name, wert in (("_antwortet", lambda url, timeout=2.0: server),
                           ("ollama_pfad", lambda: ollama),
                           ("ollama_modelle", lambda log=None: list(modelle))):
            echt = getattr(lokales_modell, name)
            setattr(lokales_modell, name, wert)
            self.addCleanup(lambda n=name, e=echt: setattr(lokales_modell, n, e))

    def test_laufender_server_wird_genannt(self):
        self._lage(server=["qwen2.5:1.5b"])
        t = lokales_modell.bericht(log=_stille)
        self.assertIn("Lokale KI laeuft", t)
        self.assertIn("qwen2.5:1.5b", t)

    def test_ohne_alles_steht_der_naechste_schritt_da(self):
        """Eine Auskunft "keine KI gefunden" ohne den naechsten Schritt hilft niemandem."""
        self._lage(server=None, ollama=None)
        t = lokales_modell.bericht(log=_stille)
        self.assertIn("nicht installiert", t)
        self.assertIn("ollama.com", t)
        self.assertIn("Vorschlaege", t)

    def test_installiert_aber_nicht_gestartet(self):
        self._lage(server=None, ollama="C:/x/ollama.exe", modelle=[("qwen2.5:1.5b", "1.0 GB")])
        t = lokales_modell.bericht(log=_stille)
        self.assertIn("nicht gestartet", t)
        self.assertIn("qwen2.5:1.5b", t)

    def test_es_steht_dabei_dass_es_auch_ohne_geht(self):
        """Ohne diesen Satz liest sich der Bericht wie eine fehlende Voraussetzung. Die
        Bearbeitung laeuft vollstaendig ohne KI."""
        self._lage(server=None, ollama=None)
        self.assertIn("ohne KI", lokales_modell.bericht(log=_stille))


class TestModellHolen(unittest.TestCase):

    def test_ohne_ollama_klare_absage(self):
        echt = lokales_modell.ollama_pfad
        lokales_modell.ollama_pfad = lambda: None
        self.addCleanup(lambda: setattr(lokales_modell, "ollama_pfad", echt))
        ok, meldung = lokales_modell.modell_holen("qwen2.5:1.5b-instruct", log=_stille)
        self.assertFalse(ok)
        self.assertIn("nicht installiert", meldung)

    def test_empfehlungen_sind_wohlgeformt(self):
        self.assertTrue(lokales_modell.EMPFOHLEN)
        for name, groesse, grund in lokales_modell.EMPFOHLEN:
            self.assertIn(":", name, "ein Ollama-Name hat die Form modell:variante")
            self.assertIn("GB", groesse)
            self.assertTrue(grund)


class TestOllamaPfad(unittest.TestCase):

    def test_which_wird_zuerst_gefragt(self):
        import shutil
        echt = shutil.which
        shutil.which = lambda n: "/pfad/zu/ollama" if n == "ollama" else None
        self.addCleanup(lambda: setattr(shutil, "which", echt))
        self.assertEqual(lokales_modell.ollama_pfad(), "/pfad/zu/ollama")

    def test_nicht_vorhanden_gibt_None(self):
        import shutil
        echt_w, echt_f = shutil.which, os.path.isfile
        shutil.which = lambda n: None
        os.path.isfile = lambda p: False
        self.addCleanup(lambda: setattr(shutil, "which", echt_w))
        self.addCleanup(lambda: setattr(os.path, "isfile", echt_f))
        self.assertIsNone(lokales_modell.ollama_pfad())


if __name__ == "__main__":
    unittest.main(verbosity=2)
