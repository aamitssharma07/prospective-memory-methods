"""Independent, scripted event-stream checks for the prospective-memory interface.

Run ``python3 -m prospective_memory.demo --output /path/to/report.json``.
These scenarios validate lifecycle and evidence controls. Their compiler and
matcher are scripted; the results do not measure language-model understanding.
No benchmark data or benchmark-specific adapter is imported here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from .core import Change, Decision, Engine, Instruction, Observation


class ScriptedCompiler:
    """Translate fixture IDs through a declared script, without semantic parsing."""

    def __init__(self, plans: dict):
        self.plans = plans

    def __call__(self, instruction, intentions, sources):
        plan = dict(self.plans[instruction.id])
        target_action = plan.pop("target_action", None)
        if target_action is not None:
            plan["target_id"] = next(
                item.id for item in intentions if item.action == target_action
            )
        plan.setdefault("evidence_quote", instruction.text)
        return [Change(**plan)]


def literal_matcher(intentions, observations, sources):
    """Use literal fixture conditions; this is deliberately not a semantic model."""
    decisions = []
    for intention in intentions:
        evidence = [
            observation.id
            for observation in observations
            if observation.current
            and observation.source in intention.sources
            and intention.condition in observation.text
        ]
        decisions.append(
            Decision(
                "ACT" if evidence else "WAIT",
                intention.id,
                reason="Scripted literal condition comparison",
                evidence_ids=tuple(evidence),
            )
        )
    return decisions


def _engine(plans, matcher=literal_matcher, query_budget=1):
    return Engine(
        compiler=ScriptedCompiler(plans),
        matcher=matcher,
        sources=("events", "clock", "messages", "status"),
        query_budget=query_budget,
    )


def _registration(action, condition, *, sources=("events",), repeat=False):
    return dict(
        op="register", action=action, condition=condition,
        sources=sources, repeat=repeat,
    )


def _acts(decisions):
    return [decision for decision in decisions if decision.kind == "ACT"]


def _expect(condition, message):
    if not condition:
        raise AssertionError(message)


def delayed_event():
    engine = _engine({
        "start": _registration("Summarize the experiment", "Experiment complete")
    })
    intention_id = engine.ingest(Instruction(
        "start", "Summarize the experiment when it completes."
    ))[0]
    quiet_ticks = 0
    for index, text in enumerate((
        "A new unrelated meeting was scheduled.",
        "The experiment remains in progress.",
        "An unrelated document was edited.",
    )):
        decisions = engine.tick([Observation(f"delay-{index}", text)])
        _expect(not _acts(decisions), "An unrelated event triggered the intention")
        quiet_ticks += 1
    acts = _acts(engine.tick([Observation("finished", "Experiment complete")]))
    _expect(len(acts) == 1 and acts[0].intention_id == intention_id,
            "The delayed completion event did not activate the stored intention")
    return {"quiet_ticks": quiet_ticks, "reminders": len(acts)}


def simultaneous_intentions():
    engine = _engine({
        "report": _registration("Forward the report", "Report approved"),
        "experiment": _registration("Summarize the experiment", "Experiment complete"),
    })
    ids = {
        engine.ingest(Instruction("report", "Forward the report once approved."))[0],
        engine.ingest(Instruction("experiment", "Summarize the completed experiment."))[0],
    }
    acts = _acts(engine.tick([
        Observation("approval", "Report approved"),
        Observation("completion", "Experiment complete"),
    ]))
    _expect({decision.intention_id for decision in acts} == ids,
            "Independent simultaneous conditions were not both recognized")
    return {"pending_intentions": 2, "reminders": len(acts)}


def cancelled_intention():
    engine = _engine({
        "start": _registration("Forward the report", "Report approved"),
        "cancel": dict(op="cancel", target_action="Forward the report"),
    })
    engine.ingest(Instruction("start", "Forward the report once approved."))
    engine.ingest(Instruction("cancel", "Cancel the instruction to forward the report."))
    acts = _acts(engine.tick([Observation("approval", "Report approved")]))
    _expect(not acts, "A cancelled intention was still activated")
    return {"reminders_after_cancellation": len(acts)}


def revised_intention():
    engine = _engine({
        "start": _registration("Forward the report", "Preliminary approval"),
        "revision": dict(
            op="revise", target_action="Forward the report",
            action="Forward the report", condition="Final approval", sources=("events",),
        ),
    })
    original_id = engine.ingest(Instruction(
        "start", "Forward the report after preliminary approval."
    ))[0]
    changed = engine.ingest(Instruction(
        "revision", "Wait for final approval before forwarding the report."
    ))
    _expect(original_id in changed, "Revision replaced the stable intention identity")
    _expect(not _acts(engine.tick([Observation("old-trigger", "Preliminary approval")])),
            "The obsolete condition still triggered the revised intention")
    acts = _acts(engine.tick([Observation("new-trigger", "Final approval")]))
    _expect(len(acts) == 1 and acts[0].intention_id == original_id,
            "The revised condition did not trigger the same intention")
    return {"stable_identity": True, "obsolete_trigger_reminders": 0,
            "revised_trigger_reminders": len(acts)}


def never_triggered():
    engine = _engine({
        "start": _registration("Notify the team", "Experiment failed")
    })
    engine.ingest(Instruction("start", "Notify the team if the experiment fails."))
    reminders = 0
    for index in range(5):
        reminders += len(_acts(engine.tick([
            Observation(f"healthy-{index}", "Experiment is healthy")
        ])))
    _expect(reminders == 0, "A never-satisfied condition produced a reminder")
    return {"observed_ticks": 5, "reminders": reminders}


def stale_evidence():
    # This matcher deliberately proposes unsafe decisions so the core, rather
    # than the fixture model, must reject old and repeated observation IDs.
    def matcher(intentions, observations, sources):
        return [Decision("ACT", item.id, evidence_ids=("approval",))
                for item in intentions]

    engine = _engine({
        "start": _registration("Forward the report", "Report approved")
    }, matcher)
    engine.ingest(Instruction("start", "Forward the report once approved."))
    _expect(not _acts(engine.tick([
        Observation("approval", "Report approved", current=False)
    ])), "A historical observation was accepted as current evidence")
    first = _acts(engine.tick([Observation("approval", "Report approved")]))
    _expect(len(first) == 1, "Fresh evidence was incorrectly rejected")
    _expect(not _acts(engine.tick([Observation("approval", "Report approved")])),
            "The same evidence generated duplicate reminders")
    _expect(not _acts(engine.tick([Observation("unrelated", "A meeting began")])),
            "Previously seen evidence was accepted when absent from this tick")
    return {"fresh_reminders": 1, "historical_or_duplicate_reminders": 0}


def invented_evidence():
    def matcher(intentions, observations, sources):
        return [Decision("ACT", item.id, evidence_ids=("invented-observation",))
                for item in intentions]

    engine = _engine({
        "start": _registration("Forward the report", "Report approved")
    }, matcher)
    engine.ingest(Instruction("start", "Forward the report once approved."))
    acts = _acts(engine.tick([Observation("real-observation", "No report update")]))
    _expect(not acts, "An invented evidence ID was accepted")
    _expect(bool(engine.errors), "Rejected invented evidence was not recorded")
    return {"unsupported_reminders": len(acts), "validation_errors": len(engine.errors)}


def push_and_pull_budget():
    def matcher(intentions, observations, sources):
        result = []
        for item in intentions:
            evidence = [ob.id for ob in observations
                        if ob.current and ob.source in item.sources
                        and item.condition in ob.text]
            if evidence:
                result.append(Decision("ACT", item.id, evidence_ids=tuple(evidence)))
            elif item.sources[0] != "events":
                result.append(Decision("CHECK", item.id, source=item.sources[0]))
            else:
                result.append(Decision("WAIT", item.id))
        return result

    engine = _engine({
        "push": _registration("Acknowledge the message", "Message arrived"),
        "pull-one": _registration("Summarize the experiment", "Experiment complete",
                                  sources=("status",)),
        "pull-two": _registration("Archive experiment outputs", "Experiment complete",
                                  sources=("status",)),
        "other-source": _registration("Submit the report", "17:00", sources=("clock",)),
    }, matcher, query_budget=1)
    for instruction_id, text in (
        ("push", "Acknowledge the message when it arrives."),
        ("pull-one", "Summarize the experiment once it finishes."),
        ("pull-two", "Archive outputs once the experiment finishes."),
        ("other-source", "Submit the report at 17:00."),
    ):
        engine.ingest(Instruction(instruction_id, text))
    decisions = engine.tick([Observation("message", "Message arrived")])
    checks = [decision for decision in decisions if decision.kind == "CHECK"]
    _expect(len(_acts(decisions)) == 1, "A pushed event needed an unnecessary query")
    _expect(len(checks) == 1 and checks[0].source == "status",
            "Query budget or shared-source query deduplication failed")
    # The environment executes the returned check, then feeds its public result
    # back. Each tick has a budget; this host closes the example after one pull.
    observed_result = Observation("status-result", "Experiment complete", source="status")
    acts = _acts(engine.tick([observed_result]))
    _expect(len(acts) == 2, "One channel observation did not serve both intentions")
    return {"query_budget_per_tick": 1, "executed_queries": 1,
            "push_reminders": 1, "pull_reminders": len(acts)}


def persistence_restore():
    plans = {"start": _registration("Forward the report", "Report approved")}
    original = _engine(plans)
    intention_id = original.ingest(Instruction(
        "start", "Forward the report once approved."
    ))[0]
    state = json.loads(json.dumps(original.snapshot()))
    restored = _engine(plans)
    restored.restore(state)
    acts = _acts(restored.tick([Observation("approval", "Report approved")]))
    _expect(len(acts) == 1 and acts[0].intention_id == intention_id,
            "A restored intention lost its identity or condition")
    # Persist the consumed observation too, to prevent a restart replaying it.
    after_reminder = _engine(plans)
    after_reminder.restore(json.loads(json.dumps(restored.snapshot())))
    _expect(not _acts(after_reminder.tick([Observation("approval", "Report approved")])),
            "Restoring the snapshot forgot consumed evidence")
    return {"json_round_trip": True, "restored_reminders": len(acts),
            "replay_reminders_after_restore": 0}


def recurring_acknowledgement():
    engine = _engine({
        "start": _registration("Summarize the experiment", "Experiment complete",
                               repeat=True)
    })
    intention_id = engine.ingest(Instruction(
        "start", "Summarize each experiment whenever it completes."
    ))[0]
    _expect(len(_acts(engine.tick([Observation("first", "Experiment complete")]))) == 1,
            "The first recurring occurrence did not fire")
    engine.acknowledge(intention_id, outcome="attempted")
    _expect(not _acts(engine.tick([Observation("while-working", "Experiment complete")])),
            "An in-flight intention was reminded before acknowledgment")
    engine.acknowledge(intention_id, outcome="completed")
    _expect(not _acts(engine.tick([Observation("first", "Experiment complete")])),
            "Rearming recurrence reused already consumed evidence")
    second = _acts(engine.tick([Observation("second", "Experiment complete")]))
    _expect(len(second) == 1, "A completed recurring intention was not rearmed")
    return {"distinct_occurrence_reminders": 2, "duplicate_reminders": 0}


SCENARIOS: dict[str, Callable[[], dict]] = {
    "delayed_event_and_unrelated_activity": delayed_event,
    "simultaneous_independent_intentions": simultaneous_intentions,
    "cancellation": cancelled_intention,
    "revision": revised_intention,
    "never_triggered": never_triggered,
    "stale_and_repeated_evidence": stale_evidence,
    "invented_evidence": invented_evidence,
    "push_and_pull_with_query_budget": push_and_pull_budget,
    "persistence_restore": persistence_restore,
    "recurring_intention_acknowledgement": recurring_acknowledgement,
}


def run_scenarios():
    results = []
    for name, scenario in SCENARIOS.items():
        try:
            results.append({"scenario": name, "passed": True, "details": scenario()})
        except Exception as exc:
            results.append({"scenario": name, "passed": False,
                            "error": f"{type(exc).__name__}: {exc}"})
    return {
        "evaluation": "scripted interface and lifecycle validation",
        "semantic_model_performance_evaluated": False,
        "benchmark_data_used": False,
        "note": (
            "The compiler and matcher are deterministic fixtures. These checks establish "
            "interface behavior, lifecycle transitions, and evidence controls; they do "
            "not establish improved prospective-memory accuracy or semantic trigger recognition."
        ),
        "passed": sum(item["passed"] for item in results),
        "total": len(results),
        "scenarios": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON report destination")
    args = parser.parse_args()
    report = run_scenarios()
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
