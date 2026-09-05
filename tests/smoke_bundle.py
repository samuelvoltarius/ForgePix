"""Run a synthetic focus stack through the packaged CLI and read its output."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np


def main():
    root = Path(__file__).resolve().parents[1]
    if "--source" in sys.argv:
        command = [sys.executable, str(root / "focus_stack_gui.py")]
    else:
        binary = {"win32": "dist/ForgePix/ForgePix.exe",
                  "darwin": "dist/ForgePix.app/Contents/MacOS/ForgePix"}.get(
                      sys.platform, "dist/ForgePix/ForgePix")
        command = [str(root / binary)]
    with tempfile.TemporaryDirectory(prefix="forgepix-smoke-") as d:
        source, work = Path(d) / "input", Path(d) / "work"
        source.mkdir()
        rng = np.random.default_rng(42)
        base = rng.integers(30, 230, size=(120, 160, 3), dtype=np.uint8)
        for i in range(4):
            frame = cv2.GaussianBlur(base, (0, 0), 2)
            frame[:, i * 40:(i + 1) * 40] = base[:, i * 40:(i + 1) * 40]
            cv2.imencode(".png", frame)[1].tofile(str(source / ("f%d.png" % i)))
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run(command + ["--cli", "--input", str(source), "--work", str(work)],
                                env=env, capture_output=True, timeout=180, cwd=root)
        if result.returncode:
            raise RuntimeError("Packaged CLI failed: " + result.stderr.decode(errors="replace"))
        outputs = list((work / "stack").glob("*"))
        images = [cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_UNCHANGED) for p in outputs]
        if not any(im is not None and im.size and float(im.std()) > 1 for im in images):
            raise RuntimeError("No readable, nonconstant stack output")
        print("CLI smoke test passed: readable focus stack exported")


if __name__ == "__main__":
    main()
