"""VirtualDisplay processes are cleaned up when a browser launch fails (#907)."""

from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest
from camoufox import async_api, sync_api


class _FakeVirtualDisplay:
    instances: ClassVar[list["_FakeVirtualDisplay"]] = []

    def __init__(self, debug=None):
        self.debug = debug
        self.killed = False
        _FakeVirtualDisplay.instances.append(self)

    def get(self):
        return ":99"

    def kill(self):
        self.killed = True


@pytest.fixture(autouse=True)
def reset_fakes():
    _FakeVirtualDisplay.instances = []


def test_sync_new_browser_kills_virtual_display_on_launch_error(monkeypatch):
    monkeypatch.setattr(sync_api, "VirtualDisplay", _FakeVirtualDisplay)
    mock_pw = MagicMock()
    mock_pw.firefox.launch.side_effect = RuntimeError("launch error")

    with pytest.raises(RuntimeError):
        sync_api.NewBrowser(mock_pw, headless="virtual", from_options={"args": []})

    assert len(_FakeVirtualDisplay.instances) == 1
    assert _FakeVirtualDisplay.instances[0].killed is True


def test_sync_new_browser_kills_virtual_display_on_options_error(monkeypatch):
    monkeypatch.setattr(sync_api, "VirtualDisplay", _FakeVirtualDisplay)
    monkeypatch.setattr(
        sync_api, "launch_options", MagicMock(side_effect=ValueError("invalid config"))
    )
    mock_pw = MagicMock()

    with pytest.raises(ValueError):
        sync_api.NewBrowser(mock_pw, headless="virtual")

    assert len(_FakeVirtualDisplay.instances) == 1
    assert _FakeVirtualDisplay.instances[0].killed is True


def test_async_new_browser_kills_virtual_display_on_launch_error(monkeypatch):
    import asyncio

    monkeypatch.setattr(async_api, "VirtualDisplay", _FakeVirtualDisplay)
    mock_pw = MagicMock()
    mock_pw.firefox.launch = AsyncMock(side_effect=RuntimeError("launch error"))

    with pytest.raises(RuntimeError):
        asyncio.run(
            async_api.AsyncNewBrowser(
                mock_pw, headless="virtual", from_options={"args": []}
            )
        )

    assert len(_FakeVirtualDisplay.instances) == 1
    assert _FakeVirtualDisplay.instances[0].killed is True
