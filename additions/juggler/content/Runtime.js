/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";
// Note: this file should be loadabale with eval() into worker environment.
// Avoid Components.*, ChromeUtils and global const variables.

if (!this.Debugger) {
  // Worker has a Debugger defined already.
  const {addDebuggerToGlobal} = ChromeUtils.importESModule("resource://gre/modules/jsdebugger.sys.mjs");
  addDebuggerToGlobal(Components.utils.getGlobalForObject(globalThis));
}

let lastId = 0;
function generateId() {
  return 'id-' + (++lastId);
}

const consoleLevelToProtocolType = {
  'dir': 'dir',
  'log': 'log',
  'debug': 'debug',
  'info': 'info',
  'error': 'error',
  'warn': 'warning',
  'dirxml': 'dirxml',
  'table': 'table',
  'trace': 'trace',
  'clear': 'clear',
  'group': 'startGroup',
  'groupCollapsed': 'startGroupCollapsed',
  'groupEnd': 'endGroup',
  'assert': 'assert',
  'profile': 'profile',
  'profileEnd': 'profileEnd',
  'count': 'count',
  'countReset': 'countReset',
  'time': null,
  'timeLog': 'timeLog',
  'timeEnd': 'timeEnd',
  'timeStamp': 'timeStamp',
};

const disallowedMessageCategories = new Set([
  'XPConnect JavaScript',
  'component javascript',
  'chrome javascript',
  'chrome registration',
  'XBL',
  'XBL Prototype Handler',
  'XBL Content Sink',
  'xbl javascript',
]);

// Camoufox: does this Runtime.callFunction carry a `mw:`-prefixed script?
//
// The typeof guard matters: Runtime.js is also eval'd into worker globals,
// where ChromeUtils does not exist, and worker evaluation must not trip over
// the main-world path at all.
// Camoufox: report a bad `mw:` request the way an in-page exception is
// reported, so the message survives Playwright's error rewriting.
function mainWorldFailure(text) {
  return {exceptionDetails: {text}};
}

function isMainWorldRequest(functionDeclaration, args) {
  return typeof ChromeUtils !== 'undefined' &&
      functionDeclaration.includes('utilityScript.evaluate') &&
      args.length > 4 &&
      typeof args[3].value === 'string' &&
      args[3].value.startsWith('mw:');
}

// Camoufox: the main-world half of the `mw:` escape hatch -- a standalone
// equivalent of Playwright's utilityScript.evaluate, compiled inside the page's
// own global.
//
// It has to be a re-implementation rather than a call into Playwright's utility
// script: that script only exists in the worlds Playwright created, and the
// page's real global is deliberately not one of them. The wire format is the
// contract, so this mirrors utilityScript.evaluate and the call-argument
// serializers exactly -- arguments arrive in Playwright's serialized form and
// the result has to go back in it, or the client would misread a returned
// object such as {a: 1} as a serialized array.
//
// Everything here resolves through the page's globals (eval, Object, JSON,
// Array...), so a hostile page can observe or poison main-world evaluation.
// That is inherent to running there and is exactly why the default world is
// isolated and this path is opt-in.
//
// It is written as a real function and stringified at the bottom rather than
// authored as a template literal, so SpiderMonkey parses it when Runtime.js
// loads. A syntax error is then a startup failure instead of a first-`mw:`-call
// failure -- which matters here more than usual, because Playwright rewrites
// callFunction protocol errors into "Execution context was destroyed", so a bad
// wrapper surfaces as a phantom navigation rather than as a syntax error (#631).
// Nothing in the body may close over Runtime.js scope: only the source text
// crosses into the page, and the page's global is where every name resolves.
function mainWorldEvaluate(isFunction, returnByValue, expression, argCount, ...argsAndHandles) {
  const typedArrays = {
    i8: Int8Array, ui8: Uint8Array, ui8c: Uint8ClampedArray,
    i16: Int16Array, ui16: Uint16Array,
    i32: Int32Array, ui32: Uint32Array,
    f32: Float32Array, f64: Float64Array,
    bi64: BigInt64Array, bui64: BigUint64Array,
  };
  const tagged = (value, name) => {
    try {
      return Object.prototype.toString.call(value) === '[object ' + name + ']';
    } catch (e) {
      return false;
    }
  };

  const parse = (value, refs) => {
    if (Object.is(value, undefined))
      return undefined;
    if (typeof value === 'object' && value) {
      if ('ref' in value)
        return refs.get(value.ref);
      if ('v' in value) {
        if (value.v === 'undefined') return undefined;
        if (value.v === 'null') return null;
        if (value.v === 'NaN') return NaN;
        if (value.v === 'Infinity') return Infinity;
        if (value.v === '-Infinity') return -Infinity;
        if (value.v === '-0') return -0;
        return undefined;
      }
      if ('d' in value)
        return new Date(value.d);
      if ('u' in value)
        return new URL(value.u);
      if ('bi' in value)
        return BigInt(value.bi);
      if ('e' in value) {
        const error = new Error(value.e.m);
        error.name = value.e.n;
        error.stack = value.e.s;
        return error;
      }
      if ('r' in value)
        return new RegExp(value.r.p, value.r.f);
      if ('a' in value) {
        const result = [];
        refs.set(value.id, result);
        for (const item of value.a)
          result.push(parse(item, refs));
        return result;
      }
      if ('o' in value) {
        const result = {};
        refs.set(value.id, result);
        for (const {k, v} of value.o) {
          if (k === '__proto__')
            continue;
          result[k] = parse(v, refs);
        }
        return result;
      }
      if ('h' in value)
        throw new Error('Main world evaluation cannot accept element or JS handles as arguments.');
      if ('ta' in value) {
        const binary = atob(value.ta.b);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++)
          bytes[i] = binary.charCodeAt(i);
        return new typedArrays[value.ta.k](bytes.buffer);
      }
    }
    return value;
  };

  const serialize = (value, visited) => {
    if (value && typeof value === 'object') {
      if (typeof Window === 'function' && value instanceof Window)
        return 'ref: <Window>';
      if (typeof Document === 'function' && value instanceof Document)
        return 'ref: <Document>';
      if (typeof Node === 'function' && value instanceof Node)
        return 'ref: <Node>';
    }
    if (typeof value === 'symbol')
      return {v: 'undefined'};
    if (Object.is(value, undefined))
      return {v: 'undefined'};
    if (Object.is(value, null))
      return {v: 'null'};
    if (Object.is(value, NaN))
      return {v: 'NaN'};
    if (Object.is(value, Infinity))
      return {v: 'Infinity'};
    if (Object.is(value, -Infinity))
      return {v: '-Infinity'};
    if (Object.is(value, -0))
      return {v: '-0'};
    if (typeof value === 'boolean' || typeof value === 'number' || typeof value === 'string')
      return value;
    if (typeof value === 'bigint')
      return {bi: value.toString()};
    if (value instanceof Error || tagged(value, 'Error')) {
      const header = value.name + ': ' + value.message;
      const stack = value.stack && value.stack.startsWith(header) ? value.stack : header + '\n' + value.stack;
      return {e: {n: value.name, m: value.message, s: stack}};
    }
    if (value instanceof Date || tagged(value, 'Date'))
      return {d: value.toJSON()};
    if (value instanceof URL || tagged(value, 'URL'))
      return {u: value.toJSON()};
    if (value instanceof RegExp || tagged(value, 'RegExp'))
      return {r: {p: value.source, f: value.flags}};
    for (const kind of Object.keys(typedArrays)) {
      if (value instanceof typedArrays[kind]) {
        const bytes = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
        let binary = '';
        for (const byte of bytes)
          binary += String.fromCharCode(byte);
        return {ta: {b: btoa(binary), k: kind}};
      }
    }
    const seen = visited.ids.get(value);
    if (seen)
      return {ref: seen};
    if (Array.isArray(value)) {
      const id = ++visited.lastId;
      visited.ids.set(value, id);
      const a = [];
      for (let i = 0; i < value.length; ++i)
        a.push(serialize(value[i], visited));
      return {a, id};
    }
    if (typeof value === 'object') {
      const id = ++visited.lastId;
      visited.ids.set(value, id);
      const o = [];
      for (const name of Object.keys(value)) {
        let item;
        try {
          item = value[name];
        } catch (e) {
          continue;
        }
        if (name === 'toJSON' && typeof item === 'function')
          o.push({k: name, v: {o: [], id: 0}});
        else
          o.push({k: name, v: serialize(item, visited)});
      }
      if (!o.length) {
        try {
          if (typeof value.toJSON === 'function')
            return serialize(value.toJSON(), visited);
        } catch (e) {
        }
      }
      return {o, id};
    }
    // Functions and anything else without a representation.
    return undefined;
  };

  const jsonValue = value => {
    if (value === undefined)
      return undefined;
    try {
      return serialize(value, {ids: new Map(), lastId: 0});
    } catch (e) {
      return undefined;
    }
  };

  const parameters = argsAndHandles.slice(0, argCount).map(arg => parse(arg, new Map()));
  // Indirect eval, so the page sees a plain global-scope evaluation and this
  // function's own locals stay out of the evaluated script's scope. Statements
  // ("if (x) { ... }") evaluate to their completion value, same as Playwright.
  let result = (0, eval)(expression);
  if (isFunction === true)
    result = result(...parameters);
  else if (isFunction !== false && typeof result === 'function')
    result = result(...parameters);
  if (result && typeof result.then === 'function')
    return result.then(jsonValue);
  return jsonValue(result);
}

// evaluateFunction() compiles this with `executeInGlobal('(' + text + ')')`, so
// what gets evaluated is a function *expression*, and its binding never reaches
// the page global either way.
//
// The name is dropped on the way out regardless. A named function expression
// puts its name on every stack frame it appears in, and a page that throws
// inside page.evaluate() can read those frames back off error.stack -- so
// keeping it would hand a detector the literal string "mainWorldEvaluate".
// Anonymous is what the page saw before this was a real function, so keep it
// that way. Verified: with the name stripped, output is identical to the
// previous template-literal wrapper, stack frames included.
const MAIN_WORLD_EVALUATE = mainWorldEvaluate.toString().replace(/^function mainWorldEvaluate/, 'function');

class Runtime {
  constructor(isWorker = false) {
    this._debugger = new Debugger();
    // Keep the debuggee realm indistinguishable from one with no debugger
    // attached: without this, having Juggler attached is equivalent to having
    // DevTools open as far as content-visible behaviour is concerned (async
    // stack capture, throw-site stack capture, deoptimized asm.js/wasm).
    this._debugger.invisibleToContent = true;
    this._pendingPromises = new Map();
    this._executionContexts = new Map();
    this._windowToExecutionContext = new Map();
    this._eventListeners = [];
    if (isWorker) {
      this._registerWorkerConsoleHandler();
    } else {
      this._registerConsoleServiceListener(Services);
      this._registerConsoleAPIListener(Services);
    }
    // We can't use event listener here to be compatible with Worker Global Context.
    // Use plain callbacks instead.
    this.events = {
      onConsoleMessage: createEvent(),
      onRuntimeError: createEvent(),
      onErrorFromWorker: createEvent(),
      onExecutionContextCreated: createEvent(),
      onExecutionContextDestroyed: createEvent(),
      onBindingCalled: createEvent(),
    };
  }

  executionContexts() {
    return [...this._executionContexts.values()];
  }

  async evaluate({executionContextId, expression, returnByValue}) {
    const executionContext = this.findExecutionContext(executionContextId);
    if (!executionContext)
      throw new Error('Failed to find execution context with id = ' + executionContextId);
    const exceptionDetails = {};
    let result = await executionContext.evaluateScript(expression, exceptionDetails);
    if (!result)
      return {exceptionDetails};
    if (returnByValue)
      result = executionContext.ensureSerializedToValue(result);
    return {result};
  }

  async callFunction({executionContextId, functionDeclaration, args, returnByValue}) {
    const executionContext = this.findExecutionContext(executionContextId);
    if (!executionContext)
      throw new Error('Failed to find execution context with id = ' + executionContextId);

    // Camoufox: page.evaluate() runs in an isolated world (see FrameTree.js), so
    // page JS state is invisible to it. `page.evaluate('mw:' + script)` is the
    // opt-in escape hatch that runs `script` in the page's own global instead.
    //
    // Playwright hands every evaluation to its utility script as
    // `(utilityScript, ...args) => utilityScript.evaluate(...args)` with
    // args = [utilityScript, isFunction, returnByValue, expression, argCount,
    // ...callArgs]; the prefix is spotted on the expression and the rest of the
    // call is replayed against the main world, so an unprefixed script is
    // untouched by any of this.
    //
    // Anything wrong with the request has to come back as exceptionDetails
    // rather than as a thrown protocol error: Playwright rewrites every
    // callFunction protocol error to "Execution context was destroyed, most
    // likely because of a navigation" (ffExecutionContext.js rewriteError), so a
    // thrown message never reaches the caller. That rewrite is also what made
    // #631 so hard to read -- a syntax error in the old main-world wrapper
    // surfaced as a phantom navigation.
    if (isMainWorldRequest(functionDeclaration, args)) {
      if (!ChromeUtils.camouGetBool('allowMainWorld', false))
        return mainWorldFailure('Main world evaluation is disabled. Launch with main_world_eval=True to use the "mw:" prefix.');
      if (!returnByValue)
        return mainWorldFailure('Main world evaluation cannot return a handle; use page.evaluate() rather than page.evaluate_handle().');
      const mainWorldContext = executionContext.mainWorldContext();
      if (!mainWorldContext)
        return mainWorldFailure('Main world evaluation is only available in the page\'s main execution context.');
      ChromeUtils.camouDebug(`Evaluating in main world: ${args[3].value}`);
      // Replay Playwright's own call shape, minus the utility script handle and
      // minus the prefix. Handles cannot cross the compartment boundary.
      const mainWorldArgs = args.slice(1);
      if (mainWorldArgs.some(arg => arg.objectId))
        return mainWorldFailure('Main world evaluation cannot accept element or JS handles as arguments.');
      mainWorldArgs[2] = {value: args[3].value.substring(3)};
      const exceptionDetails = {};
      const result = await mainWorldContext.evaluateFunction(MAIN_WORLD_EVALUATE, mainWorldArgs, exceptionDetails);
      if (!result)
        return {exceptionDetails};
      return {result: mainWorldContext.ensureSerializedToValue(result)};
    }

    const exceptionDetails = {};
    let result = await executionContext.evaluateFunction(functionDeclaration, args, exceptionDetails);
    if (!result)
      return {exceptionDetails};
    if (returnByValue)
      result = executionContext.ensureSerializedToValue(result);
    return {result};
  }

  async getObjectProperties({executionContextId, objectId}) {
    const executionContext = this.findExecutionContext(executionContextId);
    if (!executionContext)
      throw new Error('Failed to find execution context with id = ' + executionContextId);
    return {properties: executionContext.getObjectProperties(objectId)};
  }

  async disposeObject({executionContextId, objectId}) {
    const executionContext = this.findExecutionContext(executionContextId);
    if (!executionContext)
      throw new Error('Failed to find execution context with id = ' + executionContextId);
    return executionContext.disposeObject(objectId);
  }

  _registerConsoleServiceListener(Services) {
    const Ci = Components.interfaces;
    const consoleServiceListener = {
      QueryInterface: ChromeUtils.generateQI([Ci.nsIConsoleListener]),

      observe: message => {
        if (!(message instanceof Ci.nsIScriptError) || !message.outerWindowID ||
            !message.category || disallowedMessageCategories.has(message.category)) {
          return;
        }
        const errorWindow = Services.wm.getOuterWindowWithId(message.outerWindowID);
        const errorLocation = {
          lineNumber: message.lineNumber - 1,
          columnNumber: message.columnNumber - 1,
          url: message.sourceName,
        };
        if (message.category === 'Web Worker' && message.logLevel === Ci.nsIConsoleMessage.error) {
          emitEvent(this.events.onErrorFromWorker, errorWindow, message.message, '' + message.stack, errorLocation);
          return;
        }
        const executionContext = this._windowToExecutionContext.get(errorWindow);
        if (!executionContext) {
          return;
        }
        const typeNames = {
          [Ci.nsIConsoleMessage.debug]: 'debug',
          [Ci.nsIConsoleMessage.info]: 'info',
          [Ci.nsIConsoleMessage.warn]: 'warn',
          [Ci.nsIConsoleMessage.error]: 'error',
        };
        if (!message.hasException) {
          emitEvent(this.events.onConsoleMessage, {
            args: [{
              value: message.message,
            }],
            type: typeNames[message.logLevel],
            executionContextId: executionContext.id(),
            location: {
              lineNumber: message.lineNumber,
              columnNumber: message.columnNumber,
              url: message.sourceName,
            },
          });
        } else {
          emitEvent(this.events.onRuntimeError, {
            executionContext,
            message: message.errorMessage,
            stack: message.stack ? message.stack.toString() : '',
            location: errorLocation,
          });
        }
      },
    };
    Services.console.registerListener(consoleServiceListener);
    this._eventListeners.push(() => Services.console.unregisterListener(consoleServiceListener));
  }

  _registerConsoleAPIListener(Services) {
    const Ci = Components.interfaces;
    const Cc = Components.classes;
    const ConsoleAPIStorage = Cc["@mozilla.org/consoleAPI-storage;1"].getService(Ci.nsIConsoleAPIStorage);
    const onMessage = ({ wrappedJSObject }) => {
      const executionContext = Array.from(this._executionContexts.values()).find(context => {
        // There is no easy way to determine isolated world context and we normally don't write
        // objects to console from utility worlds so we always return main world context here.
        if (context._isIsolatedWorldContext())
          return false;
        const domWindow = context._domWindow;
        try {
          // `windowGlobalChild` might be dead already; accessing it will throw an error, message in a console,
          // and infinite recursion.
          return domWindow && domWindow.windowGlobalChild.innerWindowId === wrappedJSObject.innerID;
        } catch (e) {
          return false;
        }
      });
      if (!executionContext)
        return;
      this._onConsoleMessage(executionContext, wrappedJSObject);
    }
    ConsoleAPIStorage.addLogEventListener(
      onMessage,
      Cc["@mozilla.org/systemprincipal;1"].createInstance(Ci.nsIPrincipal)
    );
    this._eventListeners.push(() => ConsoleAPIStorage.removeLogEventListener(onMessage));
  }

  _registerWorkerConsoleHandler() {
    setConsoleEventHandler(message => {
      const executionContext = Array.from(this._executionContexts.values())[0];
      this._onConsoleMessage(executionContext, message);
    });
    this._eventListeners.push(() => setConsoleEventHandler(null));
  }

  _onConsoleMessage(executionContext, message) {
    const type = consoleLevelToProtocolType[message.level];
    if (!type)
      return;
    const args = message.arguments.map(arg => executionContext.rawValueToRemoteObject(arg));
    emitEvent(this.events.onConsoleMessage, {
      args,
      type,
      executionContextId: executionContext.id(),
      location: {
        lineNumber: message.lineNumber - 1,
        columnNumber: message.columnNumber - 1,
        url: message.filename,
      },
    });
  }

  dispose() {
    for (const tearDown of this._eventListeners)
      tearDown.call(null);
    this._eventListeners = [];
  }

  async _awaitPromise(executionContext, obj, exceptionDetails = {}) {
    if (obj.promiseState === 'fulfilled')
      return {success: true, obj: obj.promiseValue};
    if (obj.promiseState === 'rejected') {
      const debuggee = executionContext._debuggee;
      exceptionDetails.text = debuggee.executeInGlobalWithBindings('e.message', {e: obj.promiseReason}, {useInnerBindings: true}).return;
      exceptionDetails.stack = debuggee.executeInGlobalWithBindings('e.stack', {e: obj.promiseReason}, {useInnerBindings: true}).return;
      return {success: false, obj: null};
    }
    let resolve, reject;
    const promise = new Promise((a, b) => {
      resolve = a;
      reject = b;
    });
    this._pendingPromises.set(obj.promiseID, {resolve, reject, executionContext, exceptionDetails});
    if (this._pendingPromises.size === 1)
      this._debugger.onPromiseSettled = this._onPromiseSettled.bind(this);
    return await promise;
  }

  _onPromiseSettled(obj) {
    const pendingPromise = this._pendingPromises.get(obj.promiseID);
    if (!pendingPromise)
      return;
    this._pendingPromises.delete(obj.promiseID);
    if (!this._pendingPromises.size)
      this._debugger.onPromiseSettled = undefined;

    if (obj.promiseState === 'fulfilled') {
      pendingPromise.resolve({success: true, obj: obj.promiseValue});
      return;
    };
    const debuggee = pendingPromise.executionContext._debuggee;
    pendingPromise.exceptionDetails.text = debuggee.executeInGlobalWithBindings('e.message', {e: obj.promiseReason}, {useInnerBindings: true}).return;
    pendingPromise.exceptionDetails.stack = debuggee.executeInGlobalWithBindings('e.stack', {e: obj.promiseReason}, {useInnerBindings: true}).return;
    pendingPromise.resolve({success: false, obj: null});
  }

  createExecutionContext(domWindow, contextGlobal, auxData) {
    // Note: domWindow is null for workers.
    const context = new ExecutionContext(this, domWindow, contextGlobal, auxData);
    this._executionContexts.set(context._id, context);
    if (domWindow)
      this._windowToExecutionContext.set(domWindow, context);
    emitEvent(this.events.onExecutionContextCreated, context);
    return context;
  }

  findExecutionContext(executionContextId) {
    const executionContext = this._executionContexts.get(executionContextId);
    if (!executionContext)
      throw new Error('Failed to find execution context with id = ' + executionContextId);
    return executionContext;
  }

  // Camoufox: a main-world context is never registered in _executionContexts and
  // no executionContextCreated event is emitted for it, so Playwright does not
  // know it exists. That also means it has to be torn down by hand, without the
  // destroyed event -- announcing the death of a context the client never saw
  // would be worse than saying nothing.
  _destroyMainWorldContext(context) {
    for (const [promiseID, {reject, executionContext}] of this._pendingPromises) {
      if (executionContext === context) {
        reject(new Error('Execution context was destroyed!'));
        this._pendingPromises.delete(promiseID);
      }
    }
    if (!this._pendingPromises.size)
      this._debugger.onPromiseSettled = undefined;
    this._debugger.removeDebuggee(context._contextGlobal);
  }

  destroyExecutionContext(destroyedContext) {
    if (destroyedContext._mainWorldContext) {
      this._destroyMainWorldContext(destroyedContext._mainWorldContext);
      destroyedContext._mainWorldContext = null;
    }
    for (const [promiseID, {reject, executionContext}] of this._pendingPromises) {
      if (executionContext === destroyedContext) {
        reject(new Error('Execution context was destroyed!'));
        this._pendingPromises.delete(promiseID);
      }
    }
    if (!this._pendingPromises.size)
      this._debugger.onPromiseSettled = undefined;
    this._debugger.removeDebuggee(destroyedContext._contextGlobal);
    this._executionContexts.delete(destroyedContext._id);
    if (destroyedContext._domWindow)
      this._windowToExecutionContext.delete(destroyedContext._domWindow);
    emitEvent(this.events.onExecutionContextDestroyed, destroyedContext);
  }
}

class ExecutionContext {
  constructor(runtime, domWindow, contextGlobal, auxData) {
    this._runtime = runtime;
    this._domWindow = domWindow;
    this._contextGlobal = contextGlobal;
    this._debuggee = runtime._debugger.addDebuggee(contextGlobal);
    this._remoteObjects = new Map();
    this._id = generateId();
    this._auxData = auxData;
    // Camoufox: set by FrameTree on the default world when `allowMainWorld` is
    // on; see mainWorldContext().
    this._mainWorldGlobal = null;
    this._mainWorldContext = null;
    this._jsonStringifyObject = this._debuggee.executeInGlobal(`((stringify, object) => {
      const oldToJSON = Date.prototype?.toJSON;
      if (oldToJSON)
        Date.prototype.toJSON = undefined;
      const oldArrayToJSON = Array.prototype.toJSON;
      const oldArrayHadToJSON = Array.prototype.hasOwnProperty('toJSON');
      if (oldArrayHadToJSON)
        Array.prototype.toJSON = undefined;

      let hasSymbol = false;
      const result = stringify(object, (key, value) => {
        if (typeof value === 'symbol')
          hasSymbol = true;
        return value;
      });

      if (oldToJSON)
        Date.prototype.toJSON = oldToJSON;
      if (oldArrayHadToJSON)
        Array.prototype.toJSON = oldArrayToJSON;

      return hasSymbol ? undefined : result;
    }).bind(null, JSON.stringify.bind(JSON))`).return;
  }

  id() {
    return this._id;
  }

  auxData() {
    return this._auxData;
  }

  _isIsolatedWorldContext() {
    return !!this._auxData.name;
  }

  // Camoufox: opt this world into the `mw:` escape hatch by handing it the
  // page's own global.
  enableMainWorld(domWindow) {
    this._mainWorldGlobal = domWindow;
  }

  // Camoufox: the context `mw:` scripts run in, built on first use. Building it
  // lazily keeps the page's own global out of the debuggee set entirely for
  // sessions that never use `mw:`, even with the flag on.
  mainWorldContext() {
    if (!this._mainWorldGlobal)
      return null;
    if (!this._mainWorldContext) {
      this._mainWorldContext = new ExecutionContext(this._runtime, this._mainWorldGlobal, this._mainWorldGlobal, {
        frameId: this._auxData.frameId,
        name: '',
      });
    }
    return this._mainWorldContext;
  }

  async evaluateScript(script, exceptionDetails = {}) {
    const userInputHelper = this._domWindow ? this._domWindow.windowUtils.setHandlingUserInput(true) : null;
    if (this._domWindow && this._domWindow.document)
      this._domWindow.document.notifyUserGestureActivation();

    let {success, obj} = this._getResult(this._debuggee.executeInGlobal(script), exceptionDetails);
    userInputHelper && userInputHelper.destruct();
    if (!success)
      return null;
    if (obj && obj.isPromise) {
      const awaitResult = await this._runtime._awaitPromise(this, obj, exceptionDetails);
      if (!awaitResult.success)
        return null;
      obj = awaitResult.obj;
    }
    return this._createRemoteObject(obj);
  }

  evaluateScriptSafely(script) {
    try {
      this._debuggee.executeInGlobal(script);
    } catch (e) {
      dump(`WARNING: ${e.message}\n${e.stack}\n`);
    }
  }

  async evaluateFunction(functionText, args, exceptionDetails = {}) {
    const funEvaluation = this._getResult(this._debuggee.executeInGlobal('(' + functionText + ')'), exceptionDetails);
    if (!funEvaluation.success)
      return null;
    if (!funEvaluation.obj.callable)
      throw new Error('functionText does not evaluate to a function!');
    args = args.map(arg => {
      if (arg.objectId) {
        if (!this._remoteObjects.has(arg.objectId))
          throw new Error('Cannot find object with id = ' + arg.objectId);
        return this._remoteObjects.get(arg.objectId);
      }
      switch (arg.unserializableValue) {
        case 'Infinity': return Infinity;
        case '-Infinity': return -Infinity;
        case '-0': return -0;
        case 'NaN': return NaN;
        default: return this._toDebugger(arg.value);
      }
    });
    const userInputHelper = this._domWindow ? this._domWindow.windowUtils.setHandlingUserInput(true) : null;
    if (this._domWindow && this._domWindow.document)
      this._domWindow.document.notifyUserGestureActivation();
    let {success, obj} = this._getResult(funEvaluation.obj.apply(null, args), exceptionDetails);
    userInputHelper && userInputHelper.destruct();
    if (!success)
      return null;
    if (obj && obj.isPromise) {
      const awaitResult = await this._runtime._awaitPromise(this, obj, exceptionDetails);
      if (!awaitResult.success)
        return null;
      obj = awaitResult.obj;
    }
    return this._createRemoteObject(obj);
  }

  addBinding(name, script) {
    Cu.exportFunction((...args) => {
      emitEvent(this._runtime.events.onBindingCalled, {
        executionContextId: this._id,
        name,
        payload: args[0],
      });
    }, this._contextGlobal, {
      defineAs: name,
    });
    this.evaluateScriptSafely(script);
  }

  unsafeObject(objectId) {
    if (!this._remoteObjects.has(objectId))
      return;
    return { object: this._remoteObjects.get(objectId).unsafeDereference() };
  }

  rawValueToRemoteObject(rawValue) {
    const debuggerObj = this._debuggee.makeDebuggeeValue(rawValue);
    return this._createRemoteObject(debuggerObj);
  }

  _instanceOf(debuggerObj, rawObj, className) {
    if (this._domWindow)
      return rawObj instanceof this._domWindow[className];
    return this._debuggee.executeInGlobalWithBindings('o instanceof this[className]', {o: debuggerObj, className: this._debuggee.makeDebuggeeValue(className)}, {useInnerBindings: true}).return;
  }

  _createRemoteObject(debuggerObj) {
    if (debuggerObj instanceof Debugger.Object) {
      const objectId = generateId();
      this._remoteObjects.set(objectId, debuggerObj);
      const rawObj = debuggerObj.unsafeDereference();
      const type = typeof rawObj;
      let subtype = undefined;
      if (debuggerObj.isProxy)
        subtype = 'proxy';
      else if (Array.isArray(rawObj))
        subtype = 'array';
      else if (Object.is(rawObj, null))
        subtype = 'null';
      else if (typeof Node !== 'undefined' && Node.isInstance(rawObj))
        subtype = 'node';
      else if (this._instanceOf(debuggerObj, rawObj, 'RegExp'))
        subtype = 'regexp';
      else if (this._instanceOf(debuggerObj, rawObj, 'Date'))
        subtype = 'date';
      else if (this._instanceOf(debuggerObj, rawObj, 'Map'))
        subtype = 'map';
      else if (this._instanceOf(debuggerObj, rawObj, 'Set'))
        subtype = 'set';
      else if (this._instanceOf(debuggerObj, rawObj, 'WeakMap'))
        subtype = 'weakmap';
      else if (this._instanceOf(debuggerObj, rawObj, 'WeakSet'))
        subtype = 'weakset';
      else if (this._instanceOf(debuggerObj, rawObj, 'Error'))
        subtype = 'error';
      else if (this._instanceOf(debuggerObj, rawObj, 'Promise'))
        subtype = 'promise';
      else if ((this._instanceOf(debuggerObj, rawObj, 'Int8Array')) || (this._instanceOf(debuggerObj, rawObj, 'Uint8Array')) ||
               (this._instanceOf(debuggerObj, rawObj, 'Uint8ClampedArray')) || (this._instanceOf(debuggerObj, rawObj, 'Int16Array')) ||
               (this._instanceOf(debuggerObj, rawObj, 'Uint16Array')) || (this._instanceOf(debuggerObj, rawObj, 'Int32Array')) ||
               (this._instanceOf(debuggerObj, rawObj, 'Uint32Array')) || (this._instanceOf(debuggerObj, rawObj, 'Float32Array')) ||
               (this._instanceOf(debuggerObj, rawObj, 'Float64Array'))) {
        subtype = 'typedarray';
      }
      return {objectId, type, subtype};
    }
    if (typeof debuggerObj === 'symbol') {
      const objectId = generateId();
      this._remoteObjects.set(objectId, debuggerObj);
      return {objectId, type: 'symbol'};
    }

    let unserializableValue = undefined;
    if (Object.is(debuggerObj, NaN))
      unserializableValue = 'NaN';
    else if (Object.is(debuggerObj, -0))
      unserializableValue = '-0';
    else if (Object.is(debuggerObj, Infinity))
      unserializableValue = 'Infinity';
    else if (Object.is(debuggerObj, -Infinity))
      unserializableValue = '-Infinity';
    return unserializableValue ? {unserializableValue} : {value: debuggerObj};
  }

  ensureSerializedToValue(protocolObject) {
    if (!protocolObject.objectId)
      return protocolObject;
    const obj = this._remoteObjects.get(protocolObject.objectId);
    this._remoteObjects.delete(protocolObject.objectId);
    return {value: this._serialize(obj)};
  }

  _toDebugger(obj) {
    if (typeof obj !== 'object')
      return obj;
    if (obj === null)
      return obj;
    const properties = {};
    for (let [key, value] of Object.entries(obj)) {
      properties[key] = {
        configurable: true,
        writable: true,
        enumerable: true,
        value: this._toDebugger(value),
      };
    }
    const baseObject = Array.isArray(obj) ? '([])' : '({})';
    const debuggerObj = this._debuggee.executeInGlobal(baseObject).return;
    debuggerObj.defineProperties(properties);
    return debuggerObj;
  }

  _serialize(obj) {
    const result = this._debuggee.executeInGlobalWithBindings('stringify(e)', {e: obj, stringify: this._jsonStringifyObject}, {useInnerBindings: true});
    if (result.throw)
      throw new Error('Object is not serializable');
    return result.return === undefined ? undefined : JSON.parse(result.return);
  }

  disposeObject(objectId) {
    this._remoteObjects.delete(objectId);
  }

  getObjectProperties(objectId) {
    if (!this._remoteObjects.has(objectId))
      throw new Error('Cannot find object with id = ' + arg.objectId);
    const result = [];
    for (let obj = this._remoteObjects.get(objectId); obj; obj = obj.proto) {
      for (const propertyName of obj.getOwnPropertyNames()) {
        const descriptor = obj.getOwnPropertyDescriptor(propertyName);
        if (!descriptor.enumerable)
          continue;
        result.push({
          name: propertyName,
          value: this._createRemoteObject(descriptor.value),
        });
      }
    }
    return result;
  }

  _getResult(completionValue, exceptionDetails = {}) {
    if (!completionValue)
      throw new Error('evaluation terminated');
    if (completionValue.throw) {
      if (this._debuggee.executeInGlobalWithBindings('e instanceof Error', {e: completionValue.throw}, {useInnerBindings: true}).return) {
        exceptionDetails.text = this._debuggee.executeInGlobalWithBindings('e.message', {e: completionValue.throw}, {useInnerBindings: true}).return;
        exceptionDetails.stack = this._debuggee.executeInGlobalWithBindings('e.stack', {e: completionValue.throw}, {useInnerBindings: true}).return;
      } else {
        exceptionDetails.value = this._serialize(completionValue.throw);
      }
      return {success: false, obj: null};
    }
    return {success: true, obj: completionValue.return};
  }
}

const listenersSymbol = Symbol('listeners');

function createEvent() {
  const listeners = new Set();
  const subscribeFunction = listener => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }
  subscribeFunction[listenersSymbol] = listeners;
  return subscribeFunction;
}

function emitEvent(event, ...args) {
  let listeners = event[listenersSymbol];
  if (!listeners || !listeners.size)
    return;
  listeners = new Set(listeners);
  for (const listener of listeners)
    listener.call(null, ...args);
}

// Export Runtime to global.
globalThis.Runtime = Runtime;
