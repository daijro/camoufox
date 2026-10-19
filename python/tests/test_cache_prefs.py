from camoufox.utils import CACHE_PREFS


def test_enable_cache_leaves_history_length_at_stock():
    # history.length is page-readable; enable_cache capped it at 10 where stock
    # Firefox keeps 50 entries (browser/settings/camoufox.cfg pins the stock value).
    assert 'browser.sessionhistory.max_entries' not in CACHE_PREFS
