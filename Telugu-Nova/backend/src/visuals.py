"""The Visual Director: a diagram for every question, pictures without asking.

The Live teacher is busy talking; left to itself it draws when it remembers.
So every time the student finishes a question, this second agent (Gemini 3.8
Flash) looks at the question and the board, and DECIDES the visuals itself:

  - always a diagram, in the form that fits the subject — a stacked-layers
    picture for the OSI model, a cycle for the water cycle, a timeline for
    history, a hub for "types of", a comparison for "X vs Y";
  - an illustration (Nano Banana) when the thing is physical or visual;
  - a short clip (Veo) only when motion is the point, and sparingly.

The teacher is told what appeared, so it can point at it while explaining.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from google import genai
from google.genai import types

logger = logging.getLogger("agent.visuals")

DIRECTOR_MODELS = [
    os.getenv("DIRECTOR_MODEL", "gemini-3.8-flash"),
    "gemini-3.7-flash",
    "gemini-3.5-flash",
]

LAYOUTS = ["flow", "cycle", "hub", "timeline", "layers", "compare"]
COLORS = ["blue", "green", "orange", "pink", "purple", "yellow", "gray"]

_S = types.Schema
_STR = _S(type="STRING")

DIAGRAM_SCHEMA = _S(
    type="OBJECT",
    properties={
        "title": _S(type="STRING", description="Short title, under 40 characters."),
        "layout": _S(type="STRING", enum=LAYOUTS),
        "nodes": _S(
            type="ARRAY",
            description="3 to 8 nodes.",
            items=_S(
                type="OBJECT",
                properties={
                    "id": _STR,
                    "label": _S(type="STRING", description="Under 22 characters."),
                    "icon": _S(
                        type="STRING",
                        description="ONE emoji that makes this node recognisable at a glance.",
                    ),
                    "note": _S(
                        type="STRING",
                        description="Optional detail under 40 chars: a date, a number, a function.",
                    ),
                    "color": _S(type="STRING", enum=COLORS),
                    "group": _S(
                        type="STRING",
                        description="layout=compare only: which side, e.g. 'TCP' or 'UDP'.",
                    ),
                },
                required=["id", "label", "icon", "color"],
            ),
        ),
        "edges": _S(
            type="ARRAY",
            items=_S(
                type="OBJECT",
                properties={
                    "from": _STR,
                    "to": _STR,
                    "label": _S(
                        type="STRING", description="Under 16 characters, or empty."
                    ),
                },
                required=["from", "to"],
            ),
        ),
    },
    required=["title", "layout", "nodes"],
)

DIRECTOR_SCHEMA = _S(
    type="OBJECT",
    properties={
        "skip": _S(
            type="BOOLEAN",
            description=(
                "True for greetings, thanks, yes/no, small talk, and continuations like "
                "'okay continue', 'next', 'go on' — nothing new to show."
            ),
        ),
        "diagram": DIAGRAM_SCHEMA,
        "image_prompt": _S(
            type="STRING",
            description="Empty unless a real illustration helps (anatomy, geography, devices, scenes, labelled real objects). Otherwise a precise prompt for an educational infographic.",
        ),
        "image_caption": _STR,
        "photo_query": _S(
            type="STRING",
            description=(
                "For a REAL named person, place, landmark, building, event, artwork or "
                "organisation: a Wikipedia search for its real photo, e.g. 'Narendra Modi'. "
                "Use this INSTEAD of image_prompt for real, named things."
            ),
        ),
        "photo_caption": _STR,
        "video_prompt": _S(
            type="STRING",
            description="Empty unless MOTION is the essence (a process over time, a physical phenomenon, a mechanism moving). A precise prompt for an 8-second educational animation.",
        ),
        "video_caption": _STR,
    },
    required=["skip"],
)

PROMPT = """\
You are the visual director for a live teacher. The student just said:

"{question}"

What is already on the board:
{board}

Design the visuals for THIS question. Rules:
- Unless it is pure small talk, ALWAYS design a diagram — every real question
  gets one. Make it specific to the subject and instantly recognisable:
    layers   — stacked levels: OSI/TCP-IP model, atmosphere, org hierarchy,
               software stack, food pyramid (first node = top layer)
    cycle    — anything that loops: water cycle, heart beat, business cycle
    timeline — history, versions, stages of life, a process with dates
    hub      — "types of", "parts of", "features of": centre node first,
               the rest around it
    compare  — "X vs Y": give every node a group (exactly two groups)
    flow     — processes, systems, cause -> effect, data/money/blood flow
- Every node gets a fitting emoji icon and a colour; use colour to group
  related nodes. Use notes for the one number or fact that matters.
- Edges carry short labels only where they add meaning. Every edge must use
  node ids that exist. No duplicate nodes. Nothing already on the board.
- photo_query: for real, named people, places, landmarks and events, fetch
  the REAL photo instead of generating one. Never put a real person in
  image_prompt.
- image_prompt: fill it whenever a picture of the real thing would help a
  student remember it — most science, medicine, geography, engineering and
  real-world topics. Leave it empty for abstract or purely numeric topics.
- video_prompt: only when motion is the whole point. {video_rule}
- All text in English. Be accurate — no invented facts.
"""


class VisualDirector:
    def __init__(self) -> None:
        self._client = genai.Client(
            api_key=os.environ["GOOGLE_API_KEY"],
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )
        self._last_video = 0.0
        self._last_image = 0.0

    def video_allowed(self) -> bool:
        return time.monotonic() - self._last_video > 150  # clips are slow and costly

    def used_video(self) -> None:
        self._last_video = time.monotonic()

    def image_allowed(self) -> bool:
        return (
            time.monotonic() - self._last_image > 40
        )  # one picture per idea, not per sentence

    def used_image(self) -> None:
        self._last_image = time.monotonic()

    async def direct(self, question: str, board: str) -> dict | None:
        rule = (
            "At most one clip every few minutes; one is allowed now."
            if self.video_allowed()
            else "A clip was made very recently, so leave video_prompt empty."
        )
        prompt = PROMPT.format(question=question, board=board, video_rule=rule)
        for model in DIRECTOR_MODELS:
            try:
                resp = await asyncio.wait_for(
                    self._client.aio.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=DIRECTOR_SCHEMA,
                            temperature=0.5,
                            thinking_config=types.ThinkingConfig(thinking_level="low"),
                        ),
                    ),
                    timeout=15,
                )
                return json.loads(resp.text or "{}")
            except Exception as exc:
                logger.warning("director via %s failed: %s", model, str(exc)[:120])
        return None


def clean_diagram(d: dict | None) -> dict | None:
    """Validate a director/planner diagram into the board's element shape."""
    if not d:
        return None
    nodes = []
    seen: set[str] = set()
    for n in d.get("nodes") or []:
        nid, label = str(n.get("id") or "").strip(), str(n.get("label") or "").strip()
        if not nid or not label or nid in seen:
            continue
        seen.add(nid)
        node = {"id": nid, "label": label[:28]}
        for f in ("icon", "note", "color", "group"):
            if n.get(f):
                node[f] = str(n[f])[:44]
        nodes.append(node)
    nodes = nodes[:8]
    if len(nodes) < 2:
        return None
    ids = {n["id"] for n in nodes}
    edges = [
        {
            "from": str(e["from"]),
            "to": str(e["to"]),
            "label": str(e.get("label") or "")[:18],
        }
        for e in d.get("edges") or []
        if e.get("from") in ids and e.get("to") in ids and e.get("from") != e.get("to")
    ]
    layout = d.get("layout") if d.get("layout") in LAYOUTS else "flow"
    return {
        "kind": "diagram",
        "layout": layout,
        "nodes": nodes,
        "edges": edges,
        "label": str(d.get("title") or "")[:48],
    }
