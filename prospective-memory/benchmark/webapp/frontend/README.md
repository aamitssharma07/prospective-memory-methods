# PM-Bench Human Evaluation UI

Frontend-only interface for running participant sessions on the released v9
benchmark scenario.

## Run locally

```bash
npm install
npm run dev
```

Open the URL printed by Vite, normally `http://localhost:5173`.

For a production build:

```bash
npm run build
npm run preview
```

The app loads `public/scenarios/synthetic_week_v9.json`. A participant selects
one ongoing-task choice at every step and may also select anonymous PM action
handles. The interface supports state-channel queries, local autosave, summary
scoring, and export of scorer-compatible `.jsonl` and `.score.md` files.

Participant IDs should be pseudonymous. Unfinished sessions remain only in the
current browser's `localStorage`; the app has no backend.

