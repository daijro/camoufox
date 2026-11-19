"""A caller's user agent alone does not keep the drawn platform.

Setting navigator.userAgent marked the whole navigator domain as the caller's,
so fix_navigator_arch never ran. fpgen's Linux pool holds draws whose platform
is another OS's beside a Linux oscpu, and those reached the page as Win32
behind a Linux user agent. Only a caller's own navigator.platform or
navigator.oscpu stands the fix down.
"""

import pytest

from camoufox import fingerprints as fp
from camoufox import utils

from test_launch_environment import isolated_launch_dependencies  # noqa: F401

LIN_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:158.0) Gecko/20100101 Firefox/158.0"


@pytest.fixture
def launch(monkeypatch, isolated_launch_dependencies):  # noqa: F811
    """launch_options on a Linux host; returns (config, prefs)."""
    monkeypatch.setattr(utils, "_host_os_key", lambda: "lin")
    seen = {}

    def capture(config, *args, **kwargs):
        seen["config"] = dict(config)
        return {}

    monkeypatch.setattr(utils, "get_env_vars", capture)

    def run(ua, **kwargs):
        config = {"navigator.userAgent": ua, **kwargs.pop("config", {})}
        prefs = utils.launch_options(config=config, i_know_what_im_doing=True, **kwargs)["firefox_user_prefs"]
        return seen["config"], prefs

    return run


def test_a_caller_user_agent_alone_still_fixes_the_drawn_platform(
    launch, monkeypatch
):
    """A Linux draw can carry another OS's platform beside its Linux oscpu.
    The caller set only the user agent, so platform and oscpu follow it."""
    monkeypatch.setattr(utils, "from_fpgen", fp.from_fpgen)
    monkeypatch.setattr(utils, "fix_navigator_arch", fp.fix_navigator_arch)
    fingerprint = fp.generate_fingerprint(os="linux")
    fingerprint["navigator"]["platform"] = "Win32"
    config, _ = launch(LIN_UA, fingerprint=fingerprint)

    assert config["navigator.platform"] == "Linux x86_64"
    assert config["navigator.oscpu"] == "Linux x86_64"


def test_a_callers_platform_is_kept_when_the_user_agent_is_set(
    launch, monkeypatch
):
    monkeypatch.setattr(utils, "fix_navigator_arch", fp.fix_navigator_arch)
    config, _ = launch(
        LIN_UA, config={"navigator.platform": "Linux i686"}
    )

    assert config["navigator.platform"] == "Linux i686"
