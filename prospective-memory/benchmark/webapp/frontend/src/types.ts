export type TaskType = "event" | "time" | "time_check";
export type StateChannelMode = "delta" | "snapshot";
export type UpdateAction = "cancel" | "reschedule" | "override";
export type Choice = "A" | "B" | "C";

export interface StateEventObject {
  id?: string;
  text?: string;
  value?: unknown;
  meta?: Record<string, unknown>;
}

export type StateEventInput = string | StateEventObject;

export interface StepUpdate {
  task_id?: string;
  action?: UpdateAction;
  cue_id?: string;
  target_day?: string;
  new_type?: TaskType;
  new_cue_id?: string;
  new_target_time?: string;
  new_window_before?: number;
  new_window_after?: number;
  new_label?: string;
  new_action_text?: string;
}

export interface GroundtruthAction {
  id: string;
  task_handle: string;
}

export interface StepGroundtruth {
  status: "due" | "none";
  actions: GroundtruthAction[];
}

export interface Step {
  id: string;
  time: string;
  text: string;
  options: string[];
  cues: string[];
  updates?: StepUpdate[];
  state_events?: Record<string, StateEventInput[]>;
  groundtruth?: StepGroundtruth;
}

export interface Task {
  id: string;
  label: string;
  action_text?: string;
  type: TaskType;
  cue_id?: string;
  cue_channel?: string;
  target_time?: string;
  window_before?: number;
  window_after?: number;
  regular: boolean;
  encoding: string;
  depends_on?: string;
  cross_day?: boolean;
  cross_day_offset?: number;
}

export interface Lure {
  id: string;
  action_text?: string;
}

export type LureInput = string | Lure;

export interface Day {
  name: string;
  start_instructions: string[];
  tasks: Task[];
  lures: LureInput[];
  steps: Step[];
}

export interface StateChannelConfig {
  mode?: StateChannelMode;
  default_item?: StateEventObject;
}

export interface Scenario {
  scenario_name: string;
  days: Day[];
  state_visibility?: Record<string, boolean>;
  state_channels?: Record<string, StateChannelConfig>;
  time_visible_by_default?: boolean;
}

export interface StateItem {
  id?: string;
  text?: string;
  value?: unknown;
  meta: Record<string, unknown>;
}

export interface StateQueryResponse {
  channel: string;
  items: StateItem[];
  meta: {
    day: string;
    step_id: string;
  };
}

export interface LogEntry {
  day: string;
  step_id: string;
  choice: Choice;
  task_ids: string[];
  check_time: number;
  state_queries: Record<string, number>;
}

export interface ScoreMetrics {
  hit: number;
  late: number;
  miss: number;
  false_alarm: number;
  commission: number;
  wrong_content: number;
  check_time_calls: number;
  state_query_calls: number;
  overkill_steps: number;
  chosen_tasks: number;
  dependency_violation: number;
  cross_day_total: number;
  cross_day_hit: number;
  cross_day_late: number;
  cross_day_miss: number;
  update_total: number;
  update_hit: number;
  update_late: number;
  update_miss: number;
  update_violation: number;
  update_canceled: number;
  canceled_total: number;
  exact_set_match_steps: number;
  exact_set_mismatch_steps: number;
  exact_set_match_reward: number;
  set_tp: number;
  set_fp: number;
  set_fn: number;
}

export interface ScoreBreakdown {
  hit: number;
  late: number;
  miss: number;
  total: number;
}

export interface DayScoreResult {
  metrics: ScoreMetrics;
  by_type: Record<string, ScoreBreakdown>;
  by_regular: Record<string, ScoreBreakdown>;
  by_monitoring: Record<string, ScoreBreakdown>;
  by_monitoring_channel: Record<string, ScoreBreakdown>;
  state_query_calls_by_channel: Record<string, number>;
  steps: number;
}

export interface ScoreReport {
  summary: ScoreMetrics;
  per_day: Record<string, DayScoreResult>;
  summary_steps: number;
}

export interface RunMetadataRecord {
  record_type: "run_metadata";
  mode: string;
  started_at_utc: string;
  finished_at_utc: string;
  duration_seconds: number;
  entry_count: number;
  model?: string;
  backend?: string;
}

export interface TaskRuntimeCurrent {
  type?: TaskType;
  cue_id?: string;
  cue_channel?: string;
  target_time?: string;
  window_before?: number;
  window_after?: number;
  label?: string;
  action_text?: string;
}

export interface TaskRuntimeState {
  completed: boolean;
  completed_at: string | null;
  cue_seen: boolean;
  cue_step_idx: number | null;
  active: boolean;
  result: string | null;
  task: Task;
  current: TaskRuntimeCurrent;
  canceled: boolean;
  canceled_by_dependency: boolean;
  updated: boolean;
  has_update: boolean;
  completion_had_required_query: boolean;
}

export interface DayRuntime {
  day_name: string;
  day_start_minutes: number;
  step_index_by_id: Record<string, number>;
  task_states: Record<string, TaskRuntimeState>;
  active_task_ids: string[];
  lure_catalog: Lure[];
  id_to_handle: Record<string, string>;
  prepared_step_id: string | null;
  current_menu_items: ActionMenuItem[];
  start_instructions: string[];
  last_query_step_by_channel: Record<string, number>;
  last_snapshot_item_by_channel: Record<string, StateItem>;
}

export interface DayUpdates {
  pre: StepUpdate[];
  by_step: Record<string, StepUpdate[]>;
}

export interface SessionRuntime {
  scenario: Scenario;
  scenario_path: string;
  participant_id: string;
  experimenter_notes: string;
  show_task_legend: boolean;
  show_groundtruth?: boolean;
  allow_backtrack_debug?: boolean;
  allowed_channels: string[];
  state_visibility: Record<string, boolean>;
  state_channels: Record<string, StateChannelConfig>;
  updates_by_day: Record<string, DayUpdates>;
  day_idx: number;
  step_idx: number;
  day_runtime: DayRuntime | null;
  current_step_query_counts: Record<string, number>;
  step_query_transcript: string[];
  log_entries: LogEntry[];
  started_at: string;
  finished_at: string | null;
  run_id: string;
}

export interface ActionMenuItem {
  id: string;
  handle: string;
  action_text: string;
}
