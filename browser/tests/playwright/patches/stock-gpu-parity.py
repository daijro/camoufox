"""
Run stock Firefox of the version Camoufox is built from (browser/upstream.sh)
beside Camoufox with an identity claiming this machine, its OS and its GPU, and
diff what a page reads from WebGL and WebGPU where the browser, not the
hardware, decides it.

The launchers build WebGL from fpgen's recordings, which an older Firefox made.
Values the browser decides drift with every upgrade: an extension a backend
exposes on every device, a limit Firefox fixes itself
(webgl-browser-owned-values-follow-firefox in ci/tribal-rules.yml). To tell
them from the hardware's, stock Firefox of the release fpgen's pinned model
mostly recorded runs on the same machine too. A value the two stock releases
report differently is the browser's, and Camoufox must report the new one.
Every other value belongs to the GPU and its driver, and is not compared.

Compared: WebGL1 and WebGL2 supported extensions and getParameter values, where
the two releases differ; the order of the extensions; whether navigator.gpu
and an adapter exist, and the adapter's features and limits. Camoufox claims
the GPU stock reports, with the recorded device of that GPU nearest to stock,
so a machine whose GPU fpgen never recorded fails.

Stock Firefox is downloaded from archive.mozilla.org, checked against the
release's SHA256SUMS, whose signature gpg checks against Mozilla's release
signing key, and cached under .ci-work. That is implemented for Linux;
elsewhere, pass both stock binaries.

    python browser/tests/playwright/patches/stock-gpu-parity.py
    python browser/tests/playwright/patches/stock-gpu-parity.py --stock FIREFOX --recorded-stock FIREFOX
"""

import hashlib
import http.server
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))
from ci._util import WORK_DIR, read_upstream_sh  # noqa: E402

from camoufox import webgl  # noqa: E402
from camoufox.fingerprints import _FPGEN_OS  # noqa: E402
from camoufox.fpgen_model import load_fpgen  # noqa: E402
from camoufox.host_rendering import renders_on_hardware  # noqa: E402
from camoufox.utils import launch_options, resolve_verstr  # noqa: E402

ARCHIVE = "https://archive.mozilla.org/pub/firefox/releases/{version}/"
LINUX_PACKAGE = "linux-{machine}/en-US/firefox-{version}.tar.xz"
OS_NAMES = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}
OS_KEYS = {"linux": "lin", "macos": "mac", "windows": "win"}
CONTEXTS = {"webgl": "webGl", "webgl2": "webGl2"}
# Mozilla Software Releases' primary key, which signs every release's SHA256SUMS:
# https://blog.mozilla.org/security/2026/08/10/updated-gpg-key-for-signing-firefox-and-thunderbird-releases/
MOZILLA_RELEASE_KEY = "14F26682D0916CDD81E37B6D61B7B526D98F0353"

PAGE = b"""<!doctype html><script>
function gl(kind, constants) {
  const c = document.createElement('canvas').getContext(kind);
  if (!c) return null;
  const info = c.getExtension('WEBGL_debug_renderer_info');
  const params = {};
  for (const name of Object.getOwnPropertyNames(constants)) {
    const pname = constants[name];
    if (!/^[A-Z0-9_]+$/.test(name) || typeof pname !== 'number') continue;
    const value = c.getParameter(pname);
    if (value === null || typeof value !== 'object' || ArrayBuffer.isView(value))
      params[pname] = ArrayBuffer.isView(value) ? Array.from(value) : value;
  }
  return {gpu: info && [c.getParameter(info.UNMASKED_VENDOR_WEBGL), c.getParameter(info.UNMASKED_RENDERER_WEBGL)],
          extensions: c.getSupportedExtensions(), params};
}
(async () => {
  const out = {webgl: gl('webgl', WebGLRenderingContext), webgl2: gl('webgl2', WebGL2RenderingContext),
               webgpu: {gpu: !!navigator.gpu}};
  if (navigator.gpu) {
    const a = await navigator.gpu.requestAdapter();
    out.webgpu.adapter = a && {features: [...a.features].sort(),
        limits: Object.fromEntries(Object.keys(Object.getPrototypeOf(a.limits)).map(k => [k, a.limits[k]]))};
  }
  await fetch('/result', {method: 'POST', body: JSON.stringify(out)});
})();
</script>"""


class Probe(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(PAGE)

    def do_POST(self):
        self.server.result = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.send_response(204)
        self.end_headers()
        self.server.done.set()

    def log_message(self, *args):
        pass


def probe(binary: Path, env: Dict[str, str]) -> Dict[str, Any]:
    """Load the probe page in `binary` with a throwaway profile. Stock Firefox
    has no Juggler, so no browser here is driven by Playwright."""
    server = http.server.HTTPServer(("127.0.0.1", 0), Probe)
    server.done, server.result = threading.Event(), None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    profile = tempfile.mkdtemp(prefix="stock-gpu-parity-")
    # The launchers force WebGL on for every identity, so stock gets it too.
    Path(profile, "user.js").write_text('user_pref("webgl.force-enabled", true);\n', encoding="utf-8")
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    proc = subprocess.Popen(
        [str(binary), "-headless", "-no-remote", "-profile", profile, url],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not server.done.wait(120):
            raise SystemExit(f"{binary} did not report within 120s")
        return server.result
    finally:
        # Every process of this browser carries the throwaway profile path.
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            subprocess.run(["pkill", "-9", "-f", profile], capture_output=True)
        proc.wait()
        server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)


def ini_version(binary: Path) -> str:
    return resolve_verstr(binary).split("-")[0]


def recorded_version(host_os: str) -> str:
    """The Firefox release fpgen's pinned model mostly recorded on this OS."""
    majors: Counter = Counter()
    for result in load_fpgen().trace(target="navigator.userAgent", browser="Firefox", os=_FPGEN_OS[host_os]):
        if match := re.search(r"Firefox/(\d+)", str(result.value)):
            majors[match.group(1)] += result.probability
    return f"{majors.most_common(1)[0][0]}.0"


def stock_firefox(flag: str, version: str) -> Path:
    """The stock binary passed with `flag`, or the release downloaded once."""
    if flag in sys.argv:
        binary = Path(sys.argv[sys.argv.index(flag) + 1]).resolve()
    elif platform.system() == "Linux":
        binary = download_stock(version)
    else:
        raise SystemExit(f"downloading stock Firefox is implemented for Linux; pass {flag} with Firefox {version}")
    if ini_version(binary) != version:
        raise SystemExit(f"{binary} is Firefox {ini_version(binary)}, not {version}")
    return binary


def download_stock(version: str) -> Path:
    package = LINUX_PACKAGE.format(machine=platform.machine(), version=version)
    binary = WORK_DIR / "stock-firefox" / version / platform.machine() / "firefox" / "firefox"
    if binary.exists():
        return binary
    base = ARCHIVE.format(version=version)
    sums = {name: digest for digest, name in (line.split("  ", 1) for line in signed_sums(base).splitlines())}
    if package not in sums:
        raise SystemExit(f"{base}SHA256SUMS lists no {package}")
    binary.parent.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=binary.parent.parent) as tmp:
        archive = Path(tmp, "firefox.tar.xz")
        digest = hashlib.sha256()
        url = base + urllib.parse.quote(package)
        with urllib.request.urlopen(url, timeout=300) as resp, archive.open("wb") as out:  # noqa: S310
            while chunk := resp.read(1 << 20):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != sums[package]:
            raise SystemExit(f"{package}: SHA-256 {digest.hexdigest()} is not the release's {sums[package]}")
        with tarfile.open(archive) as tar:
            tar.extractall(tmp, filter="data")
        # Renamed into place last, so an interrupted run leaves nothing cached.
        Path(tmp, "firefox").rename(binary.parent)
    return binary


def signed_sums(base: str) -> str:
    """The release's SHA256SUMS, once gpg finds it signed by Mozilla's release
    key. The KEY file beside it is trusted only through the pinned fingerprint."""
    gpg = shutil.which("gpg")
    if not gpg:
        raise SystemExit("gpg is required to verify stock Firefox's SHA256SUMS; install GnuPG")
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp, "gnupg")
        home.mkdir(mode=0o700)
        for name in ("KEY", "SHA256SUMS", "SHA256SUMS.asc"):
            with urllib.request.urlopen(base + name, timeout=60) as resp:  # noqa: S310
                Path(tmp, name).write_bytes(resp.read())
        subprocess.run(
            [gpg, "--homedir", str(home), "--batch", "--quiet", "--import", str(Path(tmp, "KEY"))],
            check=True, capture_output=True,
        )
        verify = subprocess.run(
            [gpg, "--homedir", str(home), "--batch", "--status-fd", "1",
             "--verify", str(Path(tmp, "SHA256SUMS.asc")), str(Path(tmp, "SHA256SUMS"))],
            capture_output=True, text=True,
        )
        # VALIDSIG ends with the primary key of whichever subkey signed.
        signers = [line.split()[-1] for line in verify.stdout.splitlines() if line.startswith("[GNUPG:] VALIDSIG ")]
        if verify.returncode or signers != [MOZILLA_RELEASE_KEY]:
            raise SystemExit(f"{base}SHA256SUMS is not signed by Mozilla's release key:\n{verify.stdout}{verify.stderr}")
        return Path(tmp, "SHA256SUMS").read_text(encoding="utf-8")


def flatten(output: Dict[str, Any]) -> Dict[str, Any]:
    """One value per supported extension and per getParameter answer."""
    flat: Dict[str, Any] = {}
    for context in CONTEXTS:
        webgl_output = output.get(context) or {"extensions": [], "params": {}}
        flat.update({f"{context} {extension}": True for extension in webgl_output["extensions"]})
        flat.update({f"{context} {pname}": value for pname, value in webgl_output["params"].items()})
    return flat


def nearest_device(target_os: str, gpu: List[str], stock: Dict[str, Any]) -> Dict[str, Any]:
    """The device fpgen recorded behind this GPU that stock agrees with most,
    as the launchers configure it: a fixed choice where a draw would vary."""
    devices = webgl.recorded_devices(target_os, *gpu)

    def disagreements(device: Dict[str, Any]) -> int:
        recorded = flatten({
            context: {"extensions": device[f"{prefix}:supportedExtensions"], "params": device[f"{prefix}:parameters"]}
            for context, prefix in CONTEXTS.items()
            if f"{prefix}:parameters" in device
        })
        return sum(stock.get(key) != value for key, value in recorded.items())

    return min(devices, key=disagreements)


def main() -> int:
    version = read_upstream_sh()["version"]
    host_os = OS_NAMES[platform.system()]
    target_os = OS_KEYS[host_os]
    camoufox = Path(sys.argv[sys.argv.index("--binary") + 1]).resolve() if "--binary" in sys.argv else resolve_binary()
    if ini_version(camoufox) != version:
        raise SystemExit(f"{camoufox} is Firefox {ini_version(camoufox)}; browser/upstream.sh pins {version}")
    stock = stock_firefox("--stock", version)
    recorded = stock_firefox("--recorded-stock", recorded_version(host_os))
    print(f"Camoufox: {camoufox}\nStock:    {stock}\nRecorded: {recorded}")

    stock_out = probe(stock, dict(os.environ))
    recorded_out = probe(recorded, dict(os.environ))
    gpu = (stock_out["webgl"] or {}).get("gpu")
    if not gpu or tuple(gpu) not in webgl.firefox_gpus(target_os):
        print(f"FAIL: stock Firefox reports the GPU {gpu}, which fpgen never recorded on {host_os}")
        return 1
    stock_flat = flatten(stock_out)
    # Without webGl:vendor/renderer the launcher claims a hardware GPU of the
    # host itself, through the path a real launch takes, and keeps the
    # device's tables. A software renderer it leaves to the draw, so that one
    # is named.
    device = nearest_device(target_os, gpu, stock_flat)
    named = () if renders_on_hardware(tuple(gpu)) else ("webGl:vendor", "webGl:renderer")
    pinned = {
        k: v for k, v in device.items()
        if k in named or k.startswith(("webGl:", "webGl2:")) and not k.endswith(("vendor", "renderer"))
    }
    options = launch_options(
        os=host_os, headless=True, executable_path=str(camoufox), config=pinned, i_know_what_im_doing=True
    )
    camoufox_out = probe(camoufox, {k: str(v) for k, v in options["env"].items()})

    failures: List[str] = []
    camoufox_gpu = (camoufox_out["webgl"] or {}).get("gpu")
    if camoufox_gpu != gpu:
        print(f"    [FAIL] Camoufox claims {camoufox_gpu}, not the host's {gpu}")
        failures.append("claimed GPU")
    recorded_flat, camoufox_flat = flatten(recorded_out), flatten(camoufox_out)
    for key in sorted(set(stock_flat) | set(recorded_flat)):
        new, old, got = stock_flat.get(key), recorded_flat.get(key), camoufox_flat.get(key)
        if new != old:
            print(f"    [{'ok  ' if got == new else 'FAIL'}] {key}: stock {new}, recorded release {old}, Camoufox {got}")
            if got != new:
                failures.append(key)
    for context in CONTEXTS:
        stock_exts = (stock_out[context] or {}).get("extensions", [])
        camoufox_exts = (camoufox_out[context] or {}).get("extensions", [])
        if [e for e in stock_exts if e in camoufox_exts] != [e for e in camoufox_exts if e in stock_exts]:
            print(f"    [FAIL] {context} extension order: stock {stock_exts}, Camoufox {camoufox_exts}")
            failures.append(f"{context} extension order")
    if stock_out["webgpu"] != camoufox_out["webgpu"]:
        print(f"    [FAIL] WebGPU: stock {stock_out['webgpu']}, Camoufox {camoufox_out['webgpu']}")
        failures.append("WebGPU")

    print()
    if failures:
        print(f"FAIL: {len(failures)} browser-owned difference(s) from stock Firefox {version}: {', '.join(failures)}")
        return 1
    print(f"PASS: WebGL and WebGPU follow stock Firefox {version} on {gpu[1]}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
