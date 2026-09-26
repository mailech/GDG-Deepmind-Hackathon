# Nova — నోవా

A voice-first Computer Science companion for Telugu-speaking students.

Nova speaks **Telangana Telugu**, teaches **only Computer Science**, writes real
programs on screen while it talks, draws flowcharts as it explains, remembers
students between calls, and hands out **real practice problems** fetched live
from Codeforces.

Built for **10 Days of Voice Agents** · Track: **Learning & Literacy** ·
`#VoiceForBharat`

---

## Data sources — live or local?

| Source | Live or local | Notes |
|---|---|---|
| **Codeforces problemset** | **LIVE** | `https://codeforces.com/api/problemset.problems` — public, no API key. ~11,000 real problems with genuine difficulty ratings and tags. |
| **Student memory** | **LIVE** | Postgres (Neon). Written and read at call time. |
| Dialect register packs | Local | Hand-written prompt fragments in `backend/src/registers/`. |
| Topic → tag and level → rating maps | Local | Hand-built tables in `backend/src/practice.py`. |

**Nothing about the practice problems is invented or hard-coded.** Every problem
Nova gives you is fetched from Codeforces at run time. The problemset response is
~5 MB, so it is cached in memory for six hours, and **the fetch timestamp travels
with every result** — Nova says "just fetched now" or "fetched two hours ago"
rather than implying everything is current.

### When Codeforces is down

Tested, not assumed:

- **Cold failure** (unreachable, nothing cached) → the tool raises, and Nova says
  so out loud: *"Codeforces కనెక్ట్ కావట్లేదు రా"*, then offers to invent a
  practice question itself or carry on explaining. It never goes silent and
  never fabricates a problem.
- **Warm failure** (unreachable, cache present) → serves the cached problemset
  and says how old it is. Stale data beats no data, as long as you say it's stale.
- Requests time out after **12 seconds**, chosen for slow connections.

---

## What it does

| Day | Feature |
|---|---|
| 1 | Telugu voice pipeline — Deepgram STT → LLM → Murf Falcon TTS over LiveKit |
| 2 | Identity, objectives, guardrails, escalation script. See [RED_TEAM.md](./RED_TEAM.md) |
| 3 | Purpose-built frontend: five call states, live transcript, mic-permission recovery |
| 4 | Persistent memory in Postgres, consent-gated, with a forget-me tool |
| 5 | Live practice-problem lookup from Codeforces |
| 6 | Outbound calls over Twilio SIP, with per-outcome retry rules |
| 7 | Escalation to a human, consent-gated, with a teacher's desk |
| 8 | Call analytics — success measured from tool side-effects |

## The stack

- **TTS** — Murf Falcon, `en-IN-samar` at `locale="te-IN"` (native Telugu)
- **STT** — Deepgram `nova-3`, `te-IN`
- **LLM** — a hosted frontier model, pinned to a South Asia region and with
  extended thinking disabled, both for latency. Swappable: LiveKit ships plugins
  for several providers, and only the `llm=` line in `agent.py` changes.
- **Transport** — LiveKit
- **Memory** — Postgres on Neon via asyncpg
- **Frontend** — Next.js, Tailwind, Motion, Shiki

## Agent tools

| Tool | What it does |
|---|---|
| `find_practice_problem` | Fetches a real Codeforces problem by topic and level |
| `show_code` | Renders a syntax-highlighted program on screen |
| `show_flowchart` | Draws an animated flowchart, one box at a time |
| `recall_student` | Looks a student up by name |
| `remember_student` | Saves level, topics covered, weak spots — **only after consent** |
| `forget_student` | Deletes everything stored about a student |
| `create_escalation` | Files a request for a human — **only after consent** |
| `check_escalation` | Looks up a request the student has a reference for |

## Running it

```bash
# backend
cd backend
uv sync
cp .env.example .env.local        # fill in your keys

# then authenticate whichever LLM provider `agent.py` is configured for —
# some use a key in .env.local, some use a CLI login. See .env.example.

uv run python src/agent.py dev

# frontend
cd frontend
pnpm install
pnpm dev
```

Then open http://localhost:3002.

```bash
# see what Nova remembers
uv run python src/show_memory.py

# call a student (needs SIP_OUTBOUND_TRUNK_ID)
uv run python src/outbound.py +91XXXXXXXXXX --student "Name"
```

## Pages

| Route | What it is |
|---|---|
| `/` | The student's view — five call states, live transcript, code and flowcharts |
| `/desk` | Teacher's desk — students Nova handed over, most urgent first |
| `/stats` | Call analytics — total, successful, failed, and why |
| `/monitor` | Live view of an in-progress phone call |

## What "a successful call" means

Defined in code, not by asking the model. A call succeeded if the student left
with something concrete — a concept drawn on screen, a real practice problem, or
a human found for them. Those counters only move when a tool actually fired, so
the agent cannot talk its way into a success. Failures are split by cause
(never spoke / never reached a concept / a tool broke) because those are three
different problems.

The analytics store counters and timings only: no transcripts, no phone
numbers, no student content.

## Known limitations

- **Murf has no `te-IN` voice id.** Telugu works through multilingual voices
  (`en-IN-samar` + `locale="te-IN"`). Voice and locale are separate knobs; reading
  only a voice's primary `locale` field will wrongly suggest Telugu is unsupported.
- **No live language switching.** Deepgram rejects language detection in streaming
  mode, and the other major provider tested returns whichever language is listed
  first regardless of what was spoken — both verified by testing. Language is
  fixed per call by the student's profile.
- **Students are identified by spoken name**, normalised to a slug. Two students
  with the same name would share a record. Real deployment needs a phone number
  or account.
- Codeforces problems are competitive-programming style, which is a steeper ramp
  than a typical college syllabus. Fine for DSA practice, less so for a first-year
  student meeting loops for the first time.
