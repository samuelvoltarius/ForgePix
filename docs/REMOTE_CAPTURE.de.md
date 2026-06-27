# Fernsteuerung der Aufnahme — Konzept-Notiz

*[🇬🇧 English version](REMOTE_CAPTURE.md)*

> **Status: Zukunft / geparkte Idee.** Eine Design-Skizze, um die Idee festzuhalten — kein zugesagtes
> Feature. Der harte Teil (ein Kamera-SDK zum Auslösen/Fokussieren) ist ein großes Vorhaben.

## Die Idee

Heute verarbeitet ForgePix Fotos **nach** der Aufnahme. Die Vision: ForgePix **steuert auch die
Aufnahme** — löst die Reihe aus, zieht den Fokus durch und stackt live mit — und du bedienst alles
**vom Handy oder Tablet**, direkt am Rig.

## Architektur

```
   Kamera (z. B. Sony A7 V) ──USB──► [ ForgePix Capture-Server ]
                                     (Mac Mini / Laptop / Raspberry Pi am Rig)
                                     · steuert die Kamera (Auslöser, Fokusschritte)
                                     · bewertet + richtet aus + stackt live
                                           │
                                           │  lokales WLAN / LAN
                                           ▼
                                     [ Handy / Tablet — nur Browser ]
                                     · Live-View  · „Reihe aufnehmen"
                                     · Fokus-Map baut sich live auf  · speichern/exportieren
```

Das Handy ist **nur ein Browser**. Es kann selbst kein Kamera-SDK fahren (braucht USB-Host + Desktop-
SDK), aber als schlanke Fernbedienung für einen Server ist es perfekt — und schöner als eine fette
Desktop-App: Kamera ans Rig-Gerät, Handy in die Hand, fertig.

## Verbindung — lokales Netz + QR-Code (kein Konto, kein VPN)

Für den Normalfall (du stehst am Rig, alles im selben Netz) schlägt **lokales WLAN/LAN** ein VPN. Ablauf:

1. Der Server startet und zeigt einen **QR-Code** (auf dem Bildschirm oder im Terminal).
2. Der QR enthält die lokale Adresse, z. B. `http://forgepix.local:8080/?token=ab12cd`
   (mDNS/Bonjour-Name `forgepix.local`, übersteht wechselnde DHCP-IPs).
3. Du **scannst ihn mit der Handy-Kamera** → der Browser öffnet → verbunden. Kein Tippen, keine IP-Suche.

Der **Einmal-Token** in der URL heißt: nur wer den Bildschirm physisch sieht, kann sich verbinden —
simple Sicherheit auf offenem WLAN, ohne Login.

Genau das Muster nutzen gute lokale Tools (Pi-hole, OctoPrint, Home-Assistant-Onboarding, Syncthing).
**Tailscale bleibt optional** für den Sonderfall, das Rig **von woanders** zu steuern (Server zuhause,
du bist unterwegs). Der Server kann auf beidem gleichzeitig lauschen.

## Der harte Teil: das Kamera-SDK

Es gibt **kein Protokoll, das mit jeder Kamera gut geht**:

| Weg | Abdeckung | Haken |
|---|---|---|
| **Sony Camera Remote SDK** | nur Sony (inkl. A7 V) | offiziell, kann Fokus steuern — aber Sony-only |
| Canon EDSDK / Nikon SDK | je 1 Marke | pro Marke eigene Integration |
| **gPhoto2 / libgphoto2** | viele Marken (PTP/USB) | open-source, am nächsten an „alles" — aber Qualität je Modell schwankt, neue Bodies (A7 V) hinken oft hinterher |

**Realistischer erster Schritt:** das **Sony-SDK für die A7 V** (vorhandene Kamera, offiziell unterstützt,
Fokussteuerung möglich). Breite Multi-Marken-Abdeckung per gPhoto2 später.

## Phasen-Fahrplan (grob)

1. **Server-Gerüst** — kleiner lokaler Webserver + handyfreundliche Web-UI; Live-Vorschau aus dem
   Tethered-Live-View; QR + mDNS-Verbindung.
2. **Nur Auslösen** — eine Reihe per Sony-SDK auslösen (noch keine Fokussteuerung); Frames holen; mit
   der vorhandenen Engine stacken; Fokus-Map live wachsen lassen.
3. **Fokus-Schritte** — Fokus von vorne nach hinten durchziehen (das eigentliche Fokus-Bracketing); die
   Live-Fokus-Map zeigt die Abdeckung, während sie sich füllt.
4. **Modi** — Fokus-Stacking, dann Belichtungsreihen (HDR), dann **Lucky Imaging aus Video** (Sonne/Mond).
5. **Feinschliff** — Einmal-Token, mehrere Kameras, gPhoto2 für andere Marken.

## Verwandt: „Sonne/Mond aus Video" (Lucky Imaging)

Ein verwandtes Modul (`core/lucky.py`) stapelt die **schärfsten Frames aus einem Video** (AutoStakkert-
Prinzip) — ForgePix dekodiert das Video selbst (OpenCV). Live-Aufnahme würde das direkt speisen: Sonnen-/
Mond-Video tethered aufnehmen, die besten Frames am Server stacken, das Ergebnis am Handy sehen.

---

*Festgehalten, damit die Idee nicht verloren geht. Nichts davon ist terminiert.*
