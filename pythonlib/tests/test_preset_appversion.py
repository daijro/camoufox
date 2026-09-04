"""
Tests that a device preset does not leak the host's operating system.

Run with:
    cd pythonlib && python -m pytest tests/test_preset_appversion.py -v

The regression these guard (daijro/camoufox#744): from_preset() sets
navigator.userAgent, platform and oscpu from the captured device, but never
appVersion. Firefox reports appVersion as "5.0 (<OS token>)", so an unset value
falls through to the host's own -- and a page reading two properties sees a
Linux platform beside "5.0 (Macintosh)".

Measured before the fix on 152.0.4-beta.29, macOS host, os="linux" with
fingerprint_preset=True:

    navigator.platform    Linux x86_64
    navigator.appVersion  5.0 (Macintosh)     <- the host

The generated (browserforge) path already emits a coherent pair, which is why
this only shows up on the preset path.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox.fingerprints import _app_version_from_user_agent, from_preset  # noqa: E402

# The tokens Firefox actually reports. Sampled from 800 browserforge
# fingerprints: Windows and Macintosh collapse to the family name, X11 keeps a
# distro token when the user agent carries one, and Android keeps its version.
_MAC = "5.0 (Macintosh)"
_WINDOWS = "5.0 (Windows)"
_X11 = "5.0 (X11)"
_X11_UBUNTU = "5.0 (X11; Ubuntu)"


def _preset(platform: str, user_agent: str) -> dict:
    return {"navigator": {"platform": platform, "userAgent": user_agent}}


@pytest.mark.parametrize(
    ("platform", "user_agent", "expected"),
    [
        (
            "Linux x86_64",
            "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0",
            _X11,
        ),
        (
            "Win32",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
            _WINDOWS,
        ),
        (
            "MacIntel",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0",
            _MAC,
        ),
    ],
)
def test_app_version_follows_the_preset_platform(platform, user_agent, expected):
    """Every preset must carry the appVersion its own platform implies."""
    config = from_preset(_preset(platform, user_agent))

    assert config["navigator.appVersion"] == expected


def test_app_version_agrees_with_the_user_agent():
    """The pair a page compares must not contradict itself.

    This is the check the issue is about: not that appVersion holds any
    particular string, but that it names the same system as the userAgent
    beside it.
    """
    config = from_preset(
        _preset("Linux x86_64", "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0")
    )

    assert "X11" in config["navigator.userAgent"]
    assert config["navigator.appVersion"] == _X11
    assert "Macintosh" not in config["navigator.appVersion"]
    assert "Windows" not in config["navigator.appVersion"]


def test_a_preset_that_carries_its_own_app_version_keeps_it():
    """A captured value is the real device's, so it wins over the derived one."""
    preset = _preset("Win32", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Firefox/152.0")
    preset["navigator"]["appVersion"] = "5.0 (Windows NT 10.0; Win64; x64)"

    config = from_preset(preset)

    assert config["navigator.appVersion"] == "5.0 (Windows NT 10.0; Win64; x64)"


def test_an_unknown_platform_follows_its_user_agent():
    """The user agent is the authority, not the platform string beside it."""
    config = from_preset(_preset("iPhone", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Gecko/20100101"))

    assert config["navigator.appVersion"] == "5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"


@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [
        # Every shape in the captured corpus, with the counts they appeared in.
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0", _WINDOWS),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0", _MAC),
        ("Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0", _X11),
        ("Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0", _X11_UBUNTU),
        ("Mozilla/5.0 (Android 16; Mobile; rv:152.0) Gecko/152.0 Firefox/152.0", "5.0 (Android 16)"),
    ],
)
def test_the_derivation_matches_what_firefox_reports(user_agent, expected):
    """Checked against 800 browserforge fingerprints; exact on every one."""
    assert _app_version_from_user_agent(user_agent) == expected


def test_a_distro_token_survives():
    """Twenty of the bundled Linux presets say "X11; Ubuntu" in their user agent.

    Deriving from the platform instead would flatten those to "X11" — a smaller
    mismatch than the host leaking, but the same kind, and Firefox never emits it.
    """
    config = from_preset(
        _preset(
            "Linux x86_64",
            "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0",
        )
    )

    assert config["navigator.appVersion"] == _X11_UBUNTU


def test_a_user_agent_it_cannot_read_is_left_alone():
    """Better an absent value than an invented one."""
    config = from_preset(_preset("Win32", "not a user agent"))

    assert "navigator.appVersion" not in config
