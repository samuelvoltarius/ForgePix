"""Bounded sequential Spark experiments. No automatic production promotion."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=10000)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents concurrent queues sharing the same run directory.
    lock = args.output / "queue.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(descriptor, str(os.getpid()).encode())
    os.close(descriptor)
    try:
        for task in ("background", "deblur", "starless", "denoise"):
            run = args.output / task
            if run.exists():
                # Never overwrite checkpoints or silently retry a failed experiment.
                continue
            command = [sys.executable, "-m", "training.train_synthetic", "--output", str(run),
                       "--task", task, "--steps", str(args.steps), "--size", "256", "--batch", "4"]
            with (args.output / (task + ".log")).open("w") as log:
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            record = dict(task=task, exit_code=completed.returncode, finished_at=time.time(),
                          production_approved=False)
            if completed.returncode == 0:
                report = json.loads((run / "report.json").read_text())
                metrics = report["validation"]
                record["improved_over_input_on_synthetic_validation"] = metrics["output_mse"] < metrics["input_mse"]
                record["validation"] = metrics
            with (args.output / "queue.jsonl").open("a") as log:
                log.write(json.dumps(record) + "\n")
            print(json.dumps(record), flush=True)
            if completed.returncode != 0:
                raise SystemExit(completed.returncode)
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
