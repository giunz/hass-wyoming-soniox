"""Text helpers: language detection by script and sentence splitting."""

import re
from typing import List, Tuple

_GREEK = re.compile(r"[Ͱ-Ͽἀ-῿]")
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")

# Sentence ends: . ! ? … plus Greek question mark (U+037E, and the ASCII
# semicolon Greek text usually uses) and ano teleia (U+0387, ·).
_SENTENCE_END = re.compile(r"(?<=[.!?…;;··])\s+|\n+")


def detect_language(text: str, default: str) -> str:
    """Return "el" if the text is mostly Greek script, otherwise the default.

    Home Assistant's Wyoming TTS client sends only a voice name, never the
    language, so the language has to be inferred from the text itself.
    """
    greek = len(_GREEK.findall(text))
    latin = len(_LATIN.findall(text))
    if greek > 0 and greek >= latin:
        return "el"
    if default == "el" and latin > 0:
        # Default is Greek but this text is Latin script; English is the
        # most likely match for a mixed English/Greek household.
        return "en"
    return default


_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_LIST_MARKER = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+", re.MULTILINE)
_MD_HEADING = re.compile(r"^\s*#{1,6}\s*", re.MULTILINE)
_MD_SYMBOLS = re.compile(r"[*_`~]{1,3}|^\s*>\s?", re.MULTILINE)
_ONLY_LIST_NUMBER = re.compile(r"^\s*\d+[.)]?\s*$")


def clean_for_speech(text: str) -> str:
    """Remove markdown that LLM replies often contain, so it is not read aloud.

    Keeps the words: "**Lights** are [on](url)" becomes "Lights are on".
    A piece that is only a list number ("1.") becomes empty.
    """
    if _ONLY_LIST_NUMBER.match(text):
        return ""
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_HEADING.sub("", text)
    text = _MD_LIST_MARKER.sub("", text)
    # Underscores inside words (entity ids such as light.living_room) stay.
    text = re.sub(r"(?<=\w)_(?=\w)", "\0", text)
    text = _MD_SYMBOLS.sub("", text).replace("\0", "_")
    return re.sub(r"[ \t]+", " ", text).strip()


def split_complete_sentences(buffer: str) -> Tuple[List[str], str]:
    """Split off complete sentences; return (sentences, unfinished remainder)."""
    parts = _SENTENCE_END.split(buffer)
    if len(parts) <= 1:
        return [], buffer
    complete = [p.strip() for p in parts[:-1] if p.strip()]
    return complete, parts[-1]


def chunk_text(text: str, max_chars: int = 1000) -> List[str]:
    """Group sentences into chunks of at most max_chars (for long messages)."""
    sentences, rest = split_complete_sentences(text)
    if rest.strip():
        sentences.append(rest.strip())

    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > max_chars:
            # A single very long sentence: cut at the last space.
            cut = sentence.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current = f"{current} {sentence}"
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return [c for c in chunks if c]
