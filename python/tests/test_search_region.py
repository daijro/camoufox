from camoufox import utils

from test_launch_environment import isolated_launch_dependencies  # noqa: F401  (fixture)


def _prefs(**kwargs):
    kwargs.setdefault('i_know_what_im_doing', True)
    return utils.launch_options(**kwargs)['firefox_user_prefs']


def test_search_region_follows_the_locale_region(isolated_launch_dependencies):
    assert _prefs(locale='de-DE')['browser.search.region'] == 'DE'


def test_no_search_region_without_one(isolated_launch_dependencies):
    assert 'browser.search.region' not in _prefs(config={'locale:language': 'en'})


def test_search_region_caller_pref_wins(isolated_launch_dependencies):
    prefs = _prefs(locale='de-DE', firefox_user_prefs={'browser.search.region': 'AT'})
    assert prefs['browser.search.region'] == 'AT'
