# Nova · D4 — Memory

## Remember students between calls

### What was built

- memory.py — Postgres on Neon, one row per student
- recall_student / remember_student / forget_student
- Consent gate — nothing saved unless the student agrees
- show_memory.py — prove persistence from the terminal

### Worth knowing

The database runs on its own event loop and thread. Replacing LiveKit's default executor fixed asyncpg but killed Deepgram STT mid-call.

### Files changed this day

```
M   Telugu-Nova/backend/.env.example
M   Telugu-Nova/backend/pyproject.toml
M   Telugu-Nova/backend/src/agent.py
A   Telugu-Nova/backend/src/memory.py
M   Telugu-Nova/backend/src/prompts.py
A   Telugu-Nova/backend/src/show_memory.py
M   Telugu-Nova/frontend/components/app/app.tsx
D   Telugu-Nova/frontend/components/app/view-controller.tsx
M   Telugu-Nova/frontend/components/nova/canvas.tsx
M   Telugu-Nova/frontend/components/nova/nova-view.tsx
```

---

Run it:

```bash
cd backend  && uv sync && cp .env.example .env.local && uv run python src/agent.py dev
cd frontend && pnpm install && pnpm dev
```
