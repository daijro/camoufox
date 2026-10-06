"""
Camoufox version constants.
"""


class CONSTRAINTS:
    """
    The minimum and maximum supported versions of the Camoufox browser.
    """

    MIN_VERSION = 'alpha.1'
    MAX_VERSION = '1'

    # The browser floor is conditional on the resolved Playwright, not fixed.
    #
    # Each entry is (playwright_version, required_browser_build): from that
    # Playwright on, the browser must be at least that build. 1.61 began
    # sending viewport isMobile/screenSize in Browser.setDefaultViewport and
    # Page.setViewportSize; beta.30 is the first build whose Protocol.js schema
    # accepts them. Below that pairing every new_context() dies with
    # "Protocol error (Browser.setDefaultViewport)". Measured: 1.60 works on
    # beta.29 and beta.30; 1.61 and 1.62 fail on beta.29 and pass on beta.30.
    #
    # A flat MIN_VERSION cannot express this. It only knows about the browser,
    # so to stay safe it has to assume the worst Playwright and force *every*
    # user to re-download -- including the majority on <1.61, who are in no
    # danger -- and it leaves the library unusable until the matching browser
    # release is published. Keyed on Playwright, only the users who would
    # actually break get moved.
    PLAYWRIGHT_BROWSER_FLOORS = (((1, 61), 'beta.30'),)

    # The browser interface built from this tree. Every browser release
    # declares it in its manifest.json (ci/release.py reads it from here), and
    # this library accepts browsers from MIN_INTERFACE up to it. Raise it when a
    # browser change would break released libraries; raise MIN_INTERFACE when
    # this library can no longer drive older browsers. Releases from before
    # manifests carried the field are interface 1.
    INTERFACE = 1
    MIN_INTERFACE = 1

