# StackForge — User Guide

StackForge turns a **series of photos** into **one better image**: fully sharp (Macro),
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
python3 focus_stack_gui.py        # or double-click StackForge.app (macOS)
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
  **number of frames**. **📷 Read from photo (EXIF):** pick a photo → focal length, aperture,
  sensor and (if present) focus distance are filled in automatically. Perfect for A7V + 105mm macro.
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
- **Output:** linear 16-bit TIFF + 32-bit linear + optional FITS — ready for GraXpert/StarNet/PixInsight.

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
- **Shooting:** tripod, identical exposure. If shaky, set "Align" to shift/handheld.

---

## Keyboard control

The app is fully keyboard-operable — **F1** (or the ⌨ button top-right) shows the full list.
The most important: **⌘O** choose folder, **⌘↩** start automatic, **⌘⇧↩** start manually,
**⎋** stop / back to module selection, **⌘1–4** switch module, **⌘B** beginner/pro, **⌘E** edit
result, **⌘⇧A** analyse series, **⌘D** DOF calculator, **⌘] / ⌘[** wizard next/back.
*(On Windows/Linux ⌘ = Ctrl.)*

## Beginner vs. Pro mode

Toggle at the top right.

- **🌱 Beginner:** just choose a folder + **one big Automatic button**. The software picks the
  settings and explains **why** in the log.
- **🛠️ Pro:** full step-by-step wizard, all parameters manual, AI can be turned off.

---

## Edit, preview & export

After each run, in the result bar on the right:

- **Preview** + **before/after slider** (all modules).
- **🎚️ Edit** — built-in Camera-Raw editor: exposure/contrast/white balance, tone curve,
  per-color HSL, clarity, crop/rotate, histogram. (all modules)
- **✏️ Retouch** — brush sharp areas from single frames onto the result
  (focus stacking only: Macro + Hybrid Focus+Astro).
- **👻 Ghost map** — shows motion artefacts in focus stacking.
- **Export presets:** Instagram / WhatsApp / Web / 4K / Print.
- **Batch:** one stack per subfolder. **Watch folder:** stack automatically once new photos
  finish copying. (Macro, Astro, Long exposure)

EXIF (camera/lens/date) is carried over to all outputs.

---

## External tools

**Setup menu (⚙) → "External tools (optional)"** — enter the paths to **GraXpert**,
**StarNet++** and **Siril** here (or leave empty = auto-detect). Paths are remembered.

- **🌌 GraXpert** (result bar, sky modules): remove background/gradient. Found → one click +
  automatic re-import; otherwise reveal the file in the file manager.
- **⭐ StarNet++**: remove stars (starless). Needs 16-bit TIF — StackForge hands over the right
  file automatically.
- **Siril**: selectable as an alternative astro engine.

None of this is required — StackForge is self-contained.

---

## AI / Automatic

- The automatic mode runs **completely without AI** via a heuristic (no server, no download).
- Optionally an **OpenAI-compatible server** (llama.cpp / LM Studio / vLLM) **or a provider with
  an API key** (OpenAI / OpenRouter) — in the Setup menu.
- The AI only **advises and checks** (setting suggestions, quality control). It **never touches
  pixels** and invents nothing (faithful/non-generative).
- *Note:* a ChatGPT subscription is **not** an API key — that needs a separate (paid) API key.

---

## Command line (CLI)

The GUI calls `focus_cull_stack.py` — you can run it directly too:

```bash
# Macro automatic
python3 focus_cull_stack.py --input photos/ --auto

# Astro with field rotation, hot-pixel, drizzle, FITS
python3 focus_cull_stack.py --input lights/ --astro --astro-align rotate \
    --astro-cosmetic --astro-drizzle 2 --fits-out --dark darks/ --flat flats/

# Long exposure, smooth, 60% virtual exposure
python3 focus_cull_stack.py --input series/ --longexp --longexp-mode smooth --longexp-strength 60

# Hybrid Focus+Astro (one subfolder per position)
python3 focus_cull_stack.py --input positions/ --hybrid-fa

# Batch over several series (one stack per subfolder)
python3 focus_cull_stack.py --input series/ --batch --astro
```

`python3 focus_cull_stack.py --help` lists all options.

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
StackForge streams from disk automatically; lower `--ram-budget-gb` if needed.

**RAW before-preview missing in compare (non-macro).**
Some RAWs can't render a quick preview — JPG/TIFF always work.

**English interface.**
Setup menu → Language → "English" (applies on next start). Own translation: copy `lang/de.json`,
translate it, save as `lang/xx.json`.

See also the [German guide](GUIDE.de.md).
