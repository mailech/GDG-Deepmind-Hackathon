# Nova · D1 — Voice pipeline

## Get a voice agent speaking Telangana Telugu

### What was built

- Deepgram STT → LLM → Murf Falcon TTS over LiveKit
- locale_map.py — state/district resolves language, dialect register and voice
- prompts.py — system prompt assembled from tutor core + register pack
- registers/te_telangana.md, hi_dakhni.md — dialect packs with negative examples
- transliterate.py — Telugu→Kannada sister-script shift for the audio path

### Worth knowing

Murf has no `te-IN` voice id. Discovered later that multilingual voices carry te-IN in supportedLocales — voice and locale are separate knobs.

---

Run it:

```bash
cd backend  && uv sync && cp .env.example .env.local && uv run python src/agent.py dev
cd frontend && pnpm install && pnpm dev
```
