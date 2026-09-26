"""Day 6: Nova calls the student.

Use case for Learning & Literacy: the **daily practice call**. A student who
asked to be called gets a ring at the time they picked, and Nova opens with the
weak spot it remembered from Day 4 — "పోయిన సారి pointers దగ్గర ఆగిపోయినవ్ కదా".

Outbound is a different animal from inbound. Nobody asked for this call, nobody
knows who is ringing, and the phone may be answered by voicemail, a busy tone,
or someone who hangs up in two seconds. Every one of those has a defined
behaviour here.

Usage
-----
    uv run python src/outbound.py +919876543210
    uv run python src/outbound.py +919876543210 --student "Subhash"
    uv run python src/outbound.py +919876543210 --dry-run

Setup
-----
Needs a LiveKit SIP outbound trunk pointed at a telephony provider (Twilio).
Put the trunk id in .env.local as SIP_OUTBOUND_TRUNK_ID. See README.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import timedelta

from dotenv import load_dotenv
from livekit import api

load_dotenv(".env.local")

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("outbound")

AGENT_NAME = os.getenv("AGENT_NAME", "nova-te")
TRUNK_ID = os.getenv("SIP_OUTBOUND_TRUNK_ID", "")

# How long to let it ring before giving up. Long enough for someone to reach a
# phone in another room, short enough not to roll to voicemail every time.
# These are protobuf Durations — passing a bare int fails at serialisation.
RINGING_TIMEOUT = timedelta(seconds=30)

# A practice call has no business running longer than this.
MAX_CALL_DURATION = timedelta(minutes=10)


class CallOutcome:
    ANSWERED = "answered"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    REJECTED = "rejected"
    UNREACHABLE = "unreachable"
    FAILED = "failed"


# What to do about each ending. Retrying a rejected call is harassment; retrying
# a busy line is courtesy. The difference matters.
RETRY_POLICY: dict[str, dict[str, object]] = {
    CallOutcome.ANSWERED: {"retry": False, "why": "call connected"},
    CallOutcome.NO_ANSWER: {
        "retry": True,
        "after_minutes": 120,
        "max_attempts": 2,
        "why": "they may simply have been away from the phone",
    },
    CallOutcome.BUSY: {
        "retry": True,
        "after_minutes": 20,
        "max_attempts": 3,
        "why": "line was engaged; likely reachable shortly",
    },
    CallOutcome.REJECTED: {
        "retry": False,
        "why": "they actively declined — calling again is harassment",
    },
    CallOutcome.UNREACHABLE: {
        "retry": True,
        "after_minutes": 240,
        "max_attempts": 2,
        "why": "phone off or out of coverage",
    },
    CallOutcome.FAILED: {
        "retry": True,
        "after_minutes": 30,
        "max_attempts": 1,
        "why": "our side broke, not theirs",
    },
}


def classify(error: Exception) -> str:
    """Map a SIP failure onto an outcome we have a policy for.

    LiveKit surfaces the provider's SIP status text, so we read it rather than
    guessing from exception types.
    """
    text = str(error).lower()
    if "busy" in text or "486" in text:
        return CallOutcome.BUSY
    if "decline" in text or "reject" in text or "603" in text:
        return CallOutcome.REJECTED
    if "no answer" in text or "timeout" in text or "408" in text or "480" in text:
        return CallOutcome.NO_ANSWER
    if "not found" in text or "404" in text or "unavailable" in text:
        return CallOutcome.UNREACHABLE
    return CallOutcome.FAILED


async def place_call(
    phone: str,
    student: str | None = None,
    reason: str = "daily_practice",
    dry_run: bool = False,
) -> str:
    """Ring a number and put Nova on the line. Returns a CallOutcome."""
    room_name = f"nova-outbound-{uuid.uuid4().hex[:10]}"
    # The agent reads this to know it is an outbound call and who it rang.
    metadata = json.dumps(
        {"direction": "outbound", "student": student, "reason": reason, "phone": phone},
        ensure_ascii=False,
    )

    if dry_run:
        logger.info("DRY RUN — would call %s", phone)
        logger.info("  room     : %s", room_name)
        logger.info("  agent    : %s", AGENT_NAME)
        logger.info("  trunk    : %s", TRUNK_ID)
        logger.info("  metadata : %s", metadata)
        return CallOutcome.ANSWERED

    if not TRUNK_ID:
        logger.error(
            "SIP_OUTBOUND_TRUNK_ID is not set in .env.local.\n"
            "Create a LiveKit SIP outbound trunk pointed at your Twilio number first."
        )
        return CallOutcome.FAILED

    lk = api.LiveKitAPI()
    try:
        # 1. Put the agent in the room FIRST, so it is already listening when
        #    the callee says "hello". Dialling first means the first second of
        #    the call is dead air.
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME, room=room_name, metadata=metadata
            )
        )
        logger.info("agent dispatched to %s", room_name)

        # 2. Now ring the phone.
        logger.info("calling %s ...", phone)
        await lk.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                sip_trunk_id=TRUNK_ID,
                sip_call_to=phone,
                room_name=room_name,
                participant_identity=f"phone-{phone}",
                participant_name=student or "student",
                participant_metadata=metadata,
                # Block until they actually pick up, so the outcome we report is
                # the real one rather than "we dialled successfully".
                wait_until_answered=True,
                ringing_timeout=RINGING_TIMEOUT,
                max_call_duration=MAX_CALL_DURATION,
                play_dialtone=False,
                krisp_enabled=True,
            )
        )
        logger.info("ANSWERED — Nova is on the line")
        return CallOutcome.ANSWERED

    except Exception as exc:
        outcome = classify(exc)
        policy = RETRY_POLICY[outcome]
        logger.warning("outcome: %s (%s)", outcome.upper(), policy["why"])
        if policy["retry"]:
            logger.info(
                "  retry: yes, in %s min, max %s attempts",
                policy.get("after_minutes"),
                policy.get("max_attempts"),
            )
        else:
            logger.info("  retry: no")
        logger.debug("sip error: %s", exc)
        return outcome
    finally:
        await lk.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Nova calls a student.")
    parser.add_argument("phone", help="E.164 number, e.g. +919876543210")
    parser.add_argument("--student", help="Their name, so Nova can greet them by it")
    parser.add_argument(
        "--reason",
        default="daily_practice",
        choices=["daily_practice", "follow_up"],
        help="Why we are calling — shapes the opening line",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print, do not dial")
    args = parser.parse_args()

    if not args.phone.startswith("+"):
        logger.error("Number must be E.164 and start with + — e.g. +919876543210")
        sys.exit(1)

    outcome = asyncio.run(
        place_call(args.phone, args.student, args.reason, args.dry_run)
    )
    sys.exit(0 if outcome == CallOutcome.ANSWERED else 1)


if __name__ == "__main__":
    main()
