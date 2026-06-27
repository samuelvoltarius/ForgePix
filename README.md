# ForgePix ⚡

### [forgepix.app](https://forgepix.app) · Focus • Astro • Long Exposure

*[🇩🇪 Deutsche Version](README.de.md)*

![tests](https://github.com/samuelvoltarius/ForgePix/actions/workflows/tests.yml/badge.svg)
[![release](https://img.shields.io/github/v/release/samuelvoltarius/ForgePix?include_prereleases)](https://github.com/samuelvoltarius/ForgePix/releases)
[![license: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> **ForgePix Beta** — automatic focus stacking and computational photography for **macro, astro
> and long‑exposure** series. **Local‑first, AI optional.** It’s usable and tested, but young —
> expect the occasional rough edge and please [report issues](https://github.com/samuelvoltarius/ForgePix/issues).

**Focus Stacking + Astro + Long Exposure.** Drop your photos in, get a finished image out — in
the best possible quality for further editing. Self‑contained, free (MIT), cross‑platform
(Windows / macOS / Linux).

## Why ForgePix?

> - ✓ **Analyses focus series**
> - ✓ **Removes rejects automatically**
> - ✓ **Computes the optimal frame count**
> - ✓ **Long exposure without an ND filter**
> - ✓ **Astro + macro in one app**
> - ✓ **Works without AI** (fully local, no server)

## How it works

A soft focus series becomes one fully sharp image — and you see *what* happens at every step:

| 1 · Input (series) | 2 · Analysis | 3 · Focus map | 4 · Result |
|---|---|---|---|
| ![Input](assets/shots/p1_input.jpg) | ![Analysis](assets/shots/p2_analyse.png) | ![Focus map](assets/shots/05_focusmap.png) | ![Result](assets/shots/p4_result.jpg) |
| *9 frames, each only partly sharp* | *shaky dropped, optimal frame count* | *which area from which photo* | *fully sharp, ready to edit* |

📖 **Full guide:** [docs/GUIDE.en.md](docs/GUIDE.en.md) · *[🇩🇪 Anleitung](docs/GUIDE.de.md)*

| Start screen | Macro module |
|---|---|
| ![Start](assets/shots/01_start.png) | ![Macro](assets/shots/02_makro.png) |
| **Camera‑Raw editor** | **Astro module** |
| ![Editor](assets/shots/04_editor.png) | ![Astro](assets/shots/03_astro.png) |

## Highlights

*(Short version — the [full guide](docs/GUIDE.en.md) has every option.)*

- **One‑click Automatic** (Beginner & Pro) — picks the usable frames, aligns, merges to a
  fully‑sharp image, sharpens gently. In Beginner mode just **drop a folder**: ForgePix guesses the
  module (file types / names / EXIF sample) and runs. In → done.
- **Four modules, one app:** 🔬 **Macro** (focus stacking, Product/Coin/Food presets),
  🌌 **Astro** (star stacking), 🌗 **Hybrid** (Moon/Sun **mosaic** + **Focus+Astro**) and
  📷 **Long exposure** (no ND filter — silky water/clouds, trails, **virtual exposure‑time** slider).
- **Own engine** (OpenCV/NumPy) — no external stacking software. Large stacks are streamed
  (memory‑friendly); RAW development & sharpness analysis run across **all CPU cores** (cached).
- **Focus tools** (macro): series & **focus‑map** analysis, **DOF/bracketing assistant** with EXIF
  read‑out, **stack‑confidence score**, and a **decision panel** with clickable findings and a
  **“why these settings?”** rationale.
- **Astro:** auto‑detected **calibration** (darks/flats/bias), star alignment (translation or field
  rotation) plus **TPS local registration** (field‑curvature fix), hot/cold‑pixel fix,
  **sigma / winsor / linear‑fit rejection**, **drizzle‑lite *and* true drizzle** (pixfrac drop),
  **binning**, **multi‑session** stacking, **asinh / MTF / GHS** stretch, **real photometric color
  calibration (PCC/SPCC)** via Siril (Gaia DR3) or an own astroquery path (lite fallback always works),
  explainable sub‑grading, **32‑bit linear + FITS** export, **live preview** while stacking, and
  **automatic GraXpert/StarNet++**. Dual‑band (Hα/OIII) with **HOO / synthetic SHO / Foraxx / Bicolor**.
- **Focus merge methods:** Laplacian **pyramid**, **depth‑map**, weighted **average** (Method A),
  à‑trous **wavelet**, and **halofix** (dual‑output halo retouch) — with Helicon‑style **Radius/Smoothing**.
- **HDR & long exposure:** Exposure Fusion **or radiance‑map tonemapping**; deghosting; comet/trail
  gap‑fill; **sigma‑clipping** and **freeze‑foreground** (Sequator‑style).
- **Built‑in editors:** Camera‑Raw (exposure, **tone curve**, per‑color **HSL**, **lens corrections**
  — lensfun auto or manual vignette/distortion/CA, crop/rotate, histogram, mask brush) and a
  **retouch** brush over halos/**ghosting**.
- **RAW** faithfully developed to 16‑bit (DHT/DCB/VNG/AHD, AMaZE where available); EXIF/provenance preserved.
- **Export & workflow:** before/after slider, film strip, **ghost map/deghost**, export presets
  (Instagram/WhatsApp/Web/4K/Print), **batch** & **watch folder**, quick‑export chips, resume last folder.
- **Fully keyboard‑operable**, **German & English** UI, **AI strictly optional** (local or API).

## Runs everywhere — AI is optional

Automatic works **completely without AI** (settings derived from the measured sharpness
profile). **No Ollama, no server, no model download.** Optionally connect an OpenAI‑compatible
server (llama.cpp / LM Studio / vLLM) **or a provider with API key** (OpenAI / OpenRouter).
The AI only **advises & checks** — it never touches pixels. *“The software explains why it
chose these settings.”* You can add a **free‑text wish** (e.g. “silky water, people sharp”) and the
suggestion also gets **EXIF basics** + the **focus map**. Setup states exactly what is sent — a few
preview frames, the sharpness profile, EXIF basics and your wish; no original files, no location data.

Pros can optionally **connect Siril** (if installed) — used both as an alternative astro engine and
for **real photometric color calibration** (plate‑solve + Gaia DR3 SPCC) — and hand off to
**GraXpert / StarNet++**. None of it is required: without Siril/network, PCC falls back to the
built‑in star‑based calibration.

## Download (prebuilt)

Ready‑made packages for **macOS · Windows · Linux** are on the
[**Releases page**](https://github.com/samuelvoltarius/ForgePix/releases) (no Python needed):

- **macOS:** `ForgePix-macOS.zip` → unzip, open `ForgePix.app`.
- **Windows:** `ForgePix-Windows.zip` → unzip, run `ForgePix.exe`.
- **Linux:** `ForgePix-Linux.tar.gz` → extract, run `./ForgePix/ForgePix`.

> First launch on macOS/Windows: right‑click → “Open” (the app isn’t notarised yet —
> [enable signing](docs/SIGNING.md)).

## From source

```bash
python3 -m pip install -r requirements.txt
python3 focus_stack_gui.py
```

- **macOS:** double‑click `ForgePix.app` (optional `exiftool` for EXIF copy).
- **Windows:** `run.bat`  ·  **Linux:** `./run.sh`

## First steps

1. Open the app → **pick a module** (Macro / Astro / Hybrid / Long exposure).
2. **🌱 Beginner** (default): pick a folder (or drag it onto the window) → **⚡ Start**. Done.
3. **🛠️ Pro:** guided wizard with all controls, AI server, external tools, etc.

> Every setting has a **?** with a plain‑language explanation. The recommended frame count per
> module is shown right in its group — details in the [guide](docs/GUIDE.en.md).

## Sample data to try

Curated test datasets (good **and** deliberately bad frames) are a
[**sample download**](https://github.com/samuelvoltarius/ForgePix/releases/tag/samples-v1):
astro subs (M 42 / IC 5146, Bayer FITS), a landscape RAW and a macro focus series — just drop the
folder onto the window.

## External tools (optional)

In the **Setup menu (⚙) → "External tools"** you set paths to **GraXpert**, **StarNet++** and
**Siril** (or leave empty = auto‑detect). For Astro/Long‑exposure/Hybrid you can then send the
result through GraXpert (gradient) or StarNet++ (starless) with **one click** — including
automatic re‑import. None of it is required.

## Languages

German & English built in (switch top‑right, applies on restart). Add your own language:
copy `lang/de.json`, translate the values, save as e.g. `lang/fr.json` — it appears in the
language menu automatically.

## Keyboard shortcuts

**Photo keys** (Lightroom-style): **Space** before/after · **← →** switch image · **A** analyse ·
**S** stack · **E** editor · **G** ghost map · **F** focus map · **R** retouch.
**Commands:** ⌘O folder · ⌘↩ automatic · ⌘E export · ⎋ stop/back · ⌘1–4 modules · ⌘B beginner/pro ·
⌘D DOF · **F1** = full overview. *Dropping a folder on the window starts the analysis.*

## Tests

```bash
./run_tests.sh        # or: python3 -m unittest discover -s tests
```

Engine tests (standard library, no pytest needed) cover focus analysis, long exposure, astro
(registration, palettes, binning, calibration), stacker, mosaic, export, parallel helper, module
guessing, AI context, i18n completeness (incl. an unwrapped‑string guard) and a GUI smoke test.

## License

MIT (see `LICENSE`). Built only on permissive components: OpenCV, NumPy, rawpy, tifffile,
psdtags, PySide6 (LGPL). Astro methods inspired by [Siril](https://siril.org) (re‑implemented,
no GPL code copied).
