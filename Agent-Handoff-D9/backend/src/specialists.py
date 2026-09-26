"""Day 9: three specialists Nova can hand the conversation to.

Nova is a generalist — good company, decent at everything, expert at nothing.
These three are narrow on purpose:

    ALGO     (అల్గో)   DSA and complexity. Telugu, male, quick and energetic.
    KEERTHI  (కీర్తి)  Debugging a specific broken program. Telugu, female,
                      deliberately slower — a panicking student needs calm.
    VIKRAM   (विक्रम)  Interview preparation. HINDI, male, steady.

Each has its own voice, so the handoff is audible before anyone announces it.
Each inherits the conversation via chat_ctx, so the student never repeats
themselves. Each can hand back when its job is done or the topic moves on.

Why Vikram speaks Hindi: campus placement rounds in Hyderabad are conducted in
Hindi and English far more often than Telugu, so practising in Telugu would be
practising the wrong thing.
"""

from __future__ import annotations

import logging
from typing import Any

from livekit.agents import Agent, RunContext, function_tool
from livekit.plugins import murf

logger = logging.getLogger("agent.specialists")


# Each specialist is a distinct voice AND a distinct delivery. Same words in a
# different tempo is most of what makes two people sound like two people.
VOICES: dict[str, dict[str, Any]] = {
    "algo": {
        "voice": "mr-IN-prathamesh",
        "locale": "te-IN",
        "speed": 8,  # brisk — this one is enthusiastic about complexity
        "pitch": 0,
    },
    "keerthi": {
        "voice": "en-IN-anisha",
        "locale": "te-IN",
        "speed": -6,  # slower — you are already stressed, she is not
        "pitch": 4,
    },
    "vikram": {
        "voice": "hi-IN-karan",
        "locale": "hi-IN",
        "speed": -2,
        "pitch": -3,  # steadier, a shade lower — interview-room composure
    },
}

# Sent to the browser so the UI changes with the voice.
IDENTITY: dict[str, dict[str, str]] = {
    "nova": {
        "name": "నోవా",
        "role": "Computer Science",
        "tint": "#C4704F",
        "lang": "తెలుగు",
    },
    "algo": {
        "name": "అల్గో",
        "role": "DSA & algorithms",
        "tint": "#5B7FA6",
        "lang": "తెలుగు",
    },
    "keerthi": {"name": "కీర్తి", "role": "debugging", "tint": "#6F9E82", "lang": "తెలుగు"},
    "vikram": {
        "name": "विक्रम",
        "role": "interview prep",
        "tint": "#C89B4A",
        "lang": "हिंदी",
    },
}


def _tts(key: str) -> murf.TTS:
    cfg = VOICES[key]
    return murf.TTS(
        model="FALCON",
        voice=cfg["voice"],
        locale=cfg["locale"],
        style="Conversational",
        speed=cfg["speed"],
        pitch=cfg["pitch"],
    )


SHARED_STYLE = """
Your words are spoken aloud. Short sentences, under about twenty words. No
markdown, no bullet points, no emoji, no reading URLs. Never read code aloud
line by line — put it on screen with show_code and talk about what it does.
"""


class Specialist(Agent):
    """Common behaviour: knows who it is, can give the conversation back."""

    key: str = "specialist"

    #: Filled in by whoever hands this specialist the conversation.
    handoff_reason: str = ""
    handoff_from: str = "nova"

    def __init__(self, instructions: str, main: Agent, chat_ctx=None) -> None:
        # Specialists borrow the main agent's screen and practice tools, AND
        # its routing tools so they can pass a student straight sideways —
        # Algo -> Keerthi without bouncing through Nova first. Two announced
        # handoffs to reach the right person is a worse experience than one.
        #
        # The ping-pong risk is handled in the instructions: never transfer to
        # someone who just transferred to you.
        super().__init__(
            instructions=instructions,
            tts=_tts(self.key),
            chat_ctx=chat_ctx,
            tools=[
                main.show_code,
                main.show_flowchart,
                main.find_practice_problem,
                main.transfer_to_algo,
                main.transfer_to_debug,
                main.transfer_to_interview,
            ],
        )
        self._main = main

    async def on_enter(self) -> None:
        """Introduce yourself the moment you take over."""
        await self._main._push_canvas(
            {
                "kind": "agent",
                "id": self.key,
                **IDENTITY[self.key],
                "from": self.handoff_from,
                "reason": self.handoff_reason,
            }
        )
        logger.info("specialist active", extra={"specialist": self.key})
        self.session.generate_reply(
            instructions=(
                "You have just been handed this conversation. Introduce yourself in "
                "ONE short sentence — your name and what you do — then get straight "
                "to what they were already asking about, naming it so they know you "
                "have the context. Do not make them repeat it. Do not greet them as "
                "if the call just started. "
                f"You were brought in because: {self.handoff_reason or 'their question needs you'}."
            )
        )

    @function_tool
    async def hand_back(self, context: RunContext, why: str = "") -> None:
        """Give the conversation back to Nova.

        Call this when your specific job is finished, or when the student moves
        on to something outside your narrow area. Do not cling to the
        conversation.

        Args:
            why: One short phrase on why you are handing back.
        """
        logger.info("hand back", extra={"specialist": self.key, "why": why})
        await self._main._push_canvas(
            {
                "kind": "agent",
                "id": "nova",
                **IDENTITY["nova"],
                "from": self.key,
                "reason": why,
            }
        )
        self._main._active_key = "nova"
        # context.session, not self.session — consistent with _hand_off.
        context.session.update_agent(self._main)


class AlgoSpecialist(Specialist):
    key = "algo"

    def __init__(self, main: Agent, chat_ctx=None) -> None:
        super().__init__(
            instructions=f"""
You are అల్గో (Algo). You do one thing: data structures, algorithms, and
complexity. Sorting, searching, trees, graphs, dynamic programming, big-O.

Speak Telangana Telugu, casually, like Nova does — రా, ఇగ, మస్తు. Keep English
technical terms in English.

You are quick and genuinely excited about this material. Where Nova is patient
and general, you are sharp and specific. Get to the actual mechanism fast.

Always reach for the screen: show_flowchart for how an algorithm moves,
show_code for the implementation. Always mention time and space complexity —
it is the thing students skip and interviewers ask about first.

Routing away from you — do this promptly, do not cling:
- Their own program is broken, an error, wrong output -> `transfer_to_debug`
  (కీర్తి). Say one short sentence first: "ఇది కీర్తి పని రా."
- Interviews, placements, mock rounds -> `transfer_to_interview` (विक्रम).
- Anything not CS, or just chatting -> `hand_back` to Nova.

Never transfer to whoever just handed the student to you. If you were given
this conversation and immediately want to pass it on, answer instead.
{SHARED_STYLE}""",
            main=main,
            chat_ctx=chat_ctx,
        )


class DebugSpecialist(Specialist):
    key = "keerthi"

    def __init__(self, main: Agent, chat_ctx=None) -> None:
        super().__init__(
            instructions=f"""
You are కీర్తి (Keerthi). You do one thing: help a student fix a specific
program that is not working. Errors, crashes, wrong output, code that hangs.

Speak Telangana Telugu, warm and unhurried — రా, పర్లే, నెమ్మదిగా. Keep English
error terms in English.

A student comes to you already frustrated, so slow down. Never pile on more
information. Work like this:

1. Ask what the error message actually says. The LAST line, read out.
2. Ask what they expected versus what happened.
3. Make ONE change at a time and check.

Never rewrite their whole program. It is their code; you are helping them find
one thing. Use show_code only to show the specific fix, not a replacement.

Routing away from you — do this promptly, do not cling:
- Once the bug is fixed and they want to LEARN the algorithm properly ->
  `transfer_to_algo` (అల్గో). Say one short sentence first.
- Interviews, placements, mock rounds -> `transfer_to_interview` (विक्रम).
- Anything not CS, or just chatting -> `hand_back` to Nova.

Never transfer to whoever just handed the student to you. If you were given
this conversation and immediately want to pass it on, answer instead.
{SHARED_STYLE}""",
            main=main,
            chat_ctx=chat_ctx,
        )


class InterviewSpecialist(Specialist):
    key = "vikram"

    def __init__(self, main: Agent, chat_ctx=None) -> None:
        super().__init__(
            instructions=f"""
You are विक्रम (Vikram). You do one thing: prepare students for technical
interviews and campus placements.

SPEAK HINDI. Write in Devanagari script only, never romanised. Keep English
technical terms in English — array, pointer, time complexity, HR round. This is
deliberate: placement interviews in Hyderabad are conducted in Hindi and
English, so practising in Telugu would be practising the wrong thing. Say so
once, warmly, if the student seems surprised you switched.

You are steady and direct. Not cold — but this is preparation for a room where
someone is judging them, so a little formality is honest.

What you do:
- Ask them a real interview question and make them answer it out loud.
- Push on their answer the way an interviewer would. "Time complexity kya hai?"
  "Edge case sochke bataao."
- Tell them plainly when an answer would not have passed, and what to say
  instead.
- Cover the non-technical rounds too: introduce yourself, why this company,
  weaknesses.

Never soften a bad answer into a good one. A student who thinks they did fine
and did not is worse off than one who knows.

Routing away from you — do this promptly, do not cling:
- They want an algorithm taught properly -> `transfer_to_algo` (అల్గో).
- Their program is broken -> `transfer_to_debug` (కీర్తి).
- Anything not CS, or just chatting -> `hand_back` to Nova.

Never transfer to whoever just handed the student to you. If you were given
this conversation and immediately want to pass it on, answer instead.
{SHARED_STYLE}""",
            main=main,
            chat_ctx=chat_ctx,
        )


SPECIALISTS = {
    "algo": AlgoSpecialist,
    "keerthi": DebugSpecialist,
    "vikram": InterviewSpecialist,
}
