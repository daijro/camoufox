"""Regression tests for per-launch environment isolation."""

import os

import pytest

from camoufox import utils


@pytest.fixture
def isolated_launch_dependencies(monkeypatch):
    """Keep launch_options focused on environment assembly, without a browser."""
    monkeypatch.setattr(utils, "add_default_addons", lambda *args, **kwargs: None)
    monkeypatch.setattr(utils, "generate_fingerprint", lambda *args, **kwargs: object())
    monkeypatch.setattr(utils, "from_fpgen", lambda *args, **kwargs: {})
    monkeypatch.setattr(utils, "get_screen_cons", lambda *args, **kwargs: None)
    monkeypatch.setattr(utils, "_generate_random_font_subset", lambda *args, **kwargs: [])
    monkeypatch.setattr(utils, "_generate_random_voice_subset", lambda *args, **kwargs: [])
    monkeypatch.setattr(utils, "fix_navigator_arch", lambda *args: None)
    monkeypatch.setattr(utils, "fix_screen_no_taskbar", lambda *args: None)
    monkeypatch.setattr(utils, "clamp_window_dimensions", lambda *args: None)
    monkeypatch.setattr(utils, "set_media_devices_defaults", lambda *args: None)
    monkeypatch.setattr(utils, "installed_verstr", lambda: "152.0.4-beta.28")
    monkeypatch.setattr(utils, "validate_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(utils, "get_env_vars", lambda *args, **kwargs: {})
    monkeypatch.setattr(utils, "launch_path", lambda: "/test/camoufox")


def _launch_with_virtual_display(**kwargs):
    return utils.launch_options(
        virtual_display=":4242",
        headless=True,
        block_webgl=True,
        i_know_what_im_doing=True,
        **kwargs,
    )


def test_virtual_display_does_not_mutate_process_environment(
    monkeypatch, isolated_launch_dependencies
):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("GDK_BACKEND", "wayland")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("MOZ_ENABLE_WAYLAND", "1")
    keys = ("DISPLAY", "GDK_BACKEND", "WAYLAND_DISPLAY", "MOZ_ENABLE_WAYLAND")
    before = {key: os.environ.get(key) for key in keys}

    options = _launch_with_virtual_display()

    assert {key: os.environ.get(key) for key in keys} == before
    assert options["env"]["DISPLAY"] == ":4242"
    assert options["env"]["GDK_BACKEND"] == "x11"
    assert "WAYLAND_DISPLAY" not in options["env"]
    assert options["env"]["MOZ_ENABLE_WAYLAND"] == "0"


def test_virtual_display_does_not_mutate_caller_environment(
    isolated_launch_dependencies,
):
    caller_env = {
        "UNCHANGED": "value",
        "GDK_BACKEND": "wayland",
        "WAYLAND_DISPLAY": "wayland-0",
        "MOZ_ENABLE_WAYLAND": "1",
    }
    before = caller_env.copy()

    options = _launch_with_virtual_display(env=caller_env)

    assert caller_env == before
    assert options["env"]["UNCHANGED"] == "value"
    assert options["env"]["DISPLAY"] == ":4242"
    assert options["env"]["GDK_BACKEND"] == "x11"
    assert "WAYLAND_DISPLAY" not in options["env"]
    assert options["env"]["MOZ_ENABLE_WAYLAND"] == "0"


class TestFontFallbackAsyncPref:
    """Per-character font fallback must not skip families whose
    charmap is not loaded yet.

    Gecko's GlobalFontFallback walks the shared font list for a family covering
    the character; in a content process with async fallback on it hits the
    `!family.IsFullyInitialized()` branch, schedules a cmap load and SKIPS the
    family, so the first measurement of a character only one bundled family
    provides returns the primary family's .notdef. Linux takes that path for
    every fallback (UseCmapsDuringSystemFallback), so the font-hijacker change
    that restored this on macOS cannot reach it there.

    macOS must NOT get the pref: it uses the CoreText fallback, and forcing the
    synchronous scan changed the face picked for U+1E9E in Futura (stock 21.733
    -> 27.267), measured on a real Mac mini.
    """

    PREF = "gfx.font_rendering.fallback.async"

    def _prefs_for(self, ua, isolated):
        return utils.launch_options(
            config={"navigator.userAgent": ua},
            i_know_what_im_doing=True,
        )["firefox_user_prefs"]

    def test_linux_disables_async_font_fallback(self, isolated_launch_dependencies):
        prefs = self._prefs_for("Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0", None)
        assert prefs[self.PREF] is False

    def test_macos_keeps_async_font_fallback(self, isolated_launch_dependencies):
        prefs = self._prefs_for(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:152.0) Gecko/20100101 Firefox/152.0", None
        )
        assert self.PREF not in prefs

    def test_windows_keeps_async_font_fallback(self, isolated_launch_dependencies):
        prefs = self._prefs_for(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0", None
        )
        assert self.PREF not in prefs

    def test_caller_pref_wins(self, isolated_launch_dependencies):
        prefs = utils.launch_options(
            config={"navigator.userAgent": "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0"},
            firefox_user_prefs={"gfx.font_rendering.fallback.async": True},
            i_know_what_im_doing=True,
        )["firefox_user_prefs"]
        assert prefs[self.PREF] is True


class TestUiLocaleFollowsIntlLocale:
    """The packaged browser locale must follow the spoofed Intl locale.

    With locale="fr-FR" and the browser left on en-US, Intl formatting went
    French while input.validationMessage and XML parse errors stayed English --
    a mix no real Firefox produces. Packages now bake in the language packs;
    intl.locale.requested selects one, and must always be set because an empty
    value would follow the host OS locale.
    """

    PREF = "intl.locale.requested"
    UA = "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0"

    def _prefs(self, **kwargs):
        return utils.launch_options(
            config={"navigator.userAgent": self.UA, **kwargs.pop("config", {})},
            i_know_what_im_doing=True,
            **kwargs,
        )["firefox_user_prefs"]

    def test_default_identity_pins_en_us(self, isolated_launch_dependencies):
        assert self._prefs()[self.PREF] == "en-US"

    def test_spoofed_locale_selects_matching_ui_locale(self, isolated_launch_dependencies):
        # handle_locale adds the likely script; Gecko's filtering negotiation
        # treats a packaged "fr" as a range, so fr-Latn-FR still selects fr.
        assert self._prefs(locale="fr-FR")[self.PREF] == "fr-Latn-FR"
        assert self._prefs(locale="pt-BR")[self.PREF] == "pt-Latn-BR"

    def test_first_of_several_locales_wins(self, isolated_launch_dependencies):
        assert self._prefs(locale="de-DE, en-US")[self.PREF] == "de-Latn-DE"

    def test_geoip_style_config_locale_is_used(self, isolated_launch_dependencies):
        config = {"locale:language": "ja", "locale:region": "JP"}
        assert self._prefs(config=config)[self.PREF] == "ja-JP"

    def test_script_subtag_is_kept(self, isolated_launch_dependencies):
        config = {"locale:language": "zh", "locale:script": "Hant", "locale:region": "TW"}
        assert self._prefs(config=config)[self.PREF] == "zh-Hant-TW"

    def test_caller_pref_wins(self, isolated_launch_dependencies):
        prefs = self._prefs(locale="fr-FR", firefox_user_prefs={self.PREF: "de"})
        assert prefs[self.PREF] == "de"


class TestToggleSettingsAreWrittenBothWays:
    """A persistent profile keeps every pref it was ever launched with.

    Firefox saves a user.js pref into prefs.js, and a later launch that simply
    omits it does not clear it. A profile once launched with block_webrtc kept
    WebRTC off after the flag was removed (a real profile's prefs.js still held
    media.peerconnection.enabled=false), so each toggle writes its pref on every
    launch, on or off.
    """

    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0"
    TOGGLES = [
        ("block_webrtc", "media.peerconnection.enabled", True, False),
        ("block_images", "permissions.default.image", 1, 2),
        ("disable_coop", "browser.tabs.remote.useCrossOriginOpenerPolicy", True, False),
    ]

    def _prefs(self, **kwargs):
        return utils.launch_options(
            config={"navigator.userAgent": self.UA}, i_know_what_im_doing=True, **kwargs
        )["firefox_user_prefs"]

    @pytest.mark.parametrize("flag, pref, stock, toggled", TOGGLES)
    def test_off_writes_the_stock_value(self, isolated_launch_dependencies, flag, pref, stock, toggled):
        assert self._prefs()[pref] == stock

    @pytest.mark.parametrize("flag, pref, stock, toggled", TOGGLES)
    def test_on_writes_the_toggled_value(self, isolated_launch_dependencies, flag, pref, stock, toggled):
        assert self._prefs(**{flag: True})[pref] == toggled

    @pytest.mark.parametrize("flag, pref, stock, toggled", TOGGLES)
    def test_caller_pref_wins(self, isolated_launch_dependencies, flag, pref, stock, toggled):
        assert self._prefs(firefox_user_prefs={pref: toggled})[pref] == toggled


class TestPrefsReachStartup:
    """Launcher prefs must be readable by camoufox.cfg at startup.

    Playwright's non-persistent launch writes no user.js, so firefox_user_prefs
    only arrived via juggler after startup; intl.locale.requested lost the race
    against Gecko's pre-created string bundles on Windows.
    """

    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0"

    def test_prefs_are_passed_as_env(self, isolated_launch_dependencies):
        import orjson

        opts = utils.launch_options(config={"navigator.userAgent": self.UA}, locale="fr-FR", i_know_what_im_doing=True)
        chunks = sorted((k for k in opts["env"] if k.startswith("CAMOU_PREFS_")), key=lambda k: int(k.rsplit("_", 1)[1]))
        assert chunks and chunks[0] == "CAMOU_PREFS_1"
        prefs = orjson.loads("".join(opts["env"][k] for k in chunks))
        assert prefs == opts["firefox_user_prefs"]
        assert prefs["intl.locale.requested"] == "fr-Latn-FR"

    def test_large_prefs_are_chunked_in_order(self, monkeypatch):
        import orjson

        monkeypatch.setattr(utils, "OS_NAME", "win")
        prefs = {f"camoufox.test.pref{i}": "x" * 50 for i in range(200)}
        env = utils.get_pref_env_vars(prefs)
        assert len(env) > 1 and all(len(v) <= 2047 for v in env.values())
        joined = "".join(env[f"CAMOU_PREFS_{i}"] for i in range(1, len(env) + 1))
        assert orjson.loads(joined) == prefs

    def test_no_prefs_no_env(self):
        assert utils.get_pref_env_vars({}) == {}


class TestWindowsScrollbarsFollowVersion:
    """Windows 11 draws overlay scrollbars by default (stock 152.0.4 on Win11: 0 px),
    Windows 10 classic 17 px ones; the identity's font draw decides the version."""

    PREF = "ui.useOverlayScrollbars"
    WIN_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0"

    def _prefs(self, fonts, ua=None):
        return utils.launch_options(
            config={"navigator.userAgent": ua or self.WIN_UA, "fonts": fonts},
            i_know_what_im_doing=True,
        )["firefox_user_prefs"]

    def test_windows_11_fonts_get_overlay(self, isolated_launch_dependencies):
        assert self._prefs(["Arial", "Segoe UI Variable Text"])[self.PREF] == 1

    def test_windows_10_fonts_get_classic(self, isolated_launch_dependencies):
        assert self._prefs(["Arial", "Segoe UI", "Calibri"])[self.PREF] == 0

    def test_other_oses_overlay(self, isolated_launch_dependencies):
        ua = "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0"
        assert self._prefs(["DejaVu Sans"], ua=ua)[self.PREF] == 1

    def test_marker_set_is_the_font_model(self):
        from camoufox.fingerprints import _BASE_VARIANT_FONTS_WINDOWS, WINDOWS_11_MARKER_FONTS
        assert WINDOWS_11_MARKER_FONTS == frozenset(_BASE_VARIANT_FONTS_WINDOWS[1])


class TestNativeWindowsVariantFonts:
    """A native Windows identity claims the Win11 font variant iff the host has it."""

    def test_native_windows_11_host_claims_variant(self, monkeypatch):
        from camoufox import fingerprints as fp
        monkeypatch.setattr(fp, "_host_has_variant_fonts", lambda target_os: True)
        fonts = fp._generate_random_font_subset("windows", seed=1, native=True)
        assert fp.WINDOWS_11_MARKER_FONTS <= set(fonts)

    def test_native_windows_10_host_does_not(self, monkeypatch):
        from camoufox import fingerprints as fp
        monkeypatch.setattr(fp, "_host_has_variant_fonts", lambda target_os: False)
        fonts = fp._generate_random_font_subset("windows", seed=1, native=True)
        assert not (fp.WINDOWS_11_MARKER_FONTS & set(fonts))

    def test_non_windows_hosts_never_report_variant(self):
        from camoufox import fingerprints as fp
        assert fp._host_has_variant_fonts("linux") is False
        assert fp._host_has_variant_fonts("macos") is False


class _Usage:
    """shutil.disk_usage's namedtuple, with only `total` filled in."""

    def __init__(self, total):
        self.total = total
        self.used = 0
        self.free = total


class TestStorageQuotaFollowsHostDisk:
    """The storage quota a page reads must be the host's, not a constant.

    Gecko derives navigator.storage.estimate().quota from the disk: the
    temporary-storage limit is GetDiskCapacity() / 2 and the group limit a page
    reads is min(that / 5, 10 GiB). camoufox.cfg used to pin the limit to
    52428800 KB -- 50 GiB, which is exactly nsRFPService::GetSpoofedStorageLimit()
    and reports 10 GiB on every host whatever its disk holds.

    Deriving it from the host keeps the shape Gecko produces (a 100 GB+ disk
    reports the 10 GiB cap, a smaller one reports capacity / 10) while ignoring
    the disk Playwright's throwaway profile happens to land on -- a tmpfs /tmp
    is a RAM-sized volume no real profile lives on.
    """

    PREF = "dom.quotaManager.temporaryStorage.fixedLimit"
    UA = "Mozilla/5.0 (X11; Linux x86_64; rv:152.0) Gecko/20100101 Firefox/152.0"

    def _prefs(self, **kwargs):
        return utils.launch_options(
            config={"navigator.userAgent": self.UA},
            i_know_what_im_doing=True,
            **kwargs,
        )["firefox_user_prefs"]

    def test_limit_is_half_the_host_disk(self, monkeypatch, isolated_launch_dependencies):
        # 512 GiB, the way a filesystem reports it: a multiple of the block size.
        capacity = 512 * 1024**3
        monkeypatch.setattr(utils.shutil, "disk_usage", lambda _p: _Usage(capacity))
        assert self._prefs()[self.PREF] == capacity // 2 // 1024

    def test_small_disk_reports_less_than_the_cap(
        self, monkeypatch, isolated_launch_dependencies
    ):
        # A 40 GB VPS: stock reports 4 GB, not the 10 GiB cap. The old pin
        # claimed 10 GiB here, which that machine's own Firefox never says.
        capacity = 40 * 1000**3
        monkeypatch.setattr(utils.shutil, "disk_usage", lambda _p: _Usage(capacity))
        limit_kb = self._prefs()[self.PREF]
        group_limit = min(limit_kb * 1024 // 5, 10 * 1024**3)
        assert group_limit == capacity // 2 // 5
        assert group_limit < 10 * 1024**3

    def test_multi_terabyte_disk_stays_in_int32(
        self, monkeypatch, isolated_launch_dependencies
    ):
        monkeypatch.setattr(utils.shutil, "disk_usage", lambda _p: _Usage(16 * 1024**4))
        limit_kb = self._prefs()[self.PREF]
        assert limit_kb <= 2**31 - 1
        # Still above 50 GiB, so the page reads the same 10 GiB cap stock does.
        assert limit_kb * 1024 // 5 >= 10 * 1024**3

    def test_unreadable_disk_leaves_gecko_to_measure(
        self, monkeypatch, isolated_launch_dependencies
    ):
        def _raise(_p):
            raise OSError("no such device")

        monkeypatch.setattr(utils.shutil, "disk_usage", _raise)
        assert self.PREF not in self._prefs()

    def test_caller_pref_wins(self, monkeypatch, isolated_launch_dependencies):
        monkeypatch.setattr(utils.shutil, "disk_usage", lambda _p: _Usage(512 * 1024**3))
        prefs = self._prefs(firefox_user_prefs={self.PREF: 1234})
        assert prefs[self.PREF] == 1234


class TestStockMediaDefaults:
    """The host's own media features, not Playwright's emulated ones.

    Playwright emulates four media features on every context whether or not the
    caller asked: colorScheme "light", and no-preference values for
    reducedMotion / forcedColors / contrast. The page then reads those whatever
    the machine is set to -- measured 2026-09-18, headed on an Xvfb with
    GTK_THEME=Adwaita:dark: stock Firefox reported
    `(prefers-color-scheme: dark)`, camoufox reported light.

    "no-override" is Playwright's opt-out: no emulation is sent and the browser
    answers from the host.
    """

    def test_defaults_are_no_override(self):
        assert utils.STOCK_MEDIA_DEFAULTS == {
            "color_scheme": "no-override",
            "reduced_motion": "no-override",
            "forced_colors": "no-override",
            "contrast": "no-override",
        }

    def test_new_page_and_new_context_get_them(self):
        class FakeBrowser:
            def __init__(self):
                self.calls = []

            def new_page(self, **kwargs):
                self.calls.append(("new_page", kwargs))

            def new_context(self, **kwargs):
                self.calls.append(("new_context", kwargs))

        browser = FakeBrowser()
        utils.attach_stock_media_defaults(browser)
        browser.new_page()
        browser.new_context()
        for _, kwargs in browser.calls:
            assert kwargs["color_scheme"] == "no-override"
            assert kwargs["reduced_motion"] == "no-override"
            assert kwargs["forced_colors"] == "no-override"
            assert kwargs["contrast"] == "no-override"

    def test_caller_value_wins(self):
        class FakeBrowser:
            def __init__(self):
                self.kwargs = None

            def new_context(self, **kwargs):
                self.kwargs = kwargs

        browser = FakeBrowser()
        utils.attach_stock_media_defaults(browser)
        browser.new_context(color_scheme="dark", forced_colors="active")
        assert browser.kwargs["color_scheme"] == "dark"
        assert browser.kwargs["forced_colors"] == "active"
        # the ones the caller left alone still follow the host
        assert browser.kwargs["reduced_motion"] == "no-override"


class TestDesktopOnlyWarning:
    """Camoufox has only desktop identities and Juggler never enters Responsive
    Design Mode, so is_mobile on new_page()/new_context() gets a LeakWarning."""

    class FakeBrowser:
        def new_page(self, **kwargs):
            return kwargs

        def new_context(self, **kwargs):
            return kwargs

    def test_is_mobile_warns(self):
        from camoufox._warnings import LeakWarning

        browser = utils.attach_desktop_only_warning(self.FakeBrowser())
        for create in (browser.new_page, browser.new_context):
            with pytest.warns(LeakWarning, match="built for desktops"):
                assert create(is_mobile=True) == {"is_mobile": True}

    def test_a_desktop_context_does_not(self):
        import warnings

        browser = utils.attach_desktop_only_warning(self.FakeBrowser())
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            browser.new_context(viewport={"width": 800, "height": 600}, is_mobile=False)
            browser.new_page()
