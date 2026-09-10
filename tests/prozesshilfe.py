"""Unterprozesse aus Tests starten — mit einem gueltigen stdin.

Der Fehler, um den es geht:

    OSError: [WinError 6] Das Handle ist ungueltig
    subprocess.py:1430, beim ANLEGEN des Prozesses

Er trat je nach Lauf in vier bis sieben Tests auf, immer in anderen, und einzeln nachgefahren
waren sie gruen. Das sah nach einem Lastproblem aus — **war es nicht**. Die Ursache ist
`capture_output=True` ohne `stdin=`:

* `capture_output=True` leitet stdout und stderr in Rohre um, **stdin aber nicht** — das erbt
  der Kindprozess vom Elternprozess.
* pytest ersetzt `sys.stdin` durch ein Objekt ohne echtes Handle. Wird waehrend eines Laufs auf
  diese Art der Abfangung umgeschaltet (etwa weil ein Test `capsys` benutzt), hat der
  Elternprozess kein Handle mehr zu vererben, und Windows lehnt das Duplizieren ab.

Daraus folgt auch die scheinbare Zufaelligkeit: es haengt davon ab, was **vorher** lief.

Nachgewiesen mit zwei Tests in derselben Datei, einer mit und einer ohne `stdin=`: der ohne
faellt unter pytest zuverlaessig um, der mit laeuft. Ausserhalb von pytest laufen beide.

Darum setzt `lauf()` `stdin=subprocess.DEVNULL`, wenn der Aufrufer nichts anderes sagt. Kein
Wiederholen, kein Abfangen von Fehlern: ein Prozess, der laeuft und mit einem Fehlercode
zurueckkommt, ist ein Befund am Programm und muss durchschlagen.
"""
import subprocess


def lauf(*args, **kwargs):
    """Wie `subprocess.run`, aber mit einem gueltigen stdin fuer den Kindprozess.

    `input=` bleibt unangetastet: `subprocess.run` baut daraus selbst ein Rohr und lehnt ein
    zusaetzliches `stdin=` mit „stdin and input arguments may not both be used" ab. Wer etwas
    hereinreicht, hat also ohnehin ein gueltiges Handle.
    """
    if "stdin" not in kwargs and "input" not in kwargs:
        kwargs["stdin"] = subprocess.DEVNULL
    return subprocess.run(*args, **kwargs)
