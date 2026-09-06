"""Bounded further training of an own mono denoiser; no automatic promotion.

This uses development validation, not the independent evaluator's test scenes.
The initial parent is included in checkpoint selection, so a worse refinement
cannot replace it solely because additional training has completed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import numpy as np
import torch
from training.train_restoration import CONFIG, CONTRACT, sample, normalize, loss_function, evaluate
from training.vendor.nafnet_upstream import NAFNet


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--parent",type=Path,required=True)
    ap.add_argument("--scenes",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--steps",type=int,default=8000)
    args=ap.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    lock=args.output.parent/"restoration-training.lock"
    with lock.open("x") as stream:
        stream.write(json.dumps(dict(pid=os.getpid(),output=str(args.output))))
    try:
        refine(args)
    finally:
        lock.unlink(missing_ok=True)


def refine(args):
    if args.steps<1:
        raise ValueError("Positive steps required")
    args.output.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(4)
    torch.manual_seed(609062)
    gen=torch.Generator(device="cuda").manual_seed(609062)
    checkpoint=torch.load(args.parent,map_location="cpu",weights_only=False)
    if checkpoint.get("contract")!=CONTRACT or checkpoint["config"]!=CONFIG:
        raise ValueError("Refinement requires the v2 mono contract")
    model=NAFNet(**CONFIG).cuda()
    model.load_state_dict(checkpoint["model"])
    train_bank=torch.from_numpy(np.load(args.scenes/"train.npy"))[:,None].cuda()
    val_bank=torch.from_numpy(np.load(args.scenes/"validation.npy"))[:,None].cuda()
    model.eval()
    before=evaluate(model,"denoise","cuda",val_bank)
    best,best_step=before["output_mse"],0
    torch.save(checkpoint,args.output/"checkpoint.pt")
    optimizer=torch.optim.AdamW(model.parameters(),lr=8e-5)
    scheduler=torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,args.steps,eta_min=8e-6)
    start=time.perf_counter()
    with (args.output/"metrics.jsonl").open("w") as stream:
        for step in range(1,args.steps+1):
            model.train()
            inp,target=sample(4,"cuda",gen,"denoise",train_bank)
            x,y,_,_=normalize(inp,target)
            optimizer.zero_grad(set_to_none=True)
            loss=loss_function(model(x),y)
            if not torch.isfinite(loss):
                raise ValueError("Non-finite loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),1.)
            optimizer.step(); scheduler.step()
            if step==1 or step%100==0:
                row=dict(step=step,loss=float(loss.detach()),seconds=time.perf_counter()-start)
                print(json.dumps(row),flush=True)
                stream.write(json.dumps(row)+"\n"); stream.flush()
            if step%1000==0 or step==args.steps:
                model.eval()
                val=evaluate(model,"denoise","cuda",val_bank)
                print(json.dumps(dict(step=step,validation=val)),flush=True)
                if val["output_mse"]<best:
                    best,best_step=val["output_mse"],step
                    torch.save(dict(model=model.state_dict(),config=CONFIG,contract=CONTRACT,
                        report=dict(task="denoise",step=step,validation=val,release_approved=False)),
                        args.output/"checkpoint.pt")
    selected=torch.load(args.output/"checkpoint.pt",map_location="cpu",weights_only=False)
    report=dict(schema_version=1,task="denoise",status="experimental",release_approved=False,
        steps=args.steps,best_step=best_step,batch=4,config=CONFIG,contract=CONTRACT,seed=609062,
        before=before,validation=selected["report"]["validation"],
        seconds=time.perf_counter()-start,torch_version=str(torch.__version__),
        parent_checkpoint_sha256=hashlib.sha256(args.parent.read_bytes()).hexdigest(),
        training_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        generator_source_sha256=hashlib.sha256((Path(__file__).parent/"train_restoration.py").read_bytes()).hexdigest(),
        scene_counts=json.loads((args.scenes/"manifest.json").read_text())["counts"],
        limitations="Development validation used for checkpoint selection; independent synthetic and real-camera evaluation still required. HST targets retain observational noise.")
    (args.output/"report.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)


if __name__=="__main__":
    main()
