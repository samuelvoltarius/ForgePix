# Local AI acceleration

The four own AI tools default to **Automatic (prefer graphics processor)**.
The dialog also offers **Processor only**. Training on the Spark is separate
from running a trained model on the desktop; inference does not need PyTorch.

Windows x64 packages now include ONNX Runtime DirectML 1.24.4, with CPU fallback.
DirectML can use compatible NVIDIA, AMD and Intel DirectX 12 adapters without
a separate CUDA/cuDNN installation. Other platforms use the existing ONNX Runtime
package: available CUDA is preferred, and macOS can select CoreML. CUDA/CoreML
support in the code does not establish execution or speed on every GPU/OS.

The status names the configured backend. `ai_report.json.execution` records
the requested device, available and registered providers, selected provider,
initialization attempts, fallback reasons and whole-image restart count.
Provider registration is not proof that every operator ran on a physical GPU;
`gpu_execution_verified` remains false in ordinary application reports. Separate
profiling evidence is needed to make a hardware-acceleration claim.

If GPU initialization fails, another available backend or CPU is tried. If a
GPU inference fails after some tiles or channels, the entire image is recomputed
on CPU. Results from different attempts are not mixed. Cancellation never starts
a fallback run. All existing linear-value, original-preservation and experimental
model checks remain in force. CUDA TF32 and CoreML reduced-precision GPU
accumulation are disabled; small floating-point differences still require tests.

CLI example:

```text
ForgePix --ai-restore --input linear.fits --model forgepix-denoise-mono-v2 --experimental --device auto
```

`--device` accepts `auto`, `cpu`, `gpu`, `cuda`, `directml`, and `coreml`.
An explicitly requested unavailable GPU backend still falls back with a recorded
reason. For verification, `tests/smoke_bundle.py --require-provider
DmlExecutionProvider` makes an unexpected CPU fallback fail the package check.

For development, use a fresh environment. `onnxruntime`, `onnxruntime-directml`
and `onnxruntime-gpu` share the same Python import and must not be installed
together. The default requirements select DirectML only on Windows x64. A custom
CUDA environment must replace that runtime package and supply the compatible
CUDA/cuDNN dependencies; the desktop app does not download them automatically.

DirectML is supported in sustained engineering; new Windows ML development is
moving toward WinML. DirectML is used here for the existing Python ONNX Runtime
application and bounded package dependencies, not described as Microsoft's new
preferred platform.

Primary references: [DirectML requirements and session constraints](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html),
[CUDA compatibility and precision options](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html),
[CoreML options](https://onnxruntime.ai/docs/execution-providers/CoreML-ExecutionProvider.html).

Models remain experimental. Backend parity, finite pixels and faster computation
do not qualify denoising quality, photometry or camera generalization.
