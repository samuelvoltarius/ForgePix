#!/usr/bin/env python3
"""ui/result_view.py — Ergebnis-/Vorschau-Anzeige, Ansicht-Umschalter und Entscheidungs-Panel
(Stack-Konfidenz, Befunde, „Warum?") als Mixin für MainWindow."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from i18n import tr
from ui.appinfo import _cache_path, IMG_EXTS

try:
    import cv2
    import numpy as np
except Exception:
    cv2 = None
    np = None


class ResultMixin:
    """Ergebnis finden/anzeigen, Vorschau-Cache, Ansicht-Umschalter, Fokus-Map, Qualitäts-Panel."""

    def _find_result(self):
        """Neuestes Stack-Bild finden — auch im Batch (<work>/<sub>/stack)."""
        wd = self._work_dir()
        cands = []
        for d in [os.path.join(wd, "stack")] + \
                 [os.path.join(wd, s, "stack") for s in (os.listdir(wd) if os.path.isdir(wd) else [])
                  if os.path.isdir(os.path.join(wd, s, "stack"))]:
            if os.path.isdir(d):
                cands += [os.path.join(d, f) for f in os.listdir(d)
                          if os.path.splitext(f)[1].lower() in IMG_EXTS]
        return max(cands, key=os.path.getmtime) if cands else None

    def _preview_png(self, src):
        """Beliebiges Bild (auch 16-bit TIFF) zu 8-bit-PNG für die Anzeige."""
        if not src or not os.path.isfile(src):
            return None
        if cv2 is None:
            return src  # Fallback: direkt versuchen
        img = cv2.imread(src, cv2.IMREAD_UNCHANGED)
        if img is None:
            return src if QPixmap(src).isNull() is False else None
        if img.dtype != "uint8":
            img = (img / 256).astype("uint8") if img.max() > 255 else img.astype("uint8")
        h, w = img.shape[:2]
        if max(h, w) > 1400:
            f = 1400 / max(h, w)
            img = cv2.resize(img, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
        out = _cache_path("sf_prev_", src)
        cv2.imwrite(out, img)
        return out

    def _set_preview(self, src):
        png = self._preview_png(src)
        self._preview_src = png
        if png:
            pix = QPixmap(png)
            if not pix.isNull():
                self.preview.setPixmap(pix.scaled(self.preview.size(), Qt.KeepAspectRatio,
                                                  Qt.SmoothTransformation))
                self.preview.setToolTip(src)
                return
        self.preview.setText("(Vorschau nicht darstellbar)")

    def _sharpest_kept(self, result_path):
        """Schärfsten behaltenen Quell-Frame aus dem cull_report ziehen."""
        report = os.path.join(os.path.dirname(os.path.dirname(result_path)), "cull_report.json")
        if not os.path.isfile(report):
            return None
        try:
            import json as _json
            data = _json.load(open(report))
            kept = [f for f in data["frames"] if f.get("keep")]
            if kept:
                return max(kept, key=lambda f: f.get("peak_sharp", 0)).get("path")
        except Exception:
            pass
        return None

    def _representative_input(self):
        """Ein Original-Frame (mittlerer) als „Vorher“ für den Vergleich — modulübergreifend."""
        folder = self.in_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            return None
        try:
            import focus_cull_stack as F
            paths = F.list_images(folder)
            if not paths:  # Hybrid Fokus+Astro: Bilder liegen in Unterordnern
                for s in sorted(os.listdir(folder)):
                    sub = os.path.join(folder, s)
                    if os.path.isdir(sub):
                        paths = F.list_images(sub)
                        if paths:
                            break
            return paths[len(paths) // 2] if paths else None
        except Exception:
            return None

    def _show_result(self):
        res = self._find_result()
        if not res:
            self.preview.setText("(kein Stack-Output — Selektionslauf?)")
            return
        self.result_path = res
        self._focusmap_cache = None   # neue Reihe -> Fokus-Map neu berechnen
        # „Vorher“: schärfster behaltener Frame (Makro) — sonst ein repräsentatives Original
        self.before_path = self._sharpest_kept(res) or self._representative_input()
        self.view_result.setChecked(True)
        self._set_preview(res)
        self.open_btn.setEnabled(True)
        self.openfolder_btn.setEnabled(True); self.adjust_btn.setEnabled(True)
        self.cmp_btn.setEnabled(bool(self.before_path))
        self.ghost_btn.setEnabled(bool(self._ghostmap_path()))
        # Ansicht-Umschalter: Ergebnis immer, Geister-Karte wenn da, Fokus-Map nur Makro
        makro = not (getattr(self, "is_astro", False) or getattr(self, "is_hybrid", False)
                     or getattr(self, "is_longexp", False))
        self.view_result.setEnabled(True)
        self.view_ghost.setEnabled(bool(self._ghostmap_path()))
        self.view_focusmap.setEnabled(makro)
        self.send_btn.setEnabled(True); self.reimport_btn.setEnabled(True)
        self.export_btn.setEnabled(True); self.tools_btn.setEnabled(True)
        for b in getattr(self, "export_chips", []):
            b.setEnabled(True)
        # GraXpert/StarNet nur bei Himmels-Modulen sinnvoll (Astro/Langzeit/Hybrid), nicht Makro
        sky = (getattr(self, "is_astro", False) or getattr(self, "is_longexp", False)
               or getattr(self, "is_hybrid", False))
        for b in (self.graxpert_btn, self.starnet_btn):
            b.setVisible(sky); b.setEnabled(sky)
        # Retusche nur wo es Sinn macht (Fokus-Stacking): Makro + Hybrid Fokus+Astro
        fa = getattr(self, "is_hybrid", False) and self.hybrid_kind.currentData() == "fa"
        retouch_ok = (not getattr(self, "is_astro", False)
                      and not getattr(self, "is_longexp", False)
                      and (not getattr(self, "is_hybrid", False) or fa))
        self.retouch_btn.setVisible(retouch_ok)
        self.retouch_btn.setEnabled(retouch_ok)
        self._build_filmstrip(res)
        self._show_quality()

    def _set_view(self, mode):
        """Mittleres Bild umschalten: Ergebnis · Fokus-Map · Geister-Karte."""
        for b, m in ((self.view_result, "result"), (self.view_focusmap, "focusmap"),
                     (self.view_ghost, "ghost")):
            b.setChecked(m == mode)
        if mode == "result" and self.result_path:
            self._set_preview(self.result_path)
        elif mode == "focusmap":
            p = self._focusmap_png()
            if p:
                self._set_preview(p)
            else:
                self._append("\n(Fokus-Map: zu wenige Bilder oder nicht berechenbar.)\n")
        elif mode == "ghost":
            g = self._ghostmap_path()
            if g:
                self._set_preview(g)

    def _focusmap_png(self):
        """Fokus-Herkunfts-Karte als PNG (berechnet bei Bedarf, gecacht)."""
        if getattr(self, "_focusmap_cache", None):
            return self._focusmap_cache
        try:
            import focus_analysis as fa
            import focus_cull_stack as F
            paths = getattr(self, "_analyze_paths", None) or F.list_images(self.in_edit.text().strip())
            if not paths or len(paths) < 3:
                return None
            fm = fa.focus_map(paths)
            p = os.path.join("/tmp", "fp_focusmap_view.png")
            cv2.imwrite(p, fm)
            self._focusmap_cache = p
            return p
        except Exception:
            return None

    def _finding_action(self, text):
        """Passenden Klick-Link zu einem Befund liefern (springt zur richtigen Ansicht/Werkzeug)."""
        low = (text or "").lower()
        link = '  <a href="{href}" style="color:#7bd36a;text-decoration:none">→ {lbl}</a>'
        if ("geist" in low or "ghost" in low) and self._ghostmap_path():
            return link.format(href="view:ghost", lbl=tr("Geister-Karte"))
        if "halo" in low and self.retouch_btn.isEnabled():
            return link.format(href="tool:retouch", lbl=tr("Retusche"))
        if ("fokus" in low or "schärf" in low or "unscharf" in low or "abdeckung" in low
                or "lücke" in low) and self.view_focusmap.isEnabled():
            return link.format(href="view:focusmap", lbl=tr("Fokus-Map"))
        return ""

    def _panel_link(self, href):
        """Klick auf einen Link im Entscheidungs-Panel: zur passenden Ansicht/Werkzeug springen."""
        if href == "view:ghost":
            self._set_view("ghost")
        elif href == "view:focusmap":
            self._set_view("focusmap")
        elif href == "view:result":
            self._set_view("result")
        elif href == "tool:retouch":
            self.open_retouch()

    def _show_quality(self):
        """Stack-Qualität (aus quality.json) ins Log + ins rechte Entscheidungs-Panel schreiben."""
        qf = os.path.join(self._work_dir(), "quality.json")
        q = None
        if os.path.isfile(qf):
            try:
                import json as _json
                q = _json.load(open(qf))
            except Exception:
                q = None
        # Cull-Report für „X von Y verwendet"
        kept = total = None
        try:
            import json as _json
            rep = os.path.join(os.path.dirname(os.path.dirname(self.result_path)), "cull_report.json")
            if os.path.isfile(rep):
                d = _json.load(open(rep)); kept = d.get("kept"); total = d.get("total")
        except Exception:
            pass
        if q:
            findings = " · ".join(q.get("findings", []))
            self._append(f"\n🏅 Stack-Qualität: {q.get('score')}/100 — {findings}\n")
        # Entscheidungs-Panel (rechts) aufbauen
        score = q.get("score") if q else None
        col = "#4caf50" if (score or 0) >= 85 else "#d4a72c" if (score or 0) >= 70 else "#e5534b"
        html = []
        if score is not None:
            html.append(f"<div style='font-size:30px;font-weight:800;color:{col}'>{score}<span "
                        f"style='font-size:14px;color:#9aa09a'>/100</span></div>"
                        f"<div style='color:#9aa09a;font-size:11px;margin-bottom:8px'>"
                        + tr("Stack-Konfidenz") + "</div>")
        if kept is not None and total:
            html.append(f"<b>{kept}</b> " + tr("von") + f" <b>{total}</b> " + tr("Fotos verwendet")
                        + f" <span style='color:#9aa09a'>({total - kept} " + tr("aussortiert") + ")</span><br><br>")
        if q and q.get("findings"):
            html.append("<b>" + tr("Befunde") + ":</b><ul style='margin:4px 0 0 -18px'>")
            for f in q["findings"]:
                html.append(f"<li>{f}{self._finding_action(f)}</li>")
            html.append("</ul>")
        # „Warum diese Einstellungen?" — Begründung der Automatik/KI (aus dem Log)
        rationale = getattr(self, "_last_rationale", "")
        if rationale:
            html.append("<br><b style='color:#7bd36a'>" + tr("Warum diese Einstellungen?") + "</b>"
                        f"<div style='color:#b9bdb6;font-size:12px;margin-top:3px'>{rationale}</div>")
        html.append("<br><span style='color:#7bd36a'>→ </span>" + tr("Bearbeiten (E) · Export (⌘E) · "
                    "Werkzeuge für Geister-Karte/Retusche."))
        self.decision.setText("".join(html) if html else tr("Ergebnis fertig."))
