"""fpgen's model, installed from the pinned release before fpgen is imported.

Left to itself, `import fpgen` downloads its model from the first release the
GitHub API lists, with TLS verification off and no checksum, and downloads it
again whenever the files are five weeks old (fpgen/pkgman.py). The first
release listed is model-4/2025, whose WebGL records have no vendor or renderer,
so every generated launch failed with KeyError: 'vendor'.

So fpgen is only ever imported through load_fpgen(), which first installs the
release named by fpgen-model.json (a copy of scripts/data/fpgen-model.json),
checks the archive and each file against its sha256, and dates the files in the
future so fpgen's five-week refresh never replaces them. The data directory
layout, including the `.pinned-model` stamp, is the one
scripts/pin-fpgen-model.py and the TypeScript launcher write.
"""

import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from threading import Lock
from types import ModuleType
from typing import Optional
from zipfile import ZipFile

from .exceptions import CorruptedDownload, FpgenModelError
from .pkgman import verify_sha256, webdl, write_atomic

PIN = json.loads((Path(__file__).parent / 'fpgen-model.json').read_text(encoding='utf-8'))

# Holds the archive's sha256, written last: a stamp means the install finished.
STAMP = '.pinned-model'

# `python -m fpgen decompress` replaces the archive's files with these, which
# fpgen then reads in preference to them.
DECOMPRESSED_FILES = ('fingerprint-network.json', 'values.json', 'values.dat')
# The TypeScript launcher decompresses values.dat beside the archive's files,
# and CAMOUFOX_FPGEN_DATA may point it at this directory. The pin carries its
# hash, so a values.dat from the pinned model is kept and any other is dropped.

# 2100-01-01T00:00:00Z. fpgen refetches files whose mtime is older than this
# window (pkgman.files_are_recent).
PINNED_MTIME = 4102444800
FPGEN_MAX_AGE_S = 5 * 7 * 24 * 3600

# fpgen fetches a model from this URL instead of GitHub. A caller who set it
# chose their model, so it is left alone.
CUSTOM_MODEL_ENV = 'FPGEN_MODEL_URL'

_LOCK = Lock()
_ready = False


def fpgen_data_dir() -> Path:
    """Where fpgen reads its model, found without importing fpgen (which fetches)."""
    spec = importlib.util.find_spec('fpgen')
    if spec is None or spec.origin is None:
        raise FpgenModelError('fpgen is not installed.')
    return Path(spec.origin).parent / 'data'


def load_fpgen() -> ModuleType:
    """fpgen, imported only once the pinned model is in place."""
    global _ready
    if not _ready:
        ensure_fpgen_model()
        _ready = True
    import fpgen
    import fpgen.utils  # noqa: F401 -- callers use fpgen.utils._lookup_possibilities

    return fpgen


def is_pinned(data_dir: Optional[Path] = None) -> bool:
    """Whether the pinned model's files are in place, whatever wrote them."""
    data_dir = data_dir or fpgen_data_dir()
    return all(
        (data_dir / name).exists() and _hash(data_dir / name) == digest
        for name, digest in PIN['file_sha256'].items()
    )


def ensure_fpgen_model(data_dir: Optional[Path] = None, force: bool = False) -> None:
    """Install the pinned model unless it is already there, and keep fpgen from
    replacing it. Hashing the installed files takes ~2 ms, and catches a model
    fpgen fetched over an earlier install."""
    if os.getenv(CUSTOM_MODEL_ENV):
        return
    data_dir = data_dir or fpgen_data_dir()
    with _LOCK:
        if any(
            (data_dir / name).exists()
            for name in DECOMPRESSED_FILES
            if name not in PIN['decompressed_sha256']
        ):
            raise FpgenModelError(
                f"fpgen's model in {data_dir} is decompressed, so it cannot be checked against "
                f"the pinned {PIN['tag']}. Remove it with `python -m fpgen remove`; Camoufox "
                'then installs the pinned model.'
            )
        try:
            if force or not is_pinned(data_dir):
                _install(data_dir)
            _drop_foreign_decompressed(data_dir)
            _stamp(data_dir)
        except PermissionError as e:
            raise FpgenModelError(
                f"This user cannot read or write fpgen's model file {e.filename}.\n"
                'Install the model once as the account that owns the directory, e.g. while '
                'building an image: camoufox fetch. A model this user cannot read was installed '
                'by another account or elevation level: remove it from that account with '
                '`python -m fpgen remove`, then run camoufox fetch.'
            ) from e


def _install(data_dir: Path) -> None:
    print(f"Downloading fpgen model {PIN['tag']}: {PIN['url']}", file=sys.stderr)
    buffer = webdl(PIN['url'], progress_callback=lambda done, total: None)
    verify_sha256(buffer, PIN['sha256'], 'fpgen model')

    members = {}
    with ZipFile(buffer) as zf:
        if sorted(zf.namelist()) != sorted(PIN['file_sha256']):
            raise CorruptedDownload(
                f"fpgen model archive holds {sorted(zf.namelist())}, "
                f"expected {sorted(PIN['file_sha256'])}."
            )
        # Members are read by name, never extracted by path, and every one is
        # verified before any is written.
        for name, expected in PIN['file_sha256'].items():
            members[name] = zf.read(name)
            if hashlib.sha256(members[name]).hexdigest() != expected:
                raise CorruptedDownload(f'fpgen model member {name} does not match its pinned sha256.')
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / STAMP).unlink(missing_ok=True)
    for name, data in members.items():
        # Dated before the replace, so fpgen never sees it as stale; each
        # replace is atomic, so a concurrent reader never sees a torn file.
        write_atomic(data_dir / name, data, mtime=PINNED_MTIME)


def _drop_foreign_decompressed(data_dir: Path) -> None:
    """Remove a decompressed file that is not the pinned model's: fpgen would
    read it in preference to the verified archive. Hashing values.dat (~210 MB)
    takes ~0.2 s, once per process, and only when the file is there."""
    for name, digest in PIN['decompressed_sha256'].items():
        path = data_dir / name
        if path.exists() and _hash(path) != digest:
            path.unlink(missing_ok=True)


def _stamp(data_dir: Path) -> None:
    """Date the files past fpgen's refresh and write the stamp. Files seeded by
    another user (a root-built image) may be left as they are while fpgen still
    considers them current."""
    for name in PIN['file_sha256']:
        path = data_dir / name
        if int(path.stat().st_mtime) == PINNED_MTIME:
            continue
        try:
            os.utime(path, (PINNED_MTIME, PINNED_MTIME))
        except PermissionError:
            if path.stat().st_mtime < time.time() - FPGEN_MAX_AGE_S:
                raise
    stamp = data_dir / STAMP
    try:
        if stamp.read_text(encoding='utf-8').strip() == PIN['sha256']:
            return
    except OSError:
        pass
    stamp.write_text(PIN['sha256'] + '\n', encoding='utf-8')


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()
