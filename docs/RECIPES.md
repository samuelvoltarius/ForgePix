# Native AI recipes, version 1

A recipe stores an ordered sequence of ForgePix's own local AI operations. It
can be saved once and run on another linear FITS or TIFF. This first version
supports background correction, denoising, deblurring and star removal. It does
not record arbitrary GUI actions, execute Python/shell scripts, run external
programs, calibrate raw frames, or reproduce a full processing graph.

All current model steps require explicit experimental consent for each run.
Saving or loading a recipe never starts processing and never grants that
consent. A repeatable file workflow is not evidence that model estimates are
scientifically validated or camera independent.

## Recipe format

The UTF-8 JSON object has exactly four fields:

```json
{
  "format": "ForgePixRecipe",
  "schema_version": 1,
  "name": "Background and noise",
  "steps": [
    {
      "task": "background",
      "model_id": "forgepix-background-mono-v2",
      "model_sha256": "<exact 64-character SHA256 of the local ONNX file>",
      "strength": 0.5,
      "device": "auto"
    }
  ]
}
```

The hash placeholder above must be replaced with a real hash. `pin_step()`
builds a valid step from a locally verified model. A recipe accepts 1–32 steps;
the allowed tasks are `denoise`, `background`, `deblur`, `starless`. The exact
model ID, task and SHA256 must match. Updating a model requires explicitly
updating the recipe; a replacement is never silently selected. Strength is a
finite number in `[0,1]`; device is `auto`, `cpu`, `gpu`, `cuda`, `directml` or
`coreml`. Unknown fields and duplicate JSON keys are rejected. Source/output
paths are supplied at run time and are not baked into the portable recipe.

## Python API used by the GUI

```python
import recipes

recipe = {
    "format": "ForgePixRecipe", "schema_version": 1,
    "name": "Background and noise",
    "steps": [
        recipes.pin_step("forgepix-background-mono-v2", strength=0.5),
        recipes.pin_step("forgepix-denoise-mono-v2", strength=0.5),
    ],
}
recipes.save_recipe("my-recipe.forgepix-recipe.json", recipe)
recipe = recipes.load_recipe("my-recipe.forgepix-recipe.json")
report = recipes.run_recipe(
    recipe, "linear-stack.fits", "existing-output-folder",
    allow_experimental=True, cancel=cancel_event,
    progress=lambda step, count, done, total: update_progress(step, count, done, total),
    on_step=lambda index, result_path, record: record_completed_step(index, result_path, record),
)
```

`validate_recipe()` returns an independent, normalized dictionary. Save/load
validate the portable schema without requiring installed models. `pin_step()`
and `run_recipe()` also check actual local model bytes. `model_dir` is an
optional keyword for `pin_step` and `run_recipe`. Model availability checks,
input inspection, hashing, copying and execution belong in the GUI worker.

The step callback runs in the caller's worker thread after the completed step
has been written to the journal. Its result path points to the Float32 FITS;
subsequent steps also use that FITS. It receives a detached record and can emit a
queued GUI signal or call `Project.add_result(result_path, comparison, label)`
from an appropriate project worker. Widgets must not be modified directly from
the callback. Progress counts are local to the current step; backend selection
and fallback are recorded by the actual AI runtime in each step's `execution`.
Registered GPU providers alone do not prove physical GPU work.

A callback failure marks the run `failed` and records `callback_status=failed`.
The successfully computed files retain their `completed` processing status;
they are not deleted or passed to the next step after a failed callback.

## Files, integrity and cancellation

Before creating a run directory, the engine validates the entire recipe, every
model ID/hash/task, the input's supported linear pixel domain and its coverage.
It uses the existing AI contract: no JPEG/8-bit TIFF display input, no unprocessed
Bayer FITS, and no partial coverage. Unknown coverage remains unknown; the
recipe does not manufacture a mask or missing observations.

Each run gets a fresh `stack-recipe-*` directory containing:

- `recipe.json`: the canonical recipe used for this run; its exact bytes are
  hashed in `run.json`.
- `input/`: a byte-identical snapshot of the source and its supported companion
  files. Source paths, sizes and hashes are recorded independently. Originals
  are never written. Later changes outside the run cannot change its input.
- `ai-<task>-*/`: the native worker's Float32 TIFF/FITS, coverage, optional signed
  star residuals and `ai_report.json`. Successful groups are verified against
  their reports and the pinned recipe before becoming completed steps.
- `run.json`: the atomic run journal with input/recipe hashes, ordered states,
  completed file hashes, actual execution records and the last completed result.

Scientific headers and companion files follow `ai_restore.run_file`'s existing
contract. Float inputs retain their physical scale; integer inputs follow the
documented dtype-range normalization with unit/scaling provenance. Each next
step reads the previous complete target image. A starless residual is retained
as a signed layer; it is not automatically recombined or described as measured
stellar flux.

The run returns a dictionary with `status` (`completed`, `cancelled`, `failed`),
`run_dir`, `journal_path`, `result_path`, `completed_steps`, `steps`, and `error`.
Cancellation uses an Event-like `is_set()` or callable. It is cooperative;
already completed steps and the input snapshot remain available. Cancellation
before validation finishes creates no run folder and returns null paths.
Unstarted steps remain `pending`. A failed output group is not promoted to the
last successful result, even if diagnostic files remain in its run folder.

Invalid recipes/inputs raise `RecipeError` before outputs. Operational failures
return a failed journal when it can be saved. A journal I/O failure raises
`RecipeError` naming the run location; the previous complete journal is retained
by atomic replacement, and completed scientific files are not deleted. There
is no automatic resume or recomputation from an interrupted journal in version 1.

Hashes make file changes detectable; they are not digital signatures. Device
preferences and exact model bytes are pinned, but floating-point results may
vary across runtimes and execution backends. Current models remain experimental.

## Verification

The GUI is available under **Bearbeitung → Bearbeitungsrezepte** (Ctrl+Shift+R).
It edits order, effect strength and backend per step, saves/loads `.fprecipe`
files, reports progress and retains completed results after cancellation. With
an open project, each completed step is archived; archive failures are explicit
and do not display an older result as the final one. The input snapshot supplies
the comparison preview. Actual M27 GUI acceptance ran background 25% then
denoise 50% with DirectML, saved/reloaded the recipe, reopened both project
results after restart and verified original/output hashes (43 s total).

The same recipe can run from a terminal or another local automation:

```text
ForgePix --recipe --file Astro.fprecipe --input linear.fits --output-root results --experimental
```

The output parent must exist. Ctrl+C requests cooperative cancellation;
exit codes are 0 completed, 1 failed, 130 cancelled. There is no shell execution
inside recipe files. Multi-input scheduling, a GUI action recorder, masks,
PixelMath steps and arbitrary processing graphs remain future work.

`tests/test_recipes.py` exercises recipe reuse on two FITS inputs, original/header/
coverage preservation, all four allowed tasks and star residuals, incorrect
model hashes/tasks, unsupported input domains, explicit consent, cancellation
during a second model, changes to models and source files, corrupt output masks,
atomic write failures and callback isolation. Its small bundled-model test runs
real ONNX inference when ONNX Runtime and the packaged denoiser are available;
it verifies integration and finite output, not scientific model quality.
