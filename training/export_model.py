"""Export locally trained mono weights with a checked inference contract."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import numpy as np
import torch
import onnx
import onnxruntime as ort
from training.vendor.nafnet_upstream import NAFNet


def export(checkpoint_path, output, evaluation=None):
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    contract = checkpoint["contract"]
    # Nur BEKANNTE Vertraege — mono und farbig. Alles andere wird nicht geraten: die
    # Normierung laesst sich aus den Gewichten nicht ablesen, und ein falsch normierter
    # Entrauscher macht Bilder schlechter, ohne dabei zu scheitern.
    bekannt = [dict(channels=k, tile_size=256, halo=32,
                    normalization="affine_percentile_v1", output="complete_target")
               for k in (1, 3)]
    if contract not in bekannt:
        raise ValueError("Unknown preprocessing contract; do not guess normalization")
    kanaele = int(contract["channels"])
    task = checkpoint["report"]["task"]
    model = NAFNet(**checkpoint["config"]).eval()
    model.load_state_dict(checkpoint["model"])
    torch.set_num_threads(4)
    output.mkdir(parents=True, exist_ok=False)
    destination = output/"model.onnx"
    torch.onnx.export(model, torch.zeros(1,kanaele,256,256), str(destination),
                      input_names=["image"], output_names=["restored"],
                      opset_version=17, dynamo=False, external_data=False)
    onnx.checker.check_model(onnx.load(destination))
    opts=ort.SessionOptions(); opts.intra_op_num_threads=4
    session = ort.InferenceSession(str(destination), sess_options=opts,
                                   providers=["CPUExecutionProvider"])
    rng=np.random.default_rng(789055)
    form=(1,kanaele,256,256)
    inputs=[np.zeros(form,np.float32),
            rng.normal(.08,.03,form).astype(np.float32),
            rng.uniform(-.2,2.,form).astype(np.float32)]
    errors=[]
    for data in inputs:
        with torch.no_grad():
            reference=model(torch.from_numpy(data)).numpy()
        actual=session.run(None,{"image":data})[0]
        if not np.isfinite(actual).all():
            raise ValueError("Non-finite exported model")
        np.testing.assert_allclose(actual,reference,atol=2e-5,rtol=2e-4)
        errors.append(float(np.max(np.abs(actual-reference))))
    report_path=checkpoint_path.parent/"report.json"
    report=json.loads(report_path.read_text())
    if evaluation:
        independent=json.loads(evaluation.read_text())
        checkpoint_digest=hashlib.sha256(checkpoint_path.read_bytes()).hexdigest()
        if (independent.get("task") != task or
                independent.get("models",{}).get("candidate",{}).get("sha256") != checkpoint_digest):
            raise ValueError("Evaluation task/checkpoint hash does not match exported weights")
        (output/"evaluation.json").write_text(json.dumps(independent,indent=2))
    (output/"training_report.json").write_text(json.dumps(report,indent=2))
    art="mono" if kanaele==1 else "farbe"
    manifest=dict(schema_version=1,id=f"forgepix-{task}-{art}-v2",task=task,
        model_file="model.onnx",sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
        **contract,status="experimental",release_approved=False,
        license="MIT",weights_origin="Trained by ForgePix; no third-party pretrained weights",
        architecture="NAFNet %s width%d; upstream licence retained" % (
            art, checkpoint["config"]["width"]),
        upstream="https://github.com/megvii-research/NAFNet/tree/2b4af71ebe098a92a75910c233a3965a3e93ede4",
        checkpoint_sha256=hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
        photometry_validated=False,onnx_opset=17,export_max_abs_errors=errors,
        limitations=report["limitations"])
    manifest["inference"] = (dict(strategy="global_background_residual",working_shape=[256,256],
        residual_smoothing_sigma=16,downsample="area",upsample_residual="cubic") if task=="background"
        else dict(strategy="overlapping_tiles",stride=192,overlap=64,padding="reflect"))
    (output/"manifest.json").write_text(json.dumps(manifest,indent=2))
    source_root=Path(__file__).resolve().parent.parent
    shutil.copyfile(source_root/"training/vendor/NAFNet-LICENSE.txt",output/"NAFNet-LICENSE.txt")
    if (source_root/"LICENSE").exists():
        shutil.copyfile(source_root/"LICENSE",output/"LICENSE")
    print(json.dumps(manifest),flush=True)


if __name__ == "__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--checkpoint",required=True,type=Path)
    ap.add_argument("--output",required=True,type=Path)
    ap.add_argument("--evaluation",type=Path)
    args=ap.parse_args()
    export(args.checkpoint,args.output,args.evaluation)
