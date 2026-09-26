# Nova · D5 — Live tools

## Fetch real data from the internet

### What was built

- practice.py — live Codeforces API, ~11,000 real problems
- Freshness reported with every result
- Graceful failure: says so aloud, never invents a problem
- Problem card rendered on the canvas

### Worth knowing

max_output_tokens=200 truncated show_code's arguments mid-JSON. The LLM returned MALFORMED_FUNCTION_CALL and the call was silently dropped.

### Files changed this day

```
M   Telugu-Nova/README.md
M   Telugu-Nova/backend/src/agent.py
M   Telugu-Nova/backend/src/memory.py
A   Telugu-Nova/backend/src/practice.py
M   Telugu-Nova/backend/src/prompts.py
M   Telugu-Nova/backend/src/show_memory.py
M   Telugu-Nova/frontend/components/nova/canvas.tsx
M   Telugu-Nova/frontend/components/nova/nova-view.tsx
```

---

Run it:

```bash
cd backend  && uv sync && cp .env.example .env.local && uv run python src/agent.py dev
cd frontend && pnpm install && pnpm dev
```
