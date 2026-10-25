#!/usr/bin/env python3
"""Preview or execute the frozen PM-Bench model/setup matrix."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

from tqdm import tqdm


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return payload


def resolve(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def validate(config: dict, models: dict) -> None:
    if config.get("schema_version") != 1 or models.get("schema_version") != 1:
        raise ValueError("Unsupported configuration schema version")

    model_rows = models.get("models")
    setup_rows = config.get("setups")
    if not isinstance(model_rows, list) or not model_rows:
        raise ValueError("The model registry is empty")
    if not isinstance(setup_rows, list) or not setup_rows:
        raise ValueError("The setup list is empty")

    model_ids = [row.get("id") for row in model_rows]
    setup_names = [row.get("name") for row in setup_rows]
    if any(not value for value in model_ids) or len(model_ids) != len(set(model_ids)):
        raise ValueError("Model IDs must be non-empty and unique")
    if any(not value for value in setup_names) or len(setup_names) != len(set(setup_names)):
        raise ValueError("Setup names must be non-empty and unique")

    expected_setups = {
        "single_baseline",
        "optional_heartbeat",
        "todo_ledger",
        "auto_heartbeat_30m",
    }
    if set(setup_names) != expected_setups:
        raise ValueError(f"Expected exactly the core four setups: {sorted(expected_setups)}")

    scenario = resolve(ROOT, config["scenario"])
    actual_hash = hashlib.sha256(scenario.read_bytes()).hexdigest()
    if actual_hash != config.get("scenario_sha256"):
        raise ValueError(
            f"Scenario hash mismatch: expected {config.get('scenario_sha256')}, "
            f"found {actual_hash}"
        )


def slug(value: str) -> str:
    return value.lower().replace("/", "--").replace(".", "-").replace(" ", "-")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write_manifest(path: Path, config: dict, model: dict, setup: dict,
                   command: list[str], status: str, error: str | None = None) -> None:
    source_paths = [
        ROOT / "sim" / name for name in (
            "pm_bench.py", "run_eval.py", "run_todo_ledger.py", "checkpointing.py",
            "analyze_run.py", "run_experiment_matrix.py",
        )
    ]
    existing = load_json(path) if path.exists() else {}
    payload = {
        "schema_version": 1,
        "experiment": config["name"],
        "status": status,
        "created_at_utc": existing.get("created_at_utc", utc_now()),
        "updated_at_utc": utc_now(),
        "model": model,
        "setup": setup,
        "scenario": config["scenario"],
        "scenario_sha256": config["scenario_sha256"],
        "generation": {
            key: config[key] for key in (
                "max_tokens", "max_invalid_retries", "temperature"
            )
        },
        "invalid_response_policy": "fail_closed_empty",
        "command": command,
        "source_sha256": {
            str(source.relative_to(ROOT)): hashlib.sha256(source.read_bytes()).hexdigest()
            for source in source_paths
        },
        "error": error,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_command(config: dict, model: dict, setup: dict, base_url: str | None) -> list[str]:
    run_dir = resolve(ROOT, config["output_directory"]) / slug(model["id"]) / setup["name"]
    log_path = run_dir / "trajectory.jsonl"
    checkpoint_path = run_dir / "checkpoint.json"
    command = [
        sys.executable,
        str(ROOT / "sim" / "run_eval.py"),
        "--setup",
        setup["runner_setup"],
        "--scenario",
        str(resolve(ROOT, config["scenario"])),
        "--backend",
        model["backend"],
        "--model",
        model["id"],
        "--out-dir",
        str(resolve(ROOT, config["output_directory"])),
        "--log",
        str(log_path),
        "--prompt-log",
        str(run_dir / "prompts.log"),
        "--checkpoint",
        str(checkpoint_path),
        "--max-tokens",
        str(config["max_tokens"]),
        "--max-invalid-retries",
        str(config["max_invalid_retries"]),
        "--temperature",
        str(config["temperature"]),
    ]
    if config.get("score", False):
        command.append("--score")
    if setup.get("heartbeat_mode"):
        command.extend(["--heartbeat-mode", setup["heartbeat_mode"]])
    if setup["runner_setup"] == "todo_ledger":
        command.extend(["--ledger-log", str(run_dir / "ledger.jsonl")])
    if checkpoint_path.exists():
        command.append("--resume")
    if base_url:
        command.extend(["--base-url", base_url])
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview the core-four matrix; execution requires --execute."
    )
    parser.add_argument("--config", default=str(ROOT / "experiment.json"))
    parser.add_argument("--model", action="append", default=[], help="Model name or ID; repeatable.")
    parser.add_argument("--backend", choices=["sglang", "openrouter"])
    parser.add_argument("--base-url", help="Endpoint override, normally required for local sglang runs.")
    parser.add_argument("--execute", action="store_true", help="Actually execute the selected commands.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    config = load_json(config_path)
    models_path = resolve(ROOT, config["models_file"])
    models = load_json(models_path)
    validate(config, models)

    selected = [row for row in models["models"] if row.get("enabled", True)]
    if args.backend:
        selected = [row for row in selected if row["backend"] == args.backend]
    if args.model:
        requested = set(args.model)
        selected = [
            row for row in selected if row["id"] in requested or row["name"] in requested
        ]
        found = {value for row in selected for value in (row["id"], row["name"])}
        missing = sorted(requested - found)
        if missing:
            raise ValueError(f"Unknown model selection: {', '.join(missing)}")
    if not selected:
        raise ValueError("No models matched the selection")
    if args.execute and any(row["backend"] == "sglang" for row in selected) and not args.base_url:
        raise ValueError("Use --base-url when executing an sglang model")

    commands = [
        (model, setup, build_command(config, model, setup, args.base_url))
        for model in selected
        for setup in config["setups"]
    ]
    mode = "EXECUTE" if args.execute else "PREVIEW"
    print(f"{mode}: {len(selected)} models x {len(config['setups'])} setups = {len(commands)} runs")
    command_iter = tqdm(
        commands,
        desc="PM-Bench runs",
        unit="run",
        dynamic_ncols=True,
        disable=not args.execute,
    )
    for model, setup, command in command_iter:
        if args.execute:
            command_iter.set_postfix_str(f"{model['name']} / {setup['name']}")
        run_dir = (
            resolve(ROOT, config["output_directory"])
            / slug(model["id"])
            / setup["name"]
        )
        metrics_path = run_dir / "metrics.json"
        if args.execute and metrics_path.exists():
            metrics = load_json(metrics_path)
            if metrics.get("status") == "complete":
                print(f"SKIP complete: {model['name']} / {setup['name']}")
                continue
        print(f"[{model['name']} / {setup['name']}] {shlex.join(command)}")
        if args.execute:
            run_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = run_dir / "manifest.json"
            write_manifest(manifest_path, config, model, setup, command, "running")
            try:
                subprocess.run(command, cwd=ROOT, check=True)
            except BaseException as exc:
                write_manifest(
                    manifest_path, config, model, setup, command, "failed",
                    f"{type(exc).__name__}: {exc}",
                )
                raise
            write_manifest(manifest_path, config, model, setup, command, "complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
