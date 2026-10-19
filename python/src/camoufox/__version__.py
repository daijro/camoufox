"""
Camoufox version constants.
"""


class CONSTRAINTS:
    """
    The minimum and maximum supported versions of the Camoufox browser.
    """

    MIN_VERSION = 'alpha.1'
    MAX_VERSION = '1'

    # (playwright_version, required_browser_build): from that Playwright on, the
    # browser must be at least that build. Playwright 1.61 sends viewport fields
    # only beta.30's Juggler schema accepts; keying the floor on Playwright moves
    # only the users who would break, where a flat MIN_VERSION would move all.
    PLAYWRIGHT_BROWSER_FLOORS = (((1, 61), 'beta.30'),)

    # The browser interface built from this tree. Every browser release
    # declares it in its manifest.json (ci/release.py reads it from here), and
    # this library accepts browsers from MIN_INTERFACE up to it. Raise it when a
    # browser change would break released libraries; raise MIN_INTERFACE when
    # this library can no longer drive older browsers. Releases from before
    # manifests carried the field are interface 1.
    INTERFACE = 1
    MIN_INTERFACE = 1

