import pytest


@pytest.fixture(autouse=True)
def no_host_gpu_probe(monkeypatch):
    """launch_options launches the browser to read the host's GPU when an
    identity claims the host's OS. This suite has no browser, and its results
    must not depend on the machine running it, so the host reads as having no
    WebGL. Tests of the probe's consumers patch it themselves."""
    from camoufox import utils

    monkeypatch.setattr(utils, 'host_gpu', lambda *args: None)
