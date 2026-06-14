"""
Tests for camoufox.fingerprints speech-voice generation.

Mirrors camoufox-js/tests-camoufox-js/voices.test.ts.

Run with:
    cd pythonlib && python -m pytest tests/test_voices.py -v

The core regression these guard: every spoofable OS -- including Linux --
must yield a non-empty list of MaskConfig voice OBJECTS (not raw
"Name:lang:type" strings), or the C++ MaskConfig::MVoices() silently drops
them and the host machine's native voices leak through.
"""

import os
import sys

import pytest

# Make `import camoufox` resolve to the in-tree pythonlib without an install.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox.fingerprints import (  # noqa: E402
    _generate_random_voice_subset,
    _normalize_preset_voices,
)

_REQUIRED_FIELDS = {"lang", "name", "voiceUri", "isDefault", "isLocalService"}


@pytest.mark.parametrize("target_os", ["macos", "windows", "linux"])
def test_non_empty_for_every_os(target_os):
    voices = _generate_random_voice_subset(target_os, "en-US")
    assert len(voices) > 0


@pytest.mark.parametrize("target_os", ["macos", "windows", "linux"])
def test_entries_are_full_objects(target_os):
    # MaskConfig::MVoices() drops any entry missing a field, so every voice
    # must carry the full object shape.
    for v in _generate_random_voice_subset(target_os, "en-US"):
        assert isinstance(v, dict)
        assert _REQUIRED_FIELDS <= set(v.keys())


@pytest.mark.parametrize("target_os", ["macos", "windows", "linux"])
def test_exactly_one_default(target_os):
    voices = _generate_random_voice_subset(target_os, "en-US")
    assert sum(1 for v in voices if v["isDefault"]) == 1


def test_default_matches_spoofed_locale_prefix():
    de = _generate_random_voice_subset("linux", "de-DE")
    default = next(v for v in de if v["isDefault"])
    assert default["lang"].split("-")[0] == "de"


class TestLinuxSpeechdUris:
    """Linux voiceUris must match Firefox's SpeechDispatcherService.cpp:
    urn:moz-tts:speechd:<NS_EscapeURL(name, OnlyNonASCII|Spaces)>?<lang>
    """

    def setup_method(self):
        self.lin = _generate_random_voice_subset("linux", "en-US")

    def test_prefix_and_lang_suffix(self):
        for v in self.lin:
            assert v["voiceUri"].startswith("urn:moz-tts:speechd:")
            assert v["voiceUri"].endswith("?" + v["lang"])

    def test_spaces_escaped_punctuation_intact(self):
        gb = next(v for v in self.lin if v["name"] == "English (Great Britain)")
        assert gb["voiceUri"] == "urn:moz-tts:speechd:English%20(Great%20Britain)?en-GB"

    def test_all_local_service(self):
        assert all(v["isLocalService"] for v in self.lin)


def test_normalize_preset_voices_converts_strings():
    # Presets historically store "Name:lang:type" strings.
    out = _normalize_preset_voices(
        ["Albert:en-US:local", "Alice:it-IT:local"], "macos"
    )
    assert all(_REQUIRED_FIELDS <= set(v.keys()) for v in out)
    assert out[0]["name"] == "Albert"
    assert out[0]["lang"] == "en-US"
    assert sum(1 for v in out if v["isDefault"]) == 1


def test_normalize_preset_voices_passes_through_objects():
    obj = {
        "name": "Alex",
        "lang": "en-US",
        "voiceUri": "urn:moz-tts:osx:alex",
        "isDefault": True,
        "isLocalService": True,
    }
    out = _normalize_preset_voices([obj], "macos")
    assert out == [obj]


def test_unknown_os_falls_back_to_macos():
    assert len(_generate_random_voice_subset("plan9", "en-US")) > 0
