"""Driver-side guard for daijro/camoufox#666.

Playwright's implicit 1280x720 viewport makes Juggler ask a spoofed window to
resize to a size it can never reach, deadlocking new_page(). The driver defaults
to no_viewport whenever the config spoofs any window dimension, which fixes the
hang on *already-released* browser builds -- no rebuild needed.
"""

import pytest

from camoufox.utils import attach_no_viewport_default, spoofs_window_dimensions


def _opts(config_blob: str):
    """Launch options with the config chunked the way launch_options() does."""
    chunks = [config_blob[i : i + 10] for i in range(0, len(config_blob), 10)] or [""]
    return {"env": {f"CAMOU_CONFIG_{i + 1}": c for i, c in enumerate(chunks)}}


@pytest.mark.parametrize(
    "config, expected",
    [
        ('{"window.outerWidth": 360}', True),
        ('{"window.innerHeight": 740}', True),
        ('{"screen.width": 360}', False),
        ('{"navigator.userAgent": "x"}', False),
        ("{}", False),
    ],
)
def test_detects_window_dimension_spoofing(config, expected):
    assert spoofs_window_dimensions(_opts(config)) is expected


def test_reassembles_chunks_in_index_order():
    """CAMOU_CONFIG_10 must not sort before CAMOU_CONFIG_2 -- a lexicographic
    join would corrupt the key we search for."""
    blob = '{"padding": "' + "x" * 200 + '", "window.outerWidth": 360}'
    assert spoofs_window_dimensions(_opts(blob)) is True


def test_no_env_is_not_spoofed():
    assert spoofs_window_dimensions({}) is False


class _FakeBrowser:
    def __init__(self):
        self.calls = []

    def new_page(self, **kwargs):
        self.calls.append(kwargs)
        return "page"

    def new_context(self, **kwargs):
        self.calls.append(kwargs)
        return "context"


def test_defaults_to_no_viewport():
    b = attach_no_viewport_default(_FakeBrowser())
    b.new_page()
    b.new_context()
    assert b.calls == [{"no_viewport": True}, {"no_viewport": True}]


@pytest.mark.parametrize(
    "override",
    [{"viewport": {"width": 800, "height": 600}}, {"no_viewport": False}],
)
def test_explicit_caller_choice_always_wins(override):
    """We must never override an explicit viewport decision."""
    b = attach_no_viewport_default(_FakeBrowser())
    b.new_page(**override)
    assert b.calls == [override]


def test_other_kwargs_are_forwarded():
    b = attach_no_viewport_default(_FakeBrowser())
    b.new_page(locale="en-US")
    assert b.calls == [{"locale": "en-US", "no_viewport": True}]
