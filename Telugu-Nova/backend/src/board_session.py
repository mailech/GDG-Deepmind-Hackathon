"""Nova at the whiteboard: one Gemini Live session teaching on a shared board.

Pipeline (NOVA_PIPELINE=board, the default):

    student mic ──► Gemini 3.8 Live ──► Nova's voice
                        │  tool calls
                        ▼
                  Board (board.py) ──data channel──► browser whiteboard
                        ▲                                   │
                        └──── student marks (text stream) ◄─┘

Gemini Live hears the student directly, so barge-in is native and it can read
tone of voice, which a transcript throws away. Lessons are planned out-of-band
by Gemini 3.8 Flash (board.LessonPlanner) so the Live model never goes silent
composing a board.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

from google.genai import types
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RunContext,
    function_tool,
    llm,
    room_io,
)
from livekit.plugins import google, noise_cancellation

import analytics
import memory
from board import STUDENT_TOPIC, Board, LessonPlanner, describe_target
from board_prompts import (
    LANG_NAMES,
    build_board_greeting,
    build_board_prompt,
    build_resume_greeting,
)
from locale_map import LocaleProfile
from media import MediaMaker
from research import Researcher
from visuals import VisualDirector, clean_diagram

logger = logging.getLogger("agent.board_session")

LIVE_MODEL = os.getenv("LIVE_MODEL", "gemini-3.8-live")
LIVE_VOICE = os.getenv("LIVE_VOICE", "Puck")
# Affective dialog: off by default because gemini-3.8-live rejects the flag
# (1007 invalid argument, on both v1beta and v1alpha). The native-audio model
# still hears tone directly, and the prompt tells it to act on it.
AFFECTIVE = os.getenv("LIVE_AFFECTIVE", "0") == "1"


def _patch_realtime_audio() -> None:
    """gemini-3.8-live silently ignores audio sent as legacy `media` chunks,
    which is what livekit-plugins-google 1.4.5 sends — so the model never
    hears the student (verified: same clip, `media=` -> no reply, `audio=` ->
    reply). Re-route those chunks to the `audio` / `video` fields."""
    from google.genai import live

    orig = live.AsyncSession.send_realtime_input
    if getattr(orig, "_nova_patched", False):
        return

    async def send_realtime_input(self, *, media=None, **kw):
        if media is not None:
            mime = getattr(media, "mime_type", "") or ""
            if mime.startswith("audio/"):
                return await orig(self, audio=media, **kw)
            if mime.startswith("image/"):
                return await orig(self, video=media, **kw)
            return await orig(self, media=media, **kw)
        return await orig(self, **kw)

    send_realtime_input._nova_patched = True  # type: ignore[attr-defined]
    live.AsyncSession.send_realtime_input = send_realtime_input


_patch_realtime_audio()

MARK_CONTEXT_TTL_S = 30  # a mark still explains "ఇది" this long after it was drawn

# Fire-and-forget tasks must stay referenced, or the loop may drop them mid-run.
_background: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)


def _parse_pointers(spec: str, n: int) -> list[dict] | None:
    """'i=2, j=5' -> [{'name': 'i', 'index': 2}, ...]; out-of-range dropped."""
    if not spec.strip():
        return None
    out = []
    for part in spec.split(","):
        name, _, idx = part.partition("=")
        try:
            i = int(idx.strip())
        except ValueError:
            continue
        if name.strip() and 0 <= i < n:
            out.append({"name": name.strip(), "index": i})
    return out


# Who can hold the class. Every one of them teaches on the SAME board, with
# the same tools — only the voice, focus and manner change. A Live model's
# voice is fixed per session, so each gets its own RealtimeModel.
PERSONAS: dict[str, dict[str, str]] = {
    "nova": {
        "voice": LIVE_VOICE,
        "name": "Acharya",
        "role": "Computer Science",
        "tint": "#C4704F",
        "lang": "any",
    },
    "algo": {
        "voice": "Fenrir",
        "name": "Algo",
        "role": "DSA & algorithms",
        "tint": "#5B7FA6",
        "lang": "any",
    },
    "keerthi": {
        "voice": "Kore",
        "name": "Keerthi",
        "role": "debugging",
        "tint": "#6F9E82",
        "lang": "any",
    },
    "vikram": {
        "voice": "Charon",
        "name": "Vikram",
        "role": "interview prep",
        "tint": "#C89B4A",
        "lang": "Hindi",
    },
}


class Classroom:
    """State that outlives any one agent: the boards, the student, the stats."""

    def __init__(
        self, room: rtc.Room, profile: LocaleProfile, planner: LessonPlanner
    ) -> None:
        self.room = room
        self.profile = profile
        self.planner = planner
        self.board = Board(room)
        self.researcher = Researcher()
        self.media = MediaMaker(room)
        self.director = VisualDirector()
        self._research_n = 0
        self.student: str | None = None
        self.active = "nova"
        # Continuing a previous chat: the browser sends its history and board.
        self.resumed = asyncio.Event()
        self.resume_transcript = ""
        self.lang = "en"
        self.stats: dict[str, int] = {
            "concepts_taught": 0,
            "problems_given": 0,
            "escalations": 0,
            "turns": 0,
            "tool_errors": 0,
        }

    relay: MarkRelay | None = None

    def notify(self, text: str) -> None:
        """Queue a fact for the teacher, delivered when it is not mid-sentence."""
        if self.relay is not None:
            self.relay.hold(text)

    async def announce(self, key: str, came_from: str, reason: str) -> None:
        """Tell the browser who holds the class now, so the UI changes with the voice."""
        p = PERSONAS[key]
        payload = {
            "kind": "agent",
            "id": key,
            "name": p["name"],
            "role": p["role"],
            "tint": p["tint"],
            "lang": p["lang"],
            "from": came_from,
            "reason": reason,
        }
        await self.room.local_participant.publish_data(
            json.dumps(payload, ensure_ascii=False), reliable=True, topic="nova-canvas"
        )


class BoardTeacher(Agent):
    def __init__(
        self, cls: Classroom, key: str = "nova", chat_ctx: llm.ChatContext | None = None
    ) -> None:
        super().__init__(
            instructions=build_board_prompt(cls.profile, key),
            chat_ctx=chat_ctx,
            llm=build_live_model(PERSONAS[key]["voice"]),
        )
        self.cls = cls
        self.key = key
        self.board = cls.board
        self.planner = cls.planner
        self.handoff_reason = ""
        self.handoff_from = ""

    @property
    def _student(self) -> str | None:
        return self.cls.student

    @_student.setter
    def _student(self, name: str | None) -> None:
        self.cls.student = name

    @property
    def stats(self) -> dict[str, int]:
        return self.cls.stats

    async def on_enter(self) -> None:
        if not self.handoff_from:
            return  # the opening agent greets from run_board_session instead
        self.session.generate_reply(
            instructions=(
                f"You have just been handed this class by {PERSONAS[self.handoff_from]['name']} because: "
                f"{self.handoff_reason or 'their question needs you'}. Introduce yourself in ONE short "
                f"sentence, then carry on with exactly what they were doing, on the same board. "
                f"Do not greet as if the call just started. What is on the board right now:\n"
                f"{self.board.inventory()}"
            )
        )

    # --- handing the class to someone else --------------------------------

    async def _hand_to(self, context: RunContext, key: str, reason: str) -> str:
        if key == self.key:
            return "You already have the class. Carry on."
        nxt = BoardTeacher(
            self.cls, key, chat_ctx=self.chat_ctx.copy(exclude_instructions=True)
        )
        nxt.handoff_from = self.key
        nxt.handoff_reason = reason
        self.cls.active = key
        await self.cls.announce(key, self.key, reason)
        logger.info("handoff", extra={"from": self.key, "to": key, "why": reason})
        context.session.update_agent(nxt)
        return f"Handing over to {PERSONAS[key]['name']}. Say nothing more."

    @function_tool
    async def transfer_to_algo(self, context: RunContext, reason: str = "") -> str:
        """Hand the class to అల్గో, the data structures & algorithms specialist,
        for deep DSA, complexity analysis or tricky problem-solving. They keep
        the same board.

        Args:
            reason: One short phrase on why.
        """
        return await self._hand_to(context, "algo", reason)

    @function_tool
    async def transfer_to_debug(self, context: RunContext, reason: str = "") -> str:
        """Hand the class to కీర్తి, who helps fix the student's own broken code
        (errors, wrong output, crashes). Same board.

        Args:
            reason: One short phrase on why.
        """
        return await self._hand_to(context, "keerthi", reason)

    @function_tool
    async def transfer_to_interview(self, context: RunContext, reason: str = "") -> str:
        """Hand the class to विक्रम for interview and placement practice (he
        speaks Hindi). Same board.

        Args:
            reason: One short phrase on why.
        """
        return await self._hand_to(context, "vikram", reason)

    @function_tool
    async def hand_back_to_nova(self, context: RunContext, reason: str = "") -> str:
        """Give the class back to నోవా when your specific job is done or the
        student moves outside your area.

        Args:
            reason: One short phrase on why.
        """
        return await self._hand_to(context, "nova", reason)

    # --- pages -------------------------------------------------------------

    @function_tool
    async def new_board(self, context: RunContext, title: str) -> str:
        """Start a fresh, empty board page. The old boards are kept and the
        student can switch back to them. Use for a side-explanation you do not
        want mixed into the lesson, or when they ask for a new board.

        Args:
            title: Short name for the new board, e.g. "Recursion side-note".
        """
        await self.board.new_page(title)
        return f"New board '{title}' is open. Boards:\n{self.board.page_list()}"

    @function_tool
    async def open_board(self, context: RunContext, number: int) -> str:
        """Switch back to an earlier board page.

        Args:
            number: Board number as listed (1 is the first board).
        """
        if not 1 <= number <= len(self.board.pages):
            return f"No board {number}. Boards:\n{self.board.page_list()}"
        await self.board.open_page(self.board.pages[number - 1])
        return f"Board {number} is on screen.\n{self.board.inventory()}"

    # --- lessons -----------------------------------------------------------

    @function_tool
    async def teach(self, context: RunContext, topic: str, focus: str = "") -> str:
        """Start a whiteboard lesson. Call this as soon as the student wants to
        learn or understand a topic — do not ask clarifying questions first.

        The board is prepared in the background (a few seconds). This returns
        immediately so you can talk while it is drawn.

        Args:
            topic: The CS topic, e.g. "quicksort partition", "BST insertion",
                "how recursion uses the call stack".
            focus: Optional: the specific part they are stuck on, in their words.
        """
        if self.board.pending and not self.board.pending.done():
            self.board.pending.cancel()
        # A new topic gets a new page; the previous board stays one tab away.
        await self.board.new_page(topic)
        await self.board.publish({"op": "planning", "topic": topic})

        level = ""
        if self._student:
            record = await memory.recall(self._student)
            if record:
                facts = record["facts"]
                level = str(facts.get("level", ""))
                spots = facts.get("weak_spots") or []
                if spots and not focus:
                    focus = f"they previously struggled with: {spots[-1]}"

        self.board.pending = asyncio.create_task(self.planner.plan(topic, level, focus))
        logger.info("teach", extra={"topic": topic, "focus": focus})
        return (
            f"The board for '{topic}' is being prepared (a few seconds). Right now say "
            f"one or two short sentences to set it up — a hook, or why it matters. "
            f"Do not explain details yet. Then call show_step with step=1."
        )

    async def _lesson(self) -> dict | None:
        """The current lesson, waiting for the planner if it is still running."""
        if self.board.pending is not None:
            task = self.board.pending
            try:
                lesson = await asyncio.wait_for(asyncio.shield(task), timeout=40)
            except Exception:
                logger.exception("lesson planning failed")
                self.board.pending = None
                self.stats["tool_errors"] += 1
                return None
            self.board.pending = None
            await self.board.load_lesson(lesson)
        return self.board.lesson

    @function_tool
    async def show_step(self, context: RunContext, step: int) -> str:
        """Draw the next step of the current lesson on the board and learn
        what is on it. Explain it, check they follow, then show the next one.

        Args:
            step: Step number, starting at 1.
        """
        lesson = await self._lesson()
        if lesson is None:
            return (
                "The board could not be prepared. Tell the student in a few words, "
                "then teach it yourself using draw, highlight and write_note."
            )
        n = len(lesson["steps"])
        s = await self.board.reveal(step)
        if s is None:
            return f"There is no step {step}; this lesson has {n} steps (1 to {n})."
        self.stats["concepts_taught"] = max(self.stats["concepts_taught"], 1)

        items = []
        for el in s["elements"]:
            items.append(f"- {el['id']}: {describe_target(el, None)}")
            if el["kind"] == "code":
                items += [
                    f"    {el['id']}#{i}: {ln.strip()}"
                    for i, ln in enumerate(el["lines"])
                ]
            elif el["kind"] in ("array", "chain"):
                items.append(
                    "    cells: "
                    + ", ".join(
                        f"{el['id']}#{i}={v}" for i, v in enumerate(el["values"])
                    )
                )
                if el.get("pointers"):
                    items.append(
                        "    pointers: "
                        + ", ".join(f"{p['name']}={p['index']}" for p in el["pointers"])
                    )
            elif el["kind"] == "tree":
                items.append(
                    "    nodes: "
                    + ", ".join(
                        f"{el['id']}#{nd['id']}={nd['label']}" for nd in el["nodes"]
                    )
                )
        nxt = (
            f"When they are with you, call show_step({step + 1})."
            if step < n
            else "This is the last step: sum up in one sentence, then ask if they want to try a problem."
        )
        return (
            f"Step {step} of {n}, '{s['title']}', is being drawn now. On it:\n"
            + "\n".join(items)
            + f"\nThe point to get across: {s['say']}\n"
            + (f"Check question for after: {s['check']}\n" if s.get("check") else "")
            + "Explain it out loud now, pointing at the board and highlighting as you go. "
            + nxt
        )

    # --- live annotation ----------------------------------------------------

    @function_tool
    async def highlight(
        self, context: RunContext, target: str, color: str = "yellow"
    ) -> str:
        """Highlight something on the board while you talk about it.

        Args:
            target: e.g. "arr1#3", "code1#2", "tree1#n4", or a whole element "arr1".
            color: yellow (default), green, pink, blue or orange.
        """
        if self.board.describe(target) is None:
            return f"'{target}' is not on the board. Targets on the board:\n{self.board.inventory()}"
        await self.board.publish({"op": "highlight", "target": target, "color": color})
        return "Highlighted. Keep talking."

    @function_tool
    async def write_note(self, context: RunContext, text: str, near: str = "") -> str:
        """Write one short line in your handwriting on the board, next to what
        it explains. Use for the key idea after a doubt. Under 60 characters.

        Args:
            text: The note. English or Telugu.
            near: The target it explains, e.g. "code1#2". Optional.
        """
        el = {"id": self.board.new_id("note"), "kind": "note", "text": text[:90]}
        if near:
            el["target"] = near
        await self.board.add(el, after=near or None)
        return "Written on the board."

    @function_tool
    async def draw_arrow(
        self, context: RunContext, from_target: str, to_target: str, label: str = ""
    ) -> str:
        """Draw an arrow between two things on the board.

        Args:
            from_target: e.g. "arr1#0".
            to_target: e.g. "arr1#5".
            label: Optional short label on the arrow.
        """
        for t in (from_target, to_target):
            if self.board.describe(t) is None:
                return f"'{t}' is not on the board. Targets on the board:\n{self.board.inventory()}"
        await self.board.publish(
            {"op": "arrow", "from": from_target, "to": to_target, "label": label}
        )
        return "Arrow drawn."

    @function_tool
    async def update_array(
        self, context: RunContext, target: str, cells: str = "", pointers: str = ""
    ) -> str:
        """Change an array on the board as the algorithm runs — swap values,
        move pointers — so the student SEES each step you narrate.

        Args:
            target: The array element id, e.g. "arr1".
            cells: New values, comma-separated, e.g. "3,1,2,5". Empty = unchanged.
            pointers: New pointer positions, e.g. "i=2, j=4". Empty = unchanged.
        """
        found = self.board.split_target(target)
        if not found or found[0]["kind"] != "array":
            return f"'{target}' is not an array on the board. Targets:\n{self.board.inventory()}"
        el = found[0]
        values = [v.strip() for v in cells.split(",")] if cells.strip() else None
        n = len(values or el["values"])
        await self.board.update_array(el["id"], values, _parse_pointers(pointers, n))
        return "Updated on the board."

    @function_tool
    async def draw(
        self, context: RunContext, kind: str, content: str, label: str = ""
    ) -> str:
        """Draw something small on the board for a quick side-question,
        without starting a whole lesson.

        Args:
            kind: "text", "code", "array", "chain" (linked list) or "stack".
            content: text: the line. code: the code, lines separated by newlines.
                array/chain/stack: values separated by commas.
            label: Optional caption.
        """
        el_id = self.board.new_id(kind)
        k = kind.lower().strip()
        if k == "code":
            el = {
                "id": el_id,
                "kind": "code",
                "lines": content.split("\n")[:12],
                "label": label or None,
            }
        elif k in ("array", "chain", "stack", "linked list", "list", "queue"):
            vals = [v.strip() for v in content.split(",") if v.strip()][:10]
            el = {
                "id": el_id,
                "kind": "array" if k == "array" else "chain",
                "values": vals,
                "label": label or None,
                "vertical": k == "stack",
                "arrows": k != "stack",
            }
        else:
            el = {"id": el_id, "kind": "text", "text": content[:90]}
        el = {k2: v for k2, v in el.items() if v is not None}
        await self.board.add(el)
        return f"Drawn as '{el_id}'. Its parts can be highlighted as {el_id}#0, {el_id}#1, ..."

    @function_tool
    async def clear_board(self, context: RunContext) -> str:
        """Wipe the board when moving to a completely different topic."""
        await self.board.clear()
        return "Board cleared."

    # --- generated visuals -------------------------------------------------

    async def _make_media(self, kind: str, description: str, caption: str) -> str:
        el_id = self.board.new_id(kind)
        await self.board.add(
            {
                "id": el_id,
                "kind": "media",
                "media": "video" if kind == "video" else "image",
                "caption": caption[:80],
                "label": caption[:80],
            }
        )
        board, media, cls = self.board, self.cls.media, self.cls

        async def work() -> None:
            try:
                source = ""
                if kind == "photo":
                    data, mime, source = await media.photo(description)
                elif kind == "image":
                    try:
                        data, mime = await media.image(description)
                    except Exception:
                        # Image models refuse real people and famous places; a
                        # real photo of the caption is the next best thing.
                        data, mime, source = await media.photo(caption)
                else:
                    data, mime = await media.video(description)
                await media.send(el_id, data, mime, source)
                cls.notify(
                    f"[BOARD] The {kind} '{caption}' ({el_id}) is now visible on the student's "
                    f"board. You may refer to it now."
                )
                logger.info(
                    "media ready",
                    extra={"id": el_id, "kind": kind, "kb": len(data) // 1024},
                )
            except Exception:
                logger.exception("media generation failed")
                await board.publish({"op": "media_fail", "id": el_id})
                cls.notify(
                    f"[BOARD] The {kind} '{caption}' could NOT be generated. Tell the student "
                    f"plainly and explain without it; do not describe it as if it exists."
                )

        _spawn(work())
        return el_id

    @function_tool
    async def show_image(
        self, context: RunContext, description: str, caption: str
    ) -> str:
        """Generate an infographic or illustration (Nano Banana) and put it on
        the board. Use when a picture beats a sketch: anatomy, geography,
        a device, a labelled chart, a real-world scene. Ready in ~5 seconds;
        keep talking while it appears.

        Args:
            description: What to draw, specifically, with the labels it needs.
            caption: Short caption under the image, e.g. "How the heart pumps".
        """
        el_id = await self._make_media("image", description, caption)
        return f"The image '{caption}' ({el_id}) is being generated and will appear on the board in a few seconds. Keep explaining; refer to it once it is there."

    @function_tool
    async def show_photo(self, context: RunContext, query: str, caption: str) -> str:
        """Put a REAL photo on the board, from Wikipedia: a real person,
        place, landmark, building, historical event, artwork, organism or
        product. Use this instead of show_image for anything real and named —
        never generate a picture of a real person.

        Args:
            query: What to look up, e.g. "Narendra Modi", "Charminar", "Taj Mahal".
            caption: Short caption, e.g. "Prime Minister Narendra Modi".
        """
        el_id = await self._make_media("photo", query, caption)
        return f"A real photo for '{query}' ({el_id}) is being fetched and will appear in a few seconds. Keep talking."

    @function_tool
    async def mark_on_image(
        self, context: RunContext, image: str, instruction: str
    ) -> str:
        """Draw ON an image you generated: circle, arrow, label or highlight a
        part of it — e.g. "circle the left ventricle and label it", "draw an
        arrow along the path of the blood". Replaces the image with the marked
        version in ~5 seconds. Use it whenever the student asks you to point
        something out in a picture, or when pointing at part of it helps.

        Args:
            image: The image element id, e.g. "xima1" (from show_image).
            instruction: Exactly what to mark, and where.
        """
        el_id = image.split("#")[0].strip()
        stored = self.cls.media.store.get(el_id)
        if stored is None:
            ready = list(self.cls.media.store)
            return f"No finished image called '{el_id}'. Images you can mark: {ready or 'none yet'}."
        await self.board.publish({"op": "point", "target": el_id})
        media, cls = self.cls.media, self.cls

        async def work() -> None:
            try:
                data, mime = await media.edit(*stored, instruction)
                await media.send(el_id, data, mime)
                cls.notify(
                    f"[BOARD] The marked-up image {el_id} is now on the board ({instruction})."
                )
            except Exception:
                logger.exception("image edit failed")
                cls.notify(
                    f"[BOARD] Marking image {el_id} FAILED. Say so; point to it in words instead."
                )

        _spawn(work())
        return "Marking it on the image now (a few seconds). Talk them through that part meanwhile."

    @function_tool
    async def show_video(
        self, context: RunContext, description: str, caption: str
    ) -> str:
        """Generate a short animated clip (~8s) and put it on the board. Use
        for motion that a still cannot show: a process over time, a physical
        phenomenon. It takes about a minute — call it early, keep teaching,
        and mention the clip when it appears.

        Args:
            description: The animation to make, concretely.
            caption: Short caption, e.g. "Water cycle in motion".
        """
        el_id = await self._make_media("video", description, caption)
        return f"The clip '{caption}' ({el_id}) is being made; it takes about a minute. Carry on teaching meanwhile."

    @function_tool
    async def draw_diagram(
        self,
        context: RunContext,
        nodes: str,
        edges: str = "",
        cycle: bool = False,
        label: str = "",
    ) -> str:
        """Draw a concept map, system or process diagram right now — boxes and
        labelled arrows. For any subject: how money flows, how a disease
        spreads, how a request reaches a server.

        Args:
            nodes: Box labels separated by ";", e.g. "RBI; Banks; Home loan rate; EMI".
            edges: Arrows separated by ";" as "A -> B : label", e.g.
                "RBI -> Banks : repo rate; Banks -> Home loan rate". Empty = chain in order.
            cycle: True to arrange the boxes in a loop (a cycle).
            label: Optional caption.
        """
        names = [n.strip() for n in nodes.split(";") if n.strip()][:8]
        if not names:
            return "Give at least one node."
        ids = {n.lower(): f"n{i}" for i, n in enumerate(names)}
        out_edges = []
        for part in [e for e in edges.split(";") if "->" in e]:
            lhs, _, rhs = part.partition("->")
            to, _, lab = rhs.partition(":")
            a, b = ids.get(lhs.strip().lower()), ids.get(to.strip().lower())
            if a and b and a != b:
                out_edges.append({"from": a, "to": b, "label": lab.strip()})
        if not out_edges:
            out_edges = [
                {"from": f"n{i}", "to": f"n{i + 1}", "label": ""}
                for i in range(len(names) - 1)
            ]
            if cycle and len(names) > 2:
                out_edges.append(
                    {"from": f"n{len(names) - 1}", "to": "n0", "label": ""}
                )
        el_id = self.board.new_id("diagram")
        el = {
            "id": el_id,
            "kind": "diagram",
            "layout": "cycle" if cycle else "flow",
            "nodes": [{"id": f"n{i}", "label": n} for i, n in enumerate(names)],
            "edges": out_edges,
        }
        if label:
            el["label"] = label
        await self.board.add(el)
        return f"Diagram drawn as {el_id}. Boxes can be highlighted as " + ", ".join(
            f"{el_id}#n{i}={n}" for i, n in enumerate(names)
        )

    # --- live research ---------------------------------------------------------

    @function_tool
    async def research(self, context: RunContext, question: str) -> str:
        """Look up the LATEST real-world information, with sources, shown to the
        student in the research panel. Use it for anything that changes over
        time or where being current matters: finance (rates, markets, tax
        rules), health (guidelines, treatments, studies), law and policy,
        science news, recent technology, prices, statistics. Before calling,
        say one short line like "ఒక్క నిమిషం, latest ఏముందో చూస్తా". Takes ~10s.

        Args:
            question: A specific search question, e.g. "latest RBI repo rate and
                effect on home loan EMIs".
        """
        cls = self.cls
        cls._research_n += 1
        rid = f"r{cls._research_n}"
        await self.board.publish({"op": "research_start", "id": rid, "query": question})
        try:
            findings = await cls.researcher.find(question)
        except Exception:
            logger.exception("research failed")
            await self.board.publish(
                {"op": "research_fail", "id": rid, "query": question}
            )
            return "Research did not come back. Say so plainly and answer from what you know, marking it as possibly out of date."
        await self.board.publish(
            {"op": "research", "id": rid, "query": question, "findings": findings}
        )
        lines = "\n".join(
            f"- {f['point']} (source: {f['source'] or 'web'})" for f in findings
        )
        return (
            f"Findings, now listed in the research panel on the student's screen:\n{lines}\n"
            f"Tell them the one or two that matter most, in your own words, mentioning where "
            f"it comes from. If it is a concept worth seeing, call teach next with the key "
            f"finding as the focus."
        )

    # --- memory ---------------------------------------------------------------

    @function_tool
    async def recall_student(self, context: RunContext, name: str) -> str:
        """Look up whether you have taught this student before. Call as soon as
        they tell you their name.

        Args:
            name: The name they gave, as you heard it.
        """
        record = await memory.recall(name)
        if record is None:
            return f"No record for {name}. First meeting — do not pretend to remember anything."
        self._student = record["name"]
        return (
            f"You have taught {record['name']} before. Last time: {record['last_interaction']}. "
            f"Known: {json.dumps(record['facts'], ensure_ascii=False)}. Welcome them back and "
            f"mention one specific thing — ideally what they found hard."
        )

    @function_tool
    async def remember_student(
        self,
        context: RunContext,
        name: str,
        topic_covered: str = "",
        weak_spot: str = "",
        level: str = "",
    ) -> str:
        """Save what you learned about this student. ONLY after they agreed.

        Args:
            name: Their name.
            topic_covered: A topic you got through today.
            weak_spot: The exact thing they got stuck on — the most useful fact.
            level: How far along they are, e.g. "2nd year CSE".
        """
        existing = await memory.recall(name)
        prior = existing["facts"] if existing else {}
        facts: dict[str, object] = {}
        if level:
            facts["level"] = level
        for key, value in (
            ("topics_covered", topic_covered),
            ("weak_spots", weak_spot),
        ):
            if value:
                cur = list(prior.get(key, []) or [])
                if value not in cur:
                    cur.append(value)
                facts[key] = cur
        if not facts:
            return "Nothing to save."
        await memory.remember(name, facts, None)
        self._student = name
        return "Saved. Say briefly that you will remember, then carry on."


# ---------------------------------------------------------------------------
# Student marks
# ---------------------------------------------------------------------------

SHAPE_VERB = {"circle": "circled", "underline": "underlined", "scribble": "marked"}


class MarkRelay:
    """Carries what the student does on the board into the Live conversation.

    An "ask" mark (they tapped "ఇది అర్థం కాలేదు") interrupts whoever is
    teaching at once. A plain mark is only context — what "ఇది" means — and is
    held until the student starts talking, because injecting content mid-reply
    would cut the teacher off for a doodle. Tab switches move the agents'
    attention to the page the student is looking at.
    """

    def __init__(self, session: AgentSession, cls: Classroom) -> None:
        self.session = session
        self.cls = cls
        self._held: list[tuple[float, str, str | None]] = []

    @property
    def teacher(self) -> BoardTeacher | None:
        agent = self.session.current_agent
        return agent if isinstance(agent, BoardTeacher) else None

    def _describe(self, mark: dict) -> str:
        board = self.cls.board
        parts = []
        for t in mark.get("targets") or []:
            desc = board.describe(t.get("target", ""))
            text = t.get("text", "")
            if desc and "% from the left" in text:
                desc += (
                    " —" + text.split("—", 1)[-1]
                )  # where on the picture they marked
            parts.append(desc or f"'{text}'")
        verb = SHAPE_VERB.get(mark.get("shape", ""), "marked")
        where = f" on board '{board.current.title}'"
        if not parts:
            return f"The student {verb} an empty part{where} — look at the picture for what they drew."
        return f"The student {verb}{where}: " + "; ".join(parts) + "."

    async def _inject(self, text: str, image: str | None) -> None:
        teacher = self.teacher
        if teacher is None:
            return
        content: list = [text]
        if image and image.startswith("data:image/"):
            content.append(llm.ImageContent(image=image))
        ctx = teacher.chat_ctx.copy()
        ctx.add_message(role="user", content=content)
        await teacher.update_chat_ctx(ctx)

    async def _follow_page(self, msg: dict) -> None:
        """Point the agents at whichever page the student has on screen."""
        board = self.cls.board
        page_id = msg.get("board")
        if not page_id:
            return
        page = board.find(page_id)
        if page is None and msg.get("type") == "board_new":
            page = await board.new_page(
                msg.get("title") or "", page_id=page_id, announce=False
            )
        if page is not None and page is not board.current:
            await board.open_page(page, announce=False)

    async def handle(self, reader: rtc.TextStreamReader, participant: str) -> None:
        try:
            msg = json.loads(await reader.read_all())
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("unreadable board message")
            return
        kind = msg.get("type")
        if kind == "resume":
            if msg.get("book"):
                self.cls.board.restore(msg["book"])
            self.cls.resume_transcript = str(msg.get("transcript") or "")[-6000:]
            self.cls.resumed.set()
            logger.info("chat resumed", extra={"pages": len(self.cls.board.pages)})
            return
        if kind == "language":
            code = str(msg.get("lang", "en"))
            if code != self.cls.lang and code in LANG_NAMES:
                self.cls.lang = code
                name = LANG_NAMES[code]
                self.session.generate_reply(
                    instructions=(
                        f"[SETTINGS] The student just switched the app language to {name}. "
                        f"From now on speak {name}. Say one short sentence in {name} to show "
                        f"you switched, then carry on exactly where you were."
                    )
                )
            return
        await self._follow_page(msg)

        if kind in ("board_open", "board_new"):
            board = self.cls.board
            note = (
                f"[BOARD] The student opened a new blank board '{board.current.title}'."
                if kind == "board_new"
                else f"[BOARD] The student switched to board '{board.current.title}'.\n{board.inventory()}"
            )
            self.hold(note)
            return
        if kind != "mark":
            return

        what = self._describe(msg)
        image = msg.get("image")
        logger.info("board mark", extra={"ask": msg.get("ask"), "what": what[:160]})

        if msg.get("ask"):
            self.session.interrupt()
            await self._inject(
                f"[BOARD] {what} They tapped 'I do not get this'. "
                f"Explain exactly that part now. The lesson on this board is at step "
                f"{self.cls.board.revealed}.",
                image,
            )
            self.session.generate_reply()
            return

        self.hold(f"[BOARD] {what} (context for what they say next)", image)

    def hold(self, text: str, image: str | None = None) -> None:
        self._held.append((time.monotonic(), text, image))
        if self.session.agent_state == "listening":
            _spawn(self.flush())

    async def flush(self) -> None:
        held, self._held = self._held, []
        for t, text, image in held:
            if time.monotonic() - t < MARK_CONTEXT_TTL_S * 4:
                await self._inject(text, image)


# ---------------------------------------------------------------------------


def build_live_model(voice: str = LIVE_VOICE) -> google.realtime.RealtimeModel:
    kwargs: dict = {}
    if AFFECTIVE:
        kwargs["enable_affective_dialog"] = True
    return google.realtime.RealtimeModel(
        model=LIVE_MODEL,
        api_key=os.environ["GOOGLE_API_KEY"],
        voice=voice,
        temperature=0.4,
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        **kwargs,
    )


async def run_board_session(
    ctx: JobContext, profile: LocaleProfile, planner: LessonPlanner
) -> None:
    try:
        await memory.init()
    except Exception:
        logger.exception("memory unavailable — continuing without it")

    # Warm the planner while Nova greets, so the first lesson skips TLS setup.
    _spawn(planner.warm())

    cls = Classroom(ctx.room, profile, planner)
    teacher = BoardTeacher(cls, "nova")
    session = AgentSession()  # each teacher brings its own Live model (voice)
    relay = MarkRelay(session, cls)
    cls.relay = relay

    ctx.room.register_text_stream_handler(
        STUDENT_TOPIC,
        lambda reader, identity: _spawn(relay.handle(reader, identity)),
    )

    @session.on("user_state_changed")
    def _on_user_state(ev) -> None:
        if ev.new_state == "speaking":
            cls.stats["turns"] += 1
            # They are talking now; this is the moment "ఇది" needs its referent.
            _spawn(relay.flush())

    # --- Visual Director: a diagram for every question, pictures unasked ------
    heard = {"text": "", "done": ""}

    @session.on("user_input_transcribed")
    def _on_heard(ev) -> None:
        if ev.transcript:
            heard["text"] = ev.transcript

    async def direct(question: str) -> None:
        pending_before = cls.board.pending
        page_before = cls.board.current
        kinds_before = [
            e.get("media") or e["kind"] for e in cls.board.elements.values()
        ]
        await asyncio.sleep(2.5)  # let the teacher decide first
        teacher_now = session.current_agent
        if not isinstance(teacher_now, BoardTeacher):
            return
        plan = await cls.director.direct(question, cls.board.inventory())
        if not plan or plan.get("skip"):
            return
        # Never duplicate what the teacher already put up for this question: a
        # lesson it started carries its own diagrams, and a diagram or picture
        # it drew itself in the meantime covers that slot.
        lesson_started = (
            cls.board.pending is not None and cls.board.pending is not pending_before
        ) or cls.board.current is not page_before
        kinds_now = [e.get("media") or e["kind"] for e in cls.board.elements.values()]
        drew_diagram = kinds_now.count("diagram") > kinds_before.count("diagram")
        drew_image = kinds_now.count("image") > kinds_before.count("image")
        drew_video = kinds_now.count("video") > kinds_before.count("video")
        diagram = (
            None
            if (lesson_started or drew_diagram)
            else clean_diagram(plan.get("diagram"))
        )
        if diagram:
            diagram["id"] = cls.board.new_id("diagram")
            await cls.board.add(diagram)
            refs = ", ".join(
                f"{diagram['id']}#{n['id']}={n['label']}" for n in diagram["nodes"]
            )
            cls.notify(
                f"[BOARD] A {diagram['layout']} diagram '{diagram['label']}' is now on the board for "
                f"this question. Walk through it and highlight parts as you explain: {refs}"
            )
            logger.info(
                "director diagram",
                extra={"layout": diagram["layout"], "q": question[:80]},
            )
        if plan.get("image_prompt") and not drew_image and cls.director.image_allowed():
            cls.director.used_image()
            await teacher_now._make_media(
                "image",
                plan["image_prompt"],
                plan.get("image_caption") or "Illustration",
            )
        if plan.get("photo_query") and not drew_image and cls.director.image_allowed():
            cls.director.used_image()
            await teacher_now._make_media(
                "photo",
                plan["photo_query"],
                plan.get("photo_caption") or plan["photo_query"],
            )
        if plan.get("video_prompt") and not drew_video and cls.director.video_allowed():
            cls.director.used_video()
            await teacher_now._make_media(
                "video", plan["video_prompt"], plan.get("video_caption") or "Animation"
            )

    @session.on("agent_state_changed")
    def _on_agent_state(ev) -> None:
        if ev.new_state == "listening":
            _spawn(relay.flush())
        # The student's turn just ended: direct the visuals for what they asked.
        if ev.new_state in ("thinking", "speaking"):
            q = heard["text"].strip()
            # "okay", "continue", "next step" carry no new idea to draw; any
            # question of three words or more ("Narendra Modi evaru") does.
            filler = re.fullmatch(
                r"(ok(ay)?|continue|go on|next( step)?|yes|no|hmm+|sare|avunu|haan|theek hai)[\s.,!?]*",
                q.lower(),
            )
            if len(q.split()) >= 3 and not filler and q != heard["done"]:
                heard["done"] = q
                _spawn(direct(q))

    call_started = datetime.now(timezone.utc)
    channel = "phone" if ctx.room.name.startswith("nova-outbound-") else "browser"
    try:
        await analytics.start_call(ctx.room.name, channel, profile.language)
    except Exception:
        logger.exception("could not open analytics row — call still proceeds")

    async def close_out() -> None:
        try:
            result = await analytics.finish_call(
                ctx.room.name, cls.student, cls.stats, call_started
            )
            logger.info("call outcome", extra=result)
        except Exception:
            logger.exception("could not close analytics row")

    ctx.add_shutdown_callback(close_out)

    await session.start(
        agent=teacher,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            text_output=room_io.TextOutputOptions(sync_transcription=True),
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=noise_cancellation.BVC()
            ),
        ),
    )
    await ctx.connect()
    student = None
    try:
        student = await asyncio.wait_for(ctx.wait_for_participant(), timeout=10)
        lang = student.attributes.get("language", "en")
        cls.lang = lang if lang in LANG_NAMES else "en"
    except TimeoutError:
        pass
    resuming = False
    if student is not None:
        resuming = student.attributes.get("resume") == "1"
    if resuming:
        # Wait for the browser to hand over the old conversation and board.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(cls.resumed.wait(), timeout=12)
    if resuming and cls.resume_transcript:
        blank = not any(p.elements for p in cls.board.pages)
        await session.generate_reply(
            instructions=build_resume_greeting(
                cls.lang, cls.resume_transcript, cls.board.inventory(), blank
            )
        )
        if blank:
            # A chat from before boards were saved: redraw the last idea so the
            # student does not come back to an empty board.
            asked = [
                ln.split(":", 1)[1].strip()
                for ln in cls.resume_transcript.splitlines()
                if ln.startswith("Student:") and len(ln.split()) >= 4
            ]
            if asked:
                _spawn(direct(asked[-1]))
    else:
        await session.generate_reply(
            instructions=build_board_greeting(profile, cls.lang)
        )
