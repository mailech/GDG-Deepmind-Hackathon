import json
import logging
import os

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

import memory
from locale_map import (
    DEFAULT_PROFILE,
    LocaleProfile,
    normalise_language,
    resolve,
)
from prompts import build_greeting_instructions, build_system_prompt
from transliterate import transliterate_stream

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
            # Spoken turns are short by design (see TUTOR_CORE). Capping output
            # stops the model rambling, which is the single biggest source of
            # dead air — every extra token is extra time before the turn ends.
            max_output_tokens=200,
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

    # Start the session, which initializes the voice pipeline and warms up the models
    await session.start(
        agent=Assistant(PROFILE, room=ctx.room),
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

    # Speak first, in-dialect, before the student says anything. This is the
    # hook moment from design section 4.4 — the app greeting them in their own
    # register from second zero is the whole product promise.
    await session.generate_reply(instructions=build_greeting_instructions(PROFILE))


if __name__ == "__main__":
    cli.run_app(server)
