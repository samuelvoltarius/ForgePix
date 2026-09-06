"""Gemeinsame Hilfen für die Oberflächen-Tests.

**Warum es diese Datei gibt — der teuerste Fehler dieser Testsuite:**

Die GUI-Tests haben `MainWindow._restore_settings` und `_save_settings` auf KLASSENEBENE durch
einen `MagicMock` ersetzt, damit beim Bauen des Fensters keine echten Einstellungen gelesen oder
geschrieben werden. Das ist die naheliegende Lösung und sie funktioniert auf vielen Rechnern.

Unter **Python 3.14 mit PySide6 6.10.1** stürzt der Interpreter dabei ab — `access violation` in
`ui/welcome.py` an der Stelle `about.clicked.connect(self._show_about)`. PySide6 sieht sich beim
Verbinden eines Signals die Klasse an; ein `MagicMock` als Klassenattribut eines `QObject`
erfindet auf jede Anfrage ein neues Attribut, und die Metaobjekt-Maschinerie läuft ins Leere.

Das Tückische daran ist nicht der Absturz, sondern was er anrichtet: `unittest discover` bricht
mitten im Lauf ab, **ohne Zusammenfassung und ohne das Wort „FAILED"**. Am 06.09.2026 starb die
Suite so beim 27. von 692 Tests; wer nur nach „FAILED" schaut, hält den Lauf für bestanden.
Die CI hat es nie gesehen, weil dort Python 3.12 läuft (dort gehen 734 Tests durch).

**Die Lösung ist eine Zeile:** statt eines `MagicMock` eine echte, leere Funktion einsetzen. Die
Absicht bleibt dieselbe — das Fenster liest und schreibt keine Einstellungen — und PySide6 findet
auf der Klasse das vor, was es erwartet. Auf die beiden Mocks hat ohnehin nie ein Test zugegriffen.
"""
from contextlib import contextmanager
from unittest.mock import patch


def _nichts(self, *args, **kwargs):
    """Ersatz für die Einstellungs-Methoden: tut nichts, ist aber eine echte Funktion."""
    return None


@contextmanager
def stilles_hauptfenster():
    """Fenster bauen, ohne Einstellungen zu lesen/schreiben und ohne Update-Abfrage.

    Verwendung::

        with stilles_hauptfenster():
            fenster = MainWindow()

    Siehe den Modulkopf: die Ersatzmethoden müssen echte Funktionen sein, kein `MagicMock`.
    """
    from ui.main_window import MainWindow
    with patch.object(MainWindow, "_restore_settings", _nichts), \
         patch.object(MainWindow, "_save_settings", _nichts), \
         patch("ui.main_window._UpdateChecker.start", lambda self, *a, **k: None):
        yield


def stilles_hauptfenster_aufsetzen(testfall):
    """Dasselbe für `setUp()`: die Ersetzungen laufen bis zum Ende des Testfalls.

    `testfall` ist die `TestCase`-Instanz; aufgeräumt wird über deren `addCleanup`.
    """
    from ui.main_window import MainWindow
    for ziel, ersatz in ((("object", MainWindow, "_restore_settings"), _nichts),
                         (("object", MainWindow, "_save_settings"), _nichts),
                         (("name", "ui.main_window._UpdateChecker.start"),
                          lambda self, *a, **k: None)):
        if ziel[0] == "object":
            kontext = patch.object(ziel[1], ziel[2], ersatz)
        else:
            kontext = patch(ziel[1], ersatz)
        kontext.start()
        testfall.addCleanup(kontext.stop)
