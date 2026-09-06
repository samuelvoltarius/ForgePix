"""Finite, exclusive train/evaluate/export queue; never auto-promote weights."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--scenes",type=Path,required=True)
    ap.add_argument("--parents",type=Path,required=True)
    ap.add_argument("--steps",type=int,default=4000)
    args=ap.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    lock=args.output.parent/"restoration-training.lock"
    with lock.open("x") as stream:
        stream.write(json.dumps(dict(pid=os.getpid(),output=str(args.output))))
    try:
        args.output.mkdir(parents=True,exist_ok=False)
        for task in ("denoise","starless","deblur","background"):
            if shutil.disk_usage(args.output).free < 80*1024**3:
                raise RuntimeError("Disk reserve below 80 GiB")
            run=args.output/task
            commands=[
                [sys.executable,"-m","training.train_restoration","--task",task,
                 "--output",str(run),"--scenes",str(args.scenes),"--steps",str(args.steps)],
                [sys.executable,"-m","training.evaluate_models","--candidate",str(run/"checkpoint.pt"),
                 "--parent",str(args.parents/task/"checkpoint.pt"),"--task",task,
                 "--output",str(run/"independent_evaluation.json")],
                [sys.executable,"-m","training.export_model","--checkpoint",str(run/"checkpoint.pt"),
                 "--evaluation",str(run/"independent_evaluation.json"),
                 "--output",str(args.output/"models"/f"forgepix-{task}-mono-v2")]]
            for command in commands:
                print(json.dumps(dict(time=time.time(),command=command)),flush=True)
                subprocess.run(command,check=True)
            with (args.output/"queue.jsonl").open("a") as log:
                log.write(json.dumps(dict(task=task,completed_at=time.time(),release_approved=False))+"\n")
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
