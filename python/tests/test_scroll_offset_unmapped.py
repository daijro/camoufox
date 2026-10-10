"""No identity pins the page's scroll offset.

The browser returns a configured screen.pageYOffset from scrollY on every read,
so a drawn value froze the page at one scroll position whatever the user did.
"""

from camoufox.fingerprints import from_fpgen, generate_fingerprint

_SCROLL_KEYS = ("screen.pageXOffset", "screen.pageYOffset")


def test_a_drawn_scroll_offset_is_not_carried_into_the_config():
    fingerprint = generate_fingerprint(os="windows")
    fingerprint["window"] = {**fingerprint["window"], "pageXOffset": 17, "pageYOffset": 528}
    config = from_fpgen(fingerprint, "152")
    assert not set(_SCROLL_KEYS) & config.keys()
