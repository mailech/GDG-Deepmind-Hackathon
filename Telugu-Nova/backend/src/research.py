"""Live research: the latest real-world facts on a concept, with sources.

Board lessons come from the model's own knowledge, which is months old. For
anything that moves — interest rates, drug guidelines, regulations, a new
model release — Nova calls this first. Gemini 3.8 Flash answers with Google
Search grounding, and each finding keeps the web source it came from, so the
student's research panel shows WHERE a claim comes from, not just the claim.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import date

from google import genai
from google.genai import types

logger = logging.getLogger("agent.research")

RESEARCH_MODELS = [
    os.getenv("RESEARCH_MODEL", "gemini-3.8-flash"),
    "gemini-3.7-flash",
    "gemini-3.5-flash",
]

PROMPT = """\
Today is {today}. Research this for a student, using Google Search:

{question}

Reply with 4 to 6 findings, most important first. Each finding is ONE line
starting with "- ", under 30 words, concrete (numbers, dates, names), and
current as of today. Prefer the latest developments and authoritative sources
(regulators, journals, official data). No intro, no conclusion — only the lines.
"""


class Researcher:
    def __init__(self) -> None:
        self._client = genai.Client(
            api_key=os.environ["GOOGLE_API_KEY"],
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )

    async def find(self, question: str) -> list[dict]:
        """[{point, source, url}], newest-and-most-important first."""
        last: Exception | None = None
        for model in RESEARCH_MODELS:
            try:
                resp = await asyncio.wait_for(
                    self._client.aio.models.generate_content(
                        model=model,
                        contents=PROMPT.format(
                            today=date.today().isoformat(), question=question
                        ),
                        config=types.GenerateContentConfig(
                            tools=[types.Tool(google_search=types.GoogleSearch())],
                            temperature=0.2,
                        ),
                    ),
                    timeout=25,
                )
                findings = _findings(resp)
                if findings:
                    logger.info(
                        "research done",
                        extra={"q": question, "model": model, "n": len(findings)},
                    )
                    return findings
                raise ValueError("no findings")
            except (genai.errors.APIError, ValueError, TimeoutError) as exc:
                last = exc
                logger.warning(
                    "research via %s failed: %s",
                    model,
                    str(exc)[:120] or type(exc).__name__,
                )
        raise RuntimeError(f"research failed: {last}")


def _findings(resp: types.GenerateContentResponse) -> list[dict]:
    text = resp.text or ""
    lines = [
        re.sub(r"^[-*•\d.)\s]+", "", ln).strip()
        for ln in text.splitlines()
        if ln.strip()
    ]
    lines = [ln.replace("**", "") for ln in lines if len(ln) > 12][:6]

    meta = resp.candidates[0].grounding_metadata if resp.candidates else None
    chunks = (meta.grounding_chunks or []) if meta else []
    supports = (meta.grounding_supports or []) if meta else []

    def source_for(line: str) -> tuple[str, str]:
        # The chunk that grounds the most of this line's text wins.
        for sup in supports:
            seg = (
                (sup.segment.text or "").replace("**", "").strip()
                if sup.segment
                else ""
            )
            if (
                seg
                and (seg[:40] in line or line[:40] in seg)
                and sup.grounding_chunk_indices
            ):
                web = chunks[sup.grounding_chunk_indices[0]].web
                if web:
                    return web.title or "", web.uri or ""
        return "", ""

    out = []
    for i, ln in enumerate(lines):
        title, url = source_for(ln)
        if not url and i < len(chunks) and chunks[i].web:  # fall back to source order
            title, url = chunks[i].web.title or "", chunks[i].web.uri or ""
        out.append({"point": ln, "source": title, "url": url})
    return out
