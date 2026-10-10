"""
Verify WebRTC candidate ports are in the identity's OS port range.

A UDP candidate's port is the ephemeral port the OS gave its socket: 32768-60999
on Linux (the kernel's ip_local_port_range), 49152-65535 on Windows and macOS.
The host kernel picked it, so a Windows or macOS identity on a Linux host showed
Linux ports in its host candidates, and in the srflx candidate that reuses the
host port: ports the claimed OS could not have used.

The probe gathers several peer connections against a STUN server that never
answers (a silent loopback socket), so the run needs no network and the srflx
candidate is the one webrtc-ip-spoofing.patch fabricates. Twelve connections
make a range that is off by one OS fail almost every run, while a correct one
always passes.

What PASS means: for a Windows, a macOS and a Linux identity, every UDP host
and srflx candidate port is inside that OS's range.

    python browser/tests/playwright/patches/webrtc-port-range.py
"""

import asyncio
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import resolve_binary  # noqa: E402

RANGES = {"windows": (49152, 65535), "macos": (49152, 65535), "linux": (32768, 60999)}
CONNECTIONS = 12

PROBE = """async ([stun, count]) => {
  const gather = async () => {
    const pc = new RTCPeerConnection({iceServers: [{urls: stun}]});
    const ports = {host: [], srflx: []};
    const done = new Promise(resolve => {
      setTimeout(resolve, 30000);
      pc.onicecandidate = e => {
        if (!e.candidate) return resolve();
        const m = e.candidate.candidate.match(/ UDP \\d+ \\S+ (\\d+) typ (host|srflx)/);
        if (m) ports[m[2]].push(Number(m[1]));
      };
    });
    pc.createDataChannel('probe');
    await pc.setLocalDescription(await pc.createOffer());
    await done;
    pc.close();
    return ports;
  };
  const all = await Promise.all(Array.from({length: count}, gather));
  return {host: all.flatMap(p => p.host), srflx: all.flatMap(p => p.srflx)};
}"""


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox

    silent = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    silent.bind(("127.0.0.1", 0))
    stun = f"stun:127.0.0.1:{silent.getsockname()[1]}"

    passed = True
    for os_name, (lo, hi) in RANGES.items():
        async with AsyncCamoufox(headless=True, os=os_name, config={"webrtc:ipv4": "203.0.113.9"},
                                 i_know_what_im_doing=True,
                                 executable_path=str(resolve_binary())) as browser:
            page = await browser.new_page()
            await page.goto("about:blank")
            ports = await page.evaluate(PROBE, [stun, CONNECTIONS])
        for kind in ("host", "srflx"):
            got = ports[kind]
            outside = [p for p in got if not lo <= p <= hi]
            if len(got) >= CONNECTIONS and not outside:
                print(f"  PASS {os_name} {kind}: {len(got)} ports, all in {lo}-{hi}")
            else:
                passed = False
                print(f"  FAIL {os_name} {kind}: {len(got)} ports from {CONNECTIONS} connections; "
                      f"outside {lo}-{hi}: {outside}")
    silent.close()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
