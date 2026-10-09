"""
Tests for camoufox.fingerprints speech-voice generation.

Mirrored by the "voices" cases in typescript/tests/fingerprints.test.ts.

Run with:
    cd python && python -m pytest tests/test_voices.py -v

The core regression these guard: every spoofable OS -- including Linux --
must yield a non-empty list of MaskConfig voice OBJECTS (not raw
"Name:lang:type" strings), or the C++ MaskConfig::MVoices() silently drops
them and the host machine's native voices leak through.
"""


import pytest

from camoufox.fingerprints import (
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
def test_no_default_voice(target_os):
    # Stock Firefox 152 marks no SpeechSynthesisVoice.default on any OS.
    voices = _generate_random_voice_subset(target_os, "en-US")
    assert voices and not any(v["isDefault"] for v in voices)


def test_windows_display_language_pack():
    # A German display language gets the German OneCore pack first; en-US is
    # the pack every stock en-US box reports (David / Mark / Zira + Desktop).
    de = _generate_random_voice_subset("windows", "de-DE", seed=1)
    assert de[0]["lang"] == "de-DE"
    en = _generate_random_voice_subset("windows", "en-US", seed=1)
    assert [v["name"] for v in en[:3]] == [
        "Microsoft David - English (United States)",
        "Microsoft Mark - English (United States)",
        "Microsoft Zira - English (United States)",
    ]


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


# ── Fail-closed voice configuration (daijro/camoufox#731) ────────────────────
#
# nsSynthVoiceRegistry only withholds the host's speech-dispatcher / SAPI /
# NSSpeech voices while Camoufox owns the list. An empty or unset `voices`
# used to fall through to the host backend and register every native voice --
# 14805 espeak-ng entries on a stock Linux box -- under a fingerprint claiming
# macOS or Windows.

from camoufox.exceptions import InvalidPropertyType  # noqa: E402
from camoufox.utils import validate_voices  # noqa: E402


def _launch_config(**kwargs):
    """Rebuild the config dict from the chunked CAMOU_CONFIG_* env vars."""
    import json

    from camoufox.utils import launch_options

    opts = launch_options(headless=True, i_know_what_im_doing=True, **kwargs)
    env = opts["env"]
    chunks = sorted(
        (k for k in env if k.startswith("CAMOU_CONFIG_")),
        key=lambda k: int(k.rsplit("_", 1)[1]),
    )
    return json.loads("".join(env[k] for k in chunks))


def test_block_flag_is_pinned_by_default():
    # Without this the browser has no instruction to withhold host voices when
    # the list it receives turns out to be empty or unusable.
    assert _launch_config(os="macos")["voices:blockIfNotDefined"] is True


def test_caller_can_override_the_block_flag():
    cfg = _launch_config(os="macos", config={"voices:blockIfNotDefined": False})
    assert cfg["voices:blockIfNotDefined"] is False


def test_voice_generation_failure_fails_closed(monkeypatch):
    import camoufox.utils as utils

    from camoufox._warnings import FallbackWarning

    def boom(*_args, **_kwargs):
        raise OSError("voice-manifests.json unreadable")

    monkeypatch.setattr(utils, "_generate_random_voice_subset", boom)
    with pytest.warns(FallbackWarning, match="github.com/daijro/camoufox/issues/new"):
        cfg = _launch_config(os="macos")
    # An empty list plus the block flag means "no voices" -- never "all of the
    # host's".
    assert cfg["voices"] == []
    assert cfg["voices:blockIfNotDefined"] is True


@pytest.mark.parametrize(
    "value",
    [
        ["Alex:en-US:local"],  # the bare-string shape MVoices() drops
        [{"name": "Alex", "lang": "en-US"}],  # incomplete object
        "Alex",  # not a list at all
    ],
)
def test_validate_voices_rejects_unusable_shapes(value):
    with pytest.raises(InvalidPropertyType):
        validate_voices(value)


@pytest.mark.parametrize(
    "value",
    [
        [],  # empty is legal: it means "no voices", and the flag enforces it
        [
            {
                "lang": "en-US",
                "name": "Alex",
                "voiceUri": "urn:moz-tts:osx:alex",
                "isDefault": True,
                "isLocalService": True,
            }
        ],
    ],
)
def test_validate_voices_accepts_usable_shapes(value):
    validate_voices(value)
