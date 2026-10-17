"""audio_noise=False renders Web Audio as stock Firefox does.

By default the launchers seed Web Audio noise per identity, so a returning
identity reproduces its own audio hash (#442/#765). Stock Firefox renders the
standard OfflineAudioContext probe to the same value on every machine
measured, so a caller can opt out of the noise: the launch then sends seed 0,
which the browser reads as no noise, and NewContext contexts of that browser
follow it.

Run with:
    cd python && python -m pytest tests/test_audio_noise.py -v
"""

import asyncio
import re
from contextlib import contextmanager
from unittest import mock

import orjson
import pytest

from camoufox import async_api, sync_api, utils
from camoufox import fingerprints as fp


@contextmanager
def host():
    with mock.patch.object(utils, "get_screen_cons", lambda headless: None), (
        mock.patch.object(utils, "has_display", lambda env: False)
    ), mock.patch.object(utils, "installed_verstr", lambda: "150.0.2"), (
        mock.patch.object(utils, "launch_path", lambda **kwargs: "/nonexistent/camoufox")
    ):
        yield


def launch(**kwargs):
    kwargs.setdefault("os", "linux")
    kwargs.setdefault("headless", True)
    kwargs.setdefault("i_know_what_im_doing", True)
    with host():
        env = utils.launch_options(**kwargs)["env"]
    chunks = sorted((int(k.rsplit("_", 1)[1]), v) for k, v in env.items() if k.startswith("CAMOU_CONFIG_"))
    return orjson.loads("".join(chunk for _, chunk in chunks))


def seed_of(init_script):
    return int(re.search(r"setAudioFingerprintSeed\((\d+)\)", init_script).group(1))


class TestLaunch:
    def test_the_default_seeds_noise(self):
        assert launch()["audio:seed"] != 0

    def test_off_renders_stock_audio(self):
        assert launch(audio_noise=False)["audio:seed"] == 0

    def test_off_replaces_a_presets_seed(self):
        preset = fp.get_random_preset(os="windows", ff_version="150")
        assert launch(os="windows", fingerprint_preset=preset, audio_noise=False)["audio:seed"] == 0

    @pytest.mark.parametrize("audio_noise", [True, False])
    def test_a_callers_seed_is_kept(self, audio_noise):
        assert launch(config={"audio:seed": 9}, audio_noise=audio_noise)["audio:seed"] == 9


def browser(audio_noise=None):
    browser = mock.MagicMock()
    browser.version = "150.0.2"
    browser._camoufox_host_identity = None
    if audio_noise is not None:
        browser._camoufox_audio_noise = audio_noise
    return browser


class TestContexts:
    @pytest.mark.parametrize("audio_noise", [None, True])
    def test_a_context_draws_its_own_seed_by_default(self, audio_noise):
        b = browser(audio_noise)
        sync_api.NewContext(b, os="linux")

        assert seed_of(b.new_context.return_value.add_init_script.call_args.args[0]) != 0

    def test_a_context_of_a_stock_audio_browser_has_stock_audio(self):
        b = browser(False)
        sync_api.NewContext(b, os="linux")

        assert seed_of(b.new_context.return_value.add_init_script.call_args.args[0]) == 0

    def test_an_async_context_follows_the_browser(self):
        b = browser(False)
        context = mock.MagicMock()
        context.add_init_script = mock.AsyncMock()
        b.new_context = mock.AsyncMock(return_value=context)
        asyncio.run(async_api.AsyncNewContext(b, os="linux"))

        assert seed_of(context.add_init_script.call_args.args[0]) == 0


@pytest.mark.parametrize(
    "kwargs, recorded",
    [({}, True), ({"audio_noise": True}, True), ({"audio_noise": False}, False)],
)
def test_new_browser_records_the_choice_for_its_contexts(kwargs, recorded):
    playwright = mock.MagicMock()
    with mock.patch.object(sync_api, "launch_options", lambda **kw: {"env": {}, "firefox_user_prefs": {}}), \
            mock.patch.object(sync_api, "host_identity", lambda *args: None):
        launched = sync_api.NewBrowser(playwright, **kwargs)

    assert launched._camoufox_audio_noise is recorded
