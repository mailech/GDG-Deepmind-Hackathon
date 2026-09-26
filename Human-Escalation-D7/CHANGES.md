# Nova · D7 — Human escalation

## Know when to fetch a human

### What was built

- escalations.py — two reasons only: wellbeing, or a teacher is needed
- Consent required before anything is sent
- PII stripped by regex, not by asking the model
- Duplicate suppression within 24 hours
- /desk — the teacher's queue, most urgent first

### Worth knowing

The LLM leaked its own tool-call scaffolding into speech — <speak> tags and print(default_api...) were read aloud. Now stripped at the TTS boundary.

### Files changed this day

```
M   Telugu-Nova/backend/src/agent.py
A   Telugu-Nova/backend/src/escalations.py
M   Telugu-Nova/backend/src/prompts.py
M   Telugu-Nova/backend/src/transliterate.py
A   Telugu-Nova/frontend/app/api/desk/route.ts
A   Telugu-Nova/frontend/app/desk/page.tsx
M   Telugu-Nova/frontend/package.json
```

---

Run it:

```bash
cd backend  && uv sync && cp .env.example .env.local && uv run python src/agent.py dev
cd frontend && pnpm install && pnpm dev
```
