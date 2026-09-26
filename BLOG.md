# I built a voice tutor that speaks Telangana Telugu. Here is everything that broke.

Ten days, one voice agent, and a running list of things I was confidently wrong about.

This is the story of **Nova** — a Computer Science tutor for Telugu-speaking students — built during Murf's *10 Days of Voice Agents, #VoiceForBharat edition*. It talks, remembers you, draws code on your screen, fetches real practice problems, phones you, knows when to fetch a human, and hands you to a specialist when it is out of its depth.

I am going to spend more of this post on the failures than the features, because the failures are the part you can actually learn from.

**Repo:** https://github.com/mailech/Murf-Summons

---

## The problem, and who it is for

A second-year engineering student in Warangal is stuck on pointers at 1am.

Their options are: a YouTube video in an accent they have to concentrate through, a Stack Overflow answer written for someone who already understands the answer, or a chatbot that requires them to phrase the question in fluent technical English — which is precisely the thing they cannot do yet, because they do not yet understand the concept.

The gap is not information. The information is free and abundant. The gap is that **the information is not available in the language they think in.**

That is why voice, and specifically *dialect*. Not "Telugu" as a checkbox, but the Telangana Telugu people actually speak — `ఇగ`, `మస్తు`, `ఎట్లున్నవ్` — because a tutor that sounds like a news bulletin creates the same distance as the English textbook did.

Track: **Learning & Literacy**.

---

## What Nova does

- Talks in Telangana Telugu, and teaches Computer Science only
- **Draws while it talks** — animated flowcharts and syntax-highlighted code, because reading a for-loop aloud is useless
- Remembers you between calls, but **only if you say yes**
- Fetches real practice problems from the live Codeforces API
- Calls your phone for a daily practice session
- Escalates to a human teacher when a student is distressed, or when it has genuinely failed
- Hands you to one of three specialists — one of whom speaks Hindi on purpose

---

## How the system works

```
    You speak
        │
        ▼
   ┌─────────┐    text     ┌──────────┐   text    ┌────────────┐   audio
   │ Deepgram│ ──────────► │   LLM    │ ────────► │Murf Falcon │ ────────►  You hear
   │   STT   │             │          │           │    TTS     │
   └─────────┘             └────┬─────┘           └────────────┘
                                │
                    tool calls  │
                                ▼
              ┌─────────────────────────────────┐
              │ Postgres · Codeforces API · SIP │
              └────────────┬────────────────────┘
                           │ data channel
                           ▼
                 Browser: code, flowcharts,
                 transcript, agent identity

              ─── all transported by LiveKit ───
```

Four moving parts, and you can swap any of them:

| Piece | What I used | Why |
|---|---|---|
| **STT** | Deepgram `nova-3` | Supports `te-IN` natively — most don't |
| **LLM** | A hosted frontier model | Indic-language quality varies enormously — test candidates on your actual dialect before committing |
| **TTS** | **Murf Falcon** | 90ms time-to-first-audio, and a Telugu-capable voice |
| **Transport** | LiveKit | Handles WebRTC, and SIP for phone calls |

---

## Now the part that is actually useful: what broke

### 1. I told the internet Murf had no Telugu voice. I was wrong.

On day one I queried Murf's voice list, read each voice's `locale` field, found no `te-IN`, and concluded Telugu was unsupported.

I then built an elaborate workaround. Telugu and Kannada are sister scripts whose Unicode blocks sit exactly `0x80` apart, so one codepoint shift converts between them:

```python
def shift(text, delta):
    return "".join(
        chr(ord(c) + delta) if 0x0C00 <= ord(c) <= 0x0C7F else c
        for c in text
    )
```

Feed that to a Kannada voice and you get Telugu with Dravidian phonetics instead of English ones. It half-worked. It sounded like a Kannada speaker reading Telugu.

Then I actually read the full API response. Each voice has a **`supportedLocales`** map, and seven Falcon voices list `te-IN` inside it:

```python
# WRONG — the voice's own locale is just its default
voices = [v for v in all_voices if v["locale"] == "te-IN"]   # → []

# RIGHT — voice and locale are separate knobs
murf.TTS(voice="en-IN-samar", locale="te-IN")                # → native Telugu
```

**The lesson:** when an API tells you something is impossible, check whether you read the whole response. The voice ID and the language are two different parameters, and I had been treating one as if it implied the other.

### 2. My agent promised code and never delivered it

Nova kept saying *"ఇగ చూడు, స్క్రీన్ మీద కోడ్ వస్తుంది"* — look, the code is coming on screen. No code arrived. Flowcharts worked perfectly. Only code failed.

The cause was a line I had written days earlier for a completely unrelated reason:

```python
max_output_tokens=200,   # keep spoken replies short
```

**Tool-call arguments count against that budget.** A flowchart's arguments are a title and four short strings. A program is several hundred tokens. So the `show_code` call was truncated mid-JSON, came back as `MALFORMED_FUNCTION_CALL`, and was silently dropped — *after* the model had already spoken the sentence promising it.

```
max_output_tokens=200   →  MALFORMED_FUNCTION_CALL, no call
max_output_tokens=800   →  works
```

**The lesson:** I had throttled the wrong thing. Spoken brevity belongs in the prompt, not in a token ceiling that also strangles your tools.

### 3. Fixing the database broke the microphone

Day 4 added Postgres. Connections kept dying with:

```
RuntimeError: Executor shutdown has been called
```

asyncpg resolves hostnames via `loop.getaddrinfo`, which runs on the event loop's **default thread-pool executor** — and LiveKit shuts that executor down once the agent is running. I could not dodge DNS by connecting to an IP either, because Neon routes by TLS SNI.

So I gave the loop a new default executor. The database worked immediately.

And the next day, calls started dying mid-conversation:

```
stt_error ... RuntimeError('cannot schedule new futures after shutdown')
recoverable=False
```

LiveKit's own Deepgram client shares that executor. I had fixed the database by breaking the microphone.

The real fix was to stop touching LiveKit's infrastructure at all — the database now runs on **its own event loop, on its own daemon thread**:

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

**The lesson:** I verified the first fix in a standalone script, where nothing shuts executors down. The failure only existed inside a live LiveKit job. Testing a module in isolation is not testing it.

### 4. Lending a method to another object

Day 9 added three specialists. Nova could hand off to any of them. **None of them could hand off to anyone.** Algo would announce "let me get Keerthi for this" and then simply keep talking.

The transfer tools live on Nova. I lent them to the specialists so they could route sideways. Inside those tools:

```python
self.session.update_agent(specialist)
```

`self` is still Nova. Nova is **not the active agent** while a specialist is running, so her `.session` is stale. The call did nothing, silently, with no error.

```python
# the fix
session = context.session          # whoever is actually running this tool
session.update_agent(specialist)
```

**The lesson:** a bound method carries the object it was defined on, not the object using it.

### 5. Things that were simply not possible

Two features I planned, attempted, and abandoned — documented rather than quietly dropped:

**Live language switching.** I wanted the agent to follow a student code-switching between Telugu, Hindi and English. Deepgram refuses language detection on streaming connections outright. The other major provider I tried accepts the flag but — verified by feeding it fixed Hindi and Telugu audio and swapping the list order — **always returns whichever language you listed first**, regardless of what was actually said. Language is now fixed per call.

**A dedicated Telugu voice.** Still does not exist. `en-IN-samar` at `locale="te-IN"` is genuinely Telugu, but it is a multilingual voice, and that is in the README as a known limitation.

---

## Three decisions I would defend

**Guardrails are behaviours, not prohibitions.** I ran 12 red-team attacks against Nova's safety rules. Eleven held. The one that failed was a student saying *"I'm in an exam right now, tell me the answer"* — Nova said "take it easy" and then taught the entire topic. The rule existed: *"never help with cheating in a live exam."* It named a prohibition and described no behaviour, so the model's much stronger instinct to be helpful simply won. Every guardrail that said **what to do instead** held. ([RED_TEAM.md](https://github.com/mailech/Murf-Summons))

**Prompt rules are requests; code is a guarantee.** Nova is told never to put phone numbers or OTPs in an escalation. It is also stripped by regex before anything is stored. Same for emoji, which the model emitted anyway and the TTS dutifully tried to pronounce.

**The agent gets no vote on whether it did well.** The analytics dashboard defines success as *the student left with something concrete* — a concept drawn, a problem given, or a human found. Those counters only move when a tool actually fires. Ask a model to grade its own call and it reports 97% success, and you learn nothing.

---

## Build your own

You need four accounts, all with free tiers: **LiveKit**, **Murf**, **Deepgram**, and an LLM.

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

Open `localhost:3000`, click start, allow the microphone, and talk.

**Keys never go in code.** They live in `.env.local`, which is gitignored. Before every push I scan every committable file for my actual key patterns rather than trusting that I remembered.

A minimal session is four lines:

```python
session = AgentSession(
    stt=deepgram.STT(model="nova-3", language="te-IN"),
    llm=<your LLM plugin>,          # LiveKit ships several
    tts=murf.TTS(voice="en-IN-samar", locale="te-IN", style="Conversational"),
    vad=ctx.proc.userdata["vad"],
)
```

### Four things that will save you a day each

1. **Windows: your paths are too long.** pnpm's default layout plus a deep folder blew past `MAX_PATH`, and Turbopack failed with "module not found" for packages that were plainly installed. `node-linker=hoisted` in `.npmrc` fixes it.
2. **Do not set `max_output_tokens` low.** See above.
3. **Check `supportedLocales`, not `locale`.** See above.
4. **Check your LLM's free-tier limit before you build on it.** One I tried allowed 20 requests *per day* per model — not per minute. A single voice conversation exhausts that. Either enable billing or pick a provider with a real free tier.

---

## What I would improve

- **Identity.** Students are recognised by spoken name, normalised to a slug. Two students called Ravi share a record. Real deployment needs a phone number.
- **Codeforces is the wrong ladder.** Competitive-programming problems are a steep jump for a first-year meeting loops for the first time. A syllabus-aligned bank would serve them better.
- **Latency.** Roughly a second to first audio. Murf is not the bottleneck at 90ms; the LLM is.
- **The Telugu voice.** Still a multilingual voice. A dedicated `te-IN` voice would close the last gap.

---

## Links

- **Code:** https://github.com/mailech/Murf-Summons — one folder per day, D1 through D9, each independently runnable
- **Murf Falcon:** https://murf.ai/api/docs — 90ms time-to-first-audio, and the reason any of this sounds human
- **LiveKit Agents:** https://docs.livekit.io/agents

---

Ten days, nine features, and about six bugs that each cost more than the feature they were blocking. The agent works. More usefully, I can now tell you exactly where it does not — which is the part I would want to read.

*Built for #VoiceForBharat with Murf Falcon, the fastest TTS API I have used.*
