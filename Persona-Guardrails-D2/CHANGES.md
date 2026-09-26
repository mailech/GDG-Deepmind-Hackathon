# Nova · D2 — Persona and guardrails

## Give the agent a job and limits

### What was built

- Prompt restructured: IDENTITY / OBJECTIVES / KNOWLEDGE / LANGUAGE / GUARDRAILS / STYLE
- Scoped to Computer Science only — declines other subjects
- Guardrails: no shaming, no disability labels, no mark predictions, no live-exam help
- RED_TEAM.md — 12 attacks run against the guardrails

### Worth knowing

11 of 12 attacks held. The failure: it taught a student who said they were mid-exam. The rule existed but described no behaviour, so helpfulness won.

### Files changed this day

```
A   CS-Nova/AGENTS.md
A   CS-Nova/LICENSE
A   CS-Nova/README.md
A   CS-Nova/RED_TEAM.md
A   CS-Nova/backend/.dockerignore
A   CS-Nova/backend/.env.example
A   CS-Nova/backend/.github/workflows/ruff.yml
A   CS-Nova/backend/.github/workflows/tests.yml
A   CS-Nova/backend/.python-version
A   CS-Nova/backend/Dockerfile
A   CS-Nova/backend/LICENSE
A   CS-Nova/backend/README.md
A   CS-Nova/backend/pyproject.toml
A   CS-Nova/backend/railway.toml
A   CS-Nova/backend/src/__init__.py
A   CS-Nova/backend/src/agent.py
A   CS-Nova/backend/src/locale_map.py
A   CS-Nova/backend/src/prompts.py
A   CS-Nova/backend/src/registers/hi_dakhni.md
A   CS-Nova/backend/src/registers/te_telangana.md
A   CS-Nova/backend/src/transliterate.py
A   CS-Nova/backend/taskfile.yaml
A   CS-Nova/backend/tests/test_agent.py
A   CS-Nova/frontend/.env.example
A   CS-Nova/frontend/.eslintrc.json
A   CS-Nova/frontend/.github/workflows/build-and-test.yaml
A   CS-Nova/frontend/.npmrc
A   CS-Nova/frontend/.prettierignore
A   CS-Nova/frontend/.prettierrc
A   CS-Nova/frontend/LICENSE
A   CS-Nova/frontend/README.md
A   CS-Nova/frontend/app-config.ts
A   CS-Nova/frontend/app/api/token/route.ts
A   CS-Nova/frontend/app/favicon.ico
A   CS-Nova/frontend/app/layout.tsx
A   CS-Nova/frontend/app/opengraph-image.tsx
A   CS-Nova/frontend/app/page.tsx
A   CS-Nova/frontend/components.json
A   CS-Nova/frontend/components/agents-ui/agent-audio-visualizer-aura.tsx
A   CS-Nova/frontend/components/agents-ui/agent-audio-visualizer-bar.tsx
... and 58 more
```

---

Run it:

```bash
cd backend  && uv sync && cp .env.example .env.local && uv run python src/agent.py dev
cd frontend && pnpm install && pnpm dev
```
