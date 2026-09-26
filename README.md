# Agent Acharya (AA) — a live AI teacher on a shared whiteboard

**Live demo:** https://gdg-deepmind-hackathon.vercel.app

Agent Acharya is a voice-first teacher. You talk to it, and it teaches you on a
live whiteboard — drawing diagrams, writing, generating pictures and pointing
at them while it speaks. You can interrupt it at any moment: by voice, or by
circling anything on the board, and it stops and explains exactly that part.

It teaches any subject — computer science, finance, medicine, physics,
history, politics — in English, Telugu, Hindi, Tamil and Kannada, and switches
language the moment you do.

Built for **Problem Statement 2: Next-Gen Voice & Real-Time Audio**.

---

## What it does

| | |
|---|---|
| **Talks, not types** | A native-audio conversation on Gemini 3.8 Live. Interrupt mid-sentence; it stops, listens, answers, and picks up where it left off. |
| **Reads your voice** | Hears hesitation and confusion in *how* you speak, and slows down or re-explains without being asked. |
| **Teaches on a board** | Every question gets a diagram drawn for its subject — stacked layers for the OSI model, a cycle for the water cycle, a timeline for history, a side-by-side for "X vs Y". Lessons unfold step by step as it talks. |
| **Circle to ask** | Circle or underline anything — a cell, a line of code, part of a picture. The mark (and a snapshot of it) goes straight to the teacher, which interrupts itself to explain that exact thing. |
| **Pictures without asking** | Generates an infographic when a picture helps, draws on it when you ask ("circle the left ventricle"), and shows real photos for real people and places. |
| **Researches live** | For anything current — interest rates, medical guidelines, recent events — it searches the web first, and shows every finding with its source in a research panel. |
| **Four teachers, one board** | Hands off to specialists (DSA, debugging, interview practice) who keep the same board. Old boards stay as tabs. |
| **Speaks your language** | Pick a language in the app; the interface and the teacher switch together. Speak another language mid-class and it follows you. |

---

## How it works

```
 student mic ──► Gemini 3.8 Live ──────────────► teacher's voice
                      │ tool calls
                      ▼
              ┌───────────────┐     data channel      ┌──────────────────┐
              │   the Board   │ ────────────────────► │ browser whiteboard│
              │ (board.py)    │ ◄──────────────────── │  (Next.js + SVG)  │
              └───────────────┘   student marks +     └──────────────────┘
                 ▲    ▲    ▲      snapshot of the mark
                 │    │    │
   Lesson planner │    │    │ Visual Director — runs on every question:
 (Gemini 3.8 Flash)    │      picks a diagram, an image, or a clip
                       │
        Research (Gemini 3.8 Flash + Google Search) · Images (Nano Banana 2 Lite)
```

- **Gemini 3.8 Live** holds the conversation: hears the student directly (so
  barge-in and tone are native), speaks, and drives the board through tools.
- **Gemini 3.8 Flash** does the thinking the voice model should not do while
  talking: plans each lesson as a board script, directs the visuals for every
  question, and researches current facts with Google Search grounding.
- **Nano Banana 2 Lite** generates infographics and edits them to mark parts.
- **LiveKit** carries audio, the board's drawing ops, and the student's marks.

### Models used

| Model | Role |
|---|---|
| `gemini-3.8-live` | The teacher's voice, listening, interruptions |
| `gemini-3.8-flash` | Lesson planner, Visual Director, live research |
| `gemini-3.1-flash-lite-image` (Nano Banana 2 Lite) | Generated images and marking on them |
| `veo-3.1-fast-generate-preview` | Short animated clips (Gemini Omni needs google-genai 2.x; the LiveKit plugin is on 1.x) |

When `gemini-3.8-flash` returns "high demand", planning falls back to earlier
Flash versions so a class never goes silent. Real photos of real people and
places come from Wikipedia.

---

## Repository layout

| Folder | What it is |
|---|---|
| [`Telugu-Nova/backend`](./Telugu-Nova/backend/) | The live teacher — a LiveKit agent on Gemini 3.8 Live |
| [`Telugu-Nova/frontend`](./Telugu-Nova/frontend/) | The whiteboard web app (Next.js) |

Key backend files in `Telugu-Nova/backend/src/`:

| File | |
|---|---|
| `board_session.py` | The live class: Gemini Live session, the teachers and their board tools, student marks, the Visual Director hook |
| `board.py` | Board state and the lesson planner |
| `visuals.py` | The Visual Director — a diagram for every question |
| `media.py` | Nano Banana images, image editing, clips, Wikipedia photos |
| `research.py` | Live research with sources |
| `board_prompts.py` | The teacher's instructions |

---

## Running it

You need a [LiveKit Cloud](https://cloud.livekit.io) project and a Gemini API
key from [Google AI Studio](https://aistudio.google.com/apikey) on a billed
project (the free tier runs out mid-class).

```bash
# backend
cd Telugu-Nova/backend
cp .env.example .env.local      # set LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, GOOGLE_API_KEY
uv sync
uv run python src/agent.py download-files
uv run python src/agent.py start

# frontend (another terminal)
cd Telugu-Nova/frontend
cp .env.example .env.local      # same LiveKit values, plus AGENT_NAME=nova-te
pnpm install
pnpm dev                        # http://localhost:3002
```

`DATABASE_URL` (Postgres) is optional: it enables remembering students and
class analytics. No secrets are committed — every `.env.local` is gitignored.

### Deploying

- **Frontend:** Vercel, root directory `Telugu-Nova/frontend`.
- **Agent:** LiveKit Cloud (`lk agent create` from `Telugu-Nova/backend`), or
  any host that runs the included Dockerfile.
