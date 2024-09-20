from typing import Any, Dict, List, Optional, Union

from browserforge.fingerprints import Fingerprint, Screen
from playwright.async_api import Browser, Playwright, PlaywrightContextManager

from .addons import DefaultAddons
from .utils import ListOrString, get_launch_options


class AsyncCamoufox(PlaywrightContextManager):
    """
    Wrapper around playwright.async_api.PlaywrightContextManager that automatically
    launches a browser and closes it when the context manager is exited.
    """

    def __init__(self, **launch_options):
        super().__init__()
        self.launch_options = launch_options
        self.browser: Optional[Browser] = None

    async def __aenter__(self) -> Browser:
        _playwright = await super().__aenter__()
        self.browser = await AsyncNewBrowser(_playwright, **self.launch_options)
        return self.browser

    async def __aexit__(self, *args: Any):
        if self.browser:
            await self.browser.close()
        await super().__aexit__(*args)


async def AsyncNewBrowser(
    playwright: Playwright,
    *,
    config: Optional[Dict[str, Any]] = None,
    addons: Optional[List[str]] = None,
    fingerprint: Optional[Fingerprint] = None,
    exclude_addons: Optional[List[DefaultAddons]] = None,
    screen: Optional[Screen] = None,
    os: Optional[ListOrString] = None,
    user_agent: Optional[ListOrString] = None,
    fonts: Optional[List[str]] = None,
    args: Optional[List[str]] = None,
    executable_path: Optional[str] = None,
    block_images: Optional[bool] = None,
    block_webrtc: Optional[bool] = None,
    firefox_user_prefs: Optional[Dict[str, Any]] = None,
    env: Optional[Dict[str, Union[str, float, bool]]] = None,
    **launch_options: Dict[str, Any]
) -> Browser:
    """
    Launches a new browser instance for Camoufox.

    Parameters:
        playwright (Playwright):
            Playwright instance to use.
        config (Optional[Dict[str, Any]]):
            Configuration to use.
        addons (Optional[List[str]]):
            Addons to use.
        fingerprint (Optional[Fingerprint]):
            BrowserForge fingerprint to use.
        exclude_addons (Optional[List[DefaultAddons]]):
            Default addons to exclude. Passed as a list of camoufox.DefaultAddons enums.
        screen (Optional[browserforge.fingerprints.Screen]):
            BrowserForge screen constraints to use.
        os (Optional[ListOrString]):
            Operating system to use for the fingerprint. Either a string or a list of strings.
        user_agent (Optional[ListOrString]):
            User agent to use for the fingerprint. Either a string or a list of strings.
        fonts (Optional[List[str]]):
            Fonts to load into Camoufox, in addition to the default fonts.
        args (Optional[List[str]]):
            Arguments to pass to the browser.
        block_images (Optional[bool]):
            Whether to block all images.
        block_webrtc (Optional[bool]):
            Whether to block WebRTC entirely.
        firefox_user_prefs (Optional[Dict[str, Any]]):
            Firefox user preferences to set.
        env (Optional[Dict[str, Union[str, float, bool]]]):
            Environment variables to set.
        executable_path (Optional[str]):
            Custom Camoufox browser executable path.
        **launch_options (Dict[str, Any]):
            Additional Firefox launch options.
    """
    opt = get_launch_options(
        config=config,
        addons=addons,
        fingerprint=fingerprint,
        exclude_addons=exclude_addons,
        screen=screen,
        os=os,
        user_agent=user_agent,
        fonts=fonts,
        args=args,
        executable_path=executable_path,
        env=env,
        block_images=block_images,
        block_webrtc=block_webrtc,
        firefox_user_prefs=firefox_user_prefs,
    )
    return await playwright.firefox.launch(**opt, **launch_options)
