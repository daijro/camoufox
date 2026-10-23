"""fingerprint_options: the noise Camoufox adds on top of an identity.

{"audio": {"noise": False}} renders Web Audio as stock Firefox does,
{"audio": {"seed": N}} fixes the audio seed, and {"canvas": {"randomize": bool}}
sets canvas randomization. Without an entry the seed follows the identity, so a
returning identity reproduces its audio hash (#442/#765), and canvas
randomization is on whenever the identity claims another OS or GPU. The older
canvas_noise= and config={"audio:seed": N} still work and warn. NewContext
contexts take the audio entry; without one they follow the browser.

Run with:
    cd python && python -m pytest tests/test_fingerprint_options.py -v
"""

import asyncio
import re
import warnings
from contextlib import contextmanager
from unittest import mock

import orjson
import pytest

from camoufox import async_api, sync_api, utils
from camoufox import fingerprints as fp
from camoufox.exceptions import InvalidFingerprintOptions
from camoufox.host_rendering import has_canvas_placeholder

AUDIO_OFF = {"audio": {"noise": False}}


@contextmanager
def host():
    with mock.patch.object(utils, "get_screen_cons", lambda headless: None), (
        mock.patch.object(utils, "has_display", lambda env: False)
    ), mock.patch.object(utils, "installed_verstr", lambda: "150.0.2"), (
        mock.patch.object(utils, "launch_path", lambda **kwargs: "/nonexistent/camoufox")
    ), mock.patch.object(utils, "host_gpu", lambda *args: None):
        yield


def options_for(**kwargs):
    kwargs.setdefault("os", "linux")
    kwargs.setdefault("headless", True)
    kwargs.setdefault("i_know_what_im_doing", True)
    with host():
        return utils.launch_options(**kwargs)


def seed_sent(**kwargs):
    return orjson.loads(utils._camou_config_blob(options_for(**kwargs)))["audio:seed"]


LINUX = fp.generate_fingerprint(os="linux")


class TestLaunchAudio:
    def test_the_default_seed_follows_the_identity(self):
        seed = seed_sent(fingerprint=LINUX)
        assert seed != 0
        assert seed_sent(fingerprint=LINUX) == seed

    @pytest.mark.parametrize("audio", [{}, {"noise": True}])
    def test_an_entry_without_a_choice_is_the_default(self, audio):
        assert seed_sent(fingerprint=LINUX, fingerprint_options={"audio": audio}) == seed_sent(fingerprint=LINUX)

    def test_noise_off_sends_the_browsers_no_noise_seed(self):
        assert seed_sent(fingerprint_options=AUDIO_OFF) == 0

    def test_noise_off_replaces_a_presets_seed(self):
        preset = fp.get_random_preset(os="windows", ff_version="150")
        assert seed_sent(os="windows", fingerprint_preset=preset, fingerprint_options=AUDIO_OFF) == 0

    @pytest.mark.parametrize("seed", [1, 1000433, 0xFFFFFFFF])
    def test_a_fixed_seed_is_sent(self, seed):
        assert seed_sent(fingerprint_options={"audio": {"seed": seed}}) == seed
        assert seed_sent(fingerprint_options={"audio": {"seed": seed, "noise": True}}) == seed


class TestValidation:
    @pytest.mark.parametrize("surface", ["fonts", "glyphs", "webgl"])
    def test_a_surface_camoufox_does_not_noise_raises(self, surface):
        with pytest.raises(InvalidFingerprintOptions, match="no-glyph-spacing-noise"):
            options_for(fingerprint_options={surface: {"noise": False}})

    @pytest.mark.parametrize(
        "options",
        [
            {"audio": {"off": True}},
            {"canvas": {"seed": 3}},
            {"audio": False},
            {"canvas": True},
            {"audio": {"noise": 0}},
            {"canvas": {"randomize": "yes"}},
            ["audio"],
        ],
    )
    def test_an_unknown_key_or_shape_raises(self, options):
        with pytest.raises(InvalidFingerprintOptions):
            options_for(fingerprint_options=options)

    @pytest.mark.parametrize("seed", [0, -1, 0x100000000, True, "5", 1.5, None])
    def test_a_seed_outside_1_to_2_32_raises(self, seed):
        with pytest.raises(InvalidFingerprintOptions, match="1 to 4294967295"):
            options_for(fingerprint_options={"audio": {"seed": seed}})

    def test_noise_off_with_a_seed_raises(self):
        with pytest.raises(InvalidFingerprintOptions, match="Pass one of them"):
            options_for(fingerprint_options={"audio": {"noise": False, "seed": 5}})


class TestOldForms:
    def test_an_audio_seed_in_config_still_works_and_warns(self):
        with pytest.warns(FutureWarning, match=r'fingerprint_options=\{"audio"'):
            assert seed_sent(config={"audio:seed": 9}) == 9
        with pytest.warns(FutureWarning):
            assert seed_sent(config={"audio:seed": 0}) == 0

    @pytest.mark.parametrize("audio", [{"noise": False}, {"seed": 9}, {}])
    def test_an_audio_seed_in_config_with_an_audio_entry_raises(self, audio):
        with pytest.raises(InvalidFingerprintOptions, match="both set the audio noise"):
            options_for(config={"audio:seed": 9}, fingerprint_options={"audio": audio})

    @pytest.mark.parametrize("randomize", [True, False])
    def test_canvas_noise_still_works_and_warns(self, randomize):
        with pytest.warns(FutureWarning, match=r'fingerprint_options=\{"canvas"'):
            old = options_for(os="windows", fingerprint=None, canvas_noise=randomize)
        new = options_for(os="windows", fingerprint_options={"canvas": {"randomize": randomize}})
        assert has_canvas_placeholder(old["firefox_user_prefs"]) is randomize
        assert has_canvas_placeholder(new["firefox_user_prefs"]) is randomize

    def test_canvas_noise_with_a_canvas_entry_raises(self):
        with pytest.warns(FutureWarning), pytest.raises(InvalidFingerprintOptions, match="both set canvas randomization"):
            options_for(canvas_noise=True, fingerprint_options={"canvas": {"randomize": True}})

    def test_the_new_forms_do_not_warn(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", FutureWarning)
            options_for(fingerprint_options={"audio": {"seed": 4}, "canvas": {"randomize": False}})


class TestLaunchCanvas:
    def test_without_an_entry_another_os_is_randomized(self):
        assert has_canvas_placeholder(options_for(os="windows")["firefox_user_prefs"])

    def test_new_browser_takes_the_canvas_choice_for_its_contexts(self):
        recorded = []

        def record(from_options, canvas_noise):
            recorded.append(canvas_noise)

        with mock.patch.object(sync_api, "launch_options", lambda **kw: {"env": {}, "firefox_user_prefs": {}}), \
                mock.patch.object(sync_api, "host_identity", record):
            sync_api.NewBrowser(mock.MagicMock(), fingerprint_options={"canvas": {"randomize": False}})
            sync_api.NewBrowser(mock.MagicMock())
            with pytest.raises(InvalidFingerprintOptions):
                sync_api.NewBrowser(mock.MagicMock(), canvas_noise=True, fingerprint_options={"canvas": {"randomize": True}})

        assert recorded == [False, None]


def browser_launched_with(from_options=None, **kwargs):
    """A NewBrowser browser (Playwright mocked) launched with these options."""
    from_options = from_options or options_for(**kwargs)
    playwright = mock.MagicMock()
    browser = playwright.firefox.launch.return_value
    browser.version = "150.0.2"
    with mock.patch.object(sync_api, "host_identity", lambda *args: None):
        launched = sync_api.NewBrowser(playwright, from_options=from_options)
    # One context per call, so a probe context and the real one stay apart.
    launched.new_context = mock.MagicMock(side_effect=lambda **kw: mock.MagicMock())
    return launched


def audio_calls(context):
    script = context.add_init_script.call_args.args[0]
    seed = re.search(r"setAudioFingerprintSeed\((\d+)\)", script)
    off = "w.setAudioFingerprintNoise(false)" in script
    return int(seed.group(1)) if seed else None, off


def browser_seed(browser):
    return browser._camoufox_audio_seed


class TestContexts:
    def test_new_browser_records_the_seed_the_launch_sent(self):
        assert browser_seed(browser_launched_with(fingerprint_options=AUDIO_OFF)) == 0
        assert browser_seed(browser_launched_with(fingerprint_options={"audio": {"seed": 77}})) == 77
        with pytest.warns(FutureWarning):
            built = options_for(config={"audio:seed": 0})
        assert browser_seed(browser_launched_with(from_options=built)) == 0

    def test_a_context_of_a_noised_browser_draws_its_own_seed(self):
        browser = browser_launched_with(fingerprint=LINUX)
        seed, off = audio_calls(sync_api.NewContext(browser, os="linux"))
        assert seed not in (None, 0, browser_seed(browser))
        assert not off

    def test_a_context_does_not_take_the_browsers_fixed_seed(self):
        browser = browser_launched_with(fingerprint_options={"audio": {"seed": 1000433}})
        seeds = {audio_calls(sync_api.NewContext(browser, os="linux"))[0] for _ in range(3)}
        assert len(seeds) == 3 and 1000433 not in seeds

    def test_a_context_of_a_browser_without_noise_has_none(self):
        browser = browser_launched_with(fingerprint_options=AUDIO_OFF)
        assert audio_calls(sync_api.NewContext(browser, os="linux")) == (None, True)
        assert audio_calls(sync_api.NewContext(browser, os="linux", fingerprint_options=AUDIO_OFF)) == (None, True)
        assert browser.new_context.call_count == 2
        assert "_camoufox_context_audio_off" not in vars(browser)

    @pytest.mark.parametrize("launch", [{}, {"fingerprint_options": AUDIO_OFF}])
    def test_a_context_takes_its_own_seed(self, launch):
        browser = browser_launched_with(**launch)
        context = sync_api.NewContext(browser, os="linux", fingerprint_options={"audio": {"seed": 31}})
        assert audio_calls(context) == (31, False)

    def test_a_context_with_noise_on_draws_a_seed_on_a_browser_without_noise(self):
        browser = browser_launched_with(fingerprint_options=AUDIO_OFF)
        seed, off = audio_calls(sync_api.NewContext(browser, os="linux", fingerprint_options={"audio": {"noise": True}}))
        assert seed not in (None, 0) and not off

    def test_a_context_turns_its_noise_off_on_a_noised_browser(self):
        browser = browser_launched_with()
        browser._camoufox_context_audio_off = True
        assert audio_calls(sync_api.NewContext(browser, os="linux", fingerprint_options=AUDIO_OFF)) == (None, True)

    def test_a_build_without_the_setter_raises_instead_of_staying_noised(self):
        browser = browser_launched_with()
        browser._camoufox_context_audio_off = False
        with pytest.raises(RuntimeError, match="setAudioFingerprintNoise"):
            sync_api.NewContext(browser, os="linux", fingerprint_options=AUDIO_OFF)

    @pytest.mark.parametrize("answer, ok", [(True, True), (False, False)])
    def test_the_browser_is_asked_once(self, answer, ok):
        browser = browser_launched_with()
        probe = mock.MagicMock()
        probe.new_page.return_value.evaluate.return_value = answer
        browser.new_context.side_effect = [probe, mock.MagicMock(), mock.MagicMock()]
        for _ in range(2):
            if ok:
                sync_api.NewContext(browser, os="linux", fingerprint_options=AUDIO_OFF)
            else:
                with pytest.raises(RuntimeError):
                    sync_api.NewContext(browser, os="linux", fingerprint_options=AUDIO_OFF)
        assert probe.add_init_script.call_args.args[0] == utils.AUDIO_OFF_PROBE
        probe.close.assert_called_once()
        assert browser.new_context.call_count == (3 if ok else 1)

    def test_canvas_in_a_context_raises(self):
        with pytest.raises(InvalidFingerprintOptions, match="belongs to the browser"):
            sync_api.NewContext(browser_launched_with(), fingerprint_options={"canvas": {"randomize": True}})

    @pytest.mark.parametrize(
        "options", [{"fonts": {}}, {"audio": {"seed": 0}}, {"audio": {"noise": False, "seed": 3}}]
    )
    def test_an_invalid_context_entry_raises(self, options):
        with pytest.raises(InvalidFingerprintOptions):
            sync_api.NewContext(browser_launched_with(), fingerprint_options=options)


class TestAsyncContexts:
    def run(self, browser, **kwargs):
        def make(**kw):
            context = mock.MagicMock()
            context.add_init_script = mock.AsyncMock()
            context.close = mock.AsyncMock()
            page = mock.MagicMock()
            page.evaluate = mock.AsyncMock(return_value=True)
            context.new_page = mock.AsyncMock(return_value=page)
            return context

        browser.new_context = mock.AsyncMock(side_effect=make)
        return asyncio.run(async_api.AsyncNewContext(browser, os="linux", **kwargs))

    def test_an_async_context_follows_a_browser_without_noise(self):
        assert audio_calls(self.run(browser_launched_with(fingerprint_options=AUDIO_OFF))) == (None, True)

    def test_an_async_context_asks_before_turning_its_noise_off(self):
        browser = browser_launched_with()
        assert audio_calls(self.run(browser, fingerprint_options=AUDIO_OFF)) == (None, True)
        assert browser._camoufox_context_audio_off is True
        assert browser.new_context.call_count == 2


class TestInitScript:
    def test_seed_0_turns_the_noise_off_rather_than_inheriting_the_launch_seed(self):
        script = fp._build_init_script({"audioFingerprintSeed": 0})
        assert 'if (typeof w.setAudioFingerprintNoise === "function") w.setAudioFingerprintNoise(false);' in script
        assert "setAudioFingerprintSeed" not in script

    def test_a_seed_is_set_as_before(self):
        script = fp._build_init_script({"audioFingerprintSeed": 5})
        assert 'w.setAudioFingerprintSeed(5);' in script
        assert "setAudioFingerprintNoise" not in script
