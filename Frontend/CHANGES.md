# Nova · D3 — Frontend

## A frontend built for this product, not a demo shell

### What was built

- Five explicit call states: ready, connecting, live, ended, mic-error
- Live transcript from track transcriptions
- Microphone permission errors with numbered fix steps
- canvas.tsx — code rendered with Shiki, flowcharts drawn box by box
- Warm low-contrast palette

### Worth knowing

useSessionMessages carries typed chat only — speech transcripts live on the audio tracks, which is why the transcript stayed empty at first.

### Files changed this day

```
A   Telugu-Nova/AGENTS.md
A   Telugu-Nova/LICENSE
A   Telugu-Nova/README.md
A   Telugu-Nova/RED_TEAM.md
A   Telugu-Nova/backend/.dockerignore
A   Telugu-Nova/backend/.env.example
A   Telugu-Nova/backend/.github/workflows/ruff.yml
A   Telugu-Nova/backend/.github/workflows/tests.yml
A   Telugu-Nova/backend/.python-version
A   Telugu-Nova/backend/Dockerfile
A   Telugu-Nova/backend/LICENSE
A   Telugu-Nova/backend/README.md
A   Telugu-Nova/backend/pyproject.toml
A   Telugu-Nova/backend/railway.toml
A   Telugu-Nova/backend/src/__init__.py
A   Telugu-Nova/backend/src/agent.py
A   Telugu-Nova/backend/src/locale_map.py
A   Telugu-Nova/backend/src/prompts.py
A   Telugu-Nova/backend/src/registers/hi_dakhni.md
A   Telugu-Nova/backend/src/registers/te_telangana.md
A   Telugu-Nova/backend/src/transliterate.py
A   Telugu-Nova/backend/taskfile.yaml
A   Telugu-Nova/backend/tests/test_agent.py
A   Telugu-Nova/frontend/.env.example
A   Telugu-Nova/frontend/.eslintrc.json
A   Telugu-Nova/frontend/.github/workflows/build-and-test.yaml
A   Telugu-Nova/frontend/.npmrc
A   Telugu-Nova/frontend/.prettierignore
A   Telugu-Nova/frontend/.prettierrc
A   Telugu-Nova/frontend/LICENSE
A   Telugu-Nova/frontend/README.md
A   Telugu-Nova/frontend/app-config.ts
A   Telugu-Nova/frontend/app/api/token/route.ts
A   Telugu-Nova/frontend/app/favicon.ico
A   Telugu-Nova/frontend/app/layout.tsx
A   Telugu-Nova/frontend/app/opengraph-image.tsx
A   Telugu-Nova/frontend/app/page.tsx
A   Telugu-Nova/frontend/components.json
A   Telugu-Nova/frontend/components/agents-ui/agent-audio-visualizer-aura.tsx
A   Telugu-Nova/frontend/components/agents-ui/agent-audio-visualizer-bar.tsx
... and 60 more
```

---

Run it:

```bash
cd backend  && uv sync && cp .env.example .env.local && uv run python src/agent.py dev
cd frontend && pnpm install && pnpm dev
```
