#!/usr/bin/env python3
"""
focus_stack_gui.py — Starter für ForgePix.

Die Oberfläche liegt modular im Paket `ui/` (ui/main_window.py + ui/components.py).
Diese Datei ist nur der Einstiegspunkt und re-exportiert die öffentlichen Namen,
damit `python3 focus_stack_gui.py`, das .app-Bundle und bestehende Skripte/Tests
(`import focus_stack_gui as g; g.MainWindow / g.THEME / g.AdjustDialog …`) weiter funktionieren.

Start:  python3 focus_stack_gui.py
"""
import os
import sys

# Projekt-Root auf den Importpfad — NUR im Quellcode-Modus. Im gebündelten Binary
# (PyInstaller) würde das den Pfad verschmutzen und cv2 doppelt auflösen (Rekursionsfehler).
if not getattr(sys, "frozen", False):
    _root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, _root)
    sys.path.insert(0, os.path.join(_root, "core"))   # Engine-Module liegen jetzt in core/

from ui.main_window import MainWindow, THEME, main, APP_NAME, ICON, ICON_PNG  # noqa: F401
from ui.components import (  # noqa: F401  (Rück-Export für bestehende Skripte/Tests)
    CompareSlider, CurveWidget, AdjustDialog, RetouchDialog, _Canvas,
    _bgr_to_pixmap, histogram_pixmap, adjust_image, HSL_BANDS,
    help_btn, _row, reveal_in_files, open_path, notify,
)

if __name__ == "__main__":
    # UTF-8-Ausgabe erzwingen, bevor irgendetwas loggt: die Logzeilen enthalten „→/─/σ",
    # die die Windows-Locale-Codepage (cp1252) nicht kodieren kann → UnicodeEncodeError.
    from constants import force_utf8_stdio
    force_utf8_stdio()
    # Im gebündelten Binary (PyInstaller) ist `sys.executable` das Binary selbst, nicht python.
    # Damit der GUI-Subprozess die Pipeline starten kann, dient `--cli` als zweiter Einstiegspunkt:
    #   forgepix --cli --input … → ruft focus_cull_stack.main() statt der GUI.
    if len(sys.argv) > 1 and sys.argv[1] in {"--photometry", "--photometry-catalogue"}:
        import argparse
        import json
        import signal
        import threading
        from pathlib import Path
        from constants import ForgePixFehler
        mode = sys.argv[1]
        parser = argparse.ArgumentParser(description="Native Sternphotometrie: Diagnose ohne Farbänderung")
        parser.add_argument("--catalogue", required=True, help="Separater Gaia-DR3/GSPC-Feldauszug als NPZ")
        if mode == "--photometry-catalogue":
            parser.add_argument("--ra", required=True, type=float, help="Feldmitte in Grad")
            parser.add_argument("--dec", required=True, type=float, help="Feldmitte in Grad")
            parser.add_argument("--radius", type=float, default=.5, help="Feldradius in Grad")
            parser.add_argument("--max-mag", type=float, default=15.5)
            parser.add_argument("--limit", type=int, default=20000)
        else:
            parser.add_argument("--input", required=True, help="Lineares Mono-/RGB-FITS mit WCS")
            parser.add_argument("--output-root")
            parser.add_argument("--epoch", type=float, help="Dokumentierte effektive Aufnahmeepoche als Julianisches Jahr")
            parser.add_argument("--saturation", nargs="+", type=float, help="Belegte Sättigung in Eingangs-Pixeleinheiten; ein Wert oder R G B")
            parser.add_argument("--variance", help="Varianz-FITS gleicher Form in Eingangseinheit²; keine Drizzle-Gewichte")
            parser.add_argument("--linear", action="store_true", help="Lineare Eingabe ausdrücklich bestätigen, falls Headernachweis fehlt")
            parser.add_argument("--aperture", type=float, default=6.)
            parser.add_argument("--annulus-inner", type=float, default=9.)
            parser.add_argument("--annulus-outer", type=float, default=14.)
        options = parser.parse_args(sys.argv[2:])
        cancel = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: cancel.set())
        try:
            if mode == "--photometry-catalogue":
                from photometric_catalogue import download_field
                path = Path(options.catalogue).resolve()
                if path.exists() or not path.parent.is_dir():
                    raise ForgePixFehler("Bitte eine neue Katalogdatei in einem vorhandenen Ordner wählen.")
                catalogue = download_field(options.ra, options.dec, options.radius,
                    max_mag=options.max_mag, limit=options.limit, cancel=cancel)
                catalogue.save(path)
                print(json.dumps({"catalogue_path": str(path), "rows": len(catalogue.columns["source_id"])}, ensure_ascii=False))
            else:
                from photometry_file import diagnose_file
                saturation = options.saturation
                if saturation and len(saturation) == 1:
                    saturation = saturation[0]
                result = diagnose_file(options.input, options.catalogue, options.output_root,
                    epoch_jyear=options.epoch, saturation=saturation, variance_path=options.variance,
                    linear_confirmed=options.linear, aperture_radius=options.aperture,
                    annulus_inner=options.annulus_inner, annulus_outer=options.annulus_outer, cancel=cancel)
                print(json.dumps({key: result[key] for key in ("report_path", "csv_path")}, ensure_ascii=False))
        except (ForgePixFehler, OSError, ValueError) as exc:
            parser.exit(130 if cancel.is_set() else 1, str(exc) + "\n")
    elif len(sys.argv) > 1 and sys.argv[1] in {"--recipe", "--solve"}:
        import argparse
        import json
        import signal
        import threading
        from constants import ForgePixFehler
        mode = sys.argv[1]
        parser = argparse.ArgumentParser(description="Gespeichertes Astro-Rezept oder eigene lokale Astrometrie")
        parser.add_argument("--input", required=True)
        parser.add_argument("--output-root")
        if mode == "--recipe":
            parser.add_argument("--file", required=True, help="Gespeichertes ForgePix-Rezept")
            parser.add_argument("--experimental", action="store_true")
        else:
            parser.add_argument("--catalogue", required=True, help="Lokaler Gaia-Auszug als NPZ")
            parser.add_argument("--ra", required=True, type=float, help="Bildmitte in Grad")
            parser.add_argument("--dec", required=True, type=float, help="Bildmitte in Grad")
            parser.add_argument("--scale", required=True, type=float, help="Bogensekunden pro Pixel")
        options = parser.parse_args(sys.argv[2:])
        cancel = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: cancel.set())
        try:
            if mode == "--recipe":
                import recipes
                result = recipes.run_recipe(options.file, options.input, options.output_root,
                    allow_experimental=options.experimental, cancel=cancel)
                print(json.dumps({key: result.get(key) for key in
                    ("status", "result_path", "journal_path", "error")}, ensure_ascii=False))
                sys.exit(0 if result["status"] == "completed" else 130 if result["status"] == "cancelled" else 1)
            else:
                from astrometry_file import solve_file
                result = solve_file(options.input, options.catalogue,
                    {"ra": options.ra, "dec": options.dec, "pixelscale_arcsec": options.scale},
                    options.output_root, cancel=cancel)
                print(json.dumps({key: result[key] for key in ("result_path", "report_path")}, ensure_ascii=False))
        except (ForgePixFehler, OSError, ValueError) as exc:
            parser.exit(130 if cancel.is_set() else 1, str(exc) + "\n")
    elif len(sys.argv) > 1 and sys.argv[1] == "--ai-restore":
        import argparse
        import ai_restore
        from constants import ForgePixFehler
        parser = argparse.ArgumentParser(description="Eigene lokale Astro-KI auf einem linearen FITS-/TIFF-Bild")
        parser.add_argument("--input", required=True)
        parser.add_argument("--model", required=True)
        parser.add_argument("--output-root")
        parser.add_argument("--strength", type=float, default=.5)
        parser.add_argument("--device", choices=("auto", "cpu", "gpu", "cuda", "directml", "coreml"),
                            default="auto", help="Rechenbackend: automatisch bevorzugt Grafikkarte; cpu erzwingt Prozessor")
        parser.add_argument("--experimental", action="store_true",
                            help="Experimentelle Modelle ausdrücklich für diesen Lauf zulassen")
        options = parser.parse_args(sys.argv[2:])
        try:
            result = ai_restore.run_file(options.input, options.model,
                output_root=options.output_root, strength=options.strength,
                allow_experimental=options.experimental, device=options.device)
            print(result)
        except (ForgePixFehler, OSError, ValueError) as exc:
            parser.exit(1, str(exc) + "\n")
    elif len(sys.argv) > 1 and sys.argv[1] == "--cli":
        import focus_cull_stack
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        focus_cull_stack.main()
    else:
        main()
