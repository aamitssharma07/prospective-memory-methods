#!/usr/bin/env python3
"""Download exactly the locally served models declared in models.json."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / ".cache" / "huggingface" / "hub"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--model", action="append", default=[], help="Model name or ID; repeatable.")
    parser.add_argument("--workers", type=int, default=3, help="Concurrent model repositories.")
    args = parser.parse_args()

    registry = json.loads((ROOT / "models.json").read_text(encoding="utf-8"))
    local_models = [
        row for row in registry["models"]
        if row["backend"] == "sglang" and row.get("enabled", True)
    ]
    if args.model:
        requested = set(args.model)
        local_models = [
            row for row in local_models
            if row["name"] in requested or row["id"] in requested
        ]
        found = {value for row in local_models for value in (row["name"], row["id"])}
        missing = requested - found
        if missing:
            parser.error(f"unknown local model(s): {', '.join(sorted(missing))}")

    token = os.environ.get("HF_TOKEN")
    if not token:
        parser.error("HF_TOKEN is not set; load it from .env before downloading")

    args.cache_dir.mkdir(parents=True, exist_ok=True)
    def download(model: dict) -> tuple[str, str]:
        print(f"Downloading {model['id']}", flush=True)
        path = snapshot_download(
            repo_id=model["id"],
            cache_dir=args.cache_dir,
            token=token,
        )
        return model["id"], path

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(download, model): model for model in local_models}
        completed = 0
        for future in as_completed(futures):
            model_id, path = future.result()
            completed += 1
            print(f"[{completed}/{len(local_models)}] Ready: {model_id} at {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
