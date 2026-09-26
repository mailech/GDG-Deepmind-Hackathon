import json
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from google.genai import types
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
    room_io,
    stt,
    tokenize,
)
from livekit.plugins import deepgram, google, murf, noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

import analytics
import escalations
import memory
import practice
from locale_map import (
    DEFAULT_PROFILE,
    LocaleProfile,
    normalise_language,
    resolve,
)
from prompts import (
    build_greeting_instructions,
    build_outbound_greeting,
    build_system_prompt,
)
from transliterate import strip_unspeakable, transliterate_stream

logger = logging.getLogger("agent")

load_dotenv(".env.local")

# Day 1: one hardcoded student (Ravi, Warangal). Day 2 reads this from the
# LiveKit token's participant metadata, populated by the /onboard flow.
PROFILE: LocaleProfile = DEFAULT_PROFILE

# Swap this to change the Groq model. Bigger models handle Telugu better;
# see https://console.groq.com/docs/models for what is currently served.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# "vertex" (Gemini on Vertex AI, paid credits) or "groq" (free tier fallback).
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "vertex")

# "deepgram" (accurate, one language per call) or "google".
#
# Live language auto-detection is NOT possible with either, tested Day 1:
#   - Deepgram raises "language detection is not supported in streaming mode"
#   - Google's detect_language always returns whichever language is listed
#     FIRST, regardless of what was actually spoken (verified by swapping the
#     list order against fixed Hindi and Telugu audio)
# So the language is fixed per call, chosen by the student's profile.
STT_PROVIDER = os.getenv("STT_PROVIDER", "deepgram")


# Languages the student may switch between mid-call. Order matters only as a
# hint; Google reports whichever it actually heard. Keep this list short —
# every extra candidate makes detection slower and less certain.
STT_LANGUAGES = ["te-IN", "hi-IN", "en-IN"]


def build_stt():
    """Multilingual streaming STT.

    Deepgram is a one-language-per-connection service in streaming mode, so it
    cannot support code-switching. Google takes a candidate list and tells us
    which language each utterance was, which the Assistant uses to repoint the
    voice and register. Auth is the same ADC used for Vertex.
    """
    if STT_PROVIDER == "google":
        return google.STT(
            languages=STT_LANGUAGES,
            detect_language=True,
            model="latest_long",
            location=os.getenv("VERTEX_LOCATION", "us-central1"),
        )

    # Single-language fallback. Accurate, but the student is locked to one
    # language for the whole call.
    return deepgram.STT(model="nova-3", language=PROFILE.stt_language)


def build_llm():
    """Pick the LLM backend.

    Vertex is preferred: Gemini handles Telugu and Telangana dialect markedly
    better than Llama, and it does not invent facts as readily — both of which
    matter more for a tutor than for a generic agent. Vertex also bills against
    project credits rather than the AI Studio free tier, which caps at 20
    requests PER DAY per model and cannot run a voice loop.

    Vertex authenticates via Application Default Credentials, not an API key:
        gcloud auth application-default login
    """
    if LLM_PROVIDER == "vertex":
        return google.LLM(
            model=os.getenv("VERTEX_MODEL", "gemini-2.5-flash"),
            vertexai=True,
            project=os.environ["VERTEX_PROJECT"],
            location=os.getenv("VERTEX_LOCATION", "us-central1"),
            # Gemini 2.5 "thinks" before answering by default, spending output
            # tokens and wall-clock on reasoning the student never hears. In a
            # voice loop that shows up as truncated replies and dead air, so
            # turn it off — conversational tutoring needs no deliberation.
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            # Must be generous: tool-call ARGUMENTS count against this budget,
            # and a program passed to show_code easily exceeds a few hundred
            # tokens. At 200 the call was truncated mid-JSON and Gemini returned
            # MALFORMED_FUNCTION_CALL — silently dropping it, so the agent said
            # "code is coming" and nothing appeared. Flowcharts survived only
            # because their arguments are short.
            #
            # Spoken brevity is enforced by the prompt (STYLE: under twenty
            # words a sentence, twenty seconds a turn), not by starving the
            # model of tokens.
            max_output_tokens=2048,
        )

    return openai.LLM(
        model=GROQ_MODEL,
        base_url="https://api.groq.com/openai/v1",
        api_key=os.environ["GROQ_API_KEY"],
    )


CANVAS_TOPIC = "nova-canvas"


class Assistant(Agent):
    def __init__(self, profile: LocaleProfile, room: rtc.Room | None = None) -> None:
        super().__init__(instructions=build_system_prompt(profile))
        self._profile = profile
        self._base = profile  # name/state/district stay fixed across switches
        self._room = room
        self._student: str | None = None  # set once we know who we are talking to
        # Day 8: what actually happened on this call. Only tools moving these
        # counts as delivery — the model cannot talk its way to a success.
        self.stats: dict[str, int] = {
            "concepts_taught": 0,
            "problems_given": 0,
            "escalations": 0,
            "turns": 0,
            "tool_errors": 0,
        }

    async def _push_canvas(self, payload: dict) -> None:
        """Send something for the student to LOOK at, not listen to.

        Code and diagrams are unspeakable — reading a for-loop aloud is
        useless. These go over the LiveKit data channel to the browser, which
        renders them beside the conversation while the agent keeps talking
        normally about what is on screen.
        """
        if self._room is None:
            logger.warning("canvas push skipped: no room")
            return
        await self._room.local_participant.publish_data(
            json.dumps(payload, ensure_ascii=False),
            reliable=True,
            topic=CANVAS_TOPIC,
        )

    @function_tool
    async def show_code(
        self,
        context: RunContext,
        title: str,
        language: str,
        code: str,
    ) -> str:
        """Display a program on the student's screen.

        Call this whenever you write or discuss actual code — an example, a
        solution, a fix, a comparison. The student sees it while you explain it
        out loud. Do NOT read the code aloud line by line; talk about what it
        does.

        Args:
            title: Short label, e.g. "Binary search" or "Bubble sort".
            language: Language id, e.g. python, java, c, cpp, javascript, sql.
            code: The complete program or snippet. Real, runnable, correct.
        """
        await self._push_canvas(
            {"kind": "code", "title": title, "language": language, "code": code}
        )
        self.stats["concepts_taught"] += 1
        logger.info("canvas: code", extra={"title": title, "language": language})
        return "The code is now on the student's screen. Explain what it does."

    @function_tool
    async def show_flowchart(
        self,
        context: RunContext,
        title: str,
        steps: list[str],
    ) -> str:
        """Draw a flowchart on the student's screen, one box at a time.

        Call this when explaining an algorithm, a process, or any sequence of
        steps — how a loop runs, how a request reaches a server, how recursion
        unwinds. The boxes animate in one after another, so narrate along with
        them rather than listing them.

        Write a step as a question ending in "?" to make it a decision diamond
        with yes/no branches.

        Args:
            title: Short label, e.g. "Binary search flow".
            steps: Ordered steps, 3 to 8 of them, a few words each. Use the
                student's language for prose but keep code terms in English.
        """
        await self._push_canvas({"kind": "flow", "title": title, "steps": steps})
        logger.info("canvas: flow", extra={"title": title, "steps": len(steps)})
        return "The flowchart is drawing on screen. Walk through it as it appears."

    @function_tool
    async def clear_canvas(self, context: RunContext) -> str:
        """Clear the screen when moving on to a different topic."""
        await self._push_canvas({"kind": "clear"})
        return "Screen cleared."

    # --- Day 5: real practice problems ------------------------------------

    @function_tool
    async def find_practice_problem(
        self,
        context: RunContext,
        topic: str = "",
        level: str | None = None,
    ) -> str:
        """Fetch a REAL coding problem for the student to solve.

        Call this whenever the student wants something to practise, asks for a
        question or an exercise, says they want to try it themselves, or says
        they have understood a topic and you want to check. Also call it when
        you finish teaching something and it is time to apply it.

        Call it straight away — do NOT interrogate them first. If they did not
        name a topic, pass whatever you were just discussing, or the weak spot
        you remember about them, or leave topic empty and you will get a
        general problem at their level. Asking "which topic?" before calling is
        the wrong move; give them something and adjust if they want different.

        This returns an actual problem from Codeforces, not an invented one.
        Never make up a problem name, rating or link — if this tool fails, say
        so out loud.

        Args:
            topic: What to practise, in plain words — "binary search", "dp",
                "arrays", "graphs", "strings", "recursion", "greedy", "trees".
                Optional; empty means any topic at their level.
            level: "beginner", "intermediate" or "advanced". Leave empty to use
                what you already know about this student from memory.
        """
        # Chain with Day 4: if we already know their level, do not ask again.
        if not level and self._student:
            record = await memory.recall(self._student)
            if record:
                stored = str(record["facts"].get("level", "")) or None
                if stored:
                    level = stored
                    logger.info("practice: level from memory", extra={"lvl": stored})

        try:
            p = await practice.find_problem(topic, level)
        except practice.PracticeUnavailableError as exc:
            self.stats["tool_errors"] += 1
            logger.warning("practice unavailable: %s", exc)
            return (
                "Codeforces could not be reached, so there is NO problem to give. "
                "Tell the student plainly that the practice site is not responding "
                "right now, do not invent a problem, and offer to make one up "
                "yourself or carry on explaining instead."
            )

        await self._push_canvas(
            {
                "kind": "problem",
                "title": p["name"],
                "rating": p["rating"],
                "tags": p["tags"],
                "url": p["url"],
                "source": p["source"],
                "freshness": p["freshness"],
            }
        )
        self.stats["problems_given"] += 1
        logger.info(
            "practice: sent", extra={"problem": p["name"], "rating": p["rating"]}
        )
        return (
            f"Problem is on their screen: '{p['name']}', difficulty {p['rating']}, "
            f"tags {', '.join(p['tags'])}. From {p['source']}, {p['freshness']}. "
            f"Say the name and roughly how hard it is, mention it came from "
            f"Codeforces and how fresh the data is, and tell them it is on screen. "
            f"Do NOT read the URL or the tag list aloud."
        )

    # --- Day 7: asking a human for help -----------------------------------

    @function_tool
    async def create_escalation(
        self,
        context: RunContext,
        reason: str,
        urgency: str,
        summary: str,
        already_tried: str = "",
        follow_up: str = "",
    ) -> str:
        """Hand this student to a real human.

        Call this in exactly two situations:

        1. reason="wellbeing" — they are distressed, frightened, or said
           something that worries you about their safety. You are not a
           counsellor. Do not try to fix it yourself.
        2. reason="teacher" — you have genuinely failed to teach it. You have
           explained the same thing several different ways and they still
           cannot follow, or they need something only a real teacher can give.

        ONLY call this after you have told them what you want to send and they
        have agreed. If they said no, do not call it.

        Never put a phone number, email, password, OTP or ID number in any
        field. Never paste the conversation. Summarise.

        Args:
            reason: "wellbeing" or "teacher".
            urgency: "low", "medium", "high", or "emergency". Use "emergency"
                only for immediate physical safety.
            summary: Two sentences on who needs help and what happened.
            already_tried: What you attempted, so the human does not repeat it.
            follow_up: How they would like to be reached, in their words.
        """
        result = await escalations.create(
            student=self._student,
            reason=reason,
            urgency=urgency,
            summary=summary,
            already_tried=already_tried,
            language=self._profile.language,
            follow_up=follow_up,
        )
        ref = result["ref"]
        self.stats["escalations"] += 1
        logger.info(
            "escalation", extra={"ref": ref, "reason": reason, "urgency": urgency}
        )

        when = (
            "Someone checks these through the day, so it may be a few hours. "
            "Do not promise anyone will call immediately."
        )
        if result["updated"]:
            return (
                f"There was already an open request for this, so it was updated "
                f"rather than duplicated. The reference is still {ref}. Tell them "
                f"the reference, digit by digit, and that it is already with a "
                f"human. {when}"
            )
        return (
            f"Filed. Reference {ref}. Read it to them slowly, digit by digit, and "
            f"tell them to keep it. Say plainly what happens next. {when}"
        )

    @function_tool
    async def check_escalation(self, context: RunContext, ref: str) -> str:
        """Look up a request the student already has a reference for.

        Call this when they read a reference back to you and ask what happened
        to it.

        Args:
            ref: What they said, e.g. "NOVA-4821" or just "4821".
        """
        cleaned = ref.strip().upper()
        if not cleaned.startswith("NOVA-"):
            cleaned = f"NOVA-{''.join(c for c in cleaned if c.isdigit())}"

        record = await escalations.status(cleaned)
        if record is None:
            return (
                f"No request found for {cleaned}. Ask them to read it again — "
                f"it is the word Nova and four digits. Do not invent a status."
            )
        return (
            f"Request {record['ref']} is '{record['status']}', urgency "
            f"{record['urgency']}, raised {record['created_at']:%d %B}. "
            f"Tell them plainly, and do not promise a time you do not know."
        )

    # --- Day 4: memory ----------------------------------------------------
    # The agent reaches storage ONLY through these tools, never through the
    # prompt, so everything it remembers is auditable and deletable.

    @function_tool
    async def recall_student(self, context: RunContext, name: str) -> str:
        """Look up whether you have taught this student before.

        Call this as soon as they tell you their name — before you say anything
        else about them. Never guess whether you know someone.

        Args:
            name: The name they gave you, spelled as you heard it.
        """
        record = await memory.recall(name)
        if record is None:
            logger.info("recall: new student", extra={"student": name})
            return (
                f"No record for {name}. This is a first meeting — greet them as "
                f"someone new. Do not pretend to remember anything."
            )

        self._student = record["name"]
        facts = record["facts"]
        logger.info("recall: returning student", extra={"student": record["name"]})
        return (
            f"You have taught {record['name']} before. "
            f"Last time: {record['last_interaction']}. "
            f"What you know: {json.dumps(facts, ensure_ascii=False)}. "
            f"Welcome them back by name and pick up from one specific thing here "
            f"— ideally something they found hard. Do not read the whole list out."
        )

    @function_tool
    async def remember_student(
        self,
        context: RunContext,
        name: str,
        level: str | None = None,
        topic_covered: str | None = None,
        weak_spot: str | None = None,
        language_preference: str | None = None,
    ) -> str:
        """Save what you learned about this student, so next time is better.

        ONLY call this after you have told them you are going to remember and
        they have agreed. If they said no, or you did not ask, do not call it.

        Args:
            name: Their name.
            level: How far along they are, e.g. "first year, just started C".
            topic_covered: One topic you got through today, e.g. "binary search".
            weak_spot: A mistake they keep making, e.g. "confuses = and ==".
                This is the single most useful thing to store.
            language_preference: "te", "hi" or "en" if they made it clear.
        """
        facts: dict[str, object] = {}
        existing = await memory.recall(name)
        prior = existing["facts"] if existing else {}

        if level:
            facts["level"] = level
        # Append to lists rather than replacing, so history accumulates.
        for key, value in (
            ("topics_covered", topic_covered),
            ("weak_spots", weak_spot),
        ):
            if value:
                current = list(prior.get(key, []) or [])
                if value not in current:
                    current.append(value)
                facts[key] = current

        if not facts and not language_preference:
            return "Nothing to save."

        await memory.remember(name, facts, language_preference)
        self._student = name
        logger.info("remembered", extra={"student": name, "keys": list(facts.keys())})
        return "Saved. Tell them briefly that you will remember, then carry on."

    @function_tool
    async def forget_student(self, context: RunContext, name: str) -> str:
        """Delete everything you have stored about this student.

        Call this the moment they ask to be forgotten. Do not argue, do not ask
        why, do not try to talk them out of it. Confirm once it is done.

        Args:
            name: Their name.
        """
        removed = await memory.forget(name)
        self._student = None
        logger.info("forget", extra={"student": name, "removed": removed})
        return (
            "Deleted everything about them. Confirm plainly that it is gone."
            if removed
            else "There was nothing stored about them. Say so plainly."
        )

    async def stt_node(self, audio, model_settings):
        """Watch the detected language and follow the student when they switch.

        Students here are multilingual and code-switch constantly. Deepgram
        reports a language per utterance; when it settles on a different one
        than we are currently speaking, reconfigure voice and prompt live.
        """
        async for ev in Agent.default.stt_node(self, audio, model_settings):
            if isinstance(ev, stt.SpeechEvent) and ev.alternatives:
                # A final transcript means the student actually said something.
                # This separates "joined and left" from "talked but got nowhere".
                if (
                    ev.type == stt.SpeechEventType.FINAL_TRANSCRIPT
                    and (ev.alternatives[0].text or "").strip()
                ):
                    self.stats["turns"] += 1
                detected = normalise_language(ev.alternatives[0].language)
                if detected and detected != self._profile.language:
                    await self._switch_language(detected)
            yield ev

    async def _switch_language(self, language: str) -> None:
        """Repoint TTS voice and system prompt at a new language, mid-call."""
        profile = resolve(
            name=self._base.name,
            state=self._base.state,
            district=self._base.district,
            prefer_language=language,
        )
        logger.info(
            "student switched language",
            extra={
                "from": self._profile.language,
                "to": profile.language,
                "voice": profile.murf_voice_id,
            },
        )
        self._profile = profile
        await self.update_instructions(build_system_prompt(profile))
        self.session.tts.update_options(
            locale=profile.murf_locale,
            voice=profile.murf_voice_id,
            style=profile.murf_style,
        )

    async def tts_node(self, text, model_settings):
        """Transliterate on the way to the voice, and only there.

        Telugu has no Murf voice, so Telugu text is shifted into Kannada script
        before synthesis (see transliterate.py). transcription_node is left
        untouched, so the student still reads real Telugu on screen.
        """
        # Always runs — it strips emoji and other unspeakable characters, which
        # the model emits regardless of what the prompt says. Transliteration
        # only kicks in when the profile asks for it.
        text = transliterate_stream(text, self._profile.tts_transliterate)
        return Agent.default.tts_node(self, text, model_settings)

    async def transcription_node(self, text, model_settings):
        """Clean the on-screen transcript too.

        tts_node only fixes what is spoken. Without this, leaked scaffolding
        like <speak> or print(default_api...) still appears on the student's
        screen even though they never hear it.
        """

        async def cleaned():
            async for chunk in text:
                if isinstance(chunk, str):
                    out = strip_unspeakable(chunk)
                    if out:
                        yield out
                else:
                    yield chunk

        return Agent.default.transcription_node(self, cleaned(), model_settings)

    # To add tools, use the @function_tool decorator.
    # Here's an example that adds a simple weather tool.
    # You also have to add `from livekit.agents import function_tool, RunContext` to the top of this file
    # @function_tool
    # async def lookup_weather(self, context: RunContext, location: str):
    #     """Use this tool to look up current weather information in the given location.
    #
    #     If the location is not supported by the weather service, the tool will indicate this. You must tell the user the location's weather is unavailable.
    #
    #     Args:
    #         location: The location to look up weather information for (e.g. city name)
    #     """
    #
    #     logger.info(f"Looking up weather for {location}")
    #
    #     return "sunny with a temperature of 70 degrees."


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name="nova-te")
async def my_agent(ctx: JobContext):
    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # Open the connection pool before the first turn, so the initial lookup is
    # not paying for a cold TLS handshake while the student waits.
    try:
        await memory.init()
    except Exception:
        logger.exception("memory unavailable — continuing without it")

    logger.info(
        "session locale resolved",
        extra={
            "district": PROFILE.district,
            "register": PROFILE.register_pack,
            "voice": PROFILE.murf_voice_id,
            "script": PROFILE.script,
        },
    )

    # Set up a voice AI pipeline using Murf Falcon, Gemini, Deepgram, and the LiveKit turn detector
    session = AgentSession(
        # STT is deliberately the ONLY place the ASR provider is named (design D3).
        # Deepgram nova-3 supports te/te-IN natively; swap this one line for
        # Google or Sarvam if real-world Telugu accuracy proves insufficient.
        # STT is the only place the ASR provider is named (design D3).
        #
        # Google rather than Deepgram, because Deepgram cannot detect language
        # on a streaming connection at all -- it raises "language detection is
        # not supported in streaming mode" -- and students here code-switch
        # constantly. Google accepts a list of candidate languages and reports
        # which one it heard, which is what makes live switching possible.
        stt=build_stt(),
        # Gemini on Vertex by default; set LLM_PROVIDER=groq to fall back.
        llm=build_llm(),
        # Voice comes from the locale profile. Note Murf has NO Telugu voice, so
        # a Telugu profile resolves to an en-IN voice reading romanised Telugu.
        tts=murf.TTS(
            model="FALCON",
            locale=PROFILE.murf_locale,
            voice=PROFILE.murf_voice_id,
            style=PROFILE.murf_style,
            tokenizer=tokenize.basic.SentenceTokenizer(min_sentence_len=2),
            text_pacing=True,
        ),
        # VAD and turn detection are used to determine when the user is speaking and when the agent should respond
        # See more at https://docs.livekit.io/agents/build/turns
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        # Speculatively start the LLM before the student finishes speaking, so
        # the reply is already forming by end-of-turn. This was off while we
        # were on a free-tier request quota; on Vertex credits the extra calls
        # are cheap and this is the largest single latency win available.
        # See more at https://docs.livekit.io/agents/build/audio/#preemptive-generation
        preemptive_generation=True,
    )

    # To use a realtime model instead of a voice pipeline, use the following session setup instead.
    # (Note: This is for the OpenAI Realtime API. For other providers, see https://docs.livekit.io/agents/models/realtime/))
    # 1. Install livekit-agents[openai]
    # 2. Set OPENAI_API_KEY in .env.local
    # 3. Add `from livekit.plugins import openai` to the top of this file
    # 4. Use the following session setup instead of the version above
    # session = AgentSession(
    #     llm=openai.realtime.RealtimeModel(voice="marin")
    # )

    # # Add a virtual avatar to the session, if desired
    # # For other providers, see https://docs.livekit.io/agents/models/avatar/
    # avatar = hedra.AvatarSession(
    #   avatar_id="...",  # See https://docs.livekit.io/agents/models/avatar/plugins/hedra
    # )
    # # Start the avatar and wait for it to join
    # await avatar.start(session, room=ctx.room)

    # Keep a reference: the outbound path needs to tell the Assistant who it
    # rang, so memory lookups during the call attach to the right student.
    assistant = Assistant(PROFILE, room=ctx.room)

    # Day 8: open the row now, not at the end. A student who joins and leaves
    # without speaking is exactly the failure we want counted, and that call
    # never reaches a tidy ending.
    call_started = datetime.now(timezone.utc)
    channel = "phone" if ctx.room.name.startswith("nova-outbound-") else "browser"
    try:
        await analytics.start_call(ctx.room.name, channel, PROFILE.language)
    except Exception:
        logger.exception("could not open analytics row — call still proceeds")

    async def close_out():
        """Record the outcome however the call ends, including a hang-up."""
        try:
            result = await analytics.finish_call(
                ctx.room.name, assistant._student, assistant.stats, call_started
            )
            logger.info("call outcome", extra=result)
        except Exception:
            logger.exception("could not close analytics row")

    ctx.add_shutdown_callback(close_out)

    # Start the session, which initializes the voice pipeline and warms up the models
    await session.start(
        agent=assistant,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            # Publish transcriptions to the browser so the on-screen transcript
            # fills in. Enabled explicitly rather than relying on the default.
            text_output=room_io.TextOutputOptions(sync_transcription=True),
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind
                    == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC()
                ),
            ),
        ),
    )

    # Join the room and connect to the user
    await ctx.connect()

    # Speak first, in-dialect, before the student says anything.
    #
    # Outbound needs a completely different opening: they did not ask for this
    # call and do not know who is ringing, so the first two sentences must say
    # who, why, and how to stop it. outbound.py signals this through the job
    # metadata it attaches at dispatch.
    job_meta: dict = {}
    if ctx.job and ctx.job.metadata:
        try:
            job_meta = json.loads(ctx.job.metadata)
        except (ValueError, TypeError):
            logger.warning("job metadata was not JSON; treating call as inbound")

    if job_meta.get("direction") == "outbound":
        student = job_meta.get("student")
        facts = None
        if student:
            record = await memory.recall(student)
            if record:
                facts = record["facts"]
                assistant._student = student
        logger.info("outbound call", extra={"callee": student or "unknown"})
        greeting = build_outbound_greeting(PROFILE, student, facts)
    else:
        greeting = build_greeting_instructions(PROFILE)

    await session.generate_reply(instructions=greeting)


if __name__ == "__main__":
    cli.run_app(server)
