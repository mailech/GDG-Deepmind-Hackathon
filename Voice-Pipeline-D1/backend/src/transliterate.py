"""Indic script transliteration for the TTS boundary.

Why this exists: Murf ships no Telugu voice, in either the Falcon or Gen2
catalog. But it does ship Kannada and Malayalam voices, and those languages
share Telugu's phoneme inventory almost exactly -- the same retroflex series,
the same vowel-length distinctions, the same consonant clusters.

The Unicode Indic blocks are laid out in parallel, so converting between sister
scripts is a constant codepoint shift:

    Telugu     U+0C00 .. U+0C7F
    Kannada    U+0C80 .. U+0CFF     (Telugu + 0x80)
    Malayalam  U+0D00 .. U+0D7F     (Telugu + 0x100)

So a Kannada voice fed transliterated Telugu pronounces it with Dravidian
phonetics -- a neighbouring-state accent rather than an English one. This is
strictly a rendering trick: the LLM writes real Telugu, the student sees real
Telugu in the transcript, and only the audio path is transliterated.

Limits worth knowing: this maps glyphs, not pronunciation rules. Kannada and
Telugu agree on nearly every letter, so the mapping is near-lossless. Malayalam
diverges a little more (chillu letters, different gemination habits), so it will
sound slightly further from native Telugu.
"""

from collections.abc import AsyncIterable

TELUGU_START = 0x0C00
TELUGU_END = 0x0C7F

# Target script -> codepoint offset from the Telugu block.
SCRIPT_OFFSETS = {
    "kannada": 0x80,
    "malayalam": 0x100,
}


def transliterate(text: str, target: str) -> str:
    """Shift Telugu codepoints into a sister script, leaving all else intact.

    Latin text, digits, punctuation and whitespace pass through untouched, which
    matters because the tutor keeps English technical terms in English.
    """
    offset = SCRIPT_OFFSETS.get(target)
    if not offset:
        return text
    return "".join(
        chr(ord(ch) + offset) if TELUGU_START <= ord(ch) <= TELUGU_END else ch
        for ch in text
    )


async def transliterate_stream(
    text: AsyncIterable[str], target: str
) -> AsyncIterable[str]:
    """Streaming form for use in Agent.tts_node.

    Safe to apply chunk-by-chunk: every Telugu codepoint -- including combining
    vowel signs and viramas -- maps independently, so no multi-character
    sequence can be split across a chunk boundary and corrupted.
    """
    async for chunk in text:
        yield transliterate(chunk, target)
