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
    cli,
    room_io,
    stt,
    tokenize,
)
from livekit.plugins import deepgram, google, murf, noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

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


class Assistant(Agent):
    def __init__(self, profile: LocaleProfile) -> None:
        super().__init__(instructions=build_system_prompt(profile))
        self._profile = profile
        self._base = profile  # name/state/district stay fixed across switches

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


@server.rtc_session(agent_name="nova")
async def my_agent(ctx: JobContext):
    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

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
        agent=Assistant(PROFILE),
        room=ctx.room,
        room_options=room_io.RoomOptions(
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
