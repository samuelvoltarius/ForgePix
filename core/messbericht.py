#!/usr/bin/env python3
"""
core/messbericht.py — alle Zahlen über eine Aufnahme an EINER Stelle.

Wozu: die Messungen gab es längst, aber verstreut — `astro_quality` bewertet Einzelbilder,
`sensor` beurteilt das Feld, `equipment` rechnet den Abbildungsmassstab, `filters` kennt die
Bandbreiten, und den Hintergrundgradienten misst der Stapelweg nebenbei. Wer entscheiden will,
was mit einem Bild als Nächstes passieren soll, musste diese Zahlen bisher von Hand
zusammensuchen — und ein Regelwerk oder ein Sprachmodell konnte es gar nicht.

Der Bericht rechnet **nichts neu**, was es schon gibt. Er ruft die vorhandenen Funktionen auf
und legt das Ergebnis in eine flache, benennbare Form.

Zwei Dinge sind Absicht:

* **Fehlende Werte sind `None`, keine Platzhalter.** Ein Bericht, der „0.0" schreibt, wo nichts
  gemessen werden konnte, führt jede spätere Regel in die Irre. `None` heisst „nicht gemessen"
  und muss vom Leser behandelt werden.
* **Der Text ist für Menschen UND Modelle gedacht.** Kurze Zeilen, feste Reihenfolge, Einheiten
  dran. Ein Sprachmodell soll daraus schliessen dürfen — aber die Zahlen kommen aus Python,
  nicht aus dem Modell. Das ist die Trennung, an der solche Systeme sonst scheitern: ein Modell,
  das aus einem kleinen Vorschaubild den Hintergrundwert „schätzt", erfindet ihn.

Beispielausgabe::

    Bild            2822x4144, 3 Kanaele
    Himmel          Median 0.0298, Rauschen 0.00061, Gradient 1.2 %
    Sterne          82 gefunden, FWHM 2.19 px, Rundheit 1.17, ausgebrannt 0.004 %
    Farbe           G/B 1.007, G/R 1.005 - passt zur Kamera
    Ausruestung     ASI294MC Pro, 1151 mm, 4.63 um -> 0.83 "/px (unterabgetastet)
    Serie           8 Aufnahmen, 40.0 min gesamt, einheitlich 300 s
"""
import math
import os

import numpy as np
import cv2

from constants import log_print


def _zahl(x):
    """float oder None — nie NaN, nie unendlich. Ein NaN im Bericht vergiftet jede Regel."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _himmel(bild):
    """Median, Rauschen und Gradient des Hintergrunds.

    Der Hintergrund ist das untere Helligkeitsdrittel — nicht das ganze Bild. Sonst zieht ein
    grosser heller Nebel den Median mit hoch, und das Rauschen wäre die Struktur des Objekts.
    """
    import astro
    lum = astro._gray(bild) if bild.ndim == 3 else np.asarray(bild, np.float32)
    schwelle = float(np.percentile(lum, 40))
    dunkel = lum <= schwelle
    if int(dunkel.sum()) < 100:
        return {"median": _zahl(np.median(lum)), "rauschen": None, "gradient_prozent": None}
    werte = lum[dunkel]
    median = float(np.median(werte))
    rauschen = float(np.median(np.abs(werte - median))) * 1.4826
    # Gradient: wie stark schwankt der Hintergrund ueber die Flaeche? Grob ueber ein 8x8-Raster
    # der Kachel-Mediane, bezogen auf den Gesamtmedian. Ein flacher Himmel liegt bei 0-2 %.
    h, w = lum.shape[:2]
    kh, kw = max(h // 8, 1), max(w // 8, 1)
    kacheln = []
    for y in range(0, h - kh + 1, kh):
        for x in range(0, w - kw + 1, kw):
            block = lum[y:y + kh, x:x + kw]
            kacheln.append(float(np.percentile(block, 20)))   # unteres Ende = Himmel der Kachel
    gradient = None
    if len(kacheln) >= 4 and median > 1e-9:
        gradient = 100.0 * (max(kacheln) - min(kacheln)) / median
    return {"median": _zahl(median), "rauschen": _zahl(rauschen),
            "gradient_prozent": _zahl(gradient)}


_letzter_fehler = {}


def _messziele(bild, pfad):
    """Woran die Sternform gemessen wird — Stapel zuerst, Sub als Rueckfall.

    Liefert (beschreibung, dateipfad, aufraeumen). `analyze_frame` braucht einen Pfad, also
    wird das uebergebene Bild dafuer kurz in eine temporaere Datei geschrieben.
    """
    ziele = []
    try:
        import tempfile
        import cv2
        a = np.asarray(bild, np.float32)
        if a.ndim == 2:
            a = np.dstack([a] * 3)
        fd, tmp = tempfile.mkstemp(prefix="fp_form_", suffix=".tif")
        os.close(fd)
        if cv2.imwrite(tmp, np.clip(a * 65535.0, 0, 65535).astype(np.uint16)):
            def weg(p=tmp):
                try:
                    os.unlink(p)
                except OSError:
                    pass
            ziele.append(("am uebergebenen Bild gemessen", tmp, weg))
        else:
            os.unlink(tmp)
    except Exception as fehler:
        _letzter_fehler["formdatei"] = "%s: %s" % (type(fehler).__name__, fehler)
    if pfad and os.path.isfile(pfad):
        ziele.append(("Form aus %s (Einzelaufnahme)" % os.path.basename(pfad),
                      pfad, lambda: None))
    return ziele


def _sterne(bild, pfad=None):
    """Sternzahl aus dem ÜBERGEBENEN Bild, Sternform aus der getesteten Einzelbildanalyse.

    Die Aufteilung ist Absicht und hat einen Grund, der Geld gekostet hätte:

    * Die **Anzahl** lässt sich am Bild verlässlich zählen und gehört auch dorthin — ein Stapel
      zeigt mehr Sterne als ein Sub (gemessen 367 gegen 218), und ein Bericht, der für beide
      dieselbe Zahl nennt, ist schlicht falsch.
    * **FWHM und Rundheit** kommen aus `astro_quality.analyze_frame`. Der Versuch, sie hier
      selbst über zweite Momente zu messen, lieferte je nach Fenstergrösse und Schwelle Werte
      zwischen 1,53 und 5,83 px für dasselbe Bild, während die vorhandene Analyse 2,19 px sagt.
      Eine zweite, schlechtere Messung neben eine getestete zu stellen, macht den Bericht
      unbrauchbar — man wüsste nie, welcher Zahl zu glauben ist.

    Darum steht in `quelle`, woher die Formwerte stammen.

    **Gemessen wird am übergebenen Bild, nicht an einem Sub.** `analyze_frame` braucht einen
    Dateipfad, also wird das Bild dafür kurz in eine temporäre Datei geschrieben. Der frühere
    Weg — die Form von einem Sub nehmen — führte zu falschen Ratschlägen: an sechs echten
    Seestar-Serien lag die Rundheit der Subs bei 1,63 bis 1,66, die des fertigen Stapels aber
    bei 1,26 bis 1,37. Die Regelschwelle liegt bei 1,6, also empfahl das Regelwerk in vier von
    sechs Fällen `--astro-synthstar` — eine Massnahme, die die Photometrie unbrauchbar macht —
    für Bilder, die gar keine verzogenen Sterne hatten. Die Ausrichtung mittelt die Verformung
    der Einzelaufnahmen weg; genau deshalb ist der Stapel das richtige Messobjekt.
    """
    import astro
    anzahl = None
    try:
        lum = astro._gray(bild) if bild.ndim == 3 else np.asarray(bild, np.float32)
        punkte = astro._star_centroids(lum / (float(lum.max()) + 1e-9), max_stars=2000)
        anzahl = int(len(punkte))
    except Exception as fehler:
        _letzter_fehler["sterne"] = "%s: %s" % (type(fehler).__name__, fehler)
    # Erst am uebergebenen Bild versuchen (das ist der Stapel), dann als Rueckfall am Sub.
    for quelle, messpfad, aufraeumen in _messziele(bild, pfad):
        try:
            import astro_quality
            r = astro_quality.analyze_frame(messpfad)
            return {"anzahl": anzahl if anzahl is not None else r.get("stars"),
                    "fwhm_px": _zahl(r.get("fwhm")), "rundheit": _zahl(r.get("ecc")),
                    "spur": bool(r.get("trail")), "quelle": quelle}
        except Exception as fehler:
            _letzter_fehler["form"] = "%s: %s" % (type(fehler).__name__, fehler)
        finally:
            aufraeumen()
    return {"anzahl": anzahl, "fwhm_px": None, "rundheit": None, "spur": None,
            "quelle": "nur gezaehlt" if anzahl is not None else None}


def _ausgebrannt(bild, grenze=0.995):
    """Anteil Pixel am oberen Anschlag, in Prozent. Über 0,1 % sind Sternkerne verloren."""
    a = np.asarray(bild, np.float32)
    if a.size == 0:
        return None
    return _zahl(100.0 * float((a >= grenze).mean()))


def _farbe(bild, kamera=None):
    """Kanalverhältnisse im Hintergrund plus das Urteil aus der Kameradatenbank."""
    a = np.asarray(bild, np.float32)
    if a.ndim != 3 or a.shape[2] != 3:
        return {"g_zu_b": None, "g_zu_r": None, "urteil": "einkanalig", "passt": None}
    lum = a.mean(axis=2)
    dunkel = lum <= float(np.percentile(lum, 40))
    if int(dunkel.sum()) < 100:
        return {"g_zu_b": None, "g_zu_r": None, "urteil": "zu wenig Hintergrund", "passt": None}
    b, g, r = (float(a[..., i][dunkel].mean()) for i in range(3))
    verh = {"g_zu_b": _zahl(g / b) if b > 1e-9 else None,
            "g_zu_r": _zahl(g / r) if r > 1e-9 else None}
    verh["passt"], verh["urteil"] = None, "keine Kamera angegeben"
    if kamera:
        try:
            import equipment
            verh["passt"], verh["urteil"] = equipment.farb_plausibel(kamera, a)
        except Exception as fehler:
            verh["urteil"] = "Farbpruefung nicht moeglich (%s)" % fehler
    return verh


def _signal(bild):
    """Wie weit hebt sich das Objekt vom Himmel ab, gemessen in Rausch-Einheiten.

    Das ist die ehrlichste Einzelzahl über eine Nacht: liegt sie unter 1, ist das Signal
    schwächer als das Rauschen, und keine Bearbeitung kann daraus Farbe machen. Genau diese
    Grenze wurde an Alfreds Dual-Band-Daten schon einmal teuer übersehen.
    """
    import astro
    lum = astro._gray(bild) if bild.ndim == 3 else np.asarray(bild, np.float32)
    himmel = float(np.percentile(lum, 30))
    objekt = float(np.percentile(lum, 99.0))
    dunkel = lum <= float(np.percentile(lum, 40))
    if int(dunkel.sum()) < 100:
        return None
    werte = lum[dunkel]
    rauschen = float(np.median(np.abs(werte - np.median(werte)))) * 1.4826
    return _zahl((objekt - himmel) / rauschen) if rauschen > 1e-12 else None


def _ausruestung(pfad, kamera=None, filter_key=None):
    """Kamera, Filter, Brennweite, Abbildungsmassstab und das Sampling-Urteil."""
    daten = {"kamera": kamera, "filter": filter_key, "brennweite_mm": None,
             "pixelgroesse_um": None, "skala_bogensek_px": None, "sampling": None,
             "belichtung_s": None, "temperatur_c": None, "gain": None}
    if not pfad or not os.path.isfile(pfad):
        return daten
    try:
        from astropy.io import fits
        import equipment
        header = fits.getheader(pfad)
        aus = equipment.aus_header(header)
        daten.update({k: aus.get(k) for k in
                      ("brennweite_mm", "pixelgroesse_um", "belichtung_s", "temperatur_c", "gain")})
        daten["kamera"] = kamera or aus.get("kamera")
        daten["filter"] = filter_key or aus.get("filter")
        if aus.get("brennweite_mm") and aus.get("pixelgroesse_um"):
            # Reihenfolge beachten: (Brennweite in mm, Pixelgroesse in um). Vertauscht kommt
            # 51276 "/px heraus statt 0,83 — ein Wert, den man im Bericht sofort sieht, in
            # einer Regel aber blind weiterreichen wuerde.
            daten["skala_bogensek_px"] = _zahl(
                equipment.abbildungsskala(aus["brennweite_mm"], aus["pixelgroesse_um"],
                                          aus.get("binning") or 1))
    except Exception:
        pass
    return daten


def _serie(paths):
    """Was über die Aufnahmeserie bekannt ist: Anzahl, Gesamtbelichtung, gemischte Zeiten."""
    if not paths:
        return {"anzahl": None, "gesamt_minuten": None, "zeiten_s": None, "gemischt": None}
    zeiten, gesamt_s, subs = [], 0.0, 0
    for p in paths:
        if os.path.splitext(p)[1].lower() not in (".fit", ".fits", ".fts"):
            continue
        try:
            from astropy.io import fits
            h = fits.getheader(p)
            t = h.get("EXPTIME", h.get("EXPOSURE"))
            if t is not None:
                zeiten.append(float(t))
            # Fertige Stapel tragen ihre wahre Gesamtbelichtung im Header (Seestar:
            # TOTALEXP/STACKCNT). Ohne diese Felder meldete der Bericht fuer sechs
            # zusammengefasste M-42-Ergebnisse "3 Minuten" statt 199 — Faktor 66.
            gt = h.get("TOTALEXP")
            gesamt_s += float(gt) if gt is not None else float(t or 0.0)
            sc = h.get("STACKCNT")
            if sc is not None:
                subs += int(float(sc))
        except Exception:
            continue
    if not zeiten:
        return {"anzahl": len(paths), "gesamt_minuten": None, "zeiten_s": None,
                "gemischt": None, "enthaltene_subs": None}
    einzeln = sorted(set(round(t, 1) for t in zeiten))
    return {"anzahl": len(paths), "gesamt_minuten": _zahl(gesamt_s / 60.0),
            "zeiten_s": einzeln, "gemischt": len(einzeln) > 1,
            "enthaltene_subs": (subs if subs else None)}


def erstellen(bild, pfad=None, paths=None, kamera=None, filter_key=None, log=log_print):
    """Den vollständigen Messbericht erstellen.

    Args:
        bild: das LINEARE Bild (float, BGR oder mono). Nach einer Streckung sind Median,
            Rauschen und Kanalverhältnisse verzerrt und der Bericht wertlos.
        pfad: eine Beispieldatei für die Header-Angaben (Kamera, Brennweite, Belichtung).
        paths: die ganze Serie, für Anzahl und Gesamtbelichtung.
        kamera: Kameraschlüssel aus `equipment` — nur damit gibt es ein Farburteil.

    Returns:
        dict mit den Abschnitten `bild`, `himmel`, `sterne`, `farbe`, `signal`,
        `ausruestung` und `serie`.
    """
    a = np.asarray(bild, np.float32)

    # Kamera aus dem Header erkennen, wenn keine vorgegeben wurde. Ohne Schluessel gaebe es
    # kein Farburteil — und niemand traegt im DAU-Modus eine Kamera von Hand ein. Erkannt wird
    # nur, was eindeutig ist; bei Mehrdeutigkeit bleibt es None (siehe equipment.kamera_aus_name).
    kamera_quelle = "vorgegeben" if kamera else None
    if not kamera and pfad:
        try:
            from astropy.io import fits
            import equipment
            kamera = equipment.kamera_aus_name(fits.getheader(pfad).get("INSTRUME"))
            if kamera:
                kamera_quelle = "aus dem Header erkannt"
        except Exception:
            kamera = None

    bericht = {
        "bild": {"hoehe": int(a.shape[0]), "breite": int(a.shape[1]),
                 "kanaele": int(a.shape[2]) if a.ndim == 3 else 1,
                 "ausgebrannt_prozent": _ausgebrannt(a)},
        "himmel": _himmel(a),
        "sterne": _sterne(a, pfad),
        "farbe": _farbe(a, kamera),
        "signal_zu_rauschen": _signal(a),
        "ausruestung": _ausruestung(pfad, kamera, filter_key),
        "serie": _serie(paths),
    }
    bericht["ausruestung"]["kamera_schluessel"] = kamera
    bericht["ausruestung"]["kamera_herkunft"] = kamera_quelle
    try:
        import equipment
        skala = bericht["ausruestung"].get("skala_bogensek_px")
        fwhm = bericht["sterne"].get("fwhm_px")
        if skala and fwhm:
            bericht["ausruestung"]["sampling"] = equipment.sampling_urteil(skala, fwhm)[0]
    except Exception:
        pass
    return bericht


def text(bericht):
    """Den Bericht als kurzen Block — für das Protokoll und als Eingabe für ein Modell."""
    z = []

    def wert(x, form="%.4f", sonst="?"):
        return sonst if x is None else (form % x)

    b, hi, st = bericht["bild"], bericht["himmel"], bericht["sterne"]
    fa, au, se = bericht["farbe"], bericht["ausruestung"], bericht["serie"]
    z.append("Bild            %dx%d, %d Kanaele, ausgebrannt %s %%"
             % (b["breite"], b["hoehe"], b["kanaele"], wert(b["ausgebrannt_prozent"], "%.3f")))
    z.append("Himmel          Median %s, Rauschen %s, Gradient %s %%"
             % (wert(hi["median"]), wert(hi["rauschen"], "%.5f"),
                wert(hi["gradient_prozent"], "%.1f")))
    # Die Herkunft der Formwerte gehoert in die Zeile: FWHM und Rundheit beschreiben ein
    # einzelnes Sub, die Anzahl das uebergebene Bild. Ohne diesen Zusatz liest man beides
    # als Aussage ueber denselben Gegenstand.
    herkunft = st.get("quelle") or ""
    zusatz = ""
    if st.get("fwhm_px") is not None and herkunft.startswith("Form aus"):
        zusatz = "   [Form gemessen an einem Sub, nicht am Stapel]"
    z.append("Sterne          %s gefunden, FWHM %s px, Rundheit %s%s%s"
             % (wert(st["anzahl"], "%d"), wert(st["fwhm_px"], "%.2f"),
                wert(st["rundheit"], "%.2f"), ", Spur erkannt" if st.get("spur") else "",
                zusatz))
    z.append("Farbe           G/B %s, G/R %s - %s"
             % (wert(fa["g_zu_b"], "%.3f"), wert(fa["g_zu_r"], "%.3f"), fa["urteil"]))
    z.append("Signal/Rauschen %s%s"
             % (wert(bericht["signal_zu_rauschen"], "%.1f"),
                "   ACHTUNG: Signal schwaecher als das Rauschen"
                if (bericht["signal_zu_rauschen"] or 99) < 1 else ""))
    teile = [t for t in (au.get("kamera"),
                         "%.0f mm" % au["brennweite_mm"] if au.get("brennweite_mm") else None,
                         "%.2f um" % au["pixelgroesse_um"] if au.get("pixelgroesse_um") else None,
                         '%.2f "/px' % au["skala_bogensek_px"] if au.get("skala_bogensek_px") else None,
                         au.get("sampling")) if t]
    z.append("Ausruestung     %s" % (", ".join(str(t) for t in teile) if teile else "unbekannt"))
    if se.get("anzahl"):
        zeiten = se.get("zeiten_s") or []
        z.append("Serie           %d Aufnahmen, %s min gesamt, %s"
                 % (se["anzahl"], wert(se.get("gesamt_minuten"), "%.1f"),
                    ("gemischt: " + "/".join("%g s" % t for t in zeiten)) if se.get("gemischt")
                    else ("einheitlich %g s" % zeiten[0] if zeiten else "Zeiten unbekannt")))
    return "\n".join(z)
