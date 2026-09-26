"""Location -> language -> dialect register -> Murf voice resolution.

Design ref: system-design.md section 4.2. This file is data, not logic: adding a
state should be a config edit, never a code change.

Voice IDs here are constrained by what Murf actually ships. IMPORTANT: Falcon
and Gen2 have SEPARATE voice catalogs — a Gen2 voice id sent to Falcon fails
with "Invalid voice_id". Always check with:

    GET /v1/speech/voices?model=FALCON

Verified against the live Falcon catalog on Day 1 (124 voices):

    available : en-IN, hi-IN, ta-IN, bn-IN, kn-IN, ml-IN, mr-IN, gu-IN, pa-IN
    MISSING   : te-IN

(Falcon covers more Indian languages than Gen2, which lacks kn/ml/mr/gu/pa.
Telugu is absent from both.)

Telugu therefore has no native voice. It falls back to an en-IN voice reading
*romanised* Telugu, which is why every Telugu profile carries script="roman".
See registers/te_telangana.md and TENGLISH_RULE in prompts.py.

Deepgram is the opposite story: nova-3 supports te/te-IN natively, so the agent
hears real Telugu script even though it cannot speak it.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class LocaleProfile:
    """Everything the agent needs to configure voice + prompt before speaking."""

    name: str
    state: str
    district: str
    language: str  # ISO 639-1, e.g. "te"
    dialect_register: str  # register pack key -> registers/<language>_<key>.md
    murf_voice_id: str
    murf_locale: str
    murf_style: str
    stt_language: str  # Deepgram language code
    script: str  # "roman" | "native" -- the script the LLM must WRITE in
    # Target script for the AUDIO path only. Set when the language has no Murf
    # voice but a phonetically-close sister language does. See transliterate.py.
    tts_transliterate: str | None = None
    greeting_style: str = "warm_informal"

    @property
    def register_pack(self) -> str:
        """Filename stem of this profile's register pack."""
        return f"{self.language}_{self.dialect_register}"


# --- Voice constants -------------------------------------------------------
# Named so a swap is one edit, and so the fallback is visible at a glance.
# ALL of these must exist in the FALCON catalog (see module docstring).

# Telugu has no Murf voice at all. Kannada is its closest phonetic sibling, so
# we speak Telugu through a Kannada voice via script transliteration — a
# neighbouring-state accent instead of an English one. Only one Kannada voice
# exists on Falcon and she is female; ml-IN-madhavan is the male alternative
# (Malayalam, slightly further phonetically).
VOICE_TELUGU_VIA_KANNADA = "kn-IN-harshitha"
VOICE_TELUGU_VIA_MALAYALAM = "ml-IN-madhavan"
VOICE_TAMIL = "ta-IN-karthikeyan"
VOICE_HINDI = "hi-IN-karan"
VOICE_ENGLISH_IN = "en-IN-nikhil"


# --- District -> register clusters -----------------------------------------
# Andhra Pradesh splits into two registers; Telangana is uniform enough for one.

AP_RAYALASEEMA_DISTRICTS = {
    "kadapa",
    "ysr kadapa",
    "anantapur",
    "sri sathya sai",
    "kurnool",
    "nandyal",
    "chittoor",
    "tirupati",
    "annamayya",
}


def _telugu_register(state: str, district: str) -> str:
    if state.strip().lower() == "telangana":
        return "telangana"
    if district.strip().lower() in AP_RAYALASEEMA_DISTRICTS:
        return "rayalaseema"
    return "coastal"


# --- State -> language -----------------------------------------------------
# Day 1 ships ONE register pack (te_telangana). The other entries resolve
# correctly but fall back to a neutral pack until Day 8 adds their packs.

HINDI_BELT = {
    "uttar pradesh",
    "madhya pradesh",
    "bihar",
    "rajasthan",
    "jharkhand",
    "chhattisgarh",
    "haryana",
    "delhi",
    "uttarakhand",
    "himachal pradesh",
}


def _hindi_profile(name: str, state: str, district: str) -> LocaleProfile:
    """Hindi profile. Register depends on WHERE the student speaks Hindi.

    A Hyderabadi student speaking Delhi khadi-boli sounds like a newsreader, so
    Telangana/AP Hindi speakers get the Dakhni register instead.
    """
    southern = state.strip().lower() in {"telangana", "andhra pradesh", "karnataka"}
    return LocaleProfile(
        name=name,
        state=state,
        district=district,
        language="hi",
        dialect_register="dakhni" if southern else "khadiboli",
        murf_voice_id=VOICE_HINDI,
        murf_locale="hi-IN",
        murf_style="Conversational",
        stt_language="hi",
        script="native",  # real Hindi voice -> write Devanagari
    )


def normalise_language(code: str | None) -> str | None:
    """Map a Deepgram language code onto one of our supported languages.

    Deepgram returns things like "te", "te-IN", "hi", "en-US". We only care
    about the base tag, and only for languages we can actually speak back.
    """
    if not code:
        return None
    base = code.split("-")[0].lower()
    return base if base in SUPPORTED_LANGUAGES else None


SUPPORTED_LANGUAGES = {"te", "hi", "ta", "en"}


def resolve(
    name: str, state: str, district: str = "", prefer_language: str | None = None
) -> LocaleProfile:
    """Resolve a student's location into a full locale profile.

    Most Indian students are multilingual, so location picks the DEFAULT
    language while prefer_language lets them override it. District still drives
    the dialect register and local examples either way.

    Unknown states fall back to Indian English rather than guessing a language
    the student may not read -- an honest fallback beats a confident wrong one.
    """
    key = state.strip().lower()

    if prefer_language == "hi":
        return _hindi_profile(name, state, district)

    if prefer_language == "en":
        return LocaleProfile(
            name=name,
            state=state,
            district=district,
            language="en",
            dialect_register="neutral",
            murf_voice_id=VOICE_ENGLISH_IN,
            murf_locale="en-IN",
            murf_style="Conversational",
            stt_language="en-IN",
            script="native",
        )

    if prefer_language == "ta":
        return LocaleProfile(
            name=name,
            state=state,
            district=district,
            language="ta",
            dialect_register="chennai",
            murf_voice_id=VOICE_TAMIL,
            murf_locale="ta-IN",
            murf_style="Conversational",
            stt_language="ta-IN",
            script="native",
        )

    if key in {"telangana", "andhra pradesh"}:
        return LocaleProfile(
            name=name,
            state=state,
            district=district,
            language="te",
            dialect_register=_telugu_register(state, district),
            murf_voice_id=VOICE_TELUGU_VIA_KANNADA,
            murf_locale="kn-IN",
            murf_style="Conversational",
            stt_language="te-IN",
            # The LLM writes real Telugu script; transliterate.py converts it to
            # Kannada on the audio path only, so the voice applies Dravidian
            # phonetics. The student still sees Telugu in the transcript.
            script="native",
            tts_transliterate="kannada",
        )

    if key == "tamil nadu":
        return LocaleProfile(
            name=name,
            state=state,
            district=district,
            language="ta",
            dialect_register="chennai",
            murf_voice_id=VOICE_TAMIL,
            murf_locale="ta-IN",
            murf_style="Conversational",
            stt_language="ta-IN",
            script="native",  # real Tamil voice -> write Tamil script
        )

    if key in HINDI_BELT:
        return _hindi_profile(name, state, district)

    return LocaleProfile(
        name=name,
        state=state,
        district=district,
        language="en",
        dialect_register="neutral",
        murf_voice_id=VOICE_ENGLISH_IN,
        murf_locale="en-IN",
        murf_style="Conversational",
        stt_language="en-IN",
        script="native",
    )


# --- Day 1: default student --------------------------------------------------
# Day 2 replaces this with POST /onboard writing a real profile.
#
# Hyderabadi Hindi (Dakhni) with a NATIVE Murf voice. Drop prefer_language to
# get Telugu, which has no Murf voice at all and falls back to a Kannada voice
# reading transliterated text — audibly not Telugu.
#
# name is empty: the agent addresses the student without one until onboarding
# collects it.

DEFAULT_PROFILE = resolve(
    name="", state="Telangana", district="Hyderabad", prefer_language="hi"
)
