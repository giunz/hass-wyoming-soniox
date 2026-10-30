from wyoming_soniox.soniox_api import _join_tokens, _language_hints
from wyoming_soniox.text import chunk_text, detect_language, split_complete_sentences


def test_detect_language():
    assert detect_language("Καλημέρα, τι κάνεις;", "en") == "el"
    assert detect_language("Good morning", "en") == "en"
    assert detect_language("Good morning", "el") == "en"
    assert detect_language("Το Netflix είναι ανοιχτό", "en") == "el"
    assert detect_language("21°C", "en") == "en"


def test_split_sentences_greek_question_mark():
    done, rest = split_complete_sentences("Τι ώρα είναι; Είναι οκτώ. Και")
    assert done == ["Τι ώρα είναι;", "Είναι οκτώ."]
    assert rest == "Και"


def test_chunk_text_limits():
    text = " ".join(["This is sentence number %d." % i for i in range(200)])
    chunks = chunk_text(text, max_chars=300)
    assert all(len(c) <= 300 for c in chunks)
    assert " ".join(chunks) == text


def test_join_tokens_drops_markers():
    assert _join_tokens(["Turn", " on", " the", " light", "<end>"]) == "Turn on the light"


def test_language_hints():
    assert _language_hints("el-GR", ["en", "el"]) == ["el", "en"]
    assert _language_hints(None, ["en", "el"]) == ["en", "el"]


def test_clean_for_speech_markdown():
    from wyoming_soniox.text import clean_for_speech

    assert clean_for_speech("**Lights** are [on](http://x)") == "Lights are on"
    assert clean_for_speech("## Status") == "Status"
    assert clean_for_speech("- *Kitchen*: 21°C") == "Kitchen: 21°C"
    assert clean_for_speech("Use `light.living_room` now") == "Use light.living_room now"
    assert clean_for_speech("1.") == ""
    assert clean_for_speech("Η πόρτα είναι **κλειδωμένη**.") == "Η πόρτα είναι κλειδωμένη."
