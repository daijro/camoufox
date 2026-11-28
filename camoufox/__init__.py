"""camoufox: the Camoufox launcher, under its own name.

The `camoufox` release wrapper (https://github.com/daijro/camoufox) carries no
launcher code: everything here is camoucore.camoufox from
https://github.com/CamouBrowser/camoucore, at the one release pyproject.toml
pins, so `import camoufox.sync_api` and `camoucore.camoufox.sync_api` are the
same module. The layout follows camoucore's RELEASING.md, "The wrapper
packages"; launcher changes go to camoucore.
"""

import camoucore.camoufox as _impl
from camoucore.camoufox import *  # noqa: F403
from camoucore.camoufox import __all__  # noqa: F401


def __getattr__(name):
    return getattr(_impl, name)
