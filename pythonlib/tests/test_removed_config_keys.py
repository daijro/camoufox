"""
A config key the browser no longer reads stays in settings/properties.json,
marked "removed" (#835).

Libraries up to 0.4.x raise UnknownProperty on any key the installed browser's
properties.json does not declare, and they still send navigator.appCodeName and
the other keys #787 deleted, so every release after that failed to launch under
them. Keeping the entries fixes those libraries; this library must in turn not
validate a removed key as a live one, and must say that it has no effect.
"""

import json

from camoufox.utils import validate_config


def _browser_with(tmp_path, entries):
    (tmp_path / "properties.json").write_text(json.dumps(entries))
    return tmp_path / "camoufox-bin"


def test_a_removed_key_is_skipped_with_its_release(tmp_path, capsys):
    binary = _browser_with(tmp_path, [
        {"property": "navigator.userAgent", "type": "str"},
        {"property": "navigator.appCodeName", "type": "str", "removed": "156.0.1-beta.32"},
    ])
    validate_config({"navigator.appCodeName": "Mozilla", "navigator.userAgent": "x"}, path=binary)
    assert "navigator.appCodeName: removed in 156.0.1-beta.32" in capsys.readouterr().out


def test_a_removed_key_is_not_type_checked(tmp_path):
    """Its type is whatever older libraries sent; it is never validated again."""
    binary = _browser_with(tmp_path, [
        {"property": "navigator.languages", "type": "array", "removed": "156.0.1-beta.32"},
    ])
    validate_config({"navigator.languages": "not-an-array"}, path=binary)
