"""Credit-gated recovery using each interrupted run's unchanged source snapshot."""

import argparse
import ast
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[3]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def rows(path):
    if not path.exists():
        return []
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def reserve(request):
    return (len(json.dumps(request.get("messages", []), ensure_ascii=False).encode())
            + len(json.dumps(request.get("response_format", {})).encode())
            + 64 * (len(request.get("messages", [])) + 1)
            + request.get("max_completion_tokens", request.get("max_tokens", 0)))


def rejected_for_credits(call):
    error = call.get("error") or {}
    prefix = "Error code: 429 - "
    message = error.get("message", "")
    if (error.get("type") != "RateLimitError" or not message.startswith(prefix)
            or call.get("response") is not None or call.get("usage") is not None):
        return False
    try:
        detail = ast.literal_eval(message[len(prefix):])["error"]
        return (detail.get("type") == "insufficient_quota"
                and detail.get("code") == "credit_balance_exhausted")
    except (ValueError, SyntaxError, KeyError, TypeError, AttributeError):
        return False


def reconciliation(calls, events):
    actor = [call for call in calls if call["role"] == "actor"]
    ids = [call["call_id"] for call in actor]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate actor calls; recovery blocked")
    starts = {e["call_id"] for e in events
              if e.get("event") == "call_start" and e.get("role") == "actor"}
    if starts - set(ids):
        raise ValueError("Unfinished actor attempt has unknown usage; recovery blocked")
    reservations = []
    for call in actor:
        usage = call.get("usage")
        total = usage.get("total_tokens") if isinstance(usage, dict) else None
        if type(total) is int and total >= 0:
            continue
        if not rejected_for_credits(call):
            raise ValueError("Unreconciled actor usage; recovery blocked")
        request = call["request"]
        if request.get("max_completion_tokens") != 768:
            raise ValueError("Unexpected output budget")
        reservations.append({"call_id": call["call_id"], "observed_usage": None,
                             "accounting": "conservative_request_reservation_not_measured_usage",
                             "reserved_tokens": reserve(request),
                             "request_sha256": hashlib.sha256(
                                 json.dumps(request, sort_keys=True).encode()).hexdigest(),
                             "provider_error_code": "credit_balance_exhausted"})
    return reservations


def verified_manifest(path):
    manifest = json.loads(path.read_text())
    source = path.parent / "source"
    for name, expected in manifest["source_sha256"].items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Frozen source mismatch: {name}")
    for name, expected in manifest["dependencies"].items():
        if importlib.metadata.version(name) != expected:
            raise ValueError(f"Dependency mismatch: {name}")
    if (manifest["actor_backend"] != "openai_chat" or manifest["actor_model"] != "gpt-5.4"
            or manifest["base_url"] != "https://api.openai.com/v1"
            or manifest["max_tokens"] != 768 or manifest["helper_max_tokens"] != 768):
        raise ValueError("Unexpected hosted actor configuration")
    return manifest


def phase_arguments(manifest_path, output, kind, manifest):
    resume = (output / "manifest.json").exists()
    if output.exists() and not resume:
        raise ValueError("Existing output is not a resumable run")
    values = {key: manifest[key] for key in (
        "actor_backend", "base_url", "helper_model", "helper_base_url", "projector_id",
        "actor_projector_id", "actor_guidance", "query_handoff", "query_budget", "gate_style",
        "report_gates", "verify_actions", "source_routing", "scope_grounding", "bounded_priority",
        "registration_grounding", "local_only")}
    values.update(model=manifest["actor_model"], output=str(output), kind=kind,
                  scenario=str(manifest_path.parent / "scenario.json") if kind == manifest["kind"]
                  else str(ROOT / "benchmark/data/synthetic_week_v9.json"),
                  provenance=str(manifest_path), actor_provenance=None,
                  max_actor_calls=manifest["max_actor_calls"] if kind == manifest["kind"] else 300,
                  max_actor_tokens=manifest["max_actor_tokens"] if kind == manifest["kind"] else 4000000,
                  resume=resume, stop_after=None)
    # A new benchmark needs a server provenance file, not the parent run manifest.
    if not resume:
        provenance = output.parent / (output.name + "-helper-provenance.json")
        actual_provenance = dict(manifest["provenance"])
        if os.environ.get("RECOVERY_SERVING_RECORD"):
            serving = json.loads(Path(os.environ["RECOVERY_SERVING_RECORD"]).read_text())
            actual_provenance.update(gpu=serving["gpu"], slurm_job_id=serving["slurm_job_id"],
                                     server_log=str(Path(os.environ["RECOVERY_SERVING_RECORD"]).with_name("server.log")),
                                     original_serving_job_id=manifest["provenance"]["slurm_job_id"])
        save(provenance, actual_provenance)
        values["provenance"] = str(provenance)
    return SimpleNamespace(**values)


def load_runner(manifest_path, manifest):
    source = manifest_path.parent / "source"
    # run_memory imports two unused baseline classes that old snapshots omitted.
    # They are pinned separately in the recovery plan, after frozen import paths.
    sys.path.append(str(ROOT / "harness"))
    spec = importlib.util.spec_from_file_location(
        "frozen_rgpm_run", source / "experiments/rgpm/run.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    actual = {str(p.relative_to(runner.ROOT)): runner.digest(p) for p in runner.source_files()}
    if manifest["source_sha256"] != actual:
        raise ValueError("Frozen source file inventory mismatch")
    return runner


def recovery_session(base_session, reservations):
    class RecoverySession(base_session):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if os.environ.get("RECOVERY_SERVING_RECORD"):
                self.event("recovery_serving_context", record_path=os.environ["RECOVERY_SERVING_RECORD"],
                           serving=json.loads(Path(os.environ["RECOVERY_SERVING_RECORD"]).read_text()))
            # Only explicit pre-inference credit rejections qualify. Actual usage
            # stays null in the original call; unknown transport usage still blocks.
            if reservations:
                self._actor_tokens += sum(r["reserved_tokens"] for r in reservations)
                self._actor_usage_unknown = False
                self.event("billing_rejection_budget_reservation", reservations=reservations,
                           known_plus_reserved_actor_tokens=self._actor_tokens,
                           operational_wrapper_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    return RecoverySession


def phase(manifest_path, output, kind):
    manifest = verified_manifest(manifest_path)
    runner = load_runner(manifest_path, manifest)
    reservations = reconciliation(rows(output / "calls.jsonl"), rows(output / "events.jsonl"))
    runner.Session = recovery_session(runner.Session, reservations)
    return runner.run(phase_arguments(manifest_path, output, kind, manifest))


def credit_check(output):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        save(output, {"status": "missing_key"})
        return False
    payload = {"model": "gpt-5.4", "messages": [{"role": "user", "content": "Reply only OK."}],
               "temperature": 0, "reasoning_effort": "none", "max_completion_tokens": 768}
    request = urllib.request.Request("https://api.openai.com/v1/chat/completions",
                                     data=json.dumps(payload).encode(), method="POST",
                                     headers={"Authorization": "Bearer " + key,
                                              "Content-Type": "application/json"})
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "request": payload}
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result.update(http_status=response.status, response=json.load(response),
                          request_id=response.headers.get("x-request-id"))
        usage = result["response"].get("usage") or {}
        passed = result["http_status"] == 200 and type(usage.get("total_tokens")) is int
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc)
        except (ValueError, UnicodeDecodeError):
            detail = {"error": {"type": "unparseable_http_error"}}
        result.update(http_status=exc.code, error=json.loads(json.dumps(detail).replace(key, "[REDACTED]")))
        passed = False
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc).replace(key, "[REDACTED]")}
        passed = False
    result.update(duration_seconds=time.monotonic() - started, admitted=passed)
    save(output, result)
    return passed


def execute(plan_path):
    plan = json.loads(plan_path.read_text())
    if datetime.now(timezone.utc) < datetime.fromisoformat(plan["not_before_utc"]):
        raise ValueError("Refusing to run before the approved Chicago midnight")
    for relative, expected in plan["operational_sha256"].items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("Scheduled operational code changed; revalidate before running")
    attempt = ROOT / plan["attempts_root"] / str(os.environ["SLURM_JOB_ID"])
    attempt.mkdir(parents=True, exist_ok=False)
    with (plan_path.with_suffix(".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        save(attempt / "status.json", {"status": "checking_credits"})
        if not credit_check(attempt / "credit_check.json"):
            save(attempt / "status.json", {"status": "blocked_no_credit_or_api_error",
                                           "experiments_started": False})
            print("Credit check failed; no experiment calls or helper servers started.", flush=True)
            return 2
        try:
            for pair in plan["pairs"]:
                manifest_path = ROOT / pair["manifest"]
                manifest = verified_manifest(manifest_path)
                provenance = manifest["provenance"]
                if importlib.metadata.version("sglang") != provenance["sglang_version"]:
                    raise ValueError("SGLang version mismatch")
                if Path(provenance["checkpoint"]).name != provenance["revision"]:
                    raise ValueError("Helper checkpoint revision mismatch")
                if (provenance["projector_id"] != manifest["projector_id"]
                        or provenance["model"] != manifest["helper_model"]):
                    raise ValueError("Helper identity mismatch")
                output = ROOT / pair["full_output"]
                if (output / "status.json").exists() and json.loads(
                        (output / "status.json").read_text())["status"] == "complete":
                    continue
                # Refuse unrelated unknown-usage attempts before loading a helper.
                reconciliation(rows(manifest_path.parent / "calls.jsonl"),
                               rows(manifest_path.parent / "events.jsonl"))
                command = provenance["command"]
                url = manifest["helper_base_url"] + "/models"
                try:
                    with urllib.request.urlopen(url, timeout=2):
                        raise RuntimeError("Helper port already in use")
                except urllib.error.HTTPError as exc:
                    raise RuntimeError("Helper port returned an HTTP error; refusing reuse") from exc
                except urllib.error.URLError:
                    pass
                directory = attempt / manifest["helper_model"].split("/")[-1]
                directory.mkdir()
                gpu = subprocess.run(["nvidia-smi", "--query-gpu=name,uuid,memory.total",
                                      "--format=csv,noheader"], check=True, capture_output=True, text=True)
                save(directory / "serving.json", {"command": command, "revision": provenance["revision"],
                     "projector_id": provenance["projector_id"], "gpu": gpu.stdout.strip(),
                     "slurm_job_id": os.environ["SLURM_JOB_ID"], "parent_manifest": str(manifest_path)})
                with (directory / "server.log").open("w") as server_log:
                    server = subprocess.Popen(command, stdout=server_log, stderr=subprocess.STDOUT,
                                              start_new_session=True)
                    try:
                        ready = False
                        for _ in range(180):
                            if server.poll() is not None:
                                raise RuntimeError("Helper server exited; inspect server.log")
                            try:
                                with urllib.request.urlopen(url, timeout=3) as response:
                                    models = json.load(response)
                                if any(m.get("id") == manifest["helper_model"] for m in models["data"]):
                                    ready = True
                                    break
                            except (urllib.error.URLError, ValueError, KeyError):
                                pass
                            time.sleep(5)
                        if not ready:
                            raise RuntimeError("Helper readiness timed out")
                        phases = [(manifest_path.parent, "smoke"), (output, "benchmark")] if pair["resume_smoke"] else [(output, "benchmark")]
                        for phase_output, kind in phases:
                            save(attempt / "status.json", {"status": "running", "helper": manifest["helper_model"],
                                                           "phase": kind, "output": str(phase_output)})
                            subprocess.run([sys.executable, str(Path(__file__).resolve()), "phase",
                                            "--manifest", str(manifest_path), "--output", str(phase_output),
                                            "--kind", kind], check=True,
                                           env={**os.environ, "RECOVERY_SERVING_RECORD": str(directory / "serving.json")})
                            if kind == "smoke":
                                subprocess.run([sys.executable, str(manifest_path.parent / "source/experiments/rgpm/smoke_gate.py"),
                                                str(phase_output), "--admission-policy", "report_only"], check=True)
                    finally:
                        if server.poll() is None:
                            os.killpg(server.pid, signal.SIGTERM)
                            try:
                                server.wait(timeout=20)
                            except subprocess.TimeoutExpired:
                                os.killpg(server.pid, signal.SIGKILL)
                                server.wait()
            save(attempt / "status.json", {"status": "complete"})
        except BaseException as exc:
            save(attempt / "status.json", {"status": "failed", "error_type": type(exc).__name__,
                                           "message": str(exc)})
            raise
    return 0


def schedule(plan_path, not_before):
    target = datetime.fromisoformat(not_before)
    if target.tzinfo is None or target <= datetime.now(timezone.utc):
        raise ValueError("Provide a future timezone-aware time")
    if plan_path.exists():
        raise ValueError("Schedule record already exists; refusing duplicate submission")
    followup = json.loads((ROOT / "experiments/rgpm/launches/gpt_v15_remaining_helpers_submitted_20261023.json").read_text())
    pairs = []
    for job in followup["jobs"]:
        if job["helper"] not in {"Qwen/Qwen3-4B", "Qwen/Qwen3-8B"}:
            continue
        full = Path(job["result_directory"])
        smoke = Path("experiments/rgpm/smoke_artifacts") / full.relative_to(
            "experiments/rgpm/runs/registration_v15_gpt_remaining_helpers")
        resume_smoke = job["helper"] == "Qwen/Qwen3-8B"
        manifest_path = ROOT / (smoke if resume_smoke else full) / "manifest.json"
        verified_manifest(manifest_path)
        reconciled = reconciliation(rows(manifest_path.parent / "calls.jsonl"),
                                    rows(manifest_path.parent / "events.jsonl"))
        if not resume_smoke:
            status = json.loads((ROOT / smoke / "status.json").read_text())
            if status["status"] != "complete" or status["committed_steps"] != 6:
                raise ValueError("4B smoke admission was not completed")
        pairs.append({"helper": job["helper"], "original_job_id": job["job_id"],
                      "manifest": str(manifest_path.relative_to(ROOT)),
                      "full_output": str(full), "resume_smoke": resume_smoke,
                      "expected_credit_rejection_reservations": reconciled})
    if len(pairs) != 2:
        raise ValueError("Expected precisely the two interrupted GPT pairs")
    files = [Path(__file__).resolve(), Path(__file__).with_name("retry_gpt_after_midnight.sbatch"),
             ROOT / "harness/memory_intervention.py", ROOT / "harness/structured_memory.py",
             ROOT / "benchmark/data/synthetic_week_v9.json"]
    for pair in pairs:
        manifest_path = ROOT / pair["manifest"]
        files.extend([manifest_path, manifest_path.parent / "scenario.json"])
    plan = {"schema_version": 1, "experiment": 3, "status": "prepared_not_submitted",
            "authorization": "User requested retry after midnight Chicago time if credits unavailable",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "not_before_utc": target.astimezone(timezone.utc).isoformat(),
            "not_before_chicago": target.astimezone(ZoneInfo("America/Chicago")).isoformat(),
            "attempts_root": "experiments/rgpm/jobs/gpt_midnight_recovery_20261025",
            "pairs": pairs, "max_tokens": 768, "credit_probe_max_calls": 1,
            "credit_failure_policy": "stop_without_experiment_calls_no_automatic_retry",
            "operational_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            "completed_1_7b_and_32b_results": "not_rerun",
            "local_jobs": "not_changed"}
    save(plan_path, plan)
    utc = target.astimezone(timezone.utc)
    command = ["sbatch", "--parsable", "--begin=" + utc.strftime("%Y-%m-%dT%H:%M:%S"),
               "--nodelist=crest-g002", "experiments/rgpm/operations/retry_gpt_after_midnight.sbatch",
               str(plan_path.relative_to(ROOT))]
    plan["submission_argv"] = command
    save(plan_path, plan)
    env = {**os.environ, "TZ": "UTC"}
    submitted = subprocess.run(command, cwd=ROOT, env=env, check=True, capture_output=True, text=True)
    job_id = submitted.stdout.strip().split(";")[0]
    if not job_id.isdigit():
        raise ValueError("Unexpected scheduler submission response; inspect before resubmitting")
    plan.update(job_id=job_id, status="submitted")
    save(plan_path, plan)
    inspected = subprocess.run(["scontrol", "show", "job", job_id, "-o"], env=env,
                               check=True, capture_output=True, text=True)
    plan["scheduler_verification"] = inspected.stdout.strip()
    fields = dict(item.split("=", 1) for item in inspected.stdout.split() if "=" in item)
    eligible = datetime.fromisoformat(fields["EligibleTime"]).replace(tzinfo=timezone.utc)
    if eligible < utc:
        subprocess.run(["scontrol", "hold", job_id], env=env, check=True)
        plan["status"] = "held_schedule_verification_failed"
        save(plan_path, plan)
        raise ValueError("Scheduler eligibility was earlier than approved; job held")
    save(plan_path, plan)
    print(json.dumps({"job_id": job_id, "not_before_chicago": plan["not_before_chicago"],
                      "scheduler_state": fields["JobState"], "scheduler_eligible_utc": eligible.isoformat(),
                      "plan": str(plan_path.relative_to(ROOT))}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    execute_parser = subparsers.add_parser("execute")
    execute_parser.add_argument("--plan", type=Path, required=True)
    submit = subparsers.add_parser("schedule")
    submit.add_argument("--plan", type=Path, required=True)
    submit.add_argument("--not-before", required=True)
    run = subparsers.add_parser("phase")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--kind", choices=("smoke", "benchmark"), required=True)
    args = parser.parse_args()
    if args.command == "schedule":
        schedule(args.plan.resolve(), args.not_before)
        return
    if args.command == "execute":
        def interrupted(signum, frame):
            raise InterruptedError(f"Scheduler signal {signum}")
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        raise SystemExit(execute(args.plan.resolve()))
    phase(args.manifest.resolve(), args.output.resolve(), args.kind)


if __name__ == "__main__":
    main()
