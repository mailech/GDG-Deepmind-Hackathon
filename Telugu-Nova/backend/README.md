# Agent Acharya — backend

The live teacher: a LiveKit agent on Gemini 3.8 Live that teaches on a shared
whiteboard. See the [project README](../../README.md) for the full picture.

```bash
cp .env.example .env.local   # LIVEKIT_*, GOOGLE_API_KEY
uv sync
uv run python src/agent.py download-files
uv run python src/agent.py start
```

| File | |
|---|---|
| `src/agent.py` | Registers the worker |
| `src/board_session.py` | The live class: teachers, board tools, student marks, visual director hook |
| `src/board.py` | Board state and the lesson planner |
| `src/visuals.py` | Visual director — a diagram for every question |
| `src/media.py` | Images, image editing, clips, real photos |
| `src/research.py` | Live research with sources |
| `src/board_prompts.py` | The teacher's instructions |
| `src/memory.py`, `src/analytics.py` | Optional Postgres memory and class analytics |
