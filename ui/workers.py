#!/usr/bin/env python3
"""
ui/workers.py — Hintergrund-Threads & Versions-Helfer für ForgePix.

Aus ui/main_window.py ausgelagert (Modularisierung): enthält keine GUI-/self-Abhängigkeiten,
nur QThread-Worker und eine reine Vergleichsfunktion.
"""
from PySide6.QtCore import QObject, QThread, Signal


class _AnalyzeWorker(QThread):
    """Fokusreihen-Analyse im Hintergrund-Thread (blockiert die GUI nicht, auch bei RAWs)."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def run(self):
        try:
            import focus_analysis as fa
            self.done.emit(fa.analyze_series(self.paths, log=lambda *a: None))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class _ToolWorker(QThread):
    """Extern-Tool (GraXpert/StarNet/Starless-Workflow …) im Hintergrund-Thread.

    Vorher liefen diese subprocess-Aufrufe (bis 30 min Timeout!) synchron im GUI-Thread
    → Beachball, kein Repaint. `fn(log)` bekommt einen Log-Callback, dessen Meldungen als
    Signal queued im GUI-Thread ankommen (direktes Anfassen von Widgets aus dem Worker
    wäre nicht threadsicher)."""
    done = Signal(object)
    failed = Signal(str)
    log = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn(self.log.emit))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class _UpdateChecker(QObject):
    """Fragt einmalig die neueste GitHub-Release-Version ab (nur lesen, leise bei Offline/Fehler).

    Läuft bewusst in einem Python-Daemon-Thread (kein QThread): so kann beim App-Ende NIE ein
    QThread-„destroyed while running"-Abort auftreten, selbst wenn man sofort nach dem Start quittet.
    Das Ergebnis wird per Signal (Queued-Connection) in den GUI-Thread zurückgegeben.
    """
    found = Signal(str, str)  # (neueste Version ohne 'v', Release-URL)

    REPO = "samuelvoltarius/ForgePix"

    def start(self):
        import threading
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self):
        try:
            import json
            import urllib.request
            url = f"https://api.github.com/repos/{self.REPO}/releases/latest"
            req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                                       "User-Agent": "ForgePix"})
            with urllib.request.urlopen(req, timeout=4) as r:
                data = json.load(r)
            tag = str(data.get("tag_name", "")).lstrip("vV")
            html = data.get("html_url") or f"https://github.com/{self.REPO}/releases"
            if tag:
                self.found.emit(tag, html)
        except Exception:
            pass  # offline / Rate-Limit / kein Release -> still bleiben


def _version_newer(latest, current):
    """True, wenn latest (z.B. '1.10.0') neuer als current ist — numerischer Tupel-Vergleich."""
    def parts(v):
        out = []
        for chunk in str(v).split("."):
            num = "".join(c for c in chunk if c.isdigit())
            out.append(int(num) if num else 0)
        return out
    a, b = parts(latest), parts(current)
    n = max(len(a), len(b))
    a += [0] * (n - len(a)); b += [0] * (n - len(b))
    return a > b
