"""A context's user agent carries the Firefox version of the browser it runs in.

Without an explicit ff_version, NewContext kept whatever version fpgen drew
(e.g. Firefox/146) on a 160 browser, so the UA disagreed with every
version-dependent API the page could probe.
"""

import asyncio
import re
from unittest import mock

import pytest

from camoufox import async_api, sync_api


def _user_agent(init_script):
    return re.search(r'setNavigatorUserAgent\("([^"]+)"\)', init_script).group(1)


@pytest.mark.parametrize("api", ["sync", "async"])
def test_user_agent_matches_the_browser_version(api):
    context = mock.MagicMock()
    browser = mock.MagicMock()
    # Playwright's Browser.version for Firefox: MOZ_APP_VERSION_DISPLAY.
    browser.version = "160.0.1"
    if api == "sync":
        browser.new_context.return_value = context
        sync_api.NewContext(browser, os="linux")
    else:
        context.add_init_script = mock.AsyncMock()
        browser.new_context = mock.AsyncMock(return_value=context)
        asyncio.run(async_api.AsyncNewContext(browser, os="linux"))

    user_agent = _user_agent(context.add_init_script.call_args.args[0])
    assert "Firefox/160.0" in user_agent and "rv:160.0" in user_agent, user_agent
