# Camoufox's own Playwright tests

Tests for behaviour that is **specific to Camoufox** and therefore has no
upstream equivalent -- either because upstream never tested it, or because
upstream tests for the stock-Firefox behaviour that this fork deliberately does
not have.

These are not a fork of anything. `ci/suite.py` copies them into the upstream
playwright-python checkout it prepares for each run (`tests/async/`), so they
execute against **upstream's current harness** -- its `conftest.py`, its
`server.py`, its fixtures -- at whatever tag `ci/versions.py` resolved. Nothing
here is frozen, so nothing here goes stale the way a vendored suite does.

Write a test here when, and only when, one of these is true:

- **Camoufox has a behaviour upstream has no test for.** `test_route_request_fingerprint.py`
  is the example: enabling request interception must not change what a request
  looks like on the wire (daijro/camoufox#428, #271). Stock Playwright does not
  care, so upstream has nothing to say about it.

- **Upstream asserts the stock-Firefox behaviour and Camoufox is right not to
  match it.** `test_worker_locale.py` is the example: upstream expects a worker
  to *ignore* the context locale (microsoft/playwright#38919); Camoufox sets the
  locale below that layer, so its workers agree with the main thread. The
  upstream test is skiplisted in `ci/skiplist.yml` and the version here takes
  over guarding the behaviour.

In the second case the `ci/skiplist.yml` entry must name the test that replaces
it, so a skip can never quietly mean "nothing checks this any more".

Everything else belongs upstream, where it is maintained for free.
