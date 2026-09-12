"""Camoufox's test pipeline.

Everything that *runs* a suite and reports what happened lives here, and is
driven identically from a pull request, a push to main, and -- through
`workflow_call` -- any caller that needs to test a specific browser version.
That is deliberate: a version bump should be provable by running the same checks
a contributor's pull request runs, so there is exactly one definition of "the
tests pass".

  versions.py       which browser build, and which Playwright suite tests it
  suite.py          fetch and prepare that Playwright suite
  skiplist.yml      tests Camoufox cannot pass by design, each with a reason
  pw_camoufox_plugin.py   main-world execution, binary selection, skips, sharding
  run_*.py          one runner per suite; each writes one result file
  summarize.py      fold the result files into a verdict and a readable table
"""
