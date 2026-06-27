#!/usr/bin/env python3
"""
ui_components.py — wiederverwendbare GUI-Bausteine von ForgePix.
Hilfsfunktionen (Vorschau, Plattform-Öffnen, ?-Hilfe) + Bild-Anpassung (Camera-Raw)
+ Dialoge (Vergleich, Retusche, Bearbeiten) + Kurven-/Canvas-Widgets.
Bewusst aus dem GUI-Monolithen ausgelagert.
"""
import os
import sys
import subprocess

import cv2
import numpy as np

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPixmap, QImage, QPainter, QColor, QPen, QCursor
from PySide6.QtWidgets import (
    QWidget, QLabel, QDialog, QPushButton, QSlider, QComboBox, QSpinBox,
    QCheckBox, QScrollArea, QFrame, QHBoxLayout, QVBoxLayout,
    QGridLayout, QMessageBox, QToolButton, QToolTip,
)

from i18n import tr

class CompareSlider(QWidget):
    """Vorher/Nachher mit ziehbarem Trennstrich."""
    def __init__(self, before_png, after_png, parent=None):
        super().__init__(parent)
        self.before = QPixmap(before_png)
        self.after = QPixmap(after_png)
        self.pos = 0.5
        self.setMinimumSize(640, 460)
        self.setMouseTracking(True)

    def _img_rect(self):
        if self.after.isNull():
            return None
        s = self.after.size().scaled(self.size(), Qt.KeepAspectRatio)
        x = (self.width() - s.width()) // 2
        y = (self.height() - s.height()) // 2
        return QRect(x, y, s.width(), s.height())

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#101113"))
        r = self._img_rect()
        if r is None:
            return
        p.drawPixmap(r, self.after)
        divx = r.x() + int(r.width() * self.pos)
        p.save()
        p.setClipRect(QRect(r.x(), r.y(), divx - r.x(), r.height()))
        p.drawPixmap(r, self.before)
        p.restore()
        p.setPen(QPen(QColor("#5cc85c"), 3))
        p.drawLine(divx, r.y(), divx, r.bottom())
        p.setPen(QColor("white"))
        p.drawText(r.x() + 10, r.y() + 22, "VORHER (schärfster Einzel-Frame)")
        t = "NACHHER (Stack)"
        p.drawText(r.right() - p.fontMetrics().horizontalAdvance(t) - 10, r.y() + 22, t)

    def _set_from_x(self, x):
        r = self._img_rect()
        if r and r.width() > 0:
            self.pos = min(1.0, max(0.0, (x - r.x()) / r.width()))
            self.update()

    def mouseMoveEvent(self, e):
        self._set_from_x(e.position().x())

    def mousePressEvent(self, e):
        self._set_from_x(e.position().x())


def _bgr_to_pixmap(bgr, max_w=900):
    """BGR-Array (8/16-bit) -> skaliertes QPixmap. Gibt (pixmap, scale) zurück."""
    scale = min(1.0, max_w / bgr.shape[1])
    small = cv2.resize(bgr, (int(bgr.shape[1] * scale), int(bgr.shape[0] * scale)),
                       interpolation=cv2.INTER_AREA) if scale < 1.0 else bgr
    if small.dtype != np.uint8:
        small = (small / 256).astype(np.uint8) if small.max() > 255 else small.astype(np.uint8)
    rgb = np.ascontiguousarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
    qimg = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy()), scale


HSL_BANDS = {"Rot": 0, "Orange": 30, "Gelb": 60, "Grün": 120,
             "Türkis": 180, "Blau": 240, "Violett": 270, "Magenta": 300}


def adjust_image(img, p):
    """Treue Camera-Raw-Anpassungen (kein Erfinden von Inhalten). Werte -100..100.
    Reihenfolge: Belichtung -> Weißabgleich -> Kontrast -> Tonwerte -> Klarheit -> Farbe."""
    maxv = 65535.0 if img.dtype == np.uint16 else 255.0
    f = img.astype(np.float32) / maxv
    if p.get("exposure"):
        f *= 2.0 ** (p["exposure"] / 100.0)
    if p.get("temp"):  # Temperatur: + wärmer (R hoch, B runter)
        t = p["temp"] / 100.0 * 0.12
        f[..., 2] += t; f[..., 0] -= t
    if p.get("tint"):  # Tönung: + magenta, - grün
        t = p["tint"] / 100.0 * 0.10
        f[..., 2] += t * 0.5; f[..., 0] += t * 0.5; f[..., 1] -= t
    if p.get("contrast"):
        f = (f - 0.5) * (1.0 + p["contrast"] / 100.0) + 0.5
    keys = ("highlights", "shadows", "whites", "blacks")
    if any(p.get(k) for k in keys):
        L = np.clip(0.114 * f[..., 0] + 0.587 * f[..., 1] + 0.299 * f[..., 2], 0, 1)
        if p.get("shadows"):
            f = f + (p["shadows"] / 100.0) * ((1 - L) ** 2)[..., None]
        if p.get("highlights"):
            f = f + (p["highlights"] / 100.0) * (L ** 2)[..., None]
        if p.get("blacks"):
            f = f + (p["blacks"] / 100.0) * 0.5 * (np.clip(0.5 - L, 0, 0.5) * 2)[..., None]
        if p.get("whites"):
            f = f + (p["whites"] / 100.0) * 0.5 * (np.clip(L - 0.5, 0, 0.5) * 2)[..., None]
    f = np.clip(f, 0, 1)
    if p.get("curve") and len(p["curve"]) >= 2:  # Tonwertkurve (RGB-Komposit) via LUT
        pts = sorted(p["curve"])
        xs = np.array([q[0] for q in pts], np.float32)
        ys = np.clip([q[1] for q in pts], 0, 1)
        f = np.interp(f, xs, ys).astype(np.float32)
    if p.get("hsl"):  # HSL pro Farbband
        hsv = cv2.cvtColor(np.clip(f, 0, 1), cv2.COLOR_BGR2HSV)
        H = hsv[..., 0]
        for band, (dh, ds, dl) in p["hsl"].items():
            if not (dh or ds or dl):
                continue
            center = HSL_BANDS.get(band, 0)
            dist = np.abs(((H - center + 180) % 360) - 180)
            mask = np.clip(1 - dist / 35.0, 0, 1)
            if dh:
                hsv[..., 0] = (hsv[..., 0] + dh * 0.6 * mask) % 360
            if ds:
                hsv[..., 1] = np.clip(hsv[..., 1] * (1 + (ds / 100.0) * mask), 0, 1)
            if dl:
                hsv[..., 2] = np.clip(hsv[..., 2] * (1 + (dl / 100.0) * mask), 0, 1)
        f = np.clip(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR), 0, 1)
    if p.get("clarity"):  # lokaler Kontrast-Equalizer (multiskalig, halo-arm) — darktable/RT-Stil
        try:
            import sys as _sys, os as _os
            _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "core"))
            import develop as _dev
            f = np.clip(_dev.local_contrast(f.astype(np.float32), amount=p["clarity"] / 100.0), 0, 1)
        except Exception:                                # Fallback: einfaches Großradius-Unsharp
            r = max(3.0, min(f.shape[0], f.shape[1]) / 90.0)
            blur = cv2.GaussianBlur(f, (0, 0), r)
            f = np.clip(f + (p["clarity"] / 100.0) * (f - blur), 0, 1)
    if p.get("vibrance") or p.get("saturation"):
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
        s = hsv[..., 1]
        if p.get("vibrance"):  # Dynamik: hebt blasse Farben stärker an
            s = s * (1.0 + (p["vibrance"] / 100.0) * (1.0 - s))
        if p.get("saturation"):
            s = s * (1.0 + p["saturation"] / 100.0)
        hsv[..., 1] = np.clip(s, 0, 1)
        f = np.clip(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR), 0, 1)
    return (f * maxv).astype(img.dtype)


def histogram_pixmap(img, w=256, h=90):
    """Kleines RGB-Histogramm als QPixmap."""
    im = (img / 256).astype(np.uint8) if img.dtype != np.uint8 else img
    canvas = np.full((h, w, 3), 22, np.uint8)
    for ch, col in [(0, (255, 90, 90)), (1, (90, 255, 90)), (2, (90, 90, 255))]:
        hist = cv2.calcHist([im], [ch], None, [w], [0, 256]).flatten()
        hist = hist / (hist.max() + 1) * (h - 3)
        for x in range(w):
            cv2.line(canvas, (x, h - 1), (x, h - 1 - int(hist[x])), col, 1)
    rgb = np.ascontiguousarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    return QPixmap.fromImage(QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888).copy())


class CurveWidget(QWidget):
    """Ziehbare Tonwertkurve. Punkte hinzufügen (Klick), ziehen, Doppelklick entfernt."""
    def __init__(self, on_change):
        super().__init__()
        self.setFixedHeight(190); self.setMinimumWidth(200)
        self.points = [[0.0, 0.0], [1.0, 1.0]]
        self._on_change = on_change
        self._drag = None

    def _px(self, x, y):
        w, h = self.width() - 2, self.height() - 2
        return 1 + x * w, 1 + (1 - y) * h

    def _norm(self, px, py):
        w, h = self.width() - 2, self.height() - 2
        return min(1, max(0, (px - 1) / w)), min(1, max(0, 1 - (py - 1) / h))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1c1b22"))
        p.setPen(QPen(QColor("#34383f"), 1))
        for i in range(1, 4):
            x = self.width() * i / 4; y = self.height() * i / 4
            p.drawLine(int(x), 0, int(x), self.height()); p.drawLine(0, int(y), self.width(), int(y))
        pts = sorted(self.points)
        xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
        p.setPen(QPen(QColor("#5cc85c"), 2))
        prev = None
        for i in range(101):
            xx = i / 100.0
            yy = float(np.interp(xx, xs, ys))
            cx, cy = self._px(xx, yy)
            if prev:
                p.drawLine(int(prev[0]), int(prev[1]), int(cx), int(cy))
            prev = (cx, cy)
        p.setBrush(QColor("#e8eae6"))
        for x, y in pts:
            cx, cy = self._px(x, y)
            p.drawEllipse(int(cx) - 4, int(cy) - 4, 8, 8)

    def _nearest(self, px, py):
        for i, (x, y) in enumerate(self.points):
            cx, cy = self._px(x, y)
            if abs(cx - px) < 10 and abs(cy - py) < 10:
                return i
        return None

    def mousePressEvent(self, e):
        i = self._nearest(e.position().x(), e.position().y())
        if i is None:
            nx, ny = self._norm(e.position().x(), e.position().y())
            self.points.append([nx, ny]); self.points.sort(); i = self.points.index([nx, ny])
        self._drag = i; self.update()

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return
        nx, ny = self._norm(e.position().x(), e.position().y())
        i = self._drag
        if i == 0:
            nx = 0.0
        elif i == len(self.points) - 1:
            nx = 1.0
        self.points[i] = [nx, ny]
        self.update(); self._on_change(self.points)

    def mouseReleaseEvent(self, e):
        self.points.sort(); self._drag = None; self._on_change(self.points)

    def mouseDoubleClickEvent(self, e):
        i = self._nearest(e.position().x(), e.position().y())
        if i is not None and 0 < i < len(self.points) - 1:
            del self.points[i]; self.update(); self._on_change(self.points)

    def reset(self):
        self.points = [[0.0, 0.0], [1.0, 1.0]]; self.update(); self._on_change(self.points)


class AdjustDialog(QDialog):
    """Camera-Raw-Entwickler: Tonwerte, Weißabgleich, Präsenz, Farbe, Kurve, HSL, Geometrie."""
    # (Schlüssel, Anzeige, Gruppe)
    SLIDERS = [
        ("exposure", "Belichtung", "Tonwerte"), ("contrast", "Kontrast", "Tonwerte"),
        ("highlights", "Lichter", "Tonwerte"), ("shadows", "Schatten", "Tonwerte"),
        ("whites", "Weiß", "Tonwerte"), ("blacks", "Schwarz", "Tonwerte"),
        ("temp", "Temperatur", "Weißabgleich"), ("tint", "Tönung", "Weißabgleich"),
        ("clarity", "Klarheit", "Präsenz"),
        ("vibrance", "Dynamik", "Farbe"), ("saturation", "Sättigung", "Farbe"),
    ]

    def __init__(self, img_bgr, save_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Bearbeiten — Camera-Raw"))
        self.full = img_bgr
        self.save_path = save_path
        s = min(1.0, 900 / img_bgr.shape[1])
        self.base = cv2.resize(img_bgr, (int(img_bgr.shape[1] * s), int(img_bgr.shape[0] * s)),
                               interpolation=cv2.INTER_AREA) if s < 1.0 else img_bgr.copy()
        self.vals = {k: 0 for k, _, _ in self.SLIDERS}
        self.curve = None                 # Tonwertkurve-Punkte oder None
        self.hsl = {}                     # Farbband -> [Farbton, Sättigung, Luminanz]
        self.angle = 0                    # Drehen (Grad)
        self.crop = {"top": 0, "bottom": 0, "left": 0, "right": 0}  # Beschnitt in %
        # Masken-Pinsel: self.mask (HxW, [0..1]) wird lazy aus der Auto-Maske/Voll erzeugt, sobald
        # man malt. brush_add=True -> Bereich AUFNEHMEN (Anpassung wirkt), False -> ENTFERNEN (schützen).
        self.mask = None
        self.brush_add = True
        self.brush_r = 40
        self._disp = None                 # (off_x, off_y, disp_w, disp_h, img_w, img_h) fürs Maus-Mapping
        self._painting = False

        lay = QHBoxLayout(self)
        self.preview = QLabel(); self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(760, 540)          # mehr Bildfläche (~¾)
        self.preview.setMouseTracking(True)
        self.preview.mousePressEvent = self._mouse_paint
        self.preview.mouseMoveEvent = self._mouse_paint
        lay.addWidget(self.preview, 1)

        # rechtes Panel mit (größerem) Histogramm + scrollbaren Reglern
        panel = QWidget(); panel.setMaximumWidth(310); panel.setMinimumWidth(290)
        pv = QVBoxLayout(panel)
        self.hist = QLabel(); self.hist.setFixedHeight(132); self.hist.setAlignment(Qt.AlignCenter)
        pv.addWidget(self.hist)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget(); side = QVBoxLayout(inner)
        self.value_labels = {}
        last_group = None
        for key, lbl, group in self.SLIDERS:
            if group != last_group:
                gl = QLabel(tr(group)); gl.setObjectName("sectionHeader")
                side.addWidget(gl); last_group = group
            row = QHBoxLayout()
            name = QLabel(tr(lbl)); name.setMinimumWidth(86)
            val = QLabel("0"); val.setMinimumWidth(32); val.setAlignment(Qt.AlignRight)
            self.value_labels[key] = val
            sld = QSlider(Qt.Horizontal); sld.setRange(-100, 100); sld.setValue(0)
            sld.valueChanged.connect(lambda v, k=key: self._on_slider(k, v))
            row.addWidget(name); row.addWidget(sld, 1); row.addWidget(val)
            side.addLayout(row)

        # --- Tonwertkurve ---
        cl = QLabel(tr("Tonwertkurve")); cl.setObjectName("sectionHeader")
        side.addWidget(cl)
        self.curve_widget = CurveWidget(self._on_curve)
        side.addWidget(self.curve_widget)
        side.addWidget(QLabel(tr("Klick = Punkt, ziehen, Doppelklick entfernt.")))

        # --- HSL pro Farbe ---
        hl = QLabel(tr("Farben (HSL)")); hl.setObjectName("sectionHeader")
        side.addWidget(hl)
        self.hsl_band = QComboBox(); self.hsl_band.addItems(list(HSL_BANDS.keys()))
        self.hsl_band.currentTextChanged.connect(self._load_hsl_band)
        side.addWidget(self.hsl_band)
        self.hsl_sliders = {}
        for sub in ("Farbton", "Sättigung", "Luminanz"):
            r = QHBoxLayout(); n = QLabel(tr(sub)); n.setMinimumWidth(86)
            sld = QSlider(Qt.Horizontal); sld.setRange(-100, 100); sld.setValue(0)
            sld.valueChanged.connect(lambda v, s=sub: self._on_hsl(s, v))
            self.hsl_sliders[sub] = sld
            r.addWidget(n); r.addWidget(sld, 1); side.addLayout(r)

        # --- Geometrie ---
        gl = QLabel(tr("Geometrie")); gl.setObjectName("sectionHeader")
        side.addWidget(gl)
        self.geo_sliders = {}
        for key, lbl, lo, hi in [("angle", "Drehen", -45, 45), ("top", "Beschnitt oben", 0, 45),
                                 ("bottom", "Beschnitt unten", 0, 45), ("left", "Beschnitt links", 0, 45),
                                 ("right", "Beschnitt rechts", 0, 45)]:
            r = QHBoxLayout(); n = QLabel(tr(lbl)); n.setMinimumWidth(110)
            sld = QSlider(Qt.Horizontal); sld.setRange(lo, hi); sld.setValue(0)
            sld.valueChanged.connect(lambda v, k=key: self._on_geo(k, v))
            self.geo_sliders[key] = sld
            r.addWidget(n); r.addWidget(sld, 1); side.addLayout(r)

        side.addStretch(1)
        scroll.setWidget(inner)
        pv.addWidget(scroll, 1)

        # Auto-Maske: Anpassungen nur aufs Motiv (mittlere Helligkeiten), schützt Sterne+Hintergrund
        self.auto_mask = QCheckBox(tr("🎯 Auto-Maske: nur Motiv aufhellen (Sterne/Hintergrund schützen)"))
        self.auto_mask.setToolTip(tr("Legt Helligkeit/Klarheit nur auf die mittleren Helligkeiten "
                                     "(Nebel/Motiv) — heller Kern/Sterne und dunkler Hintergrund "
                                     "bleiben geschützt. Ideal für Astro & Makro, ganz ohne Malen."))
        self.auto_mask.toggled.connect(self._update)
        pv.addWidget(self.auto_mask)

        # Masken-Pinsel: Auto-Maske als Start, dann von Hand aufnehmen/schützen
        self.brush_on = QCheckBox(tr("🖌 Maske von Hand malen (B)"))
        self.brush_on.setToolTip(tr("An: auf dem Bild malen. Plus/Aufnehmen lässt die Anpassung dort "
                                    "wirken, Minus/Schützen nimmt sie dort weg. Start ist die Auto-Maske "
                                    "(falls aktiv), sonst leer. Tasten: B Pinsel, A/S +/-, [ ] Größe, "
                                    "Backspace Maske löschen."))
        self.brush_on.toggled.connect(self._update)
        pv.addWidget(self.brush_on)
        brow = QHBoxLayout()
        self.btn_add = QPushButton(tr("+ Aufnehmen")); self.btn_add.setCheckable(True); self.btn_add.setChecked(True)
        self.btn_erase = QPushButton(tr("− Schützen")); self.btn_erase.setCheckable(True)
        self.btn_add.clicked.connect(lambda: self._set_brush(True))
        self.btn_erase.clicked.connect(lambda: self._set_brush(False))
        self.brush_size = QSlider(Qt.Horizontal); self.brush_size.setRange(8, 200); self.brush_size.setValue(40)
        self.brush_size.valueChanged.connect(lambda v: setattr(self, "brush_r", v))
        clr = QPushButton(tr("Maske löschen")); clr.clicked.connect(self._clear_mask)
        brow.addWidget(self.btn_add); brow.addWidget(self.btn_erase)
        brow.addWidget(QLabel(tr("Größe"))); brow.addWidget(self.brush_size, 1); brow.addWidget(clr)
        pv.addLayout(brow)

        btns = QHBoxLayout()
        auto = QPushButton(tr("Auto")); auto.clicked.connect(self._auto)
        reset = QPushButton(tr("Zurücksetzen")); reset.clicked.connect(self._reset)
        save = QPushButton(tr("💾 Speichern")); save.clicked.connect(self._save)
        btns.addWidget(auto); btns.addWidget(reset); btns.addWidget(save)
        pv.addLayout(btns)
        note = QLabel(tr("Treue Anpassung — keine Inhalte erfunden."))
        note.setStyleSheet("color:#9aa09a;"); pv.addWidget(note)
        lay.addWidget(panel)
        self.resize(1200, 800)
        self._sliders = inner.findChildren(QSlider)
        self._update()

    def _on_slider(self, key, v):
        self.vals[key] = v
        self.value_labels[key].setText(str(v))
        self._update()

    def _on_curve(self, points):
        self.curve = [list(p) for p in points] if points else None
        self._update()

    def _load_hsl_band(self, band):
        vals = self.hsl.get(band, [0, 0, 0])
        for sub, v in zip(("Farbton", "Sättigung", "Luminanz"), vals):
            sld = self.hsl_sliders[sub]
            sld.blockSignals(True); sld.setValue(int(v)); sld.blockSignals(False)

    def _on_hsl(self, sub, v):
        band = self.hsl_band.currentText()
        cur = self.hsl.setdefault(band, [0, 0, 0])
        cur[("Farbton", "Sättigung", "Luminanz").index(sub)] = v
        self.hsl[band] = cur
        self._update()

    def _on_geo(self, key, v):
        if key == "angle":
            self.angle = v
        else:
            self.crop[key] = v
        self._update()

    def _geometry(self, img):
        out = img
        if self.angle:
            h, w = out.shape[:2]
            M = cv2.getRotationMatrix2D((w / 2, h / 2), self.angle, 1.0)
            out = cv2.warpAffine(out, M, (w, h), flags=cv2.INTER_LANCZOS4,
                                 borderMode=cv2.BORDER_REPLICATE)
        h, w = out.shape[:2]
        t = int(h * self.crop["top"] / 100); b = int(h * (1 - self.crop["bottom"] / 100))
        l = int(w * self.crop["left"] / 100); r = int(w * (1 - self.crop["right"] / 100))
        if b - t > 8 and r - l > 8:
            out = out[t:b, l:r]
        return out

    def _params(self):
        return {**self.vals, "curve": self.curve, "hsl": self.hsl}

    def _lum_mask(self, base):
        """Auto-Maske: betont die mittleren Helligkeiten (das Motiv/der Nebel) und schützt
        dunklen Hintergrund (Rauschen) sowie helle Sterne/Kern (Ausbleichen). Weicher Rand."""
        g = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY).astype(np.float32)
        mx = 65535.0 if base.dtype == np.uint16 else 255.0
        L = g / mx
        lo = np.clip((L - 0.04) / 0.12, 0, 1)        # Hintergrund unten ausblenden
        hi = 1.0 - np.clip((L - 0.78) / 0.18, 0, 1)  # helle Sterne/Kern oben schützen
        m = cv2.GaussianBlur(lo * hi, (0, 0), 4)
        return m[..., None]

    def _current_mask(self, shape_hw):
        """Effektive Maske (HxW in [0..1], auf shape_hw skaliert) oder None (= global, keine Maske).
        Vorrang: handgemalte Maske > Auto-Maske > keine."""
        m = None
        if self.mask is not None:
            m = self.mask
        elif getattr(self, "auto_mask", None) and self.auto_mask.isChecked():
            return None  # Auto-Maske wird in _masked direkt aus dem Bild berechnet
        if m is None:
            return None
        if m.shape != shape_hw:
            m = cv2.resize(m, (shape_hw[1], shape_hw[0]))
        return m

    def _masked(self, base, out):
        """Anpassung über eine Maske blenden: handgemalt (Vorrang) oder Auto-Maske; sonst global."""
        m = self._current_mask(out.shape[:2])
        if m is None and getattr(self, "auto_mask", None) and self.auto_mask.isChecked() \
                and self.mask is None:
            m = self._lum_mask(out)[..., 0]
        if m is None:
            return out
        m3 = m[..., None]
        return np.clip(base.astype(np.float32) * (1 - m3) + out.astype(np.float32) * m3, 0,
                       65535 if base.dtype == np.uint16 else 255).astype(base.dtype)

    # ---------- Masken-Pinsel ----------
    def _set_brush(self, add):
        self.brush_add = add
        self.btn_add.setChecked(add); self.btn_erase.setChecked(not add)

    def _clear_mask(self):
        self.mask = None; self._update()

    def _ensure_mask(self):
        """Maske lazy anlegen: aus der Auto-Maske (falls aktiv), sonst leer (alles geschützt)."""
        if self.mask is None:
            base = self._geometry(self.base)
            if getattr(self, "auto_mask", None) and self.auto_mask.isChecked():
                self.mask = self._lum_mask(base)[..., 0].copy()
            else:
                self.mask = np.zeros(base.shape[:2], np.float32)

    def _mouse_paint(self, e):
        if not getattr(self, "brush_on", None) or not self.brush_on.isChecked() or not self._disp:
            return
        ox, oy, dw, dh, iw, ih = self._disp
        x = e.position().x() - ox; y = e.position().y() - oy
        if x < 0 or y < 0 or x > dw or y > dh:
            return
        ix = int(x / dw * iw); iy = int(y / dh * ih)
        self._ensure_mask()
        h, w = self.mask.shape
        if not (0 <= ix < w and 0 <= iy < h):
            return
        r = max(2, int(self.brush_r * iw / max(dw, 1)))   # Pinselradius in Bildpixeln
        disc = np.zeros((h, w), np.float32)
        cv2.circle(disc, (ix, iy), r, 1.0, -1)
        disc = cv2.GaussianBlur(disc, (0, 0), max(2, r / 2.5))  # weicher Rand
        if self.brush_add:
            self.mask = np.maximum(self.mask, disc)
        else:
            self.mask = np.clip(self.mask - disc, 0, 1)
        self._update()

    def _update(self):
        g = self._geometry(self.base)
        out = self._masked(g, adjust_image(g, self._params()))
        pix, _ = _bgr_to_pixmap(out, max_w=900)
        disp = pix.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        # Anzeige-Geometrie fürs Maus-Mapping merken (zentriert im Label)
        ox = (self.preview.width() - disp.width()) / 2
        oy = (self.preview.height() - disp.height()) / 2
        self._disp = (ox, oy, disp.width(), disp.height(), out.shape[1], out.shape[0])
        self.preview.setPixmap(disp)
        self.hist.setPixmap(histogram_pixmap(out, w=300, h=128))

    def keyPressEvent(self, e):
        from PySide6.QtCore import Qt as _Qt
        k = e.key()
        if k == _Qt.Key_B:
            self.brush_on.setChecked(not self.brush_on.isChecked())
        elif k == _Qt.Key_A:
            self._set_brush(True)
        elif k == _Qt.Key_S:
            self._set_brush(False)
        elif k == _Qt.Key_BracketRight:
            self.brush_size.setValue(min(200, self.brush_size.value() + 8))
        elif k == _Qt.Key_BracketLeft:
            self.brush_size.setValue(max(8, self.brush_size.value() - 8))
        elif k in (_Qt.Key_Backspace, _Qt.Key_Delete):
            self._clear_mask()
        else:
            super().keyPressEvent(e)

    def _auto(self):
        """Sanfter Auto-Tonwert: Belichtung Richtung Mittelhelligkeit + leichter Kontrast."""
        g = cv2.cvtColor(self.base, cv2.COLOR_BGR2GRAY).astype(np.float32)
        mx = 65535.0 if self.base.dtype == np.uint16 else 255.0
        mean = float(g.mean()) / mx
        exp = int(np.clip(np.log2(0.45 / max(mean, 0.02)) * 100, -60, 60))
        self._set("exposure", exp); self._set("contrast", 12)

    def _set(self, key, v):
        self.vals[key] = v
        self.value_labels[key].setText(str(v))
        self._sync_sliders()
        self._update()

    def _sync_sliders(self):
        # Slider-Positionen an self.vals angleichen (ohne erneutes _update je Slider)
        for idx, (key, _, _) in enumerate(self.SLIDERS):
            self._sliders[idx].blockSignals(True)
            self._sliders[idx].setValue(int(self.vals.get(key, 0)))
            self._sliders[idx].blockSignals(False)

    def _reset(self):
        for k in self.vals:
            self.vals[k] = 0
        for lbl in self.value_labels.values():
            lbl.setText("0")
        self._sync_sliders()
        self.curve = None; self.curve_widget.reset()
        self.hsl = {}
        for sld in self.hsl_sliders.values():
            sld.blockSignals(True); sld.setValue(0); sld.blockSignals(False)
        self.angle = 0; self.crop = {"top": 0, "bottom": 0, "left": 0, "right": 0}
        for sld in self.geo_sliders.values():
            sld.blockSignals(True); sld.setValue(0); sld.blockSignals(False)
        self._update()

    def _save(self):
        g = self._geometry(self.full)
        out = self._masked(g, adjust_image(g, self._params()))
        ext = os.path.splitext(self.save_path)[1].lower()
        if ext in (".jpg", ".jpeg"):
            cv2.imwrite(self.save_path, out, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        else:
            cv2.imwrite(self.save_path, out, [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
        QMessageBox.information(self, "Gespeichert", f"Gespeichert:\n{self.save_path}")


class _Canvas(QLabel):
    """Bild-Anzeige, die Maus-Mal-Ereignisse in Bildkoordinaten weitergibt."""
    def __init__(self, on_paint):
        super().__init__()
        self._on_paint = on_paint
        self._scale = 1.0
        self._drawing = False
        self.setCursor(Qt.CrossCursor)

    def set_image(self, bgr):
        pix, self._scale = _bgr_to_pixmap(bgr)
        self.setPixmap(pix)
        self.setFixedSize(pix.width(), pix.height())

    def _xy(self, e):
        return int(e.position().x() / self._scale), int(e.position().y() / self._scale)

    def mousePressEvent(self, e):
        self._drawing = True
        self._on_paint(*self._xy(e), True)

    def mouseMoveEvent(self, e):
        if self._drawing:
            self._on_paint(*self._xy(e), False)

    def mouseReleaseEvent(self, e):
        self._drawing = False


class RetouchDialog(QDialog):
    """Eigener Retusche-Editor: scharfe Stellen aus einem Quellfoto über das Ergebnis malen."""
    def __init__(self, result_bgr, sources, names, save_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Retusche — scharfe Stellen übermalen"))
        self.work = result_bgr.copy()
        self.original = result_bgr.copy()  # für den Radiergummi (zurück zum Stack)
        self.sources = sources
        self.cur = 0
        self.radius = 60
        self.eraser = False
        self._undo = []
        self.save_path = save_path

        lay = QHBoxLayout(self)
        self.canvas = _Canvas(self._paint)
        scroll = QScrollArea(); scroll.setWidget(self.canvas)
        scroll.setAlignment(Qt.AlignCenter)
        lay.addWidget(scroll, 1)

        side = QVBoxLayout()
        side.addWidget(QLabel(tr("Quelle (Foto, das du übermalst):")))
        self.src_box = QComboBox(); self.src_box.addItems(names)
        self.src_box.currentIndexChanged.connect(lambda i: setattr(self, "cur", i))
        side.addWidget(self.src_box)
        side.addWidget(help_btn("Wähle das Einzelfoto, dessen scharfe Stelle du an die "
                                "übermalte Position holen willst.") )
        side.addWidget(QLabel(tr("Pinselgröße")))
        bs = QSpinBox(); bs.setRange(5, 500); bs.setValue(60)
        bs.valueChanged.connect(lambda v: setattr(self, "radius", v))
        side.addWidget(bs)
        self.eraser_box = QCheckBox(tr("Radiergummi (zurück zum Stack)"))
        self.eraser_box.setToolTip(tr("An: übermalte Stellen wieder auf das ursprüngliche "
                                      "Stack-Ergebnis zurücksetzen."))
        self.eraser_box.toggled.connect(lambda v: setattr(self, "eraser", v))
        side.addWidget(self.eraser_box)
        undo = QPushButton(tr("↶ Rückgängig")); undo.clicked.connect(self._undo_last)
        save = QPushButton(tr("💾 Speichern")); save.clicked.connect(self._save)
        side.addWidget(undo); side.addWidget(save)
        side.addWidget(QLabel(tr("Tipp: an Halos/Doppelkonturen (Ghosting) malen,\num die scharfe "
                                 "Stelle aus einem Quellfoto zu holen.\nRadiergummi setzt zurück.")))
        side.addStretch(1)
        lay.addLayout(side)

        self.canvas.set_image(self.work)
        self.resize(1180, 820)

    def _paint(self, x, y, start):
        src = self.original if self.eraser else self.sources[self.cur]
        if src.shape != self.work.shape:
            return
        if start:
            self._undo.append(self.work.copy()); self._undo = self._undo[-12:]
        r = self.radius
        h, w = self.work.shape[:2]
        x0, x1 = max(0, x - r), min(w, x + r)
        y0, y1 = max(0, y - r), min(h, y + r)
        if x0 >= x1 or y0 >= y1:
            return
        yy, xx = np.ogrid[y0:y1, x0:x1]
        d = np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
        alpha = (np.clip(1 - d / r, 0, 1) ** 1.6)[..., None].astype(np.float32)
        roiw = self.work[y0:y1, x0:x1].astype(np.float32)
        rois = src[y0:y1, x0:x1].astype(np.float32)
        self.work[y0:y1, x0:x1] = (roiw * (1 - alpha) + rois * alpha).astype(self.work.dtype)
        self.canvas.set_image(self.work)

    def _undo_last(self):
        if self._undo:
            self.work = self._undo.pop()
            self.canvas.set_image(self.work)

    def _save(self):
        ext = os.path.splitext(self.save_path)[1].lower()
        if ext in (".jpg", ".jpeg"):
            cv2.imwrite(self.save_path, self.work, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        else:
            cv2.imwrite(self.save_path, self.work, [int(cv2.IMWRITE_TIFF_COMPRESSION), 1])
        QMessageBox.information(self, "Gespeichert", f"Gespeichert:\n{self.save_path}")


def reveal_in_files(path):
    """Datei im Dateimanager zeigen — macOS/Windows/Linux."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", path])
        elif sys.platform.startswith("win"):
            subprocess.run(["explorer", "/select,", os.path.normpath(path)])
        else:
            subprocess.run(["xdg-open", os.path.dirname(path)])
    except Exception:
        pass


def open_path(path):
    """Datei/Ordner mit dem Standardprogramm öffnen — plattformübergreifend."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", path])
        elif sys.platform.startswith("win"):
            os.startfile(path)  # noqa
        else:
            subprocess.run(["xdg-open", path])
    except Exception:
        pass


def notify(title, msg):
    """Desktop-Benachrichtigung (best effort, plattformübergreifend)."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["osascript", "-e",
                              f'display notification "{msg}" with title "{title}"'])
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["notify-send", title, msg])
        # Windows: still über das fertige Bild / Log; keine externe Abhängigkeit
    except Exception:
        pass


def help_btn(text):
    """Kleiner runder „?"-Button, der eine Klartext-Erklärung zeigt.
    Text läuft durch i18n.tr(), damit Hilfetexte übersetzbar sind (Fallback: deutsch)."""
    try:
        from i18n import tr as _tr
        text = _tr(text)
    except Exception:
        pass
    b = QToolButton()
    b.setText("?")
    b.setFixedSize(20, 20)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet("QToolButton{border:none;border-radius:10px;color:#7a7490;"
                    "background:#232231;font-weight:600;} "
                    "QToolButton:hover{background:#4caf50;color:#ffffff;}")
    rich = f"<div style='max-width:340px;white-space:normal'>{text}</div>"
    b.setToolTip(rich)
    b.clicked.connect(lambda: QToolTip.showText(QCursor.pos(), rich, b))
    return b


class CollapsibleSection(QWidget):
    """Ausklappbarer Abschnitt: ein Pfeil-Button schaltet einen Inhaltsbereich sichtbar/unsichtbar.
    Für selten gebrauchte „Erweitert"-Optionen, damit das Panel aufgeräumt bleibt. Der Inhalt
    kommt in `self.body` mit eigenem QGridLayout `self.grid`."""
    def __init__(self, title, parent=None, expanded=False):
        super().__init__(parent)
        self._title = title
        v = QVBoxLayout(self); v.setContentsMargins(0, 4, 0, 0); v.setSpacing(2)
        self.toggle = QToolButton()
        self.toggle.setCheckable(True); self.toggle.setChecked(expanded)
        self.toggle.setStyleSheet("QToolButton{border:none;color:#7bd36a;font-weight:bold;}")
        self.toggle.toggled.connect(self._on_toggle)
        self.body = QWidget()
        self.grid = QGridLayout(self.body); self.grid.setContentsMargins(8, 2, 0, 2)
        v.addWidget(self.toggle); v.addWidget(self.body)
        self.body.setVisible(expanded)
        self._on_toggle(expanded)

    def _on_toggle(self, on):
        self.toggle.setText(("▾  " if on else "▸  ") + self._title)
        self.body.setVisible(on)


def _row(label, widget, help_text=None):
    h = QHBoxLayout()
    lab = QLabel(label)
    lab.setMinimumWidth(150)
    h.addWidget(lab)
    h.addWidget(widget, 1)
    if help_text:
        h.addWidget(help_btn(help_text))
    return h


