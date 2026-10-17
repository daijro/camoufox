#!/usr/bin/env python3
"""Optimized builds: cross-language LTO plus PGO, as stock Firefox ships.

Without them Gecko's C++ runs slower than stock while JIT-compiled script does
not, and a page can time the ratio. Measured against stock Firefox 152.0.4 on
the same host: JSON.parse 1.52x, location.href 1.77x, createElement 1.32x,
TextEncoder 1.45x, a regexp replace 1.04x -- so JSON.parse over a regexp
replace read ~3.3 where stock reads ~2.2, with no reference machine needed.

Stock's recipe (build/mozconfig.common, taskcluster run-profileserver.sh) is
two stages, and so is this one:

  1. An instrumented build (--enable-profile-generate=cross) runs Mozilla's
     own training pages (build/pgo/profileserver.py). The merged profile is
     published once per Firefox version as a release asset by the "PGO
     profile" workflow, and pinned by sha256 in browser/assets/optimized-build.json.
  2. Every CI build uses it: --enable-profile-use=cross --enable-lto=cross.
     browser/assets/ feeds the native-input hash, so pinning a new profile
     rebuilds.

Cross-language LTO hands Rust bitcode to lld, so rustc's LLVM may not be newer
than clang's. The bootstrapped clang for 156 is 22 (linux64-clang in
taskcluster/kinds/toolchain/clang.yml); Mozilla builds 156 with Rust 1.95.0
(linux64-rust in taskcluster/kinds/toolchain/rust.yml), whose LLVM is 22 too.
rustup's stable can be newer than the clang, so the Rust version is pinned.

Stdlib only: `toolchain` and `fetch` run before the pip install.

Run:
    python3 -m ci.pgo toolchain          # install + pin Rust (RUSTUP_TOOLCHAIN)
    python3 -m ci.pgo check              # rustc LLVM <= bootstrapped clang
    python3 -m ci.pgo fetch [--require]  # pinned profile -> CAMOUFOX_* env
    python3 -m ci.pgo generate --out D   # train an instrumented build
    python3 -m ci.pgo publish --dir D --revision N
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

from ._pytest import source_dir
from ._util import BROWSER_ROOT, die, log, read_upstream_sh, run, set_output, summary

CONFIG_PATH = BROWSER_ROOT / "assets" / "optimized-build.json"
MOZBUILD = Path(os.environ.get("MOZBUILD_STATE_PATH", Path.home() / ".mozbuild"))
CLANG = MOZBUILD / "clang" / "bin" / "clang"
LLVM_PROFDATA = MOZBUILD / "clang" / "bin" / "llvm-profdata"
PROFILE_DIR = Path(os.environ.get("CAMOUFOX_PGO_DIR", Path.home() / "pgo-profile"))
PROFDATA = "merged.profdata"
JARLOG = "en-US.log"
RUST_TARGET = "x86_64-unknown-linux-gnu"

# What profileserver.py serves and loads, relative to the source root. A source
# tarball that lacks one of these trains on less, silently -- so each is
# checked, and fetched from hg.mozilla.org at the release tag if absent.
CORPUS = (
    "build/pgo",
    "testing/profiles",
    "tools/quitter",
    "third_party/webkit/PerformanceTests/Speedometer3",
    "testing/talos/talos",
)


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def write_env(values: Dict[str, str]) -> None:
    """Export to later steps (GITHUB_ENV) and log what was set."""
    path = os.environ.get("GITHUB_ENV")
    for key, value in values.items():
        log(f"env {key}={value}")
        if path:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"{key}={value}\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# toolchain
# --------------------------------------------------------------------------


def llvm_major(version_output: str, pattern: str) -> Optional[int]:
    found = re.search(pattern, version_output)
    return int(found.group(1)) if found else None


def cmd_toolchain(_args) -> int:
    rust = config()["rust"]
    rustup = shutil.which("rustup") or str(Path.home() / ".cargo" / "bin" / "rustup")
    run([rustup, "toolchain", "install", rust, "--profile", "minimal", "--target", RUST_TARGET], check=True)
    info = run([rustup, "run", rust, "rustc", "-vV"], check=True).stdout
    log(info.strip())
    write_env({"RUSTUP_TOOLCHAIN": rust})
    return 0


def cmd_check(_args) -> int:
    """rustc's LLVM must not be newer than clang's, or lld cannot read the
    Rust bitcode at the LTO link -- which fails an hour into the build."""
    rust = config()["rust"]
    rustc = run(["rustc", "-vV"], env={"RUSTUP_TOOLCHAIN": rust}, check=True).stdout
    clang = run([str(CLANG), "--version"], check=True).stdout
    rust_llvm = llvm_major(rustc, r"LLVM version: (\d+)")
    clang_llvm = llvm_major(clang, r"clang version (\d+)")
    log(f"rustc {rust}: LLVM {rust_llvm}; bootstrapped clang: {clang_llvm}")
    if rust_llvm is None or clang_llvm is None:
        die(f"could not read LLVM versions:\n{rustc}\n{clang}")
    if rust_llvm > clang_llvm:
        die(f"rustc {rust} uses LLVM {rust_llvm}, newer than clang {clang_llvm}: "
            "cross-language LTO cannot link its bitcode. Pin the Rust release Mozilla "
            "pairs with this clang (taskcluster/kinds/toolchain/rust.yml).")
    return 0


# --------------------------------------------------------------------------
# fetch: pinned profile -> build environment
# --------------------------------------------------------------------------


def cmd_fetch(args) -> int:
    cfg = config()
    profile = cfg["profile"]
    version = read_upstream_sh()["version"]
    env = {"CAMOUFOX_LTO": "1"}

    problem = None
    if not profile.get("tag") or not profile.get("sha256"):
        problem = "no profile is pinned in browser/assets/optimized-build.json"
    elif cfg["firefox"] != version:
        problem = (f"the pinned profile is for Firefox {cfg['firefox']}, the tree is {version}; "
                   "run the PGO profile workflow and pin its output")
    if problem:
        if args.require:
            die(f"refusing an unoptimized release build: {problem}")
        print(f"::warning::building with LTO but without PGO: {problem}", flush=True)
        write_env(env)
        return 0

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    archive = PROFILE_DIR / profile["asset"]
    url = (f"https://github.com/{profile['repository']}/releases/download/"
           f"{profile['tag']}/{profile['asset']}")
    if not archive.exists() or sha256(archive) != profile["sha256"]:
        log(f"downloading {url}")
        try:
            with urllib.request.urlopen(url, timeout=600) as resp, open(archive, "wb") as fh:
                shutil.copyfileobj(resp, fh)
        except OSError as exc:  # urllib's HTTPError and URLError are OSErrors
            archive.unlink(missing_ok=True)
            die(f"could not download the pinned profile {url}: {exc}")
    actual = sha256(archive)
    if actual != profile["sha256"]:
        die(f"{archive.name} sha256 {actual} != pinned {profile['sha256']}")

    with tarfile.open(archive, "r:xz") as tar:
        for member in tar.getmembers():
            if member.name not in (PROFDATA, JARLOG) or not member.isfile():
                die(f"unexpected member {member.name!r} in {archive.name}")
        tar.extractall(PROFILE_DIR)
    profdata = PROFILE_DIR / PROFDATA
    if not profdata.is_file() or profdata.stat().st_size == 0:
        die(f"{archive.name} has no usable {PROFDATA}")
    env["CAMOUFOX_PGO_PROFILE"] = str(profdata.resolve())
    jarlog = PROFILE_DIR / JARLOG
    if jarlog.is_file() and jarlog.stat().st_size:
        env["CAMOUFOX_PGO_JARLOG"] = str(jarlog.resolve())
    write_env(env)
    summary(f"PGO profile `{profile['tag']}` ({actual[:12]}), cross-language LTO")
    return 0


# --------------------------------------------------------------------------
# generate: train the instrumented build
# --------------------------------------------------------------------------


def hg_release_tag(version: str) -> str:
    return "FIREFOX_" + version.replace(".", "_") + "_RELEASE"


def ensure_corpus(src: Path, version: str) -> None:
    for rel in CORPUS:
        if (src / rel).exists() and any((src / rel).iterdir()):
            continue
        url = (f"https://hg.mozilla.org/releases/mozilla-release/archive/"
               f"{hg_release_tag(version)}.tar.gz/{rel}/")
        log(f"{rel} is missing from the source tree; fetching {url}")
        with urllib.request.urlopen(url, timeout=900) as resp:
            data = resp.read()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar.getmembers():
                # The archive's root is a single "mozilla-release-<rev>/" dir.
                parts = Path(member.name).parts[1:]
                if not parts:
                    continue
                member.name = str(Path(*parts))
                tar.extract(member, src)
        if not (src / rel).exists():
            die(f"{rel} still missing after fetching it from hg")


# Child processes write their profile at exit, through the parent's sandbox
# broker. camoufox.cfg sets toolkit.shutdown.fastShutdownStage 3, which exits
# right after xpcom-will-shutdown: in the first run two children lost every
# write ("LLVM Profile Error: Failed to write file ... Broken pipe", 43 lines).
# Stock builds instrumented binaries with stage 0 for exactly this reason
# (StaticPrefList.yaml: MOZ_PROFILE_GENERATE -> 0); a user pref in the
# training profile beats the defaultPref.
FLUSH_PREFS = {"toolkit.shutdown.fastShutdownStage": 0}


def allow_profile_flush(src: Path) -> None:
    user_js = src / "testing" / "profiles" / "profileserver" / "user.js"
    text = user_js.read_text(encoding="utf-8")
    for pref, value in FLUSH_PREFS.items():
        line = f'user_pref("{pref}", {json.dumps(value)});'
        if line not in text:
            text += f"\n// ci/pgo.py: let child processes flush their profiles.\n{line}\n"
    user_js.write_text(text, encoding="utf-8")


def camou_config_env(binary: Path) -> Dict[str, str]:
    """A representative identity, so training runs the spoofing paths a real
    session runs (MaskConfig reads, per-context lookups) rather than only the
    empty-config fallthroughs."""
    from camoufox.utils import launch_options  # installed by the workflow

    opts = launch_options(os="windows", headless=False, executable_path=str(binary),
                          i_know_what_im_doing=True)
    return {k: v for k, v in opts["env"].items() if k.startswith("CAMOU_CONFIG")}


def cmd_generate(args) -> int:
    src = source_dir()
    version = read_upstream_sh()["version"]
    dist_bin = src / "obj-x86_64-pc-linux-gnu" / "dist" / "bin"
    binary = dist_bin / "camoufox-bin"
    if not binary.exists():
        die(f"no instrumented build at {binary}")
    if not LLVM_PROFDATA.exists():
        die(f"no llvm-profdata at {LLVM_PROFDATA}")
    if not os.environ.get("DISPLAY"):
        die("profileserver.py launches a real browser: run under xvfb-run")

    ensure_corpus(src, version)
    allow_profile_flush(src)
    # The launcher resolves properties.json next to the binary.
    for name in ("properties.json",):
        if not (dist_bin / name).exists():
            shutil.copy(BROWSER_ROOT / "settings" / name, dist_bin / name)

    env = {
        "LLVM_PROFDATA": str(LLVM_PROFDATA),
        "JARLOG_FILE": JARLOG,
        **camou_config_env(binary),
    }
    for key in [k for k in os.environ if "proxy" in k.lower()]:
        env[key] = ""
    work = src
    for stale in work.glob("*.profraw"):
        stale.unlink()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    res = run(["./mach", "python", "build/pgo/profileserver.py", "--binary", str(binary)],
              cwd=work, env=env, timeout=args.timeout)
    log_text = res.combined()
    (out / "profile-run.log").write_text(log_text, encoding="utf-8")
    print(log_text[-6000:], flush=True)
    if res.code != 0:
        die(f"profileserver.py exited {res.code} (full log: {out / 'profile-run.log'})")
    # Stock's own rule (profileserver.py in automation): a process that failed
    # to write its profile leaves that process's code unprofiled, so the run
    # does not count.
    errors = [l for l in log_text.splitlines() if "LLVM Profile Error" in l]
    if errors:
        die(f"{len(errors)} LLVM Profile Error lines, e.g. {errors[0].strip()}")

    profdata = work / PROFDATA
    if not profdata.is_file() or profdata.stat().st_size == 0:
        die(f"training produced no {PROFDATA}")
    raw = list(work.glob("*.profraw"))
    log(f"{len(raw)} profraw files merged into {PROFDATA} ({profdata.stat().st_size >> 20} MB)")

    asset = out / config()["profile"]["asset"]
    members = [PROFDATA] + ([JARLOG] if (work / JARLOG).is_file() else [])
    with tarfile.open(asset, "w:xz") as tar:
        for name in members:
            tar.add(work / name, arcname=name)
    digest = sha256(asset)
    (out / "sha256").write_text(digest + "\n")
    set_output("sha256", digest)
    log(f"{asset} sha256 {digest} ({asset.stat().st_size >> 20} MB; {', '.join(members)})")
    return 0


# --------------------------------------------------------------------------
# publish
# --------------------------------------------------------------------------


def cmd_publish(args) -> int:
    cfg = config()
    version = read_upstream_sh()["version"]
    out = Path(args.dir)
    asset = out / cfg["profile"]["asset"]
    digest = (out / "sha256").read_text().strip()
    if sha256(asset) != digest:
        die("asset does not match its recorded sha256")
    tag = f"pgo-{version}-r{args.revision}"
    repo = os.environ.get("GITHUB_REPOSITORY", cfg["profile"]["repository"])
    notes = (f"PGO training profile for Firefox {version} (Rust {cfg['rust']}), "
             "produced by the PGO profile workflow. Not a browser release: builds "
             "consume it through browser/assets/optimized-build.json.")
    run(["gh", "release", "create", tag, "--repo", repo, "--prerelease",
         "--title", f"PGO profile {version} r{args.revision}", "--notes", notes, str(asset)],
        check=True)
    pinned = dict(cfg)
    pinned["firefox"] = version
    pinned["profile"] = {**cfg["profile"], "repository": repo, "tag": tag, "sha256": digest}
    snippet = json.dumps(pinned, indent=2)
    set_output("tag", tag)
    summary(f"Published `{tag}`. Pin it in `browser/assets/optimized-build.json`:\n\n```json\n{snippet}\n```")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("toolchain").set_defaults(fn=cmd_toolchain)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--require", action="store_true",
                       help="fail instead of building without PGO (release builds)")
    fetch.set_defaults(fn=cmd_fetch)
    gen = sub.add_parser("generate")
    gen.add_argument("--out", required=True)
    gen.add_argument("--timeout", type=int, default=7200)
    gen.set_defaults(fn=cmd_generate)
    pub = sub.add_parser("publish")
    pub.add_argument("--dir", required=True)
    pub.add_argument("--revision", default="1")
    pub.set_defaults(fn=cmd_publish)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
