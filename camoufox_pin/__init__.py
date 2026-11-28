"""The browser release this `camoufox` package was released with.

Data only: `browser-pin.json` beside this file names the one browser release
built from the same sources as this package (see browser_pin in the driver,
https://github.com/CamouBrowser/camoucore). A development checkout carries
`{}`, which pins nothing. Read it as

    importlib.resources.files("camoufox_pin") / "browser-pin.json"
"""
