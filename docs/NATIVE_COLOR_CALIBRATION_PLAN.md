# Eigene kataloggestützte Farbkalibrierung: nächster Ausbau

Stand 06.09.2026 · P0-Diagnosebasis implementiert; PCC/SPCC weiterhin Entwurf, nicht qualifiziert.

Das separate Gaia/GSPC-Feldformat mit verlustfreien IDs, Eigenbewegung und
Qualitätsmerkmalen sowie native Aperturmessungen stehen jetzt über die CLI zur
Verfügung. Sie schreiben ausschließlich Diagnoseberichte. Bedienung und Grenzen:
[NATIVE_PHOTOMETRY.md](NATIVE_PHOTOMETRY.md). Die folgenden Farbfit-/SPCC-Schritte
sind weiterhin nicht implementiert oder freigegeben. Die Beschreibung des alten
Positionskatalogs bleibt für dessen eigenes, getrenntes NPZ-Format gültig.

**Priorität: ein überprüfbarer empirischer Breitband-PCC nach dem nativen Solver.** Anschließend folgt eine spektrale Vorhersage mit belegten Instrumentkurven. Dafür ist kein KI-Training erforderlich. Produktgleichheit mit Siril/PixInsight wird daraus nicht abgeleitet.

## 1. Kleinster sinnvoller Umsetzungsschritt

Der aktuelle ForgePix-Katalog enthält RA/Dec, Gaia-G und BP−RP; es fehlen insbesondere stabile Stern-IDs, Messfehler und spektrale Daten. G ist kein Kamera-Grünkanal. Zwei Katalogwerte bestimmen weder das vollständige Spektrum noch die drei gemessenen Sensorflüsse. Die vorhandenen Equipment-Namen und Filterbandbreiten ersetzen keine Antwortkurven. Siril unterscheidet ebenfalls kataloggestützten PCC von SPCC und nennt Filterabhängigkeiten des PCC ausdrücklich. [Siril PCC](https://siril.readthedocs.io/en/stable/processing/color-calibration/pcc.html)

**P0 – Photometrie und Katalogvertrag:** Neues, separat versioniertes Feldauszugformat; bisherige NPZ bleiben Positionskataloge. Zusätzlich `source_id` als verlustfreies int64, `ref_epoch`, `pmra`, `pmdec`, Unsicherheiten und Qualitätsmerkmale aus `gaiadr3.gaia_source`. Über `source_id` die Tabelle `gaiadr3.synthetic_photometry_gspc` verbinden: `b_jkc_mag`, `v_jkc_mag`, `r_jkc_mag`, zugehörige `*_flux_error`/`*_flux`/`*_flag` und `c_star`. Diese standardisierten Johnson-Kron-Cousins-Werte sind keine Kamera-RGB-Flüsse; fehlende/außerhalb validierter Bereiche liegende Bänder ausschließen. [ESA GSPC-Datenmodell](https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_performance_verification/ssec_dm_synthetic_photometry_gspc.html)

Katalogpositionen zur dokumentierten Aufnahmeepoche fortschreiben, einschließlich des bereits in `pmra` enthaltenen cos(Dec)-Faktors. Fehlende Bewegung/Epoche kenntlich machen und unsichere Zuordnungen ausschließen. Eine Montage über mehrere Epochen benötigt dokumentierte Zeitbehandlung. [Astropy Raumbewegung](https://docs.astropy.org/en/stable/coordinates/apply_space_motion.html)

**P1 – Empirischer PCC:** Ausschließlich registriertes, lineares Breitband-RGB ohne KI-Veränderung, Stretch, Sternentfernung oder selektiven Mehrbandfilter. Native Aperturphotometrie mit lokalem Hintergrund, Nachbarmasken, Sättigungsprüfung und gemeinsamer gültiger Coverage; positive Stern-Nettoflüsse samt Unsicherheit messen. Bei unterschiedlichen PSFs ausreichend große gemeinsame Aperturen und eine geprüfte Aperturkorrektur verwenden.

Robust und fehlergewichtet fitten: instrumentell `−2,5 log10(F_R/F_G)` gegen katalogseitig `R−V`, entsprechend `B/G` gegen `B−V`. Lineare Farbterme beschreiben die jeweilige Messserie; sie sind keine universelle Kamera-Spektralkurve. An einer ausdrücklich dokumentierten Referenzfarbe innerhalb des gemessenen Farbbereichs zwei positive Kanalverstärkungen ableiten; G bleibt Referenz. Das liefert einen **empirischen photometrischen Weißabgleich**, keine absolute Flusskalibrierung und keine allgemeine Transformation nach sRGB. Magnitudensystem und Nullpunkte ausdrücklich speichern; Vega, AB und ST sind nicht austauschbar. [Astropy Magnituden](https://docs.astropy.org/en/stable/units/logarithmic_units.html)

Neues Float-FITS plus Bericht: Eingabe-/Kataloghashes, Stern-IDs, Aperturen, Ausschlussgründe, Fit-/Prüfaufteilung, Farbterme, Referenz und Verstärkungen. Signierte/HDR-Werte erhalten, keine Begrenzung auf 0…1; fehlende Pixel bleiben fehlend. WCS und Coverage mitführen. Globale Hintergrundneutralisierung ist ein gesonderter, protokollierter Schritt.

## 2. Danach: echte instrumentbezogene SPCC

Für Stern *i*, Kanal *c* gilt bei konsistenten Einheiten:

`E[i,c] = t[c] · A · ∫ Fλ[i] · QE[c] · T_Filter[c] · T_Optik · T_Atmosphäre · λ/(h·c₀) dλ`

Das Ergebnis sind erwartete Elektronen. Gain, Belichtungszeit und tatsächliche Stack-Normierung verbinden es mit Bildwerten. Bei bereits kombinierter OSC-Kanalantwort die CFA-Transmission nicht doppelt multiplizieren. Der Faktor λ/(hc₀) ist für Photonenzählung wesentlich. [STScI/synphot Formeln](https://synphot.readthedocs.io/en/latest/synphot/formulae.html)

Benötigt werden `source_id`, `solution_id`, `flux`, `flux_error` aus Gaia `XP_SAMPLED` über DataLink: 343 Samples, 336–1020 nm, 2-nm-Abstand, W m⁻² nm⁻¹. Das ist kein normaler TAP-Tabellendownload. Alternativ später kontinuierliche XP-Koeffizienten samt Kalibrationsmodell und Kovarianzen. Sample-Abstand ist keine spektrale Auflösung; korrelierte Fehler nicht als unabhängige Samples behandeln. [ESA XP-Datenmodell](https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_spectroscopic_tables/ssec_dm_xp_sampled_mean_spectrum.html)

Jedes Instrumentprofil braucht eine versionierte ID, numerische Wellenlängen/Einheiten, Herkunft, Messunsicherheit und Nutzungsrechte: OSC-QE je R/G/B beziehungsweise Mono-QE plus echte RGB-Filter, Sperrfilter/Fenster, Optik/Reducer und Atmosphärenmodell. Kameramodell und maximale QE genügen nicht. Fehlende spektrale Abdeckung nicht still extrapolieren. Weißreferenz als versioniertes Spektrum; Atmosphärenkorrektur nur mit dokumentierten Annahmen zu Luftmasse/Extinktion. Sirils Ansatz belegt diese Datenabhängigkeit, ersetzt aber keine eigene Validierung. [Siril SPCC](https://siril.readthedocs.io/en/stable/processing/color-calibration/spcc.html)

**SII/OIII separat:** Das Profil `sv220_sii_oiii_7` erlaubt keinen Hα-Kanal. Zwei Linienkomponenten plus Sternkontinuum lassen sich aus beliebigen OSC-Kanälen nicht voraussetzungslos trennen. Zuerst genaue Filtervariante, gemessene Transmission samt f/Verhältnis-/Winkelabhängigkeit und Sensorantwort belegen. Gaia-XP allein qualifiziert keine 7-nm-Linienphotometrie. Später hochauflösende Referenzspektren und kontrollierte Linienmessungen verwenden; bis dahin nur benannte SII/OIII-Darstellung, keine Breitband-PCC-Freigabe, kein erfundenes Hα/SHO und keine behaupteten absoluten Nebellinienverhältnisse.

## 3. Vorher festgelegte Freigabe und Prüfdaten

Vorgeschlagene erste Gates, noch **nicht erreicht**: ≥60 isolierte Sterne, ≥20 davon unverändert zurückgehalten, alle vier Bildquadranten, genügende Farbspanne um die Referenz; Netto-S/N≥30 je Kanal. Auf Prüf-Sternen je Farbbeziehung Medianbias ≤0,03 mag, P95-Absolutresiduum ≤0,10 mag; Bootstrap-Unsicherheit der Verstärkungen ≤5 %. Fehlende Linearitäts-/Sättigungsinformation oder unzureichender Konsens ergibt einen nachvollziehbaren Abbruch, keine automatische Ersatzfarbe.

Zunächst analytische Apertur-/Einheitentests und simulierte bekannte Verstärkungen; anschließend neue kalibrierte FITS-Serien aus mindestens zwei OSC-Sensorfamilien und einem Mono-RGB-Aufbau, mehreren Sternfarben, zwei Nächten und verschiedenen Luftmassen. Serien/Instrumente zur Prüfung vor Parameterwahl reservieren. Für den eigenen SII/OIII-Aufbau zusätzlich dasselbe Feld in echtem Breitband aufnehmen. Aktuelle M27-Solver-Evidenz ersetzt diesen Farbtest nicht.

CALSPEC-Spektren mit festgehaltenen Dateiversionen können später einen getrennten hochauflösenden Integrationsvergleich gegen synphot ermöglichen. Gaia und CALSPEC teilen jedoch Teile ihrer absoluten Kalibrationsbasis; neue terrestrische Messungen bleiben nötig. [STScI Referenzatlanten](https://stdatu.stsci.edu/hlsp/reference-atlases)

**Rechte/Datenbeschaffung:** Kleine Feldauszüge nach Bedarf; keine pauschalen Trainingsdownloads. Gaia mit Release-/ESA/Gaia/DPAC-Nachweis und gespeicherten Datenbedingungen; die aktuelle [ESA-Lizenzseite](https://www.cosmos.esa.int/web/gaia-users/license) war hier mit HTTP 451 nicht verifizierbar, deshalb keine CC0-/uneingeschränkte Weitergabe behaupten. Für mitgelieferte Kurven und Referenzspektren Rechte je Produkt dokumentieren. [MAST-Datennutzung](https://stdatu.stsci.edu/publishing/data-use) unterscheidet öffentliche Daten und gesondert lizenzierte Produkte. [GaiaXPy](https://github.com/gaia-dpci/GaiaXPy/blob/main/LICENSE) ist BSD-3-Clause und eignet sich als unabhängiges Prüfwerkzeug; eigene Integration bleibt möglich. „Gratis“ ersetzt keine Daten- oder Softwarelizenzprüfung.

**Nächster Auftrag:** P0-Diagnosen breiter prüfen, anschließend P1 hinter den festen Gates und eine geführte Oberfläche. Kein automatischer PCC-Farbauftrag für den vorhandenen SII/OIII-Datensatz. In der ursprünglichen Entwurfsrunde wurden keine weiteren Astronomiedaten geladen und kein Runtimecode geändert; der anschließende P0-Ausbau ist separat im RELEASE_WORKLOG dokumentiert.
