#!/usr/bin/env python3
"""
ForgePix — die Szenenbank darf nicht von einer Kamera beherrscht werden.

    python3 tests/test_szenenbank_kameramix.py

ForgePix soll oeffentlich werden, und das Entrausch-Modell soll allen Astrofotografen nuetzen,
nicht nur denen mit derselben Kamera. Ein Entrauscher lernt aber das Rauschprofil des Sensors,
den er am haeufigsten sieht — der Kameramix der Trainingsdaten entscheidet also darueber, fuer
wen das Modell taugt.

Der Bau sortierte die Serien streng nach Sub-Anzahl absteigend. Der Seestar S30 nimmt sehr viele
kurze Aufnahmen, seine Serien stehen damit alle vorn. Gemessen an den ersten sechs Serien von
Szenenbank v2:

    Seestar S30        96 Kacheln
    ZWO ASI294MC Pro   24 Kacheln
    ZWO ASI533MC Pro   24 Kacheln

also **4:1:1**. Wieder dieselbe Fehlerform: nichts schlaegt fehl, das Protokoll meldet lauter
erfolgreiche Serien, und heraus kaeme ein Seestar-Modell mit Beiwerk.

Reihum genommen stimmt das Verhaeltnis zu **jedem** Zeitpunkt, nicht erst am Ende. Das ist der
Punkt: diese Laeufe dauern Stunden und werden unterbrochen — ein Mix, der nur nach vollstaendigem
Durchlauf ausgewogen waere, ist in der Praxis nie ausgewogen.
"""
import ast
import collections
import io
import os
import sys
import unittest

sys.path.insert(0, "training")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "training"))

WURZEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
QUELLE = os.path.join(WURZEL, "training", "prepare_scenes_eigene.py")


def _lade():
    """Nur die eine Funktion holen — das Modul zieht sonst OpenCV und den ganzen Kern nach."""
    baum = ast.parse(io.open(QUELLE, encoding="utf-8").read())
    for k in baum.body:
        if isinstance(k, ast.FunctionDef) and k.name == "_nach_kamera_verschraenken":
            raum = {"collections": collections}
            exec(compile(ast.Module([k], []), QUELLE, "exec"), raum)
            return raum["_nach_kamera_verschraenken"]
    raise AssertionError("_nach_kamera_verschraenken nicht gefunden")


def _serie(kamera, n, i):
    """Ein Serieneintrag, wie ihn `serien_finden` liefert: (Schluessel, Pfadliste)."""
    return ((kamera, 60.0, "2026-01-0%d" % (i % 9 + 1), "ordner", (100, 100), 0), ["p"] * n)


class TestVerschraenkung(unittest.TestCase):

    def setUp(self):
        self.f = _lade()

    def test_der_gemessene_fall_wird_ausgewogen(self):
        """Die Ausgangslage nachgestellt: der Seestar hat die grossen Serien. Nach Groesse
        sortiert liefert das 4 Seestar-Serien in den ersten sechs — reihum genau zwei."""
        reihen = ([_serie("Seestar S30", 300 - i, i) for i in range(10)]
                  + [_serie("ZWO ASI294MC Pro", 200 - i, i) for i in range(5)]
                  + [_serie("ZWO ASI533MC Pro", 150 - i, i) for i in range(5)])
        nach_groesse = sorted(reihen, key=lambda kv: -len(kv[1]))
        vorher = collections.Counter(k[0][0] for k in nach_groesse[:6])
        self.assertEqual(vorher["Seestar S30"], 6,
                         "die Gegenprobe traegt nicht: hier muss die alte Sortierung "
                         "einseitig sein, sonst prueft der Test nichts")

        nachher = collections.Counter(k[0][0] for k in self.f(nach_groesse)[:6])
        self.assertEqual(sorted(nachher.values()), [2, 2, 2],
                         "der Mix ist immer noch schief: %s" % dict(nachher))

    def test_das_verhaeltnis_stimmt_an_jedem_punkt(self):
        """Der eigentliche Grund fuer das Reihum: diese Laeufe dauern Stunden und werden
        unterbrochen. Ein Mix, der erst am Ende stimmt, hilft dann nichts."""
        reihen = ([_serie("A", 300 - i, i) for i in range(12)]
                  + [_serie("B", 100 - i, i) for i in range(12)])
        raus = self.f(reihen)
        for schnitt in range(2, len(raus) + 1, 2):
            z = collections.Counter(k[0][0] for k in raus[:schnitt])
            self.assertEqual(z["A"], z["B"],
                             "nach %d Serien: %s" % (schnitt, dict(z)))

    def test_ungleich_viele_serien_laufen_nicht_leer(self):
        """Hat eine Kamera weniger Serien, muessen die uebrigen trotzdem alle drankommen."""
        reihen = [_serie("A", 100, i) for i in range(5)] + [_serie("B", 90, 0)]
        raus = self.f(reihen)
        self.assertEqual(len(raus), 6)
        self.assertEqual(collections.Counter(k[0][0] for k in raus), {"A": 5, "B": 1})

    def test_eine_einzige_kamera_bleibt_unveraendert(self):
        """Die Gegenprobe: wer nur eine Kamera hat, darf keine Umsortierung bemerken."""
        reihen = [_serie("A", 300 - i, i) for i in range(6)]
        self.assertEqual(self.f(reihen), reihen)

    def test_nichts_geht_verloren(self):
        reihen = ([_serie("A", 300 - i, i) for i in range(7)]
                  + [_serie("B", 100 - i, i) for i in range(3)]
                  + [_serie("C", 50 - i, i) for i in range(11)])
        self.assertEqual(sorted(map(repr, self.f(reihen))), sorted(map(repr, reihen)))


class TestObergrenze(unittest.TestCase):
    """Die Option muss wirken — eine, die niemand liest, ist ein Versprechen ohne Wirkung."""

    def setUp(self):
        self.quelle = io.open(QUELLE, encoding="utf-8").read()

    def test_die_option_existiert_und_wird_gelesen(self):
        self.assertIn('"--max-je-kamera"', self.quelle)
        self.assertIn("args.max_je_kamera", self.quelle)

    def test_sie_zaehlt_bei_einer_fortsetzung_mit(self):
        """Sonst haette jeder zweite Lauf seine eigene, frische Obergrenze — und die
        Deckelung waere ueber mehrere Laeufe hinweg wirkungslos."""
        kopf = self.quelle.split("for i, (schluessel, pfade) in enumerate")[0]
        self.assertIn("je_kamera[str(eintrag.get(\"kamera\")", kopf,
                      "die Obergrenze beruecksichtigt fortgesetzte Laeufe nicht")

    def test_die_verschraenkung_wird_wirklich_benutzt(self):
        self.assertIn("_nach_kamera_verschraenken(sorted(", self.quelle,
                      "die Serien werden weiterhin nur nach Groesse sortiert")


if __name__ == "__main__":
    unittest.main(verbosity=2)
