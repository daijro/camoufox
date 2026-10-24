"""browser/scripts/_mixin.py: the Rust release a build uses is Mozilla's for the tree."""

import sys

import pytest

from ci._util import BROWSER_ROOT

sys.path.insert(0, str(BROWSER_ROOT / "scripts"))
from _mixin import mozilla_rust_version  # noqa: E402

# The shape of Firefox 158's taskcluster/kinds/toolchain/rust.yml: an older
# floor, a by-project alias, a -dev variant and a cross build.
RUST_YML = """\
task-defaults:
    run:
        script: repack_rust.py

linux64-rust-1.90:
    run:
        arguments: [
            '--channel', '1.90.0',
        ]
        toolchain-alias: linux64-rust-base

linux64-rust-1.95:
    run:
        arguments: [
            '--channel', '1.95.0',
            '--host', 'x86_64-unknown-linux-gnu',
        ]
        toolchain-alias:
            by-project:
                toolchains: null
                default: linux64-rust

linux64-rust-1.95-dev:
    run:
        arguments: [
            '--channel', 'dev',
        ]
        toolchain-alias:
            by-project:
                default: linux64-rust-dev

linux64-rust-cross-1.95:
    run:
        arguments: [
            '--channel', '1.95.0',
        ]
        toolchain-alias:
            by-project:
                default: linux64-rust-cross
"""


def _tree(tmp_path, text):
    path = tmp_path / "taskcluster" / "kinds" / "toolchain" / "rust.yml"
    path.parent.mkdir(parents=True)
    path.write_text(text)
    return str(tmp_path)


def test_the_release_aliased_linux64_rust_is_used(tmp_path):
    assert mozilla_rust_version(_tree(tmp_path, RUST_YML)) == "1.95.0"


def test_a_plain_alias_counts_too(tmp_path):
    text = RUST_YML.replace("toolchain-alias: linux64-rust-base", "toolchain-alias: linux64-rust")
    text = text.replace("default: linux64-rust\n", "default: linux64-rust-next\n")
    assert mozilla_rust_version(_tree(tmp_path, text)) == "1.90.0"


@pytest.mark.parametrize("text", [
    RUST_YML.replace("default: linux64-rust\n", "default: linux64-rust-next\n"),
    RUST_YML.replace("toolchain-alias: linux64-rust-base", "toolchain-alias: linux64-rust"),
])
def test_no_or_two_candidates_fail_rather_than_guess(tmp_path, text):
    with pytest.raises(ValueError):
        mozilla_rust_version(_tree(tmp_path, text))
