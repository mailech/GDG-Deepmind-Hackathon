# Nova · D8 — Analytics

## Measure whether calls actually worked

### What was built

- analytics.py — success decided in code from tool side-effects
- Failure split by cause, not one bucket
- /stats — total, successful, failed, plus rate and history
- Counters and timings only — no transcripts, no phone numbers

### Worth knowing

The agent gets no vote on whether it did well. Ask a model to grade itself and it reports 97% success.

### Files changed this day

```
M   Telugu-Nova/README.md
M   Telugu-Nova/backend/src/agent.py
A   Telugu-Nova/backend/src/analytics.py
A   Telugu-Nova/frontend/app/api/stats/route.ts
A   Telugu-Nova/frontend/app/stats/page.tsx
```

---

Run it:

```bash
cd backend  && uv sync && cp .env.example .env.local && uv run python src/agent.py dev
cd frontend && pnpm install && pnpm dev
```
