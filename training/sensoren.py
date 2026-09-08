"""Gemessene Sensor-Kennwerte — damit das Training echte Kameras nachbildet statt Zufall.

Das Rauschmodell im Training war physikalisch richtig aufgebaut (Poisson-Schrotrauschen,
gaussches Ausleserauschen, korreliertes Rauschen, Zeilenrauschen), aber seine Parameter kamen
aus willkuerlichen Bereichen: Vollskala 250 bis 125000 Elektronen, ueber einen Faktor 500. Ein
Modell verteilt seine Kapazitaet damit ueber Sensoren, die es nie zu sehen bekommt.

Die Werte hier sind an Alfreds eigenen Aufnahmen GEMESSEN, nicht aus Datenblaettern
abgeschrieben. Verfahren:

* **Zeitliches Rauschen** aus der Differenz zweier aufeinanderfolgender Aufnahmen. Himmel,
  Objekt und das feste Muster stehen in beiden gleich und fallen heraus.
* **Gain** aus Himmel geteilt durch Varianz — aber erst, nachdem der SOCKEL abgezogen ist.
  Genau den hatte ein erster Anlauf unterschlagen, und daran scheiterte er: zwei Ordner
  derselben Kamera mit identischer Einstellung ergaben 2,1 und 4,4 e-/ADU.
* Der Sockel selbst aus zwei Serien mit gleicher Gain- UND Offset-Einstellung:
  zwei Gleichungen, zwei Unbekannte.

    (Himmel_1 - Sockel) = Varianz_1 * Gain
    (Himmel_2 - Sockel) = Varianz_2 * Gain

Ergebnis, ueber vier Serien mit zwei Offset- und zwei Gain-Einstellungen gegengeprueft:

    m106   Offset 30  Himmel 1229  Varianz 281.0  -> 0,281 e-/ADU
    risi   Offset 30  Himmel 1328  Varianz 633.0  -> 0,281
    roset  Offset 30  Himmel 1335  Varianz 633.1  -> 0,292
    herz   Offset  4  Himmel  174  Varianz  70.3  -> 0,299

Alle vier zwischen 0,28 und 0,30; die ASI294 kam unabhaengig auf 0,270. Der Sockel folgt mit
rund 38 ADU je Offset-Schritt.

WAS HIER NICHT DRINSTEHT und darum auch nicht behauptet wird: das reine Ausleserauschen.
Dafuer braucht es Bias-Aufnahmen (kuerzeste Belichtung, Deckel drauf). Bei den gemessenen
Himmelspegeln liegt es unter der Nachweisgrenze — an `herz` (10 s, dunkelster Fall) waere fuer
reines Schrotrauschen eine Varianz von 75 zu erwarten, gemessen wurden 70,3. Es ist also
klein, und `ausleserauschen_e` unten ist eine SCHAETZUNG, kein Messwert.
"""

# Vollskala in Elektronen = 65535 * Gain[e-/ADU]. Das ist der Wert, mit dem das Training
# rechnet: er sagt, wieviele Photonen hinter einem Pixelwert von 1,0 stehen.
KAMERAS = [
    dict(name="ZWO ASI294MC Pro",
         gain_e_pro_adu=0.270, vollskala_e=17694,
         # An M51 gemessen: 120 s, Gain 120, -10 C, Himmel 9400 ADU, Rauschen 186,6 ADU.
         hotpixel_anteil=0.000071, zeilenrauschen_anteil=0.03,
         ausleserauschen_e=2.0, gemessen_an="M51, 120 s, Gain 120, -10 C"),
    dict(name="ZWO ASI533MC Pro",
         gain_e_pro_adu=0.281, vollskala_e=18415,
         # Deutlich mehr Hotpixel als die 294 — Faktor 20.
         hotpixel_anteil=0.001438, zeilenrauschen_anteil=0.00,
         ausleserauschen_e=2.0, gemessen_an="risi/m106, 60 s, Gain 95, -20 C"),
    dict(name="Seestar S30",
         gain_e_pro_adu=0.080, vollskala_e=5243,
         # Ungekuehlt (+20,7 C gemessen): mehr Dunkelstrom, entsprechend mehr Rauschen.
         hotpixel_anteil=0.000309, zeilenrauschen_anteil=0.00,
         ausleserauschen_e=3.0, gemessen_an="IC 434, 30 s, Gain 200, +20,7 C"),
]

# Streuung um die gemessenen Werte. Ein Modell, das NUR diese drei Kameras kennt, faellt bei
# der vierten um; ein Modell, das alles kennt, kann nichts richtig.
#
# WICHTIG, an echten Daten gelernt: die Werte oben sind am ROHEN Sensor gemessen. Training und
# Anwendung arbeiten aber am DEBAYERTEN Bild, und Debayering mittelt Nachbarpixel — das
# Rauschen sinkt dabei um Faktor 2 bis 3, was einer drei- bis zehnfach hoeheren effektiven
# Elektronenzahl entspricht. Dazu kommt, dass jemand auch schon gestapeltes Material
# nachbearbeitet; bei 100 Aufnahmen ist das Rauschen nochmal zehnfach kleiner.
#
# Ein erster Anlauf mit enger Streuung (Faktor 2,2, also 2383 bis 40513 Elektronen) hat genau
# das verfehlt: eine echte 120-Sekunden-Aufnahme der ASI294MC entspricht nach dem Debayern
# rund 96000 Elektronen. Das Modell hatte nie ein so ruhiges Bild gesehen, hielt es fuer
# bereits sauber und tat NICHTS — an kuenstlichem Rauschen 8,8-fache Minderung, an der echten
# Aufnahme 1,00-fach. Der Bereich muss nach OBEN weit offen sein.
VOLLSKALA_STREUUNG_UNTEN = 3.0      # verrauschter als gemessen (kurze Belichtung, warm)
VOLLSKALA_STREUUNG_OBEN = 30.0      # ruhiger als gemessen (Debayering, gestapeltes Material)
HOTPIXEL_STREUUNG = 3.0


def bereich():
    """(kleinste, groesste) Vollskala in Elektronen ueber alle Kameras samt Streuung.

    Zum Vergleich der alte, willkuerliche Bereich: 250 bis 125000 Elektronen, Faktor 500.
    Gemessen liegen die drei Kameras zwischen 5243 und 18415, also innerhalb eines Faktors
    von 3,5 — mit der Streuung wird daraus rund 1750 bis 552000. Nach oben weit offen, weil
    Debayering und Stapeln das Rauschen weiter senken; siehe die Erklaerung bei den Konstanten.
    """
    werte = [k["vollskala_e"] for k in KAMERAS]
    return min(werte) / VOLLSKALA_STREUUNG_UNTEN, max(werte) * VOLLSKALA_STREUUNG_OBEN


def als_text():
    zeilen = ["%-20s %8.0f e- Vollskala  %6.3f e-/ADU  %6.4f %% Hotpixel   (%s)"
              % (k["name"], k["vollskala_e"], k["gain_e_pro_adu"],
                 100 * k["hotpixel_anteil"], k["gemessen_an"]) for k in KAMERAS]
    lo, hi = bereich()
    zeilen.append("Bereich fuers Training: %.0f bis %.0f Elektronen Vollskala" % (lo, hi))
    return "\n".join(zeilen)


if __name__ == "__main__":
    print(als_text())
