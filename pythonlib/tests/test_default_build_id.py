"""
Tests for the default navigator.buildID derivation in camoufox.fingerprints.

Without an explicit navigator.buildID, XULAppInfo reports the engine binary's
own (often stale) buildID — letting a modern Firefox UA claim a years-old
build. generate_context_fingerprint() now derives a period-correct default
when the user has not set one.

Run with:
    cd pythonlib && python -m pytest tests/test_default_build_id.py -v
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox.fingerprints import (  # noqa: E402
    _default_build_id,
    _ff_major_from_ua,
    generate_context_fingerprint,
)

BUILDID_RE = re.compile(r"^\d{14}$")


class TestDefaultBuildId:
    def test_returns_14_digit_string(self):
        bid = _default_build_id("152")
        assert bid is not None
        assert BUILDID_RE.match(bid)

    def test_none_for_missing_version(self):
        assert _default_build_id(None) is None
        assert _default_build_id("") is None

    def test_none_for_non_numeric(self):
        assert _default_build_id("abc") is None

    def test_deterministic(self):
        assert _default_build_id("152") == _default_build_id("152")
        assert _default_build_id("152.0.4") == _default_build_id("152")

    def test_newer_version_is_later_date(self):
        # A newer major version must never map to an earlier build date.
        older = _default_build_id("130")
        newer = _default_build_id("150")
        assert older is not None and newer is not None
        assert newer > older

    def test_period_plausible_for_modern_firefox(self):
        # Firefox 152 (2026) must map to a 2025/2026 build, not a stale one.
        bid = _default_build_id("152")
        assert bid is not None
        assert bid.startswith("2025") or bid.startswith("2026")


class TestFfMajorFromUa:
    def test_extracts_major(self):
        ua = "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0"
        assert _ff_major_from_ua(ua) == "152"

    def test_none_when_no_firefox(self):
        assert _ff_major_from_ua("Mozilla/5.0 (Windows NT 10.0) Chrome/147.0") is None


class TestGenerateContextFingerprintIntegration:
    def test_config_gets_buildid_without_explicit(self):
        result = generate_context_fingerprint(ff_version="152")
        bid = result["config"].get("navigator.buildID")
        assert bid is not None
        assert BUILDID_RE.match(bid)

    def test_explicit_buildid_is_preserved(self):
        result = generate_context_fingerprint(
            ff_version="152",
            config_overrides={"navigator.buildID": "20200101000000"},
        )
        assert result["config"]["navigator.buildID"] == "20200101000000"
