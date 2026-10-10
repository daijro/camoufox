"""Guards for the integrity of downloaded release assets.

`webdl()` streams a release asset straight into a buffer that `unzip()` then
extracts over the install directory. The GitHub API already hands us the
asset's `digest` field, and `check_asset()` parses it into `installed_sha256`
-- but nothing ever compared it against the bytes on disk, so a corrupted or
substituted archive was extracted and executed unchallenged.

`verify_sha256()` closes that gap. These tests pin the behaviour that matters:
a mismatch must abort the install, and a verified buffer must still be
readable from position 0 so the extraction step keeps working.
"""

import hashlib
from io import BytesIO

import pytest

from camoufox.exceptions import CorruptedDownload
from camoufox.pkgman import verify_sha256

# Large enough to span several read() blocks, so a single-shot read()
# regression cannot pass by accident.
PAYLOAD = b"camoufox release asset" * 100_000
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


def test_matching_digest_is_accepted():
    verify_sha256(BytesIO(PAYLOAD), DIGEST, "asset")


def test_digest_comparison_is_case_insensitive():
    """GitHub returns lowercase hex, but a hand-pinned digest may not be."""
    verify_sha256(BytesIO(PAYLOAD), DIGEST.upper(), "asset")


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda b: bytes([b[0] ^ 0xFF]) + b[1:], id="first-byte-flipped"),
        pytest.param(lambda b: b[:-1] + bytes([b[-1] ^ 0x01]), id="last-bit-flipped"),
        pytest.param(lambda b: b[:-1], id="truncated"),
        pytest.param(lambda b: b + b"\x00", id="appended"),
        pytest.param(lambda b: b"", id="empty"),
    ],
)
def test_tampered_payload_aborts_the_install(mutate):
    """Any deviation must raise -- extraction never gets to run."""
    with pytest.raises(CorruptedDownload):
        verify_sha256(BytesIO(mutate(PAYLOAD)), DIGEST, "asset")


def test_error_names_both_digests():
    """The message has to be actionable when someone hits this in the wild."""
    with pytest.raises(CorruptedDownload) as exc:
        verify_sha256(BytesIO(b"wrong"), DIGEST, "Camoufox v1.2.3")
    msg = str(exc.value)
    assert "Camoufox v1.2.3" in msg
    assert DIGEST in msg
    assert hashlib.sha256(b"wrong").hexdigest() in msg


@pytest.mark.parametrize("absent", [None, ""])
def test_missing_digest_does_not_block_the_install(absent):
    """Sources that publish no digest must stay installable, not hard-fail."""
    verify_sha256(BytesIO(PAYLOAD), absent, "asset")


def test_buffer_is_rewound_for_extraction():
    """unzip() reads the same buffer next; leaving it at EOF yields an
    empty archive rather than a loud failure."""
    buf = BytesIO(PAYLOAD)
    verify_sha256(buf, DIGEST, "asset")
    assert buf.tell() == 0
    assert buf.read() == PAYLOAD


def test_verifies_a_real_temporary_file(tmp_path):
    """The install path passes a NamedTemporaryFile, not a BytesIO."""
    path = tmp_path / "asset.zip"
    path.write_bytes(PAYLOAD)
    with open(path, "rb") as f:
        verify_sha256(f, DIGEST, "asset")
        assert f.tell() == 0
