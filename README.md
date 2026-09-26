# Nova — 10 Days of Voice Agents

A voice-first Computer Science tutor for Telugu-speaking students.

Each folder is the **complete, runnable project as it stood at the end of that day**, so you can open any day and see exactly what existed then.

| Day | What was built |
|---|---|
| [Voice-Pipeline](./Voice-Pipeline/) | Get a voice agent speaking Telangana Telugu |
| [Persona-Guardrails](./Persona-Guardrails/) | Give the agent a job and limits |
| [Frontend](./Frontend/) | A frontend built for this product, not a demo shell |
| [Memory](./Memory/) | Remember students between calls |
| [Live-Tools](./Live-Tools/) | Fetch real data from the internet |
| [Outbound-Calls](./Outbound-Calls/) | The agent calls the student |
| [Human-Escalation](./Human-Escalation/) | Know when to fetch a human |
| [Analytics](./Analytics/) | Measure whether calls actually worked |
| [Agent-Handoff](./Agent-Handoff/) | Three specialists, and knowing when to step aside |

## Running any day

Every folder is self-contained. Copy `.env.example` to `.env.local`, fill in your keys, then:

```bash
cd backend  && uv sync && uv run python src/agent.py dev
cd frontend && pnpm install && pnpm dev
```

No secrets are committed. `.env.local` is gitignored everywhere.
