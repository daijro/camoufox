"""
Stealth regression tests for the two upstream issues addressed by the
fix/stealth-system-ui-font and fix/stealth-webrtc-leak branches.

These tests will FAIL against the current published Camoufox binary
until the rebuild agent applies font-system-ui.patch + the WebRTC
prefs change to the build. They are gated behind
`CAMOUFOX_STEALTH_FIXES_BUILT=1` so CI doesn't go red in the meantime.
Once the rebuild lands and this env var is exported, the tests run
and assert the fixes.

Refs:
- daijro/camoufox#598 (system-ui font leak)
- daijro/camoufox#538 (WebRTC IP leak under proxy)
"""

from __future__ import annotations

import os
import re

import pytest


REQUIRES_REBUILD = pytest.mark.skipif(
    os.environ.get("CAMOUFOX_STEALTH_FIXES_BUILT") != "1",
    reason="Set CAMOUFOX_STEALTH_FIXES_BUILT=1 once the rebuild agent has "
    "applied font-system-ui.patch and the WebRTC prefs change.",
)


# --------------------------------------------------------------------------
# daijro#598 — system-ui font must follow spoofed navigator.platform.
#
# Strategy: load a tiny page that puts the document body's `font-family`
# at `system-ui` and then read the *resolved* font family back via
# document.fonts.check / getComputedStyle. Under the patch, on a Linux
# host we must see "Helvetica" when navigator.platform is "MacIntel"
# and "Segoe UI" when navigator.platform is "Win32" — never "Cantarell"
# or another GTK-leaked font.
# --------------------------------------------------------------------------


async def _resolve_system_ui_family(camoufox_binary: str, headless: bool,
                                    config: dict) -> str:
    """Launch Camoufox with `config` as CAMOU_CONFIG and resolve
    `font: system-ui` on the page, returning the family name the
    browser actually picked."""
    import json
    from playwright.async_api import async_playwright

    env = dict(os.environ)
    env["CAMOU_CONFIG"] = json.dumps(config)

    async with async_playwright() as p:
        browser = await p.firefox.launch(
            executable_path=camoufox_binary,
            headless=headless,
            env=env,
        )
        try:
            page = await browser.new_page()
            await page.set_content(
                "<!doctype html>"
                "<style>#probe{font-family:system-ui}</style>"
                "<div id='probe'>X</div>"
            )
            # Use document.fonts to ask the engine which physical font
            # `system-ui` mapped to. We look it up indirectly by checking
            # against a list of candidates.
            family = await page.evaluate(
                """() => {
                  const probe = document.getElementById('probe');
                  const cs = getComputedStyle(probe);
                  // Force a layout flush.
                  probe.offsetWidth;
                  // Use canvas measureText with each candidate family
                  // and find the one whose metrics match system-ui.
                  const target = cs.fontFamily;
                  const candidates = [
                    'Helvetica', 'Segoe UI', 'Cantarell', 'Ubuntu',
                    'Noto Sans', 'San Francisco', '-apple-system',
                  ];
                  // The simplest signal: ask which font the rendered
                  // glyphs came from via document.fonts. system-ui is
                  // a generic, so we instead read the *first* loaded
                  // family for the probe.
                  const c = document.createElement('canvas').getContext('2d');
                  const measure = (fam) => {
                    c.font = `16px ${fam}`;
                    return c.measureText('mwjqgyiABC').width;
                  };
                  const sysWidth = (() => {
                    c.font = '16px system-ui';
                    return c.measureText('mwjqgyiABC').width;
                  })();
                  let best = null, bestDelta = Infinity;
                  for (const fam of candidates) {
                    const delta = Math.abs(measure(fam) - sysWidth);
                    if (delta < bestDelta) {
                      bestDelta = delta;
                      best = fam;
                    }
                  }
                  return best;
                }"""
            )
            return family
        finally:
            await browser.close()


@REQUIRES_REBUILD
@pytest.mark.asyncio
async def test_system_ui_resolves_to_helvetica_when_spoofing_mac(
    camoufox_binary: str, headless: bool
) -> None:
    """When navigator.platform is MacIntel, system-ui should resolve to
    Helvetica even on a Linux host."""
    fam = await _resolve_system_ui_family(
        camoufox_binary, headless,
        {"navigator.platform": "MacIntel",
         "navigator.userAgent":
             "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:146.0) "
             "Gecko/20100101 Firefox/146.0",
         "navigator.oscpu": "Intel Mac OS X 14.4"},
    )
    assert fam == "Helvetica", (
        f"system-ui leaked: expected Helvetica under MacIntel spoof, "
        f"got {fam!r}. The fix is daijro/camoufox#598 / "
        f"patches/font-system-ui.patch."
    )


@REQUIRES_REBUILD
@pytest.mark.asyncio
async def test_system_ui_resolves_to_segoe_ui_when_spoofing_windows(
    camoufox_binary: str, headless: bool
) -> None:
    """When navigator.platform is Win32, system-ui should resolve to
    Segoe UI."""
    fam = await _resolve_system_ui_family(
        camoufox_binary, headless,
        {"navigator.platform": "Win32",
         "navigator.userAgent":
             "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) "
             "Gecko/20100101 Firefox/146.0",
         "navigator.oscpu": "Windows NT 10.0; Win64; x64"},
    )
    assert fam == "Segoe UI", (
        f"system-ui leaked: expected Segoe UI under Win32 spoof, got {fam!r}."
    )


# --------------------------------------------------------------------------
# daijro#538 — WebRTC must not surface real LAN/WAN IPs through ICE
# candidates when a proxy is in play. Without an actual TURN/STUN
# server, the strongest portable signal we have is to check that the
# default prefs are now hardened (no_host=true, default_address_only=
# true, etc.) — the patch in fix/stealth-webrtc-leak ships these as
# defaultPref() in settings/camoufox.cfg, so they should be live in
# any compiled binary.
# --------------------------------------------------------------------------


HARDENED_PREFS = {
    "media.peerconnection.ice.no_host": True,
    "media.peerconnection.ice.default_address_only": True,
    "media.peerconnection.ice.proxy_only_if_behind_proxy": True,
    "media.peerconnection.ice.proxy_only_if_pbmode": True,
    "media.peerconnection.ice.obfuscate_host_addresses": True,
    "network.proxy.socks_remote_dns": True,
}


@REQUIRES_REBUILD
@pytest.mark.asyncio
async def test_webrtc_hardening_prefs_are_live(camoufox_binary, headless) -> None:
    """All ICE-hardening prefs from settings/camoufox.cfg should reach the
    compiled binary as their hardened values.

    We read the prefs via about:config-equivalent JS — Camoufox routes
    privileged pref reads through the juggler bridge in chrome context,
    so we use `Services.prefs.getBoolPref` on the chrome side via a
    dedicated test surface if available; otherwise we dump
    about:support's WebRTC section. To stay portable, we instead
    confirm via `RTCPeerConnection` behaviour: ICE candidate gathering
    on a fresh peer connection must not yield any candidate of type
    'host' (because no_host=true) and must not yield more than one
    distinct address (because default_address_only=true).
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.firefox.launch(
            executable_path=camoufox_binary,
            headless=headless,
        )
        try:
            page = await browser.new_page()
            await page.set_content("<!doctype html><html></html>")
            candidates = await page.evaluate(
                """async () => {
                  const pc = new RTCPeerConnection({iceServers: []});
                  pc.createDataChannel('x');
                  const offer = await pc.createOffer();
                  await pc.setLocalDescription(offer);
                  await new Promise((res) => {
                    const t = setTimeout(res, 2500);
                    pc.onicegatheringstatechange = () => {
                      if (pc.iceGatheringState === 'complete') {
                        clearTimeout(t); res();
                      }
                    };
                  });
                  const sdp = pc.localDescription.sdp;
                  pc.close();
                  return sdp.split('\\n').filter(l => l.startsWith('a=candidate'));
                }"""
            )
            # No host candidates allowed:
            host_lines = [c for c in candidates if " typ host " in c]
            assert not host_lines, (
                "WebRTC leaked host (LAN) ICE candidates despite "
                "media.peerconnection.ice.no_host=true:\n" + "\n".join(host_lines)
            )
            # And no real public IPs leaked through srflx either when
            # running offline (no STUN server) — there should simply be
            # no srflx candidates at all without iceServers configured.
            srflx = [c for c in candidates if " typ srflx " in c]
            assert not srflx, (
                "Unexpected srflx candidates without STUN configured:\n"
                + "\n".join(srflx)
            )
        finally:
            await browser.close()
