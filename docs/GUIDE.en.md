# ForgePix — User Guide

ForgePix turns a **series of photos** into **one better image**: fully sharp (Macro),
low-noise (Astro), stitched (Mosaic), or with a long-exposure look (no ND filter). The
automatic mode makes sensible decisions and **explains them**. AI is optional — without a
server everything runs on a built-in heuristic.

> Quick start: open the app → **pick a module** → choose the folder with your photos → **Automatic**.

---

## Contents
1. [Install](#install)
2. [The four modules](#the-four-modules)
3. [Beginner vs. Pro mode](#beginner-vs-pro-mode)
4. [Edit, preview & export](#edit-preview--export)
5. [External tools (GraXpert, StarNet++, Siril)](#external-tools)
6. [AI / Automatic](#ai--automatic)
7. [Command line (CLI)](#command-line-cli)
8. [FAQ & troubleshooting](#faq--troubleshooting)

---

## Install

```bash
python3 -m pip install -r requirements.txt
python3 focus_stack_gui.py        # or double-click ForgePix.app (macOS)
```

Requires Python 3.9+. RAW via `rawpy`, FITS via `astropy` (optional). External tools
(GraXpert/StarNet++/Siril) are **not** required — only if you want to use them.

---

## The four modules

Pick a module on launch. Use **"◀ Modules"** (top left) to switch any time.

### 🔬 Macro / focus stacking
Several close-ups where focus moves **front to back** are merged into **one fully sharp image**.
Great for products, coins, insects, food.

- **Recommended count:** 10–40 (enough to cover everything sharp from front to back).
- **Shooting:** tripod, identical exposure, move focus in small steps.
- **Presets:** Products / Coins / Food set sensible starting values.
- **Merge methods:** `pyramid` (Laplacian, default — sharp, good for fine/soft subjects), `depthmap`
  (depth-map selection — hard depth edges), `average` (Method A — low noise), **`halofix`** (dual-output
  halo retouch — pyramid sharpness clamped to the source envelope, no halos), `wavelet` (à-trous detail).
  Helicon-style **Radius/Smoothing** sliders for depthmap/average.
- **Output:** sharp 16-bit image + optional Photoshop-layered TIFF for retouching.

**🔍 Focus tools** (Pro mode, "Selection" step):
- **Drop shaky/blurry frames automatically** — removes photos that are sharp *nowhere*
  (shake/misfocus), with reasons in the log. On by default in Automatic.
- **🔍 Analyse series** (shot analysis) — examines the focus series *before* stacking and shows
  e.g.: *"37 frames detected · focus range complete · frame 14 shaky · frame 21 outside the
  focus series"*. A status per frame (✓ usable / ♻️ redundant / ⚠️ shaky / ⤳ out of sequence).
  Plus the **stack optimizer**: how much sharpness coverage remains with fewer frames (e.g. 40 →
  99%, 30 → 98%, 20 → 95%). Button **🗺️ Focus map** colours each area by **which photo** the
  sharpest details come from (blue = early, red = late) — shows gaps at a glance.
- **📐 DOF calculator / focus-bracketing assistant** — enter sensor, focal length, aperture and
  magnification (e.g. 1:1) or distance → depth of field per frame, recommended **step size** and
  **number of frames**. **📷 Read from photo (EXIF)** *(built‑in — no exiftool needed)*: pick a
  photo → focal length, aperture, sensor and (if present) focus distance are filled in automatically
  (reads JPEG **and** RAW via `ExifRead`). Perfect for A7V + 105mm macro.
- **Stack confidence** — after each stack a score (0–100) with **real metrics**: focus range
  complete?, halos, ghosting, sharpness — not AI marketing, but measurements.

### 🌌 Astro
Many frames of the same sky area are aligned and **averaged** to **reduce noise**. Bad frames
are dropped automatically (with reasons).

- **Recommended count:** 20–100+ lights (more = less noise).
- **Calibration (optional):** darks 15–30, flats 15–30, bias 30+ (as folder or file).
- **Alignment:** *translation* (tracking mount) or *translation + field rotation* (Alt-Az
  mount without rotator).
- **Extras:** hot/cold-pixel correction, drizzle 2× (finer sampling), background/gradient
  removal, sub-grading (FWHM/star count/guiding/clouds/trails).
- **Pro techniques (Advanced panel):**
  - **Rejection:** `sigma` · `winsor` · **`linearfit`** (PixInsight-style per-pixel line fit — best with few subs).
  - **Stretch (preview):** `asinh` · `MTF` (AutoSTF) · **`GHS`** (Generalised Hyperbolic, parametric D/b/SP).
  - **TPS fine registration** — corrects residual field distortion (wide-angle/refractor) after the global align.
  - **True drizzle** — real variable-pixel reconstruction (pixfrac drop) instead of plain upscaling; needs
    drizzle 2× and dithered subs.
  - **Photometric color calibration (PCC/SPCC)** — real catalog color: **Siril SPCC** (plate-solve + Gaia DR3)
    → own **astroquery** Gaia path → **lite** (star-based, offline). Backend `auto/siril/gaia/lite`; optional
    OSC sensor name and narrowband mode. Siril needs network or its local Gaia catalog; otherwise it falls
    back gracefully. *(AI is deliberately not used here — PCC is a measurement, not a judgement.)*
- **Output:** linear 16-bit TIFF + 32-bit linear + optional FITS — ready for GraXpert/StarNet/PixInsight.
- **Faster & better (new):** registration runs **in parallel** across all cores; far-dithered
  frames are **recovered via a cluster bridge** instead of dropped. **Binning** (2×/3×) for more
  SNR + rounder stars; **auto-detect calibration** (dark/flat/bias subfolders); **combine multiple
  nights/sessions into one stack** („➕ Add night"); **switching palette recolors instantly**
  (no re-stacking); **live preview** while stacking.
- **✨ Enhance (one click):** sends the finished linear image through **GraXpert** (gradient removal
  + AI denoising) and reimports it automatically — the usual post-stack step, without switching tools.
  GraXpert is free (graxpert.com); if it isn't installed, ForgePix tells you where to get it and shows
  the finished linear file to open by hand. Paths under **Setup → External tools** (or auto-detected).
- **⭐ Starless workflow (with StarNet++):** the fully-automatic "pro path" — **separate the stars →
  boost the nebula (local contrast, gentle saturation) → add the stars cleanly back via screen blend**.
  Pulls out much more nebula structure without bloating stars. In **Beginner mode**, "✨ Enhance"
  does this automatically (if StarNet is present); in **Pro mode** via **Tools → Starless workflow**.
  StarNet++ is free (starnetastro.com).
  > **macOS note:** StarNet++ is usually *unsigned* — Gatekeeper blocks the first launch. Unblock it
  > once in Terminal: `xattr -dr com.apple.quarantine <StarNet-folder>` and `chmod +x <…>/starnet++`
  > (or System Settings → Privacy & Security → "Allow Anyway").

> **Dual-band / narrowband filter (Hα+OIII):** Set **Filter** to *Dual-band* (e.g. SVBony SV220,
> Optolong L-eXtreme) — or it's auto-detected from the FITS `FILTER` header. Hα and OIII are then
> cleanly **separated** and recombined. Pick a **palette**:
>
> - **HOO** — faithful: Hα red, OIII teal. The most honest rendition.
> - **SHO synthetic** — Hubble gold + blue; the missing **SII is synthesized from Hα** (there is no
>   real SII in a dual-band filter — deliberately "faked").
> - **SHO Foraxx** — dynamic: pure Hα stays **red**, Hα+OIII mixes go **gold**, pure OIII **blue**.
> - **Bicolor (Cannistra)** — the missing green channel is **computed** from Hα+OIII
>   (G = max(OIII, 0.5·Hα)) → warmer, more natural, less magenta, more neutral stars.
>
> Without a filter / broadband: leave it off (normal color calibration + green-cast removal).

### 🌗 Hybrid
Two special cases in one module (sub-mode chosen at the top of the group):

- **Mosaic (Moon/Sun):** stitch overlapping tiles into one large image.
  *Recommended:* 4–20+ tiles, ~30% overlap.
- **Focus + Astro:** per focus position, first **denoise** several frames (astro stack), then
  **focus-stack** (depth of field). Put one **subfolder** per position.
  *Recommended:* 5–15 frames per position, multiple positions.

### 📷 Long exposure
A long exposure from a burst **without an ND filter**. Four effects:

| Effect | Result | Recommended |
|---|---|---|
| **Smooth** (average) | silky water, soft clouds | 10–30 |
| **Light trails** (lighten) | car lights, star trails, fireworks | 30–300+ (gap-free) |
| **Declutter** (median) | passers-by/cars disappear | 8–20 |
| **Brighten** (additive) | brighten dark night scenes | 10–60 |

- **Virtual exposure time:** slider 0–100% — continuous between a sharp single frame (frozen)
  and full smoothing/trails. Like a shorter/longer shutter speed.
- **Suggest effect:** analyses the motion in the series and picks the matching effect.
- **Sigma-clipping:** for Smooth/Declutter — rejects outliers (birds, satellites, hot pixels, sparkle).
- **Freeze foreground (Sequator-style):** the bottom fraction stays sharp from a single frame while only
  the sky is long-exposed — against wind/drift blur on the ground.
- **Shooting:** tripod, identical exposure. If shaky, set "Align" to shift/handheld.

> **HDR (exposure brackets):** Exposure Fusion (default, halo-free) **or** radiance-map tonemapping
> (Debevec + Reinhard/Mantiuk/Drago) for a more dramatic local-contrast look; plus motion deghosting.

---

## Keyboard control

The app is fully keyboard-operable — **F1** (or the ⌨️ button top-right) shows the full list.
**Photo keys** (Lightroom-style, only when no text field is active): **Space** before/after ·
**← →** switch image in the film strip · **A** analyse series · **S** stack/automatic · **E** editor ·
**G** ghost map · **F** focus map · **R** retouch.
**Commands:** **⌘O** folder, **⌘↩** automatic, **⌘E** export, **⎋** stop/back, **⌘1–4** module,
**⌘B** beginner/pro, **⌘D** DOF calculator, **⌘] / ⌘[** wizard. *(Windows/Linux: ⌘ = Ctrl.)*
Tip: **drop a folder on the window** to load it and (in Pro macro) start the analysis right away.

## Beginner vs. Pro mode

Toggle at the top right.

- **🌱 Beginner:** just choose a folder + **one big Automatic button**. The software picks the
  settings and explains **why** in the log.
- **🛠️ Pro:** full step-by-step wizard, all parameters manual, AI can be turned off.

### Who can do what — and when is it worth it?

| Topic | 🌱 Beginner | 🛠️ Pro |
|---|---|---|
| **Operation** | drop a folder on the window → **done** (zero‑click) | step‑by‑step wizard with every control |
| **Module** | **auto‑guessed** (switchable) | chosen deliberately + fine‑tuned |
| **Settings** | software decides (heuristic), explains **why** | you set dip/abs/transform/detector/sharpen/… |
| **Culling** | automatic (shaky/structureless dropped) | thresholds adjustable, keep frames manually |
| **Editing** | Camera‑Raw editor available | + retouch, ghost map, layered export, 16‑bit |
| **AI (optional)** | off; automatic runs fully local | AI suggestion + **free‑text wish** + per‑frame QC |
| **Astro/Hybrid details** | sensible defaults | calibration, field rotation, sigma/drizzle, sub‑grading |
| **When useful?** | fast, many series, “just a good image” | tricky subjects, full control, reproducibility |

**Rule of thumb:** when in doubt, **Beginner** — the automatic is deliberately conservative and
explains its choices. Switch to **Pro** the moment you want to solve a specific problem (retouch
ghosting, filter astro subs by FWHM, force a desired look).

---

## Edit, preview & export

**Decision panel (right):** after each run you see the **stack-confidence score**, “**X of Y**
frames used”, the **findings** and — for the automatic — **“Why these settings?”** (subject &
rationale). Findings are **clickable** and jump straight to the matching view: *ghosting* → ghost
map, *halos* → retouch, *focus gaps* → focus map. Below are **quick-export chips**
(📷 Instagram · 🌐 Web · 🖨 Print) for one-click export.

After each run, in the result bar on the right:

- **Preview** + **before/after slider** (all modules).
- **🎚️ Edit** — built-in Camera-Raw editor: exposure/contrast/white balance, tone curve,
  per-color HSL, clarity, crop/rotate, histogram. (all modules)
  - **🎯 Auto-mask:** one click — adjustments affect only the subject (mid-tones); **stars and dark
    background stay protected** (ideal for astro & macro).
  - **🖌 Paint the mask by hand:** add/remove on the image — **+ pick up** (apply here) or
    **− protect** (remove here), soft edge. Keys: **B** brush on/off, **A/S** pick up/protect,
    **[ ]** brush size, **Backspace** clear mask.
- **✏️ Retouch** — brush sharp areas from single frames onto the result
  (focus stacking only: Macro + Hybrid Focus+Astro).
- **👻 Ghost map** — shows motion artefacts in focus stacking.
- **📦 Export** (or ⌘E) — a dialog where you choose **what** to export — targets (Web JPG /
  Instagram / WhatsApp / Web / 4K / Print as 16-bit TIFF), **output sharpening**, **JPG quality**,
  **Photoshop layered file** and lossless **16-bit TIFF**. For a single format, a **quick-export
  chip** in the panel does it without the dialog.
- **↩ Resume** — on the start screen, one click reopens your last used folder and module.
- **Batch:** one stack per subfolder. **Watch folder:** stack automatically once new photos
  finish copying. (Macro, Astro, Long exposure)

EXIF is **built‑in** and ships with the app — **no exiftool needed**: **reading** (DOF assistant,
AI context, module guessing) via `ExifRead`; **copying onto JPEG** via `piexif` (full EXIF); **TIFF**
gets core provenance (camera/model/date + a readable summary with focal/aperture/ISO/exposure) via
`tifffile` — pixel‑identical. Only the **full EXIF sub‑IFD** on TIFF (every individual tag) is left
to optional **`exiftool`**; it is preferred automatically when present.

---

## External tools

**Setup menu (⚙) → "External tools (optional)"** — enter the paths to **GraXpert**,
**StarNet++** and **Siril** here (or leave empty = auto-detect). Paths are remembered.

- **🌌 GraXpert** (result bar, sky modules): remove background/gradient. Found → one click +
  automatic re-import; otherwise reveal the file in the file manager.
- **⭐ StarNet++**: remove stars (starless). Needs 16-bit TIF — ForgePix hands over the right
  file automatically.
- **Siril**: selectable as an alternative astro engine.

None of this is required — ForgePix is self-contained.

---

## AI / Automatic

- The automatic mode runs **completely without AI** via a heuristic (no server, no download).
- Optionally an **OpenAI-compatible server** (llama.cpp / LM Studio / vLLM) **or a provider with
  an API key** (OpenAI / OpenRouter) — in the Setup menu.
- The AI only **advises and checks** (setting suggestions, quality control). It **never touches
  pixels** and invents nothing (faithful/non-generative).
- **Privacy — what is sent to the AI:** only a few downscaled **preview frames**, the measured
  **sharpness profile**, **EXIF basics** (focal length/aperture/exposure/ISO/lens), optionally the
  **focus/ghost map** and your **free‑text wish**. **No** original files, **no** GPS/location data.
  With a local server (llama.cpp / LM Studio / vLLM) **nothing** leaves your machine. The Setup
  menu shows this note as well.
- *Note:* a ChatGPT subscription is **not** an API key — that needs a separate (paid) API key.

---

## Command line (CLI)

The GUI calls `core/focus_cull_stack.py` — you can run it directly too:

```bash
# Macro automatic
python3 core/focus_cull_stack.py --input photos/ --auto

# Astro with field rotation, hot-pixel, drizzle, FITS
python3 core/focus_cull_stack.py --input lights/ --astro --astro-align rotate \
    --astro-cosmetic --astro-drizzle 2 --fits-out --dark darks/ --flat flats/

# Astro, pro: linear-fit rejection, GHS stretch, TPS, true drizzle, real PCC
python3 core/focus_cull_stack.py --input lights/ --astro --astro-method linearfit \
    --astro-stretch --astro-stretch-mode ghs --astro-ghs-d 2.5 --astro-ghs-b -0.6 \
    --astro-tps --astro-drizzle 2 --astro-drizzle-true --astro-pixfrac 0.7 \
    --astro-pcc --astro-pcc-backend auto

# Focus: halo-retouch merge with Helicon radius/smoothing
python3 core/focus_cull_stack.py --input photos/ --focus-method halofix \
    --focus-radius 6 --focus-smoothing 3

# RAW with lens corrections (lensfun auto, or manual)
python3 core/focus_cull_stack.py --input raws/ --lens-auto   # or --lens-vignette 0.3 --lens-distortion -0.1

# HDR radiance tonemapping; long exposure with sigma-clip + freeze foreground
python3 core/focus_cull_stack.py --input brackets/ --hdr --hdr-method radiance --hdr-tonemap mantiuk
python3 core/focus_cull_stack.py --input series/ --longexp --longexp-mode smooth \
    --longexp-sigma --longexp-freeze 0.6

# Hybrid Focus+Astro (one subfolder per position)
python3 core/focus_cull_stack.py --input positions/ --hybrid-fa

# Batch over several series (one stack per subfolder)
python3 core/focus_cull_stack.py --input series/ --batch --astro
```

`python3 core/focus_cull_stack.py --help` lists all options.

---

## FAQ & troubleshooting

**The macro result isn't fully sharp.**
Take more frames with smaller focus steps. In Pro mode set "Alignment" to homography if the
camera drifted slightly.

**Water looks "stepped" (long exposure).**
Use more frames (10–30+). Set virtual exposure to 100%.

**Astro stars are elongated/double.**
On an Alt-Az mount choose "translation + field rotation". Let bad subs be dropped.

**Very large stack / little RAM.**
ForgePix streams from disk automatically; lower `--ram-budget-gb` if needed.

**RAW before-preview missing in compare (non-macro).**
Some RAWs can't render a quick preview — JPG/TIFF always work.

**English interface.**
Setup menu → Language → "English" (applies on next start). Own translation: copy `lang/de.json`,
translate it, save as `lang/xx.json`.

See also the [German guide](GUIDE.de.md).
