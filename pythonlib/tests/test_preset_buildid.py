"""
navigator.buildID defaults, derived from the spoofed UA version.

Run with:
    cd pythonlib && python -m pytest tests/test_preset_buildid.py -v

The regression these guard: Camoufox spoofs navigator.userAgent to a chosen
Firefox version, but navigator.buildID is only spoofed when the user sets it
explicitly (settings/properties.json, validated in camoucfg.jvv). Unset, the
engine falls back to XULAppInfo — the *host build's* value. Distributed
Camoufox builds report a stale one (our deployed instance: 20181001000000,
i.e. a Firefox 63-era build) while the UA claims a current Firefox: a
cross-check any detector can make in two properties.

The fix derives a plausible YYYYMMDDHHMMSS from the spoofed major version
(Firefox 94 anchored at 2021-11-02, ~4 weeks per major since) in both
assembly paths — from_preset and from_browserforge — and never overrides a
user-supplied value.
"""

import os
import re
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox.fingerprints import (  # noqa: E402
    _default_build_id,
    _ff_major_from_user_agent,
    from_preset,
)


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0"


def test_build_id_derivation_shape():
    bid = _default_build_id(152)
    assert bid is not None
    # YYYYMMDDHHMMSS, all digits (camoucfg.jvv validates str[/^\d+$/])
    assert re.fullmatch(r"\d{14}", bid)
    # Plausibly recent for a 2026-era version, not a 2018 host artifact
    assert bid > "20240101000000"


def test_build_id_deterministic_per_major():
    assert _default_build_id(152) == _default_build_id(152)
    assert _default_build_id(152) != _default_build_id(151)


def test_build_id_monotonic_in_version():
    lower = _default_build_id(151)
    upper = _default_build_id(152)
    assert lower is not None and upper is not None
    assert lower < upper


def test_build_id_unparseable_versions():
    assert _default_build_id(None) is None
    assert _default_build_id(0) is None
    # Pre-anchor versions keep the user's/host's value rather than guessing
    assert _default_build_id(63) is None


def test_major_extraction():
    assert _ff_major_from_user_agent(UA) == 152
    assert _ff_major_from_user_agent("no firefox here") is None
    assert _ff_major_from_user_agent(None) is None


def test_preset_path_derives_build_id():
    preset = {"navigator": {"userAgent": UA, "platform": "Win32"}}
    config = from_preset(preset)
    assert re.fullmatch(r"\d{14}", config["navigator.buildID"])
    # Coherent with the UA: derived for 152, newer than the 151 stamp
    assert config["navigator.buildID"] == _default_build_id(152)


def test_preset_path_respects_user_supplied_build_id():
    preset = {"navigator": {"userAgent": UA, "buildID": "20240101120000"}}
    config = from_preset(preset)
    # User's explicit value wins
    assert config["navigator.buildID"] == "20240101120000"


def test_preset_path_no_ua_no_derivation():
    preset = {"navigator": {"platform": "Win32"}}
    config = from_preset(preset)
    assert "navigator.buildID" not in config


def test_ff_version_override_rewrites_derivation():
    preset = {"navigator": {"userAgent": UA.replace("152", "135")}}
    config = from_preset(preset, ff_version="152")
    # UA rewritten to 152; buildID must match 152's stamp
    assert config["navigator.buildID"] == _default_build_id(152)


def test_browserforge_path_derives_build_id():
    from camoufox.fingerprints import from_browserforge, generate_fingerprint

    fp = generate_fingerprint(os="windows")
    config = from_browserforge(fp, ff_version="152")
    bid = config["navigator.buildID"]
    assert re.fullmatch(r"\d{14}", bid)
    m = re.search(r"Firefox/(\d+)", config["navigator.userAgent"])
    assert m is not None
    assert bid == _default_build_id(int(m.group(1)))