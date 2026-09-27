"""Per-identity draws: unrelated launches must not share them, a pinned identity must.

identity_seed() used to hash only the UA, platform, screen size and core count.
Those take a handful of values per OS, so over 500 launches the seed took 12-30
distinct values, and every install drew its fonts, voices, GPU, media devices and
canvas/audio noise seeds from that same short list.
"""

from contextlib import contextmanager
from unittest import mock

import orjson
import pytest

from camoufox import cpu_affinity, utils
from camoufox import fingerprints as fp


@contextmanager
def host():
    with mock.patch.object(utils, "get_screen_cons", lambda headless: None), (
        mock.patch.object(utils, "has_display", lambda env: False)
    ), mock.patch.object(utils, "installed_verstr", lambda: "150.0.2"), (
        mock.patch.object(utils, "launch_path", lambda **kwargs: "/nonexistent/camoufox")
    ):
        yield


def config_of(options):
    env = options["env"]
    chunks = sorted(
        (int(k.rsplit("_", 1)[1]), v) for k, v in env.items() if k.startswith("CAMOU_CONFIG_")
    )
    return orjson.loads("".join(chunk for _, chunk in chunks))


def launch(**kwargs):
    kwargs.setdefault("os", "linux")
    kwargs.setdefault("headless", True)
    kwargs.setdefault("i_know_what_im_doing", True)
    with host():
        return config_of(utils.launch_options(**kwargs))


DRAWN = ("audio:seed", "fonts", "voices", "webGl:renderer")


def drawn(config):
    return {k: orjson.dumps(config.get(k)) for k in DRAWN}


class TestUnpinnedLaunchesAreDistinct:
    def test_noise_seeds_do_not_collide(self):
        seeds = [launch()["audio:seed"] for _ in range(40)]
        # 40 draws from 2**32: any collision means the seed space collapsed.
        assert len(set(seeds)) == len(seeds)

    def test_same_presented_values_still_differ(self):
        # The same UA/platform/screen/cores, i.e. what two users on the same
        # common machine present, must not yield the same noise seeds.
        config = {"navigator.userAgent": "x", "navigator.platform": "Win32",
                  "screen.width": 1920, "screen.height": 1080, "navigator.hardwareConcurrency": 8}
        seeds = {fp.identity_seed(config, fp.identity_salt()) for _ in range(200)}
        assert len(seeds) == 200


class TestPinnedIdentityIsStable:
    def test_fixed_fingerprint_reproduces_every_draw(self):
        fingerprint = fp.generate_fingerprint(os="linux")
        first = launch(fingerprint=fingerprint)
        second = launch(fingerprint=fingerprint)
        assert drawn(first) == drawn(second)

    def test_fixed_preset_reproduces_noise_seeds(self):
        preset = fp.get_random_preset(os="windows", ff_version="150")
        if not preset:
            pytest.skip("no presets bundled")
        first = launch(os="windows", fingerprint_preset=preset)
        second = launch(os="windows", fingerprint_preset=preset)
        assert first["audio:seed"] == second["audio:seed"]
        assert first["fonts"] == second["fonts"]

    @pytest.mark.parametrize("os_name", ["windows", "macos", "linux"])
    def test_every_bundled_preset_launches(self, os_name):
        # The test above draws ONE preset at random, so a preset that cannot
        # launch would show up as a flake rather than a failure. Every preset
        # must launch with its own GPU and that GPU's recorded parameters.
        presets = fp.load_presets("150")["presets"][os_name]
        for i, preset in enumerate(presets):
            config = launch(os=os_name, fingerprint_preset=preset)
            assert config["webGl:renderer"] == preset["webgl"]["unmaskedRenderer"], (os_name, i)
            assert config.get("webGl:parameters"), (os_name, i)

    def test_caller_seed_is_kept(self):
        assert launch(config={"audio:seed": 9})["audio:seed"] == 9


def test_no_canvas_seed_is_generated():
    """The browser adds no canvas noise (#528), and no patch reads canvas:seed
    (#721). Generating one only sent the browser a value it ignored."""
    assert "canvas:seed" not in launch()
    context = fp.generate_context_fingerprint(os="linux")
    assert "canvas:seed" not in context["config"]
    assert "setCanvasSeed" not in context["init_script"]

    def test_salt_of_equal_objects_is_equal(self):
        a = fp.generate_fingerprint(os="windows")
        assert fp.identity_salt(a) == fp.identity_salt(a)
        assert fp.identity_salt({"a": 1, "b": 2}) == fp.identity_salt({"b": 2, "a": 1})


class TestVoicesFollowLocale:
    def test_windows_fr_identity_has_french_voices(self, monkeypatch):
        for _ in range(5):
            config = launch(os="windows", locale="fr-FR")
            langs = {v["lang"] for v in config["voices"]}
            assert "fr-FR" in langs, langs


class TestCoreCountFloor:
    def test_small_pinnable_host_reports_table_floor(self, monkeypatch):
        monkeypatch.setattr(cpu_affinity, "supported", lambda: True)
        for host_cores in (1, 2, 3):
            monkeypatch.setattr(fp, "host_cpu_count", lambda n=host_cores: n)
            for drawn_cores in (1, 2, 3, 8):
                c = {"navigator.hardwareConcurrency": drawn_cores}
                fp.fix_hardware_concurrency(c)
                assert c["navigator.hardwareConcurrency"] == 4, (host_cores, drawn_cores)

    def test_unpinned_launch_reports_host(self, monkeypatch):
        monkeypatch.setattr(cpu_affinity, "supported", lambda: True)
        monkeypatch.setattr(fp, "host_cpu_count", lambda: 16)
        c = {"navigator.hardwareConcurrency": 8}
        fp.fix_hardware_concurrency(c, can_pin=False)
        assert c["navigator.hardwareConcurrency"] == 16

    def test_recorded_counts_are_in_the_table(self):
        for n in (18, 22, 28, 32):
            assert n in fp.PLAUSIBLE_CORE_COUNTS


class TestAffinityPick:
    def test_adjacent_cores_from_a_random_start(self):
        cores = list(range(16))
        starts = set()
        for _ in range(200):
            picked = cpu_affinity._pick(cores, 4)
            assert len(picked) == 4 and set(picked) <= set(cores)
            ring = sorted(picked)
            # adjacent modulo 16
            assert any(all((s + i) % 16 in picked for i in range(4)) for s in ring)
            starts.add(tuple(picked))
        assert len(starts) > 4


class TestPrefsEnvIsAscii:
    def test_non_ascii_pref_round_trips(self):
        prefs = {"font.name.serif.ja": "游明朝", "intl.accept_languages": "fr-FR, fr"}
        env = utils.get_pref_env_vars(prefs)
        joined = "".join(env[f"CAMOU_PREFS_{i}"] for i in range(1, len(env) + 1))
        assert joined.isascii()
        assert orjson.loads(joined) == prefs


@pytest.mark.parametrize("off", [None, False])
def test_fingerprint_preset_off_never_draws_a_preset(off):
    """`fingerprint_preset=False` means off, the same as None. It used to be
    checked with `is not None`, so False drew a random bundled preset."""
    with mock.patch.object(utils, "get_random_preset", side_effect=AssertionError("preset drawn")):
        launch(fingerprint_preset=off)


def test_no_glyph_spacing_seed_is_generated():
    """Glyph-spacing noise moved every measured text width off what the same
    font gives on a real machine, so it was itself a fingerprint; the feature
    is gone from the browser, and the launcher sends nothing for it."""
    assert "fonts:spacing_seed" not in launch()
    context = fp.generate_context_fingerprint(os="linux")
    assert "fonts:spacing_seed" not in context["config"]
    assert "setFontSpacingSeed" not in context["init_script"]


def test_config_overrides_reach_the_config_and_the_init_script():
    context = fp.generate_context_fingerprint(os="linux", config_overrides={"audio:seed": 7})
    assert context["config"]["audio:seed"] == 7
    assert "setAudioFingerprintSeed(7)" in context["init_script"]


def test_instant_animations_warn_that_they_are_detectable():
    from camoufox._warnings import LeakWarning

    with pytest.warns(LeakWarning, match="getComputedTiming"):
        launch(config={"instantAnimations": True}, i_know_what_im_doing=False)


def test_is_mobile_warns_that_camoufox_is_desktop_only():
    """A persistent context takes its context options at launch."""
    from camoufox._warnings import LeakWarning

    with pytest.warns(LeakWarning, match="built for desktops"):
        launch(is_mobile=True, i_know_what_im_doing=False)


def test_a_context_with_a_linux_ua_is_linux_throughout(monkeypatch):
    """fpgen's Linux pool now and then pairs the Linux UA with platform Win32 and
    a Windows oscpu (~1.6% of NewContext Linux identities). launch_options()
    fixed that and generate_context_fingerprint() did not -- and it reads the OS
    for fonts and voices from the platform, so those came out Windows too."""
    real = fp.generate_fingerprint

    def mismatched(**kwargs):
        drawn = real(**kwargs)
        drawn["navigator"]["platform"] = "Win32"
        drawn["navigator"]["oscpu"] = "Windows NT 10.0; Win64; x64"
        return drawn

    monkeypatch.setattr(fp, "generate_fingerprint", mismatched)
    config = fp.generate_context_fingerprint(os="linux")["config"]

    assert "Linux x86_64" in config["navigator.userAgent"]
    assert config["navigator.platform"] == "Linux x86_64"
    assert config["navigator.oscpu"] == "Linux x86_64"
    assert "Segoe UI" not in config["fonts"]
