import pytest


@pytest.fixture(autouse=True)
def _first_attempt(monkeypatch):
    """Run every test as a first attempt, whatever job runs the suite.

    A re-run job sets GITHUB_RUN_ATTEMPT, which renames saved evidence to
    `<gate>.attemptN.json`; tests that read `<gate>.json` then fail only on
    re-runs. Tests about re-runs set the variable themselves.
    """
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)
