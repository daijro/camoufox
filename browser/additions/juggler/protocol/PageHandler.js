/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

const {Helper, EventWatcher} = ChromeUtils.importESModule('resource://gre/modules/juggler/Helper.js');
const {NetUtil} = ChromeUtils.importESModule('resource://gre/modules/NetUtil.sys.mjs');
const {NetworkObserver, PageNetwork} = ChromeUtils.importESModule('resource://gre/modules/juggler/NetworkObserver.js');
const {PageTarget} = ChromeUtils.importESModule('resource://gre/modules/juggler/TargetRegistry.js');
const {setTimeout} = ChromeUtils.importESModule('resource://gre/modules/Timer.sys.mjs');
const {MouseDispatch, kAckDeadlineMs} = ChromeUtils.importESModule('resource://gre/modules/juggler/input/MouseDispatch.js');
const kMoveIntervalMs = 8; // a 125 Hz mouse
const {logNormalDelay} = ChromeUtils.importESModule('resource://gre/modules/juggler/input/HumanDelay.js');
const {cursory, humanizedMove} = ChromeUtils.importESModule('resource://gre/modules/juggler/input/CursorTrajectory.js');
const {play} = ChromeUtils.importESModule('resource://gre/modules/juggler/input/Pacer.js');

const Cc = Components.classes;
const Ci = Components.interfaces;
const Cu = Components.utils;
const XUL_NS = 'http://www.mozilla.org/keymaster/gatekeeper/there.is.only.xul';
const helper = new Helper();

// How long a person holds a mouse button for a click. Human press durations
// are right-skewed (arXiv 2607.26935 centres them on 100-120 ms), so this is a
// log-normal with a 95 ms median, sigma 0.42, never under 50 ms.
const clickHold = () => logNormalDelay(95, 0.42, 50);

// How long a person's button stays up between the clicks of a double click:
// 110 ms median, sigma 0.32, kept within 70-180 ms, so press to press stays
// well inside the OS double-click time with clickHold() before it.
const clickGap = () => logNormalDelay(110, 0.32, 70, 180);

// How long a person's pointer rests on a target before pressing it: 125 ms
// median, sigma 0.5, kept within 60-240 ms. Stock's OS input reads under
// 250 ms from arrival to press; Playwright pressed under 10 ms after the move.
const hoverDwell = () => logNormalDelay(125, 0.5, 60, 240);

function hashConsoleMessage(params) {
  return params.location.lineNumber + ':' + params.location.columnNumber + ':' + params.location.url;
}

class WorkerHandler {
  constructor(session, contentChannel, workerId) {
    this._session = session;
    this._contentWorker = contentChannel.connect(workerId);
    this._workerConsoleMessages = new Set();
    this._workerId = workerId;

    const emitWrappedProtocolEvent = eventName => {
      return params => {
        this._session.emitEvent('Page.dispatchMessageFromWorker', {
          workerId,
          message: JSON.stringify({method: eventName, params}),
        });
      }
    }

    this._eventListeners = [
      contentChannel.register(workerId, {
        runtimeConsole: (params) => {
          this._workerConsoleMessages.add(hashConsoleMessage(params));
          emitWrappedProtocolEvent('Runtime.console')(params);
        },
        runtimeExecutionContextCreated: emitWrappedProtocolEvent('Runtime.executionContextCreated'),
        runtimeExecutionContextDestroyed: emitWrappedProtocolEvent('Runtime.executionContextDestroyed'),
      }),
    ];
  }

  async sendMessage(message) {
    const [domain, method] = message.method.split('.');
    if (domain !== 'Runtime')
      throw new Error('ERROR: can only dispatch to Runtime domain inside worker');
    const result = await this._contentWorker.send(method, message.params);
    this._session.emitEvent('Page.dispatchMessageFromWorker', {
      workerId: this._workerId,
      message: JSON.stringify({result, id: message.id}),
    });
  }

  dispose() {
    this._contentWorker.dispose();
    helper.removeListeners(this._eventListeners);
  }
}

export class PageHandler {
  constructor(target, session, contentChannel) {
    this._session = session;
    this._contentChannel = contentChannel;
    this._contentPage = contentChannel.connect('page');
    this._workers = new Map();

    this._pageTarget = target;
    this._pageNetwork = PageNetwork.forPageTarget(target);

    const emitProtocolEvent = eventName => {
      return (...args) => this._session.emitEvent(eventName, ...args);
    }

    this._isDragging = false;
    this._dragWatcher = null;
    // GTK: how many moves the current drag session has had, and whether it has
    // taken the pointer from the window yet (_dragMotion).
    this._dragMoves = 0;
    this._dragHasPointer = false;
    this._lastMousePosition = { x: 0, y: 0 };
    // Camoufox: last position an actual mousemove landed on. Used as the
    // start point for the humanized cursor trajectory (humanize=True).
    this._lastTrackedPos = { x: 0, y: 0 };
    // Camoufox: documents whose content process accepts user input (see
    // _awaitUserInputGate), keyed by WindowGlobalParent.
    this._userInputGateOpen = new WeakSet();

    this._reportedFrameIds = new Set();
    this._networkEventsForUnreportedFrameIds = new Map();

    // `Page.ready` protocol event is emitted whenever page has completed initialization, e.g.
    // finished all the transient navigations to the `about:blank`.
    //
    // We'd like to avoid reporting meaningful events before the `Page.ready` since they are likely
    // to be ignored by the protocol clients.
    this._isPageReady = false;

    if (this._pageTarget.videoRecordingInfo())
      this._onVideoRecordingStarted();

    this._pageEventSink = {};
    helper.decorateAsEventEmitter(this._pageEventSink);

    this._pendingEventWatchers = new Set();
    this._moveDelivery = null;
    // Arrival order of mouse commands (beforeDispatch).
    this._mouseTurn = Promise.resolve();
    this._mouseDispatched = Promise.resolve();
    this._mouseTurns = new Map();
    this._lastMoveAt = 0;
    this._humanizeAbort = new AbortController();
    this._eventListeners = [
      helper.on(this._pageTarget, PageTarget.Events.DialogOpened, this._onDialogOpened.bind(this)),
      helper.on(this._pageTarget, PageTarget.Events.DialogClosed, this._onDialogClosed.bind(this)),
      helper.on(this._pageTarget, PageTarget.Events.Crashed, () => {
        this._session.emitEvent('Page.crashed', {});
      }),
      helper.on(this._pageTarget, PageTarget.Events.ScreencastStarted, this._onVideoRecordingStarted.bind(this)),
      helper.on(this._pageTarget, PageTarget.Events.ScreencastFrame, this._onScreencastFrame.bind(this)),
      helper.on(this._pageNetwork, PageNetwork.Events.Request, this._handleNetworkEvent.bind(this, 'Network.requestWillBeSent')),
      helper.on(this._pageNetwork, PageNetwork.Events.Response, this._handleNetworkEvent.bind(this, 'Network.responseReceived')),
      helper.on(this._pageNetwork, PageNetwork.Events.RequestFinished, this._handleNetworkEvent.bind(this, 'Network.requestFinished')),
      helper.on(this._pageNetwork, PageNetwork.Events.RequestFailed, this._handleNetworkEvent.bind(this, 'Network.requestFailed')),
      contentChannel.register('page', {
        pageBindingCalled: emitProtocolEvent('Page.bindingCalled'),
        pageDispatchMessageFromWorker: emitProtocolEvent('Page.dispatchMessageFromWorker'),
        pageEventFired: emitProtocolEvent('Page.eventFired'),
        pageFileChooserOpened: emitProtocolEvent('Page.fileChooserOpened'),
        pageFrameAttached: this._onFrameAttached.bind(this),
        pageFrameDetached: emitProtocolEvent('Page.frameDetached'),
        pageLinkClicked: emitProtocolEvent('Page.linkClicked'),
        pageWillOpenNewWindowAsynchronously: emitProtocolEvent('Page.willOpenNewWindowAsynchronously'),
        pageNavigationAborted: emitProtocolEvent('Page.navigationAborted'),
        pageNavigationCommitted: emitProtocolEvent('Page.navigationCommitted'),
        pageNavigationStarted: emitProtocolEvent('Page.navigationStarted'),
        pageReady: this._onPageReady.bind(this),
        pageInputEvent: (event) => this._pageEventSink.emit(event.type, event),
        pageSameDocumentNavigation: emitProtocolEvent('Page.sameDocumentNavigation'),
        pageUncaughtError: emitProtocolEvent('Page.uncaughtError'),
        pageWorkerCreated: this._onWorkerCreated.bind(this),
        pageWorkerDestroyed: this._onWorkerDestroyed.bind(this),
        runtimeConsole: params => {
          const consoleMessageHash = hashConsoleMessage(params);
          for (const worker of this._workers.values()) {
            if (worker._workerConsoleMessages.has(consoleMessageHash)) {
              worker._workerConsoleMessages.delete(consoleMessageHash);
              return;
            }
          }
          this._session.emitEvent('Runtime.console', params);
        },
        runtimeExecutionContextCreated: emitProtocolEvent('Runtime.executionContextCreated'),
        runtimeExecutionContextDestroyed: emitProtocolEvent('Runtime.executionContextDestroyed'),
        runtimeExecutionContextsCleared: emitProtocolEvent('Runtime.executionContextsCleared'),

        webSocketCreated: emitProtocolEvent('Page.webSocketCreated'),
        webSocketOpened: emitProtocolEvent('Page.webSocketOpened'),
        webSocketClosed: emitProtocolEvent('Page.webSocketClosed'),
        webSocketFrameReceived: emitProtocolEvent('Page.webSocketFrameReceived'),
        webSocketFrameSent: emitProtocolEvent('Page.webSocketFrameSent'),
      }),
    ];
  }

  async dispose() {
    // Stop any humanized plan still playing; nothing more dispatches to a page
    // that is going away.
    this._humanizeAbort.abort();
    this._contentPage.dispose();
    for (const watcher of this._pendingEventWatchers)
      watcher.dispose();
    helper.removeListeners(this._eventListeners);
  }

  _onVideoRecordingStarted() {
    const info = this._pageTarget.videoRecordingInfo();
    this._session.emitEvent('Page.videoRecordingStarted', { screencastId: info.sessionId, file: info.file });
  }

  _onScreencastFrame(params) {
    this._session.emitEvent('Page.screencastFrame', params);
  }

  _onPageReady(event) {
    this._isPageReady = true;
    this._session.emitEvent('Page.ready');
    for (const dialog of this._pageTarget.dialogs())
      this._onDialogOpened(dialog);
  }

  _onDialogOpened(dialog) {
    if (!this._isPageReady)
      return;
    this._session.emitEvent('Page.dialogOpened', {
      dialogId: dialog.id(),
      type: dialog.type(),
      message: dialog.message(),
      defaultValue: dialog.defaultValue(),
    });
  }

  _onDialogClosed(dialog) {
    if (!this._isPageReady)
      return;
    this._session.emitEvent('Page.dialogClosed', { dialogId: dialog.id(), });
  }

  _onWorkerCreated({workerId, frameId, url}) {
    const worker = new WorkerHandler(this._session, this._contentChannel, workerId);
    this._workers.set(workerId, worker);
    this._session.emitEvent('Page.workerCreated', {workerId, frameId, url});
  }

  _onWorkerDestroyed({workerId}) {
    const worker = this._workers.get(workerId);
    if (!worker)
      return;
    this._workers.delete(workerId);
    worker.dispose();
    this._session.emitEvent('Page.workerDestroyed', {workerId});
  }

  _handleNetworkEvent(protocolEventName, eventDetails, frameId) {
    if (!this._reportedFrameIds.has(frameId)) {
      let events = this._networkEventsForUnreportedFrameIds.get(frameId);
      if (!events) {
        events = [];
        this._networkEventsForUnreportedFrameIds.set(frameId, events);
      }
      events.push({eventName: protocolEventName, eventDetails});
    } else {
      this._session.emitEvent(protocolEventName, eventDetails);
    }
  }

  _onFrameAttached({frameId, parentFrameId}) {
    this._session.emitEvent('Page.frameAttached', {frameId, parentFrameId});
    this._reportedFrameIds.add(frameId);
    const events = this._networkEventsForUnreportedFrameIds.get(frameId) || [];
    this._networkEventsForUnreportedFrameIds.delete(frameId);
    for (const {eventName, eventDetails} of events)
      this._session.emitEvent(eventName, eventDetails);
  }

  async ['Page.close']({runBeforeUnload}) {
    // Postpone target close to deliver response in session.
    Services.tm.dispatchToMainThread(() => {
      this._pageTarget.close(runBeforeUnload);
    });
  }

  async ['Page.setViewportSize']({viewportSize}) {
    await this._pageTarget.setViewportSize(viewportSize === null ? undefined : viewportSize);
  }

  async ['Page.setZoom']({zoom}) {
    await this._pageTarget.setZoom(zoom);
  }

  async ['Runtime.evaluate'](options) {
    return await this._contentPage.send('evaluate', options);
  }

  async ['Runtime.callFunction'](options) {
    return await this._contentPage.send('callFunction', options);
  }

  async ['Runtime.getObjectProperties'](options) {
    return await this._contentPage.send('getObjectProperties', options);
  }

  async ['Runtime.disposeObject'](options) {
    return await this._contentPage.send('disposeObject', options);
  }

  async ['Heap.collectGarbage']() {
    Services.obs.notifyObservers(null, "child-gc-request");
    Cu.forceGC();
    Services.obs.notifyObservers(null, "child-cc-request");
    Cu.forceCC();
  }

  async ['Network.getResponseBody']({requestId}) {
    return this._pageNetwork.getResponseBody(requestId);
  }

  async ['Network.setExtraHTTPHeaders']({headers}) {
    this._pageNetwork.setExtraHTTPHeaders(headers);
  }

  async ['Network.setRequestInterception']({enabled}) {
    if (enabled)
      this._pageNetwork.enableRequestInterception();
    else
      this._pageNetwork.disableRequestInterception();
  }

  async ['Network.resumeInterceptedRequest']({requestId, url, method, headers, postData}) {
    this._pageNetwork.resumeInterceptedRequest(requestId, url, method, headers, postData);
  }

  async ['Network.abortInterceptedRequest']({requestId, errorCode}) {
    this._pageNetwork.abortInterceptedRequest(requestId, errorCode);
  }

  async ['Network.fulfillInterceptedRequest']({requestId, status, statusText, headers, base64body}) {
    this._pageNetwork.fulfillInterceptedRequest(requestId, status, statusText, headers, base64body);
  }

  async ['Accessibility.getFullAXTree'](params) {
    return await this._contentPage.send('getFullAXTree', params);
  }

  async ['Page.setFileInputFiles'](options) {
    return await this._contentPage.send('setFileInputFiles', options);
  }

  async ['Page.setEmulatedMedia']({colorScheme, type, reducedMotion, forcedColors, contrast}) {
    this._pageTarget.setColorScheme(colorScheme || null);
    this._pageTarget.setReducedMotion(reducedMotion || null);
    this._pageTarget.setForcedColors(forcedColors || null);
    this._pageTarget.setContrast(contrast || null);
    this._pageTarget.setEmulatedMedia(type);
  }

  async ['Page.bringToFront'](options) {
    // Camoufox: and the page takes the focus, as when a user clicks into it.
    // Raising the window alone left focus on nothing once another window had
    // been open, and the page never learnt it was the active tab again.
    // Waits (bounded) for the window manager to activate the window, so the
    // page reads as focused once the call returns, as it does for a user.
    await this._pageTarget.activateAndRun(() => this._focusFrontPage());
  }

  async ['Page.setCacheDisabled']({cacheDisabled}) {
    return await this._pageTarget.setCacheDisabled(cacheDisabled);
  }

  async ['Page.addBinding']({ worldName, name, script }) {
    return await this._pageTarget.addBinding(worldName, name, script);
  }

  async ['Page.adoptNode'](options) {
    return await this._contentPage.send('adoptNode', options);
  }

  async ['Page.screenshot']({ mimeType, clip, omitDeviceScaleFactor, quality }) {
    const rect = new DOMRect(clip.x, clip.y, clip.width, clip.height);

    const browsingContext = this._pageTarget.linkedBrowser().browsingContext;
    // `win.devicePixelRatio` returns a non-overriden value to priveleged code.
    // See https://bugzilla.mozilla.org/show_bug.cgi?id=1761032
    // See https://phabricator.services.mozilla.com/D141323
    const devicePixelRatio = browsingContext.overrideDPPX || this._pageTarget._window.devicePixelRatio;
    const scale = omitDeviceScaleFactor ? 1 : devicePixelRatio;
    const canvasWidth = rect.width * scale;
    const canvasHeight = rect.height * scale;

    const MAX_CANVAS_DIMENSIONS = 32767;
    const MAX_CANVAS_AREA = 472907776;
    if (canvasWidth > MAX_CANVAS_DIMENSIONS || canvasHeight > MAX_CANVAS_DIMENSIONS)
      throw new Error('Cannot take screenshot larger than ' + MAX_CANVAS_DIMENSIONS);
    if (canvasWidth * canvasHeight > MAX_CANVAS_AREA)
      throw new Error('Cannot take screenshot with more than ' + MAX_CANVAS_AREA + ' pixels');

    let snapshot;
    while (!snapshot) {
      try {
        //TODO(fission): browsingContext will change in case of cross-group navigation.
        snapshot = await browsingContext.currentWindowGlobal.drawSnapshot(
          rect,
          scale,
          "rgb(255,255,255)"
        );
      } catch (e) {
        // The currentWindowGlobal.drawSnapshot might throw
        // NS_ERROR_LOSS_OF_SIGNIFICANT_DATA if called during navigation.
        // wait a little and re-try.
        await new Promise(x => setTimeout(x, 50));
      }
    }

    // Firefox 152 removed `ownerGlobal`; `topChromeWindow` is already the chrome window.
    const win = browsingContext.topChromeWindow;
    const canvas = win.document.createElementNS('http://www.w3.org/1999/xhtml', 'canvas');
    canvas.width = canvasWidth;
    canvas.height = canvasHeight;
    try {
      let ctx = canvas.getContext('2d');
      ctx.drawImage(snapshot, 0, 0);

      if (mimeType === 'image/jpeg' || mimeType === 'image/webp') {
        quality ??= mimeType === 'image/webp' ? 100 : 80;
        if (quality < 0 || quality > 100)
          throw new Error('Quality must be an integer value between 0 and 100; received ' + quality);
        quality /= 100;
      } else {
        quality = undefined;
      }
      const dataURL = canvas.toDataURL(mimeType, quality);
      return { data: dataURL.substring(dataURL.indexOf(',') + 1) };
    } finally {
      // The canvas is garbage until a GC, and on Windows its backing store stayed
      // committed until the browser closed (#959). A zero size frees it now.
      snapshot.close();
      canvas.width = canvas.height = 0;
    }
  }

  async ['Page.getContentQuads'](options) {
    return await this._contentPage.send('getContentQuads', options);
  }

  async ['Page.navigate']({frameId, url, referer}) {
    const browsingContext = this._pageTarget.frameIdToBrowsingContext(frameId);
    let sameDocumentNavigation = false;
    try {
      const uri = NetUtil.newURI(url);
      // This is the same check that verifes browser-side if this is the same-document navigation.
      // See CanonicalBrowsingContext::SupportsLoadingInParent.
      sameDocumentNavigation = browsingContext.currentURI && uri.hasRef && uri.equalsExceptRef(browsingContext.currentURI);
    } catch (e) {
      throw new Error(`Invalid url: "${url}"`);
    }
    let referrerURI = null;
    let referrerInfo = null;
    if (referer) {
      try {
        referrerURI = NetUtil.newURI(referer);
        const ReferrerInfo = Components.Constructor(
          '@mozilla.org/referrer-info;1',
          'nsIReferrerInfo',
          'init'
        );
        referrerInfo = new ReferrerInfo(Ci.nsIReferrerInfo.UNSAFE_URL, true, referrerURI);
      } catch (e) {
        throw new Error(`Invalid referer: "${referer}"`);
      }
    }

    let navigationId;
    const unsubscribe = helper.addObserver((browsingContext, topic, loadIdentifier) => {
      navigationId = helper.toProtocolNavigationId(loadIdentifier);
    }, 'juggler-navigation-started-browser');
    const navigationURI = Services.io.newURI(url);
    // Camoufox: a top-level load starts its connection before the content
    // process asks, as stock's own loads do (RemoteWebNavigation's
    // _speculativeConnect). Without it the page's navigation timing showed a
    // fresh lookup and connect after fetchStart, where a typed or clicked load
    // in stock has them before it.
    if (!browsingContext.parent && (navigationURI.schemeIs('http') || navigationURI.schemeIs('https'))) {
      try {
        const principal = Services.scriptSecurityManager.createContentPrincipal(
            navigationURI, browsingContext.originAttributes);
        // The callbacks give the connection the tab's load context, as stock's do.
        const callbacks = {
          QueryInterface: ChromeUtils.generateQI(['nsIInterfaceRequestor']),
          getInterface(iid) {
            if (iid.equals(Ci.nsILoadContext))
              return browsingContext;
            throw Components.Exception('', Cr.NS_ERROR_NO_INTERFACE);
          },
        };
        Services.io.speculativeConnect(navigationURI, principal, callbacks, false);
      } catch (e) {
        // As in stock: a URI that cannot be pre-connected just loads.
      }
    }
    browsingContext.loadURI(navigationURI, {
      triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
      loadFlags: Ci.nsIWebNavigation.LOAD_FLAGS_IS_LINK,
      referrerInfo,
      // postData: null,
      // headers: null,
      // Fake user activation.
      hasValidUserGestureActivation: true,
    });
    unsubscribe();
    // Camoufox: a URL loaded from the address bar hands focus to the page
    // (UrlbarParentController.focusBrowser). Without it a window that opened on
    // about:blank keeps focus in its chrome, and once the load moves the tab to
    // a content process that process never learns it is the active tab:
    // requestPointerLock() rejected "The document is not focused." where stock
    // reaches its gesture check.
    const linkedBrowser = this._pageTarget.linkedBrowser();
    if (!browsingContext.parent && linkedBrowser === linkedBrowser.ownerDocument?.defaultView?.gBrowser?.selectedBrowser)
      linkedBrowser.focus();

    return {
      navigationId: sameDocumentNavigation ? null : navigationId,
    };
  }

  async ['Page.goBack']({}) {
    const browsingContext = this._pageTarget.linkedBrowser().browsingContext;
    // Camoufox: canGoBack is the BACK BUTTON's answer -- with
    // browser.navigation.requireUserInteraction (Firefox's default) it reports
    // false when every entry behind this one was pushed without the user
    // touching the page, because the button skips those. goBack() itself does
    // not skip them, and neither does history.back(). Ask the question the
    // traversal actually answers, as Marionette does (driver.sys.mjs).
    const embedder = browsingContext.embedderElement;
    const canGoBack = embedder?.canGoBackIgnoringUserInteraction ?? embedder?.canGoBack;
    if (!canGoBack)
      return { success: false };
    browsingContext.goBack();
    return { success: true };
  }

  async ['Page.goForward']({}) {
    const browsingContext = this._pageTarget.linkedBrowser().browsingContext;
    if (!browsingContext.embedderElement?.canGoForward)
      return { success: false };
    browsingContext.goForward();
    return { success: true };
  }

  async ['Page.reload']() {
    await this._pageTarget.activateAndRun(() => {
      const browser = this._pageTarget._tab.linkedBrowser;
      // Camoufox: Firefox 146's Browser:Reload command is a no-op on about:blank
      // (no history entry to reload). Fall back to a forced reloadWithFlags via
      // browsingContext so the load event still fires and init scripts run.
      try {
        const uri = browser.currentURI?.spec;
        if (uri === 'about:blank' || !uri) {
          const bc = browser.browsingContext;
          if (bc && typeof bc.reload === 'function') {
            const Ci = Components.interfaces;
            bc.reload(Ci.nsIWebNavigation.LOAD_FLAGS_NONE);
            return;
          }
        }
      } catch (e) {
        dump(`juggler: reload-fallback failed: ${e}\n`);
      }
      const doc = browser.ownerDocument;
      doc.getElementById('Browser:Reload').doCommand();
    });
  }

  async ['Page.describeNode'](options) {
    return await this._contentPage.send('describeNode', options);
  }

  async ['Page.scrollIntoViewIfNeeded'](options) {
    return await this._contentPage.send('scrollIntoViewIfNeeded', options);
  }

  // Camoufox: measure at each dispatch, after any await, like
  // Page.dispatchMouseEvent does. Same conversion as a mouse event: a wheel at
  // relative y == 0 would otherwise land on the chrome/content boundary and
  // scroll the tab strip.
  _sendWheelStep(win, modifiers, step) {
    MouseDispatch.forBrowser(win, this._pageTarget._linkedBrowser, {modifiers}).sendWheel(step.x, step.y, {
      deltaX: step.dx,
      deltaY: step.dy,
      deltaZ: step.dz,
      deltaMode: step.mode,
      lineOrPageDeltaX: step.ticks?.x ?? 0,
      lineOrPageDeltaY: step.ticks?.y ?? 0,
      nativeNotches: Boolean(step.ticks) && !this._identityIs('Mac', 'Darwin'),
    });
  }

  async ['Page.setInitScripts']({ scripts }) {
    return await this._pageTarget.setInitScripts(scripts);
  }

  // Camoufox: Firefox's content process drops user input that reaches a
  // document before its input gate opens: dom.input_events.security.
  // minTimeElapsedInMS (100) after readyState became "loading" and
  // minNumTicks (3) refresh ticks (PresShell::CanHandleUserInputEvents,
  // nsPresContext::UserInputEventsAllowed). A wheel turned right after goto
  // lost its first notches there, while mouse and key events, flagged
  // synthesized-for-tests, got through early: trusted input no person's
  // Firefox delivers. Input waits for the gate instead, so it lands, and lands
  // when a person's could.
  async _awaitUserInputGate() {
    const windowGlobal = this._pageTarget.linkedBrowser()?.browsingContext?.currentWindowGlobal;
    if (windowGlobal && this._userInputGateOpen.has(windowGlobal))
      return;
    try {
      await this._contentPage.send('awaitUserInputGate');
    } catch (e) {
      return;
    }
    if (windowGlobal)
      this._userInputGateOpen.add(windowGlobal);
  }

  // Camoufox: a driven page stays focused and active (content/main.js), so
  // keyboard input does not have to raise its window or select its tab first.
  // Page.bringToFront still does that for callers that ask for it.
  _isFrontPage() {
    const browser = this._pageTarget.linkedBrowser();
    const win = browser?.documentGlobal || browser?.ownerGlobal;
    return !!win && Services.focus.activeWindow === win && win.gBrowser?.selectedBrowser === browser;
  }

  async _focusFrontPage() {
    const browser = this._pageTarget.linkedBrowser();
    browser.focus();
    const deadline = Date.now() + 1000;
    while (!this._isFrontPage() && Date.now() < deadline)
      await new Promise(resolve => setTimeout(resolve, 10));
    // A late window activation can move focus to the chrome; put it back.
    if (this._isFrontPage() && Services.focus.focusedElement !== browser)
      browser.focus();
  }

  async ['Page.dispatchKeyEvent']({type, keyCode, code, key, repeat, location, text}) {
    await this._awaitUserInputGate();
    // key events don't fire if we are dragging.
    if (this._isDragging) {
      if (type === 'keydown' && key === 'Escape') {
        await this._contentPage.send('dispatchDragEvent', {
          type: 'dragover',
          x: this._lastMousePosition.x,
          y: this._lastMousePosition.y,
          modifiers: 0
        });
        await this._contentPage.send('dispatchDragEvent', {type: 'dragend'});
        this._isDragging = false;
      }
      return;
    }
    return await this._contentPage.send('dispatchKeyEvent', {type, keyCode, code, key, repeat, location, text});
  }

  async ['Page.dispatchTouchEvent'](options) {
    await this._awaitUserInputGate();
    return await this._contentPage.send('dispatchTouchEvent', options);
  }

  async ['Page.dispatchTapEvent'](options) {
    await this._awaitUserInputGate();
    return await this._contentPage.send('dispatchTapEvent', options);
  }

  // Camoufox: a move is queued in the renderer and reaches the page at the
  // next refresh tick, coalesced with the moves queued since the last one, as
  // a real mouse's are (input-coalescing-parity.patch). Moves are spaced like
  // a 125 Hz mouse's reports, the common rate, so a path given as steps
  // reaches the page as a real mouse's motion does: about two moves per frame
  // in getCoalescedEvents(), one pointerrawupdate each. The page has seen the
  // last move before any other command of this page runs (beforeDispatch).
  async _sendMove(dispatch, watcher, x, y) {
    const wait = this._lastMoveAt + kMoveIntervalMs - Date.now();
    if (wait > 0)
      await new Promise(resolve => setTimeout(resolve, wait));
    // Stamp at send, not after the queue ack. The next move cannot start until
    // this command returns, and that return waits for the ack: stamping after
    // it spaces sends by 8 ms plus the ack, about one move per frame instead
    // of a 125 Hz mouse's two.
    this._lastMoveAt = Date.now();
    // Listen before dispatching, so the tick cannot come first.
    const delivery = new EventWatcher(this._pageEventSink, ['mousemove'], this._pendingEventWatchers);
    const pending = await dispatch.sendQueuedMove(watcher, delivery, x, y);
    // The newest move is the one the coalesced dispatch acks.
    this._moveDelivery?.dispose();
    this._moveDelivery = pending;
    return pending;
  }

  async _moveDelivered() {
    const pending = this._moveDelivery;
    if (!pending)
      return;
    await pending.delivered();
    if (this._moveDelivery === pending)
      this._moveDelivery = null;
    pending.dispose();
  }

  // Called by the protocol session before each command of this page. Any
  // command but another move waits until the page has the last move, so what
  // a caller does after page.mouse.move() sees the move.
  //
  // Mouse commands also join the input chain in the order they arrived. Each
  // one has waits of its own before it gets there (the move's delivery, the
  // input gate), and a release that cleared them first was dispatched before
  // its press: the page saw mouseup, then mousedown, and no click
  // (near-edge-mouse-deadlock.py cold pages, ~1 in 3 runs once mousedown
  // waited a dwell). A command takes its turn here, synchronously on arrival,
  // and hands it on once it is queued on the chain (_mouseTurnTaken).
  async beforeDispatch(method, params) {
    if (method === 'Page.dispatchMouseEvent') {
      const previous = this._mouseTurn;
      let handOn;
      this._mouseTurn = new Promise(resolve => handOn = resolve);
      this._mouseTurns.set(params, handOn);
      await previous;
      if (params.type === 'mousemove')
        return;
    }
    await this._moveDelivered();
  }

  // The command's turn is over: the next mouse command may join the chain.
  _mouseTurnTaken(params) {
    const handOn = this._mouseTurns.get(params);
    this._mouseTurns.delete(params);
    handOn?.();
  }

  async ['Page.dispatchMouseEvent'](params) {
    try {
      return await this._dispatchMouseEvent(params);
    } finally {
      this._mouseTurnTaken(params);
    }
  }

  async _dispatchMouseEvent(params) {
    const {type, x, y, button, clickCount, modifiers, buttons} = params;
    await this._awaitUserInputGate();
    const win = this._pageTarget._window;
    const eventArgs = {button, clickCount, modifiers, buttons};
    const sendEvents = async (types) => {
      // 1. Scroll element to the desired location first; the coordinates are relative to the element.
      this._pageTarget._linkedBrowser.scrollRectIntoViewIfNeeded(x, y, 0, 0);
      // 2. Make sure compositor is flushed after scrolling.
      if (win.windowUtils.flushApzRepaints())
        await helper.awaitTopicWithin('apz-repaints-flushed', kAckDeadlineMs);
      // 3. Get element's bounding box in the browser after the scroll is completed.
      //    MouseDispatch owns every conversion from these relative coordinates to
      //    absolute ones, and every wait for a renderer ack.
      //
      //    Camoufox: measured AFTER the await above, synchronously before the
      //    dispatch. The rect was previously taken before it, and the chrome can
      //    change height during that wait (the toolbar grows 1 px when a
      //    startup addon's button lands): a relative y of 0 then dispatched at
      //    the stale top, one row above the content, arrived in the renderer as
      //    an exit event at client y == -1, produced no ack, and the page saw no
      //    mousemove (tests/playwright/patches/near-edge-mouse-deadlock.py, ~1 in 25 runs).
      const dispatch = MouseDispatch.forBrowser(win, this._pageTarget._linkedBrowser, eventArgs);

      // A move is acked when the renderer queues it (mousequeued); _sendMove
      // tracks when the page gets it (mousemove, at the refresh tick).
      const acks = types.includes('mousemove') ? [...types, 'mousequeued'] : types;
      const watcher = new EventWatcher(this._pageEventSink, acks, this._pendingEventWatchers);
      const promises = [];
      for (const eventType of types) {
        // Camoufox: with humanize on, a direct mousemove becomes a human-like
        // trajectory of intermediate mousemoves that ends exactly on the
        // requested destination.
        const humanized = eventType === 'mousemove' && ChromeUtils.camouGetBool('humanize', false) &&
            humanizedMove(this._lastTrackedPos, {x, y});
        if (humanized) {
          await dispatch.sendTrajectoryAcked(watcher, 'mousemove', humanized.plan,
              (plan, dispatchStep) => play(plan, dispatchStep, {signal: this._humanizeAbort.signal, deadlineMs: humanized.deadlineMs}),
              (destX, destY) => this._sendMove(dispatch, watcher, destX, destY));
        } else if (eventType === 'mousemove') {
          promises.push(this._sendMove(dispatch, watcher, x, y));
        } else {
          promises.push(dispatch.sendAcked(watcher, eventType, x, y));
        }
      }
      await Promise.all(promises);
      await watcher.dispose();
    };

    // We must switch to proper tab in the tabbed browser so that
    // 1. Event is dispatched to a proper renderer.
    // 2. We receive an ack from the renderer for the dispatched event.
    await this._clickPacing(type, clickCount);
    const dispatched = this._mouseDispatched = this._pageTarget.activateAndRun(async () => {
      this._pageTarget.ensureContextMenuClosed();
      // If someone asks us to dispatch mouse event outside of viewport, then we normally would drop it.
      const dispatch = MouseDispatch.forBrowser(win, this._pageTarget._linkedBrowser, eventArgs);
      if (!dispatch.isInViewport(x, y)) {
        if (type !== 'mousemove')
          return;

        // A special hack: if someone tries to do `mousemove` outside of
        // viewport coordinates, then move the mouse off from the Web Content.
        // This way we can eliminate all the hover effects.
        dispatch.parkOffContent();
        // Camoufox: the pointer really moved (off content), so forget the tracked
        // position. Otherwise a later move back to the same coordinates was
        // treated as a no-op and skipped, and the following mousedown made the
        // pointer re-enter content with the button already down -- pointerover /
        // pointerenter / mouseover carried buttons=1 and pressure=0.5, which a
        // real mouse never does (measured 2026-09-14 against XTEST input).
        this._lastTrackedPos = { x: NaN, y: NaN };
        return;
      }

      if (type === 'mousedown') {
        if (this._isDragging)
          return;

        // Camoufox: Windows shows the context menu on button RELEASE, so the
        // contextmenu event arrives after mouseup with buttons=0; GTK and macOS
        // fire it on press. Follow the claimed OS (measured 2026-09-14: stock
        // Windows contextmenu.buttons=0, camoufox 2).
        const eventNames = (button === 2 && !this._contextMenuOnMouseUp()) ? ['mousedown', 'contextmenu'] : ['mousedown'];
        await sendEvents(eventNames);
        this._buttonDownAt = ChromeUtils.now();
        return;
      }

      if (type === 'mousemove') {
        this._lastMousePosition = { x, y };
        await this._settleDrag(false);
        if (this._isDragging && !this._dragSkipsMove()) {
          this._dragMotion(dispatch, x, y);
          const watcher = new EventWatcher(this._pageEventSink, ['dragover'], this._pendingEventWatchers);
          // A motion fires `drag` at the source, then dragover at the target,
          // as GTK's drag session does. The dragover before a drop is not a
          // motion and has no `drag` (measured on X11 against stock 158.0.1).
          await this._contentPage.send('dispatchDragEvent', {type: 'drag', x, y, modifiers});
          await this._contentPage.send('dispatchDragEvent', {type:'dragover', x, y, modifiers});
          await watcher.ensureEventsAndDispose(['dragover']);
          return;
        }

        // Skip a zero-displacement mousemove. When the destination rounds to the
        // pixel the pointer is already on, the widget generates no eMouseMove, so
        // the juggler-mouse-event-hit-renderer notification never fires and the
        // sendEvents() call below awaits an ack that will never arrive. Because
        // input dispatch is serialized on activateAndRun()'s process-global chain,
        // that one stuck await wedges EVERY later input event for the life of the
        // page. Reproduces on a stock build as the first action:
        //     await page.mouse.move(0, 0);   // cursor starts at 0,0 -> no-op -> hang
        // A no-op move has nothing to dispatch anyway, so return once the tracked
        // position is (re)recorded.
        if (Math.round(x) === Math.round(this._lastTrackedPos.x) &&
            Math.round(y) === Math.round(this._lastTrackedPos.y)) {
          this._lastTrackedPos = { x, y };
          return;
        }
        const watcher = new EventWatcher(this._pageEventSink, ['dragstart', 'juggler-drag-finalized'], this._pendingEventWatchers);
        await sendEvents(['mousemove']);
        // Camoufox: remember where the cursor landed so the next humanized
        // move starts its trajectory from the real previous position.
        this._lastTrackedPos = { x, y };
        if (!buttons)
          this._movedAt = ChromeUtils.now();
        // A move with a button held may start a drag, which the page decides
        // when the move reaches it, at the refresh tick.
        if (buttons)
          await this._moveDelivered();

        // The order of events after 'mousemove' is sent:
        // 1. [dragstart] - might or might NOT be emitted
        // 2. [mousemove] - always emitted. Awaited above when a button is held.
        // 3. [juggler-drag-finalized] - only emitted if dragstart was emitted.

        if (watcher.hasEvent('dragstart')) {
          this._dragWatcher = watcher;
          await this._settleDrag(false);
        } else {
          watcher.dispose();
        }
        return;
      }

      if (type === 'mouseup') {
        await this._settleDrag(true);
        if (this._isDragging) {
          this._dragMotion(dispatch, x, y);
          const watcher = new EventWatcher(this._pageEventSink, ['dragover'], this._pendingEventWatchers);
          await this._contentPage.send('dispatchDragEvent', {type: 'dragover', x, y, modifiers});
          await this._contentPage.send('dispatchDragEvent', {type: 'drop', x, y, modifiers});
          await this._contentPage.send('dispatchDragEvent', {type: 'dragend', x, y, modifiers});
          // The pointer comes back to the window with the button still held.
          if (this._dragHasPointer)
            MouseDispatch.forBrowser(win, this._pageTarget._linkedBrowser, {...eventArgs, buttons: 1}).enterWindow(x, y);
          // NOTE:
          // - 'drop' event might not be dispatched at all, depending on dropAction.
          // - 'dragend' event might not be dispatched at all, if the source element was removed
          //   during drag. However, it'll be dispatched synchronously in the renderer.
          await watcher.ensureEventsAndDispose(['dragover']);
          this._isDragging = false;
        } else {
          const eventNames = (button === 2 && this._contextMenuOnMouseUp()) ? ['mouseup', 'contextmenu'] : ['mouseup'];
          await sendEvents(eventNames);
          this._buttonUpAt = ChromeUtils.now();
        }
        return;
      }
    }, { muteNotificationsPopup: true });
    // activateAndRun() queued the slot synchronously: the next command's slot
    // now comes after this one.
    this._mouseTurnTaken(params);
    await dispatched;
  }

  // Camoufox: a click's own pacing, on this page's turn and not on the chain
  // every context shares: a person's rests hold no other page's input. The
  // times they count from are set when the event before was dispatched, so
  // that goes first; a failure there is its own command's to report.
  async _clickPacing(type, clickCount) {
    if (type !== 'mousedown' && type !== 'mouseup')
      return;
    await this._mouseDispatched.catch(() => {});
    let wait = 0;
    if (type === 'mouseup') {
      // A person holds a button down for a while before letting go; Playwright
      // sends mouseup right behind mousedown, so the page saw every press
      // released under 10 ms. A script's own longer `delay` stands
      // (driven-click-hold.py).
      if (this._buttonDownAt !== undefined)
        wait = this._buttonDownAt + clickHold() - ChromeUtils.now();
      this._buttonDownAt = undefined;
    } else if (clickCount > 1) {
      // The second press of a double click comes a person's gap after the
      // release, with no move before it (driven-dblclick-gap.py).
      if (this._buttonUpAt !== undefined)
        wait = this._buttonUpAt + clickGap() - ChromeUtils.now();
    } else if (this._movedAt !== undefined) {
      // A press comes a person's dwell after the move that brought the pointer
      // to its target: a page read under 10 ms where stock reads under 250.
      wait = this._movedAt + hoverDwell() - ChromeUtils.now();
    }
    if (type === 'mousedown') {
      this._buttonUpAt = undefined;
      this._movedAt = undefined;
    }
    if (wait > 0)
      await new Promise(resolve => setTimeout(resolve, wait));
  }

  // Whether the drag a mousemove started has a drag session. Waited for a
  // deadline per input event, not the whole slot; an answer that arrives later
  // still decides the next event, so a busy page's drag still drops. Mouseup
  // ends the gesture: no answer by then means no drag session.
  async _settleDrag(final) {
    const watcher = this._dragWatcher;
    if (!watcher)
      return;
    const finalized = await watcher.ensureEventWithin('juggler-drag-finalized', kAckDeadlineMs);
    if (!finalized && !final)
      return;
    this._dragWatcher = null;
    watcher.dispose();
    this._isDragging = !!finalized?.dragSessionStarted;
    this._dragMoves = 0;
    this._dragHasPointer = false;
  }

  // GTK hands the pointer to a new drag session one move late: the move after
  // the one that fired dragstart still reaches the page as a mousemove with the
  // button held (measured on X11 against stock 158.0.1). Windows and macOS are
  // not measured, so they keep dragging from the first move.
  _dragSkipsMove() {
    return Services.appinfo.widgetToolkit === 'gtk' && this._dragMoves++ === 0;
  }

  // The first drag motion takes the pointer from the window, as a GTK drag
  // session's grab does: a widget exit, so the drag starts with nothing hovered
  // and the next move after the drop reports no movement.
  _dragMotion(dispatch, x, y) {
    if (this._dragHasPointer || Services.appinfo.widgetToolkit !== 'gtk')
      return;
    this._dragHasPointer = true;
    dispatch.leaveWindow(x, y);
  }

  _contextMenuOnMouseUp() {
    return this._identityIs('Win', 'WINNT');
  }

  _identityIs(platformPrefix, hostOS) {
    let platform = '';
    try { platform = ChromeUtils.camouGetString('navigator.platform') || ''; } catch (e) {}
    if (platform)
      return platform.startsWith(platformPrefix);
    return Services.appinfo.OS === hostOS;
  }

  async ['Page.dispatchWheelEvent']({x, y, button, deltaX, deltaY, deltaZ, modifiers }) {
    await this._awaitUserInputGate();
    const activation = { muteNotificationsPopup: true };
    await this._pageTarget.activateAndRun(async () => {
      this._pageTarget.ensureContextMenuClosed();

      // 1. Scroll element to the desired location first; the coordinates are relative to the element.
      this._pageTarget._linkedBrowser.scrollRectIntoViewIfNeeded(x, y, 0, 0);
      // 2. Get element's bounding box in the browser after the scroll is completed.
      // 3. Make sure compositor is flushed after scrolling.
      if (this._pageTarget._window.windowUtils.flushApzRepaints())
        await helper.awaitTopicWithin('apz-repaints-flushed', kAckDeadlineMs);
    }, activation);
    // Camoufox: a wheel turns in notches, as a mouse wheel does
    // (docs/input-dispatch.md): no wheel produces a pixel delta. Each notch
    // takes the activation slot alone, so a long wheel does not hold input in
    // every other context, and waits out its gap from the notch before, however
    // long the slot took to come.
    const win = this._pageTarget._window;
    const macOS = this._identityIs('Mac', 'Darwin');
    const {steps} = cursory.planWheel({rng: Math.random, macOS}, {x, y}, {deltaX, deltaY, deltaZ});
    let previous = 0;
    for (const step of steps) {
      if (step.t > previous)
        await new Promise(resolve => setTimeout(resolve, step.t - previous));
      previous = step.t;
      await this._pageTarget.activateAndRun(() => this._sendWheelStep(win, modifiers, step), activation);
    }
  }

  async ['Page.insertText'](options) {
    await this._awaitUserInputGate();
    return await this._contentPage.send('insertText', options);
  }

  async ['Page.crash'](options) {
    return await this._contentPage.send('crash', options);
  }

  async ['Page.handleDialog']({dialogId, accept, promptText}) {
    const dialog = this._pageTarget.dialog(dialogId);
    if (!dialog)
      throw new Error('Failed to find dialog with id = ' + dialogId);
    if (accept)
      dialog.accept(promptText);
    else
      dialog.dismiss();
  }

  async ['Page.setInterceptFileChooserDialog']({ enabled }) {
    return await this._pageTarget.setInterceptFileChooserDialog(enabled);
  }

  async ['Page.startScreencast'](options) {
    return await this._pageTarget.startScreencast(options);
  }

  async ['Page.screencastFrameAck'](options) {
    await this._pageTarget.screencastFrameAck(options);
  }

  async ['Page.stopScreencast'](options) {
    await this._pageTarget.stopScreencast(options);
  }

  async ['Page.sendMessageToWorker']({workerId, message}) {
    const worker = this._workers.get(workerId);
    if (!worker)
      throw new Error('ERROR: cannot find worker with id ' + workerId);
    return await worker.sendMessage(JSON.parse(message));
  }
}
