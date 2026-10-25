import type { SessionRuntime } from "./types";

const STORAGE_KEY = "pm_bench_frontend_autosave_v1";

export interface SavedSession {
  saved_at: string;
  runtime: SessionRuntime;
}

export function loadSavedSession(): SavedSession | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as SavedSession;
    if (!parsed || !parsed.runtime) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function saveSession(runtime: SessionRuntime): void {
  const payload: SavedSession = {
    saved_at: new Date().toISOString(),
    runtime,
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
}

export function clearSavedSession(): void {
  localStorage.removeItem(STORAGE_KEY);
}

