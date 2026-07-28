/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

const {Helper} = ChromeUtils.importESModule('chrome://juggler/content/Helper.js');
const {Preferences} = ChromeUtils.importESModule("resource://gre/modules/Preferences.sys.mjs");
const {ContextualIdentityService} = ChromeUtils.importESModule("resource://gre/modules/ContextualIdentityService.sys.mjs");
const {NetUtil} = ChromeUtils.importESModule('resource://gre/modules/NetUtil.sys.mjs');
const {AppConstants} = ChromeUtils.importESModule("resource://gre/modules/AppConstants.sys.mjs");
// This module's scope has no timer globals (unlike the content-side juggler
// scripts), so the screencast tick has to import them explicitly.
const {setTimeout, clearTimeout} = ChromeUtils.importESModule("resource://gre/modules/Timer.sys.mjs");

const Cr = Components.results;

const helper = new Helper();

const IDENTITY_NAME = 'JUGGLER ';
const HUNDRED_YEARS = 60 * 60 * 24 * 365 * 100;

// Capture rate for the compositor-backed screencast. Playwright muxes at 25fps
// and repeats frames to fill gaps, so this is an upper bound on capture cost
// rather than the video's frame rate; the ack-driven backpressure in
// _startSnapshotScreencast lowers it further whenever encoding cannot keep up.
const SNAPSHOT_SCREENCAST_FPS = 25;

const ALL_PERMISSIONS = [
  'geo',
  'desktop-notification',
];

let globalTabAndWindowActivationChain = Promise.resolve();
let globalNewPageChain = Promise.resolve();

class DownloadInterceptor {
  constructor(registry) {
    this._registry = registry
    this._handlerToUuid = new Map();
    this._uuidToHandler = new Map();
  }

  //
  // nsIDownloadInterceptor implementation.
  //
  interceptDownloadRequest(externalAppHandler, request, browsingContext, outFile) {
    if (!(request instanceof Ci.nsIChannel))
      return false;
    const channel = request.QueryInterface(Ci.nsIChannel);
    let pageTarget = this._registry._browserIdToTarget.get(channel.loadInfo.browsingContext.top.browserId);
    if (!pageTarget)
      return false;

    const browserContext = pageTarget.browserContext();
    const options = browserContext.downloadOptions;
    if (!options)
      return false;

    const uuid = helper.generateId();
    let file = null;
    if (options.behavior === 'saveToDisk') {
      file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
      file.initWithPath(options.downloadsDir);
      file.append(uuid);

      try {
        file.create(Ci.nsIFile.NORMAL_FILE_TYPE, 0o600);
      } catch (e) {
        dump(`WARNING: interceptDownloadRequest failed to create file: ${e}`);
        return false;
      }
    }
    outFile.value = file;
    this._handlerToUuid.set(externalAppHandler, uuid);
    this._uuidToHandler.set(uuid, externalAppHandler);
    const downloadInfo = {
      uuid,
      browserContextId: browserContext.browserContextId,
      pageTargetId: pageTarget.id(),
      frameId: helper.browsingContextToFrameId(channel.loadInfo.browsingContext),
      url: request.name,
      suggestedFileName: externalAppHandler.suggestedFileName,
    };
    this._registry.emit(TargetRegistry.Events.DownloadCreated, downloadInfo);
    return true;
  }

  onDownloadComplete(externalAppHandler, canceled, errorName) {
    const uuid = this._handlerToUuid.get(externalAppHandler);
    if (!uuid)
      return;
    this._handlerToUuid.delete(externalAppHandler);
    this._uuidToHandler.delete(uuid);
    const downloadInfo = {
      uuid,
      error: errorName,
    };
    if (canceled === 'NS_BINDING_ABORTED') {
      downloadInfo.canceled = true;
    }
    this._registry.emit(TargetRegistry.Events.DownloadFinished, downloadInfo);
  }

  async cancelDownload(uuid) {
    const externalAppHandler = this._uuidToHandler.get(uuid);
    if (!externalAppHandler) {
      return;
    }
    await externalAppHandler.cancel(Cr.NS_BINDING_ABORTED);
  }
}

const screencastService = Cc['@mozilla.org/juggler/screencast;1'].getService(Ci.nsIScreencastService);

export class TargetRegistry {
  static instance() {
    return TargetRegistry._instance || null;
  }

  constructor() {
    helper.decorateAsEventEmitter(this);
    TargetRegistry._instance = this;

    this._browserContextIdToBrowserContext = new Map();
    this._userContextIdToBrowserContext = new Map();
    this._browserToTarget = new Map();
    this._browserIdToTarget = new Map();
    // Firefox 152+: a window.open() popup's content-process WindowGlobal actor
    // (JugglerFrameParent.actorCreated) can be created BEFORE the chrome-side
    // `TabOpen` fires and the PageTarget is registered. The old self-binding
    // actor then found no target and bailed with no retry, so the popup's page
    // channel never became ready -> `Page.ready` never reached the client ->
    // `page.on('popup')` never fired. Track actors here so binding happens
    // whenever either side appears, in either order (matches upstream Playwright).
    this._browserIdToActor = new Map();

    this._proxiesWithClashingAuthCacheKeys = new Set();
    this._browserProxy = null;

    // Cleanup containers from previous runs (if any)
    for (const identity of ContextualIdentityService.getPublicIdentities()) {
      if (identity.name && identity.name.startsWith(IDENTITY_NAME)) {
        ContextualIdentityService.remove(identity.userContextId);
        ContextualIdentityService.closeContainerTabs(identity.userContextId);
      }
    }

    this._defaultContext = new BrowserContext(this, undefined, undefined);

    Services.obs.addObserver({
      observe: (subject, topic, data) => {
        const browser = subject.ownerElement;
        if (!browser)
          return;
        const target = this._browserToTarget.get(browser);
        if (!target)
          return;
        target.emit(PageTarget.Events.Crashed);
        target.dispose();
      }
    }, 'oop-frameloader-crashed');

    const onTabOpenListener = (appWindow, window, event) => {
      const tab = event.target;
      const userContextId = tab.userContextId;
      const browserContext = this._userContextIdToBrowserContext.get(userContextId);
      const hasExplicitSize = appWindow && (appWindow.chromeFlags & Ci.nsIWebBrowserChrome.JUGGLER_WINDOW_EXPLICIT_SIZE) !== 0;
      const openerContext = tab.linkedBrowser.browsingContext.opener;
      let openerTarget;
      if (openerContext) {
        // Popups usually have opener context. Get top context for the case when opener is
        // an iframe.
        openerTarget = this._browserIdToTarget.get(openerContext.top.browserId);
      } else if (tab.openerTab) {
        // Noopener popups from the same window have opener tab instead.
        openerTarget = this._browserToTarget.get(tab.openerTab.linkedBrowser);
      }
      if (!browserContext)
        throw new Error(`Internal error: cannot find context for userContextId=${userContextId}`);
      const target = new PageTarget(this, window, tab, browserContext, openerTarget);
      target.updateOverridesForBrowsingContext(tab.linkedBrowser.browsingContext);
      if (!hasExplicitSize)
        target.updateViewportSize();
      if (browserContext.videoRecordingOptions)
        target._startVideoRecording(browserContext.videoRecordingOptions);
    };

    const onTabCloseListener = event => {
      const tab = event.target;
      const linkedBrowser = tab.linkedBrowser;
      const target = this._browserToTarget.get(linkedBrowser);
      if (target)
          target.dispose();
    };

    const domWindowTabListeners = new Map();

    const onOpenWindow = async (appWindow) => {
      let domWindow;
      if (appWindow instanceof Ci.nsIAppWindow) {
        domWindow = appWindow.QueryInterface(Ci.nsIInterfaceRequestor).getInterface(Ci.nsIDOMWindowInternal || Ci.nsIDOMWindow);
      } else {
        domWindow = appWindow;
        appWindow = null;
      }
      if (!domWindow.isChromeWindow)
        return;
      // In persistent mode, window might be opened long ago and might be
      // already initialized.
      //
      // In this case, we want to keep this callback synchronous so that we will call
      // `onTabOpenListener` synchronously and before the sync IPc message `juggler:content-ready`.
      if (domWindow.document.readyState === 'uninitialized' || domWindow.document.readyState === 'loading') {
        // For non-initialized windows, DOMContentLoaded initializes gBrowser
        // and starts tab loading (see //browser/base/content/browser.js), so we
        // are guaranteed to call `onTabOpenListener` before the sync IPC message
        // `juggler:content-ready`.
        await helper.awaitEvent(domWindow, 'DOMContentLoaded');
      }

      // Firefox 150+: chrome window may report readyState=complete before
      // gBrowser is populated. Wait for it if missing.
      if (!domWindow.gBrowser) {
        await new Promise((resolve, reject) => {
          const start = Date.now();
          const tick = () => {
            if (domWindow.gBrowser) return resolve();
            if (Date.now() - start > 15000) return reject(new Error('gBrowser never populated'));
            domWindow.setTimeout(tick, 50);
          };
          tick();
        });
      }
      if (!domWindow.gBrowser)
        return;
      const tabContainer = domWindow.gBrowser.tabContainer;
      domWindowTabListeners.set(domWindow, [
        helper.addEventListener(tabContainer, 'TabOpen', event => onTabOpenListener(appWindow, domWindow, event)),
        helper.addEventListener(tabContainer, 'TabClose', onTabCloseListener),
      ]);
      for (const tab of domWindow.gBrowser.tabs)
        onTabOpenListener(appWindow, domWindow, { target: tab });
    };

    const onCloseWindow = window => {
      const domWindow = window.QueryInterface(Ci.nsIInterfaceRequestor).getInterface(Ci.nsIDOMWindowInternal || Ci.nsIDOMWindow);
      if (!domWindow.isChromeWindow)
        return;
      if (!domWindow.gBrowser)
        return;

      const listeners = domWindowTabListeners.get(domWindow) || [];
      domWindowTabListeners.delete(domWindow);
      helper.removeListeners(listeners);
      for (const tab of domWindow.gBrowser.tabs)
        onTabCloseListener({ target: tab });
    };

    const extHelperAppSvc = Cc["@mozilla.org/uriloader/external-helper-app-service;1"].getService(Ci.nsIExternalHelperAppService);
    this._downloadInterceptor = new DownloadInterceptor(this);
    extHelperAppSvc.setDownloadInterceptor(this._downloadInterceptor);

    Services.wm.addListener({ onOpenWindow, onCloseWindow });
    for (const win of Services.wm.getEnumerator(null))
      onOpenWindow(win);
  }

  // Firefox uses nsHttpAuthCache to cache authentication to the proxy.
  // If we're provided with a single proxy with a multiple different authentications, then
  // we should clear the nsHttpAuthCache on every request.
  shouldBustHTTPAuthCacheForProxy(proxy) {
    return this._proxiesWithClashingAuthCacheKeys.has(proxy);
  }

  _updateProxiesWithSameAuthCacheAndDifferentCredentials() {
    const proxyIdToCredentials = new Map();
    const allProxies = [...this._browserContextIdToBrowserContext.values()].map(bc => bc._proxy).filter(Boolean);
    if (this._browserProxy)
      allProxies.push(this._browserProxy);
    const proxyAuthCacheKeyAndProxy = allProxies.map(proxy => [
      JSON.stringify({
        type: proxy.type,
        host: proxy.host,
        port: proxy.port,
      }),
      proxy,
    ]);
    this._proxiesWithClashingAuthCacheKeys.clear();

    proxyAuthCacheKeyAndProxy.sort(([cacheKey1], [cacheKey2]) => cacheKey1 < cacheKey2 ? -1 : 1);
    for (let i = 0; i < proxyAuthCacheKeyAndProxy.length - 1; ++i) {
      const [cacheKey1, proxy1] = proxyAuthCacheKeyAndProxy[i];
      const [cacheKey2, proxy2] = proxyAuthCacheKeyAndProxy[i + 1];
      if (cacheKey1 !== cacheKey2)
        continue;
      if (proxy1.username === proxy2.username && proxy1.password === proxy2.password)
        continue;
      // `proxy1` and `proxy2` have the same caching key, but serve different credentials.
      // We have to bust HTTP Auth Cache everytime there's a request that will use either of the proxies.
      this._proxiesWithClashingAuthCacheKeys.add(proxy1);
      this._proxiesWithClashingAuthCacheKeys.add(proxy2);
    }
  }

  async cancelDownload(options) {
    this._downloadInterceptor.cancelDownload(options.uuid);
  }

  setBrowserProxy(proxy) {
    this._browserProxy = proxy;
    this._updateProxiesWithSameAuthCacheAndDifferentCredentials();
  }

  getProxyInfo(channel) {
    const originAttributes = channel.loadInfo && channel.loadInfo.originAttributes;
    const browserContext = originAttributes ? this.browserContextForUserContextId(originAttributes.userContextId) : null;
    // Prefer context proxy and fallback to browser-level proxy.
    const proxyInfo = (browserContext && browserContext._proxy) || this._browserProxy;
    if (!proxyInfo || proxyInfo.bypass.some(domainSuffix => channel.URI.host.endsWith(domainSuffix)))
      return null;
    return proxyInfo;
  }

  defaultContext() {
    return this._defaultContext;
  }

  createBrowserContext(removeOnDetach) {
    return new BrowserContext(this, helper.generateId(), removeOnDetach);
  }

  browserContextForId(browserContextId) {
    return this._browserContextIdToBrowserContext.get(browserContextId);
  }

  browserContextForUserContextId(userContextId) {
    return this._userContextIdToBrowserContext.get(userContextId);
  }

  async newPage({browserContextId}) {
    const result = globalNewPageChain.then(() => this._newPageInternal({browserContextId}));
    globalNewPageChain = result.catch(error => { /* swallow errors to keep chain running */ });
    return result;
  }

  async _newPageInternal({browserContextId}) {
    const browserContext = this.browserContextForId(browserContextId);
    const features = "chrome,dialog=no,all";
    // See _callWithURIToLoad in browser.js for the structure of window.arguments
    // window.arguments[1]: unused (bug 871161)
    //                 [2]: referrerInfo (nsIReferrerInfo)
    //                 [3]: postData (nsIInputStream)
    //                 [4]: allowThirdPartyFixup (bool)
    //                 [5]: userContextId (int)
    //                 [6]: originPrincipal (nsIPrincipal)
    //                 [7]: originStoragePrincipal (nsIPrincipal)
    //                 [8]: triggeringPrincipal (nsIPrincipal)
    //                 [9]: allowInheritPrincipal (bool)
    //                 [10]: csp (nsIContentSecurityPolicy)
    //                 [11]: nsOpenWindowInfo
    const args = Cc["@mozilla.org/array;1"].createInstance(Ci.nsIMutableArray);
    const urlSupports = Cc["@mozilla.org/supports-string;1"].createInstance(
      Ci.nsISupportsString
    );
    urlSupports.data = 'about:blank';
    args.appendElement(urlSupports); // 0
    args.appendElement(undefined); // 1
    args.appendElement(undefined); // 2
    args.appendElement(undefined); // 3
    args.appendElement(undefined); // 4
    const userContextIdSupports = Cc[
      "@mozilla.org/supports-PRUint32;1"
    ].createInstance(Ci.nsISupportsPRUint32);
    userContextIdSupports.data = browserContext.userContextId;
    args.appendElement(userContextIdSupports); // 5
    args.appendElement(undefined); // 6
    args.appendElement(undefined); // 7
    args.appendElement(Services.scriptSecurityManager.getSystemPrincipal()); // 8

    const window = Services.ww.openWindow(null, AppConstants.BROWSER_CHROME_URL, '_blank', features, args);
    await waitForWindowReady(window);
    if (window.gBrowser.browsers.length !== 1)
      throw new Error(`Unexpected number of tabs in the new window: ${window.gBrowser.browsers.length}`);
    const browser = window.gBrowser.browsers[0];
    let target = this._browserToTarget.get(browser);
    while (!target) {
      await helper.awaitEvent(this, TargetRegistry.Events.TargetCreated);
      target = this._browserToTarget.get(browser);
    }
    browser.focus();
    if (browserContext.crossProcessCookie.settings.timezoneId) {
      if (await target.hasFailedToOverrideTimezone())
        throw new Error('Failed to override timezone');
    }
    return target.id();
  }

  targets() {
    return Array.from(this._browserToTarget.values());
  }

  targetForBrowser(browser) {
    return this._browserToTarget.get(browser);
  }

  targetForBrowserId(browserId) {
    return this._browserIdToTarget.get(browserId);
  }

  // Called from JugglerFrameParent.actorCreated for every main-frame
  // WindowGlobalParent. Records the actor and binds it to its PageTarget if the
  // target already exists; if not, PageTarget's constructor will bind it later.
  onActorCreated(actor) {
    // Only interested in main frames for now.
    if (actor.browsingContext.parent)
      return;
    const browserId = actor.browsingContext.browserId;
    this._browserIdToActor.set(browserId, actor);
    const target = this._browserIdToTarget.get(browserId);
    target?.setActor(actor);
  }

  onActorDestroyed(actor) {
    // browsingContext can be null once the WindowGlobal is fully torn down.
    const browserId = actor.browsingContext?.browserId;
    if (browserId === undefined) {
      // Fall back to clearing whichever entry points at this actor.
      for (const [id, a] of this._browserIdToActor) {
        if (a === actor) {
          this._browserIdToTarget.get(id)?.removeActor(actor);
          this._browserIdToActor.delete(id);
        }
      }
      return;
    }
    const target = this._browserIdToTarget.get(browserId);
    target?.removeActor(actor);
    if (this._browserIdToActor.get(browserId) === actor)
      this._browserIdToActor.delete(browserId);
  }
}

export class PageTarget {
  constructor(registry, win, tab, browserContext, opener) {
    helper.decorateAsEventEmitter(this);

    this._targetId = helper.generateId();
    this._registry = registry;
    this._window = win;
    this._gBrowser = win.gBrowser;
    this._tab = tab;
    this._linkedBrowser = tab.linkedBrowser;
    this._browserContext = browserContext;
    this._viewportSize = undefined;
    this._zoom = 1;
    this._initialDPPX = this._linkedBrowser.browsingContext.overrideDPPX;
    this._url = 'about:blank';
    this._openerId = opener ? opener.id() : undefined;
    this._actor = undefined;
    this._actorSequenceNumber = 0;
    this._channel = new SimpleChannel(`browser::page[${this._targetId}]`, 'target-' + this._targetId);
    this._videoRecordingInfo = undefined;
    this._screencastRecordingInfo = undefined;
    this._dialogs = new Map();
    this.forcedColors = 'none';
    this.disableCache = false;
    this.mediumOverride = '';
    this.crossProcessCookie = {
      initScripts: [],
      bindings: [],
      interceptFileChooserDialog: false,
    };

    const navigationListener = {
      QueryInterface: ChromeUtils.generateQI([Ci.nsIWebProgressListener, Ci.nsISupportsWeakReference]),
      onLocationChange: (aWebProgress, aRequest, aLocation) => this._onNavigated(aLocation),
    };
    this._eventListeners = [
      helper.addObserver(this._updateModalDialogs.bind(this), 'common-dialog-loaded'),
      helper.addProgressListener(tab.linkedBrowser, navigationListener, Ci.nsIWebProgress.NOTIFY_LOCATION),
      helper.addEventListener(this._linkedBrowser, 'DOMModalDialogClosed', event => this._updateModalDialogs()),
      helper.addEventListener(this._linkedBrowser, 'WillChangeBrowserRemoteness', event => this._willChangeBrowserRemoteness()),
    ];

    this._disposed = false;
    browserContext.pages.add(this);
    this._registry._browserToTarget.set(this._linkedBrowser, this);
    const browserId = this._linkedBrowser.browsingContext.browserId;
    this._registry._browserIdToTarget.set(browserId, this);
    // Firefox 152+: the content-process actor may already exist (window.open
    // popups create the actor before TabOpen). Bind it now so the page channel
    // becomes ready and `Page.ready` reaches the client. See _browserIdToActor.
    const actor = this._registry._browserIdToActor.get(browserId);
    if (actor)
      this.setActor(actor);

    this._registry.emit(TargetRegistry.Events.TargetCreated, this);
  }

  async activateAndRun(callback = () => {}, { muteNotificationsPopup = false } = {}) {
    // Firefox 152 renamed `ownerGlobal` to `documentGlobal` on nodes.
    const ownerWindow = this._tab.linkedBrowser.documentGlobal || this._tab.linkedBrowser.ownerGlobal;
    const tabBrowser = ownerWindow.gBrowser;
    // Serialize all tab-switching commands per tabbed browser
    // to disallow concurrent tab switching.
    const result = globalTabAndWindowActivationChain.then(async () => {
      this._window.focus();
      if (tabBrowser.selectedTab !== this._tab) {
        const promise = helper.awaitEvent(ownerWindow, 'TabSwitchDone');
        tabBrowser.selectedTab = this._tab;
        await promise;
      }
      const notificationsPopup = muteNotificationsPopup ? this._linkedBrowser?.ownerDocument.getElementById('notification-popup') : null;
      notificationsPopup?.style.setProperty('pointer-events', 'none');
      try {
        await callback();
      } finally {
        notificationsPopup?.style.removeProperty('pointer-events');
      }
    });
    globalTabAndWindowActivationChain = result.catch(error => { /* swallow errors to keep chain running */ });
    return result;
  }

  frameIdToBrowsingContext(frameId) {
    return helper.collectAllBrowsingContexts(this._linkedBrowser.browsingContext).find(bc => helper.browsingContextToFrameId(bc) === frameId);
  }

  nextActorSequenceNumber() {
    return ++this._actorSequenceNumber;
  }

  setActor(actor) {
    this._actor = actor;
    // Name the actor here (target-side) rather than in JugglerFrameParent so it
    // is set no matter which side binds first. SimpleChannel.bindToActor reads
    // actor.actorName for its debug channel name.
    actor.actorName = `browser::page[${this.id()}]/${actor.browsingContext.browserId}/${actor.browsingContext.id}/${this.nextActorSequenceNumber()}`;
    this._channel.bindToActor(actor);
  }

  removeActor(actor) {
    // Note: the order between setActor and removeActor is non-deterministic.
    // Therefore we check that we are still bound to the actor that is being removed.
    if (this._actor !== actor)
      return;
    this._actor = undefined;
    this._channel.resetTransport();
  }

  _willChangeBrowserRemoteness() {
    this.removeActor(this._actor);
  }

  dialog(dialogId) {
    return this._dialogs.get(dialogId);
  }

  dialogs() {
    return [...this._dialogs.values()];
  }

  async windowReady() {
    await waitForWindowReady(this._window);
  }

  linkedBrowser() {
    return this._linkedBrowser;
  }

  browserContext() {
    return this._browserContext;
  }

  updateOverridesForBrowsingContext(browsingContext = undefined) {
    this.updateTouchOverride(browsingContext);
    this.updateUserAgent(browsingContext);
    this.updatePlatform(browsingContext);
    this.updateDPPXOverride(browsingContext);
    this.updateZoom(browsingContext);
    this.updateEmulatedMedia(browsingContext);
    this.updateColorSchemeOverride(browsingContext);
    this.updateReducedMotionOverride(browsingContext);
    this.updateContrastOverride(browsingContext);
    this.updateForcedColorsOverride(browsingContext);
    this.updateForceOffline(browsingContext);
    this.updateCacheDisabled(browsingContext);
  }

  updateForceOffline(browsingContext = undefined) {
    (browsingContext || this._linkedBrowser.browsingContext).forceOffline = this._browserContext.forceOffline;
  }

  setCacheDisabled(disabled) {
    this.disableCache = disabled;
    this.updateCacheDisabled();
  }

  updateCacheDisabled(browsingContext = this._linkedBrowser.browsingContext) {
    const enableFlags = Ci.nsIRequest.LOAD_NORMAL;
    // Camoufox: upstream also sets LOAD_BYPASS_CACHE here, which makes necko put
    // "Pragma: no-cache" and "Cache-Control: no-cache" on every request. Firefox only
    // does that for a forced reload, and Playwright turns this on for every page.route()
    // call, so it marks all our traffic as automated. INHIBIT_CACHING alone stops
    // responses from ever being stored, which starves the cache just as effectively
    // without announcing it to the server.
    const disableFlags = Ci.nsIRequest.INHIBIT_CACHING;

    browsingContext.defaultLoadFlags = (this._browserContext.disableCache || this.disableCache) ? disableFlags : enableFlags;
  }

  updateTouchOverride(browsingContext = undefined) {
    (browsingContext || this._linkedBrowser.browsingContext).touchEventsOverride = this._browserContext.touchOverride ? 'enabled' : 'none';
  }

  updateUserAgent(browsingContext = undefined) {
    (browsingContext || this._linkedBrowser.browsingContext).customUserAgent = this._browserContext.defaultUserAgent;
  }

  updatePlatform(browsingContext = undefined) {
    (browsingContext || this._linkedBrowser.browsingContext).customPlatform = this._browserContext.defaultPlatform;
  }

  updateDPPXOverride(browsingContext = undefined) {
    browsingContext ||= this._linkedBrowser.browsingContext;
    const dppx = this._zoom * (this._browserContext.deviceScaleFactor || this._initialDPPX);
    browsingContext.overrideDPPX = dppx;
  }

  async updateZoom(browsingContext = undefined) {
    browsingContext ||= this._linkedBrowser.browsingContext;
    // Update dpr first, and then UI zoom.
    this.updateDPPXOverride(browsingContext);
    browsingContext.fullZoom = this._zoom;
  }

  _updateModalDialogs() {
    const prompts = new Set(this._linkedBrowser.tabDialogBox.getContentDialogManager().dialogs.map(dialog => dialog.frameContentWindow.Dialog));
    for (const dialog of this._dialogs.values()) {
      if (!prompts.has(dialog.prompt())) {
        this._dialogs.delete(dialog.id());
        this.emit(PageTarget.Events.DialogClosed, dialog);
      } else {
        prompts.delete(dialog.prompt());
      }
    }
    for (const prompt of prompts) {
      const dialog = Dialog.createIfSupported(prompt);
      if (!dialog)
        continue;
      this._dialogs.set(dialog.id(), dialog);
      this.emit(PageTarget.Events.DialogOpened, dialog);
    }
  }

  async updateViewportSize() {
    await waitForWindowReady(this._window);
    this.updateDPPXOverride();

    // Viewport size is defined by three arguments:
    // 1. default size. Could be explicit if set as part of `window.open` call, e.g.
    //   `window.open(url, title, 'width=400,height=400')`
    // 2. page viewport size
    // 3. browserContext viewport size
    //
    // The "default size" (1) is only respected when the page is opened.
    // Otherwise, explicitly set page viewport prevales over browser context
    // default viewport.
    const viewportSize = this._viewportSize || this._browserContext.defaultViewportSize;
    if (viewportSize) {
      const {width, height} = viewportSize;
      this._linkedBrowser.style.setProperty('width', width + 'px');
      this._linkedBrowser.style.setProperty('height', height + 'px');
      this._linkedBrowser.style.setProperty('box-sizing', 'content-box');
      this._linkedBrowser.closest('.browserStack').style.setProperty('overflow', 'auto');
      this._linkedBrowser.closest('.browserStack').style.setProperty('contain', 'size');
      this._linkedBrowser.closest('.browserStack').style.setProperty('scrollbar-width', 'none');
      this._linkedBrowser.browsingContext.inRDMPane = true;

      const stackRect = this._linkedBrowser.closest('.browserStack').getBoundingClientRect();
      const toolbarTop = stackRect.y;
      this._window.resizeBy(width - this._window.innerWidth, height + toolbarTop - this._window.innerHeight);

      await this._channel.connect('').send('awaitViewportDimensions', { width: width / this._zoom, height: height / this._zoom });
    } else {
      this._linkedBrowser.style.removeProperty('width');
      this._linkedBrowser.style.removeProperty('height');
      this._linkedBrowser.style.removeProperty('box-sizing');
      this._linkedBrowser.closest('.browserStack').style.removeProperty('overflow');
      this._linkedBrowser.closest('.browserStack').style.removeProperty('contain');
      this._linkedBrowser.closest('.browserStack').style.removeProperty('scrollbar-width');
      this._linkedBrowser.browsingContext.inRDMPane = false;

      const actualSize = this._linkedBrowser.getBoundingClientRect();
      await this._channel.connect('').send('awaitViewportDimensions', {
        width: actualSize.width / this._zoom,
        height: actualSize.height / this._zoom,
      });
    }
  }

  setEmulatedMedia(mediumOverride) {
    this.mediumOverride = mediumOverride || '';
    this.updateEmulatedMedia();
  }

  updateEmulatedMedia(browsingContext = undefined) {
    (browsingContext || this._linkedBrowser.browsingContext).mediumOverride = this.mediumOverride;
  }

  setColorScheme(colorScheme) {
    this.colorScheme = fromProtocolColorScheme(colorScheme);
    this.updateColorSchemeOverride();
  }

  updateColorSchemeOverride(browsingContext = undefined) {
    (browsingContext || this._linkedBrowser.browsingContext).prefersColorSchemeOverride = this.colorScheme || this._browserContext.colorScheme || 'none';
  }

  setReducedMotion(reducedMotion) {
    this.reducedMotion = fromProtocolReducedMotion(reducedMotion);
    this.updateReducedMotionOverride();
  }

  updateReducedMotionOverride(browsingContext = undefined) {
    (browsingContext || this._linkedBrowser.browsingContext).prefersReducedMotionOverride = this.reducedMotion || this._browserContext.reducedMotion || 'none';
  }

  setContrast(contrast) {
    this.contrast = fromProtocolContrast(contrast);
    this.updateContrastOverride();
  }

  updateContrastOverride(browsingContext = undefined) {
    (browsingContext || this._linkedBrowser.browsingContext).prefersContrastOverride = this.contrast || this._browserContext.contrast || 'none';
  }

  setForcedColors(forcedColors) {
    this.forcedColors = fromProtocolForcedColors(forcedColors);
    this.updateForcedColorsOverride();
  }

  updateForcedColorsOverride(browsingContext = undefined) {
    const isActive = this.forcedColors === 'active' || this._browserContext.forcedColors === 'active';
    (browsingContext || this._linkedBrowser.browsingContext).forcedColorsOverride = isActive ? 'active' : 'none';
  }

  async setInterceptFileChooserDialog(enabled) {
    this.crossProcessCookie.interceptFileChooserDialog = enabled;
    this._updateCrossProcessCookie();
    await this._channel.connect('').send('setInterceptFileChooserDialog', enabled).catch(e => {});
  }

  async setViewportSize(viewportSize) {
    this._viewportSize = viewportSize;
    await this.updateViewportSize();
  }

  async setZoom(zoom) {
    // This is default range from the ZoomManager.
    if (zoom < 0.3 || zoom > 5)
      throw new Error('Invalid zoom value, must be between 0.3 and 5');
    this._zoom = zoom;
    await this.updateZoom();
  }

  close(runBeforeUnload = false) {
    this._gBrowser.removeTab(this._tab, {
      skipPermitUnload: !runBeforeUnload,
    });
  }

  channel() {
    return this._channel;
  }

  id() {
    return this._targetId;
  }

  info() {
    return {
      targetId: this.id(),
      type: 'page',
      browserContextId: this._browserContext.browserContextId,
      openerId: this._openerId,
    };
  }

  _onNavigated(aLocation) {
    this._url = aLocation.spec;
    this._browserContext.grantPermissionsToOrigin(this._url);
  }

  _updateCrossProcessCookie() {
    Services.ppmm.sharedData.set('juggler:page-cookie-' + this._linkedBrowser.browsingContext.browserId, this.crossProcessCookie);
    Services.ppmm.sharedData.flush();
  }

  async ensurePermissions() {
    await this._channel.connect('').send('ensurePermissions', {}).catch(e => void e);
  }

  async setInitScripts(scripts) {
    this.crossProcessCookie.initScripts = scripts;
    this._updateCrossProcessCookie();
    await this.pushInitScripts();
  }

  async pushInitScripts() {
    await this._channel.connect('').send('setInitScripts', [...this._browserContext.crossProcessCookie.initScripts, ...this.crossProcessCookie.initScripts]).catch(e => void e);
  }

  async addBinding(worldName, name, script) {
    this.crossProcessCookie.bindings.push({ worldName, name, script });
    this._updateCrossProcessCookie();
    await this._channel.connect('').send('addBinding', { worldName, name, script }).catch(e => void e);
  }

  async applyContextSetting(name, value) {
    await this._channel.connect('').send('applyContextSetting', { name, value }).catch(e => void e);
  }

  async hasFailedToOverrideTimezone() {
    return await this._channel.connect('').send('hasFailedToOverrideTimezone').catch(e => true);
  }

  async _startVideoRecording({width, height, dir}) {
    // On Mac the window may not yet be visible when TargetCreated and its
    // NSWindow.windowNumber may be -1, so we wait until the window is known
    // to be initialized and visible.
    await this.windowReady();
    const file = PathUtils.join(dir, helper.generateId() + '.webm');
    if (width < 10 || width > 10000 || height < 10 || height > 10000)
      throw new Error("Invalid size");

    // Firefox 152 renamed `ownerGlobal` to `documentGlobal` on nodes.
    const docShell = (this._gBrowser.documentGlobal || this._gBrowser.ownerGlobal).docShell;
    // Exclude address bar and navigation control from the video.
    const rect = this.linkedBrowser().getBoundingClientRect();
    const devicePixelRatio = this._window.devicePixelRatio;
    let sessionId;
    const registry = this._registry;
    const screencastClient = {
      QueryInterface: ChromeUtils.generateQI([Ci.nsIScreencastServiceClient]),
      screencastFrame(data, deviceWidth, deviceHeight) {
      },
      screencastStopped() {
        registry.emit(TargetRegistry.Events.ScreencastStopped, sessionId);
      },
    };
    const viewport = this._viewportSize || this._browserContext.defaultViewportSize || { width: 0, height: 0 };
    sessionId = screencastService.startVideoRecording(screencastClient, docShell, true, file, width, height, 0, viewport.width, viewport.height, devicePixelRatio * rect.top);
    this._videoRecordingInfo = { sessionId, file };
    this.emit(PageTarget.Events.ScreencastStarted);
  }

  _stopVideoRecording() {
    if (!this._videoRecordingInfo)
      throw new Error('No video recording in progress');
    const videoRecordingInfo = this._videoRecordingInfo;
    this._videoRecordingInfo = undefined;
    screencastService.stopVideoRecording(videoRecordingInfo.sessionId);
  }

  videoRecordingInfo() {
    return this._videoRecordingInfo;
  }

  async startScreencast({ width, height, quality }) {
    // On Mac the window may not yet be visible when TargetCreated and its
    // NSWindow.windowNumber may be -1, so we wait until the window is known
    // to be initialized and visible.
    await this.windowReady();
    if (width < 10 || width > 10000 || height < 10 || height > 10000)
      throw new Error("Invalid size");

    // nsScreencastService only has a working capture source when the browser is
    // headless (HeadlessWindowCapturer). Outside headless it falls through to
    // libwebrtc's X11 window capturer, which does not work here in either
    // configuration:
    //
    //   * without the XComposite extension, startVideoRecording() succeeds and
    //     then never delivers a single frame -- the recording silently comes
    //     out as Playwright's blank filler;
    //   * with XComposite enabled, the browser segfaults during capture;
    //   * on Wayland it cannot start at all, because
    //     nsWindow::GetNativeData(NS_NATIVE_WINDOW_WEBRTC_DEVICE_ID) is
    //     documented as unhandled there and returns null, so the service throws
    //     NS_ERROR_FAILURE ("Failed to get native window id").
    //
    // Capture from the compositor instead. drawSnapshot() is what
    // Page.screenshot already uses, it renders the page content directly, and
    // it is independent of the windowing system -- so headful, Xvfb and Wayland
    // all record identically.
    if (!Services.appinfo.headless)
      return this._startSnapshotScreencast({ width, height, quality });

    // Firefox 152 renamed `ownerGlobal` to `documentGlobal` on nodes.
    const docShell = (this._gBrowser.documentGlobal || this._gBrowser.ownerGlobal).docShell;
    // Exclude address bar and navigation control from the video.
    const rect = this.linkedBrowser().getBoundingClientRect();
    const devicePixelRatio = this._window.devicePixelRatio;

    const self = this;
    const screencastClient = {
      QueryInterface: ChromeUtils.generateQI([Ci.nsIScreencastServiceClient]),
      screencastFrame(data, deviceWidth, deviceHeight) {
        if (self._screencastRecordingInfo)
          self.emit(PageTarget.Events.ScreencastFrame, {
            data,
            deviceWidth,
            deviceHeight,
            // nsIScreencastServiceClient does not hand us the capture time, so
            // stamp it on arrival. The frame was just encoded on the capture
            // thread, so this is within a frame interval of the real swap time
            // -- close enough for the recorder's frame pacing.
            timestamp: Date.now() / 1000,
          });
      },
      screencastStopped() {
      },
    };
    const viewport = this._viewportSize || this._browserContext.defaultViewportSize || { width: 0, height: 0 };
    const screencastId = screencastService.startVideoRecording(screencastClient, docShell, false, '', width, height, quality || 90, viewport.width, viewport.height, devicePixelRatio * rect.top);
    this._screencastRecordingInfo = { screencastId };
    return { screencastId };
  }

  // Compositor-backed screencast, used whenever the native capturer has no
  // usable source (see startScreencast). Frames come from the same
  // drawSnapshot() call Page.screenshot uses, so this works headful, under Xvfb
  // and on Wayland alike.
  _startSnapshotScreencast({ width, height, quality }) {
    const screencastId = Services.uuid.generateUUID().toString().replace(/[{}-]/g, '');
    const jpegQuality = Math.min(Math.max(quality ?? 90, 0), 100) / 100;
    const state = {
      stopped: false,
      // Mirrors nsScreencastService's kMaxFramesInFlight = 1: hold the next
      // capture until the client acks the previous frame, so a slow consumer
      // throttles the capture instead of queueing unbounded JPEGs.
      inFlight: false,
    };
    this._screencastRecordingInfo = { screencastId, snapshotState: state };

    const captureFrame = async () => {
      const browsingContext = this.linkedBrowser()?.browsingContext;
      const windowGlobal = browsingContext?.currentWindowGlobal;
      if (!windowGlobal)
        return;

      const viewport = this._viewportSize || this._browserContext.defaultViewportSize;
      const rect = viewport
        ? new DOMRect(0, 0, viewport.width, viewport.height)
        : this.linkedBrowser().getBoundingClientRect();
      if (!rect.width || !rect.height)
        return;

      // Fit inside the requested frame without distorting; ffmpeg pads the rest.
      const scale = Math.min(width / rect.width, height / rect.height);
      const frameWidth = Math.max(1, Math.round(rect.width * scale));
      const frameHeight = Math.max(1, Math.round(rect.height * scale));

      // drawSnapshot rejects with NS_ERROR_LOSS_OF_SIGNIFICANT_DATA while a
      // navigation is in flight. Drop that frame rather than ending the video.
      let snapshot;
      try {
        snapshot = await windowGlobal.drawSnapshot(
          new DOMRect(0, 0, rect.width, rect.height), scale, 'rgb(255,255,255)');
      } catch (e) {
        return;
      }
      if (state.stopped) {
        snapshot.close();
        return;
      }

      const doc = this._window.document;
      const canvas = doc.createElementNS('http://www.w3.org/1999/xhtml', 'canvas');
      canvas.width = frameWidth;
      canvas.height = frameHeight;
      canvas.getContext('2d').drawImage(snapshot, 0, 0);
      snapshot.close();

      const dataURL = canvas.toDataURL('image/jpeg', jpegQuality);
      state.inFlight = true;
      this.emit(PageTarget.Events.ScreencastFrame, {
        data: dataURL.substring(dataURL.indexOf(',') + 1),
        deviceWidth: frameWidth,
        deviceHeight: frameHeight,
        timestamp: Date.now() / 1000,
      });
    };

    const intervalMs = 1000 / SNAPSHOT_SCREENCAST_FPS;
    const tick = async () => {
      if (state.stopped)
        return;
      if (!state.inFlight) {
        try {
          await captureFrame();
        } catch (e) {
          dump(`juggler: snapshot screencast frame failed: ${e}\n`);
        }
      }
      if (!state.stopped)
        state.timer = setTimeout(tick, intervalMs);
    };
    state.timer = setTimeout(tick, 0);

    return { screencastId };
  }

  screencastFrameAck({ screencastId }) {
    const info = this._screencastRecordingInfo;
    if (!info)
      return;
    // A client that omits the id is acking whatever is currently recording --
    // there can only be one screencast per page target. Only reject an id that
    // is present and refers to some other (stale) session.
    if (screencastId !== undefined && screencastId !== info.screencastId)
      return;
    if (info.snapshotState) {
      info.snapshotState.inFlight = false;
      return;
    }
    screencastService.screencastFrameAck(info.screencastId);
  }

  stopScreencast() {
    const info = this._screencastRecordingInfo;
    if (!info)
      throw new Error('No screencast in progress');
    this._screencastRecordingInfo = undefined;
    if (info.snapshotState) {
      info.snapshotState.stopped = true;
      if (info.snapshotState.timer)
        clearTimeout(info.snapshotState.timer);
      return;
    }
    screencastService.stopVideoRecording(info.screencastId);
  }

  ensureContextMenuClosed() {
    // Close context menu, if any, since it might capture mouse events on Linux
    // and prevent browser shutdown on MacOS.
    const doc = this._linkedBrowser.ownerDocument;
    const contextMenu = doc.getElementById('contentAreaContextMenu');
    if (contextMenu)
      contextMenu.hidePopup();
    const autocompletePopup = doc.getElementById('PopupAutoComplete');
    if (autocompletePopup)
      autocompletePopup.hidePopup();
    const selectPopup = doc.getElementById('ContentSelectDropdown')?.menupopup;
    if (selectPopup)
      selectPopup.hidePopup()
  }

  dispose() {
    this.ensureContextMenuClosed();
    this._disposed = true;
    if (this._videoRecordingInfo)
      this._stopVideoRecording();
    if (this._screencastRecordingInfo)
      this.stopScreencast();
    this._browserContext.pages.delete(this);
    this._registry._browserToTarget.delete(this._linkedBrowser);
    this._registry._browserIdToTarget.delete(this._linkedBrowser.browsingContext.browserId);
    try {
      helper.removeListeners(this._eventListeners);
    } catch (e) {
      // In some cases, removing listeners from this._linkedBrowser fails
      // because it is already half-destroyed.
      if (e)
        dump(e.message + '\n' + e.stack + '\n');
    }
    this._registry.emit(TargetRegistry.Events.TargetDestroyed, this);
  }
}

PageTarget.Events = {
  ScreencastStarted: Symbol('PageTarget.ScreencastStarted'),
  ScreencastFrame: Symbol('PageTarget.ScreencastFrame'),
  Crashed: Symbol('PageTarget.Crashed'),
  DialogOpened: Symbol('PageTarget.DialogOpened'),
  DialogClosed: Symbol('PageTarget.DialogClosed'),
};

function fromProtocolColorScheme(colorScheme) {
  if (colorScheme === 'light' || colorScheme === 'dark')
    return colorScheme;
  if (colorScheme === null || colorScheme === 'no-preference')
    return undefined;
  throw new Error('Unknown color scheme: ' + colorScheme);
}

function fromProtocolReducedMotion(reducedMotion) {
  if (reducedMotion === 'reduce' || reducedMotion === 'no-preference')
    return reducedMotion;
  if (reducedMotion === null)
    return undefined;
  throw new Error('Unknown reduced motion: ' + reducedMotion);
}

function fromProtocolContrast(contrast) {
  if (contrast === 'more' || contrast === 'less' || contrast === 'custom' || contrast === 'no-preference')
    return contrast;
  if (contrast === null)
    return undefined;
  throw new Error('Unknown contrast: ' + contrast);
}

function fromProtocolForcedColors(forcedColors) {
  if (forcedColors === 'active' || forcedColors === 'none')
    return forcedColors;
  if (!forcedColors)
    return 'none';
  throw new Error('Unknown forced colors: ' + forcedColors);
}

class BrowserContext {
  constructor(registry, browserContextId, removeOnDetach) {
    this._registry = registry;
    this.browserContextId = browserContextId;
    // Default context has userContextId === 0, but we pass undefined to many APIs just in case.
    this.userContextId = 0;
    if (browserContextId !== undefined) {
      const identity = ContextualIdentityService.create(IDENTITY_NAME + browserContextId);
      this.userContextId = identity.userContextId;
    }
    this._principals = [];
    // Maps origins to the permission lists.
    this._permissions = new Map();
    this._registry._browserContextIdToBrowserContext.set(this.browserContextId, this);
    this._registry._userContextIdToBrowserContext.set(this.userContextId, this);
    this._proxy = null;
    this.removeOnDetach = removeOnDetach;
    this.extraHTTPHeaders = undefined;
    this.httpCredentials = undefined;
    this.requestInterceptionEnabled = undefined;
    this.ignoreHTTPSErrors = undefined;
    this.downloadOptions = undefined;
    this.defaultViewportSize = undefined;
    this.deviceScaleFactor = undefined;
    this.defaultUserAgent = null;
    this.defaultPlatform = null;
    this.touchOverride = false;
    this.forceOffline = false;
    this.disableCache = false;
    this.colorScheme = 'none';
    this.forcedColors = 'none';
    this.reducedMotion = 'none';
    this.contrast = 'none';
    this.videoRecordingOptions = undefined;
    this.crossProcessCookie = {
      initScripts: [],
      bindings: [],
      settings: {},
    };
    this.pages = new Set();
  }

  _updateCrossProcessCookie() {
    Services.ppmm.sharedData.set('juggler:context-cookie-' + this.userContextId, this.crossProcessCookie);
    Services.ppmm.sharedData.flush();
  }

  setColorScheme(colorScheme) {
    this.colorScheme = fromProtocolColorScheme(colorScheme);
    for (const page of this.pages)
      page.updateColorSchemeOverride();
  }

  setReducedMotion(reducedMotion) {
    this.reducedMotion = fromProtocolReducedMotion(reducedMotion);
    for (const page of this.pages)
      page.updateReducedMotionOverride();
  }

  setContrast(contrast) {
    this.contrast = fromProtocolContrast(contrast);
    for (const page of this.pages)
      page.updateContrastOverride();
  }

  setForcedColors(forcedColors) {
    this.forcedColors = fromProtocolForcedColors(forcedColors);
    for (const page of this.pages)
      page.updateForcedColorsOverride();
  }

  async destroy() {
    if (this.userContextId !== 0) {
      ContextualIdentityService.remove(this.userContextId);
      for (const page of this.pages)
        page.close();
      if (this.pages.size) {
        await new Promise(f => {
          const listener = helper.on(this._registry, TargetRegistry.Events.TargetDestroyed, () => {
            if (!this.pages.size) {
              helper.removeListeners([listener]);
              f();
            }
          });
        });
      }
    }
    this._registry._browserContextIdToBrowserContext.delete(this.browserContextId);
    this._registry._userContextIdToBrowserContext.delete(this.userContextId);
    this._registry._updateProxiesWithSameAuthCacheAndDifferentCredentials();
  }

  setProxy(proxy) {
    // Clear AuthCache.
    Services.obs.notifyObservers(null, "net:clear-active-logins");
    this._proxy = proxy;
    this._registry._updateProxiesWithSameAuthCacheAndDifferentCredentials();
  }

  setIgnoreHTTPSErrors(ignoreHTTPSErrors) {
    if (this.ignoreHTTPSErrors === ignoreHTTPSErrors)
      return;
    this.ignoreHTTPSErrors = ignoreHTTPSErrors;
    const certOverrideService = Cc[
      "@mozilla.org/security/certoverride;1"
    ].getService(Ci.nsICertOverrideService);
    if (ignoreHTTPSErrors) {
      Preferences.set("network.stricttransportsecurity.preloadlist", false);
      Preferences.set("security.cert_pinning.enforcement_level", 0);
      certOverrideService.setDisableAllSecurityChecksAndLetAttackersInterceptMyDataForUserContext(this.userContextId, true);
    } else {
      certOverrideService.setDisableAllSecurityChecksAndLetAttackersInterceptMyDataForUserContext(this.userContextId, false);
    }
  }

  setDefaultUserAgent(userAgent) {
    this.defaultUserAgent = userAgent;
    for (const page of this.pages)
      page.updateUserAgent();
  }

  setDefaultPlatform(platform) {
    this.defaultPlatform = platform;
    for (const page of this.pages)
      page.updatePlatform();
  }

  setTouchOverride(touchOverride) {
    this.touchOverride = touchOverride;
    for (const page of this.pages)
      page.updateTouchOverride();
  }

  setForceOffline(forceOffline) {
    this.forceOffline = forceOffline;
    for (const page of this.pages)
      page.updateForceOffline();
  }

  setCacheDisabled(disabled) {
    this.disableCache = disabled;
    for (const page of this.pages)
      page.updateCacheDisabled();
  }

  async setDefaultViewport(viewport) {
    this.defaultViewportSize = viewport ? viewport.viewportSize : undefined;
    this.deviceScaleFactor = viewport ? viewport.deviceScaleFactor : undefined;
    await Promise.all(Array.from(this.pages).map(page => page.updateViewportSize()));
  }

  async setInitScripts(scripts) {
    this.crossProcessCookie.initScripts = scripts;
    this._updateCrossProcessCookie();
    await Promise.all(Array.from(this.pages).map(page => page.pushInitScripts()));
  }

  async addBinding(worldName, name, script) {
    this.crossProcessCookie.bindings.push({ worldName, name, script });
    this._updateCrossProcessCookie();
    await Promise.all(Array.from(this.pages).map(page => page.addBinding(worldName, name, script)));
  }

  async applySetting(name, value) {
    this.crossProcessCookie.settings[name] = value;
    this._updateCrossProcessCookie();
    await Promise.all(Array.from(this.pages).map(page => page.applyContextSetting(name, value)));
  }

  async grantPermissions(origin, permissions) {
    this._permissions.set(origin, permissions);
    const promises = [];
    for (const page of this.pages) {
      if (origin === '*' || page._url.startsWith(origin)) {
        this.grantPermissionsToOrigin(page._url);
        promises.push(page.ensurePermissions());
      }
    }
    await Promise.all(promises);
  }

  resetPermissions() {
    for (const principal of this._principals) {
      for (const permission of ALL_PERMISSIONS)
        Services.perms.removeFromPrincipal(principal, permission);
    }
    this._principals = [];
    this._permissions.clear();
  }

  grantPermissionsToOrigin(url) {
    let origin = Array.from(this._permissions.keys()).find(key => url.startsWith(key));
    if (!origin)
      origin = '*';

    const permissions = this._permissions.get(origin);
    if (!permissions)
      return;

    const attrs = { userContextId: this.userContextId || undefined };
    const principal = Services.scriptSecurityManager.createContentPrincipal(NetUtil.newURI(url), attrs);
    this._principals.push(principal);
    for (const permission of ALL_PERMISSIONS) {
      const action = permissions.includes(permission) ? Ci.nsIPermissionManager.ALLOW_ACTION : Ci.nsIPermissionManager.DENY_ACTION;
      Services.perms.addFromPrincipal(principal, permission, action, Ci.nsIPermissionManager.EXPIRE_NEVER, 0 /* expireTime */);
    }
  }

  setCookies(cookies) {
    const protocolToSameSite = {
      [undefined]: Ci.nsICookie.SAMESITE_UNSET,
      'None': Ci.nsICookie.SAMESITE_UNSET,
      'Lax': Ci.nsICookie.SAMESITE_LAX,
      'Strict': Ci.nsICookie.SAMESITE_STRICT,
    };
    for (const cookie of cookies) {
      const uri = cookie.url ? NetUtil.newURI(cookie.url) : null;
      let domain = cookie.domain;
      if (!domain) {
        if (!uri)
          throw new Error('At least one of the url and domain needs to be specified');
        domain = uri.host;
      }
      let path = cookie.path;
      if (!path)
        path = uri ? dirPath(uri.filePath) : '/';
      let secure = false;
      if (cookie.secure !== undefined)
        secure = cookie.secure;
      else if (uri && uri.scheme === 'https')
        secure = true;
      Services.cookies.add(
        domain,
        path,
        cookie.name,
        cookie.value,
        secure,
        cookie.httpOnly || false,
        cookie.expires === undefined || cookie.expires === -1 /* isSession */,
        cookie.expires === undefined ? Date.now() + HUNDRED_YEARS : cookie.expires * 1000,
        { userContextId: this.userContextId || undefined } /* originAttributes */,
        protocolToSameSite[cookie.sameSite],
        Ci.nsICookie.SCHEME_UNSET
      );
    }
  }

  clearCookies() {
    Services.cookies.removeCookiesWithOriginAttributes(JSON.stringify({ userContextId: this.userContextId || undefined }));
  }

  getCookies() {
    const result = [];
    const sameSiteToProtocol = {
      [Ci.nsICookie.SAMESITE_UNSET]: 'None',
      [Ci.nsICookie.SAMESITE_NONE]: 'None',
      [Ci.nsICookie.SAMESITE_LAX]: 'Lax',
      [Ci.nsICookie.SAMESITE_STRICT]: 'Strict',
    };
    for (let cookie of Services.cookies.cookies) {
      if (cookie.originAttributes.userContextId !== this.userContextId)
        continue;
      if (cookie.host === 'addons.mozilla.org')
        continue;
      result.push({
        name: cookie.name,
        value: cookie.value,
        domain: cookie.host,
        path: cookie.path,
        expires: cookie.isSession ? -1 : cookie.expiry / 1000,
        size: cookie.name.length + cookie.value.length,
        httpOnly: cookie.isHttpOnly,
        secure: cookie.isSecure,
        session: cookie.isSession,
        sameSite: sameSiteToProtocol[cookie.sameSite],
      });
    }
    return result;
  }

  async setVideoRecordingOptions(options) {
    this.videoRecordingOptions = options;
    const promises = [];
    for (const page of this.pages) {
      if (options)
        promises.push(page._startVideoRecording(options));
      else if (page._videoRecordingInfo)
        promises.push(page._stopVideoRecording());
    }
    await Promise.all(promises);
  }
}

class Dialog {
  static createIfSupported(prompt) {
    const type = prompt.args.promptType;
    switch (type) {
      case 'alert':
      case 'alertCheck':
        return new Dialog(prompt, 'alert');
      case 'prompt':
        return new Dialog(prompt, 'prompt');
      case 'confirm':
      case 'confirmCheck':
        return new Dialog(prompt, 'confirm');
      case 'confirmEx':
        return new Dialog(prompt, 'beforeunload');
      default:
        return null;
    };
  }

  constructor(prompt, type) {
    this._id = helper.generateId();
    this._type = type;
    this._prompt = prompt;
  }

  id() {
    return this._id;
  }

  message() {
    return this._prompt.ui.infoBody.textContent;
  }

  type() {
    return this._type;
  }

  prompt() {
    return this._prompt;
  }

  dismiss() {
    if (this._prompt.ui.button1)
      this._prompt.ui.button1.click();
    else
      this._prompt.ui.button0.click();
  }

  defaultValue() {
    return this._prompt.ui.loginTextbox.value;
  }

  accept(promptValue) {
    if (typeof promptValue === 'string' && this._type === 'prompt')
      this._prompt.ui.loginTextbox.value = promptValue;
    this._prompt.ui.button0.click();
  }
}


function dirPath(path) {
  return path.substring(0, path.lastIndexOf('/') + 1);
}

async function waitForWindowReady(window) {
  if (window.delayedStartupPromise) {
    await window.delayedStartupPromise;
  } else {
    await new Promise((resolve => {
      Services.obs.addObserver(function observer(aSubject, aTopic) {
        if (window == aSubject) {
          Services.obs.removeObserver(observer, aTopic);
          resolve();
        }
      }, "browser-delayed-startup-finished");
    }));
  }
  if (window.document.readyState !== 'complete')
    await helper.awaitEvent(window, 'load');
}

TargetRegistry.Events = {
  TargetCreated: Symbol('TargetRegistry.Events.TargetCreated'),
  TargetDestroyed: Symbol('TargetRegistry.Events.TargetDestroyed'),
  DownloadCreated: Symbol('TargetRegistry.Events.DownloadCreated'),
  DownloadFinished: Symbol('TargetRegistry.Events.DownloadFinished'),
  ScreencastStopped: Symbol('TargetRegistry.ScreencastStopped'),
};
