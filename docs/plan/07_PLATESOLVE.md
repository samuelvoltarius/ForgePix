# 07 — Plate-Solver: was ForgePix nutzt und was es fertig gibt

Stand 23.11.2026.

## Was ForgePix heute nutzt (am Code geprüft)

| Solver | wo | blind? | Bemerkung |
|---|---|---|---|
| **Eigener Solver** | `core/astrometry.py` | **nein** — braucht RA/Dec und Bildmaßstab als Hinweis (aus FITS-Kopf oder Montierung) | Dreiecksvergleich gegen den lokalen Gaia-Katalog, freie Drehung und Spiegelung, unabhängige Prüfsterne. Wird von Zentrieren, Farbkalibrierung und „Himmelsposition bestimmen“ benutzt. Offline, ohne fremde Programme. |
| Siril | `photometric._solve_wcs_siril` | mit Hinweis | Rückfall, wenn installiert |
| ASTAP | `photometric._find_solver` | mit Hinweis, sucht aber weit | Rückfall; seit 23.11. auch im Windows-Programmordner gesucht |
| astrometry.net `solve-field` | `photometric._find_solver` | **ja** | Rückfall, wenn lokal installiert |
| nova.astrometry.net (online) | `photometric._solve_wcs_astrometry` | **ja** | braucht API-Schlüssel (`--astrometry-key`), lädt das Bild hoch |

Zentrieren am Teleskop nutzt bewusst nur den eigenen Solver: der Hinweis kommt aus der
Montierung, das ist schnell und braucht kein Netz.

## Fertige Projekte — Recherche

*(wird mit dem Ergebnis der Recherche vom 23.11.2026 ergänzt)*
