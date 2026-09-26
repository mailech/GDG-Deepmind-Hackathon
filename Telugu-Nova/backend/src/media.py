"""Generated visuals for the board: infographics (Nano Banana) and short clips.

The board is Nova's handwriting; some things are better SHOWN — the anatomy of
a heart, the water cycle in motion, a market chart with annotations. These
are generated in the background while Nova keeps talking, then streamed to
the browser over a LiveKit byte stream (topic "nova-media") and dropped onto
the board where the placeholder was.

Images: Nano Banana 2 Lite (gemini-3.1-flash-lite-image), ~4s.
Video:  Veo 3.1 Fast, ~1 min. Gemini Omni (gemini-omni-1.1-flash) is the
        intended video model, but it only accepts the Interactions API from
        google-genai >= 2.0, and livekit-plugins-google 1.4.5 is built on 1.x.
"""

from __future__ import annotations

import asyncio
import logging
import os

from google import genai
from google.genai import types
from livekit import rtc

logger = logging.getLogger("agent.media")

MEDIA_TOPIC = "nova-media"
IMAGE_MODELS = ["gemini-3.1-flash-lite-image", "gemini-3.1-flash-image"]
VIDEO_MODEL = os.getenv("VIDEO_MODEL", "veo-3.1-fast-generate-preview")

IMAGE_STYLE = (
    "Clean educational infographic for a student. White background, clear "
    "labels in English, simple flat illustration, high contrast, no watermark. "
)


class MediaMaker:
    def __init__(self, room: rtc.Room) -> None:
        self._room = room
        self._client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        # Every generated image, so it can be edited (annotated) later.
        self.store: dict[str, tuple[bytes, str]] = {}

    async def image(self, prompt: str) -> tuple[bytes, str]:
        last: Exception | None = None
        for model in IMAGE_MODELS:
            try:
                r = await asyncio.wait_for(
                    self._client.aio.models.generate_content(
                        model=model,
                        contents=IMAGE_STYLE + prompt,
                        config=types.GenerateContentConfig(
                            response_modalities=["IMAGE"]
                        ),
                    ),
                    timeout=40,
                )
                for part in r.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.data:
                        return (
                            part.inline_data.data,
                            part.inline_data.mime_type or "image/jpeg",
                        )
                raise ValueError("no image returned")
            except Exception as exc:
                last = exc
                logger.warning("image via %s failed: %s", model, str(exc)[:120])
        raise RuntimeError(f"image failed: {last}")

    async def edit(self, data: bytes, mime: str, instruction: str) -> tuple[bytes, str]:
        """Nano Banana image editing: draw ON an existing generated image."""
        last: Exception | None = None
        for model in IMAGE_MODELS:
            try:
                r = await asyncio.wait_for(
                    self._client.aio.models.generate_content(
                        model=model,
                        contents=[
                            types.Part.from_bytes(data=data, mime_type=mime),
                            "Edit this educational image: "
                            + instruction
                            + ". Use bold red circles, arrows and clear English labels. Keep "
                            "everything else in the image exactly the same.",
                        ],
                        config=types.GenerateContentConfig(
                            response_modalities=["IMAGE"]
                        ),
                    ),
                    timeout=40,
                )
                for part in r.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.data:
                        return (
                            part.inline_data.data,
                            part.inline_data.mime_type or "image/jpeg",
                        )
                raise ValueError("no image returned")
            except Exception as exc:
                last = exc
                logger.warning("image edit via %s failed: %s", model, str(exc)[:120])
        raise RuntimeError(f"image edit failed: {last}")

    async def video(self, prompt: str) -> tuple[bytes, str]:
        op = await self._client.aio.models.generate_videos(
            model=VIDEO_MODEL,
            prompt="Short educational animation, clean and clear. " + prompt,
            config=types.GenerateVideosConfig(number_of_videos=1, aspect_ratio="16:9"),
        )
        for _ in range(60):  # up to ~5 minutes
            if op.done:
                break
            await asyncio.sleep(5)
            op = await self._client.aio.operations.get(op)
        if not op.done or not op.response or not op.response.generated_videos:
            raise RuntimeError(f"video not ready: {getattr(op, 'error', None)}")
        vid = op.response.generated_videos[0].video
        data = vid.video_bytes or await self._client.aio.files.download(file=vid)
        return data, vid.mime_type or "video/mp4"

    async def send(self, media_id: str, data: bytes, mime: str) -> None:
        if mime.startswith("image"):
            self.store[media_id] = (data, mime)
        writer = await self._room.local_participant.stream_bytes(
            f"{media_id}.{'mp4' if mime.startswith('video') else 'jpg'}",
            total_size=len(data),
            mime_type=mime,
            attributes={"id": media_id},
            topic=MEDIA_TOPIC,
        )
        chunk = 64 * 1024
        for i in range(0, len(data), chunk):
            await writer.write(data[i : i + chunk])
        await writer.aclose()
