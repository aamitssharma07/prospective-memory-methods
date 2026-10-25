"""Reject missing or quantized cached checkpoints before starting SGLang."""
import argparse
import json
from pathlib import Path

from huggingface_hub import hf_hub_download


def validate_config(config):
    for section in (config, config.get("text_config") or {}):
        if section.get("quantization_config"):
            raise ValueError("Quantized checkpoint rejected: this experiment requires BF16 weights")
        dtype = section.get("dtype", section.get("torch_dtype"))
        if dtype is not None and dtype != "bfloat16":
            raise ValueError(f"Expected BF16 checkpoint metadata, found {dtype!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config_path = hf_hub_download(
        args.model, "config.json", cache_dir=root / ".cache/huggingface/hub",
        local_files_only=True,
    )
    validate_config(json.loads(Path(config_path).read_text()))
    print(f"Checkpoint metadata precision check passed: {args.model}")


if __name__ == "__main__":
    main()
