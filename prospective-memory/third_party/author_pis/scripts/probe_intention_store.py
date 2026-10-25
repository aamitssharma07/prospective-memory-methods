#!/usr/bin/env python3
"""Deterministic, no-LLM probes for one failure family of the intention store.

These are the cheap stand-in for a full PM-Bench week: each case is a tiny
typed vignette (cancel / reschedule / leftover / TIME-DUE / upsert).
Run after analyzing a score report; fix code until this script exits 0.

  python scripts/probe_intention_store.py
  python scripts/probe_intention_store.py --family update
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from pm_memory.common import (
    INTENTION_MEMORY_INJECT_HEADER,
    INTENTION_RAG_MEMORY_INJECT_HEADER,
    INTENTION_REWRITE_PROMPT,
    INTENTION_SCENE_JUDGE_PROMPT,
    build_compact_messages,
    extract_time_str,
)
from pm_memory.intention_rag import retrieve_intentions, serialize_intention
from pm_memory.intention_store import DueSlot, Intention, IntentionStoreBackend


def _store() -> IntentionStoreBackend:
    return IntentionStoreBackend(
        use_llm_update=False,
        use_llm_extract=False,
        use_llm_done=False,
        use_llm_match=False,
    )


def _intent(**kwargs) -> Intention:
    due = kwargs.pop("due", DueSlot(day="Tuesday"))
    return Intention(intent_id=kwargs.pop("intent_id", "i1"), due=due, **kwargs)


def case_scene_judge_asks_if_action_survives() -> str | None:
    """Judge reads the scene and patches rows; no flowchart, no scene quotes."""
    p = INTENTION_SCENE_JUDGE_PROMPT
    if "Update the PENDING" not in p and "update the PENDING" not in p:
        return "scene judge should just ask to update pending from the scene"
    if "ask in order" in p.lower() or "Yes → never cancel" in p:
        return "scene judge still has a decision flowchart"
    if "scene_cues" not in p:
        return "scene judge should also split the vignette into scene_cues"
    for banned in (
        "instead of the earlier cue",
        "no longer needs to happen",
        "watch for the",
        "follow-up text",
    ):
        if banned in p.lower():
            return f"scene judge still quotes catchphrase {banned!r}"
    return None


def case_cancel_does_not_kill_unrelated() -> str | None:
    """v0: cancel notice wiped every pending nearby. Apply only the named row."""
    s = _store()
    s.intentions["coop"] = _intent(
        intent_id="coop",
        action="Pay the co-op dues",
        due=DueSlot(day="Wednesday"),
    )
    s.intentions["asthma"] = _intent(
        intent_id="asthma",
        action="Take asthma medication",
        due=DueSlot(day="Wednesday", time="11:00"),
    )
    s._judge_index_to_id = {1: "coop", 2: "asthma"}
    s._apply_update_patches(
        [{"n": 1, "action": "cancel", "rationale": "scene voided co-op dues"}],
        day="Wednesday",
        time_str="",
    )
    if s.intentions["coop"].status != "canceled":
        return "coop should be canceled"
    if s.intentions["asthma"].status != "pending":
        return f"asthma was {s.intentions['asthma'].status}, expected pending"
    return None


def case_cue_firing_cancel_is_blocked() -> str | None:
    """Cue firing is event_due, not cancel; shield drops the cancel patch."""
    s = _store()
    s.intentions["key"] = _intent(
        intent_id="key",
        action="Pick up the room key",
        due=DueSlot(day="Tuesday"),
        event_cue="the conference room screen flashes your room assignment",
    )
    s._judge_index_to_id = {1: "key"}
    s._apply_update_patches(
        [{"n": 1, "action": "cancel", "rationale": "cue appeared"}],
        day="Tuesday",
        time_str="",
        event_due_ids={"key"},
    )
    if s.intentions["key"].status != "pending":
        return f"cue-firing row was {s.intentions['key'].status}, expected pending"
    if not any(
        skip.get("reason") == "cue_firing_not_cancel"
        for skip in s._update_skipped
    ):
        return "expected cue_firing_not_cancel skip"
    return None


def case_cue_firing_override_blocked() -> str | None:
    """Scene matching the stored event_cue is firing, not a cue rewrite."""
    s = _store()
    s.intentions["rack"] = _intent(
        intent_id="rack",
        action="Collect the parcel",
        due=DueSlot(day="Friday"),
        event_cue="it reaches the front rack",
    )
    s._judge_index_to_id = {1: "rack"}
    scene = "The counter has your order hanging on the front rack."
    s._apply_update_patches(
        [
            {
                "n": 1,
                "action": "override",
                "new_trigger": "The counter has your order hanging on the front rack.",
                "rationale": "condition is present now",
            }
        ],
        day="Friday",
        time_str="11:35",
        observation=scene,
    )
    if s.intentions["rack"].event_cue != "it reaches the front rack":
        return f"cue-firing override wrote {s.intentions['rack'].event_cue!r}"
    if not any(
        skip.get("reason") == "cue_firing_not_override"
        for skip in s._update_skipped
    ):
        return "expected cue_firing_not_override skip"
    return None


def case_clock_change_retargets_named_row() -> str | None:
    """A 'moves to HH:MM' scene reschedules the named clock row, not a related event."""
    s = _store()
    s.intentions["desk"] = _intent(
        intent_id="desk",
        action="Check in with the desk",
        due=DueSlot(day="Tuesday", time="15:20"),
    )
    s.intentions["move"] = _intent(
        intent_id="move",
        action="Move the check-in",
        due=DueSlot(day="Tuesday"),
        event_cue="the calendar update moves the call",
    )
    s._judge_index_to_id = {1: "desk", 2: "move"}
    scene = (
        "A short follow-up changes the timing for check in with the desk. "
        "The timing shifts a little: check in with the desk moves to 15:55."
    )
    s._apply_update_patches(
        [
            {
                "n": 2,
                "action": "override",
                "new_trigger": "the calendar update moves the call",
                "rationale": "wrong row",
            }
        ],
        day="Tuesday",
        time_str="13:00",
        observation=scene,
    )
    if s.intentions["move"].event_cue != "the calendar update moves the call":
        return "must not override the unrelated event row"
    if s.intentions["desk"].due.time != "15:55":
        return f"named clock row due.time={s.intentions['desk'].due.time!r}"
    if s.intentions["desk"].status != "pending":
        return "clock row must stay pending"
    return None


def case_cancel_with_new_trigger_becomes_override() -> str | None:
    """Cancel JSON that still names a later cue is override, not a void."""
    s = _store()
    s.intentions["a"] = _intent(
        intent_id="a",
        action="Do the deferred errand",
        due=DueSlot(day="Monday"),
        event_cue="the old condition",
    )
    s._judge_index_to_id = {1: "a"}
    s._apply_update_patches(
        [
            {
                "n": 1,
                "action": "cancel",
                "new_trigger": "the later condition",
                "rationale": "condition changed",
            }
        ],
        day="Monday",
        time_str="",
    )
    row = s.intentions["a"]
    if row.status != "pending":
        return f"status={row.status}, expected pending"
    if row.event_cue != "the later condition":
        return f"event_cue={row.event_cue!r}"
    return None


def case_true_void_still_cancels() -> str | None:
    """Cancel with empty new_trigger stays a void."""
    s = _store()
    s.intentions["a"] = _intent(
        intent_id="a",
        action="Do the deferred errand",
        due=DueSlot(day="Wednesday"),
    )
    s._judge_index_to_id = {1: "a"}
    s._apply_update_patches(
        [{"n": 1, "action": "cancel", "rationale": "voided"}],
        day="Wednesday",
        time_str="",
    )
    if s.intentions["a"].status != "canceled":
        return f"true void was {s.intentions['a'].status}"
    return None


def case_reschedule_rewrites_due_time() -> str | None:
    """v2: manager check-in moved to 15:55 must keep pending with new time."""
    s = _store()
    s.intentions["mgr"] = _intent(
        intent_id="mgr",
        action="Check in with your manager",
        due=DueSlot(day="Tuesday", time="14:00"),
    )
    s._judge_index_to_id = {1: "mgr"}
    s._apply_update_patches(
        [
            {
                "n": 1,
                "action": "reschedule",
                "new_time": "15:55",
                "new_day": "Tuesday",
                "rationale": "timing shifted",
            }
        ],
        day="Tuesday",
        time_str="",
    )
    got = s.intentions["mgr"]
    if got.status != "pending":
        return f"status={got.status}"
    if got.due.time != "15:55":
        return f"due.time={got.due.time!r}, expected 15:55"
    if got.due.day.lower() != "tuesday":
        return f"due.day={got.due.day!r}, expected Tuesday"
    return None


def case_day_change_does_not_cancel_pending() -> str | None:
    """v5: leftover sweep must not cancel still-open tasks at day change."""
    s = _store()
    s.intentions["tue"] = _intent(
        intent_id="tue",
        action="Check in with your manager",
        due=DueSlot(day="Tuesday", time="15:55"),
    )
    s.intentions["wed"] = _intent(
        intent_id="wed",
        action="Carry the prescription receipt",
        due=DueSlot(day="Wednesday"),
        event_cue="you notice the lab drop box",
    )
    messages = [
        {
            "role": "user",
            "content": "=== Wednesday ===\nToday's loose plan:\n- Take antibiotic at breakfast",
        }
    ]
    s._maybe_seed_daily(day="Wednesday")
    s._maybe_seed_day_plan(messages, day="Wednesday", time_str="")
    if s.intentions["tue"].status != "pending":
        return f"Tuesday leftover was {s.intentions['tue'].status}, expected pending"
    if s.intentions["wed"].status != "pending":
        return f"Wednesday due was {s.intentions['wed'].status}, expected pending"
    if not s._is_active_on_day(s.intentions["tue"], "Wednesday"):
        return "overdue Tuesday due should still inject on Wednesday"
    if not s._is_active_on_day(s.intentions["wed"], "Wednesday"):
        return "Wednesday due should inject on Wednesday"
    future = _intent(
        intent_id="fri",
        action="Carry the return label",
        due=DueSlot(day="Friday"),
        event_cue="doorbell camera flash",
    )
    if s._is_active_on_day(future, "Wednesday"):
        return "future Friday due must not inject on Wednesday"
    return None


def case_time_due_needs_trusted_clock() -> str | None:
    s = _store()
    s.intentions["a"] = _intent(
        intent_id="a",
        action="Take asthma medication",
        due=DueSlot(day="Monday", time="11:00"),
    )
    pending = list(s.intentions.values())
    if s._filter_time_due(pending, ""):
        return "no clock ⇒ no TIME-DUE"
    hits = s._filter_time_due(pending, "11:00")
    if [i.intent_id for i in hits] != ["a"]:
        return f"11:00 hits={hits}"
    if s._filter_time_due(pending, "11:01"):
        return "11:01 must not match 11:00 (tolerance 0)"
    return None


def case_unmatched_clock_is_today_pending() -> str | None:
    """Known clock + later due.time → withhold, not inject, not do-now PENDING."""
    s = _store()
    mgr = _intent(
        intent_id="mgr",
        action="Check in with your manager",
        due=DueSlot(day="Tuesday", time="15:55"),
    )
    text = s._format_injection(
        time_hits=[],
        event_hits=[],
        channel_hits=[],
        channel_needed=[],
        today_pending=[mgr],
        day="Tuesday",
        time_str="15:20",
    )
    if "TIME-DUE" in text and "[TIME-DUE]" in text:
        return "15:20 must not TIME-DUE a 15:55 row"
    if "TIME-WAIT" in text or "15:55" in text:
        return "unmatched clock must not be injected"
    if "TODAY pending" in text or "[PENDING]" in text:
        return "unmatched clock must not stay TODAY pending"
    return None


def case_time_due_header_asks_for_all_matches() -> str | None:
    """TIME-DUE / compact: several dues this step, do not omit one."""
    if "not a required pick" in INTENTION_MEMORY_INJECT_HEADER:
        return "compact still tells choose TIME-DUE is optional"
    if "EVERY TIME-DUE and DUE" not in INTENTION_MEMORY_INJECT_HEADER:
        return "compact should say include every TIME-DUE and DUE menu match"
    s = _store()
    hit = _intent(
        intent_id="pickup",
        action="Confirm the pickup window",
        due=DueSlot(day="Thursday", time="20:40"),
    )
    text = s._format_injection(
        time_hits=[hit],
        event_hits=[],
        channel_hits=[],
        channel_needed=[],
        today_pending=[],
        day="Thursday",
        time_str="20:40",
    )
    if "calendar-style reminder" in text:
        return "TIME-DUE header still reads as optional reminder"
    if "include ALL of these in task_ids" not in text:
        return "TIME-DUE header should tell choose not to skip clock rows"
    return None


def case_time_wait_when_gated() -> str | None:
    """`--gate-time-due`: unmatched clock rows are withheld, not TODAY pending."""
    s = _store()
    s.gate_time_due = True
    mgr = _intent(
        intent_id="mgr",
        action="Check in with your manager",
        due=DueSlot(day="Tuesday", time="15:55"),
    )
    text = s._format_injection(
        time_hits=[],
        time_waits=[mgr],
        event_hits=[],
        channel_hits=[],
        channel_needed=[],
        today_pending=[mgr],
        day="Tuesday",
        time_str="15:20",
    )
    if "TIME-DUE" in text and "[TIME-DUE]" in text:
        return "15:20 must not TIME-DUE a 15:55 row"
    if "TIME-WAIT" in text or "15:55" in text:
        return "gated unmatched clock must not be injected"
    if "TODAY pending" in text:
        return "gated unmatched clock must not stay TODAY pending"
    return None


def case_gate_strips_undue_clock_and_keeps_event() -> str | None:
    """Session gate drops TIME-WAIT menu picks; event handles stay."""
    s = _store()
    s.gate_time_due = True
    due = _intent(
        intent_id="asthma11",
        action="Take asthma medication",
        due=DueSlot(day="Monday", time="11:00"),
    )
    wait = _intent(
        intent_id="asthma21",
        action="Take asthma medication",
        due=DueSlot(day="Monday", time="21:00"),
    )
    event = _intent(
        intent_id="slip",
        action="Drop off the sample slip",
        due=DueSlot(day=""),
        event_cue="the lab drop box is unlocked",
    )
    s._last_time_hits = [due]
    s._last_time_waits = [wait]
    menu = (
        "Step action menu:\n"
        "- task_1: Take asthma medication at 11:00.\n"
        "- task_2: Take asthma medication at 21:00.\n"
        "- task_3: Drop off the sample slip.\n"
    )
    kept, dropped = s.gate_undue_clock_tasks(
        {"action": "choose", "task_ids": ["task_1", "task_2", "task_3"]},
        menu,
    )
    if dropped != ["task_2"]:
        return f"dropped={dropped}, expected ['task_2']"
    if kept != ["task_1", "task_3"]:
        return f"kept={kept}, expected task_1 and task_3"
    return None


def case_force_query_must_line() -> str | None:
    """`--force-query-channels` injection says MUST query CHECK names."""
    s = _store()
    s.force_query_channels = True
    mail = _intent(
        intent_id="mail",
        action="Send the library email",
        due=DueSlot(day="Monday", time="11:50"),
        watch=["email"],
    )
    text = s._format_injection(
        time_hits=[],
        event_hits=[],
        channel_hits=[],
        channel_needed=["email"],
        today_pending=[mail],
        day="Monday",
        time_str="10:00",
    )
    if "MUST query_state these CHECK channels" not in text:
        return "missing MUST query line"
    if "email" not in text:
        return "CHECK email not listed"
    return None


def case_cue_match_listing_hides_action() -> str | None:
    """Event listing is n+event only; time listing is n+time only; action after hit."""
    s = _store()
    asthma = _intent(
        intent_id="asthma",
        action="Take asthma medication",
        due=DueSlot(day="Monday", time="11:00"),
    )
    slip = _intent(
        intent_id="slip",
        action="Drop off the sample slip",
        due=DueSlot(day="Monday"),
        event_cue="the lab drop box is unlocked",
    )
    both = _intent(
        intent_id="both",
        action="Send the budget note",
        due=DueSlot(day="Tuesday", time="15:55"),
        event_cue="when you have a clear spot",
    )
    time_line = s._cue_match_line(1, asthma, field="time")
    event_line = s._cue_match_line(2, slip, field="event")
    mixed_event = s._cue_match_line(3, both, field="event")
    mixed_time = s._cue_match_line(3, both, field="time")
    if not time_line or "time=11:00" not in time_line:
        return f"time cue missing: {time_line!r}"
    if "event=" in time_line:
        return f"time listing leaked event: {time_line!r}"
    if "action=" in time_line or "Take asthma" in time_line:
        return f"time cue leaked action: {time_line!r}"
    if not event_line or "event=the lab drop box is unlocked" not in event_line:
        return f"event cue missing: {event_line!r}"
    if "time=" in event_line:
        return f"event listing leaked time: {event_line!r}"
    if "action=" in event_line or "Drop off" in event_line:
        return f"event cue leaked action: {event_line!r}"
    if not mixed_event or "event=when you have a clear spot" not in mixed_event:
        return f"mixed row event missing: {mixed_event!r}"
    if "time=" in mixed_event or "15:55" in mixed_event:
        return f"event listing on mixed row leaked time: {mixed_event!r}"
    if not mixed_time or "time=15:55" not in mixed_time:
        return f"mixed row time missing: {mixed_time!r}"
    if "event=" in mixed_time or "clear spot" in mixed_time:
        return f"time listing on mixed row leaked event: {mixed_time!r}"
    due_text = s._format_injection(
        time_hits=[asthma],
        event_hits=[slip],
        channel_hits=[],
        channel_needed=[],
        today_pending=[],
        day="Monday",
        time_str="11:00",
        match_filtered=True,
    )
    if "Take asthma medication" not in due_text:
        return "matched clock action missing from pending injection"
    if "Drop off the sample slip" not in due_text:
        return "matched event action missing from pending injection"
    if "event=the lab drop box is unlocked" not in due_text:
        return "DUE injection should keep the full intention including event="
    if "due=Monday 11:00" not in due_text:
        return "TIME-DUE injection should keep due="
    return None


def case_event_similarity_ignores_action() -> str | None:
    """Matcher scores event strings against vignette/State, never the action."""
    s = _store()
    s.use_llm_match = True
    slip = _intent(
        intent_id="slip",
        action="Drop off the sample slip",
        due=DueSlot(day="Monday"),
        event_cue="the lab drop box is unlocked",
    )
    decoy = _intent(
        intent_id="decoy",
        action="the lab drop box is unlocked",
        due=DueSlot(day="Monday"),
        event_cue="the laundry room cart is free",
    )
    split = s._match_event_channel(
        [slip, decoy],
        observation="You notice the lab drop box is unlocked by the cubby.",
        day="Monday",
        time_str="",
        messages=[],
    )
    due = {i.intent_id for i in split["event_due"]}
    if due != {"slip"}:
        return f"similarity due={due}, expected only slip (not the action-decoy)"
    listing = "\n".join(s.last_match_info.get("cue_listing") or [])
    if "Drop off" in listing or "action=" in listing.lower():
        return f"event listing leaked action: {listing!r}"
    hay = s._event_haystack(decoy, "Drop off the sample slip now.", {})
    if hay and s._event_similarity(decoy.event_cue, hay) >= s._event_sim_threshold:
        return "laundry cue must not match an action-only haystack"
    return None


def case_channel_watch_union_must_query() -> str | None:
    """CHECK is the watch union of filtered intentions; prompt MUST query them."""
    s = _store()
    mail = _intent(
        intent_id="mail",
        action="Forward the vendor reply",
        due=DueSlot(day="Monday"),
        watch=["email"],
    )
    needed = s._watch_needed([mail], [])
    if needed != ["email"]:
        return f"unqueried email should be CHECK, got {needed}"
    needed = s._watch_needed(
        [mail],
        [{"role": "user", "content": "State [email]: Inbox: (no updates)"}],
    )
    if needed:
        return f"already-queried email should drop from CHECK, got {needed}"
    text = s._format_injection(
        time_hits=[],
        event_hits=[],
        channel_hits=[],
        channel_needed=["email"],
        today_pending=[mail],
        day="Monday",
        time_str="10:00",
    )
    if "MUST query_state these CHECK channels" not in text:
        return "CHECK should use the MUST query line"
    if "every 2 steps" in text:
        return "cadence interval must not appear"
    return None


def case_event_match_waits_for_channel_query() -> str | None:
    """Watch rows wait for State; narrative events may match the vignette now."""
    s = _store()
    s.use_llm_match = True
    mail = _intent(
        intent_id="mail",
        action="Forward the vendor reply",
        due=DueSlot(day="Monday"),
        event_cue="the email lands",
        watch=["email"],
    )
    slip = _intent(
        intent_id="slip",
        action="Drop off the sample slip",
        due=DueSlot(day="Monday"),
        event_cue="the lab drop box is unlocked",
    )
    pending = [mail, slip]
    needed = s._watch_needed(pending, [])
    if needed != ["email"]:
        return f"email should be CHECK, got {needed}"
    before = s._match_event_channel(
        pending,
        observation="You notice the lab drop box is unlocked. Maybe check email.",
        day="Monday",
        time_str="10:00",
        messages=[],
        channel_needed=needed,
    )
    if before["mode"] != "similarity":
        return f"expected similarity, got {before['mode']!r}"
    if "slip" not in {i.intent_id for i in before["event_due"]}:
        return "narrative event should match the vignette without waiting for email"
    if before["channel_due"] or "mail" in {i.intent_id for i in before["event_due"]}:
        return "must not due the email row from the vignette before State [email]"
    kept_ids = {i.intent_id for i in before["kept"]}
    if "mail" not in kept_ids:
        return f"unqueried watch must stay for CHECK, got {kept_ids}"

    after = s._match_event_channel(
        pending,
        observation="You notice the lab drop box is unlocked.",
        day="Monday",
        time_str="10:00",
        messages=[
            {"role": "user", "content": "State [email]: Inbox: (no updates)"},
        ],
        channel_needed=[],
    )
    if after["mode"] != "similarity":
        return f"after CHECK State, match should run, got {after['mode']!r}"
    if "slip" not in {i.intent_id for i in after["event_due"]}:
        return "after query, vignette match should due the lab-drop-box row"
    if "mail" in {i.intent_id for i in after["channel_due"]}:
        return "(no updates) must not CHANNEL-DUE email"
    return None


def case_rich_cue_may_match_vignette() -> str | None:
    """Watch rows with content beyond the channel name may due from the vignette."""
    s = _store()
    s.use_llm_match = True
    mail = _intent(
        intent_id="mail",
        action="Forward the vendor reply",
        due=DueSlot(day="Monday"),
        event_cue="the confirmation email arrives",
        watch=["email"],
    )
    hit = s._match_event_channel(
        [mail],
        observation="A confirmation email arrives on the counter.",
        day="Monday",
        time_str="10:00",
        messages=[],
    )
    due = {i.intent_id for i in hit["event_due"]} | {
        i.intent_id for i in hit["channel_due"]
    }
    if "mail" not in due:
        return "vignette containing a rich event_cue should due the watch row"
    miss = s._match_event_channel(
        [mail],
        observation="Maybe check email later.",
        day="Monday",
        time_str="10:00",
        messages=[],
    )
    miss_due = {i.intent_id for i in miss["event_due"]} | {
        i.intent_id for i in miss["channel_due"]
    }
    if "mail" in miss_due:
        return "mentioning the channel name must not due a richer cue"
    return None


def case_match_after_one_of_several_watches() -> str | None:
    """Do not wait for every CHECK name; one State + vignette is enough to score."""
    s = _store()
    s.use_llm_match = True
    both = _intent(
        intent_id="both",
        action="Reply to the coordinator",
        due=DueSlot(day="Monday"),
        event_cue="the confirmation email arrives",
        watch=["email", "appointment_portal"],
    )
    other = _intent(
        intent_id="other",
        action="Collect the reserve reading",
        due=DueSlot(day="Monday"),
        event_cue="the hold is ready",
        watch=["library_hold"],
    )
    pending = [both, other]
    needed = s._watch_needed(pending, [])
    if set(needed) != {"email", "appointment_portal", "library_hold"}:
        return f"CHECK should list all three watches, got {needed}"
    before = s._match_event_channel(
        pending,
        observation="Nothing new in the hallway.",
        day="Monday",
        time_str="10:00",
        messages=[],
    )
    if before["channel_due"] or before["event_due"]:
        return "must not due watch rows before any State"
    after_one = s._match_event_channel(
        pending,
        observation="Nothing new in the hallway.",
        day="Monday",
        time_str="10:00",
        messages=[
            {
                "role": "user",
                "content": "State [email]: Inbox: the confirmation email arrives.",
            }
        ],
    )
    due = {i.intent_id for i in after_one["channel_due"]}
    if due != {"both"}:
        return f"after one email State, expected only both due, got {due}"
    wait_ids = {i.intent_id for i in after_one["channel_wait"]}
    if "other" not in wait_ids:
        return "library_hold still unqueried should wait, not block the email match"
    if "both" in wait_ids:
        return "partial-watch hit should be DUE, not wait for appointment_portal"
    return None


def case_narrative_hhmm_is_not_clock() -> str | None:
    text = "Remind yourself to take asthma medication at 11:00 after the meeting."
    if extract_time_str(text):
        return f"narrative at 11:00 leaked as clock: {extract_time_str(text)!r}"
    ok = extract_time_str("Time: 11:00 | Stopwatch: 00:12")
    if ok != "11:00":
        return f"system Time: line not parsed, got {ok!r}"
    return None


def case_asthma_two_slots_not_merged() -> str | None:
    """v1: 0.72 upsert merged 11:00 and 21:00 into one row."""
    s = _store()
    s._extract_from_text(
        "- Take asthma medication at 11:00\n- Take asthma medication at 21:00",
        day="Monday",
    )
    times = sorted(
        i.due.time
        for i in s.intentions.values()
        if i.status == "pending" and "asthma" in i.action.lower()
    )
    if times != ["11:00", "21:00"]:
        return f"asthma times={times}, expected ['11:00', '21:00']"
    return None


def case_duplicate_inserts_not_merged() -> str | None:
    """v4.2: identical bullets must both stay; no action-overlap upsert."""
    s = _store()
    s._extract_from_text(
        "- Pick up the dry cleaning when the text arrives\n"
        "- Pick up the dry cleaning when the text arrives",
        day="Monday",
    )
    n = sum(
        1
        for i in s.intentions.values()
        if i.status == "pending" and "dry cleaning" in i.action.lower()
    )
    if n != 2:
        return f"expected 2 dry-cleaning rows, got {n}"
    return None


def case_done_marks_by_n_not_overlap() -> str | None:
    """Same-action clock slots stay distinct; code maps the 11:00 choose only."""
    s = _store()
    s.intentions["a11"] = _intent(
        intent_id="a11",
        action="Take asthma medication",
        due=DueSlot(day="Monday", time="11:00"),
    )
    s.intentions["a21"] = _intent(
        intent_id="a21",
        action="Take asthma medication",
        due=DueSlot(day="Monday", time="21:00"),
    )
    s._judge_index_to_id = {1: "a11", 2: "a21"}
    hits = s._apply_done_ns([1])
    if hits != 1:
        return f"hits={hits}"
    if s.intentions["a11"].status != "done":
        return "11:00 should be done"
    if s.intentions["a21"].status != "pending":
        return f"21:00 was {s.intentions['a21'].status}; overlap would have killed it"
    s.intentions["a11"].status = "pending"
    n = s._mark_done_by_choice(
        ["Take asthma medication at 11:00."], day="Monday", time_str="11:00"
    )
    if n != 1:
        return f"stripped menu done hits={n}, expected 1"
    if s.intentions["a11"].status != "done":
        return "11:00 clock should map the choose after strip"
    if s.intentions["a21"].status != "pending":
        return "21:00 must stay pending when menu is at 11:00"
    return None


def case_done_exact_not_fuzzy() -> str | None:
    """Paraphrase must not close a row; stripped equality still marks done."""
    s = _store()
    s.intentions["filt"] = _intent(
        intent_id="filt",
        action="Pick up the replacement filter",
        due=DueSlot(day="Monday"),
        event_cue="the hardware counter clears",
    )
    n = s._mark_done_by_choice(
        ["Follow up on replacement filter pickup."], day="Monday"
    )
    if n != 0 or s.intentions["filt"].status != "pending":
        return "fuzzy paraphrase must not mark done"
    n = s._mark_done_by_choice(["Pick up the replacement filter."], day="Monday")
    if n != 1 or s.intentions["filt"].status != "done":
        return "exact strip (period ignored) should mark done"
    return None


def case_done_substring_union() -> str | None:
    """Store action as a phrase substring of the menu still marks done."""
    s = _store()
    s.intentions["abx"] = _intent(
        intent_id="abx",
        action="Take antibiotic",
        due=DueSlot(day="Wednesday"),
        event_cue="breakfast",
    )
    n = s._mark_done_by_choice(
        ["Take antibiotic at breakfast."], day="Wednesday"
    )
    if n != 1 or s.intentions["abx"].status != "done":
        return "substring fallback should mark done when menu keeps at breakfast"
    s.intentions["asthma"] = _intent(
        intent_id="asthma",
        action="Take a",
        due=DueSlot(day="Monday", time="11:00"),
    )
    n = s._mark_done_by_choice(
        ["Take asthma medication at 11:00."], day="Monday", time_str="11:00"
    )
    if n != 0 or s.intentions["asthma"].status != "pending":
        return "prefix take a must not substring-match take asthma"
    return None


def case_parse_strips_think_tags() -> str | None:
    data = IntentionStoreBackend._try_parse_judge_json(
        "<think>Let me analyze the scene.</think>\n{\"updates\": []}"
    )
    if data != {"updates": []}:
        return f"think-wrapped JSON not parsed: {data!r}"
    return None


def case_parse_json_in_prose() -> str | None:
    data = IntentionStoreBackend._try_parse_judge_json(
        "Sure, here you go:\n```json\n{\"done\": [1, 2]}\n```\n"
    )
    if data != {"done": [1, 2]}:
        return f"fenced JSON not parsed: {data!r}"
    return None


def case_done_empty_labels_skips() -> str | None:
    s = _store()
    s.intentions["a"] = _intent(
        intent_id="a",
        action="Take asthma medication",
        due=DueSlot(day="Monday", time="11:00"),
    )
    n = s._mark_done_by_choice([], day="Monday")
    if n != 0:
        return f"empty labels marked {n}"
    if s.intentions["a"].status != "pending":
        return "empty labels should not mark done"
    return None


def case_event_pending_section_visible() -> str | None:
    """v4.5: event-cued today pending must not be buried only in TODAY pending."""
    s = _store()
    receipt = _intent(
        intent_id="receipt",
        action="Carry the prescription receipt",
        due=DueSlot(day="Wednesday"),
        event_cue="you notice the lab drop box",
    )
    asthma = _intent(
        intent_id="asthma",
        action="Take asthma medication",
        due=DueSlot(day="Wednesday", time="11:00"),
    )
    s.intentions[receipt.intent_id] = receipt
    s.intentions[asthma.intent_id] = asthma
    text = s._format_injection(
        time_hits=[],
        event_hits=[],
        channel_hits=[],
        channel_needed=[],
        today_pending=[receipt, asthma],
        day="Wednesday",
        time_str="",
    )
    if "EVENT pending" not in text:
        return "missing EVENT pending section"
    if "[EVENT]" not in text or "Carry the prescription receipt" not in text:
        return "event-cued row not tagged EVENT"
    if "EVENT-CUED" in text:
        return "must not stamp EVENT-CUED"
    # unknown clock: clock rows are not do-now PENDING (check_time first)
    if "TIME-WAIT" in text:
        return "unknown clock must not TIME-WAIT (no trusted now)"
    if "Take asthma medication" in text and "[PENDING]" in text:
        return "unknown-clock row must not be TODAY pending"
    if "Carry the prescription receipt" not in text:
        return "event-cued row should still be visible as EVENT pending"
    return None


def case_event_plan_bullet_has_no_due() -> str | None:
    """Planting day must not become due.day for event-only plan bullets."""
    s = _store()
    s._extract_from_text(
        "- Adjust the prep plan when the calendar room shift appears",
        day="Tuesday",
    )
    rows = [i for i in s.intentions.values() if "prep plan" in i.action.lower()]
    if len(rows) != 1:
        return f"rows={len(rows)}"
    got = rows[0]
    if got.due.day:
        return f"event-only due.day={got.due.day!r}, expected empty"
    if got.due.time:
        return f"unexpected due.time={got.due.time!r}"
    if "calendar room shift" not in (got.event_cue or "").lower():
        return f"event_cue={got.event_cue!r}"
    watches = [
        (w or "").strip().lower()
        for w in (got.watch or [])
        if (w or "").strip() and (w or "").strip().lower() != "clock"
    ]
    text = s._format_injection(
        time_hits=[],
        event_hits=[],
        channel_hits=[],
        channel_needed=watches,
        today_pending=[got],
        day="Tuesday",
        time_str="",
    )
    if "due=" in text:
        return f"injection still labeled due: {text}"
    if watches:
        if "CHECK channels" not in text:
            return "event+watch plan should surface CHECK, not EVENT pending"
        if "[EVENT]" in text:
            return "unqueried watch must not be EVENT pending before query"
    elif "[EVENT]" not in text:
        return "event-only row should still be EVENT pending"
    return None


def case_cross_day_on_clause_keeps_due_day() -> str | None:
    """On Wednesday + when-clause is a real calendar due, not the planting day."""
    s = _store()
    s._extract_from_text(
        "On Wednesday, Email the room change note when you notice the lab cubby.",
        day="Tuesday",
    )
    rows = [
        i for i in s.intentions.values() if "room change" in i.action.lower()
    ]
    if len(rows) != 1:
        return f"rows={len(rows)} {[i.action for i in s.intentions.values()]}"
    got = rows[0]
    if (got.due.day or "").lower() != "wednesday":
        return f"due.day={got.due.day!r}, expected Wednesday"
    if "lab cubby" not in (got.event_cue or "").lower():
        return f"event_cue={got.event_cue!r}"
    return None


def case_calendar_on_clause_keeps_due_day() -> str | None:
    """On March 21 plants a future calendar due, hidden until that day."""
    s = _store()
    s._extract_from_text(
        "On March 21, Buy the train tickets when the booking window opens.",
        day="March 09",
    )
    rows = [
        i for i in s.intentions.values() if "train tickets" in i.action.lower()
    ]
    if len(rows) != 1:
        return f"rows={len(rows)} {[i.action for i in s.intentions.values()]}"
    got = rows[0]
    if (got.due.day or "") != "March 21":
        return f"due.day={got.due.day!r}, expected March 21"
    if s._is_active_on_day(got, "March 09"):
        return "March 21 due must stay hidden on March 09"
    if not s._is_active_on_day(got, "March 21"):
        return "March 21 due should inject on March 21"
    if not s._is_active_on_day(got, "March 22"):
        return "leftover March 21 due should still inject on March 22"
    return None


def case_extract_item_strips_planting_day() -> str | None:
    """LLM extract must not keep TODAY / planting weekday on event-only rows."""
    s = _store()
    same = s._intention_from_extract_item(
        {
            "action": "Take antibiotic",
            "due_day": "Tuesday",
            "due_time": None,
            "event_cue": "breakfast",
            "watch": [],
        },
        today="Tuesday",
    )
    if same.due.day:
        return f"planting-day event due.day={same.due.day!r}"
    today_token = s._intention_from_extract_item(
        {
            "action": "Collect the dry cleaning",
            "due_day": "TODAY",
            "due_time": None,
            "event_cue": "confirmation email",
            "watch": [],
        },
        today="Friday",
    )
    if today_token.due.day:
        return f"TODAY token became due.day={today_token.due.day!r}"
    named = s._intention_from_extract_item(
        {
            "action": "Email the room change note",
            "due_day": "Wednesday",
            "due_time": None,
            "event_cue": "notice the lab cubby",
            "watch": [],
        },
        today="Tuesday",
    )
    if (named.due.day or "").lower() != "wednesday":
        return f"named weekday dropped: {named.due.day!r}"
    timed = s._intention_from_extract_item(
        {
            "action": "Take asthma medication",
            "due_day": None,
            "due_time": "11:00",
            "event_cue": None,
            "watch": [],
        },
        today="Monday",
    )
    if (timed.due.day or "").lower() != "monday" or timed.due.time != "11:00":
        return f"clock task due={timed.due.day!r} {timed.due.time!r}"
    return None


def case_event_no_due_survives_leftover() -> str | None:
    """Empty due.day is not a calendar due; leftover must not invent planting day."""
    s = _store()
    s.intentions["evt"] = _intent(
        intent_id="evt",
        action="Adjust the prep plan",
        due=DueSlot(day="", time=""),
        event_cue="the calendar room shift appears",
    )
    messages = [
        {
            "role": "user",
            "content": "=== Wednesday ===\nToday's loose plan:\n- Take antibiotic at breakfast",
        }
    ]
    s._maybe_seed_daily(day="Wednesday")
    s._maybe_seed_day_plan(messages, day="Wednesday", time_str="")
    if s.intentions["evt"].status != "pending":
        return f"undated event leftover-canceled: {s.intentions['evt'].status}"
    return None


def case_daily_event_meds_have_no_due_day() -> str | None:
    s = _store()
    messages = [
        {
            "role": "user",
            "content": (
                "Regular tasks for every day:\n"
                "- Take antibiotic at breakfast and dinner.\n"
                "- Take asthma medication at 11:00 and 21:00."
            ),
        }
    ]
    s._maybe_seed_daily(messages, day="Tuesday")
    breakfast = [
        i for i in s.intentions.values() if (i.event_cue or "").lower() == "breakfast"
    ]
    if len(breakfast) != 1:
        return f"breakfast rows={len(breakfast)}"
    if breakfast[0].due.day:
        return f"antibiotic breakfast due.day={breakfast[0].due.day!r}"
    asthma = [
        i
        for i in s.intentions.values()
        if i.due.time == "11:00" and "asthma" in i.action.lower()
    ]
    if len(asthma) != 1:
        return f"asthma 11:00 rows={len(asthma)}"
    if (asthma[0].due.day or "").lower() != "tuesday":
        return f"asthma due.day={asthma[0].due.day!r}, expected Tuesday"
    return None


def case_filter_trace_drops_future_not_event() -> str | None:
    """Calendar hides future due.day; event/channel are grouped, not dropped."""
    s = _store()
    future = _intent(
        intent_id="fri",
        action="Carry the return label",
        due=DueSlot(day="Friday"),
        event_cue="doorbell camera flash",
    )
    asth = _intent(
        intent_id="a11",
        action="Take asthma medication",
        due=DueSlot(day="Wednesday", time="11:00"),
    )
    later = _intent(
        intent_id="a21",
        action="Take asthma medication",
        due=DueSlot(day="Wednesday", time="21:00"),
    )
    evt = _intent(
        intent_id="rec",
        action="Carry the prescription receipt",
        due=DueSlot(day="Wednesday"),
        event_cue="you notice the lab drop box",
        watch=["course_portal"],
    )
    pending = [future, asth, later, evt]
    s.intentions = {i.intent_id: i for i in pending}
    today = [i for i in pending if s._is_active_on_day(i, "Wednesday")]
    time_hits = s._filter_time_due(today, "11:00")
    needed = s._watch_needed(today, [])
    trace = s._build_filter_trace(
        pending=pending,
        today_pending=today,
        time_hits=time_hits,
        channel_needed=needed,
        day="Wednesday",
        step="s4",
        time_str="11:00",
        messages=[],
        extracted=[],
        extract_added=0,
    )
    dropped = {r["id"] for r in trace["drop_future_due_day"]}
    if dropped != {"fri"}:
        return f"drop_future={dropped}, expected {{fri}}"
    if {r["id"] for r in trace["time_due"]} != {"a11"}:
        return f"time_due={[r['id'] for r in trace['time_due']]}"
    if {r["id"] for r in trace["time_not_due"]} != {"a21"}:
        return f"time_not_due={[r['id'] for r in trace['time_not_due']]}"
    if "rec" not in {r["id"] for r in trace["event_group"]}:
        return "event row missing from event_group"
    if "rec" in dropped:
        return "event row was code-dropped"
    text = s._format_filter_trace(trace)
    if "不筛掉" not in text:
        return "trace text should say event/channel are not dropped"
    if "Carry the return label" not in text or "筛掉未来" not in text:
        return f"missing calendar drop in text: {text[:400]}"
    return None


def case_match_filter_drops_unmatched_event() -> str | None:
    """Scene Judge labels: unmatched event dropped; unqueried watch kept."""
    s = _store()
    fire = _intent(
        intent_id="fire",
        action="Carry the prescription receipt",
        due=DueSlot(day="Wednesday"),
        event_cue="you notice the lab drop box",
    )
    wait = _intent(
        intent_id="wait",
        action="Carry the laundry soap",
        due=DueSlot(day="Wednesday"),
        event_cue="notice the laundry room cart",
    )
    email = _intent(
        intent_id="email",
        action="Forward the vendor reply",
        due=DueSlot(day="Wednesday"),
        event_cue="",
        watch=["email"],
    )
    hold = _intent(
        intent_id="hold",
        action="Collect the reserve reading",
        due=DueSlot(day="Wednesday"),
        event_cue="",
        watch=["library_hold"],
    )
    pending = [fire, wait, email, hold]
    split = s._apply_match_labels(
        pending,
        event_due_ids={"fire"},
        channel_due_ids=set(),
        queried={"library_hold"},
    )
    kept = {i.intent_id for i in split["kept"]}
    if "wait" in kept:
        return "unmatched event should be dropped"
    if "fire" not in kept:
        return "matched event should remain"
    if "email" not in kept:
        return "unqueried watch should remain for CHECK"
    if "hold" in kept:
        return "queried watch that is not channel_due should drop"
    text = s._format_injection(
        time_hits=[],
        event_hits=split["event_due"],
        channel_hits=split["channel_due"],
        channel_needed=["email"],
        today_pending=split["kept"],
        day="Wednesday",
        time_str="",
        match_filtered=True,
    )
    if "Carry the laundry soap" in text:
        return "dropped event leaked into choose injection"
    if "DUE (" not in text:
        return "matched event should be DUE"
    if "EVENT-CUED" in text:
        return "must not stamp EVENT-CUED"
    if "Forward the vendor reply" in text:
        return "unqueried watch action must not be PENDING; CHECK names only"
    if "MUST query_state these CHECK channels" not in text:
        return "filtered watch union should MUST-query CHECK channels"
    needed = s._watch_needed(split["kept"], [])
    if needed != ["email"]:
        return f"CHECK should be email wait only, got {needed}"
    portal = _intent(
        intent_id="portal",
        action="Finish the intake form",
        due=DueSlot(day="Monday"),
        event_cue="the portal posts it",
        watch=["appointment_portal"],
    )
    hidden = s._apply_match_labels(
        [portal],
        event_due_ids=set(),
        channel_due_ids=set(),
        queried=set(),
    )
    if "portal" not in {i.intent_id for i in hidden["kept"]}:
        return "event+watch with no State must stay for CHECK"
    if hidden["event_due"] or hidden["event_drop"]:
        return "hidden-channel cue must not event-due or event-drop before query"
    if "portal" not in {i.intent_id for i in hidden["channel_wait"]}:
        return "event+watch should be channel_wait until State"
    if s._watch_needed([portal], []) != ["appointment_portal"]:
        return "CHECK must list appointment_portal from today pending"
    stamped = s._apply_match_labels(
        [portal],
        event_due_ids={"portal"},
        channel_due_ids=set(),
        queried=set(),
    )
    if not stamped["event_due"] or "portal" not in {
        i.intent_id for i in stamped["event_due"]
    }:
        return "rich vignette label on unqueried watch should EVENT-DUE"
    after_query = s._apply_match_labels(
        [portal],
        event_due_ids={"portal"},
        channel_due_ids=set(),
        queried={"appointment_portal"},
        states={"appointment_portal": "(no updates)"},
    )
    if "portal" not in {i.intent_id for i in after_query["kept"]}:
        return "queried watch with event_due must stay (judge put State in event_due)"
    if "portal" not in {i.intent_id for i in after_query["channel_due"]}:
        return "queried watch with event_due should stamp CHANNEL-DUE"
    if after_query["channel_drop"]:
        return "must not channel_drop a State hit labeled event_due"
    posted = s._apply_match_labels(
        [portal],
        event_due_ids=set(),
        channel_due_ids=set(),
        queried={"appointment_portal"},
        states={"appointment_portal": "Appointment portal: intake form posted."},
    )
    if "portal" not in {i.intent_id for i in posted["channel_due"]}:
        return "State 'intake form posted' should CHANNEL-DUE portal row"
    idle = s._apply_match_labels(
        [portal],
        event_due_ids=set(),
        channel_due_ids=set(),
        queried={"appointment_portal"},
        states={"appointment_portal": "(no updates)"},
    )
    if "portal" in {i.intent_id for i in idle["kept"]}:
        return "(no updates) should still drop unmatched portal row"
    slot = _intent(
        intent_id="slot",
        action="Move the appointment",
        due=DueSlot(day="Monday"),
        event_cue="a better slot opens",
        watch=["appointment_portal"],
    )
    form_only = s._apply_match_labels(
        [portal, slot],
        event_due_ids=set(),
        channel_due_ids=set(),
        queried={"appointment_portal"},
        states={"appointment_portal": "Appointment portal: intake form posted."},
    )
    if "slot" in {i.intent_id for i in form_only["channel_due"]}:
        return "form-posted State must not CHANNEL-DUE the better-slot row"
    hid_text = s._format_injection(
        time_hits=[],
        event_hits=hidden["event_due"],
        channel_hits=hidden["channel_due"],
        channel_needed=["appointment_portal"],
        today_pending=hidden["kept"],
        day="Monday",
        time_str="",
        match_filtered=True,
    )
    if "DUE (" in hid_text and "Finish the intake form" in hid_text:
        return "unqueried portal task must not be DUE"
    if "appointment_portal" not in hid_text:
        return "CHECK should name appointment_portal"
    # Match off: vignette may contain the cue; still no due stamp / no drop.
    off = s._match_event_channel(
        pending,
        observation="You notice the lab drop box by the cubby.",
        day="Wednesday",
        time_str="",
        messages=[],
    )
    if off["mode"] != "off":
        return f"probe default match mode={off['mode']!r}, expected off"
    if [i.intent_id for i in off["kept"]] != [i.intent_id for i in pending]:
        return "match off should keep all today pending"
    if off["event_due"] or off["channel_due"]:
        return "match off must not stamp EVENT/CHANNEL due (no substring cover)"
    # Hallucinated channel_due without this-step State → wait, not due.
    fake = s._apply_match_labels(
        [email],
        event_due_ids=set(),
        channel_due_ids={"email"},
        queried=set(),
    )
    if fake["channel_due"]:
        return "no State must not stamp CHANNEL-DUE"
    if "email" not in {i.intent_id for i in fake["kept"]}:
        return "no State wait must stay so choose can query"
    if "email" not in {i.intent_id for i in fake["channel_wait"]}:
        return "no State should be channel_wait"
    return None


def case_shared_cue_fanout_and_group() -> str | None:
    """One judge hit due-stamps every stored row watching the same cue."""
    s = _store()
    slip = _intent(
        intent_id="slip",
        action="Drop off the sample slip",
        due=DueSlot(day="Wednesday"),
        event_cue="the lab drop box is unlocked",
    )
    receipt = _intent(
        intent_id="receipt",
        action="Carry the prescription receipt",
        due=DueSlot(day="Wednesday"),
        event_cue="you notice the lab drop box",
    )
    cubby = _intent(
        intent_id="handout",
        action="Pick up the handout packet",
        due=DueSlot(day="Wednesday"),
        event_cue="it shows up in the lab cubby",
    )
    note = _intent(
        intent_id="note",
        action="Email the room change note",
        due=DueSlot(day="Wednesday"),
        event_cue="notice the lab cubby",
    )
    soap = _intent(
        intent_id="soap",
        action="Carry the laundry soap",
        due=DueSlot(day="Wednesday"),
        event_cue="notice the laundry room cart",
    )
    pending = [slip, receipt, cubby, note, soap]
    expanded = s._expand_event_due_ids(pending, {"slip"})
    if expanded != {"slip", "receipt"}:
        return f"drop-box fanout={expanded}, expected slip+receipt"
    none = s._expand_event_due_ids(pending, set())
    if none:
        return f"empty judge hit must not scan cues, got {none}"
    cubby_hit = s._expand_event_due_ids(pending, {"handout"})
    if cubby_hit != {"handout", "note"}:
        return f"cubby fanout={cubby_hit}, expected handout+note"
    split = s._apply_match_labels(
        pending,
        event_due_ids=expanded,
        channel_due_ids=set(),
        queried=set(),
    )
    due_ids = {i.intent_id for i in split["event_due"]}
    if due_ids != {"slip", "receipt"}:
        return f"event_due after fanout={due_ids}"
    if "soap" in {i.intent_id for i in split["kept"]}:
        return "unrelated laundry cue should drop"
    text = s._format_injection(
        time_hits=[],
        event_hits=split["event_due"],
        channel_hits=[],
        channel_needed=[],
        today_pending=split["kept"],
        day="Wednesday",
        time_str="11:50",
        match_filtered=True,
    )
    if "EVENT-CUED" in text:
        return "must not stamp EVENT-CUED"
    if "DUE (" not in text:
        return "shared cue should inject DUE"
    if "[lab drop box]" not in text:
        return f"missing shared-cue group header: {text}"
    if "Drop off the sample slip" not in text or "Carry the prescription receipt" not in text:
        return "both drop-box actions must appear"
    if "ALL matching" not in text:
        return "injection must tell choose to do every matching handle"
    if "Pick up the handout packet" in text or "Email the room change note" in text:
        return "cubby rows leaked into drop-box due block"
    pending_text = s._format_injection(
        time_hits=[],
        event_hits=[],
        channel_hits=[],
        channel_needed=[],
        today_pending=[slip, receipt, soap],
        day="Wednesday",
        time_str="",
    )
    if "[lab drop box]" not in pending_text:
        return f"EVENT pending should still group shared cues: {pending_text}"
    if "do ALL rows that share that cue" not in pending_text:
        return "EVENT pending header should say do all shared-cue rows"
    return None


def case_shared_cue_rejects_generic_unigram() -> str | None:
    """'email' alone must not glue two different mail cues."""
    s = _store()
    vendor = _intent(
        intent_id="vendor",
        action="Forward the vendor reply",
        due=DueSlot(day="Tuesday"),
        event_cue="the email lands",
    )
    confirm = _intent(
        intent_id="confirm",
        action="Save the receipt",
        due=DueSlot(day="Tuesday"),
        event_cue="the confirmation email arrives",
    )
    expanded = s._expand_event_due_ids([vendor, confirm], {"vendor"})
    if expanded != {"vendor"}:
        return f"email unigram fanout={expanded}, expected vendor only"
    return None


def case_done_meal_slots_stay_distinct() -> str | None:
    """Breakfast choose must not close the dinner antibiotic row."""
    s = _store()
    s.intentions["abx_b"] = _intent(
        intent_id="abx_b",
        action="Take antibiotic",
        due=DueSlot(day="Monday"),
        event_cue="breakfast",
    )
    s.intentions["abx_d"] = _intent(
        intent_id="abx_d",
        action="Take antibiotic",
        due=DueSlot(day="Monday"),
        event_cue="dinner",
    )
    n = s._mark_done_by_choice(
        ["Take antibiotic at breakfast."], day="Monday"
    )
    if n != 1:
        return f"breakfast choose hits={n}, expected 1"
    if s.intentions["abx_b"].status != "done":
        return "breakfast row should be done"
    if s.intentions["abx_d"].status != "pending":
        return f"dinner was {s.intentions['abx_d'].status}; same-action event slots must stay split"
    return None


def case_override_hhmm_becomes_reschedule() -> str | None:
    """Judge override with new_trigger=HH:MM is a clock rewrite."""
    s = _store()
    s.intentions["pick"] = _intent(
        intent_id="pick",
        action="Confirm the pickup window",
        due=DueSlot(day="Thursday", time="19:10"),
    )
    s._judge_index_to_id = {1: "pick"}
    s._apply_update_patches(
        [
            {
                "n": 1,
                "action": "override",
                "new_time": None,
                "new_day": None,
                "new_trigger": "20:40",
                "new_action": None,
                "rationale": "timing shifted",
            }
        ],
        day="Thursday",
        time_str="",
    )
    got = s.intentions["pick"]
    if got.status != "pending":
        return f"status={got.status}"
    if got.due.time != "20:40":
        return f"due.time={got.due.time!r}, expected 20:40"
    if (got.event_cue or "").strip() == "20:40":
        return "clock rewrite must not become event_cue=20:40"
    return None


def case_override_notice_not_event_due() -> str | None:
    """Announcing a new cue is override, not this-step DUE."""
    s = _store()
    s.use_llm_match = True
    s.intentions["filt"] = _intent(
        intent_id="filt",
        action="Pick up the replacement filter",
        due=DueSlot(day="Monday"),
        event_cue="the hardware counter clears",
    )
    s._judge_index_to_id = {1: "filt"}
    notice = (
        "You get a follow-up with corrected instructions for pick up the "
        "replacement filter. Instead of the earlier cue, watch for the "
        "follow-up text before you pick up the replacement filter."
    )
    s._apply_update_patches(
        [
            {
                "n": 1,
                "action": "override",
                "new_time": None,
                "new_day": None,
                "new_trigger": "the follow-up text arrives",
                "new_action": None,
                "rationale": "new later condition",
            }
        ],
        day="Monday",
        time_str="",
    )
    s._last_update_obs_key = f"Monday|{notice}"
    split = s._match_event_channel(
        [s.intentions["filt"]],
        observation=notice,
        day="Monday",
        time_str="",
        messages=[],
    )
    due = {i.intent_id for i in split["event_due"]}
    if "filt" in due:
        return "override notice must not stamp the rewritten cue due"
    later = "A follow-up text comes in with the final location."
    split2 = s._match_event_channel(
        [s.intentions["filt"]],
        observation=later,
        day="Monday",
        time_str="",
        messages=[],
    )
    due2 = {i.intent_id for i in split2["event_due"]}
    if due2 != {"filt"}:
        return f"actual follow-up text should due, got {due2}"
    return None


def case_event_sim_rejects_boilerplate_notice() -> str | None:
    """'you notice the lab cubby' must not match 'you notice the laundry cart'."""
    s = _store()
    notice = (
        "You leave yourself a note: On Friday, Carry the laundry soap when "
        "you notice the laundry room cart."
    )
    score = s._event_similarity("you notice the lab cubby", notice)
    if score >= s._event_sim_threshold:
        return f"lab cubby vs laundry notice score={score}, expected below threshold"
    fire = "You notice the lab cubby has the handout packet tucked inside it."
    hit = s._event_similarity("you notice the lab cubby", fire)
    if hit < s._event_sim_threshold:
        return f"true lab cubby cue score={hit}, expected a hit"
    return None


def case_menu_paraphrase_still_injected() -> str | None:
    """v4: 0.34 menu overlap used to drop paraphrased pending; choose aligns now."""
    s = _store()
    filt = _intent(
        intent_id="filter",
        action="Pick up the replacement filter",
        due=DueSlot(day="Tuesday"),
        event_cue="the follow-up text arrives",
    )
    s.intentions[filt.intent_id] = filt
    menu_label = "Collect the HVAC filter from the hardware store"
    score = s._overlap_score(menu_label, filt.action)
    if score >= 0.34:
        return f"fixture too similar to menu (overlap={score:.2f}); need < 0.34"
    text = s._format_injection(
        time_hits=[],
        event_hits=[],
        channel_hits=[],
        channel_needed=[],
        today_pending=[filt],
        day="Tuesday",
        time_str="",
    )
    if "Pick up the replacement filter" not in text:
        return "paraphrased today pending was not injected"
    if "menu-aligned" in text.lower():
        return "old menu-aligned gate label still present"
    return None


def case_compact_strips_day_plan() -> str | None:
    """Intention compact prompt keeps weekday, drops the stale morning list."""
    messages = [
        {"role": "system", "content": "You are taking a prospective memory evaluation."},
        {
            "role": "user",
            "content": "Regular tasks for every day:\n- Take antibiotic at breakfast.",
        },
        {
            "role": "user",
            "content": (
                "=== Monday ===\n"
                "Today's loose plan:\n"
                "- Return the library book when the return slot is open."
            ),
        },
        {
            "role": "user",
            "content": (
                "The library return slot is open as you walk by.\n"
                "A) Make a note\n"
                "Step action menu:\n"
                "- task_3: Return the library book."
            ),
        },
    ]
    kept = build_compact_messages(messages, include_day_plan=True)
    plan_msgs = [m["content"] for m in kept if "loose plan" in m.get("content", "")]
    if not plan_msgs:
        return "include_day_plan=True should keep the morning list"
    stripped = build_compact_messages(messages, include_day_plan=False)
    joined = "\n".join(m.get("content") or "" for m in stripped)
    header = next(
        (m["content"] for m in stripped if m.get("content", "").startswith("=== ")),
        "",
    )
    if "return slot" in header.lower():
        return "stale plan when-clause still in day header"
    if "=== Monday ===" not in joined:
        return "weekday header was dropped"
    if "Regular tasks for every day" not in joined:
        return "standing daily tasks should stay"
    if "The library return slot is open" not in joined:
        return "current vignette must remain"
    return None


class _FakeJudgeClient:
    """OpenAI-shaped stub: chat.completions.create → JSON payload."""

    def __init__(self, payload: dict):
        self._payload = payload
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        msg = type("Msg", (), {"content": json.dumps(self._payload)})()
        choice = type("Choice", (), {"message": msg})()
        return type("Resp", (), {"choices": [choice]})()


def _rewrite_store(payload: dict) -> IntentionStoreBackend:
    client = _FakeJudgeClient(payload)
    return IntentionStoreBackend(
        llm_client=client,
        llm_model="stub-rewrite",
        use_llm_update=False,
        use_llm_extract=False,
        use_llm_done=False,
        use_llm_match=False,
        llm_response_format="json_object",
    )


def case_rewrite_prompt_is_schema_not_dataset() -> str | None:
    """Style rewrite must describe the target format, not a week's tasks."""
    p = INTENTION_REWRITE_PROMPT.lower()
    for banned in (
        "asthma",
        "antibiotic",
        "11:00 and 21:00",
        "library email",
        "11:50",
    ):
        if banned in p:
            return f"rewrite prompt still names {banned!r}"
    if "dash" not in p and "bullet" not in p:
        return "rewrite prompt should mention dash bullets"
    if "when" not in p:
        return "rewrite prompt should mention when-clauses"
    return None


def case_rewrite_off_keeps_regex() -> str | None:
    s = _store()
    s._extract_from_text(
        "- Send the library email at 11:50.",
        day="Monday",
    )
    rows = [i for i in s.intentions.values() if "library email" in i.action.lower()]
    if len(rows) != 1:
        return f"expected 1 regex row, got {len(rows)}"
    if s.last_rewrite_info.get("mode") != "off":
        return f"rewrite should be off, got {s.last_rewrite_info}"
    return None


def case_rewrite_then_regex_plants() -> str | None:
    """Informal prose is rewritten into bullets, then regex plants."""
    s = _rewrite_store(
        {
            "text": (
                "Today's loose plan:\n"
                "- Send the library email at 11:50\n"
                "- Return the library book when the return slot is open"
            )
        }
    )
    s._extract_from_text(
        "Don't forget to shoot the library an email around 11:50, "
        "and drop the book off once the return slot is open.",
        day="Monday",
    )
    actions = [i.action.lower() for i in s.intentions.values()]
    if not any("library email" in a for a in actions):
        return f"rewritten clock row missing: {actions}"
    if not any("library book" in a for a in actions):
        return f"rewritten event row missing: {actions}"
    times = [i.due.time for i in s.intentions.values() if i.due.time]
    if "11:50" not in times:
        return f"clock not planted from rewrite: {times}"
    if s.last_rewrite_info.get("mode") != "llm":
        return f"expected rewrite llm, got {s.last_rewrite_info}"
    return None


def case_rewrite_fail_open_keeps_regex() -> str | None:
    class _Bad:
        def __init__(self):
            self.chat = self

        @property
        def completions(self):
            return self

        def create(self, **kwargs):
            raise RuntimeError("rewrite down")

    s = IntentionStoreBackend(
        llm_client=_Bad(),
        llm_model="stub-rewrite",
        use_llm_update=False,
        llm_response_format="json_object",
    )
    s._extract_from_text(
        "- Pick up the hold when the library notice says it is ready.",
        day="Monday",
    )
    if len(s.intentions) != 1:
        return f"fail-open should keep regex row, got {len(s.intentions)}"
    if s.last_rewrite_info.get("mode") != "fail_open":
        return f"expected fail_open, got {s.last_rewrite_info}"
    return None


def case_update_schema_has_scene_cues() -> str | None:
    schema = IntentionStoreBackend._update_judge_schema(3)
    if "scene_cues" not in (schema.get("properties") or {}):
        return "update schema missing scene_cues"
    required = schema.get("required") or []
    if "scene_cues" not in required:
        return f"scene_cues not required: {required}"
    return None


def case_scene_cues_used_as_haystack() -> str | None:
    """Paraphrased vignette still dues after Update Judge rewrites scene_cues."""
    s = _store()
    s.use_llm_match = True
    s.intentions["mail"] = _intent(
        intent_id="mail",
        action="File the vendor reply",
        due=DueSlot(day="Tuesday"),
        event_cue="the confirmation email arrives",
    )
    raw = "Your inbox just pinged with the vendor's OK."
    s._last_scene_cues = ["the confirmation email arrives"]
    hay = s._vignette_for_event_match(raw)
    if "confirmation email" not in hay.lower():
        return f"scene_cues not in haystack: {hay!r}"
    score = s._event_similarity("the confirmation email arrives", hay)
    if score < s._event_sim_threshold:
        return f"rewritten cue should match, score={score}"
    raw_score = s._event_similarity("the confirmation email arrives", raw)
    if raw_score >= s._event_sim_threshold:
        return "raw paraphrase should stay below threshold so the rewrite matters"
    return None


def _rag_store() -> IntentionStoreBackend:
    return IntentionStoreBackend(
        use_llm_update=False,
        use_llm_extract=False,
        use_llm_done=False,
        use_llm_match=False,
        retrieval_mode="similarity",
        embed_fn=None,
    )


def case_default_retrieval_is_due() -> str | None:
    """Main experiment must not switch to PIS-RAG unless the flag is set."""
    s = _store()
    if getattr(s, "retrieval_mode", None) != "due":
        return f"default retrieval_mode={getattr(s, 'retrieval_mode', None)}"
    if s.memory_inject_header != INTENTION_MEMORY_INJECT_HEADER:
        return "default inject header must stay the due-path guide"
    if "TIME-DUE" not in s.memory_inject_header:
        return "due-path header lost TIME-DUE"
    return None


def case_rag_skips_due_labels() -> str | None:
    """Similarity recall injects flattened records, never TIME-DUE / CHECK."""
    s = _rag_store()
    s.apply_observation_updates = lambda *a, **k: 0
    s.intentions["med"] = _intent(
        intent_id="med",
        action="Take asthma medication",
        due=DueSlot(day="Saturday", time="21:00"),
    )
    s.intentions["tube"] = _intent(
        intent_id="tube",
        action="Pick up the poster tube",
        due=DueSlot(day="Saturday"),
        event_cue="tube on the shelf",
    )
    text = s.recall(
        "There is a cardboard tube on the shelf.",
        top_k=5,
        context={
            "day": "Saturday",
            "step": "s6",
            "time": "21:00",
            "observation": "There is a cardboard tube on the shelf.",
            "messages": [],
        },
    )
    for banned in (
        "[TIME-DUE]",
        "TIME-WAIT",
        "MUST check_time",
        "CHECK channels",
        "[DUE]",
        "TODAY pending",
    ):
        if banned in text:
            return f"rag injection still has {banned!r}"
    if "status=" not in text or "action=" not in text:
        return "rag injection should serialize typed fields"
    if s.last_recall_info.get("force_check_time"):
        return "similarity recall must not set force_check_time"
    if s.last_recall_info.get("channel_needed"):
        return "similarity recall must not inject CHECK"
    if s.last_recall_info.get("retrieval_mode") != "similarity":
        return "recall info missing retrieval_mode=similarity"
    if s.memory_inject_header != INTENTION_RAG_MEMORY_INJECT_HEADER:
        return "rag header not selected"
    if "TIME-DUE" in s.memory_inject_header:
        return "rag choose-header still describes TIME-DUE"
    return None


def case_source_due_reads_sentence_not_fields() -> str | None:
    """Source-due TIME-DUE uses the planting sentence clock, not due.time."""
    s = IntentionStoreBackend(
        use_llm_update=False,
        use_llm_extract=False,
        use_llm_done=False,
        use_llm_match=True,
        retrieval_mode="source",
    )
    s.apply_observation_updates = lambda *a, **k: 0
    s.intentions["med"] = _intent(
        intent_id="med",
        action="Take asthma medication",
        due=DueSlot(day="Monday", time="11:00"),
        event_cue="should not drive time",
        source="Take asthma medication at 21:00",
    )
    s.intentions["decoy"] = _intent(
        intent_id="decoy",
        action="Pick up the poster tube",
        due=DueSlot(day="Monday", time="21:00"),
        event_cue="",
        source="Pick up the poster tube when you notice the shelf",
    )
    text = s.recall(
        "quiet morning",
        context={
            "day": "Monday",
            "step": "s1",
            "time": "21:00",
            "observation": "A quiet evening at the desk.",
            "messages": [],
        },
    )
    if s.last_recall_info.get("retrieval_mode") != "source":
        return "recall info missing retrieval_mode=source"
    if s.last_recall_info.get("time_hits") != 1:
        return f"source TIME-DUE should hit only the sentence with 21:00, got {s.last_recall_info}"
    if "Take asthma medication at 21:00" not in text:
        return "injection should show the source sentence, not typed fields"
    if "should not drive time" in text:
        return "source-due injection leaked field event_cue"
    return None


def case_source_default_due_ignores_source() -> str | None:
    """Main due path still matches due.time even if source disagrees."""
    s = _store()
    s.use_llm_match = True
    s.apply_observation_updates = lambda *a, **k: 0
    s.intentions["med"] = _intent(
        intent_id="med",
        action="Take asthma medication",
        due=DueSlot(day="Monday", time="11:00"),
        source="Take asthma medication at 21:00",
    )
    s.recall(
        "quiet",
        context={
            "day": "Monday",
            "step": "s1",
            "time": "21:00",
            "observation": "A quiet evening at the desk.",
            "messages": [],
        },
    )
    if s.last_recall_info.get("time_hits"):
        return "due path must not TIME-DUE from source when due.time is 11:00"
    if getattr(s, "retrieval_mode", None) != "due":
        return "default store is not due"
    return None


def case_rag_pool_includes_done() -> str | None:
    """Candidate pool is the whole store; done pickups can still rank."""
    tube = _intent(
        intent_id="tube",
        action="Pick up the poster tube",
        due=DueSlot(day="Saturday"),
        event_cue="tube on the shelf",
    )
    parcel = _intent(
        intent_id="parcel",
        action="Collect the parcel",
        status="done",
        due=DueSlot(day="Thursday"),
        event_cue="parcel on the shelf",
    )
    inhaler = _intent(
        intent_id="med",
        action="Take asthma medication",
        due=DueSlot(day="Saturday", time="21:00"),
    )
    hits = retrieve_intentions(
        "cardboard tube on the shelf",
        [tube, parcel, inhaler],
        top_k=3,
        embed_fn=None,
    )
    ids = [h["intent"].intent_id for h in hits]
    if "tube" not in ids:
        return f"tube should rank, got {ids}"
    if "parcel" not in ids:
        return f"done parcel must stay in the pool, got {ids}"
    if ids[0] != "tube":
        return f"tube should be top-1 for a tube query, got {ids}"
    if "status=done" not in serialize_intention(parcel):
        return "done rows must serialize status"
    return None


def case_due_path_recall_still_time_due() -> str | None:
    """Due-path recall (no flag) still stamps TIME-DUE; rag must not leak here."""
    s = _store()
    s.apply_observation_updates = lambda *a, **k: 0
    s.intentions["med"] = _intent(
        intent_id="med",
        action="Take asthma medication",
        due=DueSlot(day="Monday", time="11:00"),
    )
    text = s.recall(
        "You are at your desk.",
        top_k=5,
        context={
            "day": "Monday",
            "step": "s2",
            "time": "11:00",
            "observation": "You are at your desk.",
            "messages": [],
        },
    )
    if "TIME-DUE" not in text:
        return "due-path recall lost TIME-DUE"
    if "PIS-RAG" in text:
        return "due-path recall used the rag injection"
    if s.last_recall_info.get("retrieval_mode") == "similarity":
        return "due-path last_recall_info looks like rag"
    return None


CASES = {
    "update": [
        ("scene_judge_semantic_test", case_scene_judge_asks_if_action_survives),
        ("cancel_precision", case_cancel_does_not_kill_unrelated),
        ("cue_firing_not_cancel", case_cue_firing_cancel_is_blocked),
        ("cue_firing_not_override", case_cue_firing_override_blocked),
        ("clock_change_retarget", case_clock_change_retargets_named_row),
        ("cancel_new_trigger_override", case_cancel_with_new_trigger_becomes_override),
        ("true_void_still_cancels", case_true_void_still_cancels),
        ("reschedule_time", case_reschedule_rewrites_due_time),
        ("override_hhmm_reschedule", case_override_hhmm_becomes_reschedule),
        ("override_notice_not_due", case_override_notice_not_event_due),
        ("day_change_keeps_pending", case_day_change_does_not_cancel_pending),
        ("parse_think", case_parse_strips_think_tags),
        ("parse_fence", case_parse_json_in_prose),
        ("compact_strips_plan", case_compact_strips_day_plan),
    ],
    "time": [
        ("time_due_exact", case_time_due_needs_trusted_clock),
        ("clock_stays_pending", case_unmatched_clock_is_today_pending),
        ("time_due_include_all", case_time_due_header_asks_for_all_matches),
        ("time_wait_gated", case_time_wait_when_gated),
        ("gate_strips_undue", case_gate_strips_undue_clock_and_keeps_event),
        ("force_query_must", case_force_query_must_line),
        ("cue_match_hides_action", case_cue_match_listing_hides_action),
        ("channel_watch_union", case_channel_watch_union_must_query),
        ("event_match_waits_channel", case_event_match_waits_for_channel_query),
        ("rich_cue_vignette", case_rich_cue_may_match_vignette),
        ("match_after_one_watch", case_match_after_one_of_several_watches),
        ("no_narrative_clock", case_narrative_hhmm_is_not_clock),
        ("asthma_slots", case_asthma_two_slots_not_merged),
        ("no_insert_dedup", case_duplicate_inserts_not_merged),
        ("daily_event_no_due", case_daily_event_meds_have_no_due_day),
        ("filter_trace", case_filter_trace_drops_future_not_event),
    ],
    "cross_day": [
        ("day_change_keeps_pending", case_day_change_does_not_cancel_pending),
        ("event_pending_section", case_event_pending_section_visible),
        ("shared_cue_fanout", case_shared_cue_fanout_and_group),
        ("cross_day_on_clause", case_cross_day_on_clause_keeps_due_day),
        ("calendar_on_clause", case_calendar_on_clause_keeps_due_day),
        ("event_no_due_leftover", case_event_no_due_survives_leftover),
    ],
    "event": [
        ("menu_paraphrase_injected", case_menu_paraphrase_still_injected),
        ("event_pending_section", case_event_pending_section_visible),
        ("event_plan_no_due", case_event_plan_bullet_has_no_due),
        ("extract_strips_plant_day", case_extract_item_strips_planting_day),
        ("event_no_due_leftover", case_event_no_due_survives_leftover),
        ("daily_event_no_due", case_daily_event_meds_have_no_due_day),
        ("cross_day_on_clause", case_cross_day_on_clause_keeps_due_day),
        ("filter_trace", case_filter_trace_drops_future_not_event),
        ("match_event_channel", case_match_filter_drops_unmatched_event),
        ("event_match_waits_channel", case_event_match_waits_for_channel_query),
        ("rich_cue_vignette", case_rich_cue_may_match_vignette),
        ("match_after_one_watch", case_match_after_one_of_several_watches),
        ("event_similarity_no_action", case_event_similarity_ignores_action),
        ("cue_match_hides_action", case_cue_match_listing_hides_action),
        ("shared_cue_fanout", case_shared_cue_fanout_and_group),
        ("shared_cue_unigram", case_shared_cue_rejects_generic_unigram),
        ("event_boilerplate", case_event_sim_rejects_boilerplate_notice),
        ("override_notice_not_due", case_override_notice_not_event_due),
        ("cue_firing_not_cancel", case_cue_firing_cancel_is_blocked),
    ],
    "false_alarm": [
        ("menu_paraphrase_injected", case_menu_paraphrase_still_injected),
        ("done_by_n", case_done_marks_by_n_not_overlap),
    ],
    "done": [
        ("done_by_n", case_done_marks_by_n_not_overlap),
        ("done_skip_empty", case_done_empty_labels_skips),
        ("done_exact_not_fuzzy", case_done_exact_not_fuzzy),
        ("done_substring_union", case_done_substring_union),
        ("done_meal_slots", case_done_meal_slots_stay_distinct),
    ],
    "rewrite": [
        ("rewrite_prompt_schema", case_rewrite_prompt_is_schema_not_dataset),
        ("rewrite_off", case_rewrite_off_keeps_regex),
        ("rewrite_then_regex", case_rewrite_then_regex_plants),
        ("rewrite_fail_open", case_rewrite_fail_open_keeps_regex),
        ("update_schema_scene_cues", case_update_schema_has_scene_cues),
        ("scene_cues_haystack", case_scene_cues_used_as_haystack),
    ],
    "rag": [
        ("default_retrieval_due", case_default_retrieval_is_due),
        ("due_path_still_time_due", case_due_path_recall_still_time_due),
        ("rag_skips_due_labels", case_rag_skips_due_labels),
        ("rag_pool_includes_done", case_rag_pool_includes_done),
        ("source_due_sentence", case_source_due_reads_sentence_not_fields),
        ("source_due_default_ignores", case_source_default_due_ignores_source),
    ],
}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--family",
        choices=["all", *CASES.keys()],
        default="all",
        help="Only run probes for this failure family (from analyze_intention_run)",
    )
    args = p.parse_args()
    selected = []
    if args.family == "all":
        seen = set()
        for group in CASES.values():
            for name, fn in group:
                if name not in seen:
                    selected.append((name, fn))
                    seen.add(name)
    else:
        selected = list(CASES[args.family])

    failed = 0
    for name, fn in selected:
        err = fn()
        if err:
            print(f"FAIL {name}: {err}")
            failed += 1
        else:
            print(f"ok   {name}")
    if failed:
        print(f"{failed}/{len(selected)} failed")
        return 1
    print(f"{len(selected)} probes passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
