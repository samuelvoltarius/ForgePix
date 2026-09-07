#!/usr/bin/env python3
"""
ForgePix — Tests für den Berater (core/berater.py), Stufe 3.

    python3 tests/test_berater.py

Diese Tests laufen **ohne Netz**. Das Sprachmodell wird durch eine Funktion ersetzt, die eine
feste Antwort liefert — auch die kaputten Antworten, die am echten Modell beobachtet wurden.

Der Punkt dieser Tests ist nicht, ob das Modell klug antwortet. Das lässt sich nicht festnageln
und ändert sich mit jedem Modell. Der Punkt ist, dass **eine falsche Antwort nicht durchkommt**:

* ein Schalter, den es nicht gibt,
* eine Zahl außerhalb der Spanne (am echten Modell gesehen: „Sättigung auf Maximum" wurde
  wörtlich befolgt),
* eine Antwort, die gar kein JSON ist,
* ein nicht erreichbarer Endpunkt.

In jedem dieser Fälle muss der Vorschlag verworfen UND benannt werden. Ein still verschluckter
Vorschlag ist schlimmer als ein abgelehnter: niemand merkt, dass etwas fehlt.
"""
import os
import sys
import unittest

sys.path.insert(0, "core")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core"))

import berater  # noqa: E402


def _stille(*a, **k):
    pass


class TestPruefung(unittest.TestCase):

    def test_gueltige_gehen_durch(self):
        g, v = berater.pruefen(["--bg-extract", "--astro-saturation 1.3"])
        self.assertEqual(g, ["--bg-extract", "--astro-saturation 1.3"])
        self.assertEqual(v, [])

    def test_unbekannter_schalter_wird_verworfen_und_benannt(self):
        g, v = berater.pruefen(["--gibtsnicht"])
        self.assertEqual(g, [])
        self.assertEqual(len(v), 1)
        self.assertIn("--gibtsnicht", v[0])
        self.assertIn("Katalog", v[0])

    def test_wert_ausserhalb_der_spanne_wird_NICHT_beschnitten(self):
        """Wer 5.0 vorschlaegt, wo 2.0 das Maximum ist, hat den Schalter nicht verstanden.
        Stilles Beschneiden wuerde daraus eine brauchbar aussehende Einstellung machen und den
        Hinweis verschlucken, dass der ganze Vorschlag fraglich ist."""
        g, v = berater.pruefen(["--astro-saturation 5.0"])
        self.assertEqual(g, [])
        self.assertIn("ausserhalb", v[0])

    def test_grenzen_selbst_sind_gueltig(self):
        g, _v = berater.pruefen(["--astro-saturation 0.5", "--astro-saturation 2.0"])
        self.assertEqual(len(g), 2)

    def test_wert_an_einem_schalter_ohne_wert(self):
        g, v = berater.pruefen(["--bg-extract 1"])
        self.assertEqual(g, [])
        self.assertIn("keinen Wert", v[0])

    def test_fehlender_und_unlesbarer_wert(self):
        g, v = berater.pruefen(["--astro-saturation", "--astro-denoise abc"])
        self.assertEqual(g, [])
        self.assertEqual(len(v), 2)

    def test_leere_eingabe(self):
        self.assertEqual(berater.pruefen(None), ([], []))
        self.assertEqual(berater.pruefen([]), ([], []))

    def test_jeder_katalog_schalter_existiert_in_der_pipeline(self):
        """Dieselbe Falle wie beim Regelwerk: dort stand `--astro-bg-extract`, die Option heisst
        aber `--bg-extract`. Ein Katalog, der Schalter anbietet, die es nicht gibt, laesst das
        Modell etwas vorschlagen, das anschliessend an argparse scheitert."""
        import subprocess
        wurzel = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        hilfe = subprocess.run(
            [sys.executable, "-X", "utf8", os.path.join(wurzel, "core", "focus_cull_stack.py"),
             "--help"],
            capture_output=True, text=True, encoding="utf-8", timeout=300).stdout
        self.assertIn("--input", hilfe, "die Hilfe liess sich nicht lesen")
        fehlend = sorted(s for s in berater.KATALOG if s not in hilfe)
        self.assertEqual(fehlend, [], "Katalog bietet unbekannte Schalter an: %s" % fehlend)


class TestAntwortLesen(unittest.TestCase):

    def test_json_ohne_zaun(self):
        self.assertEqual(berater._json_aus('{"a": 1}'), {"a": 1})

    def test_json_im_zaun(self):
        """Am echten Modell beobachtet: mal mit ```json-Zaun, mal ohne."""
        self.assertEqual(berater._json_aus('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(berater._json_aus('```\n{"a": 1}\n```'), {"a": 1})

    def test_json_mit_geschwaetz_davor(self):
        self.assertEqual(berater._json_aus('Gerne! {"a": 1} Viel Erfolg.'), {"a": 1})

    def test_kein_json(self):
        for t in ("", None, "Ich kann das leider nicht.", "{kaputt"):
            self.assertIsNone(berater._json_aus(t))


class TestFragen(unittest.TestCase):
    """`fragen` mit ersetztem Modell — kein Netz noetig."""

    def _mit_antwort(self, antwort):
        import focus_cull_stack
        echt = focus_cull_stack._vlm_chat
        focus_cull_stack._vlm_chat = lambda *a, **k: antwort
        self.addCleanup(lambda: setattr(focus_cull_stack, "_vlm_chat", echt))
        # Modellname ausdruecklich: sonst fragte `fragen` den Server nach seinen Modellen und
        # der Test braeuchte Netz.
        return berater.fragen("Bericht", "Rat", "waermer bitte",
                              "http://beispiel/v1", model="qwen", log=_stille)

    def test_gute_antwort(self):
        e = self._mit_antwort('{"einstellungen": ["--astro-saturation 1.3"], '
                              '"begruendung": "Waermer."}')
        self.assertEqual(e["einstellungen"], ["--astro-saturation 1.3"])
        self.assertEqual(e["quelle"], "modell")
        self.assertEqual(e["verworfen"], [])

    def test_antwort_mit_erfundenem_schalter(self):
        e = self._mit_antwort('{"einstellungen": ["--bg-extract", "--zauberstab 3"], '
                              '"begruendung": "x"}')
        self.assertEqual(e["einstellungen"], ["--bg-extract"])
        self.assertEqual(len(e["verworfen"]), 1)
        self.assertIn("--zauberstab 3", e["verworfen"][0])

    def test_antwort_ist_kein_json(self):
        e = self._mit_antwort("Klar, mach ich!")
        self.assertEqual(e["einstellungen"], [])
        self.assertEqual(e["quelle"], "keine")
        self.assertIn("kein JSON", e["begruendung"])

    def test_modell_nicht_erreichbar(self):
        import focus_cull_stack

        def kaputt(*a, **k):
            raise OSError("Verbindung abgelehnt")

        echt = focus_cull_stack._vlm_chat
        focus_cull_stack._vlm_chat = kaputt
        self.addCleanup(lambda: setattr(focus_cull_stack, "_vlm_chat", echt))
        e = berater.fragen("B", "R", "waermer", "http://beispiel/v1", model="qwen",
                           log=_stille)
        self.assertEqual(e["einstellungen"], [])
        self.assertEqual(e["quelle"], "keine")
        self.assertIn("Verbindung abgelehnt", e["begruendung"])

    def test_ohne_modellnamen_wird_der_server_gefragt(self):
        """Vorher fiel die Oberflaeche bei leerem Modellfeld auf "gpt-4o-mini" zurueck — auch
        bei einem lokalen Server. Am laufenden vLLM geprueft: 404, "The model `gpt-4o-mini`
        does not exist." Die KI-Funktion tat kommentarlos nichts."""
        import focus_cull_stack
        gefragt = []
        echt_w = focus_cull_stack.vlm_modelle
        echt_c = focus_cull_stack._vlm_chat
        focus_cull_stack.vlm_modelle = lambda *a, **k: (gefragt.append(a) or ["mein-modell"])
        focus_cull_stack._vlm_chat = (
            lambda ep, mo, *a, **k: '{"einstellungen": ["--bg-extract"], "begruendung": "%s"}'
            % mo)
        self.addCleanup(lambda: setattr(focus_cull_stack, "vlm_modelle", echt_w))
        self.addCleanup(lambda: setattr(focus_cull_stack, "_vlm_chat", echt_c))
        e = berater.fragen("B", "R", "waermer", "http://beispiel/v1", log=_stille)
        self.assertTrue(gefragt, "der Server wurde gar nicht nach Modellen gefragt")
        self.assertEqual(e["begruendung"], "mein-modell",
                         "der ermittelte Name wurde nicht benutzt")

    def test_server_ohne_modelle_gibt_klare_auskunft(self):
        import focus_cull_stack
        echt = focus_cull_stack.vlm_modelle
        focus_cull_stack.vlm_modelle = lambda *a, **k: []
        self.addCleanup(lambda: setattr(focus_cull_stack, "vlm_modelle", echt))
        e = berater.fragen("B", "R", "waermer", "http://beispiel/v1", log=_stille)
        self.assertEqual(e["quelle"], "keine")
        self.assertIn("kein Modell", e["begruendung"])

    def test_ohne_endpunkt_wird_gar_nicht_gefragt(self):
        e = berater.fragen("B", "R", "waermer", None, log=_stille)
        self.assertEqual(e["quelle"], "keine")

    def test_ohne_wunsch_wird_gar_nicht_gefragt(self):
        for w in (None, "", "   "):
            self.assertEqual(berater.fragen("B", "R", w, "http://x/v1", model="qwen",
                                            log=_stille)["quelle"], "keine")


class TestAusgabe(unittest.TestCase):

    def test_ohne_modell_kein_text(self):
        self.assertEqual(berater.text({"quelle": "keine"}), "")

    def test_herkunft_steht_immer_dabei(self):
        """Das Wichtigste am Ausgabetext. Gemessen: das Modell widersprach einer Zahl, die
        woertlich im Prompt stand ('die Sterne sind bereits rund' bei Rundheit 1,63) — fluessig
        formuliert und mit Fachbegriff. Wer nicht weiss, dass da ein Sprachmodell schreibt,
        haelt das fuer einen Befund."""
        t = berater.text({"quelle": "modell", "einstellungen": ["--bg-extract"],
                          "begruendung": "Weil.", "verworfen": []})
        self.assertIn("NICHT gemessen", t)

    def test_verworfenes_steht_im_text(self):
        t = berater.text({"quelle": "modell", "einstellungen": [], "begruendung": "",
                          "verworfen": ["--zauberstab (nicht im Katalog)"]})
        self.assertIn("--zauberstab", t)

    def test_leere_empfehlung_wird_benannt(self):
        t = berater.text({"quelle": "modell", "einstellungen": [],
                          "begruendung": "Geht nicht.", "verworfen": []})
        self.assertIn("keine Einstellung", t)


if __name__ == "__main__":
    unittest.main(verbosity=2)
