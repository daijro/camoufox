"""headless=True on Linux runs headed on a private Xvfb whenever Xvfb is there.

Firefox's own -headless shows stand-in system colors (AccentColor #0060df,
Highlight #3399ff), `sans-serif 14px` CSS2 system fonts and a frameless window,
which pages read. The launcher therefore
treats headless=True like headless='virtual' on Linux, and falls back to true
headless, with a LeakWarning naming the missing tool, only without Xvfb/setpriv.
"""

import warnings

import pytest

from camoufox import sync_api, utils
from camoufox._warnings import LeakWarning


class FakeDisplay:
    instances = []

    def __init__(self, debug=None):
        self.killed = False
        FakeDisplay.instances.append(self)

    def get(self):
        return ":77"

    def kill(self):
        self.killed = True


@pytest.fixture(autouse=True)
def fake_display(monkeypatch):
    FakeDisplay.instances.clear()
    monkeypatch.setattr(utils, "VirtualDisplay", FakeDisplay)
    monkeypatch.setattr(utils, "OS_NAME", "lin")


def _tools(monkeypatch, present):
    monkeypatch.setattr(utils.shutil, "which", lambda tool: f"/usr/bin/{tool}" if tool in present else None)
    monkeypatch.setattr(utils.os, "access", lambda path, mode: True)


def test_headless_true_runs_on_xvfb_on_linux(monkeypatch):
    _tools(monkeypatch, {"Xvfb", "setpriv"})
    kwargs = {}
    display, headless = utils.start_virtual_display(True, False, kwargs)
    assert isinstance(display, FakeDisplay)
    assert headless is False
    assert kwargs["virtual_display"] == ":77"


@pytest.mark.parametrize("missing,named", [("Xvfb", "Xvfb"), ("setpriv", "util-linux")])
def test_headless_true_falls_back_with_a_warning(monkeypatch, missing, named):
    _tools(monkeypatch, {"Xvfb", "setpriv"} - {missing})
    kwargs = {}
    with pytest.warns(LeakWarning, match=named):
        display, headless = utils.start_virtual_display(True, False, kwargs)
    assert display is None and headless is True
    assert "virtual_display" not in kwargs
    assert not FakeDisplay.instances


def test_fallback_warning_respects_i_know_what_im_doing(monkeypatch):
    _tools(monkeypatch, set())
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert utils.headless_mode(True, {"i_know_what_im_doing": True}) is True


@pytest.mark.parametrize("value", [False, None, "virtual"])
def test_other_values_are_untouched(monkeypatch, value):
    _tools(monkeypatch, {"Xvfb", "setpriv"})
    assert utils.headless_mode(value) == value


def test_not_linux_stays_firefox_headless(monkeypatch):
    _tools(monkeypatch, {"Xvfb", "setpriv"})
    monkeypatch.setattr(utils, "OS_NAME", "win")
    assert utils.headless_mode(True) is True


def test_callers_own_display_keeps_headless(monkeypatch):
    _tools(monkeypatch, {"Xvfb", "setpriv"})
    assert utils.headless_mode(True, {"virtual_display": ":5"}) is True


def test_new_browser_kills_the_display_it_chose(monkeypatch):
    _tools(monkeypatch, {"Xvfb", "setpriv"})

    class Boom(Exception):
        pass

    def boom(**kw):
        raise Boom()

    monkeypatch.setattr(sync_api, "launch_options", boom)
    with pytest.raises(Boom):
        sync_api.NewBrowser(object(), headless=True)
    assert FakeDisplay.instances and FakeDisplay.instances[0].killed
