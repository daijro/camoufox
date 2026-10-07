#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import os
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from vsdownload import downloadPackages, extractPackages
from zstandard import ZstdCompressor


def tzstd_path(path):
    path = Path(path)
    if path.suffix not in (".zst", ".zstd") or Path(path.stem).suffix != ".tar":
        raise ValueError("F")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download and build a Visual Studio artifact"
    )
    parser.add_argument("manifest", help="YAML manifest of the contents to download")
    parser.add_argument(
        "-o", dest="output", type=tzstd_path, required=True, help="Output file"
    )
    args = parser.parse_args()

    with open(args.manifest) as f:
        selected = yaml.safe_load(f.read())
    with TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        dl_cache = tmpdir / "cache"
        downloadPackages(selected, dl_cache)
        unpacked = tmpdir / "unpack"
        extractPackages(selected, dl_cache, unpacked)
        stem = Path(Path(args.output.stem).stem)
        vfs = {}
        # Create an archive containing all the paths in lowercase form for
        # cross-compiles.
        with ZstdCompressor().stream_writer(open(args.output, "wb")) as z, tarfile.open(
            mode="w|", fileobj=z
        ) as tar:
            for subpath in ("VC", "Program Files/Windows Kits/10", "DIA SDK"):
                dest = subpath
                if dest.startswith("Program Files/"):
                    dest = dest[len("Program Files/") :]
                subpath = unpacked / subpath
                dest = Path(dest)
                for root, dirs, files in os.walk(subpath):
                    relpath = Path(root).relative_to(subpath)
                    for f in files:
                        path = Path(root) / f
                        info = tar.gettarinfo(path)
                        with open(path, "rb") as fh:
                            lower_f = f.lower()
                            # Ideally, we'd use the overlay for .libs too but as of
                            # writing it's still impractical to use, so lowercase
                            # them for now, that'll be enough.
                            if lower_f.endswith(".lib"):
                                f = lower_f
                            info.name = str(stem / dest / relpath / f)
                            # Set executable flag on .exe files, the Firefox build
                            # system wants it.
                            if lower_f.endswith(".exe"):
                                info.mode |= (info.mode & 0o444) >> 2
                            print("Adding", info.name)
                            tar.addfile(info, fh)
                            if lower_f.endswith((".h", ".idl")):
                                vfs.setdefault(str(dest / relpath), []).append(f)
            # Create an overlay file for use with clang's -ivfsoverlay flag.
            overlay = {
                "version": 0,
                "case-sensitive": False,
                "root-relative": "overlay-dir",
                "overlay-relative": True,
                "roots": [
                    {
                        "name": p,
                        "type": "directory",
                        "contents": [
                            {
                                "name": f,
                                "type": "file",
                                "external-contents": f"{p}/{f}",
                            }
                            for f in files
                        ],
                    }
                    for p, files in vfs.items()
                ],
            }
            overlay_yaml = tmpdir / "overlay.yaml"
            with overlay_yaml.open("w") as fh:
                fh.write(yaml.dump(overlay))
            info = tar.gettarinfo(overlay_yaml)
            info.name = str(stem / "overlay.yaml")
            tar.addfile(info, overlay_yaml.open("rb"))
