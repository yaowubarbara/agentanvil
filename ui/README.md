# AgentAnvil UI

Minimal Next.js trajectory replay viewer.

```bash
cd ui
npm install
npm run dev
# open http://localhost:3001
```

Reads `../traces/traces.jsonl` by default. Override with `AGENTANVIL_TRACES=/path/to/file.jsonl npm run dev`.

## Phase 0 scope

- List trajectories (sidebar)
- Step-by-step event viewer (main panel)
- Color coding per event kind
- Verify status + parsed vs gold display

## Phase 1 additions (planned)

- Diff view (two trajectories side-by-side on the same task)
- Filter / search by scaffold, correctness, task_id
- Pull from Langfuse API (not only local file)
- Image rendering for vision tasks
