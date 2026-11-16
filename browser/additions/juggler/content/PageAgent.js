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
const {normalDelay} = ChromeUtils.importESModule('resource://gre/modules/juggler/input/HumanDelay.js');

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
      await pause(modifierLead());
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
        await pause(modifierTrail());
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

  async _insertText({text}) {
    if (!text)
      return;
    const win = this._frameTree.mainFrame().domWindow();
    // The shortcut reaches the document that holds focus, perhaps a frame's;
    // this handler hears every frame in the process.
    const events = win.docShell.chromeEventHandler;
    const mac = win.navigator.platform.startsWith('Mac');
    const modifier = mac
      ? {key: 'Meta', code: 'MetaLeft', keyCode: 224, location: 1, repeat: false}
      : {key: 'Control', code: 'ControlLeft', keyCode: 17, location: 1, repeat: false};
    const v = {key: 'v', code: 'KeyV', keyCode: 86, location: 0, repeat: false};
    const field = focusedField(win);
    const editor = field && fieldEditor(field);
    const before = editor && fieldText(field);
    let error = null;
    // The shortcut's keypress is where Firefox runs its own clipboard paste
    // (GTK's key bindings, the global key handler). Content never gets a
    // keypress for a shortcut, so cancelling it in the system group is
    // invisible; the paste with the text runs in its place, at that moment.
    const onKeypress = event => {
      if (!event.isTrusted || event.key !== 'v' || !(mac ? event.metaKey : event.ctrlKey))
        return;
      event.preventDefault();
      if (!editor)
        return;
      try {
        editor.pasteTransferable(textTransferable(win, text));
      } catch (e) {
        error = e;
      }
    };
    events.addEventListener('keypress', onKeypress, {capture: true, mozSystemGroup: true});
    try {
      // The modifier leads and trails V as Shift does a key (_dispatchKeyEvent).
      await this._dispatchKeyEvent({type: 'keydown', ...modifier});
      await pause(modifierLead());
      await this._dispatchKeyEvent({type: 'keydown', ...v});
      await pause(keyHold());
      await this._dispatchKeyEvent({type: 'keyup', ...v});
      await pause(modifierTrail());
      await this._dispatchKeyEvent({type: 'keyup', ...modifier});
    } finally {
      events.removeEventListener('keypress', onKeypress, {capture: true, mozSystemGroup: true});
    }
    if (error)
      throw error;
    if (!editor || field.readOnly)
      return;
    // A page that cancels the paste may have put the text in itself: only a
    // field left as it was refused it. A person types what they cannot paste.
    if (pasted(field, before, text))
      return;
    await this._typeText(text, field);
    if (fieldText(field) === before)
      throw new Error('Cannot insert text: the page refused the paste and the keys');
  }

  // Key by key on a US keyboard, at a person's rate. A character it has no key
  // for arrives as an input method commits it.
  async _typeText(text, field) {
    for (const character of text) {
      // Keys sent on would land in whatever took the focus.
      if (focusedField(this._frameTree.mainFrame().domWindow()) !== field)
        throw new Error('Cannot insert text: the field lost focus while it was being typed into');
      const key = {...(usKey(character) ?? {key: 'Process', code: '', keyCode: 229}), location: 0, repeat: false};
      const started = ChromeUtils.now();
      await this._dispatchKeyEvent({type: 'keydown', ...key, text: character});
      await pause(keyHold());
      await this._dispatchKeyEvent({type: 'keyup', ...key});
      // Timer.sys.mjs reads a negative delay as a huge unsigned one.
      await pause(Math.max(0, started + keyInterval() - ChromeUtils.now()));
    }
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

function pause(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// How long a person holds a key: 116.25 ms (SD 23.88; Dhakal et al.,
// "Observations on Typing from 136 Million Keystrokes", CHI 2018), never under
// 50 ms.
const keyHold = () => normalDelay(116.25, 23.88, 50);
// Press to press while typing, from the same study: 238.66 ms, SD 111.60.
const keyInterval = () => normalDelay(238.66, 111.6, 80);
// How far a modifier leads the key it modifies, and trails its release: tens
// of ms. No recorded figure; these keep the mean and spread of the uniform
// 35-90 ms and 20-65 ms draws they replaced, with those floors.
const modifierLead = () => normalDelay(62.5, 16, 35);
const modifierTrail = () => normalDelay(42.5, 13, 20);

// What has focus in this page, frames included. Services.focus.focusedElement
// is the active window's: in a process shared with another page, that page's.
// A designMode document takes the focus itself, with no element in it.
function focusedField(win) {
  const focused = {};
  const element = Services.focus.getFocusedElementForWindow(win, true, focused);
  const doc = focused.value?.document;
  return element ?? (doc?.designMode === 'on' ? doc.body : null);
}

// The editor of a focused text control or editable document, or null.
function fieldEditor(element) {
  if (element.editor)
    return element.editor;
  const doc = element.ownerDocument;
  if (!element.isContentEditable && doc.designMode !== 'on')
    return null;
  return doc.defaultView.docShell.editingSession.getEditorForWindow(doc.defaultView);
}

function fieldText(element) {
  return element.editor ? element.value : element.textContent;
}

// Filling a field with what it holds changes nothing, and is still done.
function pasted(field, before, text) {
  const after = fieldText(field);
  return after !== before || after === text;
}

const kUsRows = [
  ['`~', 'Backquote', 192], ['-_', 'Minus', 173], ['=+', 'Equal', 61],
  ['[{', 'BracketLeft', 219], [']}', 'BracketRight', 221], ['\\|', 'Backslash', 220],
  [';:', 'Semicolon', 59], ['\'"', 'Quote', 222], [',<', 'Comma', 188],
  ['.>', 'Period', 190], ['/?', 'Slash', 191], [' ', 'Space', 32],
];
const kDigitShifts = ')!@#$%^&*(';

// The key a US keyboard types this character with, or null.
function usKey(character) {
  if (/^[a-zA-Z]$/.test(character)) {
    const upper = character.toUpperCase();
    return {key: character, code: `Key${upper}`, keyCode: upper.charCodeAt(0)};
  }
  const digit = /^[0-9]$/.test(character) ? Number(character) : kDigitShifts.indexOf(character);
  if (digit >= 0)
    return {key: character, code: `Digit${digit}`, keyCode: 48 + digit};
  const row = kUsRows.find(([characters]) => characters.includes(character));
  return row ? {key: character, code: row[1], keyCode: row[2]} : null;
}

// Plain text to paste, as a text source puts it on the clipboard.
function textTransferable(win, text) {
  const transferable = Cc['@mozilla.org/widget/transferable;1'].createInstance(Ci.nsITransferable);
  transferable.init(win.docShell.QueryInterface(Ci.nsILoadContext));
  transferable.addDataFlavor('text/plain');
  const data = Cc['@mozilla.org/supports-string;1'].createInstance(Ci.nsISupportsString);
  data.data = text;
  transferable.setTransferData('text/plain', data);
  return transferable;
}
