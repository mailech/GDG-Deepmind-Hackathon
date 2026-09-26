# Nova · D9 — Agent handoff

## Three specialists, and knowing when to step aside

### What was built

- specialists.py — Algo (DSA), Keerthi (debugging), Vikram (interviews, in Hindi)
- Each has its own Murf voice, speed and pitch
- Any agent can route to any other; conversation carries via chat_ctx
- UI reskins per agent — paper, panel, bubbles, accent
- Handoff reason shown inline in the transcript

### Worth knowing

Transfer tools called self.session.update_agent — but 'self' was Nova, who is not active while a specialist runs, so her session was stale.

---

Run it:

```bash
cd backend  && uv sync && cp .env.example .env.local && uv run python src/agent.py dev
cd frontend && pnpm install && pnpm dev
```
