/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Camoufox's per-window and startup work. It lives here rather than in
// browser-init.js because chrome://browser/content/ is content-accessible: a page
// can load that file and read its functions back, so it must stay byte-identical
// to stock. Registered by category entries in camoufox-window-module.patch.

const lazy = {};
ChromeUtils.defineESModuleGetters(lazy, {
  AddonManager: "resource://gre/modules/AddonManager.sys.mjs",
  FileUtils: "resource://gre/modules/FileUtils.sys.mjs",
});

// Default-branch prefs are never written to prefs.js, so they reset every launch.
const ADDONS_INSTALLED_PREF = "camoufox.addons.installed";
const CERTS_IMPORTED_PREF = "camoufox.certificates.imported";

function debug(msg) {
  ChromeUtils.camouDebug(msg);
}

function onceThisLaunch(pref) {
  const defaults = Services.prefs.getDefaultBranch("");
  if (defaults.getBoolPref(pref, false)) {
    return false;
  }
  defaults.setBoolPref(pref, true);
  return true;
}

function processRawCertificate(content) {
  return content.replace(/\-{5}[\w]+\s[\w]+\-{5}/g, "").replace(/\s/g, "");
}

function importCertificate(certdb, certData, source) {
  try {
    certdb.addCertFromBase64(certData, "C,C,C", "");
    debug("Successfully imported " + source + " certificate");
  } catch (e) {
    debug("Failed to import " + source + " certificate: " + e);
  }
}

async function readCertFile(path) {
  debug("Reading certificate file: " + path);
  const file = new lazy.FileUtils.File(path);
  const ioService = Cc["@mozilla.org/network/io-service;1"].getService(Ci.nsIIOService);
  const channel = ioService.newChannelFromURI(
    ioService.newFileURI(file),
    null,
    Services.scriptSecurityManager.getSystemPrincipal(),
    null,
    Ci.nsILoadInfo.SEC_ALLOW_CROSS_ORIGIN_SEC_CONTEXT_IS_NULL,
    Ci.nsIContentPolicy.TYPE_OTHER
  );
  const inputStream = Cc["@mozilla.org/scriptableinputstream;1"].createInstance(
    Ci.nsIScriptableInputStream
  );
  const input = channel.open();
  inputStream.init(input);
  const content = inputStream.read(input.available());
  inputStream.close();
  input.close();
  return processRawCertificate(content);
}

async function installTemporaryAddon(addonPath) {
  const addon = await lazy.AddonManager.installTemporaryAddon(new lazy.FileUtils.File(addonPath));
  Services.obs.notifyObservers(null, "devtools-installed-addon", addon.id);
  return addon;
}

function installAddons() {
  const addonPaths = ChromeUtils.camouGetStringList("addons");
  if (!addonPaths?.length || !onceThisLaunch(ADDONS_INSTALLED_PREF)) {
    return;
  }
  Promise.all(addonPaths.map(installTemporaryAddon))
    .then(addons => debug("Installed " + addons.length + " addon(s)"))
    .catch(e => debug("Failed to install addons: " + e));
}

function importCertificates() {
  const certsPaths = ChromeUtils.camouGetStringList("certificatePaths");
  const certsRaw = ChromeUtils.camouGetStringList("certificates");
  if (!(certsPaths?.length || certsRaw?.length) || !onceThisLaunch(CERTS_IMPORTED_PREF)) {
    return;
  }
  debug("Found certificates to import");
  let certdb = Cc["@mozilla.org/security/x509certdb;1"].getService(Ci.nsIX509CertDB);
  try {
    certdb = Cc["@mozilla.org/security/x509certdb;1"].getService(Ci.nsIX509CertDB2);
  } catch (e) {}
  if (certsPaths?.length) {
    debug("Processing " + certsPaths.length + " certificate files");
    Promise.all(certsPaths.map(readCertFile))
      .then(all => all.forEach(certData => importCertificate(certdb, certData, "from file")))
      .catch(e => debug("Failed to read certificate files: " + e));
  }
  for (const rawCert of certsRaw || []) {
    try {
      importCertificate(certdb, processRawCertificate(rawCert), "raw");
    } catch (e) {
      debug("Failed to process raw certificate: " + e);
    }
  }
}

function applyWindowSize(win) {
  // outerWidth/outerHeight report the real window, so the real window is resized
  // to the identity's size; pinning the document instead deadlocks Juggler's
  // viewport handshake (daijro/camoufox#666). Without an identity size, stock's
  // own startup sizing applies. So it does for a window a page opened: stock
  // gives it the size its window.open() features ask for.
  const appWindow = win.docShell.treeOwner
    .QueryInterface(Ci.nsIInterfaceRequestor)
    .getInterface(Ci.nsIAppWindow);
  if (appWindow.initialOpenWindowInfo) {
    return;
  }
  const outerWidth = ChromeUtils.camouGetInt("window.outerWidth");
  const outerHeight = ChromeUtils.camouGetInt("window.outerHeight");
  if (outerWidth || outerHeight) {
    win.resizeTo(outerWidth || win.outerWidth, outerHeight || win.outerHeight);
    // Hold that size through startup. mutter auto-maximizes a new window
    // covering >= 80% of the work area, and GTK adds its decoration margins to
    // the outer size only once the window is mapped, which left a page reading
    // the identity's size plus 10px. After the deadline a change is the user's.
    const deadline = Date.now() + 5000;
    const holdStartupSize = () => {
      if (Date.now() > deadline) {
        win.removeEventListener("sizemodechange", holdStartupSize);
        win.removeEventListener("resize", holdStartupSize);
        return;
      }
      if (win.windowState === win.STATE_MAXIMIZED) {
        win.restore();
      }
      const dw = outerWidth ? outerWidth - win.outerWidth : 0;
      const dh = outerHeight ? outerHeight - win.outerHeight : 0;
      if (dw || dh) {
        win.resizeBy(dw, dh);
      }
    };
    win.addEventListener("sizemodechange", holdStartupSize);
    win.addEventListener("resize", holdStartupSize);
  }

  const innerWidth = ChromeUtils.camouGetInt("window.innerWidth");
  const innerHeight = ChromeUtils.camouGetInt("window.innerHeight");
  if (!innerWidth && !innerHeight) {
    return;
  }
  const doc = win.document;
  doc.getElementById("browser")?.style.setProperty("box-sizing", "content-box");
  const style = doc.createElement("style");
  style.textContent = `
    .browserStack {
      ${innerWidth ? `width: ${innerWidth}px !important;` : ""}
      ${innerHeight ? `height: ${innerHeight}px !important;` : ""}
      ${innerHeight ? "flex: unset !important;" : ""}
      overflow: auto;
      contain: size;
      scrollbar-width: none;
    }
  `;
  doc.head.appendChild(style);
  if (innerWidth && innerHeight && !(outerWidth || outerHeight)) {
    // Grow the window so the pinned stack fits.
    win.requestAnimationFrame(() => {
      const stack = win.gBrowser?.selectedBrowser?.closest(".browserStack");
      const top = stack ? stack.getBoundingClientRect().y : 0;
      win.resizeBy(innerWidth - win.innerWidth, innerHeight + top - win.innerHeight);
    });
  }
}

function addDebugListeners(win) {
  if (!ChromeUtils.isCamouDebug()) {
    return;
  }
  debug("Debug mode ON.");
  win.gBrowser.addTabsProgressListener({
    onLocationChange(aBrowser, aWebProgress, aRequest, aLocation) {
      if (aBrowser === win.gBrowser.selectedBrowser) {
        debug("URL changed to: " + aLocation.spec);
      }
    },
  });
  win.gURLBar?.addEventListener("change", () => debug("URL bar value changed to: " + win.gURLBar.value));
}

function addCursorFollower(win) {
  // Debugging aid only: a visible automation cue, so opt-in (showcursor=true).
  if (!ChromeUtils.camouGetBool("showcursor", false)) {
    return;
  }
  const doc = win.document;
  const dot = doc.createElement("div");
  dot.id = "cursor-highlighter";
  dot.style.cssText = `
    position: fixed; width: 10px; height: 10px; background-color: rgba(255,105,105,0.8);
    border-radius: 50%; pointer-events: none; z-index: 2147483647; transform: translate(-50%, -50%);
    box-shadow: 0 0 0 5px rgba(255,105,105,0.5), 0 0 0 10px rgba(255,105,105,0.3), 0 0 0 15px rgba(255,105,105,0.1);
  `;
  doc.documentElement.appendChild(dot);
  win.addEventListener("mousemove", e => {
    dot.style.left = `${e.clientX}px`;
    dot.style.top = `${e.clientY}px`;
  });
}

function applyAcceptLanguages() {
  let camouLocale =
    ChromeUtils.camouGetString("locale:all") || ChromeUtils.camouGetString("navigator.language");
  if (!camouLocale) {
    const language = ChromeUtils.camouGetString("locale:language");
    const region = ChromeUtils.camouGetString("locale:region");
    if (language && region) {
      camouLocale = language + "-" + region + ", " + language;
    }
  }
  if (camouLocale) {
    Services.prefs.setCharPref("intl.accept_languages", camouLocale);
  }
}

export const CamoufoxWindow = {
  onStartup() {
    applyAcceptLanguages();
  },

  // Called from gBrowserInit.onLoad() with the window. The category's jsGlobal
  // is consumed by BrowserUtils.callModulesFromCategory, not passed on.
  onWindowLoad(win) {
    for (const step of [applyWindowSize, addDebugListeners, addCursorFollower]) {
      try {
        step(win);
      } catch (e) {
        debug(`CamoufoxWindow ${step.name} failed: ${e}`);
      }
    }
    installAddons();
    importCertificates();
  },
};
