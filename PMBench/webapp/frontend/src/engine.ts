import type {
  ActionMenuItem,
  Choice,
  Day,
  DayScoreResult,
  DayRuntime,
  DayUpdates,
  LogEntry,
  RunMetadataRecord,
  Lure,
  LureInput,
  ScoreBreakdown,
  ScoreMetrics,
  ScoreReport,
  Scenario,
  SessionRuntime,
  StateChannelConfig,
  StateEventInput,
  StateItem,
  StateQueryResponse,
  Step,
  StepUpdate,
  Task,
  TaskRuntimeState,
} from "./types";

const DAILY_TASK_HEADER_LINES = [
  "Regular tasks for every day:",
  "- Take antibiotic at breakfast and dinner.",
  "- Take asthma medication at 11:00 and 21:00.",
];

const EVENT_LATE_WINDOW_STEPS = 1;
const TIME_LATE_WINDOW_MINUTES = 60;
const STEP_LURE_DISPLAY_COUNT = 3;

function randomId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `run-${Math.random().toString(36).slice(2)}`;
}

function timeToMinutes(value: string): number {
  const parts = value.split(":");
  return Number(parts[0]) * 60 + Number(parts[1]);
}

function hashString(value: string): number {
  let hash = 2166136261;
  for (let idx = 0; idx < value.length; idx += 1) {
    hash ^= value.charCodeAt(idx);
    hash +=
      (hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24);
  }
  return hash >>> 0;
}

function deterministicOrder<T>(
  items: T[],
  seed: string,
  keyFn: (item: T) => string,
): T[] {
  return [...items].sort((left, right) => {
    const leftKey = keyFn(left);
    const rightKey = keyFn(right);
    const leftHash = hashString(`${seed}:${leftKey}`);
    const rightHash = hashString(`${seed}:${rightKey}`);
    if (leftHash !== rightHash) {
      return leftHash - rightHash;
    }
    return leftKey.localeCompare(rightKey);
  });
}

function sentenceCase(text: string): string {
  if (!text) {
    return text;
  }
  return `${text[0].toUpperCase()}${text.slice(1)}`;
}

function ensurePeriod(text: string): string {
  const normalized = text.trim();
  if (!normalized) {
    return normalized;
  }
  if (normalized.endsWith(".")) {
    return normalized;
  }
  return `${normalized}.`;
}

function deriveActionTextFromLabel(label: string | undefined): string {
  let text = (label ?? "").trim().replace(/\.$/, "");
  if (!text) {
    return "Do the task.";
  }
  text = text.replace(/\s+when\s+.*$/i, "");
  text = text.replace(/\s+(at|around)\s+\d{1,2}:\d{2}$/i, "");
  text = text.replace(/\s+after\s+.*$/i, "");
  const followupMatch = text.match(/^Follow up on the (.+?) task$/i);
  if (followupMatch) {
    const inner = followupMatch[1].trim().toLowerCase();
    const pickupMatch = inner.match(/^pick up the (.+)$/);
    if (pickupMatch) {
      text = `Follow up on ${pickupMatch[1]} pickup`;
    } else {
      text = `Follow up on ${inner}`;
    }
  }
  return ensurePeriod(sentenceCase(text));
}

function normalizeLureItem(lure: LureInput): Lure | null {
  if (typeof lure === "string") {
    return {
      id: lure,
      action_text: ensurePeriod(sentenceCase(lure.replaceAll("_", " "))),
    };
  }
  const lureId = lure.id;
  if (!lureId) {
    return null;
  }
  return {
    id: lureId,
    action_text:
      lure.action_text ??
      ensurePeriod(sentenceCase(lureId.replaceAll("_", " "))),
  };
}

function normalizeLureCatalog(lures: LureInput[]): Lure[] {
  const catalog: Lure[] = [];
  const seen = new Set<string>();
  for (const lure of lures ?? []) {
    const normalized = normalizeLureItem(lure);
    if (!normalized) {
      continue;
    }
    if (seen.has(normalized.id)) {
      continue;
    }
    seen.add(normalized.id);
    catalog.push(normalized);
  }
  return catalog;
}

function taskActionText(task: Task): string {
  return task.action_text ?? deriveActionTextFromLabel(task.label);
}

function runtimeTaskActionText(state: TaskRuntimeState): string {
  return (
    state.current.action_text ??
    deriveActionTextFromLabel(state.current.label) ??
    taskActionText(state.task)
  );
}

function normalizeEncoding(value: string): ["start", null] | ["step", string] {
  if (value === "start") {
    return ["start", null];
  }
  if (value.startsWith("step:")) {
    return ["step", value.split(":", 2)[1]];
  }
  throw new Error(`Unknown encoding format: ${value}`);
}

export function listStateChannels(scenario: Scenario): string[] {
  const channels = new Set<string>();
  const stateVisibility = scenario.state_visibility ?? {};
  const stateChannels = scenario.state_channels ?? {};
  for (const channel of Object.keys(stateVisibility)) {
    channels.add(channel);
  }
  for (const channel of Object.keys(stateChannels)) {
    channels.add(channel);
  }
  if (Object.hasOwn(scenario, "time_visible_by_default")) {
    channels.add("clock");
  }
  if (channels.size === 0) {
    channels.add("clock");
  }
  return [...channels].sort();
}

export function normalizeStateVisibility(
  scenario: Scenario,
): Record<string, boolean> {
  const channels = listStateChannels(scenario);
  const visibility: Record<string, boolean> = {};
  for (const channel of channels) {
    visibility[channel] = false;
  }
  const provided = scenario.state_visibility;
  if (provided) {
    for (const [channel, visible] of Object.entries(provided)) {
      visibility[channel] = Boolean(visible);
    }
  }
  if (Object.hasOwn(scenario, "time_visible_by_default")) {
    const hasClockInProvided = Boolean(provided && Object.hasOwn(provided, "clock"));
    if (!hasClockInProvided) {
      visibility.clock = Boolean(scenario.time_visible_by_default);
    }
  }
  return visibility;
}

export function normalizeStateChannels(
  scenario: Scenario,
): Record<string, StateChannelConfig> {
  const channels = listStateChannels(scenario);
  const provided = scenario.state_channels ?? {};
  const configs: Record<string, StateChannelConfig> = {};
  for (const channel of channels) {
    const config = { ...(provided[channel] ?? {}) };
    if (!config.mode) {
      config.mode = "delta";
    }
    configs[channel] = config;
  }
  return configs;
}

function normalizeStateEventItem(event: StateEventInput): StateItem {
  if (typeof event === "string") {
    return { id: event, text: event, value: null, meta: {} };
  }
  return {
    id: event.id,
    text: event.text,
    value: event.value,
    meta: event.meta ?? {},
  };
}

function collectStateEventsForRange(
  steps: Step[],
  startIdx: number,
  endIdx: number,
  channel: string,
): StateItem[] {
  const items: StateItem[] = [];
  const start = Math.max(0, startIdx);
  if (endIdx < start) {
    return items;
  }
  for (let idx = start; idx <= endIdx; idx += 1) {
    const events = steps[idx].state_events?.[channel] ?? [];
    for (const event of events) {
      items.push(normalizeStateEventItem(event));
    }
  }
  return items;
}

function buildClockItem(
  dayName: string,
  stepTime: string,
  dayStartMinutes: number,
): StateItem {
  const stepMinutes = timeToMinutes(stepTime);
  const stopwatch = stepMinutes - dayStartMinutes;
  return {
    id: "clock",
    text: `Time ${stepTime} | Stopwatch: ${stopwatch} min`,
    value: stepTime,
    meta: { day: dayName, stopwatch_min: stopwatch },
  };
}

function buildStateQueryResponse(
  channel: string,
  items: StateItem[],
  dayName: string,
  stepId: string,
): StateQueryResponse {
  return {
    channel,
    items,
    meta: { day: dayName, step_id: stepId },
  };
}

export function formatStateQueryDisplay(channel: string, items: StateItem[]): string {
  if (items.length === 0) {
    return `State [${channel}]: (no updates)`;
  }
  const texts = items.map((item) => item.text ?? item.id ?? "update");
  return `State [${channel}]: ${texts.join(" | ")}`;
}

function resolveStateQueryItems(
  channel: string,
  steps: Step[],
  stepIdx: number,
  dayName: string,
  dayStartMinutes: number,
  stateChannels: Record<string, StateChannelConfig>,
  lastQueryStepByChannel: Record<string, number>,
  lastSnapshotItemByChannel: Record<string, StateItem>,
): StateItem[] {
  if (channel === "clock") {
    lastQueryStepByChannel[channel] = stepIdx;
    return [buildClockItem(dayName, steps[stepIdx].time, dayStartMinutes)];
  }

  const mode = stateChannels[channel]?.mode ?? "delta";
  if (mode === "snapshot") {
    const items = collectStateEventsForRange(steps, stepIdx, stepIdx, channel);
    lastQueryStepByChannel[channel] = stepIdx;
    if (items.length > 0) {
      lastSnapshotItemByChannel[channel] = items[items.length - 1];
      return items;
    }
    const cached = lastSnapshotItemByChannel[channel];
    if (cached) {
      return [cached];
    }
    const defaultItem = stateChannels[channel]?.default_item;
    if (defaultItem) {
      const normalized = normalizeStateEventItem(defaultItem);
      lastSnapshotItemByChannel[channel] = normalized;
      return [normalized];
    }
    return [];
  }

  const startIdx = (lastQueryStepByChannel[channel] ?? -1) + 1;
  const items = collectStateEventsForRange(steps, startIdx, stepIdx, channel);
  lastQueryStepByChannel[channel] = stepIdx;
  return items;
}

function buildDayIndex(day: Day): Record<string, number> {
  const stepIndex: Record<string, number> = {};
  for (let idx = 0; idx < day.steps.length; idx += 1) {
    stepIndex[day.steps[idx].id] = idx;
  }
  return stepIndex;
}

function buildDayStartMinutes(day: Day): number {
  if (day.steps.length === 0) {
    return 0;
  }
  return timeToMinutes(day.steps[0].time);
}

function buildUpdatesByDay(scenario: Scenario): Record<string, DayUpdates> {
  const updates: Record<string, DayUpdates> = {};
  for (const day of scenario.days) {
    updates[day.name] = { pre: [], by_step: {} };
  }
  for (const day of scenario.days) {
    const dayName = day.name;
    for (const step of day.steps) {
      const stepUpdates = step.updates ?? [];
      for (const update of stepUpdates) {
        const targetDay = update.target_day ?? dayName;
        if (!Object.hasOwn(updates, targetDay)) {
          continue;
        }
        if (targetDay === dayName) {
          if (!updates[targetDay].by_step[step.id]) {
            updates[targetDay].by_step[step.id] = [];
          }
          updates[targetDay].by_step[step.id].push(update);
        } else {
          updates[targetDay].pre.push(update);
        }
      }
    }
  }
  return updates;
}

function initTaskState(task: Task): TaskRuntimeState {
  return {
    completed: false,
    completed_at: null,
    cue_seen: false,
    cue_step_idx: null,
    active: false,
    result: null,
    task,
    current: {
      type: task.type,
      cue_id: task.cue_id,
      cue_channel: task.cue_channel ?? "narrative",
      target_time: task.target_time,
      window_before: task.window_before,
      window_after: task.window_after,
      label: task.label,
      action_text: task.action_text ?? deriveActionTextFromLabel(task.label),
    },
    canceled: false,
    canceled_by_dependency: false,
    updated: false,
    has_update: false,
    completion_had_required_query: false,
  };
}

function markTaskCanceled(state: TaskRuntimeState): void {
  if (state.canceled) {
    return;
  }
  state.canceled = true;
  state.result = "canceled";
}

function cancelDependents(
  taskStates: Record<string, TaskRuntimeState>,
  taskId: string,
): void {
  const queue = [taskId];
  const seen = new Set<string>();
  while (queue.length > 0) {
    const currentId = queue.pop();
    if (!currentId || seen.has(currentId)) {
      continue;
    }
    seen.add(currentId);
    for (const dependentState of Object.values(taskStates)) {
      if (dependentState.task.depends_on !== currentId) {
        continue;
      }
      if (dependentState.canceled) {
        continue;
      }
      dependentState.canceled_by_dependency = true;
      markTaskCanceled(dependentState);
      queue.push(dependentState.task.id);
    }
  }
}

function applyTaskUpdate(
  state: TaskRuntimeState,
  update: StepUpdate,
  taskStates: Record<string, TaskRuntimeState>,
): void {
  if (state.completed) {
    return;
  }
  const action = update.action;
  if (!action || !["cancel", "reschedule", "override"].includes(action)) {
    return;
  }
  if (action === "cancel") {
    markTaskCanceled(state);
    cancelDependents(taskStates, state.task.id);
    return;
  }

  state.updated = true;
  if (update.new_type && update.new_type !== state.current.type) {
    state.current.type = update.new_type;
  }
  if (update.new_cue_id) {
    state.current.cue_id = update.new_cue_id;
    state.cue_seen = false;
    state.cue_step_idx = null;
  }
  if (update.new_target_time) {
    state.current.target_time = update.new_target_time;
    state.cue_seen = false;
    state.cue_step_idx = null;
  }
  if (update.new_window_before !== undefined) {
    state.current.window_before = update.new_window_before;
  }
  if (update.new_window_after !== undefined) {
    state.current.window_after = update.new_window_after;
  }
  if (update.new_label) {
    state.current.label = update.new_label;
  }
  if (update.new_action_text) {
    state.current.action_text = update.new_action_text;
  } else if (update.new_label) {
    state.current.action_text = deriveActionTextFromLabel(update.new_label);
  }
}

function buildDayHandleMap(
  taskStates: Record<string, TaskRuntimeState>,
  lureCatalog: Lure[],
  seed: string,
): Record<string, string> {
  const allIds = [
    ...Object.keys(taskStates),
    ...lureCatalog.map((lure) => lure.id),
  ];
  const ordered = deterministicOrder(
    [...new Set(allIds)],
    seed,
    (itemId) => itemId,
  );
  const idToHandle: Record<string, string> = {};
  for (let idx = 0; idx < ordered.length; idx += 1) {
    idToHandle[ordered[idx]] = `task_${idx + 1}`;
  }
  return idToHandle;
}

function isDueEvent(task: TaskRuntimeState["current"], step: Step): boolean {
  const cueId = task.cue_id;
  const cueChannel = task.cue_channel ?? "narrative";
  if (!cueId) {
    return false;
  }
  if (cueChannel === "narrative") {
    return step.cues.includes(cueId);
  }
  const events = step.state_events?.[cueChannel] ?? [];
  for (const event of events) {
    if (typeof event === "string" && event === cueId) {
      return true;
    }
    if (typeof event !== "string" && event.id === cueId) {
      return true;
    }
  }
  return false;
}

function isDueTime(task: TaskRuntimeState["current"], step: Step): boolean {
  return step.time === task.target_time;
}

function timecheckStatus(
  task: TaskRuntimeState["current"],
  stepMinutes: number,
  dayStartMinutes: number,
): "on_time" | "late" | "early" {
  const targetMinutes = timeToMinutes(task.target_time ?? "00:00") - dayStartMinutes;
  const currentStopwatch = stepMinutes - dayStartMinutes;
  const windowStart = targetMinutes - (task.window_before ?? 0);
  const windowEnd = targetMinutes + (task.window_after ?? 0);
  if (windowStart <= currentStopwatch && currentStopwatch <= windowEnd) {
    return "on_time";
  }
  if (currentStopwatch > windowEnd) {
    return "late";
  }
  return "early";
}

function computeDueNow(
  dayRuntime: DayRuntime,
  step: Step,
  stepIdx: number,
): Set<string> {
  const dueNow = new Set<string>();
  const stepMinutes = timeToMinutes(step.time);
  for (const taskId of dayRuntime.active_task_ids) {
    const state = dayRuntime.task_states[taskId];
    if (!state || !state.active || state.completed || state.canceled) {
      continue;
    }
    const dependsOn = state.task.depends_on;
    let dependencyMet = true;
    if (dependsOn) {
      const dependencyState = dayRuntime.task_states[dependsOn];
      dependencyMet = Boolean(dependencyState && dependencyState.completed);
    }
    if (state.current.type === "event" && isDueEvent(state.current, step)) {
      state.cue_seen = true;
      if (state.cue_step_idx === null) {
        state.cue_step_idx = stepIdx;
      }
      if (dependencyMet) {
        dueNow.add(taskId);
      }
    } else if (state.current.type === "time" && isDueTime(state.current, step)) {
      state.cue_seen = true;
      if (state.cue_step_idx === null) {
        state.cue_step_idx = stepIdx;
      }
      if (dependencyMet) {
        dueNow.add(taskId);
      }
    } else if (state.current.type === "time_check") {
      const status = timecheckStatus(
        state.current,
        stepMinutes,
        dayRuntime.day_start_minutes,
      );
      if (status === "on_time" && dependencyMet) {
        dueNow.add(taskId);
      }
    }
  }
  return dueNow;
}

function applyRuntimeCompletions(
  dayRuntime: DayRuntime,
  chosenTaskIds: string[],
  dueNow: Set<string>,
  step: Step,
  stepIdx: number,
): void {
  const stepMinutes = timeToMinutes(step.time);
  for (const taskId of chosenTaskIds) {
    const state = dayRuntime.task_states[taskId];
    if (!state || state.completed || state.canceled || !state.active) {
      continue;
    }
    const dependsOn = state.task.depends_on;
    if (dependsOn) {
      const dependencyState = dayRuntime.task_states[dependsOn];
      if (!dependencyState || !dependencyState.completed) {
        continue;
      }
    }
    if (dueNow.has(taskId)) {
      state.completed = true;
      state.completed_at = step.id;
      state.result = "hit";
      continue;
    }
    if (state.current.type === "time_check") {
      const status = timecheckStatus(
        state.current,
        stepMinutes,
        dayRuntime.day_start_minutes,
      );
      const targetMinutes = timeToMinutes(state.current.target_time ?? "00:00");
      const delta = stepMinutes - targetMinutes;
      if (status === "late" && delta > 0 && delta <= TIME_LATE_WINDOW_MINUTES) {
        state.completed = true;
        state.completed_at = step.id;
        state.result = "late";
      }
      continue;
    }
    if (state.current.type === "time") {
      const targetMinutes = timeToMinutes(state.current.target_time ?? "00:00");
      const delta = stepMinutes - targetMinutes;
      if (delta > 0 && delta <= TIME_LATE_WINDOW_MINUTES) {
        state.completed = true;
        state.completed_at = step.id;
        state.result = "late";
      }
      continue;
    }
    const cueStepIdx = state.cue_step_idx;
    if (cueStepIdx !== null) {
      const deltaSteps = stepIdx - cueStepIdx;
      if (deltaSteps > 0 && deltaSteps <= EVENT_LATE_WINDOW_STEPS) {
        state.completed = true;
        state.completed_at = step.id;
        state.result = "late";
      }
    }
  }
}

function buildStepActionMenu(
  dayRuntime: DayRuntime,
  stepId: string,
): ActionMenuItem[] {
  const taskEntries: ActionMenuItem[] = [];
  for (const taskId of dayRuntime.active_task_ids) {
    const state = dayRuntime.task_states[taskId];
    if (!state || !state.active || state.completed) {
      continue;
    }
    taskEntries.push({
      id: taskId,
      handle: dayRuntime.id_to_handle[taskId],
      action_text: runtimeTaskActionText(state),
    });
  }

  const lureEntries = deterministicOrder(
    dayRuntime.lure_catalog,
    `${dayRuntime.day_name}:${stepId}:lures`,
    (lure) => lure.id,
  )
    .slice(0, Math.min(STEP_LURE_DISPLAY_COUNT, dayRuntime.lure_catalog.length))
    .map((lure) => ({
      id: lure.id,
      handle: dayRuntime.id_to_handle[lure.id],
      action_text:
        lure.action_text ?? ensurePeriod(sentenceCase(lure.id.replaceAll("_", " "))),
    }));

  return deterministicOrder(
    [...taskEntries, ...lureEntries],
    `${dayRuntime.day_name}:${stepId}:menu`,
    (item) => item.handle,
  );
}

function initializeDayRuntime(
  scenario: Scenario,
  dayIdx: number,
  updatesByDay: Record<string, DayUpdates>,
): DayRuntime {
  const day = scenario.days[dayIdx];
  const taskStates: Record<string, TaskRuntimeState> = {};
  const activeTaskIds = new Set<string>();
  for (const task of day.tasks) {
    taskStates[task.id] = initTaskState(task);
    const [encodingType] = normalizeEncoding(task.encoding);
    if (encodingType === "start") {
      taskStates[task.id].active = true;
      activeTaskIds.add(task.id);
    }
  }

  const preUpdates = updatesByDay[day.name]?.pre ?? [];
  for (const update of preUpdates) {
    const taskId = update.task_id;
    if (!taskId || !taskStates[taskId]) {
      continue;
    }
    applyTaskUpdate(taskStates[taskId], update, taskStates);
  }

  const lureCatalog = normalizeLureCatalog(day.lures);
  return {
    day_name: day.name,
    day_start_minutes: buildDayStartMinutes(day),
    step_index_by_id: buildDayIndex(day),
    task_states: taskStates,
    active_task_ids: [...activeTaskIds],
    lure_catalog: lureCatalog,
    id_to_handle: buildDayHandleMap(taskStates, lureCatalog, `${day.name}:handles`),
    prepared_step_id: null,
    current_menu_items: [],
    start_instructions: [...day.start_instructions],
    last_query_step_by_channel: {},
    last_snapshot_item_by_channel: {},
  };
}

function prepareCurrentStep(runtime: SessionRuntime): void {
  if (isSessionComplete(runtime) || !runtime.day_runtime) {
    return;
  }
  const day = runtime.scenario.days[runtime.day_idx];
  const step = day.steps[runtime.step_idx];
  if (!step) {
    return;
  }
  if (runtime.day_runtime.prepared_step_id === step.id) {
    return;
  }

  const updates = runtime.updates_by_day[day.name]?.by_step?.[step.id] ?? [];
  for (const update of updates) {
    const taskId = update.task_id;
    if (!taskId || !runtime.day_runtime.task_states[taskId]) {
      continue;
    }
    applyTaskUpdate(
      runtime.day_runtime.task_states[taskId],
      update,
      runtime.day_runtime.task_states,
    );
  }

  for (const task of day.tasks) {
    const [encodingType, stepId] = normalizeEncoding(task.encoding);
    if (encodingType === "step" && stepId === step.id) {
      runtime.day_runtime.task_states[task.id].active = true;
      if (!runtime.day_runtime.active_task_ids.includes(task.id)) {
        runtime.day_runtime.active_task_ids.push(task.id);
      }
    }
  }

  runtime.day_runtime.current_menu_items = buildStepActionMenu(
    runtime.day_runtime,
    step.id,
  );
  runtime.day_runtime.prepared_step_id = step.id;
}

export function createSessionRuntime(
  scenario: Scenario,
  scenarioPath: string,
  participantId: string,
  experimenterNotes: string,
  showTaskLegend: boolean,
  showTimeByDefaultOverride?: boolean,
  showGroundtruth = false,
  allowBacktrackDebug = false,
): SessionRuntime {
  const stateVisibility = normalizeStateVisibility(scenario);
  if (showTimeByDefaultOverride !== undefined) {
    stateVisibility.clock = Boolean(showTimeByDefaultOverride);
  }
  const runtime: SessionRuntime = {
    scenario,
    scenario_path: scenarioPath,
    participant_id: participantId.trim(),
    experimenter_notes: experimenterNotes.trim(),
    show_task_legend: showTaskLegend,
    show_groundtruth: showGroundtruth,
    allow_backtrack_debug: allowBacktrackDebug,
    allowed_channels: listStateChannels(scenario),
    state_visibility: stateVisibility,
    state_channels: normalizeStateChannels(scenario),
    updates_by_day: buildUpdatesByDay(scenario),
    day_idx: 0,
    step_idx: 0,
    day_runtime: null,
    current_step_query_counts: {},
    step_query_transcript: [],
    log_entries: [],
    started_at: new Date().toISOString(),
    finished_at: null,
    run_id: randomId(),
  };
  runtime.day_runtime = initializeDayRuntime(scenario, 0, runtime.updates_by_day);
  prepareCurrentStep(runtime);
  return runtime;
}

export function isSessionComplete(runtime: SessionRuntime): boolean {
  return runtime.finished_at !== null;
}

export function getDailyHeaderLines(): string[] {
  return [...DAILY_TASK_HEADER_LINES];
}

export function getCurrentDay(runtime: SessionRuntime): Day | null {
  if (isSessionComplete(runtime)) {
    return null;
  }
  return runtime.scenario.days[runtime.day_idx] ?? null;
}

export function getCurrentStep(runtime: SessionRuntime): Step | null {
  const day = getCurrentDay(runtime);
  if (!day) {
    return null;
  }
  return day.steps[runtime.step_idx] ?? null;
}

export function getCurrentActionMenu(runtime: SessionRuntime): ActionMenuItem[] {
  if (!runtime.day_runtime) {
    return [];
  }
  prepareCurrentStep(runtime);
  return [...runtime.day_runtime.current_menu_items];
}

export function getCurrentLegendMenu(runtime: SessionRuntime): ActionMenuItem[] {
  if (!runtime.day_runtime) {
    return [];
  }
  const activeTasks: ActionMenuItem[] = [];
  for (const taskId of runtime.day_runtime.active_task_ids) {
    const state = runtime.day_runtime.task_states[taskId];
    if (!state || !state.active || state.completed) {
      continue;
    }
    activeTasks.push({
      id: taskId,
      handle: runtime.day_runtime.id_to_handle[taskId],
      action_text: runtimeTaskActionText(state),
    });
  }
  const lureItems = runtime.day_runtime.lure_catalog.map((lure) => ({
    id: lure.id,
    handle: runtime.day_runtime!.id_to_handle[lure.id],
    action_text:
      lure.action_text ?? ensurePeriod(sentenceCase(lure.id.replaceAll("_", " "))),
  }));
  return deterministicOrder(
    [...activeTasks, ...lureItems],
    `${runtime.day_runtime.day_name}:legend`,
    (item) => item.handle,
  );
}

export function getTotalSteps(runtime: SessionRuntime): number {
  return runtime.scenario.days.reduce((acc, day) => acc + day.steps.length, 0);
}

export function getCompletedSteps(runtime: SessionRuntime): number {
  return runtime.log_entries.length;
}

export function getTimeDisplay(runtime: SessionRuntime): string | null {
  const day = getCurrentDay(runtime);
  const step = getCurrentStep(runtime);
  if (!day || !step || !runtime.day_runtime) {
    return null;
  }
  const showByDefault = runtime.state_visibility.clock ?? false;
  if (!showByDefault) {
    return null;
  }
  const minutes = timeToMinutes(step.time) - runtime.day_runtime.day_start_minutes;
  return `Time: ${step.time} | Stopwatch: ${minutes} min`;
}

export function queryState(
  runtime: SessionRuntime,
  channel: string,
): { runtime: SessionRuntime; response: StateQueryResponse; displayText: string } {
  if (isSessionComplete(runtime)) {
    throw new Error("Session already completed.");
  }
  if (!runtime.allowed_channels.includes(channel)) {
    throw new Error(`Unknown channel: ${channel}`);
  }
  if (!runtime.day_runtime) {
    throw new Error("Missing day runtime.");
  }
  prepareCurrentStep(runtime);
  const day = getCurrentDay(runtime);
  const step = getCurrentStep(runtime);
  if (!day || !step) {
    throw new Error("No active step.");
  }
  const stepIdx = runtime.day_runtime.step_index_by_id[step.id];
  const items = resolveStateQueryItems(
    channel,
    day.steps,
    stepIdx,
    day.name,
    runtime.day_runtime.day_start_minutes,
    runtime.state_channels,
    runtime.day_runtime.last_query_step_by_channel,
    runtime.day_runtime.last_snapshot_item_by_channel,
  );
  runtime.current_step_query_counts[channel] =
    (runtime.current_step_query_counts[channel] ?? 0) + 1;
  const response = buildStateQueryResponse(channel, items, day.name, step.id);
  const displayText = formatStateQueryDisplay(response.channel, response.items);
  runtime.step_query_transcript.push(displayText);
  return { runtime, response, displayText };
}

export function chooseStep(
  runtime: SessionRuntime,
  choice: Choice,
  selectedHandles: string[],
): SessionRuntime {
  if (isSessionComplete(runtime)) {
    throw new Error("Session already completed.");
  }
  if (!runtime.day_runtime) {
    throw new Error("Missing day runtime.");
  }
  prepareCurrentStep(runtime);
  const day = getCurrentDay(runtime);
  const step = getCurrentStep(runtime);
  if (!day || !step) {
    throw new Error("No active step.");
  }
  const menuByHandle = new Map<string, ActionMenuItem>();
  for (const item of runtime.day_runtime.current_menu_items) {
    menuByHandle.set(item.handle, item);
  }
  const selectedTaskIds: string[] = [];
  for (const handle of selectedHandles) {
    const item = menuByHandle.get(handle);
    if (!item) {
      continue;
    }
    if (!selectedTaskIds.includes(item.id)) {
      selectedTaskIds.push(item.id);
    }
  }

  const stepIdx = runtime.day_runtime.step_index_by_id[step.id];
  const dueNow = computeDueNow(runtime.day_runtime, step, stepIdx);
  applyRuntimeCompletions(
    runtime.day_runtime,
    selectedTaskIds,
    dueNow,
    step,
    stepIdx,
  );

  const stateQueries = { ...runtime.current_step_query_counts };
  const entry: LogEntry = {
    day: day.name,
    step_id: step.id,
    choice,
    task_ids: selectedTaskIds,
    check_time: stateQueries.clock ?? 0,
    state_queries: stateQueries,
  };
  runtime.log_entries.push(entry);
  runtime.current_step_query_counts = {};
  runtime.step_query_transcript = [];

  if (runtime.step_idx + 1 < day.steps.length) {
    runtime.step_idx += 1;
    runtime.day_runtime.prepared_step_id = null;
    runtime.day_runtime.current_menu_items = [];
    prepareCurrentStep(runtime);
    return runtime;
  }

  if (runtime.day_idx + 1 < runtime.scenario.days.length) {
    runtime.day_idx += 1;
    runtime.step_idx = 0;
    runtime.day_runtime = initializeDayRuntime(
      runtime.scenario,
      runtime.day_idx,
      runtime.updates_by_day,
    );
    prepareCurrentStep(runtime);
    return runtime;
  }

  runtime.finished_at = new Date().toISOString();
  runtime.day_runtime = null;
  return runtime;
}

const RUN_METADATA_RECORD_TYPE = "run_metadata";

const SCORE_METRIC_KEYS: Array<keyof ScoreMetrics> = [
  "hit",
  "late",
  "miss",
  "false_alarm",
  "commission",
  "wrong_content",
  "check_time_calls",
  "state_query_calls",
  "overkill_steps",
  "chosen_tasks",
  "dependency_violation",
  "cross_day_total",
  "cross_day_hit",
  "cross_day_late",
  "cross_day_miss",
  "update_total",
  "update_hit",
  "update_late",
  "update_miss",
  "update_violation",
  "update_canceled",
  "canceled_total",
  "exact_set_match_steps",
  "exact_set_mismatch_steps",
  "exact_set_match_reward",
  "set_tp",
  "set_fp",
  "set_fn",
];

function createEmptyScoreMetrics(): ScoreMetrics {
  return {
    hit: 0,
    late: 0,
    miss: 0,
    false_alarm: 0,
    commission: 0,
    wrong_content: 0,
    check_time_calls: 0,
    state_query_calls: 0,
    overkill_steps: 0,
    chosen_tasks: 0,
    dependency_violation: 0,
    cross_day_total: 0,
    cross_day_hit: 0,
    cross_day_late: 0,
    cross_day_miss: 0,
    update_total: 0,
    update_hit: 0,
    update_late: 0,
    update_miss: 0,
    update_violation: 0,
    update_canceled: 0,
    canceled_total: 0,
    exact_set_match_steps: 0,
    exact_set_mismatch_steps: 0,
    exact_set_match_reward: 0,
    set_tp: 0,
    set_fp: 0,
    set_fn: 0,
  };
}

function createScoreBreakdown(): ScoreBreakdown {
  return { hit: 0, late: 0, miss: 0, total: 0 };
}

function dedupeTaskIds(taskIds: string[] | undefined): string[] {
  const normalized: string[] = [];
  for (const taskId of taskIds ?? []) {
    if (!taskId || normalized.includes(taskId)) {
      continue;
    }
    normalized.push(taskId);
  }
  return normalized;
}

function requiresStateMonitoring(
  current: TaskRuntimeState["current"],
  stateVisibility: Record<string, boolean>,
): boolean {
  const taskType = current.type;
  if (taskType === "time" || taskType === "time_check") {
    return !stateVisibility.clock;
  }
  if (taskType === "event") {
    return (current.cue_channel ?? "narrative") !== "narrative";
  }
  return false;
}

function requiredMonitorChannel(current: TaskRuntimeState["current"]): string | null {
  const taskType = current.type;
  if (taskType === "time" || taskType === "time_check") {
    return "clock";
  }
  if (taskType === "event") {
    const cueChannel = current.cue_channel ?? "narrative";
    if (cueChannel !== "narrative") {
      return cueChannel;
    }
  }
  return null;
}

function getActionStateQueryCounts(action: LogEntry): Record<string, number> {
  const counts: Record<string, number> = {};
  if (action.state_queries && typeof action.state_queries === "object") {
    for (const [channel, value] of Object.entries(action.state_queries)) {
      const parsed = Number.parseInt(String(value), 10);
      if (!Number.isNaN(parsed) && parsed > 0) {
        counts[channel] = (counts[channel] ?? 0) + parsed;
      }
    }
    return counts;
  }
  const checkTimeCalls = Number.parseInt(String(action.check_time ?? 0), 10);
  if (!Number.isNaN(checkTimeCalls) && checkTimeCalls > 0) {
    counts.clock = checkTimeCalls;
  }
  return counts;
}

function addChannelCounts(
  target: Record<string, number>,
  source: Record<string, number>,
): void {
  for (const [channel, value] of Object.entries(source)) {
    target[channel] = (target[channel] ?? 0) + value;
  }
}

function getActionChannelQueryCount(action: LogEntry, channel: string | null): number {
  if (!channel) {
    return 0;
  }
  return getActionStateQueryCounts(action)[channel] ?? 0;
}

function applyUpdateForScoring(
  taskStates: Record<string, TaskRuntimeState>,
  update: StepUpdate,
  metrics: ScoreMetrics,
): void {
  const taskId = update.task_id;
  if (!taskId || !taskStates[taskId]) {
    return;
  }
  const targetState = taskStates[taskId];
  const canceledBefore = new Set<string>();
  for (const [id, state] of Object.entries(taskStates)) {
    if (state.canceled) {
      canceledBefore.add(id);
    }
  }
  if (update.action === "cancel" && !targetState.canceled) {
    metrics.canceled_total += 1;
  }
  applyTaskUpdate(targetState, update, taskStates);
  for (const [id, state] of Object.entries(taskStates)) {
    if (!state.canceled || canceledBefore.has(id)) {
      continue;
    }
    if (state.task.cross_day) {
      metrics.cross_day_total -= 1;
    }
  }
}

function scoreDay(
  day: Day,
  actions: LogEntry[],
  preUpdates: StepUpdate[],
  updatesByStep: Record<string, StepUpdate[]>,
  stateVisibility: Record<string, boolean>,
): DayScoreResult {
  const steps = day.steps;
  const tasks = day.tasks;
  const dayStartMinutes = buildDayStartMinutes(day);
  const taskStates: Record<string, TaskRuntimeState> = {};
  const activeTaskIds = new Set<string>();

  for (const task of tasks) {
    taskStates[task.id] = initTaskState(task);
    const [encodingType] = normalizeEncoding(task.encoding);
    if (encodingType === "start") {
      taskStates[task.id].active = true;
      activeTaskIds.add(task.id);
    }
  }

  const metrics = createEmptyScoreMetrics();
  for (const task of tasks) {
    if (task.cross_day) {
      metrics.cross_day_total += 1;
    }
  }

  const updatedTaskIds = new Set<string>();
  for (const update of preUpdates ?? []) {
    if (update.task_id) {
      updatedTaskIds.add(update.task_id);
    }
  }
  for (const stepUpdates of Object.values(updatesByStep ?? {})) {
    for (const update of stepUpdates) {
      if (update.task_id) {
        updatedTaskIds.add(update.task_id);
      }
    }
  }
  metrics.update_total = updatedTaskIds.size;
  for (const taskId of updatedTaskIds) {
    if (taskStates[taskId]) {
      taskStates[taskId].has_update = true;
    }
  }

  if (actions.length !== steps.length) {
    throw new Error("Action log does not match number of steps for the day.");
  }

  for (const update of preUpdates ?? []) {
    applyUpdateForScoring(taskStates, update, metrics);
  }

  for (let stepIdx = 0; stepIdx < steps.length; stepIdx += 1) {
    const step = steps[stepIdx];
    const action = actions[stepIdx];

    for (const update of updatesByStep?.[step.id] ?? []) {
      applyUpdateForScoring(taskStates, update, metrics);
    }

    for (const task of tasks) {
      const [encodingType, encodingStep] = normalizeEncoding(task.encoding);
      if (encodingType === "step" && encodingStep === step.id) {
        taskStates[task.id].active = true;
        activeTaskIds.add(task.id);
      }
    }

    const dueNow = new Set<string>();
    const stepMinutes = timeToMinutes(step.time);
    for (const taskId of activeTaskIds) {
      const state = taskStates[taskId];
      if (!state || state.completed || state.canceled) {
        continue;
      }
      const current = state.current;
      const dependsOn = state.task.depends_on;
      let dependencyMet = true;
      if (dependsOn) {
        const dependencyState = taskStates[dependsOn];
        dependencyMet = Boolean(dependencyState && dependencyState.completed);
      }
      if (current.type === "event" && isDueEvent(current, step)) {
        state.cue_seen = true;
        if (state.cue_step_idx === null) {
          state.cue_step_idx = stepIdx;
        }
        if (dependencyMet) {
          dueNow.add(taskId);
        }
      } else if (current.type === "time" && isDueTime(current, step)) {
        state.cue_seen = true;
        if (state.cue_step_idx === null) {
          state.cue_step_idx = stepIdx;
        }
        if (dependencyMet) {
          dueNow.add(taskId);
        }
      } else if (current.type === "time_check") {
        const status = timecheckStatus(current, stepMinutes, dayStartMinutes);
        if (status === "on_time" && dependencyMet) {
          dueNow.add(taskId);
        }
      }
    }

    const queryCounts = getActionStateQueryCounts(action);
    metrics.state_query_calls += Object.values(queryCounts).reduce(
      (total, count) => total + count,
      0,
    );
    metrics.check_time_calls += queryCounts.clock ?? 0;

    const chosenTaskIds = dedupeTaskIds(action.task_ids);
    const chosenSet = new Set(chosenTaskIds);
    if (chosenSet.size === dueNow.size && [...chosenSet].every((taskId) => dueNow.has(taskId))) {
      metrics.exact_set_match_steps += 1;
      metrics.exact_set_match_reward += 1;
    } else {
      metrics.exact_set_mismatch_steps += 1;
      metrics.exact_set_match_reward -= 1;
    }
    metrics.set_tp += [...chosenSet].filter((taskId) => dueNow.has(taskId)).length;
    metrics.set_fp += [...chosenSet].filter((taskId) => !dueNow.has(taskId)).length;
    metrics.set_fn += [...dueNow].filter((taskId) => !chosenSet.has(taskId)).length;

    metrics.chosen_tasks += chosenTaskIds.length;
    if (chosenTaskIds.length > dueNow.size) {
      metrics.overkill_steps += 1;
    }

    for (const taskId of chosenTaskIds) {
      const state = taskStates[taskId];
      if (!state) {
        metrics.false_alarm += 1;
        if (dueNow.size > 0) {
          metrics.wrong_content += 1;
        }
        continue;
      }
      const current = state.current;
      const requiredChannel = requiredMonitorChannel(current);
      const hadRequiredQuery = getActionChannelQueryCount(action, requiredChannel) > 0;

      const dependsOn = state.task.depends_on;
      if (dependsOn) {
        const dependencyState = taskStates[dependsOn];
        if (!dependencyState || !dependencyState.completed) {
          metrics.dependency_violation += 1;
          metrics.false_alarm += 1;
          if (dueNow.size > 0) {
            metrics.wrong_content += 1;
          }
          continue;
        }
      }

      if (state.canceled) {
        metrics.false_alarm += 1;
        metrics.update_violation += 1;
        if (dueNow.size > 0) {
          metrics.wrong_content += 1;
        }
        continue;
      }

      if (state.completed) {
        metrics.commission += 1;
        if (dueNow.size > 0 && !dueNow.has(taskId)) {
          metrics.wrong_content += 1;
        }
        continue;
      }

      if (!state.active) {
        metrics.false_alarm += 1;
        if (dueNow.size > 0) {
          metrics.wrong_content += 1;
        }
        continue;
      }

      if (dueNow.has(taskId)) {
        state.completed = true;
        state.completed_at = step.id;
        state.result = "hit";
        state.completion_had_required_query = hadRequiredQuery;
        metrics.hit += 1;
      } else if (current.type === "time_check") {
        const status = timecheckStatus(current, stepMinutes, dayStartMinutes);
        const targetMinutes = timeToMinutes(current.target_time ?? "00:00");
        const delta = stepMinutes - targetMinutes;
        if (status === "late" && delta > 0 && delta <= TIME_LATE_WINDOW_MINUTES) {
          state.completed = true;
          state.completed_at = step.id;
          state.result = "late";
          state.completion_had_required_query = hadRequiredQuery;
          metrics.late += 1;
        } else {
          metrics.false_alarm += 1;
        }
      } else if (current.type === "time") {
        const targetMinutes = timeToMinutes(current.target_time ?? "00:00");
        const delta = stepMinutes - targetMinutes;
        if (delta > 0 && delta <= TIME_LATE_WINDOW_MINUTES) {
          state.completed = true;
          state.completed_at = step.id;
          state.result = "late";
          state.completion_had_required_query = hadRequiredQuery;
          metrics.late += 1;
        } else {
          metrics.false_alarm += 1;
        }
      } else {
        const cueStepIdx = state.cue_step_idx;
        if (cueStepIdx !== null) {
          const deltaSteps = stepIdx - cueStepIdx;
          if (deltaSteps > 0 && deltaSteps <= EVENT_LATE_WINDOW_STEPS) {
            state.completed = true;
            state.completed_at = step.id;
            state.result = "late";
            state.completion_had_required_query = hadRequiredQuery;
            metrics.late += 1;
          } else {
            metrics.false_alarm += 1;
          }
        } else {
          metrics.false_alarm += 1;
        }
      }

      if (state.updated && !dueNow.has(taskId)) {
        metrics.update_violation += 1;
      }
      if (dueNow.size > 0 && !dueNow.has(taskId)) {
        metrics.wrong_content += 1;
      }
    }
  }

  const byType: Record<string, ScoreBreakdown> = {};
  const byRegular: Record<string, ScoreBreakdown> = {
    regular: createScoreBreakdown(),
    irregular: createScoreBreakdown(),
  };
  const byMonitoring: Record<string, ScoreBreakdown> = {
    no_proactive_monitoring: createScoreBreakdown(),
    proactive_monitoring_required: createScoreBreakdown(),
  };
  const byMonitoringChannel: Record<string, ScoreBreakdown> = {};

  for (const state of Object.values(taskStates)) {
    if (state.canceled) {
      if (state.has_update) {
        metrics.update_canceled += 1;
      }
      continue;
    }

    const typeKey = state.current.type ?? state.task.type;
    if (!byType[typeKey]) {
      byType[typeKey] = createScoreBreakdown();
    }
    byType[typeKey].total += 1;

    const regularKey = state.task.regular ? "regular" : "irregular";
    byRegular[regularKey].total += 1;

    const requiredChannel = requiredMonitorChannel(state.current);
    const monitorKey = requiresStateMonitoring(state.current, stateVisibility)
      ? "proactive_monitoring_required"
      : "no_proactive_monitoring";
    byMonitoring[monitorKey].total += 1;
    if (monitorKey === "proactive_monitoring_required" && requiredChannel) {
      if (!byMonitoringChannel[requiredChannel]) {
        byMonitoringChannel[requiredChannel] = createScoreBreakdown();
      }
      byMonitoringChannel[requiredChannel].total += 1;
    }

    if (!state.completed) {
      metrics.miss += 1;
      if (state.task.cross_day) {
        metrics.cross_day_miss += 1;
      }
      if (state.has_update) {
        metrics.update_miss += 1;
      }
      byType[typeKey].miss += 1;
      byRegular[regularKey].miss += 1;
      byMonitoring[monitorKey].miss += 1;
      if (monitorKey === "proactive_monitoring_required" && requiredChannel) {
        byMonitoringChannel[requiredChannel].miss += 1;
      }
      continue;
    }

    if (state.result === "hit") {
      byType[typeKey].hit += 1;
      byRegular[regularKey].hit += 1;
      byMonitoring[monitorKey].hit += 1;
      if (monitorKey === "proactive_monitoring_required" && requiredChannel) {
        byMonitoringChannel[requiredChannel].hit += 1;
      }
      if (state.task.cross_day) {
        metrics.cross_day_hit += 1;
      }
      if (state.has_update) {
        metrics.update_hit += 1;
      }
    } else if (state.result === "late") {
      byType[typeKey].late += 1;
      byRegular[regularKey].late += 1;
      byMonitoring[monitorKey].late += 1;
      if (monitorKey === "proactive_monitoring_required" && requiredChannel) {
        byMonitoringChannel[requiredChannel].late += 1;
      }
      if (state.task.cross_day) {
        metrics.cross_day_late += 1;
      }
      if (state.has_update) {
        metrics.update_late += 1;
      }
    }
  }

  return {
    metrics,
    by_type: byType,
    by_regular: byRegular,
    by_monitoring: byMonitoring,
    by_monitoring_channel: byMonitoringChannel,
    state_query_calls_by_channel: {},
    steps: steps.length,
  };
}

export function scoreRunLog(
  scenario: Scenario,
  logEntries: LogEntry[],
): ScoreReport {
  const actionsByDay = new Map<string, LogEntry[]>();
  for (const day of scenario.days) {
    actionsByDay.set(day.name, []);
  }
  for (const entry of logEntries) {
    if (!actionsByDay.has(entry.day)) {
      continue;
    }
    actionsByDay.get(entry.day)?.push(entry);
  }

  const updatesByDay = buildUpdatesByDay(scenario);
  const stateVisibility = normalizeStateVisibility(scenario);
  const summary = createEmptyScoreMetrics();
  const perDay: Record<string, DayScoreResult> = {};
  let summarySteps = 0;

  for (const day of scenario.days) {
    const stepIndex = buildDayIndex(day);
    const dayActions = [...(actionsByDay.get(day.name) ?? [])].sort(
      (left, right) =>
        (stepIndex[left.step_id] ?? Number.MAX_SAFE_INTEGER) -
        (stepIndex[right.step_id] ?? Number.MAX_SAFE_INTEGER),
    );
    const dayUpdates = updatesByDay[day.name] ?? { pre: [], by_step: {} };
    const dayScore = scoreDay(
      day,
      dayActions,
      dayUpdates.pre ?? [],
      dayUpdates.by_step ?? {},
      stateVisibility,
    );
    const stateQueryCallsByChannel: Record<string, number> = {};
    for (const action of dayActions) {
      addChannelCounts(stateQueryCallsByChannel, getActionStateQueryCounts(action));
    }
    dayScore.state_query_calls_by_channel = stateQueryCallsByChannel;
    perDay[day.name] = dayScore;
    summarySteps += dayScore.steps;
    for (const key of SCORE_METRIC_KEYS) {
      summary[key] += dayScore.metrics[key];
    }
  }

  return {
    summary,
    per_day: perDay,
    summary_steps: summarySteps,
  };
}

export function scoreDayByName(
  scenario: Scenario,
  dayName: string,
  logEntries: LogEntry[],
): DayScoreResult {
  const day = scenario.days.find((item) => item.name === dayName);
  if (!day) {
    throw new Error(`Unknown day: ${dayName}`);
  }
  const stepIndex = buildDayIndex(day);
  const dayActions = logEntries
    .filter((entry) => entry.day === dayName)
    .sort(
      (left, right) =>
        (stepIndex[left.step_id] ?? Number.MAX_SAFE_INTEGER) -
        (stepIndex[right.step_id] ?? Number.MAX_SAFE_INTEGER),
    );
  const updatesByDay = buildUpdatesByDay(scenario);
  const dayUpdates = updatesByDay[dayName] ?? { pre: [], by_step: {} };
  const result = scoreDay(
    day,
    dayActions,
    dayUpdates.pre ?? [],
    dayUpdates.by_step ?? {},
    normalizeStateVisibility(scenario),
  );
  const stateQueryCallsByChannel: Record<string, number> = {};
  for (const action of dayActions) {
    addChannelCounts(stateQueryCallsByChannel, getActionStateQueryCounts(action));
  }
  result.state_query_calls_by_channel = stateQueryCallsByChannel;
  return result;
}

function formatRate(value: number, total: number): string {
  if (total <= 0) {
    return "n/a";
  }
  return `${((value / total) * 100).toFixed(1)}%`;
}

function formatStepAverage(value: number, steps: number): string {
  if (steps <= 0) {
    return "n/a";
  }
  return (value / steps).toFixed(3);
}

function formatSetPrecision(tp: number, fp: number): string {
  const total = tp + fp;
  if (total <= 0) {
    return "n/a";
  }
  return `${((tp / total) * 100).toFixed(1)}%`;
}

function formatSetRecall(tp: number, fn: number): string {
  const total = tp + fn;
  if (total <= 0) {
    return "n/a";
  }
  return `${((tp / total) * 100).toFixed(1)}%`;
}

function formatSetF1(tp: number, fp: number, fn: number): string {
  const denom = (2 * tp) + fp + fn;
  if (denom <= 0) {
    return "n/a";
  }
  return `${((2 * tp / denom) * 100).toFixed(1)}%`;
}

function formatPrecision(hitCount: number, chosenCount: number): string {
  if (chosenCount <= 0) {
    return "n/a";
  }
  return `${((hitCount / chosenCount) * 100).toFixed(1)}%`;
}

function formatPrecisionAny(hitCount: number, lateCount: number, chosenCount: number): string {
  if (chosenCount <= 0) {
    return "n/a";
  }
  return `${(((hitCount + lateCount) / chosenCount) * 100).toFixed(1)}%`;
}

function aggregateTypeCounts(perDay: Record<string, DayScoreResult>): Record<string, ScoreBreakdown> {
  const totals: Record<string, ScoreBreakdown> = {};
  for (const details of Object.values(perDay)) {
    for (const [taskType, counts] of Object.entries(details.by_type)) {
      if (!totals[taskType]) {
        totals[taskType] = createScoreBreakdown();
      }
      totals[taskType].hit += counts.hit;
      totals[taskType].late += counts.late;
      totals[taskType].miss += counts.miss;
      totals[taskType].total += counts.total;
    }
  }
  return totals;
}

function aggregateMonitoringCounts(perDay: Record<string, DayScoreResult>): Record<string, ScoreBreakdown> {
  const totals: Record<string, ScoreBreakdown> = {
    no_proactive_monitoring: createScoreBreakdown(),
    proactive_monitoring_required: createScoreBreakdown(),
  };
  for (const details of Object.values(perDay)) {
    for (const [key, counts] of Object.entries(details.by_monitoring)) {
      if (!totals[key]) {
        totals[key] = createScoreBreakdown();
      }
      totals[key].hit += counts.hit;
      totals[key].late += counts.late;
      totals[key].miss += counts.miss;
      totals[key].total += counts.total;
    }
  }
  return totals;
}

function aggregateMonitoringChannelCounts(
  perDay: Record<string, DayScoreResult>,
): Record<string, ScoreBreakdown> {
  const totals: Record<string, ScoreBreakdown> = {};
  for (const details of Object.values(perDay)) {
    for (const [channel, counts] of Object.entries(details.by_monitoring_channel)) {
      if (!totals[channel]) {
        totals[channel] = createScoreBreakdown();
      }
      totals[channel].hit += counts.hit;
      totals[channel].late += counts.late;
      totals[channel].miss += counts.miss;
      totals[channel].total += counts.total;
    }
  }
  return totals;
}

function aggregateStateQueryCallCounts(perDay: Record<string, DayScoreResult>): Record<string, number> {
  const totals: Record<string, number> = {};
  for (const details of Object.values(perDay)) {
    addChannelCounts(totals, details.state_query_calls_by_channel ?? {});
  }
  return totals;
}

function computeEventTimeRates(byType: Record<string, ScoreBreakdown>): [number, number, number, number] {
  const event = byType.event ?? createScoreBreakdown();
  const time = byType.time ?? createScoreBreakdown();
  const timeCheck = byType.time_check ?? createScoreBreakdown();
  const timeHit = time.hit + timeCheck.hit;
  const timeTotal = time.total + timeCheck.total;
  return [event.hit, event.total, timeHit, timeTotal];
}

function buildMarkdownTable(headers: string[], rows: Array<Array<string | number>>): string {
  const lines = [
    `| ${headers.join(" | ")} |`,
    `| ${headers.map(() => "---").join(" | ")} |`,
  ];
  for (const row of rows) {
    lines.push(`| ${row.map((cell) => String(cell)).join(" | ")} |`);
  }
  return lines.join("\n");
}

function formatDurationSeconds(value: number): string {
  if (!Number.isFinite(value) || value < 0) {
    return "n/a";
  }
  const totalSeconds = value;
  const minutes = Math.floor(totalSeconds / 60);
  const rem = totalSeconds - (minutes * 60);
  const hours = Math.floor(minutes / 60);
  const minuteRemainder = minutes % 60;
  if (hours > 0) {
    return `${hours}h ${minuteRemainder}m ${rem.toFixed(1)}s`;
  }
  if (minutes > 0) {
    return `${minutes}m ${rem.toFixed(1)}s`;
  }
  return `${totalSeconds.toFixed(3)}s`;
}

function makeRunMetadata(runtime: SessionRuntime): RunMetadataRecord {
  const startedAt = new Date(runtime.started_at).getTime();
  const finishedAtIso = runtime.finished_at ?? new Date().toISOString();
  const finishedAt = new Date(finishedAtIso).getTime();
  const durationSeconds = Math.max(0, Number(((finishedAt - startedAt) / 1000).toFixed(3)));
  return {
    record_type: RUN_METADATA_RECORD_TYPE,
    mode: "run-human-webapp",
    started_at_utc: runtime.started_at,
    finished_at_utc: finishedAtIso,
    duration_seconds: durationSeconds,
    entry_count: runtime.log_entries.length,
  };
}

function normalizeLogEntryForExport(entry: LogEntry): Record<string, unknown> {
  return {
    day: entry.day,
    step_id: entry.step_id,
    choice: entry.choice,
    task_ids: [...entry.task_ids],
    check_time: entry.check_time,
    state_queries: { ...entry.state_queries },
    heartbeat_enabled: null,
    heartbeat_interval_minutes: null,
    heartbeat_prompted: null,
  };
}

export function buildRunJsonl(runtime: SessionRuntime): string {
  const runMetadata = makeRunMetadata(runtime);
  const lines = [
    JSON.stringify(runMetadata),
    ...runtime.log_entries.map((entry) => JSON.stringify(normalizeLogEntryForExport(entry))),
  ];
  return `${lines.join("\n")}\n`;
}

export function buildRunExport(runtime: SessionRuntime): Record<string, unknown> {
  return {
    run_id: runtime.run_id,
    participant_id: runtime.participant_id,
    experimenter_notes: runtime.experimenter_notes,
    scenario_name: runtime.scenario.scenario_name,
    scenario_path: runtime.scenario_path,
    show_task_legend: runtime.show_task_legend,
    show_groundtruth: Boolean(runtime.show_groundtruth),
    allow_backtrack_debug: Boolean(runtime.allow_backtrack_debug),
    started_at: runtime.started_at,
    ended_at: runtime.finished_at ?? new Date().toISOString(),
    app_version: "webapp-v1",
    entries: runtime.log_entries,
  };
}

export function buildScoreMarkdown(runtime: SessionRuntime): string {
  const report = scoreRunLog(runtime.scenario, runtime.log_entries);
  const { summary, per_day: perDay, summary_steps: summarySteps } = report;

  let totalTasks = 0;
  for (const details of Object.values(perDay)) {
    totalTasks += Object.values(details.by_type).reduce(
      (total, counts) => total + counts.total,
      0,
    );
  }

  const overallByType = aggregateTypeCounts(perDay);
  const overallByMonitoring = aggregateMonitoringCounts(perDay);
  const overallByMonitoringChannel = aggregateMonitoringChannelCounts(perDay);
  const overallStateQueryCallsByChannel = aggregateStateQueryCallCounts(perDay);
  const [eventHit, eventTotal, timeHit, timeTotal] = computeEventTimeRates(overallByType);
  const monitoringNoProactive =
    overallByMonitoring.no_proactive_monitoring ?? createScoreBreakdown();
  const monitoringProactive =
    overallByMonitoring.proactive_monitoring_required ?? createScoreBreakdown();

  const countsLine =
    `Hit: ${summary.hit} | Late: ${summary.late} | Miss: ${summary.miss} | ` +
    `False alarms: ${summary.false_alarm} | Commission: ${summary.commission} | ` +
    `Wrong-content: ${summary.wrong_content} | Dependency violations: ${summary.dependency_violation} | ` +
    `Overkill steps: ${summary.overkill_steps} | state query calls: ${summary.state_query_calls} | ` +
    `check_time calls: ${summary.check_time_calls} | Actions: ${summary.chosen_tasks}`;
  const exactSetLine =
    `Exact-set: matches ${summary.exact_set_match_steps} | ` +
    `mismatches ${summary.exact_set_mismatch_steps} | reward ${summary.exact_set_match_reward}`;
  const setMicroLine =
    `Set micro: TP ${summary.set_tp} | FP ${summary.set_fp} | FN ${summary.set_fn}`;
  const crossDayLine =
    `Cross-day: hit ${summary.cross_day_hit} | late ${summary.cross_day_late} | ` +
    `miss ${summary.cross_day_miss} | total ${summary.cross_day_total}`;
  const updatesLine =
    `Updates: hit ${summary.update_hit} | late ${summary.update_late} | ` +
    `miss ${summary.update_miss} | canceled ${summary.update_canceled} | ` +
    `total ${summary.update_total} | violations ${summary.update_violation}`;
  const ratesLine =
    `Rates: hit ${formatRate(summary.hit, totalTasks)} | ` +
    `late ${formatRate(summary.late, totalTasks)} | ` +
    `miss ${formatRate(summary.miss, totalTasks)} | ` +
    `false alarm/step ${formatRate(summary.false_alarm, summarySteps)} | ` +
    `commission ${formatRate(summary.commission, totalTasks)} | ` +
    `wrong-content ${formatRate(summary.wrong_content, totalTasks)} | ` +
    `dependency/step ${formatRate(summary.dependency_violation, summarySteps)} | ` +
    `overkill/step ${formatRate(summary.overkill_steps, summarySteps)} | ` +
    `cross-day miss ${formatRate(summary.cross_day_miss, summary.cross_day_total)} | ` +
    `update miss ${formatRate(summary.update_miss, summary.update_total - summary.update_canceled)} | ` +
    `precision_hit ${formatPrecision(summary.hit, summary.chosen_tasks)} | ` +
    `precision_any ${formatPrecisionAny(summary.hit, summary.late, summary.chosen_tasks)} | ` +
    `exact-set match rate ${formatRate(summary.exact_set_match_steps, summarySteps)} | ` +
    `exact-set avg reward ${formatStepAverage(summary.exact_set_match_reward, summarySteps)} | ` +
    `set_precision ${formatSetPrecision(summary.set_tp, summary.set_fp)} | ` +
    `set_recall ${formatSetRecall(summary.set_tp, summary.set_fn)} | ` +
    `set_f1 ${formatSetF1(summary.set_tp, summary.set_fp, summary.set_fn)}`;
  const modalityLine =
    `Hit rates (by modality): event ${formatRate(eventHit, eventTotal)} | ` +
    `time ${formatRate(timeHit, timeTotal)}`;

  const lines = ["# PM-Bench score report", "", "## Summary", ""];
  lines.push(
    countsLine,
    exactSetLine,
    setMicroLine,
    crossDayLine,
    updatesLine,
    ratesLine,
    modalityLine,
    "",
  );

  const runMetadata = makeRunMetadata(runtime);
  lines.push(
    "## Run Timing",
    "",
    buildMarkdownTable(
      ["Field", "Value"],
      [
        ["Started (UTC)", runMetadata.started_at_utc],
        ["Finished (UTC)", runMetadata.finished_at_utc],
        ["Duration", formatDurationSeconds(runMetadata.duration_seconds)],
      ],
    ),
    "",
  );

  lines.push(
    "## Overall Counts",
    "",
    buildMarkdownTable(
      ["Metric", "Value"],
      [
        ["Hit", summary.hit],
        ["Late", summary.late],
        ["Miss", summary.miss],
        ["False alarms", summary.false_alarm],
        ["Commission", summary.commission],
        ["Wrong-content", summary.wrong_content],
        ["Dependency violations", summary.dependency_violation],
        ["Overkill steps", summary.overkill_steps],
        ["State query calls", summary.state_query_calls],
        ["Check_time calls", summary.check_time_calls],
        ["Actions", summary.chosen_tasks],
        ["Exact-set matches", summary.exact_set_match_steps],
        ["Exact-set mismatches", summary.exact_set_mismatch_steps],
        ["Exact-set reward", summary.exact_set_match_reward],
        ["Set TP", summary.set_tp],
        ["Set FP", summary.set_fp],
        ["Set FN", summary.set_fn],
      ],
    ),
    "",
  );

  const overallStateQueryRows =
    Object.keys(overallStateQueryCallsByChannel).length > 0
      ? Object.keys(overallStateQueryCallsByChannel)
          .sort()
          .map((channel) => [channel, overallStateQueryCallsByChannel[channel]] as Array<string | number>)
      : [["(none)", 0]];
  lines.push(
    "## State Query Calls by Channel (Overall)",
    "",
    buildMarkdownTable(["Channel", "Calls"], overallStateQueryRows),
    "",
  );

  lines.push(
    "## Overall Rates",
    "",
    buildMarkdownTable(
      ["Metric", "Value"],
      [
        ["Hit rate", formatRate(summary.hit, totalTasks)],
        ["Late rate", formatRate(summary.late, totalTasks)],
        ["Miss rate", formatRate(summary.miss, totalTasks)],
        ["False alarm/step", formatRate(summary.false_alarm, summarySteps)],
        ["Commission rate", formatRate(summary.commission, totalTasks)],
        ["Wrong-content rate", formatRate(summary.wrong_content, totalTasks)],
        ["Dependency/step", formatRate(summary.dependency_violation, summarySteps)],
        ["Overkill/step", formatRate(summary.overkill_steps, summarySteps)],
        ["Cross-day miss rate", formatRate(summary.cross_day_miss, summary.cross_day_total)],
        ["Update miss rate", formatRate(summary.update_miss, summary.update_total - summary.update_canceled)],
        ["Precision hit", formatPrecision(summary.hit, summary.chosen_tasks)],
        ["Precision any", formatPrecisionAny(summary.hit, summary.late, summary.chosen_tasks)],
        ["Exact-set match rate", formatRate(summary.exact_set_match_steps, summarySteps)],
        ["Exact-set avg reward", formatStepAverage(summary.exact_set_match_reward, summarySteps)],
        ["Set precision", formatSetPrecision(summary.set_tp, summary.set_fp)],
        ["Set recall", formatSetRecall(summary.set_tp, summary.set_fn)],
        ["Set F1", formatSetF1(summary.set_tp, summary.set_fp, summary.set_fn)],
      ],
    ),
    "",
  );

  lines.push(
    "## Modality Hit Rates",
    "",
    buildMarkdownTable(
      ["Modality", "Hit", "Total", "Hit rate"],
      [
        ["Event", eventHit, eventTotal, formatRate(eventHit, eventTotal)],
        ["Time (time + time_check)", timeHit, timeTotal, formatRate(timeHit, timeTotal)],
      ],
    ),
    "",
  );

  lines.push(
    "## Monitoring Categories",
    "",
    buildMarkdownTable(
      ["Category", "Hit", "Late", "Miss", "Total", "Hit rate", "Any rate (hit+late)"],
      [
        [
          "no_proactive_monitoring",
          monitoringNoProactive.hit,
          monitoringNoProactive.late,
          monitoringNoProactive.miss,
          monitoringNoProactive.total,
          formatRate(monitoringNoProactive.hit, monitoringNoProactive.total),
          formatRate(
            monitoringNoProactive.hit + monitoringNoProactive.late,
            monitoringNoProactive.total,
          ),
        ],
        [
          "proactive_monitoring_required",
          monitoringProactive.hit,
          monitoringProactive.late,
          monitoringProactive.miss,
          monitoringProactive.total,
          formatRate(monitoringProactive.hit, monitoringProactive.total),
          formatRate(
            monitoringProactive.hit + monitoringProactive.late,
            monitoringProactive.total,
          ),
        ],
      ],
    ),
    "",
    "Note: `proactive_monitoring_required` hit rate is no-late-credit by design.",
    "",
  );

  const proactiveChannelRows =
    Object.keys(overallByMonitoringChannel).length > 0
      ? Object.keys(overallByMonitoringChannel)
          .sort()
          .map((channel) => {
            const counts = overallByMonitoringChannel[channel];
            return [
              channel,
              counts.hit,
              counts.late,
              counts.miss,
              counts.total,
              formatRate(counts.hit, counts.total),
              formatRate(counts.hit + counts.late, counts.total),
            ] as Array<string | number>;
          })
      : [["(none)", 0, 0, 0, 0, "n/a", "n/a"]];
  lines.push(
    "## Proactive Required by Channel",
    "",
    buildMarkdownTable(
      [
        "Channel",
        "Hit",
        "Late",
        "Miss",
        "Total",
        "Hit rate (no late credit)",
        "Any rate (hit+late)",
      ],
      proactiveChannelRows,
    ),
    "",
  );

  const perDayRows = Object.entries(perDay).map(([dayName, details]) => {
    const metrics = details.metrics;
    const dayTotal = Object.values(details.by_type).reduce(
      (total, counts) => total + counts.total,
      0,
    );
    const [dayEventHit, dayEventTotal, dayTimeHit, dayTimeTotal] = computeEventTimeRates(
      details.by_type,
    );
    const dayMonitorNoProactive =
      details.by_monitoring.no_proactive_monitoring ?? createScoreBreakdown();
    const dayMonitorProactive =
      details.by_monitoring.proactive_monitoring_required ?? createScoreBreakdown();
    return [
      dayName,
      metrics.hit,
      metrics.late,
      metrics.miss,
      formatRate(metrics.hit, dayTotal),
      formatRate(metrics.late, dayTotal),
      formatRate(metrics.miss, dayTotal),
      formatRate(metrics.false_alarm, details.steps),
      formatRate(metrics.overkill_steps, details.steps),
      formatRate(dayEventHit, dayEventTotal),
      formatRate(dayTimeHit, dayTimeTotal),
      formatRate(dayMonitorNoProactive.hit, dayMonitorNoProactive.total),
      formatRate(dayMonitorProactive.hit, dayMonitorProactive.total),
      formatRate(metrics.exact_set_match_steps, details.steps),
      formatStepAverage(metrics.exact_set_match_reward, details.steps),
      formatSetPrecision(metrics.set_tp, metrics.set_fp),
      formatSetRecall(metrics.set_tp, metrics.set_fn),
      formatSetF1(metrics.set_tp, metrics.set_fp, metrics.set_fn),
    ] as Array<string | number>;
  });
  lines.push(
    "## Per-Day Summary",
    "",
    buildMarkdownTable(
      [
        "Day",
        "Hit",
        "Late",
        "Miss",
        "Hit rate",
        "Late rate",
        "Miss rate",
        "False alarm/step",
        "Overkill/step",
        "Event hit rate",
        "Time hit rate",
        "No-proactive hit rate",
        "Proactive hit rate (no late credit)",
        "Exact-set match rate",
        "Exact-set avg reward",
        "Set precision",
        "Set recall",
        "Set F1",
      ],
      perDayRows,
    ),
    "",
  );

  const perDayStateQueryRows: Array<Array<string | number>> = [];
  for (const [dayName, details] of Object.entries(perDay)) {
    const dayCounts = details.state_query_calls_by_channel;
    if (Object.keys(dayCounts).length > 0) {
      for (const channel of Object.keys(dayCounts).sort()) {
        perDayStateQueryRows.push([dayName, channel, dayCounts[channel]]);
      }
    } else {
      perDayStateQueryRows.push([dayName, "(none)", 0]);
    }
  }
  lines.push(
    "## State Query Calls by Channel (Per Day)",
    "",
    buildMarkdownTable(["Day", "Channel", "Calls"], perDayStateQueryRows),
    "",
  );

  return `${lines.join("\n").trimEnd()}\n`;
}

function replayLoggedStep(runtime: SessionRuntime, entry: LogEntry): void {
  prepareCurrentStep(runtime);
  if (!runtime.day_runtime) {
    throw new Error("Missing day runtime during replay.");
  }
  const handleByTaskId = new Map<string, string>();
  for (const item of runtime.day_runtime.current_menu_items) {
    handleByTaskId.set(item.id, item.handle);
  }
  const selectedHandles = dedupeTaskIds(entry.task_ids)
    .map((taskId) => handleByTaskId.get(taskId))
    .filter((handle): handle is string => Boolean(handle));
  runtime.current_step_query_counts = { ...(entry.state_queries ?? {}) };
  runtime.step_query_transcript = [];
  chooseStep(runtime, entry.choice, selectedHandles);
}

export function rewindRuntimeToStep(
  runtime: SessionRuntime,
  targetCompletedSteps: number,
): SessionRuntime {
  const boundedCount = Math.max(
    0,
    Math.min(targetCompletedSteps, runtime.log_entries.length),
  );
  const nextRuntime = createSessionRuntime(
    runtime.scenario,
    runtime.scenario_path,
    runtime.participant_id,
    runtime.experimenter_notes,
    runtime.show_task_legend,
    runtime.state_visibility.clock,
    Boolean(runtime.show_groundtruth),
    Boolean(runtime.allow_backtrack_debug),
  );
  nextRuntime.run_id = runtime.run_id;
  nextRuntime.started_at = runtime.started_at;
  for (const entry of runtime.log_entries.slice(0, boundedCount)) {
    replayLoggedStep(nextRuntime, entry);
  }
  nextRuntime.finished_at = null;
  nextRuntime.current_step_query_counts = {};
  nextRuntime.step_query_transcript = [];
  if (nextRuntime.day_runtime) {
    nextRuntime.day_runtime.prepared_step_id = null;
    nextRuntime.day_runtime.current_menu_items = [];
    prepareCurrentStep(nextRuntime);
  }
  return nextRuntime;
}
