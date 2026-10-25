# PM-Bench task taxonomy — one worked example per category

Read alongside `exp1_category_analysis.md`, which reports how models score on
each of these. Extracted from `benchmark/data/synthetic_week_v9.json`.

## Category counts

| Category | n (definitions) | n (scored) | What makes it hard |
|---|---:|---:|---|
| Event-based | 57 | 57 | notice a cue in narration and act the same step |
| Time-based | 26 | 24 | needs the clock; 60-minute late window |
| Regular | 28 | 28 | recurs daily under the same task id |
| Non-regular | 55 | 53 | one-shot, no routine to lean on |
| Channel-triggered | 15 | 15 | cue is invisible without querying a hidden channel |
| Cross-day | 7 | 7 | announced one day, cue arrives on a later day |
| Update: cancel | 2 | 0 | obligation withdrawn (unscored once cancelled) |
| Update: override | 3 | 3 | same action, **different cue** |
| Update: reschedule | 6 | 6 | same action, new target time |
| Lures | 74 | — | plausible menu entries that are never due |

83 definitions across 7 days; 59 unique task ids, because 4 recurring
medication tasks share an id. 83 minus the 2 cancelled = 81 scored occurrences.

## Event-based (57)

A cue appears in the step narration. The agent must notice it and act that step; event late credit is one step.

```
id          library_return_slot_d1
day         Monday
label       Return the library book when the return slot is open
action_text Return the library book.
type        event   regular=False
cue_id      library_return_slot_d1
```

## Time-based (26 defined, 24 scored)

A wall-clock target. The clock is a queryable channel, so the agent must either check it or infer the time. Late credit within 60 minutes.

```
id          send_library_email_1_d1
day         Monday
label       Send the library email at 11:50
action_text Send the library email.
type        time   regular=False
target_time 11:50
```

## Regular (28)

Recurs every day under the **same task id**, which is why an occurrence is `(day, task_id)`. This is the category models handle best: Llama-70B reaches 82.1% here against 28.3% on non-regular tasks.

```
id          antibiotic_breakfast
day         Monday
label       Take antibiotic at breakfast
action_text Take antibiotic at breakfast.
type        event   regular=True
cue_id      breakfast
```

## Channel-triggered (15)

Nothing in the narration signals the cue. The agent must proactively `query_state` the right hidden channel. **The three strongest models score 0/15.**

```
id          appointment_form_ready_d1
day         Monday
label       Finish the intake form when the portal posts it
action_text Finish the intake form.
type        event   regular=False
cue_channel appointment_portal
cue_id      appointment_form_ready_d1
```
```
id          library_hold_ready_d1
day         Monday
label       Pick up the hold when the library notice says it is ready
action_text Pick up the hold.
type        event   regular=False
cue_channel library_hold
cue_id      library_hold_ready_d1
```

## Cross-day (7)

Announced on one day, cue arrives `cross_day_offset` days later. The record sits under its **due** day; the announcement happens earlier, mid-day, as prose.

```
id          crossday_1
day         Wednesday
label       Carry the prescription receipt when you notice the lab drop box
action_text Carry the prescription receipt.
type        event   regular=False
cross_day_offset1
cue_id      lab_dropbox_d3
encoding    start
```

The announcement text for `crossday_1`, at Tuesday `d2_s4`:

```
You expect another email to land later. You jot down a quick reminder:
On Wednesday, Carry the prescription receipt when you notice the lab drop box.
```

Note it is embedded in narration and names the day explicitly.

## Update events (11)

The obligation changes mid-week. All three subtypes keep the **same action**;
they differ in what changes around it.

| # | Day / step | Subtype | Target task | What changes |
|---|---|---|---|---|
| 1 | Monday `d1_s2` | override | `hardware_counter_d1` | cue -> Pick up the replacement filter when the foll |
| 2 | Monday `d1_s8` | override | `library_return_slot_d1` | cue -> Return the library book when the updated pic |
| 3 | Tuesday `d2_s6` | reschedule | `check_in_manager_1_d2` | target_time -> 15:55 |
| 4 | Tuesday `d2_s7` | reschedule | `send_budget_note_2_d2` | target_time -> 15:55 |
| 5 | Wednesday `d3_s2` | cancel | `pay_coop_dues_2_d3` | obligation withdrawn |
| 6 | Wednesday `d3_s4` | cancel | `call_insurance_1_d3` | obligation withdrawn |
| 7 | Thursday `d4_s5` | reschedule | `confirm_pickup_window_1_d4` | target_time -> 20:40 |
| 8 | Friday `d5_s2` | override | `dry_cleaner_rack_d5` | cue -> Collect the dry cleaning when the confirmati |
| 9 | Saturday `d6_s2` | reschedule | `submit_timesheet_1_d6` | target_time -> 11:00 |
| 10 | Saturday `d6_s3` | reschedule | `email_vendor_2_d6` | target_time -> 11:50 |
| 11 | Sunday `d7_s8` | reschedule | `review_lab_notes_1_d7` | target_time -> 21:00 |

### cancel (2)

Obligation withdrawn; the task becomes unscored.

```
Wednesday d3_s2   target: pay_coop_dues_2_d3
cue_id          cancel_notice_pay_coop_dues_2_d3_d0
step text       You get a note that paying the co-op dues does not need to happen after all. You keep meaning to call the insurance desk. You leave yourself a note: O
```

### reschedule (6)

Same action, new wall-clock target.

```
Tuesday d2_s6   target: check_in_manager_1_d2
new_target_time 15:55
new_label       Check in with your manager at 15:55
new_action_text Check in with your manager.
cue_id          reschedule_notice_check_in_manager_1_d2_d0
step text       A short follow-up changes the timing for check in with your manager. The timing shifts a little: check in with your manager moves to 15:55.
```

### override (3)

Same action, **different cue**. A model that only remembers the action still fires on the old cue -- which is why every model scores **0/3** here.

```
Monday d1_s2   target: hardware_counter_d1
new_cue_id      override_hardware_counter_d1_d0
new_label       Pick up the replacement filter when the follow-up text comes in
new_action_text Pick up the replacement filter.
cue_id          override_notice_hardware_counter_d1_d0
step text       You get a follow-up with corrected instructions for pick up the replacement filter. You have a feeling the appointment portal may open a better slot l
```

## Lures (74)

Plausible menu entries that are never a real obligation. Selecting one is a
false alarm. Mostly a small-model failure: Qwen3-0.6B and 1.7B pick 6-8, while
most models 3B and above pick none.

```
look_up_recipe                    Look up a recipe.
read_blurb                        Read a book blurb.
text_friend                       Send a quick text to a friend.
brew_tea                          Make a cup of tea.
straighten_couch                  Straighten the couch pillows.
```

## What one step looks like

```
step      d1_s4   time 11:00
text      You know you still have to send the library email today.
options   A) Stack papers B) Take a breath C) Check the time
cues      []
truth     due: asthma_1100 -> task_14
```

This step is the benchmark's core difficulty in miniature. The narration
mentions the **library email**, but the actually-due task is **asthma_1100**,
visible only through the clock. A model that reads the text and acts on what it
says will select the wrong task. That is why **"real task, wrong step"** is the
dominant false-alarm kind for every model in the set -- the intention is right,
the moment is wrong.

Action handles (`task_14`) are anonymous and re-issued per day, so a handle
cannot be memorised across days.
