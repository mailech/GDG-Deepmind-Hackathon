# Medium repair sheet

Medium's DEV.to importer flattens fenced code, drops tables, and loses the ASCII
diagram. Fix the imported draft with the pieces below.

## How to paste a code block into Medium

Paste the block -> select the pasted text -> **Ctrl+Alt+6**. That converts it to a
real code block with newlines intact. Doing it in that order matters; converting
first and then pasting re-flattens it.

---

## Fix 1 - the two tables

Medium has no tables, and it does NOT parse markdown on paste — asterisks and
backticks stay on screen as literal characters. So paste the plain text below,
with no formatting marks, and style it afterwards with Medium's own toolbar.

Paste exactly this under **How the system works** (four separate lines):

    STT — Deepgram nova-3. Supports te-IN natively; most don't.
    LLM — a hosted frontier model. Indic-language quality varies enormously, so test candidates on your actual dialect before committing.
    TTS — Murf Falcon. 90ms time-to-first-audio, and a Telugu-capable voice.
    Transport — LiveKit. Handles WebRTC, and SIP for phone calls.

Then, in Medium:

- To make it a bulleted list, put the cursor at the start of the first line and
  type `*` followed by a space. Medium converts the line to a bullet, and Enter
  carries the bullet to the next one.
- To bold `STT`, `LLM`, `TTS`, `Transport` — select the word, press `Ctrl+B`.
- To make `nova-3` and `te-IN` inline code — select, then click the `<>` in the
  little toolbar that pops up over the selection.

The bold and the inline code are cosmetic. If you are short on time, paste the
four lines, bullet them, and stop there — it reads fine plain.

### The second table

Further down there was a second table (day-by-day features). Same treatment, or
just delete it — the post reads fine without it.

---

## Fix 2 - the pipeline diagram

The box-drawing diagram will not survive Medium. Either screenshot it from your
DEV.to post and insert it as an image (best), or paste this plain paragraph in
its place — no `>`, no formatting marks:

    You speak, Deepgram turns it into text, the LLM answers, and Murf Falcon speaks it back. Tool calls branch off to Postgres, the Codeforces API and SIP. Results are pushed to the browser over a data channel as code, flowcharts and transcript. LiveKit transports all of it.

---

## Fix 3 - the code blocks, in order of appearance

Block 1 is the diagram (see Fix 2). Blocks 2-12 follow.

Copy only what is **between** the ``` fence lines — never the fences themselves,
or they will appear in the post as literal backticks.

### Block 2  (python)

```python
def shift(text, delta):
    return "".join(
        chr(ord(c) + delta) if 0x0C00 <= ord(c) <= 0x0C7F else c
        for c in text
    )
```

### Block 3  (python)

```python
# WRONG — the voice's own locale is just its default
voices = [v for v in all_voices if v["locale"] == "te-IN"]   # → []

# RIGHT — voice and locale are separate knobs
murf.TTS(voice="en-IN-samar", locale="te-IN")                # → native Telugu
```

### Block 4  (python)

```python
max_output_tokens=200,   # keep spoken replies short
```

### Block 5  (text)

```
max_output_tokens=200   →  MALFORMED_FUNCTION_CALL, no call
max_output_tokens=800   →  works
```

### Block 6  (text)

```
RuntimeError: Executor shutdown has been called
```

### Block 7  (text)

```
stt_error ... RuntimeError('cannot schedule new futures after shutdown')
recoverable=False
```

### Block 8  (python)

```python
def _db_loop():
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    return loop

async def _call(coro):
    return await asyncio.wrap_future(
        asyncio.run_coroutine_threadsafe(coro, _db_loop())
    )
```

### Block 9  (python)

```python
self.session.update_agent(specialist)
```

### Block 10  (python)

```python
# the fix
session = context.session          # whoever is actually running this tool
session.update_agent(specialist)
```

### Block 11  (bash)

```bash
git clone https://github.com/murf-ai/murf-livekit-starter
cd murf-livekit-starter

# backend
cd backend
uv sync
cp .env.example .env.local     # keys go HERE — it is gitignored
uv run python src/agent.py dev

# frontend
cd ../frontend
pnpm install && pnpm dev
```

### Block 12  (python)

```python
session = AgentSession(
    stt=deepgram.STT(model="nova-3", language="te-IN"),
    llm=<your LLM plugin>,          # LiveKit ships several
    tts=murf.TTS(voice="en-IN-samar", locale="te-IN", style="Conversational"),
    vad=ctx.proc.userdata["vad"],
)
```

