"""The per-context init script hands a WebRTC IP to the setter for its family."""

import pytest

from camoufox.exceptions import InvalidIP
from camoufox.fingerprints import _build_init_script


def test_ipv4_goes_to_the_ipv4_setter():
    script = _build_init_script({"webrtcIP": "203.0.113.7"})
    assert 'w.setWebRTCIPv4("203.0.113.7")' in script
    assert "setWebRTCIPv6(" not in script


def test_ipv6_goes_to_the_ipv6_setter():
    script = _build_init_script({"webrtcIP": "2001:db8::7"})
    assert 'w.setWebRTCIPv6("2001:db8::7")' in script
    assert "2001:db8::7" not in script.split("setWebRTCIPv6")[0]


def test_an_invalid_address_is_refused():
    with pytest.raises(InvalidIP):
        _build_init_script({"webrtcIP": "not-an-ip"})
