"""headless="virtual" must not strand its Xvfb when the launch fails.

Everything after VirtualDisplay() -- launch_options(), the Playwright launch --
can raise before sync/async_attach_vd wires kill() into close, which used to
leave one Xvfb and its /tmp/.X<n> lock per failed launch.
"""

import asyncio

import pytest

from camoufox import async_api, sync_api


class FakeDisplay:
    instances = []

    def __init__(self, debug=None):
        self.killed = False
        FakeDisplay.instances.append(self)

    def get(self):
        return ":99"

    def kill(self):
        self.killed = True


class Boom(Exception):
    pass


def _raise(*args, **kwargs):
    raise Boom()


@pytest.fixture(autouse=True)
def fake_display(monkeypatch):
    FakeDisplay.instances.clear()
    monkeypatch.setattr(sync_api, "VirtualDisplay", FakeDisplay)
    monkeypatch.setattr(async_api, "VirtualDisplay", FakeDisplay)


def test_sync_kills_display_when_launch_options_fails(monkeypatch):
    monkeypatch.setattr(sync_api, "launch_options", _raise)
    with pytest.raises(Boom):
        sync_api.NewBrowser(object(), headless="virtual")
    assert FakeDisplay.instances[0].killed


def test_async_kills_display_when_launch_options_fails(monkeypatch):
    monkeypatch.setattr(async_api, "launch_options", _raise)
    with pytest.raises(Boom):
        asyncio.run(async_api.AsyncNewBrowser(object(), headless="virtual"))
    assert FakeDisplay.instances[0].killed


def test_sync_kills_display_when_browser_launch_fails(monkeypatch):
    monkeypatch.setattr(sync_api, "launch_options", lambda **kw: {})
    monkeypatch.setattr(sync_api, "host_identity", lambda *a: None)

    class Firefox:
        launch = staticmethod(_raise)

    class Playwright:
        firefox = Firefox()

    with pytest.raises(Boom):
        sync_api.NewBrowser(Playwright(), headless="virtual")
    assert FakeDisplay.instances[0].killed
