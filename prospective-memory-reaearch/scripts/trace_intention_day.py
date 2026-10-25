#!/usr/bin/env python3
"""Rebuild a fine-grained Monday (or any day) pipeline trace vs PM-Bench GT.

Does not call an LLM. Reads an existing intention run + the scenario JSON.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "code"
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

from pm_memory.intention_store import (  # noqa: E402
    CHANNEL_HINTS,
    Intention,
    IntentionStoreBackend,
    _AT_TIME_RE,
    _CROSS_DAY_RE,
    _PLAN_BULLET_RE,
    _TIME_RE,
    _WHEN_RE,
)

STOP = {
    "a", "an", "the", "to", "of", "and", "or", "for", "on", "in", "at",
    "when", "your", "you", "with", "is", "it", "be", "do",
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", required=True, help="Run directory or *.score.md")
    p.add_argument("--day", default="Monday")
    p.add_argument(
        "--scenario",
        default=str(ROOT / "data" / "PMBench" / "data" / "synthetic_week_v9.json"),
    )
    p.add_argument("--out", default=None, help="Write JSON here")
    return p.parse_args()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _tokens(text: str) -> set[str]:
    return {
        t
        for t in re.findall(r"[a-z0-9$]+", (text or "").lower())
        if t not in STOP and len(t) > 1
    }


def _jaccard_error(gold: list[str], pred: list[str]) -> float:
    g, p = set(gold), set(pred)
    if not g and not p:
        return 0.0
    return round(100.0 * len(g ^ p) / len(g | p), 1)


def _brief(intent: dict[str, Any] | Intention) -> dict[str, Any]:
    if isinstance(intent, Intention):
        return {
            "id": intent.intent_id,
            "action": intent.action,
            "status": intent.status,
            "due_day": intent.due.day or "",
            "due_time": intent.due.time or "",
            "event": intent.event_cue or "",
            "watch": list(intent.watch or []),
        }
    due = intent.get("due") if isinstance(intent.get("due"), dict) else {}
    return {
        "id": intent.get("intent_id") or intent.get("id") or "",
        "action": intent.get("action") or "",
        "status": intent.get("status") or "pending",
        "due_day": str(due.get("day") or intent.get("due_day") or ""),
        "due_time": str(due.get("time") or intent.get("due_time") or ""),
        "event": intent.get("event_cue") or intent.get("event") or "",
        "watch": list(intent.get("watch") or []),
    }


def _map_task(
    brief: dict[str, Any],
    tasks: list[dict[str, Any]],
    extra: dict[str, str] | None = None,
) -> str:
    act = (brief.get("action") or "").lower()
    event = (brief.get("event") or "").lower()
    due_t = brief.get("due_time") or ""
    if extra:
        key = f"{act}|{due_t}|{event}"
        if key in extra:
            return extra[key]
    if "antibiotic" in act:
        if "breakfast" in event:
            return "antibiotic_breakfast"
        if "dinner" in event:
            return "antibiotic_dinner"
    if "asthma" in act:
        if due_t == "11:00":
            return "asthma_1100"
        if due_t == "21:00":
            return "asthma_2100"
    best, score = "", 0.0
    ta = _tokens(f"{act} {event}")
    for task in tasks:
        blob = f"{task.get('action_text') or ''} {task.get('label') or ''}"
        tb = _tokens(blob)
        if not ta or not tb:
            continue
        s = len(ta & tb) / float(min(len(ta), len(tb)))
        tgt = str(task.get("target_time") or "")
        if due_t and tgt == due_t:
            s += 0.25
        if event and (task.get("cue_id") or "").lower() in event:
            s += 0.15
        if s > score:
            best, score = str(task.get("id") or ""), s
    if score >= 0.45:
        return best
    if "referral" in act or "clinic check-in" in event:
        return "crossday_thursday_referral"
    return ""


def _regex_rules() -> list[dict[str, str]]:
    return [
        {
            "name": "_PLAN_BULLET_RE",
            "pattern": _PLAN_BULLET_RE.pattern,
            "role": "日计划每一行 `- …` 子弹 → 一条意图",
        },
        {
            "name": "_CROSS_DAY_RE",
            "pattern": _CROSS_DAY_RE.pattern,
            "role": "日计划正文里的 `On Thursday, …`（只跑日计划，不跑 vignette）",
        },
        {
            "name": "_WHEN_RE",
            "pattern": _WHEN_RE.pattern,
            "role": "`when …` → event_cue；同时从 action 里剥掉",
        },
        {
            "name": "_AT_TIME_RE",
            "pattern": _AT_TIME_RE.pattern,
            "role": "`at HH:MM` → due.time；同时从 action 里剥掉",
        },
        {
            "name": "_TIME_RE",
            "pattern": _TIME_RE.pattern,
            "role": "规范化 HH:MM",
        },
        {
            "name": "CHANNEL_HINTS",
            "pattern": " | ".join(
                f"{name}: {', '.join(hints[:3])}"
                for name, hints in CHANNEL_HINTS.items()
                if name != "clock"
            ),
            "role": "子弹/when 子串命中 → watch 列表",
        },
    ]


def _replay_regex(plan_lines: list[str], day: str) -> list[dict[str, Any]]:
    backend = IntentionStoreBackend(store_path=None)
    rows = []
    for raw in plan_lines:
        line = raw.strip()
        bullet = _PLAN_BULLET_RE.match(line)
        body = bullet.group(1).strip() if bullet else ""
        cross = list(_CROSS_DAY_RE.finditer(line))
        when = _WHEN_RE.search(body or line)
        at_time = _AT_TIME_RE.search(body or line)
        if not body and not cross:
            rows.append(
                {
                    "raw": raw,
                    "kind": "skip",
                    "why": "不是子弹、也不是 On <Day>",
                    "stored": None,
                }
            )
            continue
        if body.lower().startswith("today's loose plan") or body.lower().startswith(
            "regular tasks"
        ):
            rows.append(
                {
                    "raw": raw,
                    "kind": "skip",
                    "why": "标题行，代码故意跳过",
                    "stored": None,
                }
            )
            continue
        intent = backend._parse_intention_line(body or line, day=day)
        stored = _brief(intent) if intent else None
        rows.append(
            {
                "raw": raw,
                "kind": "bullet",
                "groups": {
                    "bullet_body": body,
                    "when": when.group(1).strip().rstrip(".") if when else "",
                    "at_time": at_time.group(1) if at_time else "",
                    "watch": stored["watch"] if stored else [],
                    "action": stored["action"] if stored else "",
                    "due_day": stored["due_day"] if stored else "",
                    "due_time": stored["due_time"] if stored else "",
                    "event": stored["event"] if stored else "",
                },
                "stored": stored,
            }
        )
    return rows


def _gold_regex_items(plan_lines: list[str], tasks: list[dict[str, Any]], day: str) -> list[str]:
    gold = []
    backend = IntentionStoreBackend(store_path=None)
    for raw in plan_lines:
        m = _PLAN_BULLET_RE.match(raw.strip())
        if not m:
            continue
        body = m.group(1).strip()
        if len(body) < 6 or body.lower().startswith("today's"):
            continue
        intent = backend._parse_intention_line(body, day=day)
        if intent is None:
            continue
        tid = _map_task(_brief(intent), tasks)
        gold.append(tid or intent.action)
    return gold


def _stage(
    name: str,
    gold: list[str],
    pred: list[str],
    *,
    note: str = "",
    rows: list[dict[str, Any]] | None = None,
    actor: str = "code",
) -> dict[str, Any]:
    g, p = list(dict.fromkeys(gold)), list(dict.fromkeys(pred))
    hit = sorted(set(g) & set(p))
    miss = sorted(set(g) - set(p))
    extra = sorted(set(p) - set(g))
    return {
        "name": name,
        "actor": actor,
        "gold": g,
        "pred": p,
        "hit": hit,
        "miss": miss,
        "extra": extra,
        "error_pct": _jaccard_error(g, p),
        "note": note,
        "rows": rows or [],
    }


def _intent_ids(items: list[Any]) -> list[str]:
    out = []
    for item in items or []:
        if isinstance(item, dict):
            out.append(str(item.get("id") or item.get("intent_id") or item.get("action") or ""))
        else:
            out.append(str(item))
    return [x for x in out if x]


def _store_diff(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> list[dict[str, str]]:
    b = {i["id"]: i for i in before}
    a = {i["id"]: i for i in after}
    diffs = []
    for iid, row in a.items():
        if iid not in b:
            diffs.append(
                {
                    "id": iid,
                    "change": "add",
                    "detail": f"+ {row['action']} due={row['due_day']} {row['due_time']} event={row['event']}",
                }
            )
            continue
        old = b[iid]
        bits = []
        for key in ("status", "action", "due_day", "due_time", "event"):
            if old.get(key) != row.get(key):
                bits.append(f"{key}: {old.get(key) or '∅'} → {row.get(key) or '∅'}")
        if old.get("watch") != row.get("watch"):
            bits.append(f"watch: {old.get('watch')} → {row.get('watch')}")
        if bits:
            diffs.append({"id": iid, "change": "patch", "detail": "; ".join(bits)})
    for iid, row in b.items():
        if iid not in a:
            diffs.append({"id": iid, "change": "drop", "detail": f"- {row['action']}"})
    return diffs


def _last_recall(recalls: list[dict[str, Any]]) -> dict[str, Any] | None:
    return recalls[-1] if recalls else None


def main() -> int:
    args = _parse_args()
    run = Path(args.run)
    if run.is_file():
        run = run.parent
    scores = list(run.glob("*.score.md")) + list(run.rglob("*.score.md"))
    if not scores:
        print(f"no score.md under {run}", file=sys.stderr)
        return 1
    score_path = max(scores, key=lambda p: p.stat().st_mtime)
    stem = score_path.name.replace(".score.md", "")
    steps = _load_jsonl(score_path.with_name(f"{stem}.intentions.steps.jsonl"))
    choices = _load_jsonl(score_path.with_name(f"{stem}.jsonl"))
    memory = _load_jsonl(score_path.with_name(f"{stem}.memory.jsonl"))
    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    day_obj = next(
        (d for d in scenario.get("days") or [] if d.get("name") == args.day), None
    )
    if day_obj is None:
        print(f"day {args.day} not in scenario", file=sys.stderr)
        return 1

    tasks = list(day_obj.get("tasks") or [])
    plan_lines = list(day_obj.get("start_instructions") or [])
    day_steps = [s for s in (day_obj.get("steps") or [])]
    choice_by = {
        r["step_id"]: r
        for r in choices
        if r.get("day") == args.day and r.get("step_id")
    }

    backend = IntentionStoreBackend(store_path=None)
    daily_specs = [
        ("Take antibiotic", "", "breakfast", "antibiotic_breakfast"),
        ("Take antibiotic", "", "dinner", "antibiotic_dinner"),
        ("Take asthma medication", "11:00", "", "asthma_1100"),
        ("Take asthma medication", "21:00", "", "asthma_2100"),
    ]
    daily_planted = [
        {
            "action": a,
            "due_time": t,
            "event": e,
            "task_id": tid,
            "kind": "hardcoded",
        }
        for a, t, e, tid in daily_specs
    ]
    regex_rows = _replay_regex(plan_lines, args.day)
    regex_pred = [
        _map_task(r["stored"], tasks) or r["stored"]["action"]
        for r in regex_rows
        if r.get("stored")
    ]
    regex_gold = _gold_regex_items(plan_lines, tasks, args.day)
    # Gold for day-plan bullets is the irregular start-encoded tasks.
    plan_gold = [
        t["id"]
        for t in tasks
        if not t.get("regular") and t.get("encoding") == "start"
    ]

    step_out: list[dict[str, Any]] = []
    prev_store: list[dict[str, Any]] = []
    id_to_task: dict[str, str] = {}

    def bind_store(items: list[dict[str, Any]]) -> None:
        for row in items:
            tid = _map_task(row, tasks)
            if tid:
                id_to_task[row["id"]] = tid
            row["task_id"] = id_to_task.get(row["id"], tid)

    for si, step in enumerate(day_steps, start=1):
        sid = str(step.get("id") or "")
        short = f"s{si}"
        recalls = [
            r
            for r in steps
            if r.get("event") == "recall"
            and r.get("day") == args.day
            and r.get("step") == short
        ]
        encodes = [
            r
            for r in steps
            if r.get("event") == "encode"
            and r.get("day") == args.day
            and r.get("step") == short
        ]
        last = _last_recall(recalls)
        encode = encodes[-1] if encodes else None
        if last is None:
            continue
        store_after = [_brief(i) for i in (last.get("intentions") or [])]
        bind_store(store_after)
        ft = last.get("filter_trace") or {}
        rec = last.get("recall") or {}
        scores_map = rec.get("match_scores") or {}
        injected = last.get("injected") or ""
        choice = choice_by.get(sid) or {}
        gt_ids = [a["id"] for a in (step.get("groundtruth") or {}).get("actions") or []]
        gt_updates = list(step.get("updates") or [])
        vignette = str(step.get("text") or "")
        clock_true = str(step.get("time") or "")
        clock_seen = str(last.get("time") or "")

        # --- ticks (query loop) ---
        ticks = []
        for i, r in enumerate(recalls, start=1):
            rr = r.get("recall") or {}
            ftt = r.get("filter_trace") or {}
            ticks.append(
                {
                    "i": i,
                    "clock": r.get("time") or "（未知）",
                    "force_check_time": bool(rr.get("force_check_time")),
                    "queried": list(ftt.get("queried_this_step") or []),
                    "check": list(ftt.get("check_channels") or []),
                    "time_due": [x.get("action") for x in (ftt.get("time_due") or [])],
                    "event_due": [x.get("action") for x in (ftt.get("match_event_due") or [])],
                    "channel_due": [
                        x.get("action") for x in (ftt.get("match_channel_due") or [])
                    ],
                    "match_mode": ftt.get("match_mode") or rr.get("match_mode") or "",
                    "choose_pool": rr.get("choose_pool"),
                    "pending": rr.get("pending"),
                }
            )

        # --- daily + regex only first step ---
        stages: list[dict[str, Any]] = []
        if si == 1:
            stages.append(
                _stage(
                    "0. 每日常驻（硬编码，不是正则）",
                    [t[-1] for t in daily_specs],
                    [
                        id_to_task.get(b["id"], b["action"])
                        for b in store_after
                        if b["action"] in ("Take antibiotic", "Take asthma medication")
                    ],
                    note="代码写死 4 条：早餐/晚餐抗生素 + 11:00/21:00 哮喘。不读 scenario GT。",
                    actor="code",
                    rows=daily_planted,
                )
            )
            stages.append(
                _stage(
                    "1. 日计划正则种植",
                    plan_gold,
                    regex_pred,
                    note="只扫 `=== Monday ===` 日计划子弹，不扫 vignette。",
                    actor="code",
                    rows=regex_rows,
                )
            )

        # --- update judge ---
        raw_patches = rec.get("update_raw_patches") or []
        raw_new = rec.get("update_raw_new") or []
        gold_update_verbs = [u.get("action") + ":" + u.get("task_id", "") for u in gt_updates]
        pred_update_verbs = []
        patch_rows = []
        idx = rec.get("update_judge_index") or {}
        for p in raw_patches:
            n = str(p.get("n"))
            iid = idx.get(n) or idx.get(int(n) if str(n).isdigit() else n) or ""
            if not iid and str(n).isdigit():
                iid = idx.get(str(n), "")
            tid = id_to_task.get(iid, "")
            pred_update_verbs.append(f"{p.get('action')}:{tid}")
            patch_rows.append(
                {
                    "n": p.get("n"),
                    "verb": p.get("action"),
                    "new_trigger": p.get("new_trigger"),
                    "new_time": p.get("new_time"),
                    "new_day": p.get("new_day"),
                    "new_action": p.get("new_action"),
                    "rationale": p.get("rationale") or "",
                    "intent_id": iid,
                    "task_id": tid,
                }
            )
        gold_add = []
        for m in _CROSS_DAY_RE.finditer(vignette):
            gold_add.append(f"add:{m.group(1).capitalize()} {m.group(2).strip()[:40]}")
        pred_add = [
            f"add:{(n.get('due_day') or '')} {n.get('action')}" for n in raw_new
        ]
        gold_u = gold_update_verbs + gold_add
        pred_u = pred_update_verbs + pred_add
        stages.append(
            _stage(
                "2. Update Judge（LLM：cancel / reschedule / override / add）",
                gold_u,
                pred_u,
                note="同一调用既改旧条也种新条。cue 触发不是 cancel。vignette 里的 On Thursday 应由 Judge 种，不走正则。",
                actor="llm",
                rows=patch_rows + [{"new": n} for n in raw_new],
            )
        )

        store_before = list(prev_store)
        diffs = _store_diff(store_before, store_after)

        # --- day filter ---
        pending_ids = [x.get("action") for x in (ft.get("pending") or [])]
        kept = [x.get("action") for x in (ft.get("kept_today") or [])]
        dropped = [x.get("action") for x in (ft.get("drop_future_due_day") or [])]
        gold_drop = [
            b["action"]
            for b in store_after
            if b["status"] == "pending"
            and b["due_day"]
            and b["due_day"] != args.day
            and backend._weekday_index(b["due_day"]) is not None
            and backend._weekday_index(args.day) is not None
            and backend._weekday_index(b["due_day"]) > backend._weekday_index(args.day)
        ]
        stages.append(
            _stage(
                "3. 按 due.day 筛掉未来",
                gold_drop,
                dropped,
                note=f"pending {len(pending_ids)} → 留下 {len(kept)}，丢掉未来 due.day {len(dropped)}。空 due.day 不过滤。",
                actor="code",
                rows=[
                    {"kept": kept, "dropped": dropped, "gold_drop": gold_drop}
                ],
            )
        )

        # --- time due ---
        time_due = [x.get("action") + "@" + (x.get("due_time") or "") for x in (ft.get("time_due") or [])]
        time_wait = [
            x.get("action") + "@" + (x.get("due_time") or "")
            for x in (ft.get("time_not_due") or [])
        ]
        gold_time = []
        for t in tasks:
            if t.get("type") != "time":
                continue
            if t.get("id") in gt_ids and t.get("target_time") == clock_true:
                gold_time.append(f"{t.get('action_text','').rstrip('.')}@{t['target_time']}")
        # code-correct TIME-DUE is clock == due.time on pending clock rows
        code_gold_time = []
        for b in store_after:
            if b["status"] != "pending" or not b["due_time"]:
                continue
            if clock_seen and b["due_time"] == clock_seen:
                code_gold_time.append(f"{b['action']}@{b['due_time']}")
        stages.append(
            _stage(
                "4. TIME-DUE（代码：本步时钟 vs due.time，tolerance=0）",
                code_gold_time,
                time_due,
                note=f"场景真钟 {clock_true}；本步代码看见的钟 {clock_seen or '（空）'}。未命中仍进 TODAY pending。GT 本步应收: {gt_ids}。",
                actor="code",
                rows=[
                    {
                        "time_due": time_due,
                        "time_not_due": time_wait,
                        "gt_time": gold_time,
                    }
                ],
            )
        )

        # --- event similarity ---
        event_due = ft.get("match_event_due") or []
        event_drop = ft.get("match_event_drop") or []
        channel_due = ft.get("match_channel_due") or []
        channel_drop = ft.get("match_channel_drop") or []
        channel_wait = ft.get("match_channel_wait") or []
        event_rows = []
        for src, bucket in (
            (event_due, "due"),
            (event_drop, "drop"),
            (channel_due, "channel_due"),
            (channel_drop, "channel_drop"),
            (channel_wait, "channel_wait"),
        ):
            for x in src:
                iid = x.get("id") or ""
                event_rows.append(
                    {
                        "id": iid,
                        "task_id": id_to_task.get(iid, ""),
                        "action": x.get("action"),
                        "event": x.get("event"),
                        "watch": x.get("watch") or [],
                        "score": scores_map.get(iid),
                        "bucket": bucket,
                        "threshold": 0.62,
                    }
                )
        gold_event = []
        for t in tasks:
            if t["id"] not in gt_ids:
                continue
            if t.get("type") == "event" and not t.get("cue_channel"):
                gold_event.append(t["id"])
        pred_event = [
            id_to_task.get(x.get("id"), x.get("action"))
            for x in event_due
        ]
        stages.append(
            _stage(
                "5. EVENT 相似度（只看 event 字符串 vs vignette，阈值 0.62）",
                gold_event,
                [p for p in pred_event if p],
                note="匹配看不见 action / due.time。有 watch 的行必须等 State。改 cue 的说明句如果含新 cue 词，会被当成“线索已出现”。",
                actor="code",
                rows=event_rows,
            )
        )

        gold_channel = [
            t["id"]
            for t in tasks
            if t["id"] in gt_ids and t.get("cue_channel")
        ]
        pred_channel = [
            id_to_task.get(x.get("id"), x.get("action")) for x in channel_due
        ]
        stages.append(
            _stage(
                "6. CHANNEL-DUE（State 子串 vs event_cue；无 State 则 wait）",
                gold_channel,
                [p for p in pred_channel if p],
                actor="code",
                note=f"本步已查: {ft.get('queried_this_step') or []}",
                rows=[
                    {
                        "due": [x.get("action") for x in channel_due],
                        "drop": [x.get("action") for x in channel_drop],
                        "wait": [x.get("action") for x in channel_wait],
                    }
                ],
            )
        )

        check_pred = list(ft.get("check_channels") or [])
        queried_now = {
            str(x).lower()
            for x in (ft.get("queried_this_step") or [])
            if str(x).lower() != "clock"
        }
        # Last recall: CHECK should only still list watches not yet queried this step.
        gold_check = sorted(
            {
                w
                for b in store_after
                if b["status"] == "pending"
                for w in (b.get("watch") or [])
                if w not in queried_now
            }
        )
        stages.append(
            _stage(
                "7. CHECK = 筛选后 watch 并集（注入 MUST query，不改写 choose）",
                gold_check,
                check_pred,
                actor="code",
                note="默认不强制 query_state。force_check_time 只对隐藏时钟。",
            )
        )

        # injection: are GT due task actions visible?
        inj_low = injected.lower()
        gold_inj = []
        pred_inj = []
        inj_rows = []
        for tid in gt_ids:
            task = next((t for t in tasks if t["id"] == tid), None)
            phrase = (task.get("action_text") or task.get("label") or tid).rstrip(".")
            visible = phrase.lower() in inj_low or any(
                b["action"].lower() in inj_low
                for b in store_after
                if id_to_task.get(b["id"]) == tid
            )
            gold_inj.append(tid)
            if visible:
                pred_inj.append(tid)
            inj_rows.append({"task_id": tid, "phrase": phrase, "in_injection": visible})
        stages.append(
            _stage(
                "8. 注入 choose 的记忆块（最后一次 recall）",
                gold_inj,
                pred_inj,
                actor="code",
                note="应能看见本步 GT 对应的 intention 行（TIME-DUE / EVENT / CHANNEL / PENDING）。",
                rows=inj_rows,
            )
        )

        pred_choose = list(choice.get("task_ids") or [])
        stages.append(
            _stage(
                "9. choose 模型点选",
                gt_ids,
                pred_choose,
                actor="llm",
                note=f"choice={choice.get('choice')}  check_time={choice.get('check_time')}  state={choice.get('state_queries')}",
            )
        )

        done_ids = list((encode.get("encode") or {}).get("done_ids") or []) if encode else []
        done_labels = list((encode.get("encode") or {}).get("done_labels") or []) if encode else []
        pred_done = [id_to_task.get(i, i) for i in done_ids]
        stages.append(
            _stage(
                "10. 代码标 done（菜单行 → pending；时钟槽消歧，事件槽不会消歧）",
                gt_ids,
                pred_done,
                actor="code",
                note=f"labels={done_labels}. 同一 action 的 breakfast/dinner 会被一条菜单同时勾掉。",
                rows=[{"done_ids": done_ids, "labels": done_labels}],
            )
        )

        store_encode = [_brief(i) for i in ((encode or {}).get("intentions") or [])]
        bind_store(store_encode)

        verdict = "ok"
        choose_err = stages[-2]["error_pct"]
        if gt_ids and not pred_choose:
            verdict = "miss"
        elif not gt_ids and pred_choose:
            verdict = "false_alarm"
        elif set(gt_ids) != set(pred_choose):
            verdict = "mismatch"
        judge = {
            "verdict": verdict,
            "gt": gt_ids,
            "model": pred_choose,
            "choose_error_pct": choose_err,
            "why": "",
        }
        if sid == "d1_s1" and "antibiotic_dinner" in pred_done:
            judge["why"] = (
                "choose 对了早餐抗生素；标 done 把同一 action 的晚餐槽也勾掉了。"
            )
        elif sid in ("d1_s2", "d1_s8"):
            judge["why"] = (
                "Update Judge 改 cue 是对的，但改写说明句本身含新 cue 词，"
                "相似度 ≥ 0.62，被当成线索已出现 → 假阳性点选（update 违反）。"
            )
        elif sid == "d1_s7" and "hardware_counter_d1" in set(gt_ids) - set(pred_choose):
            judge["why"] = (
                "连锁：s2 假阳性已把 replacement filter 标 done，本步 pending 里没有它。"
                "Update Judge 还把 parking 的 event 误改成整句 follow-up text；"
                "parking / appointment 仍被点到。"
            )
        elif sid == "d1_s13" and "library_return_slot_d1" in set(gt_ids) - set(pred_choose):
            judge["why"] = (
                "连锁：s8 假阳性已把还书标 done。本步 vignette 是真正的新 cue，"
                "但库里该条已经 done，注入和 choose 都看不见。"
            )
        elif not judge["why"] and verdict == "ok":
            judge["why"] = "本步点选与 GT 一致。"
        elif not judge["why"]:
            judge["why"] = "点选集合与 GT 不完全相同，见第 9 步。"

        step_out.append(
            {
                "step_id": sid,
                "short": short,
                "time": clock_true,
                "vignette": vignette,
                "abc": list(step.get("options") or []),
                "cues": list(step.get("cues") or []),
                "updates_gt": gt_updates,
                "state_events": step.get("state_events") or {},
                "gt_status": (step.get("groundtruth") or {}).get("status"),
                "gt_ids": gt_ids,
                "model_choice": choice.get("choice"),
                "model_task_ids": pred_choose,
                "ticks": ticks,
                "stages": stages,
                "store_before": store_before,
                "store_after_recall": store_after,
                "store_after_encode": store_encode,
                "store_diff": diffs,
                "injected": injected[:3500],
                "judge": judge,
            }
        )
        prev_store = store_encode or store_after

    # aggregate error by stage name prefix
    agg: dict[str, list[float]] = {}
    for st in step_out:
        for sg in st["stages"]:
            agg.setdefault(sg["name"], []).append(sg["error_pct"])
    stage_summary = [
        {
            "name": name,
            "error_pct": round(sum(vals) / len(vals), 1) if vals else 0.0,
            "n": len(vals),
            "actor": next(
                (
                    sg["actor"]
                    for st in step_out
                    for sg in st["stages"]
                    if sg["name"] == name
                ),
                "code",
            ),
        }
        for name, vals in agg.items()
    ]

    score_txt = score_path.read_text(encoding="utf-8")
    m_f1 = re.search(r"set_f1\s+([\d.]+)%", score_txt, re.I)
    payload = {
        "run": str(score_path.parent),
        "stem": stem,
        "day": args.day,
        "model": "deepseek-chat",
        "setup": "intention",
        "score": {
            "set_f1": float(m_f1.group(1)) if m_f1 else None,
            "hit": 10,
            "miss": 2,
            "false_alarms": 2,
            "time_hit": 100.0,
            "event_hit": 77.8,
            "update_miss": 100.0,
            "n_steps": len(step_out),
        },
        "regex_rules": _regex_rules(),
        "daily_seed": daily_planted,
        "regex_extract": regex_rows,
        "stage_summary": stage_summary,
        "steps": step_out,
    }
    # fill score from md more carefully
    m_hit = re.search(r"Hit:\s*(\d+).*?Miss:\s*(\d+).*?False alarms:\s*(\d+)", score_txt)
    if m_hit:
        payload["score"]["hit"] = int(m_hit.group(1))
        payload["score"]["miss"] = int(m_hit.group(2))
        payload["score"]["false_alarms"] = int(m_hit.group(3))
    m_up = re.search(r"update miss\s+([\d.]+)%", score_txt, re.I)
    if m_up:
        payload["score"]["update_miss"] = float(m_up.group(1))
    m_ev = re.search(r"event\s+([\d.]+)%", score_txt, re.I)
    if m_ev:
        payload["score"]["event_hit"] = float(m_ev.group(1))
    m_tm = re.search(r"time\s+([\d.]+)%", score_txt, re.I)
    if m_tm:
        payload["score"]["time_hit"] = float(m_tm.group(1))
    m_f1b = re.search(r"set_f1\s+([\d.]+)%", score_txt, re.I)
    if m_f1b:
        payload["score"]["set_f1"] = float(m_f1b.group(1))

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    out = Path(args.out) if args.out else score_path.with_name(f"{stem}.daytrace.json")
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} steps={len(step_out)} bytes={out.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
