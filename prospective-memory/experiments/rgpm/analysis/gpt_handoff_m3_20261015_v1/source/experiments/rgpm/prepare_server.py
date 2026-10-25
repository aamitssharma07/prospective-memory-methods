"""Resolve a cached checkpoint and record the exact local serving command."""

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

from huggingface_hub import snapshot_download
from artifacts import save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=30003)
    parser.add_argument("--model", default="Qwen/Qwen3-8B")
    parser.add_argument("--mem-fraction", type=float, default=None,
                        help="sglang --mem-fraction-static, for two servers sharing one GPU")
    parser.add_argument("--tp-size", type=int, default=1,
                        help="Tensor-parallel degree; >1 for models needing multiple GPUs to load at all")
    parser.add_argument("--disable-cuda-graph", action="store_true",
                        help="Disable prefill/decode CUDA graph capture; needed at tight mem-fraction "
                             "margins on 70B+ models where graph capture itself OOMs or asserts")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    model = args.model
    caches = [root.parent / "prospective-memory-reaearch/.cache/huggingface/hub",
              root / "PMBench/.cache/huggingface/hub",
              Path.home() / ".cache/huggingface/hub"]
    checkpoint = None
    for cache in caches:
        try:
            checkpoint = snapshot_download(model, cache_dir=str(cache), local_files_only=True)
            break
        except Exception:
            model_cache = cache / ("models--" + model.replace("/", "--"))
            ref = model_cache / "refs/main"
            if not ref.is_file():
                continue
            revision = ref.read_text().strip()
            candidate = model_cache / "snapshots" / revision
            required = [candidate / "config.json", candidate / "tokenizer_config.json",
                        candidate / "tokenizer.json", candidate / "model.safetensors.index.json"]
            if all(path.is_file() and path.stat().st_size > 0 for path in required):
                index = json.loads(required[-1].read_text())
                weights = sorted(set(index.get("weight_map", {}).values()))
                if weights and all((candidate / name).is_file()
                                   and (candidate / name).stat().st_size > 0 for name in weights):
                    checkpoint = str(candidate)
                    break
    if checkpoint is None:
        raise RuntimeError(f"No cached {model} main revision found; no download attempted")
    version = importlib.metadata.version("sglang")
    revision = Path(checkpoint).name
    command = [str(Path(sys.executable).parent / "sglang"), "serve",
               "--model-path", checkpoint, "--served-model-name", model,
               "--host", "127.0.0.1", "--port", str(args.port), "--dtype", "bfloat16",
               "--tp-size", str(args.tp_size), "--sampling-backend", "pytorch",
               "--grammar-backend", "xgrammar", "--constrained-json-disable-any-whitespace"]
    if args.mem_fraction is not None:
        command += ["--mem-fraction-static", str(args.mem_fraction)]
    if args.disable_cuda_graph:
        command += ["--disable-prefill-cuda-graph", "--disable-decode-cuda-graph"]
    gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,uuid,memory.total", "--format=csv,noheader"],
                         capture_output=True, text=True, check=True).stdout.strip()
    projector_id = f"{model}@{revision};bf16;temperature=0;nonthinking;max_tokens=768;sglang={version};compact_json"
    args.output.mkdir(parents=True, exist_ok=True)
    save(args.output / "server_provenance.json", {"schema_version": 1, "model": model,
         "checkpoint": checkpoint, "revision": revision, "sglang_version": version,
         "dtype": "bfloat16", "gpu": gpu, "command": command, "mem_fraction_static": args.mem_fraction,
         "slurm_job_id": os.environ.get("SLURM_JOB_ID"), "projector_id": projector_id,
         "server_log": str((args.output / "server.log").resolve())})
    print(json.dumps({"checkpoint": checkpoint, "revision": revision, "projector_id": projector_id}))


if __name__ == "__main__":
    main()
