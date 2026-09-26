# Nova — 10 Days of Voice Agents

A voice-first Computer Science tutor for Telugu-speaking students.

Each folder is the **complete, runnable project as it stood at the end of that day**, so you can open any day and see exactly what existed then.

| Day | What was built |
|---|---|
| [Voice-Pipeline-D1](./Voice-Pipeline-D1/) | Get a voice agent speaking Telangana Telugu |
| [Persona-Guardrails-D2](./Persona-Guardrails-D2/) | Give the agent a job and limits |
| [Frontend-D3](./Frontend-D3/) | A frontend built for this product, not a demo shell |
| [Memory-D4](./Memory-D4/) | Remember students between calls |
| [Live-Tools-D5](./Live-Tools-D5/) | Fetch real data from the internet |
| [Outbound-Calls-D6](./Outbound-Calls-D6/) | The agent calls the student |
| [Human-Escalation-D7](./Human-Escalation-D7/) | Know when to fetch a human |
| [Analytics-D8](./Analytics-D8/) | Measure whether calls actually worked |
| [Agent-Handoff-D9](./Agent-Handoff-D9/) | Three specialists, and knowing when to step aside |

## Running any day

Every folder is self-contained. Copy `.env.example` to `.env.local`, fill in your keys, then:

```bash
cd backend  && uv sync && uv run python src/agent.py dev
cd frontend && pnpm install && pnpm dev
```

No secrets are committed. `.env.local` is gitignored everywhere.
