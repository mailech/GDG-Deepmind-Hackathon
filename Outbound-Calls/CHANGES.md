# Nova · D6 — Outbound calls

## The agent calls the student

### What was built

- outbound.py — Twilio Elastic SIP Trunking via LiveKit
- Opening states who, why, and how to stop it
- Five outcomes, each with its own retry rule
- /monitor — watch a live phone call from the browser

### Worth knowing

Rejected calls never retry. Calling back someone who declined is harassment, not persistence.

### Files changed this day

```
M   Telugu-Nova/backend/.env.example
M   Telugu-Nova/backend/src/agent.py
A   Telugu-Nova/backend/src/outbound.py
M   Telugu-Nova/backend/src/prompts.py
A   Telugu-Nova/frontend/app/api/monitor/route.ts
A   Telugu-Nova/frontend/app/monitor/page.tsx
```

---

Run it:

```bash
cd backend  && uv sync && cp .env.example .env.local && uv run python src/agent.py dev
cd frontend && pnpm install && pnpm dev
```
