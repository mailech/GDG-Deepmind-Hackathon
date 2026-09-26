# System Design — "Concept Anna"
### Voice tutor that explains uploaded study material in the student's native language and dialect
*10 Days of Voice Agents — #VoiceForBharat Edition · Track: Learning & Literacy*

---

## 1. Product in one paragraph

A student opens a web app that looks like a social app, not a chatbot. On first visit, a short onboarding asks where they're from (state → district). From that point on, the app greets them by voice in their native language and regional dialect. The student uploads a photo, PDF, or text of any concept from any subject — a textbook page, class notes, a diagram. The system reads and understands the material, then a voice tutor explains the concept conversationally in the student's own language and dialect, using local examples, and answers follow-up questions by voice in real time.

---

## 2. Core design decisions (read these first)

**D1 — Dialect lives in the LLM, not the TTS.**
Murf provides one voice per language (e.g., one te-IN voice), not one per dialect. So dialect is produced at the *text* layer: the LLM is instructed to write in the register of the student's region (Telangana Telugu vs coastal Andhra Telugu vs Rayalaseema; Chennai Tamil vs Madurai Tamil), and the single Murf voice for that language speaks it. This is linguistically sound — dialect is mostly vocabulary, idiom, and sentence rhythm, all of which the LLM controls.

**D2 — Document understanding is Gemini multimodal, no OCR service.**
Uploaded images/PDFs go directly to Gemini (already the LLM in the starter stack). It reads handwriting, printed text, and diagrams in one call and returns a structured concept summary. Zero extra infrastructure.

**D3 — STT is the riskiest component; keep it swappable.**
Recognizing spoken Telugu/Tamil/Kannada is harder than speaking it. The design isolates STT behind one config line so Deepgram can be swapped for Google STT or Sarvam (built for Indian languages) after real-world testing. Do not hard-couple anything to Deepgram.

**D4 — Two channels, one brain.**
Real-time voice runs over LiveKit (WebRTC). Document upload and profile management run over plain HTTP to the backend. Both feed the same agent session state, so the voice tutor "knows" what was just uploaded without the student re-explaining.

**D5 — The UI is a companion feed, not a chat window.**
No chat bubbles as the primary surface. The home screen is a story/card feed (like Instagram): concept cards from past sessions, streaks, a big "learn something" action. The live session screen is a voice orb + the uploaded document + key points appearing as visual cards while the tutor speaks.

---

## 3. High-level architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     FRONTEND (Next.js on Vercel)             │
│                                                              │
│  Onboarding flow · Home feed (stories/cards) · Upload sheet  │
│  Live session view (voice orb + doc + concept cards)         │
│  Profile & streaks                                           │
└──────────┬──────────────────────────────┬───────────────────┘
           │ HTTPS (REST)                 │ WebRTC (audio)
           ▼                              ▼
┌──────────────────────┐      ┌──────────────────────────────┐
│  API BACKEND         │      │  LIVEKIT CLOUD               │
│  (FastAPI, Railway)  │      │  (rooms, audio transport,    │
│                      │      │   token auth)                │
│  /onboard            │      └──────────┬───────────────────┘
│  /upload             │                 │ agent joins room
│  /profile            │                 ▼
│  /sessions           │      ┌──────────────────────────────┐
│  /greeting           │      │  VOICE AGENT (Python worker,  │
└──────────┬───────────┘      │  LiveKit Agents, Railway)     │
           │                  │                               │
           │ shared state     │  STT (Deepgram → swappable)   │
           ▼                  │  LLM (Gemini 2.5 Flash)       │
┌──────────────────────┐      │  TTS (Murf Falcon 2,          │
│  DATA LAYER          │◄─────┤       voice picked per user)  │
│  Postgres (Railway)  │      │  Session context injector     │
│  + S3/R2 for uploads │      └──────────────────────────────┘
└──────────────────────┘
```

Key point: frontend and agent never talk directly. Audio flows through LiveKit; everything else flows through the API backend and the shared database.

---

## 4. The language & dialect engine

This is the heart of the product. It resolves **location → language → dialect register → Murf voice → greeting**.

### 4.1 Locale profile (stored per user at onboarding)

```json
{
  "user_id": "u_2841",
  "name": "Ravi",
  "state": "Telangana",
  "district": "Warangal",
  "language": "te",
  "dialect_register": "telangana",
  "murf_voice_id": "te-IN-<voice>",
  "greeting_style": "warm_informal"
}
```

### 4.2 Resolution map (static config, `locale_map.py`)

| State (examples) | Language | Dialect registers by district cluster | Murf voice |
|---|---|---|---|
| Telangana | Telugu | telangana (all districts) | te-IN voice |
| Andhra Pradesh | Telugu | coastal (Krishna, Godavari…), rayalaseema (Kadapa, Anantapur…) | te-IN voice |
| Tamil Nadu | Tamil | chennai, madurai/southern | ta-IN voice |
| Karnataka | Kannada | bengaluru, north-karnataka | kn-IN voice |
| Maharashtra | Marathi | pune-mumbai, vidarbha | mr-IN voice |
| Hindi belt (UP, MP, Bihar…) | Hindi | khadi-boli, bhojpuri-influenced, bundeli… | hi-IN voice |
| (fallback: any other state) | Hindi or Indian English | neutral | hi-IN / en-IN voice |

*Ship v1 with 2–3 languages deeply (Telugu with 3 registers, Tamil, Hindi) rather than 11 shallowly. The map is data, so adding a state is a config edit, not code.*

### 4.3 Dialect register packs

Each register is a prompt fragment with concrete style rules and examples, e.g. `registers/te_telangana.md`:

```
Speak Telangana Telugu. Markers: "ra/anna/akka" address forms,
"emo", "gatla", "cheyyi", "unnav a?" question forms.
Avoid coastal formal endings ("andi" only for elders).
Local example sources: Warangal, Hyderabad street life, farming,
RTC buses, local food (sarva pindi, jonna rotte).
Sample explanation tone:
"Newton's third law ante enti ra ante — nuvvu wall ni
gattiga netthav anuko, wall kuda ninnu anthe force tho
venakki netthadi. Action ki equal opposite reaction."
```

The agent's system prompt is assembled at session start:
`base_tutor_prompt + register_pack(user) + session_context(uploaded_concept)`.

### 4.4 The dynamic greeting

`GET /greeting` returns a short LLM-generated greeting in the user's register (time-of-day aware, streak aware), which the frontend plays via Murf on app open:

> "Ravi anna! Manchi sayantram. Ninna physics lo aagipoyav kada — ee roju continue cheddama?"

Cache one greeting per user per day to keep it instant and cheap.

---

## 5. Document → concept pipeline

```
Upload (image/PDF/text)
   │  POST /upload  (multipart)
   ▼
Store raw file (S3/R2) + create document row (status: processing)
   │
   ▼
Gemini multimodal call — one structured extraction:
   {
     "subject": "Physics",
     "concept_title": "Newton's Third Law",
     "concept_summary": "...",
     "key_points": ["...", "...", "..."],
     "difficulty": "class 9-10",
     "diagrams_described": ["free-body diagram showing ..."],
     "likely_exam_questions": ["...", "..."]
   }
   ▼
Save extraction to DB (status: ready) → notify frontend
   │
   ▼
Injected into the live agent session as context:
"The student just uploaded material about <concept_title>.
 Key points: <...>. Explain it in <register>, using local
 examples. Check understanding with one question at a time."
```

Handoff mechanism: the agent worker watches the session's `active_document_id` (DB poll or LiveKit data-channel message from the frontend on upload-complete). When it changes, the agent proactively says, in-register: *"Sare, nee photo chusina — Newton's third law gurinchi undi. Cheptha vinu…"* — no user prompt needed. This moment is your best demo material.

---

## 6. Data model (Postgres)

```
users        id · name · state · district · language · dialect_register
             murf_voice_id · created_at · streak_count · last_seen_at

documents    id · user_id · file_url · file_type · status
             subject · concept_title · extraction_json · created_at

sessions     id · user_id · document_id? · started_at · ended_at
             transcript_url? · concepts_covered[]

concept_cards id · user_id · document_id · title · summary
              mastery_level (new/learning/known) · last_reviewed_at
```

`concept_cards` powers the Insta-style feed *and* becomes the memory/spaced-repetition layer for later challenge days — one table, two features.

---

## 7. API surface (FastAPI)

```
POST /onboard        {name, state, district}         → locale profile
GET  /profile        → profile + streak
GET  /greeting       → {text, audio_url}  (register-aware, daily-cached)
POST /upload         multipart file                   → {document_id}
GET  /documents/:id  → extraction status + concept JSON
POST /session/token  → LiveKit room token (voice metadata embedded)
GET  /feed           → concept cards for home screen
```

The LiveKit token's participant metadata carries `{user_id, language, dialect_register, murf_voice_id}` so the agent configures TTS voice and prompt *before* the first word — the greeting inside the call is in-dialect from second zero.

---

## 8. Frontend design spec (the "not a bot" mandate)

**Design language:** dark or warm-gradient theme, big rounded cards, spring animations, one accent gradient (saffron→pink works for the Bharat framing). Poppins/Baloo-style rounded type for Latin, Noto Sans Telugu/Tamil for scripts. Mobile-first — students are on phones.

**Screens:**

1. **Onboarding (3 steps, story-style full-screen)** — name → state (grid of state cards with emblems) → district (searchable list). Ends with the app *speaking* its first in-dialect greeting while a waveform pulses. That's the hook moment.
2. **Home feed** — top: horizontal "story rail" of recent concept cards (tap to review). Middle: greeting card with today's streak. Bottom: one dominant action — a floating camera/upload button, framed as "photo teeyi, nenu chepta" (snap it, I'll explain).
3. **Live session** — uploaded page shown as a card at top; center: animated voice orb that reacts to the tutor's audio; as the tutor explains, key-point cards slide in one by one (generated from the extraction JSON — synchronized visuals without extra AI calls). Mic control at bottom. No chat log on screen by default (toggle to see transcript).
4. **Concept card detail** — swipeable card: title, summary, key points, "explain again" (re-opens voice session with this context), mastery indicator.

**Component stack:** Next.js App Router · Tailwind · Framer Motion (orb + card animations) · LiveKit React components for audio only (restyled — hide default chat UI).

---

## 9. Agent pipeline detail (Python worker)

```python
AgentSession(
    stt  = deepgram.STT(model="nova-3", language=user.language),  # swappable → sarvam/google
    llm  = google.LLM(model="gemini-2.5-flash"),
    tts  = murf.TTS(voice=user.murf_voice_id, model="falcon-2"),
    turn_detection = ...,
)
```

System prompt assembly order:
1. **Tutor core** — patient, one idea at a time, checks understanding, never lectures >30s without a question, local examples mandatory.
2. **Register pack** — dialect rules + sample sentences (§4.3).
3. **Session context** — active document extraction, student's known weak concepts.
4. **Voice-output constraints** — short sentences, no markdown, no lists read aloud, numbers in words, English technical terms kept in English but explained ("force ante balam — kani exam lo 'force' ani rasko").

---

## 10. Known risks & mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Murf lacks a voice for some language (verify te-IN on Falcon 2 today) | High | Confirm on Day 1 via voice library; fallback order: Studio voice → Hindi → Indian English. Design already routes per-user voice, so fallback is config. |
| STT accuracy for Telugu/Tamil speech | High | Swappable STT (D3); test Deepgram vs Google vs Sarvam with real speech in week 1. Also allow text follow-ups in the session UI as a safety valve. |
| Code-mixed speech (Telugu + English terms) confuses STT | Medium | Prompt tutor to accept approximate transcripts; Gemini is robust to noisy STT text. |
| Gemini misreads bad photos / handwriting | Medium | Extraction returns confidence; below threshold, tutor *asks* the student what chapter it is instead of guessing. Honest failure > confident nonsense. |
| Dialect quality drift (LLM slips into formal/coastal register) | Medium | Register packs include negative examples; add 2–3 few-shot exchanges per register. |
| Latency stack-up (STT+LLM+TTS+doc context) | Medium | Falcon 2 streaming (~100 ms TTFA); keep extraction *out* of the voice loop (pre-processed at upload); log end-of-speech→first-audio daily (Day 1 advanced task). |
| Scope for 10 days | High | Phase it (§11). Days 1–2 need none of the DB/feed. |

---

## 11. Build phasing mapped to the challenge

| Day | What ships from this design |
|---|---|
| 1 | Starter running · Murf Indian voice · hardcoded locale profile · in-dialect spoken greeting · basic tutor prompt with one register pack |
| 2 | Real onboarding flow (state/district → locale map) · dynamic greeting endpoint |
| 3 | Upload → Gemini extraction pipeline (text/photo) · agent explains the uploaded concept |
| 4 | Session UI v1: voice orb + document card + key-point cards |
| 5 | Postgres + concept_cards · memory across sessions ("last time you struggled with…") |
| 6 | RAG over uploaded documents & syllabus content · multi-document library |
| 7 | Home feed + streaks + mastery dashboard (the Insta layer, fully) |
| 8 | Second/third language live (Tamil/Hindi register packs) · voice switching |
| 9 | Deploy: Railway (API + agent) + Vercel (frontend) · public URL |
| 10 | Telephony entry point (LiveKit SIP) if the task asks · README + known-limitations · final film |

*Each morning's official task may reorder this — the modules are deliberately independent so re-sequencing costs nothing.*
