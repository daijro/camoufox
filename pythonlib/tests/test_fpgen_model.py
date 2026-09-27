"""fpgen's model is the pinned release, installed before fpgen is first imported.

Left to itself, `import fpgen` downloads the first release the GitHub API
lists -- model-4/2025, whose WebGL records carry no vendor or renderer -- so a
pip-installed camoufox failed every generated launch with KeyError: 'vendor' in
webgl.py. scripts/pin-fpgen-model.py pinned the model for CI only.
"""

import ast
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from camoufox import fpgen_model  # noqa: E402
from camoufox.exceptions import CorruptedDownload, FpgenModelError  # noqa: E402
from camoufox.fpgen_model import FPGEN_MAX_AGE_S, PINNED_MTIME, STAMP, ensure_fpgen_model  # noqa: E402

PACKAGE = Path(fpgen_model.__file__).resolve().parent
MEMBERS = {
    "fingerprint-network.json.zst": b"network" * 1000,
    "values.json.zst": b"values-json" * 1000,
    "values.dat.zst": b"values-dat" * 1000,
}
# What the synthetic values.dat.zst decompresses to, as far as the pin says.
VALUES_DAT = b"decompressed-values" * 1000
STALE = time.time() - FPGEN_MAX_AGE_S - 86400


def _archive(members):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def pinned(monkeypatch):
    """Pin a small synthetic model instead of the real release, and record the
    downloads. Set `.payload` to serve other bytes than the pin describes."""
    archive = _archive(MEMBERS)
    pin = {
        **fpgen_model.PIN,
        "size": len(archive),
        "sha256": _sha256(archive),
        "files": sorted(MEMBERS),
        "file_sha256": {name: _sha256(data) for name, data in MEMBERS.items()},
        "decompressed_sha256": {"values.dat": _sha256(VALUES_DAT)},
    }
    monkeypatch.setattr(fpgen_model, "PIN", pin)
    monkeypatch.delenv("FPGEN_MODEL_URL", raising=False)

    class Downloads(list):
        payload = archive

    downloads = Downloads()

    def fake_webdl(url, desc=None, buffer=None, bar=True, progress_callback=None):
        downloads.append(url)
        return io.BytesIO(downloads.payload)

    monkeypatch.setattr(fpgen_model, "webdl", fake_webdl)
    return downloads


def _write(data_dir, members, mtime=None, stamp=None):
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, data in members.items():
        path = data_dir / name
        path.write_bytes(data)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
    if stamp is not None:
        (data_dir / STAMP).write_text(stamp + "\n")


def _mtimes(data_dir):
    return {int((data_dir / name).stat().st_mtime) for name in MEMBERS}


def test_only_the_model_module_imports_fpgen():
    """Every fpgen import goes through fpgen_model.load_fpgen(), which installs
    the pinned model first. A direct import anywhere else lets fpgen fetch
    model-4/2025 before the pin is in place."""
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.name == "fpgen_model.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            if any(name == "fpgen" or name.startswith("fpgen.") for name in names):
                offenders.append(f"{path.relative_to(PACKAGE)}:{node.lineno}")
    assert offenders == []


def test_missing_model_is_installed_verified_and_stamped(tmp_path, pinned):
    data_dir = tmp_path / "data"
    ensure_fpgen_model(data_dir)

    assert pinned == [fpgen_model.PIN["url"]]
    for name, data in MEMBERS.items():
        assert (data_dir / name).read_bytes() == data
    assert _mtimes(data_dir) == {PINNED_MTIME}
    # The same stamp scripts/pin-fpgen-model.py and the TypeScript launcher write.
    assert (data_dir / STAMP).read_text().strip() == fpgen_model.PIN["sha256"]
    assert sorted(p.name for p in data_dir.iterdir()) == sorted([*MEMBERS, STAMP])


def test_pinned_model_is_not_downloaded_again(tmp_path, pinned):
    data_dir = tmp_path / "data"
    ensure_fpgen_model(data_dir)
    ensure_fpgen_model(data_dir)

    assert len(pinned) == 1


def test_stale_pinned_model_is_restamped_not_refetched(tmp_path, pinned):
    """Five weeks after install fpgen would fetch model-4/2025 over the pin."""
    data_dir = tmp_path / "data"
    _write(data_dir, MEMBERS, mtime=STALE, stamp=fpgen_model.PIN["sha256"])

    ensure_fpgen_model(data_dir)

    assert pinned == []
    assert _mtimes(data_dir) == {PINNED_MTIME}


def test_a_model_fpgen_overwrote_under_a_valid_stamp_is_replaced(tmp_path, pinned):
    """The stamp outlives fpgen's own five-week refetch, so files are hashed."""
    data_dir = tmp_path / "data"
    _write(data_dir, {**MEMBERS, "values.dat.zst": b"model-4/2025"}, stamp=fpgen_model.PIN["sha256"])

    ensure_fpgen_model(data_dir)

    assert len(pinned) == 1
    assert (data_dir / "values.dat.zst").read_bytes() == MEMBERS["values.dat.zst"]


def test_matching_files_without_a_stamp_are_adopted(tmp_path, pinned):
    data_dir = tmp_path / "data"
    _write(data_dir, MEMBERS)

    ensure_fpgen_model(data_dir)

    assert pinned == []
    assert (data_dir / STAMP).read_text().strip() == fpgen_model.PIN["sha256"]


def test_partial_model_is_completed(tmp_path, pinned):
    data_dir = tmp_path / "data"
    _write(data_dir, {"values.json.zst": MEMBERS["values.json.zst"]})

    ensure_fpgen_model(data_dir)

    assert len(pinned) == 1
    assert all((data_dir / name).exists() for name in MEMBERS)


def test_force_reinstalls(tmp_path, pinned):
    data_dir = tmp_path / "data"
    ensure_fpgen_model(data_dir)
    ensure_fpgen_model(data_dir, force=True)

    assert len(pinned) == 2


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param(lambda a: a[:-1], id="truncated-archive"),
        pytest.param(lambda a: _archive({**MEMBERS, "values.dat.zst": b"x"}), id="member-changed"),
    ],
)
def test_tampered_download_installs_nothing(tmp_path, pinned, tamper):
    data_dir = tmp_path / "data"
    pinned.payload = tamper(_archive(MEMBERS))

    with pytest.raises(CorruptedDownload):
        ensure_fpgen_model(data_dir)

    assert not data_dir.exists() or list(data_dir.iterdir()) == []


def test_member_hashes_are_checked_even_when_the_archive_hash_matches(tmp_path, pinned):
    bad = _archive({**MEMBERS, "values.dat.zst": b"x"})
    pinned.payload = bad
    fpgen_model.PIN.update(size=len(bad), sha256=_sha256(bad))

    with pytest.raises(CorruptedDownload, match="values.dat.zst"):
        ensure_fpgen_model(tmp_path / "data")


def test_decompressed_model_fails_loudly(tmp_path, pinned):
    """`python -m fpgen decompress` leaves files the pin cannot verify, and fpgen
    reads them in preference to the verified ones."""
    data_dir = tmp_path / "data"
    _write(data_dir, {name: b"{}" for name in fpgen_model.DECOMPRESSED_FILES})

    with pytest.raises(FpgenModelError, match="fpgen remove"):
        ensure_fpgen_model(data_dir)
    assert pinned == []


def test_a_pinned_values_dat_is_shared_with_the_typescript_launcher(tmp_path, pinned):
    """CAMOUFOX_FPGEN_DATA may point the TS launcher at this directory, and it
    decompresses values.dat there. The pinned model's values.dat stays."""
    data_dir = tmp_path / "data"
    ensure_fpgen_model(data_dir)
    _write(data_dir, {"values.dat": VALUES_DAT})

    ensure_fpgen_model(data_dir)

    assert (data_dir / "values.dat").read_bytes() == VALUES_DAT
    assert pinned == [fpgen_model.PIN["url"]]


def test_a_values_dat_from_another_model_is_dropped(tmp_path, pinned):
    """fpgen reads values.dat in preference to values.dat.zst, so one left over
    from another model would pair its values with the pinned network."""
    data_dir = tmp_path / "data"
    ensure_fpgen_model(data_dir)
    _write(data_dir, {"values.dat": b"another model"})

    ensure_fpgen_model(data_dir)

    assert not (data_dir / "values.dat").exists()


def test_custom_model_url_is_left_to_fpgen(tmp_path, pinned, monkeypatch):
    monkeypatch.setenv("FPGEN_MODEL_URL", "https://example.invalid/model.zip")
    data_dir = tmp_path / "data"

    ensure_fpgen_model(data_dir)

    assert pinned == []
    assert not data_dir.exists()


needs_non_root = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignores file permissions"
)


@pytest.fixture
def read_only(tmp_path):
    data_dir = tmp_path / "data"
    yield data_dir
    if data_dir.exists():
        data_dir.chmod(0o755)


@needs_non_root
def test_read_only_missing_model_names_the_fix(read_only, pinned):
    read_only.mkdir()
    read_only.chmod(0o555)

    with pytest.raises(FpgenModelError, match="camoufox fetch"):
        ensure_fpgen_model(read_only)


@needs_non_root
def test_read_only_current_pinned_model_is_used(read_only, pinned):
    """A root-seeded image run as another user: fpgen accepts the files as they
    are for five weeks, so the launch does not need to stamp them."""
    _write(read_only, MEMBERS, stamp=fpgen_model.PIN["sha256"])
    read_only.chmod(0o555)
    for name in MEMBERS:
        (read_only / name).chmod(0o444)

    ensure_fpgen_model(read_only)

    assert pinned == []


def test_install_writes_nothing_to_stdout(tmp_path, pinned, capfd):
    """A caller's stdout may be data (a probe printing JSON)."""
    ensure_fpgen_model(tmp_path / "data")

    out, err = capfd.readouterr()
    assert out == ""
    assert "fpgen model" in err


def test_the_packaged_pin_is_the_repo_pin():
    """The package cannot ship scripts/, so it carries a copy. Bump both."""
    repo_pin = PACKAGE.parents[1] / "scripts" / "data" / "fpgen-model.json"
    assert fpgen_model.PIN == json.loads(repo_pin.read_text(encoding="utf-8"))


def test_the_real_pin_is_complete():
    pin = fpgen_model.PIN
    assert pin["url"].startswith("https://github.com/")
    assert f"/download/{pin['tag']}/" in pin["url"]
    assert sorted(pin["file_sha256"]) == sorted(pin["files"])


def test_constants_match_the_installed_fpgen():
    """fpgen's file names, data directory and five-week window are its own; if
    a release changes them, this module would install a model fpgen cannot see.
    FPGEN_NO_INIT keeps fpgen from loading (or fetching) while it is read."""
    probe = (
        "import json, fpgen.pkgman as p;"
        "print(json.dumps({"
        "'dir': str(p.DATA_DIR),"
        "'compressed': sorted(v.name for v in p.FILE_PAIRS.values()),"
        "'decompressed': sorted(k.name for k in p.FILE_PAIRS.keys())}))"
    )
    env = {**os.environ, "FPGEN_NO_INIT": "1"}
    out = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, check=True)
    seen = json.loads(out.stdout.strip().splitlines()[-1])

    assert seen["dir"] == str(fpgen_model.fpgen_data_dir())
    assert seen["compressed"] == sorted(fpgen_model.PIN["files"])
    assert seen["decompressed"] == sorted(fpgen_model.DECOMPRESSED_FILES)
    assert "timedelta(weeks=5)" in (fpgen_model.fpgen_data_dir().parent / "pkgman.py").read_text()


_IMPORT_ORDER = """
import sys
from camoufox import fpgen_model
real = fpgen_model.ensure_fpgen_model
seen = []
def spy(*args, **kwargs):
    seen.append("fpgen" in sys.modules)
    return real(*args, **kwargs)
fpgen_model.ensure_fpgen_model = spy
from camoufox import {module}
{call}
print(seen)
"""


@pytest.mark.parametrize(
    "module, call",
    [
        pytest.param("fingerprints", "fingerprints._generator()", id="generate"),
        pytest.param("webgl", "webgl.firefox_gpus('win')", id="preset-or-webgl_config"),
    ],
)
def test_each_entry_point_installs_the_model_before_fpgen_loads(module, call):
    script = _IMPORT_ORDER.format(module=module, call=call)
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=PACKAGE.parent, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip().splitlines()[-1] == "[False]"
