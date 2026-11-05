/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

const Ci = Components.interfaces;
const Cr = Components.results;
const Cu = Components.utils;

const {Helper} = ChromeUtils.importESModule('resource://gre/modules/juggler/Helper.js');
const {NetUtil} = ChromeUtils.importESModule('resource://gre/modules/NetUtil.sys.mjs');
const {setTimeout} = ChromeUtils.importESModule('resource://gre/modules/Timer.sys.mjs');

const dragService = Cc["@mozilla.org/widget/dragservice;1"].getService(
  Ci.nsIDragService
);
const obs = Cc["@mozilla.org/observer-service;1"].getService(
  Ci.nsIObserverService
);

const helper = new Helper();

class WorkerData {
  constructor(pageAgent, browserChannel, worker) {
    this._workerRuntime = worker.channel().connect('runtime');
    this._browserWorker = browserChannel.connect(worker.id());
    this._worker = worker;
    const emit = name => {
      return (...args) => this._browserWorker.emit(name, ...args);
    };
    this._eventListeners = [
      worker.channel().register('runtime', {
        runtimeConsole: emit('runtimeConsole'),
        runtimeExecutionContextCreated: emit('runtimeExecutionContextCreated'),
        runtimeExecutionContextDestroyed: emit('runtimeExecutionContextDestroyed'),
      }),
      browserChannel.register(worker.id(), {
        evaluate: (options) => this._workerRuntime.send('evaluate', options),
        callFunction: (options) => this._workerRuntime.send('callFunction', options),
        getObjectProperties: (options) => this._workerRuntime.send('getObjectProperties', options),
        disposeObject: (options) => this._workerRuntime.send('disposeObject', options),
      }),
    ];
  }

  dispose() {
    this._workerRuntime.dispose();
    this._browserWorker.dispose();
    helper.removeListeners(this._eventListeners);
  }
}

export class PageAgent {
  constructor(browserChannel, frameTree) {
    this._browserChannel = browserChannel;
    this._browserPage = browserChannel.connect('page');
    this._frameTree = frameTree;
    this._runtime = frameTree.runtime();

    this._workerData = new Map();

    const docShell = frameTree.mainFrame().docShell();
    this._docShell = docShell;

    // Dispatch frameAttached events for all initial frames
    for (const frame of this._frameTree.frames()) {
      this._onFrameAttached(frame);
      if (frame.url())
        this._onNavigationCommitted(frame);
      if (frame.pendingNavigationId())
        this._onNavigationStarted(frame);
    }

    // Report created workers.
    for (const worker of this._frameTree.workers())
      this._onWorkerCreated(worker);

    // Report execution contexts.
    this._browserPage.emit('runtimeExecutionContextsCleared', {});
    for (const context of this._runtime.executionContexts())
      this._onExecutionContextCreated(context);

    if (this._frameTree.isPageReady()) {
      this._browserPage.emit('pageReady', {});
      const mainFrame = this._frameTree.mainFrame();
      const domWindow = mainFrame.domWindow();
      const document = domWindow ? domWindow.document : null;
      const readyState = document ? document.readyState : null;
      // Sometimes we initialize later than the first about:blank page is opened.
      // In this case, the page might've been loaded already, and we need to issue
      // the `DOMContentLoaded` and `load` events.
      if (mainFrame.url() === 'about:blank' && readyState === 'complete')
        this._emitAllEvents(this._frameTree.mainFrame());
    }

    this._eventListeners = [
      helper.addObserver(this._linkClicked.bind(this, false), 'juggler-link-click'),
      helper.addObserver(this._linkClicked.bind(this, true), 'juggler-link-click-sync'),
      helper.addObserver(this._onWindowOpenInNewContext.bind(this), 'juggler-window-open-in-new-context'),
      helper.addObserver(this._filePickerShown.bind(this), 'juggler-file-picker-shown'),
      helper.addObserver(this._onDocumentOpenLoad.bind(this), 'juggler-document-open-loaded'),
      helper.on(this._frameTree, 'frameattached', this._onFrameAttached.bind(this)),
      helper.on(this._frameTree, 'framedetached', this._onFrameDetached.bind(this)),
      helper.on(this._frameTree, 'navigationstarted', this._onNavigationStarted.bind(this)),
      helper.on(this._frameTree, 'navigationcommitted', this._onNavigationCommitted.bind(this)),
      helper.on(this._frameTree, 'navigationaborted', this._onNavigationAborted.bind(this)),
      helper.on(this._frameTree, 'samedocumentnavigation', this._onSameDocumentNavigation.bind(this)),
      helper.on(this._frameTree, 'pageready', () => this._browserPage.emit('pageReady', {})),
      helper.on(this._frameTree, 'workercreated', this._onWorkerCreated.bind(this)),
      helper.on(this._frameTree, 'workerdestroyed', this._onWorkerDestroyed.bind(this)),
      helper.on(this._frameTree, 'websocketcreated', event => this._browserPage.emit('webSocketCreated', event)),
      helper.on(this._frameTree, 'websocketopened', event => this._browserPage.emit('webSocketOpened', event)),
      helper.on(this._frameTree, 'websocketframesent', event => this._browserPage.emit('webSocketFrameSent', event)),
      helper.on(this._frameTree, 'websocketframereceived', event => this._browserPage.emit('webSocketFrameReceived', event)),
      helper.on(this._frameTree, 'websocketclosed', event => this._browserPage.emit('webSocketClosed', event)),
      helper.on(this._frameTree, 'inputevent', inputEvent => {
        this._browserPage.emit('pageInputEvent', inputEvent);
        if (inputEvent.type === 'dragstart') {
          // After the dragStart event is dispatched and handled by Web,
          // it might or might not create a new drag session, depending on its preventing default.
          setTimeout(() => {
            const session = this._getCurrentDragSession();
            this._browserPage.emit('pageInputEvent', { type: 'juggler-drag-finalized', dragSessionStarted: !!session });
          }, 0);
        }
      }),
      helper.addObserver(this._onWindowOpen.bind(this), 'webNavigation-createdNavigationTarget-from-js'),
      this._runtime.events.onErrorFromWorker((domWindow, message, stack, location) => {
        const frame = this._frameTree.frameForDocShell(domWindow.docShell);
        if (!frame)
          return;
        this._browserPage.emit('pageUncaughtError', {
          frameId: frame.id(),
          message,
          stack,
          location,
        });
      }),
      this._runtime.events.onConsoleMessage(msg => this._browserPage.emit('runtimeConsole', msg)),
      this._runtime.events.onRuntimeError(this._onRuntimeError.bind(this)),
      this._runtime.events.onExecutionContextCreated(this._onExecutionContextCreated.bind(this)),
      this._runtime.events.onExecutionContextDestroyed(this._onExecutionContextDestroyed.bind(this)),
      this._runtime.events.onBindingCalled(this._onBindingCalled.bind(this)),
      browserChannel.register('page', {
        adoptNode: this._adoptNode.bind(this),
        crash: this._crash.bind(this),
        describeNode: this._describeNode.bind(this),
        awaitUserInputGate: this._awaitUserInputGate.bind(this),
        dispatchKeyEvent: this._dispatchKeyEvent.bind(this),
        dispatchDragEvent: this._dispatchDragEvent.bind(this),
        dispatchTouchEvent: this._dispatchTouchEvent.bind(this),
        dispatchTapEvent: this._dispatchTapEvent.bind(this),
        getContentQuads: this._getContentQuads.bind(this),
        getFullAXTree: this._getFullAXTree.bind(this),
        insertText: this._insertText.bind(this),
        humanizeFocus: this._humanizeFocus.bind(this),
        humanizeScrollProbe: this._humanizeScrollProbe.bind(this),
        scrollIntoViewIfNeeded: this._scrollIntoViewIfNeeded.bind(this),
        setFileInputFiles: this._setFileInputFiles.bind(this),
        evaluate: this._runtime.evaluate.bind(this._runtime),
        callFunction: this._runtime.callFunction.bind(this._runtime),
        getObjectProperties: this._runtime.getObjectProperties.bind(this._runtime),
        disposeObject: this._runtime.disposeObject.bind(this._runtime),
      }),
    ];
  }

  _emitAllEvents(frame) {
    this._browserPage.emit('pageEventFired', {
      frameId: frame.id(),
      name: 'DOMContentLoaded',
    });
    this._browserPage.emit('pageEventFired', {
      frameId: frame.id(),
      name: 'load',
    });
  }

  _onExecutionContextCreated(executionContext) {
    this._browserPage.emit('runtimeExecutionContextCreated', {
      executionContextId: executionContext.id(),
      auxData: executionContext.auxData(),
    });
  }

  _onExecutionContextDestroyed(executionContext) {
    this._browserPage.emit('runtimeExecutionContextDestroyed', {
      executionContextId: executionContext.id(),
    });
  }

  _onWorkerCreated(worker) {
    const workerData = new WorkerData(this, this._browserChannel, worker);
    this._workerData.set(worker.id(), workerData);
    this._browserPage.emit('pageWorkerCreated', {
      workerId: worker.id(),
      frameId: worker.frame().id(),
      url: worker.url(),
    });
  }

  _onWorkerDestroyed(worker) {
    const workerData = this._workerData.get(worker.id());
    if (!workerData)
      return;
    this._workerData.delete(worker.id());
    workerData.dispose();
    this._browserPage.emit('pageWorkerDestroyed', {
      workerId: worker.id(),
    });
  }

  _onWindowOpen(subject) {
    if (!(subject instanceof Ci.nsIPropertyBag2))
      return;
    const props = subject.QueryInterface(Ci.nsIPropertyBag2);
    const hasUrl = props.hasKey('url');
    const createdDocShell = props.getPropertyAsInterface('createdTabDocShell', Ci.nsIDocShell);
    if (!hasUrl && createdDocShell === this._docShell && this._frameTree.forcePageReady())
      this._emitAllEvents(this._frameTree.mainFrame());
  }

  _linkClicked(sync, anchorElement) {
    // Firefox 152 renamed `ownerGlobal` to `documentGlobal` on nodes.
    if ((anchorElement.documentGlobal || anchorElement.ownerGlobal).docShell !== this._docShell)
      return;
    this._browserPage.emit('pageLinkClicked', { phase: sync ? 'after' : 'before' });
  }

  _onWindowOpenInNewContext(docShell) {
    // TODO: unify this with _onWindowOpen if possible.
    const frame = this._frameTree.frameForDocShell(docShell);
    if (!frame)
      return;
    this._browserPage.emit('pageWillOpenNewWindowAsynchronously');
  }

  _filePickerShown(inputElement) {
    const frame = this._findFrameForNode(inputElement);
    if (!frame)
      return;
    this._browserPage.emit('pageFileChooserOpened', {
      executionContextId: frame.mainExecutionContext().id(),
      element: frame.mainExecutionContext().rawValueToRemoteObject(inputElement)
    });
  }

  _findFrameForNode(node) {
    return this._frameTree.frames().find(frame => {
      const doc = frame.domWindow().document;
      return node === doc || node.ownerDocument === doc;
    });
  }

  onWindowEvent(event) {
    if (event.type !== 'DOMContentLoaded' && event.type !== 'load')
      return;
    // Firefox 152: `ownerGlobal` may be null here; fall back to `defaultView`.
    const win = event.target.ownerGlobal || event.target.defaultView;
    if (!win)
      return;
    const docShell = win.docShell;
    const frame = this._frameTree.frameForDocShell(docShell);
    if (!frame)
      return;
    this._browserPage.emit('pageEventFired', {
      frameId: frame.id(),
      name: event.type,
    });
  }

  _onRuntimeError({ executionContext, message, stack, location }) {
    this._browserPage.emit('pageUncaughtError', {
      frameId: executionContext.auxData().frameId,
      message: message.toString(),
      stack: stack.toString(),
      location,
    });
  }

  _onDocumentOpenLoad(document) {
    // Firefox 152: `ownerGlobal` may be null; fall back to `defaultView`.
    const win = document.ownerGlobal || document.defaultView;
    if (!win)
      return;
    const docShell = win.docShell;
    const frame = this._frameTree.frameForDocShell(docShell);
    if (!frame)
      return;
    this._browserPage.emit('pageEventFired', {
      frameId: frame.id(),
      name: 'load'
    });
  }

  _onNavigationStarted(frame) {
    this._browserPage.emit('pageNavigationStarted', {
      frameId: frame.id(),
      navigationId: frame.pendingNavigationId(),
    });
  }

  _onNavigationAborted(frame, navigationId, errorText) {
    this._browserPage.emit('pageNavigationAborted', {
      frameId: frame.id(),
      navigationId,
      errorText,
    });
    if (!frame._initialNavigationDone && frame !== this._frameTree.mainFrame())
      this._emitAllEvents(frame);
    frame._initialNavigationDone = true;
  }

  _onSameDocumentNavigation(frame) {
    this._browserPage.emit('pageSameDocumentNavigation', {
      frameId: frame.id(),
      url: frame.url(),
    });
  }

  _onNavigationCommitted(frame) {
    this._browserPage.emit('pageNavigationCommitted', {
      frameId: frame.id(),
      navigationId: frame.lastCommittedNavigationId() || undefined,
      url: frame.url(),
      name: frame.name(),
    });
    frame._initialNavigationDone = true;
  }

  _onFrameAttached(frame) {
    this._browserPage.emit('pageFrameAttached', {
      frameId: frame.id(),
      parentFrameId: frame.parentFrame() ? frame.parentFrame().id() : undefined,
    });
  }

  _onFrameDetached(frame) {
    this._browserPage.emit('pageFrameDetached', {
      frameId: frame.id(),
    });
  }

  _onBindingCalled({executionContextId, name, payload}) {
    this._browserPage.emit('pageBindingCalled', {
      executionContextId,
      name,
      payload
    });
  }

  dispose() {
    for (const workerData of this._workerData.values())
      workerData.dispose();
    this._workerData.clear();
    helper.removeListeners(this._eventListeners);
  }

  async _adoptNode({frameId, objectId, executionContextId}) {
    const frame = this._frameTree.frame(frameId);
    if (!frame)
      throw new Error('Failed to find frame with id = ' + frameId);
    let unsafeObject;
    if (!objectId) {
      unsafeObject = frame.domWindow().frameElement;
    } else {
      unsafeObject = frame.unsafeObject(objectId);
    }
    const context = this._runtime.findExecutionContext(executionContextId);
    const fromPrincipal = unsafeObject.nodePrincipal;
    const toFrame = this._frameTree.frame(context.auxData().frameId);
    const toPrincipal = toFrame.domWindow().document.nodePrincipal;
    if (!toPrincipal.subsumes(fromPrincipal))
      return { remoteObject: null };
    return { remoteObject: context.rawValueToRemoteObject(unsafeObject) };
  }

  async _setFileInputFiles({objectId, frameId, files}) {
    const frame = this._frameTree.frame(frameId);
    if (!frame)
      throw new Error('Failed to find frame with id = ' + frameId);
    const unsafeObject = frame.unsafeObject(objectId);
    if (!unsafeObject)
      throw new Error('Object is not input!');
    let nsFiles;
    if (unsafeObject.webkitdirectory) {
      nsFiles = await new Directory(files[0]).getFiles(true);
    } else {
      nsFiles = await Promise.all(files.map(filePath => File.createFromFileName(filePath)));
    }
    unsafeObject.mozSetFileArray(nsFiles);
    // The file picker's own shape (DispatchEvents(), HTMLInputElement.cpp).
    // Upstream marks both cancelable and composed, which reads as synthetic.
    const events = [
      new (frame.domWindow().Event)('input', { bubbles: true, composed: true }),
      new (frame.domWindow().Event)('change', { bubbles: true }),
    ];
    for (const event of events)
      unsafeObject.dispatchEvent(event);
  }

  _getContentQuads({objectId, frameId}) {
    const frame = this._frameTree.frame(frameId);
    if (!frame)
      throw new Error('Failed to find frame with id = ' + frameId);
    const unsafeObject = frame.unsafeObject(objectId);
    if (!unsafeObject.getBoxQuads)
      throw new Error('RemoteObject is not a node');
    const quads = unsafeObject.getBoxQuads({relativeTo: this._frameTree.mainFrame().domWindow().document, recurseWhenNoFrame: true}).map(quad => {
      return {
        p1: {x: quad.p1.x, y: quad.p1.y},
        p2: {x: quad.p2.x, y: quad.p2.y},
        p3: {x: quad.p3.x, y: quad.p3.y},
        p4: {x: quad.p4.x, y: quad.p4.y},
      };
    });
    return {quads};
  }

  _describeNode({objectId, frameId}) {
    const frame = this._frameTree.frame(frameId);
    if (!frame)
      throw new Error('Failed to find frame with id = ' + frameId);
    const unsafeObject = frame.unsafeObject(objectId);
    const browsingContextGroup = frame.docShell().browsingContext.group;
    const frames = this._frameTree.allFramesInBrowsingContextGroup(browsingContextGroup);
    let contentFrame;
    let ownerFrame;
    for (const frame of frames) {
      if (unsafeObject.contentWindow && frame.docShell() === unsafeObject.contentWindow.docShell)
        contentFrame = frame;
      const document = frame.domWindow().document;
      if (unsafeObject === document || unsafeObject.ownerDocument === document)
        ownerFrame = frame;
    }
    return {
      contentFrameId: contentFrame ? contentFrame.id() : undefined,
      ownerFrameId: ownerFrame ? ownerFrame.id() : undefined,
    };
  }

  async _scrollIntoViewIfNeeded({objectId, frameId, rect}) {
    const frame = this._frameTree.frame(frameId);
    if (!frame)
      throw new Error('Failed to find frame with id = ' + frameId);
    const unsafeObject = frame.unsafeObject(objectId);
    if (!unsafeObject.isConnected)
      throw new Error('Node is detached from document');
    if (!rect)
      rect = { x: -1, y: -1, width: -1, height: -1};
    if (unsafeObject.scrollRectIntoViewIfNeeded)
      unsafeObject.scrollRectIntoViewIfNeeded(rect.x, rect.y, rect.width, rect.height);
    else
      throw new Error('Node does not have a layout object');
  }

  _getNodeBoundingBox(unsafeObject) {
    if (!unsafeObject.getBoxQuads)
      throw new Error('RemoteObject is not a node');
    const quads = unsafeObject.getBoxQuads({relativeTo: this._frameTree.mainFrame().domWindow().document});
    if (!quads.length)
      return;
    let x1 = Infinity;
    let y1 = Infinity;
    let x2 = -Infinity;
    let y2 = -Infinity;
    for (const quad of quads) {
      const boundingBox = quad.getBounds();
      x1 = Math.min(boundingBox.x, x1);
      y1 = Math.min(boundingBox.y, y1);
      x2 = Math.max(boundingBox.x + boundingBox.width, x2);
      y2 = Math.max(boundingBox.y + boundingBox.height, y2);
    }
    return {x: x1, y: y1, width: x2 - x1, height: y2 - y1};
  }

  // Camoufox: characters that need Shift on a US layout. A person typing "H"
  // or "!" presses Shift first, so a real keydown carries shiftKey=true and is
  // bracketed by Shift keydown/keyup (code ShiftLeft, location 1). Playwright's
  // keyboard.type() never presses Shift, which was a one-line tell (measured
  // 2026-09-14: keydown.which never 16, location never 1).
  _needsShift(text) {
    return typeof text === 'string' && text.length === 1 && /[A-Z~!@#$%^&*()_+{}|:"<>?]/.test(text);
  }

  // Camoufox: resolves once this process's top document accepts user input
  // (PageHandler._awaitUserInputGate): minTimeElapsedInMS after readyState
  // became "loading" (performance.timing.domLoading, the same moment as
  // Document::mLoadingOrRestoredFromBFCacheTimeStamp), then a refresh tick.
  // The initial about:blank is exempt, as in nsPresContext.
  async _awaitUserInputGate() {
    const win = this._frameTree.mainFrame().domWindow();
    if (!win || win.document.isInitialDocument)
      return;
    const timing = win.performance.timing;
    if (!timing.domLoading)
      return;
    const gateMs = Services.prefs.getIntPref('dom.input_events.security.minTimeElapsedInMS', 100);
    // +2: performance.now() is clamped to the timer precision.
    const waitMs = gateMs + 2 - (win.performance.now() - (timing.domLoading - timing.navigationStart));
    if (waitMs <= 0)
      return;
    await new Promise(resolve => setTimeout(resolve, waitMs));
    // minNumTicks: a tick after the time has passed; a hidden page's refresh
    // driver is throttled, and the gate is open for it anyway.
    await new Promise(resolve => {
      win.requestAnimationFrame(() => resolve());
      setTimeout(resolve, 100);
    });
  }

  async _dispatchKeyEvent({type, keyCode, code, key, repeat, location, text}) {
    const frame = this._frameTree.mainFrame();
    const tip = frame.textInputProcessor();
    const KeyboardEvent = frame.domWindow().KeyboardEvent;
    if (key === 'Shift')
      this._realShiftDown = type === 'keydown';
    const autoShift = type === 'keydown' && !this._realShiftDown && !this._autoShiftKey && this._needsShift(text);
    if (autoShift) {
      tip.keydown(new KeyboardEvent("", { key: 'Shift', code: 'ShiftLeft', location: 1, keyCode: 16, shiftKey: true }), 0);
      this._autoShiftKey = key;
      // A person presses Shift tens of ms before the key it modifies; 0 ms
      // between the two keydowns is a scripted-typing tell.
      await new Promise(resolve => setTimeout(resolve, 35 + Math.random() * 55));
    }
    const shiftKey = this._realShiftDown || !!this._autoShiftKey;
    let keyEvent = new KeyboardEvent("", {
      key,
      code,
      location,
      repeat,
      keyCode,
      shiftKey,
    });
    if (type === 'keydown') {
      try {
        if (text && text !== key) {
          tip.commitCompositionWith(text, keyEvent);
        } else {
          const flags = 0;
          tip.keydown(keyEvent, flags);
        }
      } catch (e) {
        // Do not leave Shift latched in the input processor.
        if (autoShift) {
          tip.keyup(new KeyboardEvent("", { key: 'Shift', code: 'ShiftLeft', location: 1, keyCode: 16 }), 0);
          this._autoShiftKey = null;
        }
        throw e;
      }
    } else if (type === 'keyup') {
      if (text)
        throw new Error(`keyup does not support text option`);
      const flags = 0;
      tip.keyup(keyEvent, flags);
      if (this._autoShiftKey === key) {
        this._autoShiftKey = null;
        await new Promise(resolve => setTimeout(resolve, 20 + Math.random() * 45));
        tip.keyup(new KeyboardEvent("", { key: 'Shift', code: 'ShiftLeft', location: 1, keyCode: 16 }), 0);
      }
    } else {
      throw new Error(`Unknown type ${type}`);
    }
  }

  async _dispatchTouchEvent({type, touchPoints, modifiers}) {
    // Firefox 152+: windowUtils.sendTouchEvent (parallel-array API) was removed.
    // Synthetic touch now goes through Window.synthesizeTouchEvent, which takes a
    // sequence of SynthesizeTouchEventData objects. Mirrors upstream Playwright.
    const frame = this._frameTree.mainFrame();
    const defaultPrevented = frame.domWindow().synthesizeTouchEvent(
      type.toLowerCase(),
      touchPoints.map((point, id) => ({
        identifier: id,
        offsetX: point.x,
        offsetY: point.y,
        radiiX: point.radiusX ?? 1.0,
        radiiY: point.radiusY ?? 1.0,
        rotationAngle: point.rotationAngle ?? 0.0,
        pressure: point.force ?? 1.0,
        tiltX: 0,
        tiltY: 0,
        twist: 0,
      })),
      modifiers
    );
    return {defaultPrevented};
  }

  async _dispatchTapEvent({x, y, modifiers}) {
    // Force a layout at the point in question, because touch events
    // do not seem to trigger one like mouse events.
    this._frameTree.mainFrame().domWindow().windowUtils.elementFromPoint(
      x,
      y,
      false /* aIgnoreRootScrollFrame */,
      true /* aFlushLayout */);

    await this._dispatchTouchEvent({
      type: 'touchstart',
      modifiers,
      touchPoints: [{x, y}]
    });
    await this._dispatchTouchEvent({
      type: 'touchend',
      modifiers,
      touchPoints: [{x, y}]
    });
  }

  _getCurrentDragSession() {
    const frame = this._frameTree.mainFrame();
    const domWindow = frame?.domWindow();
    return domWindow ? dragService.getCurrentSession(domWindow) : undefined;
  }

  async _dispatchDragEvent({type, x, y, modifiers}) {
    const session = this._getCurrentDragSession();
    const dropEffect = session.dataTransfer.dropEffect;

    if (type === 'drag') {
      const win = this._frameTree.mainFrame().domWindow();
      win.windowUtils.jugglerSendMouseEvent(
        'drag', x, y, 0, 0, modifiers, false, 0.0, win.MouseEvent.MOZ_SOURCE_MOUSE,
        true, false, 0, win.windowUtils.DEFAULT_MOUSE_POINTER_ID, false);
      return;
    }
    if ((type === 'drop' && dropEffect !== 'none') || type ===  'dragover') {
      const win = this._frameTree.mainFrame().domWindow();
      win.windowUtils.jugglerSendMouseEvent(
        type,
        x,
        y,
        0, /*button*/
        0, /*clickCount*/
        modifiers,
        false /*aIgnoreRootScrollFrame*/,
        0.0 /*pressure*/,
        win.MouseEvent.MOZ_SOURCE_MOUSE /*inputSource*/,
        true /*isDOMEventSynthesized*/,
        false /*isWidgetEventSynthesized*/,
        type === 'dragover' ? 1 : 0 /*buttons: the held button; released for drop*/,
        win.windowUtils.DEFAULT_MOUSE_POINTER_ID /* pointerIdentifier */,
        false /*disablePointerEvent*/,
      );
      return;
    }
    if (type === 'dragend') {
      const session = this._getCurrentDragSession();
      session?.endDragSession(true);
      await this._afterFrame();
      return;
    }
  }

  // A frame after the drag session ends, by when the page has its pointer back:
  // the session's end moves the pointer on the next refresh. Bounded, since a
  // throttled page may not paint.
  _afterFrame() {
    const win = this._frameTree.mainFrame().domWindow();
    return new Promise(resolve => {
      win.requestAnimationFrame(() => resolve());
      setTimeout(resolve, 100);
    });
  }

  // Camoufox: what a keyboard engine needs to know about the focused element
  // (input/HumanizeSeam.js): whether typed text lands in an editable text
  // control, whether Enter there is a line break, and any length limit.
  _humanizeFocus() {
    let active = this._frameTree.mainFrame().domWindow().document.activeElement;
    // Descend into same-process frames; an out-of-process one reads as not
    // editable, so an engine only paces keys into it.
    while (active && (active.tagName === 'IFRAME' || active.tagName === 'FRAME') && active.contentDocument)
      active = active.contentDocument.activeElement;
    if (!active)
      return {editable: false, multiline: false, type: '', maxLength: -1};
    const isInput = active.tagName === 'INPUT' && /^(text|search|url|tel|email|password|number|)$/i.test(active.type || '');
    const isTextArea = active.tagName === 'TEXTAREA';
    const editable = ((isInput || isTextArea) && !active.readOnly && !active.disabled) || !!active.isContentEditable;
    return {
      editable,
      multiline: editable && !isInput,
      type: isInput ? (active.type || 'text').toLowerCase() : isTextArea ? 'textarea' : (active.isContentEditable ? 'contenteditable' : ''),
      maxLength: (isInput || isTextArea) ? active.maxLength : -1,
    };
  }

  // Camoufox: what a scroll engine needs to plan Page.scrollIntoViewIfNeeded
  // as wheel input (input/HumanizeSeam.js, planIntoView). Coordinates are
  // top-level viewport CSS pixels, the space Page.dispatchMouseEvent uses.
  //
  //   targetRect  the target (or `rect` within it), or null when it cannot be
  //               scrolled to (detached, no layout box, cross-process frame);
  //               the stock scroll then reports the error.
  //   clip        the band the target is visible in: the viewport inset by a
  //               margin, minus pinned (fixed/sticky) bars at the target's
  //               column, intersected with every scrollable ancestor.
  //   region      the target's visible part of `clip`, or null.
  //   hitTestable the region is not covered by a pinned element (hit-tested at
  //               its centre and four interior points); `occluder` is it.
  //   scrollers   the ancestors that can move the target, innermost first,
  //               ending with the page when it can: each with its `rect`
  //               (null for the page), its visible `band`, `scrollTop`,
  //               `maxScroll`, and `wheelPoint.down/up`,
  //               the point nearest `from` (the cursor) where a wheel in that
  //               direction reaches this scroller rather than one inside it.
  _humanizeScrollProbe({objectId, frameId, rect, from}) {
    const kMargin = 20;
    const kEdge = 10;
    const frame = this._frameTree.frame(frameId);
    if (!frame)
      throw new Error('Failed to find frame with id = ' + frameId);
    const el = frame.unsafeObject(objectId);
    const topWin = this._frameTree.mainFrame().domWindow();
    const topDoc = topWin.document;
    const vw = topWin.innerWidth;
    const vh = topWin.innerHeight;
    const viewport = {width: vw, height: vh};
    if (!el.isConnected || !el.getBoundingClientRect)
      return {viewport, targetRect: null};

    const styleOf = node => node.ownerDocument.defaultView.getComputedStyle(node);
    const isFrameDocRoot = node => node === node.ownerDocument.documentElement && node.ownerDocument.defaultView !== topWin;
    // Up through shadow hosts and same-process frame boundaries.
    const stepUp = node => {
      if (node.parentElement)
        return node.parentElement;
      const root = node.getRootNode();
      if (root.host)
        return root.host;
      return root.defaultView?.frameElement ?? null;
    };
    const frameOffset = node => {
      let x = 0;
      let y = 0;
      let win = node.ownerDocument.defaultView;
      while (win && win !== topWin) {
        const fe = win.frameElement;
        if (!fe)
          return null;
        const fr = fe.getBoundingClientRect();
        x += fr.x + fe.clientLeft;
        y += fr.y + fe.clientTop;
        win = fe.ownerDocument.defaultView;
      }
      return {x, y};
    };
    const rectOf = node => {
      const r = node.getBoundingClientRect();
      const o = frameOffset(node) ?? {x: 0, y: 0};
      return {x: r.x + o.x, y: r.y + o.y, width: r.width, height: r.height,
        top: r.top + o.y, bottom: r.bottom + o.y, left: r.left + o.x, right: r.right + o.x};
    };
    const scrollerRectOf = node => (isFrameDocRoot(node) ? rectOf(node.ownerDocument.defaultView.frameElement) : rectOf(node));
    if (!frameOffset(el))
      return {viewport, targetRect: null};
    let target = rectOf(el);
    if (rect && rect.width >= 0 && rect.height >= 0) {
      const left = target.left + rect.x;
      const top = target.top + rect.y;
      target = {x: left, y: top, width: rect.width, height: rect.height, left, top, right: left + rect.width, bottom: top + rect.height};
    }
    if (!target.width && !target.height && !el.getClientRects().length)
      return {viewport, targetRect: null};

    // Scrollable ancestors, innermost first. A top-document position:fixed
    // ancestor pins the target: nothing above it, the page included, moves it.
    const chain = [];
    let pageCanMove = true;
    for (let cur = stepUp(el), depth = 0; cur && depth < 60 && cur !== topDoc.documentElement; depth++) {
      if (isFrameDocRoot(cur)) {
        if (cur.scrollHeight > cur.ownerDocument.defaultView.innerHeight + 1)
          chain.push(cur);
        cur = stepUp(cur);
        continue;
      }
      const st = styleOf(cur);
      const scrollable = cur.scrollHeight > cur.clientHeight + 1 && (st.overflowY === 'scroll' || st.overflowY === 'auto');
      if (cur === cur.ownerDocument.body) {
        // The body scrolls only when its document does not.
        if (scrollable && !(cur.ownerDocument.documentElement.scrollHeight > cur.ownerDocument.defaultView.innerHeight + 10))
          chain.push(cur);
        if (cur === topDoc.body)
          break;
        cur = stepUp(cur);
        continue;
      }
      if (scrollable)
        chain.push(cur);
      if (st.position === 'fixed') {
        if (cur.ownerDocument === topDoc) {
          pageCanMove = false;
          break;
        }
        cur = cur.ownerDocument.defaultView.frameElement;
        continue;
      }
      cur = stepUp(cur);
    }

    // elementFromPoint, descending into same-process frames.
    const hitAt = (x, y) => {
      let hit = topDoc.elementFromPoint(x, y);
      while (hit && (hit.tagName === 'IFRAME' || hit.tagName === 'FRAME') && hit.contentDocument) {
        const fr = hit.getBoundingClientRect();
        x -= fr.x + hit.clientLeft;
        y -= fr.y + hit.clientTop;
        const next = hit.contentDocument.elementFromPoint(x, y);
        if (!next)
          break;
        hit = next;
      }
      return hit;
    };
    const containsDeep = (ancestor, node) => {
      for (let n = node; n; n = stepUp(n)) {
        if (n === ancestor)
          return true;
      }
      return false;
    };
    // The pinned element covering a point, if any: the nearest fixed/sticky
    // ancestor of what is hit there, unless it is the target, inside it, or
    // one of its ancestors. Only pinned elements count: anything that scrolls
    // with the target cannot be scrolled out from over it.
    const pinnedAt = (x, y) => {
      const hit = hitAt(x, y);
      if (!hit || containsDeep(el, hit) || containsDeep(hit, el))
        return null;
      for (let n = hit; n && n !== topDoc.body && n !== topDoc.documentElement; n = stepUp(n)) {
        if (isFrameDocRoot(n) || n === n.ownerDocument.body)
          continue;
        const position = styleOf(n).position;
        if (position === 'fixed' || position === 'sticky')
          return containsDeep(n, el) ? null : rectOf(n);
      }
      return null;
    };

    // The band left clear by pinned bars at the target's column, stacked bars included.
    let clearTop = kMargin;
    let clearBottom = vh - kMargin;
    const columnX = Math.min(Math.max(target.left + target.width / 2, 5), vw - 5);
    for (let i = 0; i < 4; i++) {
      const bar = pinnedAt(columnX, clearTop + 1);
      if (!bar || bar.bottom <= clearTop)
        break;
      clearTop = Math.min(bar.bottom + 2, vh);
    }
    for (let i = 0; i < 4; i++) {
      const bar = pinnedAt(columnX, clearBottom - 1);
      if (!bar || bar.top >= clearBottom)
        break;
      clearBottom = Math.max(bar.top - 2, 0);
    }
    if (clearBottom - clearTop < 40) {
      // A full-screen overlay: keep the plain band; hit-testing still reports it.
      clearTop = kMargin;
      clearBottom = vh - kMargin;
    }

    const clip = {top: clearTop, bottom: clearBottom, left: kEdge, right: vw - kEdge};
    for (const c of chain) {
      const r = scrollerRectOf(c);
      clip.top = Math.max(clip.top, r.top);
      clip.bottom = Math.min(clip.bottom, r.bottom);
      clip.left = Math.max(clip.left, r.left);
      clip.right = Math.min(clip.right, r.right);
    }
    const regionLeft = Math.max(target.left, clip.left);
    const regionTop = Math.max(target.top, clip.top);
    const regionRight = Math.min(target.right, clip.right);
    const regionBottom = Math.min(target.bottom, clip.bottom);
    const region = regionRight - regionLeft >= 6 && regionBottom - regionTop >= 6
      ? {x: regionLeft, y: regionTop, width: regionRight - regionLeft, height: regionBottom - regionTop}
      : null;
    let occluder = null;
    if (region) {
      const cx = region.x + region.width / 2;
      const cy = region.y + region.height / 2;
      for (const [px, py] of [[cx, cy], [cx - region.width * 0.3, cy], [cx + region.width * 0.3, cy],
                              [cx, cy - region.height * 0.3], [cx, cy + region.height * 0.3]]) {
        const bar = pinnedAt(Math.round(px), Math.round(py));
        if (bar) {
          occluder = {rect: bar};
          break;
        }
      }
    }

    const fromX = Number.isFinite(from?.x) ? from.x : vw / 2;
    const fromY = Number.isFinite(from?.y) ? from.y : vh / 2;
    const scrollers = [];
    const nodes = pageCanMove ? [...chain, null] : chain;
    for (let i = 0; i < nodes.length; i++) {
      const node = nodes[i];
      const isPage = node === null;
      const band = {top: clearTop, bottom: clearBottom, left: 5, right: vw - 5};
      if (!isPage) {
        for (const c of chain.slice(i)) {
          const r = scrollerRectOf(c);
          band.top = Math.max(band.top, r.top);
          band.bottom = Math.min(band.bottom, r.bottom);
          band.left = Math.max(band.left, r.left);
          band.right = Math.min(band.right, r.right);
        }
      }
      const frameWin = !isPage && isFrameDocRoot(node) ? node.ownerDocument.defaultView : null;
      const scrollTop = isPage ? topWin.scrollY : frameWin ? frameWin.scrollY : node.scrollTop;
      const maxScroll = isPage ? Math.max(0, topDoc.documentElement.scrollHeight - vh)
        : frameWin ? Math.max(0, node.scrollHeight - frameWin.innerHeight)
        : Math.max(0, node.scrollHeight - node.clientHeight);

      // A wheel is consumed by the nearest ancestor of what it lands on that can
      // still move in its direction.
      const consumes = (n, down) => {
        if (isFrameDocRoot(n)) {
          const w = n.ownerDocument.defaultView;
          return down ? w.scrollY + w.innerHeight < n.scrollHeight - 1 : w.scrollY > 1;
        }
        const st = styleOf(n);
        if ((st.overflowY !== 'auto' && st.overflowY !== 'scroll') || n.scrollHeight <= n.clientHeight + 1)
          return false;
        return down ? n.scrollTop + n.clientHeight < n.scrollHeight - 1 : n.scrollTop > 1;
      };
      const reaches = (x, y, down) => {
        let n = hitAt(x, y);
        if (!n)
          return isPage;
        for (; n && n !== topDoc.documentElement && n !== topDoc.body; n = stepUp(n)) {
          if (n === node)
            return true;
          if (consumes(n, down))
            return false;
        }
        return isPage;
      };
      const clampX = x => Math.min(Math.max(x, Math.max(band.left + 5, 5)), Math.min(band.right - 5, vw - 5));
      const clampY = y => Math.min(Math.max(y, Math.max(band.top + 5, 5)), Math.min(band.bottom - 5, vh - 5));
      // Nearest first: sideways toward the roomier gutter, then up and down.
      const roomLeft = fromX - Math.max(band.left + 5, 5);
      const roomRight = Math.min(band.right - 5, vw - 5) - fromX;
      const lateral = roomRight > roomLeft ? [0, 60, -60, 120, -120, 200, -200] : [0, -60, 60, -120, 120, -200, 200];
      const pointFor = down => {
        for (const dy of [0, -40, 40, -90, 90]) {
          for (const dx of lateral) {
            const point = {x: clampX(fromX + dx), y: clampY(fromY + dy)};
            if (reaches(point.x, point.y, down))
              return point;
          }
        }
        return {x: clampX(fromX), y: clampY(fromY)};
      };
      scrollers.push({isPage, rect: isPage ? null : scrollerRectOf(node), band, scrollTop, maxScroll,
        wheelPoint: {down: pointFor(true), up: pointFor(false)}});
    }

    return {viewport, targetRect: target, clip, region, hitTestable: !!region && !occluder, occluder, scrollers};
  }

  // Camoufox: text a driver inserts (fill, keyboard.insertText) arrives typed,
  // as a person enters it (docs/input-dispatch.md). A character with a key on
  // the US layout is pressed through _dispatchKeyEvent, so its key fields and
  // Shift are keyboard.type's; one without (é, 嗨) is inserted as before.
  async _insertText({text}) {
    const frame = this._frameTree.mainFrame();
    const tip = frame.textInputProcessor();
    const pace = new TypingPace();
    let held = null;
    let nextDownAt = ChromeUtils.now();
    const release = async () => {
      if (!held)
        return;
      await until(held.upAt);
      await this._dispatchKeyEvent({type: 'keyup', ...held.key});
      held = null;
    };
    for (const ch of text) {
      const key = this._usKey(tip, frame, ch);
      if (!key) {
        await release();
        this._insertWithoutKey(frame, ch);
        continue;
      }
      const shifted = this._needsShift(ch);
      // Rollover (the next key down before this one is up) only between
      // unshifted keys: Shift is pressed and released around its own key.
      if (held && (shifted || held.shifted || held.upAt <= nextDownAt))
        await release();
      await until(nextDownAt);
      await this._dispatchKeyEvent({type: 'keydown', ...key, text: key.key.length === 1 ? ch : undefined});
      const downAt = ChromeUtils.now();
      await release();
      held = {key, shifted, upAt: downAt + pace.hold()};
      nextDownAt = downAt + pace.interval();
    }
    await release();
  }

  // The key that types `ch` on a US layout, or null. A line break is Enter
  // where Enter types one (a textarea, an editable element).
  _usKey(tip, frame, ch) {
    if (ch === '\n') {
      const el = frame.domWindow().document.activeElement;
      const multiline = el && (el.localName === 'textarea' || el.isContentEditable);
      return multiline ? {key: 'Enter', code: 'Enter', keyCode: 13, location: 0, repeat: false} : null;
    }
    const code = tip.guessCodeValueOfPrintableKeyInUSEnglishKeyboardLayout(ch);
    if (!code)
      return null;
    const keyCode = tip.guessKeyCodeValueOfPrintableKeyInUSEnglishKeyboardLayout(ch);
    return {key: ch, code, keyCode, location: 0, repeat: false};
  }

  _insertWithoutKey(frame, text) {
    // A focused text control inserts through its own editor: one
    // beforeinput/input pair, maxlength applies, and the value counts as
    // user-edited so blur fires `change`. nsITextInputProcessor would fire
    // `input` twice there (compositionupdate and compositionend).
    const editor = frame.domWindow().document.activeElement?.editor;
    if (editor) {
      editor.insertText(text);
      return;
    }
    frame.textInputProcessor().commitCompositionWith(text);
  }

  async _crash() {
    dump(`Crashing intentionally\n`);
    // This is to intentionally crash the frame.
    // We crash by using js-ctypes and dereferencing
    // a bad pointer. The crash should happen immediately
    // upon loading this frame script.
    const { ctypes } = ChromeUtils.importESModule('resource://gre/modules/ctypes.sys.mjs');
    ChromeUtils.privateNoteIntentionalCrash();
    const zero = new ctypes.intptr_t(8);
    const badptr = ctypes.cast(zero, ctypes.PointerType(ctypes.int32_t));
    badptr.contents;
  }

  async _getFullAXTree({objectId}) {
    let unsafeObject = null;
    if (objectId) {
      unsafeObject = this._frameTree.mainFrame().unsafeObject(objectId);
      if (!unsafeObject)
        throw new Error(`No object found for id "${objectId}"`);
    }

    const service = Cc["@mozilla.org/accessibilityService;1"]
      .getService(Ci.nsIAccessibilityService);
    const document = this._frameTree.mainFrame().domWindow().document;
    const docAcc = service.getAccessibleFor(document);

    while (docAcc.document.isUpdatePendingForJugglerAccessibility)
      await new Promise(x => this._frameTree.mainFrame().domWindow().requestAnimationFrame(x));

    async function waitForQuiet() {
      let state = {};
      docAcc.getState(state, {});
      if ((state.value & Ci.nsIAccessibleStates.STATE_BUSY) == 0)
        return;
      let resolve, reject;
      const promise = new Promise((x, y) => {resolve = x, reject = y});
      let eventObserver = {
        observe(subject, topic) {
          if (topic !== "accessible-event") {
            return;
          }

          // If event type does not match expected type, skip the event.
          let event = subject.QueryInterface(Ci.nsIAccessibleEvent);
          if (event.eventType !== Ci.nsIAccessibleEvent.EVENT_STATE_CHANGE) {
            return;
          }

          // If event's accessible does not match expected accessible,
          // skip the event.
          if (event.accessible !== docAcc) {
            return;
          }

          Services.obs.removeObserver(this, "accessible-event");
          resolve();
        },
      };
      Services.obs.addObserver(eventObserver, "accessible-event");
      return promise;
    }
    function buildNode(accElement) {
      let a = {}, b = {};
      accElement.getState(a, b);
      const tree = {
        role: service.getStringRole(accElement.role),
        name: accElement.name || '',
      };
      if (unsafeObject && unsafeObject === accElement.DOMNode)
        tree.foundObject = true;
      for (const userStringProperty of [
        'value',
        'description'
      ]) {
        tree[userStringProperty] = accElement[userStringProperty] || undefined;
      }

      const states = {};
      for (const name of service.getStringStates(a.value, b.value))
        states[name] = true;
      for (const name of ['selected',
        'focused',
        'pressed',
        'focusable',
        'required',
        'invalid',
        'modal',
        'editable',
        'busy',
        'checked',
        'multiselectable']) {
        if (states[name])
          tree[name] = true;
      }

      if (states['multi line'])
        tree['multiline'] = true;
      if (states['editable'] && states['readonly'])
        tree['readonly'] = true;
      if (states['checked'])
        tree['checked'] = true;
      if (states['mixed'])
        tree['checked'] = 'mixed';
      if (states['expanded'])
        tree['expanded'] = true;
      else if (states['collapsed'])
        tree['expanded'] = false;
      if (!states['enabled'])
        tree['disabled'] = true;

      const attributes = {};
      if (accElement.attributes) {
        for (const { key, value } of accElement.attributes.enumerate()) {
          attributes[key] = value;
        }
      }
      for (const numericalProperty of ['level']) {
        if (numericalProperty in attributes)
          tree[numericalProperty] = parseFloat(attributes[numericalProperty]);
      }
      for (const stringProperty of ['tag', 'roledescription', 'valuetext', 'orientation', 'autocomplete', 'keyshortcuts', 'haspopup']) {
        if (stringProperty in attributes)
          tree[stringProperty] = attributes[stringProperty];
      }
      const children = [];

      for (let child = accElement.firstChild; child; child = child.nextSibling) {
        children.push(buildNode(child));
      }
      if (children.length)
        tree.children = children;
      return tree;
    }
    await waitForQuiet();
    return {
      tree: buildNode(docAcc)
    };
  }
}

function until(time) {
  const ms = time - ChromeUtils.now();
  return ms > 0 ? new Promise(resolve => setTimeout(resolve, ms)) : null;
}

function normal() {
  return Math.sqrt(-2 * Math.log(1 - Math.random())) * Math.cos(2 * Math.PI * Math.random());
}

// A typist's pace, drawn per call from Dhakal et al., "Observations on Typing
// from 136 Million Keystrokes" (CHI 2018, 168,000 typists): the typist's mean
// inter-key interval from the population's (238.66 ms, SD 111.6, lognormal,
// floor 60 ms), keys held 116.25 ms (SD 23.88). The spread of one typist's
// intervals around their own mean is not in the paper; it is taken as 35%.
class TypingPace {
  constructor() {
    const sigma = Math.sqrt(Math.log(1 + (111.6 / 238.66) ** 2));
    this._mean = Math.max(60, 238.66 * Math.exp(sigma * normal() - sigma * sigma / 2));
  }

  interval() {
    return Math.max(60, this._mean * Math.exp(0.35 * normal() - 0.35 * 0.35 / 2));
  }

  hold() {
    return Math.min(250, Math.max(50, 116.25 + 23.88 * normal()));
  }
}
