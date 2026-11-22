/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/**
 * Whether Firefox's connections go through a system proxy: `proxyType` is
 * network.proxy.type and `settings` the nsISystemProxySettings service, or
 * null where there is none.
 *
 * This answers as nsProtocolProxyService resolves, which treats a failed call
 * as an absent setting: a PACURI that fails or is empty is no PAC file (macOS
 * fails when none is set, Linux and Windows return ""), and a getProxyForURI
 * that fails is no proxy (Linux fails when none is set), so the connection is
 * direct. A failure here is never an error to raise: this runs while Juggler
 * starts, and a throw there leaves the client waiting forever (#1116).
 */
export function usesSystemProxy(proxyType, settings) {
  if (proxyType !== 5 || !settings)
    return false;
  try {
    if (settings.PACURI)
      return true;
  } catch (e) {
    // No PAC file.
  }
  try {
    return settings.getProxyForURI('https://camoufox.invalid/', 'https', 'camoufox.invalid', 443) !== 'DIRECT';
  } catch (e) {
    return false;
  }
}
