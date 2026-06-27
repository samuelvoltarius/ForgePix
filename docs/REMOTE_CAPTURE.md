# Remote Capture — Concept Note

*[🇩🇪 Deutsche Version](REMOTE_CAPTURE.de.md)*

> **Status: future / parked idea.** This is a design sketch to capture the concept, not a committed
> feature. The hard part (a camera SDK for triggering/focusing) is a large undertaking.

## The idea

Today ForgePix processes photos **after** they were shot. The vision: ForgePix also **drives the
capture** — it triggers the series, steps the focus, and stacks while you watch — and you control all
of it **from a phone or tablet**, standing right at the rig.

## Architecture

```
   Camera (e.g. Sony A7 V) ──USB──► [ ForgePix capture server ]
                                    (Mac Mini / laptop / Raspberry Pi at the rig)
                                    · drives the camera (trigger, focus steps)
                                    · grades + aligns + stacks live
                                          │
                                          │  local WLAN / LAN
                                          ▼
                                    [ Phone / Tablet — browser only ]
                                    · live view  · "Shoot series"
                                    · focus map builds up live  · save/export
```

The phone is **just a web browser**. It can't run a camera SDK itself (that needs a USB host + a
desktop SDK), but as a thin remote control for a server it is perfect — and arguably nicer than a
heavy desktop app: camera on the rig device, phone in hand, done.

## Connecting the phone — local network + QR code (no account, no VPN)

For the common case (you're at the rig, everything on the same network) plain **local WLAN/LAN** beats
a VPN. Flow:

1. The server starts and shows a **QR code** (on its screen or in the terminal).
2. The QR encodes the local URL, e.g. `http://forgepix.local:8080/?token=ab12cd`
   (mDNS/Bonjour name `forgepix.local` so it survives changing DHCP IPs).
3. You **scan it with the phone camera** → the browser opens → connected. No typing, no IP hunting.

The **one-time token** in the URL means only someone who can physically see the screen can connect —
simple security on an open WLAN, without a login.

This is the pattern good local tools use (Pi-hole, OctoPrint, Home Assistant onboarding, Syncthing).
**Tailscale stays optional** for the special case of controlling the rig **from somewhere else** (server
at home, you're away). The server can listen on both at once.

## The hard part: the camera SDK

There is **no single protocol that works well with every camera**:

| Path | Coverage | Catch |
|---|---|---|
| **Sony Camera Remote SDK** | Sony only (incl. A7 V) | official, can control focus — but Sony-only |
| Canon EDSDK / Nikon SDK | one brand each | separate integration per brand |
| **gPhoto2 / libgphoto2** | many brands (PTP/USB) | open-source, closest to "everything" — but quality varies per model, newest bodies (A7 V) often lag |

**Realistic first step:** the **Sony SDK for the A7 V** (the camera on hand, officially supported,
focus control possible). Broad multi-brand support via gPhoto2 can come later.

## Phased roadmap (rough)

1. **Server skeleton** — a small local web server + a phone-friendly web UI; live preview from a
   tethered live-view stream; QR + mDNS connect.
2. **Trigger only** — fire a series via the Sony SDK (no focus control yet); pull frames; stack with the
   existing engine; show the focus map building live.
3. **Focus stepping** — drive the focus from near to far (the actual focus-bracket); the live focus map
   shows coverage as it fills in.
4. **Modes** — focus stacking, then exposure brackets (HDR), then **lucky imaging from video** (sun/moon
   — see below).
5. **Polish** — one-time token, multiple cameras, gPhoto2 for other brands.

## Related: "Sun/Moon from video" (lucky imaging)

A separate but related module (`core/lucky.py`) stacks the **sharpest frames out of a video** (the
AutoStakkert principle) — ForgePix decodes the video itself (OpenCV), grades frames by sharpness,
aligns the disc and averages the best, then sharpens. Live capture would feed this directly: shoot a
solar/lunar video tethered, stack the best frames on the server, see the result on the phone.

---

*Captured so the idea isn't lost. Nothing here is scheduled yet.*
