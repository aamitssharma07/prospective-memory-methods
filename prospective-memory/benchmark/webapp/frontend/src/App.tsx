import { useEffect, useMemo, useState } from "react";
import {
  buildRunJsonl,
  buildScoreMarkdown,
  chooseStep,
  createSessionRuntime,
  getCompletedSteps,
  getCurrentActionMenu,
  getCurrentDay,
  getCurrentStep,
  getDailyHeaderLines,
  getTimeDisplay,
  getTotalSteps,
  isSessionComplete,
  queryState,
  rewindRuntimeToStep,
  scoreDayByName,
  scoreRunLog,
} from "./engine";
import { clearSavedSession, loadSavedSession, saveSession } from "./storage";
import type { Choice, DayScoreResult, Scenario, SessionRuntime } from "./types";

const DEFAULT_SCENARIO_PATH = "data/synthetic_week_v9.json";
const DEFAULT_SCENARIO_ASSET = "/scenarios/synthetic_week_v9.json";

type AppPhase = "loading" | "start" | "play" | "day_summary" | "complete" | "error";

function makeDownloadStem(runtime: SessionRuntime): string {
  const safeParticipant = runtime.participant_id.replace(/[^a-zA-Z0-9_-]+/g, "-");
  const startedAt = new Date(runtime.started_at);
  const yyyy = String(startedAt.getUTCFullYear());
  const mm = String(startedAt.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(startedAt.getUTCDate()).padStart(2, "0");
  const hh = String(startedAt.getUTCHours()).padStart(2, "0");
  const min = String(startedAt.getUTCMinutes()).padStart(2, "0");
  const sec = String(startedAt.getUTCSeconds()).padStart(2, "0");
  const stamp = `${yyyy}${mm}${dd}-${hh}${min}${sec}`;
  return `run-${safeParticipant || "participant"}-${stamp}`;
}

function downloadText(filename: string, content: string, type: string): void {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function App() {
  const [phase, setPhase] = useState<AppPhase>("loading");
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [runtime, setRuntime] = useState<SessionRuntime | null>(null);
  const [participantId, setParticipantId] = useState("");
  const [notes, setNotes] = useState("");
  const [showTimeEachStep, setShowTimeEachStep] = useState(false);
  const [showGroundtruth, setShowGroundtruth] = useState(false);
  const [allowBacktrackDebug, setAllowBacktrackDebug] = useState(false);
  const [selectedChoice, setSelectedChoice] = useState<Choice | null>(null);
  const [selectedActionHandles, setSelectedActionHandles] = useState<string[]>([]);
  const [errorMessage, setErrorMessage] = useState("");
  const [savedRuntime, setSavedRuntime] = useState<SessionRuntime | null>(null);
  const [daySummary, setDaySummary] = useState<{
    dayName: string;
    nextDayName: string | null;
    result: DayScoreResult;
  } | null>(null);

  useEffect(() => {
    async function loadScenario(): Promise<void> {
      try {
        const response = await fetch(DEFAULT_SCENARIO_ASSET);
        if (!response.ok) {
          throw new Error(`Failed to load scenario: ${response.status}`);
        }
        const parsed = (await response.json()) as Scenario;
        setScenario(parsed);
        const scenarioClockDefault = Boolean(
          parsed.state_visibility?.clock ?? parsed.time_visible_by_default ?? false,
        );
        setShowTimeEachStep(scenarioClockDefault);
        const saved = loadSavedSession();
        if (
          saved?.runtime &&
          saved.runtime.day_runtime &&
          "task_states" in saved.runtime.day_runtime &&
          !isSessionComplete(saved.runtime)
        ) {
          setSavedRuntime(saved.runtime);
        }
        setPhase("start");
      } catch (err) {
        const message = err instanceof Error ? err.message : "Unknown error.";
        setErrorMessage(message);
        setPhase("error");
      }
    }
    void loadScenario();
  }, []);

  useEffect(() => {
    if (!runtime || isSessionComplete(runtime)) {
      return;
    }
    saveSession(runtime);
  }, [runtime]);

  const currentDay = runtime ? getCurrentDay(runtime) : null;
  const currentStep = runtime ? getCurrentStep(runtime) : null;
  const totalSteps = runtime ? getTotalSteps(runtime) : 0;
  const completedSteps = runtime ? getCompletedSteps(runtime) : 0;
  const progressPct = totalSteps > 0 ? (completedSteps / totalSteps) * 100 : 0;
  const dayTotalSteps = currentDay?.steps.length ?? 0;
  const dayCompletedSteps = runtime ? runtime.step_idx : 0;
  const dayProgressPct =
    dayTotalSteps > 0 ? (dayCompletedSteps / dayTotalSteps) * 100 : 0;
  const actionMenu = runtime ? getCurrentActionMenu(runtime) : [];
  const groundtruthTaskIds = useMemo(() => {
    if (!runtime?.show_groundtruth) {
      return new Set<string>();
    }
    return new Set(
      (currentStep?.groundtruth?.actions ?? []).map((action) => action.id),
    );
  }, [runtime?.show_groundtruth, currentStep]);
  const visibleTime = runtime ? getTimeDisplay(runtime) : null;
  const runDuration = useMemo(() => {
    if (!runtime) {
      return "00:00";
    }
    const started = new Date(runtime.started_at).getTime();
    const ended = runtime.finished_at
      ? new Date(runtime.finished_at).getTime()
      : Date.now();
    const seconds = Math.max(0, Math.floor((ended - started) / 1000));
    const min = String(Math.floor(seconds / 60)).padStart(2, "0");
    const sec = String(seconds % 60).padStart(2, "0");
    return `${min}:${sec}`;
  }, [runtime]);
  const scoreReport = useMemo(() => {
    if (!runtime || !isSessionComplete(runtime)) {
      return null;
    }
    try {
      return scoreRunLog(runtime.scenario, runtime.log_entries);
    } catch {
      return null;
    }
  }, [runtime]);

  function formatRate(value: number, total: number): string {
    if (total <= 0) {
      return "n/a";
    }
    return `${((value / total) * 100).toFixed(1)}%`;
  }

  function handleStartSession(): void {
    if (!scenario) {
      return;
    }
    const trimmedId = participantId.trim();
    if (!trimmedId) {
      setErrorMessage("Participant ID is required.");
      return;
    }
    setErrorMessage("");
    const nextRuntime = createSessionRuntime(
      scenario,
      DEFAULT_SCENARIO_PATH,
      trimmedId,
      notes.trim(),
      false,
      showTimeEachStep,
      showGroundtruth,
      allowBacktrackDebug,
    );
    setRuntime(nextRuntime);
    setDaySummary(null);
    setSelectedChoice(null);
    setSelectedActionHandles([]);
    setPhase("play");
  }

  function handleResumeSaved(): void {
    if (!savedRuntime) {
      return;
    }
    const resumedRuntime = structuredClone(savedRuntime);
    resumedRuntime.show_task_legend = false;
    setRuntime(resumedRuntime);
    setDaySummary(null);
    setParticipantId(resumedRuntime.participant_id);
    setNotes(resumedRuntime.experimenter_notes);
    setShowGroundtruth(Boolean(resumedRuntime.show_groundtruth));
    setAllowBacktrackDebug(Boolean(resumedRuntime.allow_backtrack_debug));
    setSelectedChoice(null);
    setSelectedActionHandles([]);
    setPhase("play");
  }

  function handleDiscardSaved(): void {
    clearSavedSession();
    setSavedRuntime(null);
  }

  function toggleActionHandle(handle: string): void {
    setSelectedActionHandles((prev) => {
      if (prev.includes(handle)) {
        return prev.filter((item) => item !== handle);
      }
      return [...prev, handle];
    });
  }

  function handleQuery(channel: string): void {
    if (!runtime) {
      return;
    }
    try {
      const nextRuntime = structuredClone(runtime);
      queryState(nextRuntime, channel);
      setRuntime(nextRuntime);
      setErrorMessage("");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to query state.";
      setErrorMessage(message);
    }
  }

  function handleSubmitStep(): void {
    if (!runtime) {
      return;
    }
    if (!selectedChoice) {
      setErrorMessage("Choose A, B, or C before submitting.");
      return;
    }
    try {
      const prevDayIdx = runtime.day_idx;
      const prevDayName = runtime.scenario.days[prevDayIdx]?.name ?? null;
      const nextRuntime = structuredClone(runtime);
      chooseStep(nextRuntime, selectedChoice, selectedActionHandles);
      setRuntime(nextRuntime);
      setSelectedChoice(null);
      setSelectedActionHandles([]);
      setErrorMessage("");
      if (isSessionComplete(nextRuntime)) {
        setDaySummary(null);
        clearSavedSession();
        setPhase("complete");
        return;
      }
      if (prevDayName && nextRuntime.day_idx > prevDayIdx) {
        const dayScore = scoreDayByName(
          nextRuntime.scenario,
          prevDayName,
          nextRuntime.log_entries,
        );
        const nextDayName = nextRuntime.scenario.days[nextRuntime.day_idx]?.name ?? null;
        setDaySummary({
          dayName: prevDayName,
          nextDayName,
          result: dayScore,
        });
        setPhase("day_summary");
        return;
      }
      setPhase("play");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to submit step.";
      setErrorMessage(message);
    }
  }

  function handleExportRun(): void {
    if (!runtime) {
      return;
    }
    downloadText(
      `${makeDownloadStem(runtime)}.jsonl`,
      buildRunJsonl(runtime),
      "application/x-ndjson",
    );
  }

  function handleExportScore(): void {
    if (!runtime) {
      return;
    }
    downloadText(
      `${makeDownloadStem(runtime)}.score.md`,
      buildScoreMarkdown(runtime),
      "text/markdown",
    );
  }

  function handleResetAfterCompletion(): void {
    setRuntime(null);
    setDaySummary(null);
    setParticipantId("");
    setNotes("");
    setShowGroundtruth(false);
    setAllowBacktrackDebug(false);
    setSelectedChoice(null);
    setSelectedActionHandles([]);
    setErrorMessage("");
    setPhase("start");
  }

  function handleContinueAfterDaySummary(): void {
    setDaySummary(null);
    setPhase("play");
  }

  function handleStepBack(): void {
    if (!runtime || !runtime.allow_backtrack_debug || runtime.log_entries.length === 0) {
      return;
    }
    try {
      const rewound = rewindRuntimeToStep(runtime, runtime.log_entries.length - 1);
      setRuntime(rewound);
      setDaySummary(null);
      setSelectedChoice(null);
      setSelectedActionHandles([]);
      setErrorMessage("");
      setPhase("play");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to step back.";
      setErrorMessage(message);
    }
  }

  if (phase === "loading") {
    return <main className="screen center">Loading study...</main>;
  }

  if (phase === "error") {
    return (
      <main className="screen center">
        <section className="panel">
          <h1>Unable to load PM-Bench study</h1>
          <p>{errorMessage}</p>
        </section>
      </main>
    );
  }

  if (phase === "start") {
    return (
      <main className="screen start-screen">
        <div className="ambient-bg" aria-hidden />
        <section className="panel start-card">
          <p className="eyebrow">PM-Bench Human Study</p>
          <h1>Participant Session</h1>
          <p className="muted">
            Default scenario: <code>{DEFAULT_SCENARIO_PATH}</code>
          </p>
          <div className="intro-block">
            <p className="intro-title">What to do</p>
            <p>
              Read each step, choose one ongoing option (A/B/C), and optionally
              select any action handles you want to perform at that step.
            </p>
            <p>
              You may query state channels (for example clock, calendar, shipment
              status) before choosing. Queries do not advance the step.
            </p>
            <p>
              Continue until the end of the session, then download the run JSONL
              and score report.
            </p>
          </div>
          {savedRuntime && (
            <div className="notice">
              <p>
                An unfinished local session was found for participant{" "}
                <strong>{savedRuntime.participant_id}</strong>.
              </p>
              <div className="inline-actions">
                <button className="btn" onClick={handleResumeSaved}>
                  Resume Saved Session
                </button>
                <button className="btn subtle" onClick={handleDiscardSaved}>
                  Discard Saved Session
                </button>
              </div>
            </div>
          )}
          <label className="field">
            <span>Participant ID</span>
            <input
              value={participantId}
              onChange={(e) => setParticipantId(e.target.value)}
              placeholder="e.g. P001"
            />
          </label>
          <label className="field">
            <span>Experimenter Notes (optional)</span>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Session metadata or notes..."
              rows={3}
            />
          </label>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={showTimeEachStep}
              onChange={(e) => setShowTimeEachStep(e.target.checked)}
            />
            <span>Show time automatically at each step</span>
          </label>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={showGroundtruth}
              onChange={(e) => setShowGroundtruth(e.target.checked)}
            />
            <span>Highlight groundtruth task handles during the run</span>
          </label>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={allowBacktrackDebug}
              onChange={(e) => setAllowBacktrackDebug(e.target.checked)}
            />
            <span>Allow stepping backward for debugging</span>
          </label>
          {errorMessage && <p className="error">{errorMessage}</p>}
          <div className="inline-actions">
            <button className="btn primary" onClick={handleStartSession}>
              Start Study
            </button>
          </div>
        </section>
      </main>
    );
  }

  if (!runtime) {
    return null;
  }

  if (phase === "day_summary") {
    if (!daySummary) {
      return null;
    }
    const dayMetrics = daySummary.result.metrics;
    return (
      <main className="screen complete-screen">
        <div className="ambient-bg" aria-hidden />
        <section className="panel complete-card">
          <p className="eyebrow">Day Complete</p>
          <h1>{daySummary.dayName} Results</h1>
          <table className="results-table">
            <tbody>
              <tr>
                <th>Hit</th>
                <td>{dayMetrics.hit}</td>
                <th>Late</th>
                <td>{dayMetrics.late}</td>
              </tr>
              <tr>
                <th>Miss</th>
                <td>{dayMetrics.miss}</td>
                <th>False Alarm</th>
                <td>{dayMetrics.false_alarm}</td>
              </tr>
              <tr>
                <th>Wrong Content</th>
                <td>{dayMetrics.wrong_content}</td>
                <th>Update Violation</th>
                <td>{dayMetrics.update_violation}</td>
              </tr>
              <tr>
                <th>Chosen Actions</th>
                <td>{dayMetrics.chosen_tasks}</td>
                <th>State Queries</th>
                <td>{dayMetrics.state_query_calls}</td>
              </tr>
            </tbody>
          </table>
          <p className="muted">
            Day hit rate:{" "}
            {formatRate(
              dayMetrics.hit,
              dayMetrics.hit + dayMetrics.late + dayMetrics.miss,
            )}{" "}
            • Precision(hit): {formatRate(dayMetrics.hit, dayMetrics.chosen_tasks)}
          </p>
          <div className="inline-actions">
            <button className="btn primary" onClick={handleContinueAfterDaySummary}>
              Continue to {daySummary.nextDayName ?? "Next Day"}
            </button>
            {runtime.allow_backtrack_debug && runtime.log_entries.length > 0 ? (
              <button className="btn subtle" onClick={handleStepBack}>
                Reopen Previous Step
              </button>
            ) : null}
          </div>
        </section>
      </main>
    );
  }

  if (phase === "complete") {
    const totalQueries = runtime.log_entries.reduce(
      (sum, entry) =>
        sum +
        Object.values(entry.state_queries).reduce(
          (stepTotal, count) => stepTotal + count,
          0,
        ),
      0,
    );
    const totalTaskActions = runtime.log_entries.reduce(
      (sum, entry) => sum + entry.task_ids.length,
      0,
    );
    return (
      <main className="screen complete-screen">
        <div className="ambient-bg" aria-hidden />
        <section className="panel complete-card">
          <p className="eyebrow">Session Complete</p>
          <h1>Run Ready for Export</h1>
          <ul className="stat-list">
            <li>
              <span>Participant</span>
              <strong>{runtime.participant_id}</strong>
            </li>
            <li>
              <span>Steps Completed</span>
              <strong>{runtime.log_entries.length}</strong>
            </li>
            <li>
              <span>State Queries</span>
              <strong>{totalQueries}</strong>
            </li>
            <li>
              <span>Task Actions Chosen</span>
              <strong>{totalTaskActions}</strong>
            </li>
            <li>
              <span>Duration</span>
              <strong>{runDuration}</strong>
            </li>
          </ul>
          <div className="inline-actions">
            <button className="btn primary" onClick={handleExportRun}>
              Download Run JSONL
            </button>
            <button className="btn" onClick={handleExportScore}>
              Download Score Markdown
            </button>
            {runtime.allow_backtrack_debug && runtime.log_entries.length > 0 ? (
              <button className="btn" onClick={handleStepBack}>
                Reopen Previous Step
              </button>
            ) : null}
            <button className="btn subtle" onClick={handleResetAfterCompletion}>
              Start Next Participant
            </button>
          </div>
          {scoreReport ? (
            <>
              <h2>Score Summary</h2>
              <table className="results-table">
                <tbody>
                  <tr>
                    <th>Hit</th>
                    <td>{scoreReport.summary.hit}</td>
                    <th>Late</th>
                    <td>{scoreReport.summary.late}</td>
                  </tr>
                  <tr>
                    <th>Miss</th>
                    <td>{scoreReport.summary.miss}</td>
                    <th>False Alarm</th>
                    <td>{scoreReport.summary.false_alarm}</td>
                  </tr>
                  <tr>
                    <th>Commission</th>
                    <td>{scoreReport.summary.commission}</td>
                    <th>Wrong Content</th>
                    <td>{scoreReport.summary.wrong_content}</td>
                  </tr>
                  <tr>
                    <th>Update Violations</th>
                    <td>{scoreReport.summary.update_violation}</td>
                    <th>Dependency Violations</th>
                    <td>{scoreReport.summary.dependency_violation}</td>
                  </tr>
                  <tr>
                    <th>Chosen Actions</th>
                    <td>{scoreReport.summary.chosen_tasks}</td>
                    <th>Overkill Steps</th>
                    <td>{scoreReport.summary.overkill_steps}</td>
                  </tr>
                  <tr>
                    <th>Check Time Calls</th>
                    <td>{scoreReport.summary.check_time_calls}</td>
                    <th>State Query Calls</th>
                    <td>{scoreReport.summary.state_query_calls}</td>
                  </tr>
                </tbody>
              </table>
              <p className="muted">
                Hit rate:{" "}
                {formatRate(
                  scoreReport.summary.hit,
                  scoreReport.summary.hit + scoreReport.summary.late + scoreReport.summary.miss,
                )}{" "}
                • Precision(hit):{" "}
                {formatRate(
                  scoreReport.summary.hit,
                  scoreReport.summary.chosen_tasks,
                )}
              </p>

              <h2>Per-Day Scores</h2>
              <table className="results-table">
                <thead>
                  <tr>
                    <th>Day</th>
                    <th>Hit</th>
                    <th>Late</th>
                    <th>Miss</th>
                    <th>False Alarm</th>
                    <th>Wrong Content</th>
                    <th>Update Violation</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(scoreReport.per_day).map(([day, details]) => (
                    <tr key={day}>
                      <td>{day}</td>
                      <td>{details.metrics.hit}</td>
                      <td>{details.metrics.late}</td>
                      <td>{details.metrics.miss}</td>
                      <td>{details.metrics.false_alarm}</td>
                      <td>{details.metrics.wrong_content}</td>
                      <td>{details.metrics.update_violation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <p className="muted">
              Score could not be computed from the recorded entries.
            </p>
          )}
        </section>
      </main>
    );
  }

  return (
    <main className="screen play-screen">
      <div className="ambient-bg" aria-hidden />
      <header className="topbar">
        <div className="topbar-left">
          <p className="eyebrow">PM-Bench Study Run</p>
          <h1>{runtime.participant_id}</h1>
          <p className="muted">
            {currentDay?.name} • Step {completedSteps + 1} of {totalSteps}
          </p>
          <div
            className="inline-progress"
            role="progressbar"
            aria-valuenow={dayProgressPct}
          >
            <div className="inline-progress-track">
              <div
                className="inline-progress-fill"
                style={{ width: `${dayProgressPct}%` }}
              />
            </div>
            <p className="inline-progress-meta">
              Day Progress: {dayCompletedSteps} / {dayTotalSteps}
            </p>
          </div>
        </div>
        <div className="topbar-right">
          <div className="meter" role="progressbar" aria-valuenow={progressPct}>
            <div className="meter-fill" style={{ width: `${progressPct}%` }} />
          </div>
          <p className="muted">Session Timer: {runDuration}</p>
        </div>
      </header>

      <section className="layout-grid">
        <article className="panel main-panel">
          <div className="section-head">
            <h2>Daily Instructions</h2>
            {visibleTime && <p className="time-chip">{visibleTime}</p>}
          </div>
          <div className="hint-block">
            {getDailyHeaderLines().map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
          {runtime.day_runtime?.start_instructions.length ? (
            <div className="hint-block">
              {runtime.day_runtime.start_instructions.map((line) => (
                <p key={line}>{line}</p>
              ))}
            </div>
          ) : null}

          <div className="step-card">
            <p className="step-meta">{currentStep?.id}</p>
            {visibleTime ? <p className="step-time">{currentStep?.time}</p> : null}
            <p className="step-text">{currentStep?.text}</p>
            <div className="options-grid">
              {(currentStep?.options ?? []).map((option) => {
                const key = option.slice(0, 1) as Choice;
                const selected = selectedChoice === key;
                return (
                  <button
                    key={option}
                    className={`option-btn ${selected ? "selected" : ""}`}
                    onClick={() => setSelectedChoice(key)}
                  >
                    {option}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="submit-row">
            <button className="btn primary" onClick={handleSubmitStep}>
              Submit Step
            </button>
            {runtime.allow_backtrack_debug && runtime.log_entries.length > 0 ? (
              <button className="btn subtle" onClick={handleStepBack}>
                Back One Step
              </button>
            ) : null}
            {errorMessage && <p className="error">{errorMessage}</p>}
          </div>
        </article>

        <aside className="panel side-panel">
          <h2>State Queries</h2>
          <div className="chip-wrap">
            {runtime.allowed_channels.map((channel) => (
              <button
                key={channel}
                className="chip-btn"
                onClick={() => handleQuery(channel)}
              >
                Query {channel}
              </button>
            ))}
          </div>
          <div className="transcript">
            {runtime.step_query_transcript.length === 0 ? (
              <p className="muted">No query yet for this step.</p>
            ) : (
              runtime.step_query_transcript.map((line, idx) => (
                <p key={`${line}-${idx}`}>{line}</p>
              ))
            )}
          </div>

          <h2>Step Action Menu</h2>
          <p className="muted">
            Optional: choose one or more action handles with your A/B/C response.
          </p>
          {runtime.show_groundtruth ? (
            <p className="muted">
              Groundtruth highlighting is on. Correct task handles are tinted below.
            </p>
          ) : null}
          <div className="chip-wrap">
            {actionMenu.map((item) => (
              <button
                key={item.handle}
                className={`chip-btn action-chip ${
                  selectedActionHandles.includes(item.handle) ? "selected" : ""
                } ${groundtruthTaskIds.has(item.id) ? "groundtruth" : ""}`}
                onClick={() => toggleActionHandle(item.handle)}
              >
                <span className="chip-handle">{item.handle}</span>
                <span className="chip-action">{item.action_text}</span>
              </button>
            ))}
          </div>

        </aside>
      </section>
    </main>
  );
}

export default App;
