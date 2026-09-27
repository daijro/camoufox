/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

const {Helper, EventWatcher} = ChromeUtils.importESModule('chrome://juggler/content/Helper.js');
const {NetUtil} = ChromeUtils.importESModule('resource://gre/modules/NetUtil.sys.mjs');
const {NetworkObserver, PageNetwork} = ChromeUtils.importESModule('chrome://juggler/content/NetworkObserver.js');
const {PageTarget} = ChromeUtils.importESModule('chrome://juggler/content/TargetRegistry.js');
const {setTimeout} = ChromeUtils.importESModule('resource://gre/modules/Timer.sys.mjs');
const {MouseDispatch} = ChromeUtils.importESModule('chrome://juggler/content/input/MouseDispatch.js');
const {humanizedSteps} = ChromeUtils.importESModule('chrome://juggler/content/input/CursorTrajectory.js');

const Cc = Components.classes;
const Ci = Components.interfaces;
const Cu = Components.utils;
const XUL_NS = 'http://www.mozilla.org/keymaster/gatekeeper/there.is.only.xul';
const helper = new Helper();

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
    this._lastMousePosition = { x: 0, y: 0 };
    // Camoufox: last position an actual mousemove landed on. Used as the
    // start point for the humanized cursor trajectory (humanize=True).
    this._lastTrackedPos = { x: 0, y: 0 };

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
    await this._pageTarget.activateAndRun(() => {});
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
    let ctx = canvas.getContext('2d');
    ctx.drawImage(snapshot, 0, 0);
    snapshot.close();

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
    browsingContext.loadURI(Services.io.newURI(url), {
      triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
      loadFlags: Ci.nsIWebNavigation.LOAD_FLAGS_IS_LINK,
      referrerInfo,
      // postData: null,
      // headers: null,
      // Fake user activation.
      hasValidUserGestureActivation: true,
    });
    unsubscribe();

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

  async ['Page.setInitScripts']({ scripts }) {
    return await this._pageTarget.setInitScripts(scripts);
  }

  async ['Page.dispatchKeyEvent']({type, keyCode, code, key, repeat, location, text}) {
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
    return await this._contentPage.send('dispatchTouchEvent', options);
  }

  async ['Page.dispatchTapEvent'](options) {
    return await this._contentPage.send('dispatchTapEvent', options);
  }

  async ['Page.dispatchMouseEvent']({type, x, y, button, clickCount, modifiers, buttons}) {
    const win = this._pageTarget._window;
    const eventArgs = {button, clickCount, modifiers, buttons};
    const sendEvents = async (types) => {
      // 1. Scroll element to the desired location first; the coordinates are relative to the element.
      this._pageTarget._linkedBrowser.scrollRectIntoViewIfNeeded(x, y, 0, 0);
      // 2. Make sure compositor is flushed after scrolling.
      if (win.windowUtils.flushApzRepaints())
        await helper.awaitTopic('apz-repaints-flushed');
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
      //    mousemove (tests/patches/near-edge-mouse-deadlock.py, ~1 in 25 runs).
      const dispatch = MouseDispatch.forBrowser(win, this._pageTarget._linkedBrowser, eventArgs);

      const watcher = new EventWatcher(this._pageEventSink, types, this._pendingEventWatchers);
      const promises = [];
      for (const eventType of types) {
        // Camoufox: when humanize is enabled, expand a direct mousemove into a
        // human-like trajectory of intermediate mousemoves, replayed from a
        // recording of a real hand (input/CursorTrajectory.js -> Cursory).
        if (eventType === 'mousemove' && ChromeUtils.camouGetBool('humanize', false)) {
          // The endpoints are excluded: the cursor is already on the first, and
          // the last is the destination dispatched explicitly below.
          const {steps, trailingDelayMs} =
              humanizedSteps(this._lastTrackedPos.x, this._lastTrackedPos.y, x, y);
          await dispatch.sendTrajectoryAcked(watcher, 'mousemove', steps, trailingDelayMs);
          // Always finish exactly on the requested destination.
          promises.push(dispatch.sendAcked(watcher, 'mousemove', x, y));
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
    await this._pageTarget.activateAndRun(async () => {
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
        return;
      }

      if (type === 'mousemove') {
        this._lastMousePosition = { x, y };
        if (this._isDragging) {
          const watcher = new EventWatcher(this._pageEventSink, ['dragover'], this._pendingEventWatchers);
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

        // The order of events after 'mousemove' is sent:
        // 1. [dragstart] - might or might NOT be emitted
        // 2. [mousemove] - always emitted. This was awaited as part of `sendEvents` call.
        // 3. [juggler-drag-finalized] - only emitted if dragstart was emitted.

        if (watcher.hasEvent('dragstart')) {
          const eventObject = await watcher.ensureEvent('juggler-drag-finalized');
          this._isDragging = eventObject.dragSessionStarted;
        }
        watcher.dispose();
        return;
      }

      if (type === 'mouseup') {
        if (this._isDragging) {
          const watcher = new EventWatcher(this._pageEventSink, ['dragover'], this._pendingEventWatchers);
          await this._contentPage.send('dispatchDragEvent', {type: 'dragover', x, y, modifiers});
          await this._contentPage.send('dispatchDragEvent', {type: 'drop', x, y, modifiers});
          await this._contentPage.send('dispatchDragEvent', {type: 'dragend', x, y, modifiers});
          // NOTE:
          // - 'drop' event might not be dispatched at all, depending on dropAction.
          // - 'dragend' event might not be dispatched at all, if the source element was removed
          //   during drag. However, it'll be dispatched synchronously in the renderer.
          await watcher.ensureEventsAndDispose(['dragover']);
          this._isDragging = false;
        } else {
          const eventNames = (button === 2 && this._contextMenuOnMouseUp()) ? ['mouseup', 'contextmenu'] : ['mouseup'];
          await sendEvents(eventNames);
        }
        return;
      }
    }, { muteNotificationsPopup: true });
  }

  _contextMenuOnMouseUp() {
    let platform = '';
    try { platform = ChromeUtils.camouGetString('navigator.platform') || ''; } catch (e) {}
    if (platform)
      return platform.startsWith('Win');
    return Services.appinfo.OS === 'WINNT';
  }

  async ['Page.dispatchWheelEvent']({x, y, button, deltaX, deltaY, deltaZ, modifiers }) {
    // Camoufox: with humanize on, scroll the way a physical wheel does, in
    // notches. Each notch is its own event of 3 LINES carrying one native tick,
    // so the page sees deltaMode 1, DOMMouseScroll.detail 3 and wheelDelta -120
    // per notch, and a longer scroll arrives as several such events a few tens
    // of ms apart. Playwright's pixel delta gives detail = 100 and no line
    // delta; lines without ticks give wheelDelta -396 for one notch and one big
    // event for several (measured against XTEST input). 100 px == one notch.
    //
    // Off by default: mouse.wheel(0, 100) has to deliver deltaY 100 in
    // deltaMode 0, which is the delta the caller asked for and what upstream's
    // own suite asserts. Quantising into notches changes the number the page
    // sees, so it is opt-in with the rest of the humanized input.
    const nativeNotches = ChromeUtils.camouGetBool('humanize', false);
    const PX_PER_NOTCH = 100;
    const LINES_PER_NOTCH = 3;
    const toNotches = (d) => (d === 0 ? 0 : Math.sign(d) * Math.max(1, Math.round(Math.abs(d) / PX_PER_NOTCH)));
    const notchesX = nativeNotches ? toNotches(deltaX) : 0;
    const notchesY = nativeNotches ? toNotches(deltaY) : 0;
    const notchCount = nativeNotches ? Math.max(1, Math.abs(notchesX), Math.abs(notchesY)) : 1;
    // Upstream's conversion, used when the notches are off.
    const pixelLineOrPageDeltaX = deltaX > 0 ? Math.floor(deltaX) : Math.ceil(deltaX);
    const pixelLineOrPageDeltaY = deltaY > 0 ? Math.floor(deltaY) : Math.ceil(deltaY);

    await this._pageTarget.activateAndRun(async () => {
      this._pageTarget.ensureContextMenuClosed();

      // 1. Scroll element to the desired location first; the coordinates are relative to the element.
      this._pageTarget._linkedBrowser.scrollRectIntoViewIfNeeded(x, y, 0, 0);
      // 2. Get element's bounding box in the browser after the scroll is completed.
      const win = this._pageTarget._window;
      // 3. Make sure compositor is flushed after scrolling.
      if (win.windowUtils.flushApzRepaints())
        await helper.awaitTopic('apz-repaints-flushed');
      for (let i = 0; i < notchCount; i++) {
        if (i)
          await new Promise(resolve => setTimeout(resolve, 18 + Math.random() * 42));
        const stepX = i < Math.abs(notchesX) ? Math.sign(notchesX) * LINES_PER_NOTCH : 0;
        const stepY = i < Math.abs(notchesY) ? Math.sign(notchesY) * LINES_PER_NOTCH : 0;
        // Camoufox: measure after the await, like Page.dispatchMouseEvent does.
        const dispatch = MouseDispatch.forBrowser(win, this._pageTarget._linkedBrowser, {modifiers});
        // Same conversion as a mouse event: a wheel at relative y == 0 would
        // otherwise land on the chrome/content boundary and scroll the tab strip.
        dispatch.sendWheel(x, y, nativeNotches ? {
          deltaX: stepX,
          deltaY: stepY,
          deltaZ: i ? 0 : deltaZ,
          deltaMode: 1 /* WheelEvent.DOM_DELTA_LINE */,
          lineOrPageDeltaX: stepX,
          lineOrPageDeltaY: stepY,
          nativeNotches: true,
        } : {
          deltaX,
          deltaY,
          deltaZ,
          deltaMode: 0 /* WheelEvent.DOM_DELTA_PIXEL */,
          lineOrPageDeltaX: pixelLineOrPageDeltaX,
          lineOrPageDeltaY: pixelLineOrPageDeltaY,
        });
      }
    }, { muteNotificationsPopup: true });
  }

  async ['Page.insertText'](options) {
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
