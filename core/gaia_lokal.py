#!/usr/bin/env python3
"""
core/gaia_lokal.py — Lokale Gaia-Positionen, G-Helligkeit und BP−RP-Farbindex.

Dieser Auszug enthält keine XP-Spektren und implementiert keine SPCC. Neue Downloads
stammen aus Gaia DR3 / ICRS zur Referenzepoche J2016.0; Eigenbewegung wird nicht
fortgeschrieben. Alte Dateien ohne Herkunftsmetadaten behalten eine unbekannte Epoche.
ESA-Datenmodell: https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html

**Was hier NICHT passiert:** der Gaia-Katalog wird nicht mitgeliefert. Er umfasst über
1,8 Milliarden Sterne und mehrere Terabyte; abgesehen davon hat er seine eigenen
Nutzungsbedingungen. Stattdessen legt sich jeder seinen eigenen kleinen Katalog an — einmal,
mit Netz, für die Himmelsgegenden, die er fotografiert. Ein Feld von einem Grad Radius braucht
je nach Sterndichte einige hundert Kilobyte. Danach läuft die Kalibrierung offline.

**Warum kein HEALPix:** die Sternsuche braucht einen Index, sonst muss für jedes Bild der ganze
Katalog durchgegangen werden. HEALPix ist dafür das übliche Verfahren, verlangt aber eine
zusätzliche Bibliothek (`healpy` oder `astropy_healpix`), die hier nicht installiert ist und die
für einen Katalog dieser Grösse nichts einbringt. Der Index hier teilt den Himmel in
Deklinationsbänder und darin in Rektaszensions-Zellen, deren Breite mit `1/cos(dec)` wächst — die
Zellen bleiben dadurch etwa gleich gross, was der eigentliche Zweck von HEALPix ist. Gemessene
Abfragezeiten stehen in tests/test_gaia_lokal.py.

Aufbau der Katalogdatei (`.npz`, komprimiert):
    ra, dec        float64, Grad
    g_mag          float32, Gaia-G-Helligkeit
    bp_rp          float32, Farbindex (BP − RP) — das ist die eigentlich gebrauchte Grösse
    zellen         int64, Zellennummer je Stern (nach ihr ist alles sortiert)
    zell_start     int64, Anfangsindex je belegter Zelle
    zell_id        int64, die zugehörigen Zellennummern
"""
import math
import os
import json
import time
import threading
from datetime import datetime, timezone

import numpy as np

from constants import log_print, ForgePixFehler

# Grösse eines Deklinationsbandes in Grad. 2° ist ein Kompromiss: kleiner heisst mehr Zellen
# (und mehr Verwaltung), grösser heisst mehr Sterne je Zelle und damit langsamere Abfragen.
BAND_GRAD = 2.0


def _zahl(wert, name):
    if isinstance(wert, (bool, complex, np.complexfloating)):
        raise ForgePixFehler("Gaia lokal: %s muss eine endliche reelle Zahl sein." % name)
    try:
        wert = float(wert)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ForgePixFehler("Gaia lokal: ungültiger Wert für %s." % name) from exc
    if not np.isfinite(wert):
        raise ForgePixFehler("Gaia lokal: %s muss endlich sein." % name)
    return wert


def _suchgebiet(ra, dec, radius):
    ra, dec, radius = (_zahl(ra, "RA"), _zahl(dec, "Deklination"), _zahl(radius, "Radius"))
    if not -90 <= dec <= 90 or not 0 <= radius <= 180:
        raise ForgePixFehler("Gaia lokal: Deklination muss in −90…90°, Radius in 0…180° liegen.")
    return ra % 360., dec, radius


def _bandbreite(band):
    """Breite einer Rektaszensions-Zelle in diesem Deklinationsband, in Grad.

    Gerechnet wird mit dem POLNAEHEREN Rand des Bandes: dort sind die Meridiane am dichtesten
    beieinander, und eine Zelle, die dort passt, passt im ganzen Band.
    """
    b = np.asarray(band, np.float64)
    unten = b * BAND_GRAD - 90.0
    oben = unten + BAND_GRAD
    rand = np.maximum(np.abs(unten), np.abs(oben))
    return BAND_GRAD / np.maximum(np.cos(np.radians(np.minimum(rand, 89.9))), 0.02)


def _zelle(ra, dec):
    """Zellennummer für (ra, dec) in Grad.

    Die Rektaszensions-Zellen werden mit `1/cos(dec)` breiter, damit sie am Pol nicht zu
    schmalen Streifen entarten — dort laufen die Meridiane zusammen, und eine feste Breite in
    Grad würde am Pol Zellen von wenigen Bogenminuten Ausdehnung ergeben.
    """
    dec = np.clip(np.asarray(dec, np.float64), -89.999, 89.999)
    ra = np.mod(np.asarray(ra, np.float64), 360.0)
    band = np.floor((dec + 90.0) / BAND_GRAD).astype(np.int64)
    # Die Zellenbreite haengt am BAND, nicht an der Deklination des einzelnen Sterns. Der erste
    # Entwurf rechnete sie aus der Sterndeklination — damit hatten zwei Sterne im selben Band
    # verschiedene Zellenraster, und die Abfrage (die nur EIN Raster je Band kennen kann) suchte
    # in den falschen Zellen. Gemessen gingen so bei Deklination 78 Grad sechs von 21 Sternen
    # verloren, ohne dass irgendetwas fehlgeschlagen waere.
    breite = _bandbreite(band)
    spalte = np.floor(ra / breite).astype(np.int64)
    return band * 100000 + spalte


def _winkelabstand(ra1, dec1, ra2, dec2):
    """Winkelabstand in Grad (Haversine auf der Kugel).

    Die naive Formel über das Skalarprodukt verliert bei kleinen Abständen jede Genauigkeit,
    weil `arccos` dort fast flach verläuft — und klein sind die Abstände hier immer.
    """
    p1, p2 = np.radians(dec1), np.radians(dec2)
    dl = np.radians(np.asarray(ra2, np.float64) - ra1)
    dp = p2 - p1
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return np.degrees(2 * np.arcsin(np.sqrt(np.clip(a, 0, 1))))


class Katalog:
    """Ein lokaler Sternkatalog mit Zellenindex."""

    def __init__(self, ra, dec, g_mag, bp_rp, *, metadata=None):
        arrays = []
        for values in (ra, dec, g_mag, bp_rp):
            if np.iscomplexobj(values):
                raise ForgePixFehler("Gaia lokal: Katalogspalten müssen reell sein.")
            try:
                array = np.ma.asarray(values, dtype=np.float64).filled(np.nan)
            except (ValueError, TypeError, OverflowError) as exc:
                raise ForgePixFehler("Gaia lokal: ungültige Katalogspalte.") from exc
            if array.ndim != 1 or (arrays and array.shape != arrays[0].shape):
                raise ForgePixFehler("Gaia lokal: Katalogspalten müssen gleich lange eindimensionale Arrays sein.")
            arrays.append(array)
        ra, dec, g, c = arrays
        gueltig = (np.isfinite(ra) & np.isfinite(dec) & np.isfinite(g) & np.isfinite(c)
                   & (np.abs(dec) <= 90) & (np.abs(g) <= np.finfo(np.float32).max)
                   & (np.abs(c) <= np.finfo(np.float32).max))
        ra, dec, g, c = ra[gueltig], dec[gueltig], g[gueltig], c[gueltig]
        ra = np.mod(ra, 360.)
        g, c = g.astype(np.float32), c.astype(np.float32)
        try:
            metadata = {} if metadata is None else metadata
            if not isinstance(metadata, dict) or not isinstance(metadata.get("fields", []), list):
                raise ValueError("Metadaten müssen ein Objekt mit optionaler Feldliste sein")
            if any(not isinstance(field, dict) for field in metadata.get("fields", [])):
                raise ValueError("Suchfelder müssen Metadatenobjekte sein")
            if "reference_epoch_jyear" in metadata and (isinstance(metadata["reference_epoch_jyear"], bool)
                    or not isinstance(metadata["reference_epoch_jyear"], (int, float))):
                raise ValueError("Koordinatenepoche muss eine Zahl sein")
            if "proper_motion_applied" in metadata and not isinstance(metadata["proper_motion_applied"], bool):
                raise ValueError("Eigenbewegungsstatus muss ein Wahrheitswert sein")
            self.metadata = json.loads(json.dumps(metadata, allow_nan=False))
        except (ValueError, TypeError) as exc:
            raise ForgePixFehler("Gaia lokal: ungültige Herkunftsmetadaten.") from exc
        z = _zelle(ra, dec)
        ordnung = np.argsort(z, kind="stable")
        self.ra, self.dec = ra[ordnung], dec[ordnung]
        self.g_mag, self.bp_rp = g[ordnung], c[ordnung]
        self.zellen = z[ordnung]
        self.zell_id, self.zell_start = np.unique(self.zellen, return_index=True)

    def __len__(self):
        return int(self.ra.size)

    def kegelsuche(self, ra, dec, radius_grad, max_mag=None, min_mag=None):
        """Alle Sterne innerhalb `radius_grad` um (ra, dec). Gibt ein dict von Arrays zurück.

        Gesucht wird nur in den Zellen, die den Kreis überhaupt berühren können — genau dafür
        ist der Index da. Der Kandidatenbereich wird bewusst grosszügig gewählt und dann exakt
        nachgeprüft; ein zu knapper Index würde Sterne am Rand verlieren, und die fallen bei
        einer Farbkalibrierung nicht auf.
        """
        ra, dec, radius = _suchgebiet(ra, dec, radius_grad)
        max_mag = None if max_mag is None else _zahl(max_mag, "obere Helligkeitsgrenze")
        min_mag = None if min_mag is None else _zahl(min_mag, "untere Helligkeitsgrenze")
        if max_mag is not None and min_mag is not None and min_mag > max_mag:
            raise ForgePixFehler("Gaia lokal: untere Helligkeitsgrenze liegt über der oberen.")
        d_min, d_max = max(dec - radius, -90.0), min(dec + radius, 90.0)
        last_band = int(math.ceil(180.0 / BAND_GRAD)) - 1
        b0 = min(last_band, int(math.floor((d_min + 90.0) / BAND_GRAD)))
        b1 = min(last_band, int(math.floor((d_max + 90.0) / BAND_GRAD)))
        kandidaten = []
        for band in range(b0, b1 + 1):
            breite = float(_bandbreite(band))
            # Ausdehnung in Rektaszension, die `radius` an der POLNAEHESTEN Stelle des Kreises
            # entspricht — dort ist sie am groessten. Der erste Entwurf nahm die polFERNSTE
            # und suchte damit einen zu schmalen Streifen ab.
            polnah = min(max(abs(d_min), abs(d_max)), 89.9)
            cos_d = max(math.cos(math.radians(polnah)), 1e-6)
            ra_spanne = min(radius / cos_d, 180.0)
            s0 = int(math.floor((ra - ra_spanne) / breite)) - 1
            s1 = int(math.floor((ra + ra_spanne) / breite)) + 1
            n_spalten = int(math.ceil(360.0 / breite))
            for spalte in range(s0, s1 + 1):
                sp = spalte % max(n_spalten, 1)
                nummer = band * 100000 + sp
                k = np.searchsorted(self.zell_id, nummer)
                if k < self.zell_id.size and self.zell_id[k] == nummer:
                    anfang = self.zell_start[k]
                    ende = (self.zell_start[k + 1] if k + 1 < self.zell_start.size
                            else self.zellen.size)
                    kandidaten.append((anfang, ende))
        if not kandidaten:
            leer = np.zeros(0)
            return {"ra": leer, "dec": leer, "g_mag": leer, "bp_rp": leer}
        idx = np.concatenate([np.arange(a, e) for a, e in kandidaten])
        idx = np.unique(idx)
        d = _winkelabstand(ra, dec, self.ra[idx], self.dec[idx])
        treffer = idx[d <= radius]
        g = self.g_mag[treffer]
        maske = np.ones(g.shape, bool)
        if max_mag is not None:
            maske &= (g <= float(max_mag))
        if min_mag is not None:
            maske &= (g >= float(min_mag))
        treffer = treffer[maske]
        return {"ra": self.ra[treffer], "dec": self.dec[treffer],
                "g_mag": self.g_mag[treffer], "bp_rp": self.bp_rp[treffer]}

    def speichern(self, pfad):
        np.savez_compressed(pfad, ra=self.ra, dec=self.dec, g_mag=self.g_mag,
                            bp_rp=self.bp_rp, zellen=self.zellen,
                            zell_id=self.zell_id, zell_start=self.zell_start,
                            band_grad=np.float64(BAND_GRAD), format_version=np.int64(2),
                            metadata_json=np.asarray(json.dumps(self.metadata, allow_nan=False)))
        return True

    @classmethod
    def laden(cls, pfad, log=log_print):
        """Katalog laden. Gibt None zurück, wenn die Datei fehlt oder unbrauchbar ist."""
        try:
            with np.load(pfad, allow_pickle=False) as d:
                version = d["format_version"].item() if "format_version" in d else 1
                if version not in (1, 2):
                    raise ValueError("unbekannte Katalogversion")
                metadata = json.loads(str(d["metadata_json"].item())) if "metadata_json" in d else {}
                # The saved index is a cache, not catalogue data. Rebuild from
                # validated coordinates even when its recorded band size agrees:
                # stale/corrupt cell ids previously hid otherwise valid stars.
                k = cls(d["ra"], d["dec"], d["g_mag"], d["bp_rp"], metadata=metadata)
            return k
        except Exception as e:
            log("    Gaia lokal: Katalog nicht lesbar (%s)" % e)
            return None


def standard_pfad():
    """Wo der eigene Katalog liegt — neben den übrigen Einstellungen."""
    basis = (os.environ.get("APPDATA")
             or os.path.join(os.path.expanduser("~"), ".config"))
    return os.path.join(basis, "ForgePix", "gaia_lokal.npz")


def zusammenfuehren(alt, neu):
    """Zwei Kataloge vereinigen und Doppelte entfernen.

    Doppelte entstehen zwangsläufig: wer zwei benachbarte Felder herunterlädt, holt den
    Überlappungsbereich zweimal. Erkannt werden sie über Ort UND Helligkeit; zwei echte Sterne
    liegen praktisch nie auf einer Millibogensekunde beisammen.
    """
    if alt is None:
        return neu
    if neu is None:
        return alt
    ra = np.concatenate([alt.ra, neu.ra])
    dec = np.concatenate([alt.dec, neu.dec])
    g = np.concatenate([alt.g_mag, neu.g_mag])
    c = np.concatenate([alt.bp_rp, neu.bp_rp])
    schluessel = np.stack([np.round(ra, 7), np.round(dec, 7), np.round(g, 3)], axis=1)
    _, erste = np.unique(schluessel, axis=0, return_index=True)
    erste = np.sort(erste)
    metadata = {"fields": alt.metadata.get("fields", []) + neu.metadata.get("fields", [])}
    for key in ("catalogue", "reference_frame", "reference_epoch_jyear", "proper_motion_applied"):
        if key in alt.metadata and key in neu.metadata and alt.metadata[key] == neu.metadata[key]:
            metadata[key] = alt.metadata[key]
    return Katalog(ra[erste], dec[erste], g[erste], c[erste], metadata=metadata)


def _tap_abfrage(query, *, cancel=None, timeout=120):
    """Native ESA TAP/UWS query with bounded reads and cooperative cancellation.

    https://www.cosmos.esa.int/web/gaia-users/archive/programmatic-access
    https://www.ivoa.net/documents/UWS/20161024/REC-UWS-1.1-20161024.html
    """
    from http.cookiejar import CookieJar
    from urllib import request, parse, error

    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    timeout = _zahl(timeout, "Zeitlimit")
    if not 1 <= timeout <= 600:
        raise ForgePixFehler("Gaia lokal: Zeitlimit muss zwischen 1 und 600 Sekunden liegen.")
    cancel = cancel if cancel is not None else threading.Event()
    deadline = time.monotonic() + timeout
    endpoint = "https://gea.esac.esa.int/tap-server/tap"
    opener = request.build_opener(request.HTTPCookieProcessor(CookieJar()), NoRedirect())
    job_url = None

    def check():
        if cancel.is_set():
            raise ForgePixFehler("Gaia-Download abgebrochen.")
        if time.monotonic() >= deadline:
            raise ForgePixFehler("Gaia-Download: Zeitlimit erreicht. Bitte später erneut versuchen.")

    def fetch(url, parameters=None, redirects=0):
        check()
        payload = None if parameters is None else parse.urlencode(parameters).encode("ascii")
        req = request.Request(url, data=payload, headers={"User-Agent": "ForgePix Gaia catalogue"})
        try:
            response = opener.open(req, timeout=min(10., max(.1, deadline - time.monotonic())))
        except error.HTTPError as exc:
            if exc.code == 303:
                headers = exc.headers
                exc.close()
                if parameters is None:
                    target = parse.urljoin(url, headers.get("Location", ""))
                    if redirects >= 3 or not target.startswith(endpoint + "/"):
                        raise ForgePixFehler("Gaia-Archiv lieferte eine ungültige Ergebnisweiterleitung.")
                    return fetch(target, redirects=redirects + 1)
                return headers, b""
            raise
        with response:
            chunks, size = [], 0
            while True:
                check()
                block = response.read(65536)
                if not block:
                    break
                size += len(block)
                if size > 128 * 1024 * 1024:
                    raise ForgePixFehler("Gaia-Antwort zu groß; bitte ein kleineres Feld wählen.")
                chunks.append(block)
            return response.headers, b"".join(chunks)

    try:
        headers, _ = fetch(endpoint + "/async", {"REQUEST": "doQuery", "LANG": "ADQL",
                          "FORMAT": "json", "QUERY": query, "PHASE": "RUN"})
        location = parse.urljoin(endpoint + "/async/", headers.get("Location", ""))
        parsed = parse.urlsplit(location)
        if (parsed.hostname != "gea.esac.esa.int" or parsed.scheme not in ("http", "https")
                or not parsed.path.startswith("/tap-server/tap/async/")
                or parsed.path == "/tap-server/tap/async/"):
            raise ForgePixFehler("Gaia-Archiv lieferte keine gültige Auftragsadresse.")
        job_url = parse.urlunsplit(("https", parsed.netloc, parsed.path, "", ""))
        started = False
        while True:
            _, body = fetch(job_url + "/phase")
            phase = body.decode("ascii").strip().upper()
            if phase == "COMPLETED":
                break
            if phase in ("ERROR", "ABORTED", "UNKNOWN"):
                raise ForgePixFehler("Gaia-Archiv konnte die Abfrage nicht abschließen (%s)." % phase)
            if phase == "PENDING" and not started:
                fetch(job_url + "/phase", {"PHASE": "RUN"})
                started = True
            elif phase not in ("PENDING", "QUEUED", "EXECUTING", "HELD", "SUSPENDED"):
                raise ForgePixFehler("Gaia-Archiv meldet einen unbekannten Auftragsstatus.")
            cancel.wait(min(1., max(0., deadline - time.monotonic())))
        _, body = fetch(job_url + "/results/result")
        result = json.loads(body)
        names = [column["name"] for column in result["metadata"]]
        rows = result["data"]
        if not isinstance(rows, list) or any(len(row) != len(names) for row in rows):
            raise ValueError("ungültige Tabellenform")
        required = ("ra", "dec", "phot_g_mean_mag", "bp_rp")
        table = {key: np.asarray([row[names.index(key)] for row in rows], np.float64) for key in required}
        check()
        return table
    except ForgePixFehler:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ForgePixFehler("Gaia-Download fehlgeschlagen: %s" % exc) from exc
    finally:
        if job_url:
            try:
                # Delete only the temporary server job created by this request.
                with opener.open(request.Request(job_url, method="DELETE"), timeout=2):
                    pass
            except Exception:
                pass


def herunterladen(ra, dec, radius_grad=1.0, max_mag=17.0, grenze=20000, log=log_print,
                  *, cancel=None, timeout=120):
    """Ein Feld nativ von Gaia holen (Netz nötig) und als Katalog zurückgeben.

    Das ist der EINE Schritt, für den Internet nötig ist. Danach läuft alles offline.
    """
    ra, dec, radius_grad = _suchgebiet(ra, dec, radius_grad)
    max_mag = _zahl(max_mag, "G-Grenze")
    grenze = _zahl(grenze, "Zeilenlimit")
    if grenze != int(grenze) or not 1 <= grenze <= 1_000_000:
        raise ForgePixFehler("Gaia lokal: Zeilenlimit muss eine ganze Zahl von 1 bis 1.000.000 sein.")
    grenze = int(grenze)
    log("    Gaia lokal: frage %.4f %.4f, Radius %.2f Grad, bis G=%.1f ab …"
        % (ra, dec, radius_grad, max_mag))
    # ESA recommends asynchronous queries above 2000 rows. Request one extra
    # row to detect our own TOP limit; never store an arbitrary truncated field.
    # https://www.cosmos.esa.int/web/gaia-users/archive/use-cases
    query = (
        "SELECT TOP %d ra, dec, phot_g_mean_mag, bp_rp FROM gaiadr3.gaia_source "
        "WHERE 1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', %f, %f, %f)) "
        "AND phot_g_mean_mag < %f AND bp_rp IS NOT NULL ORDER BY source_id"
        % (grenze + 1, ra, dec, radius_grad, max_mag))
    t = _tap_abfrage(query, cancel=cancel, timeout=timeout)
    rows_received = len(t["ra"])
    if rows_received > grenze:
        raise ForgePixFehler("Gaia lokal: Das Feld enthält mehr als %d passende Sterne. "
                             "Radius verkleinern oder nur hellere Sterne anfordern; "
                             "ein abgeschnittener Katalog wird nicht gespeichert." % grenze)
    metadata = {"catalogue": "gaiadr3.gaia_source", "reference_frame": "ICRS",
                "reference_epoch_jyear": 2016.0, "proper_motion_applied": False,
                "fields": [{"ra_deg": ra, "dec_deg": dec, "radius_deg": radius_grad,
                            "max_mag": max_mag, "color_selection": "bp_rp IS NOT NULL",
                            "row_limit": grenze, "rows_received": rows_received, "row_limit_reached": False,
                            "downloaded_utc": datetime.now(timezone.utc).isoformat()}]}
    k = Katalog(t["ra"], t["dec"], t["phot_g_mean_mag"], t["bp_rp"], metadata=metadata)
    log("    Gaia lokal: %d Sterne erhalten" % len(k))
    return k


def feld_hinzufuegen(ra, dec, radius_grad=1.0, pfad=None, max_mag=17.0, log=log_print):
    """Ein Feld holen und in den eigenen Katalog aufnehmen. Gibt die Sternzahl zurück."""
    pfad = pfad or standard_pfad()
    os.makedirs(os.path.dirname(os.path.abspath(pfad)), exist_ok=True)
    alt = Katalog.laden(pfad, log=log) if os.path.exists(pfad) else None
    neu = herunterladen(ra, dec, radius_grad, max_mag=max_mag, log=log)
    zusammen = zusammenfuehren(alt, neu)
    zusammen.speichern(pfad)
    log("    Gaia lokal: Katalog jetzt %d Sterne (%s)" % (len(zusammen), pfad))
    return len(zusammen)


def abdeckung(katalog, ra, dec, radius_grad, mindestens=30):
    """Genügend Sterne für einen Abgleich? Gibt (ok, anzahl, satz) zurück.

    Wichtiger als es aussieht: ein Katalog, der das Feld gar nicht enthält, liefert einfach
    null Sterne — und eine Farbkalibrierung mit null Sternen würde entweder scheitern oder,
    schlimmer, mit einem Zufallsergebnis durchlaufen. Darum wird vorher gefragt.
    """
    if katalog is None or len(katalog) == 0:
        return False, 0, "kein lokaler Katalog vorhanden"
    treffer = katalog.kegelsuche(ra, dec, radius_grad)
    n = int(treffer["ra"].size)
    if n < mindestens:
        return False, n, ("nur %d Katalogsterne im Feld (mindestens %d noetig) — dieses Feld "
                          "einmal mit Netz nachladen" % (n, mindestens))
    return True, n, "%d Katalogsterne im Feld; räumliche Vollständigkeit nicht geprüft" % n
