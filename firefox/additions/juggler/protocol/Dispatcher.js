/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

const {protocol, checkScheme} = ChromeUtils.import("chrome://juggler/content/protocol/Protocol.js");
const {Helper} = ChromeUtils.import('chrome://juggler/content/Helper.js');

const helper = new Helper();
// Camoufox: Exclude redundant internal events from logs.
const EXCLUDED_DBG = ['Page.navigationStarted', 'Page.frameAttached', 'Runtime.executionContextCreated', 'Runtime.console', 'Page.navigationAborted', 'Page.eventFired'];

class Dispatcher {
  /**
   * @param {Connection} connection
   */
  constructor(connection) {
    this._connection = connection;
    this._connection.onmessage = this._dispatch.bind(this);
    this._connection.onclose = this._dispose.bind(this);
    this._sessions = new Map();
    this._rootSession = new ProtocolSession(this, undefined);
  }

  rootSession() {
    return this._rootSession;
  }

  createSession() {
    const session = new ProtocolSession(this, helper.generateId());
    this._sessions.set(session.sessionId(), session);
    return session;
  }

  destroySession(session) {
    this._sessions.delete(session.sessionId());
    session._dispose();
  }

  _dispose() {
    this._connection.onmessage = null;
    this._connection.onclose = null;
    this._rootSession._dispose();
    this._rootSession = null;
    this._sessions.clear();
  }

  async _dispatch(event) {
    const data = JSON.parse(event.data);

    if (ChromeUtils.isCamouDebug())
      ChromeUtils.camouDebug(`[${new Date().toLocaleString()}]`
        + `\nReceived message: ${safeJsonStringify(data)}`);

    const id = data.id;
    const sessionId = data.sessionId;
    delete data.sessionId;
    try {
      const session = sessionId ? this._sessions.get(sessionId) : this._rootSession;
      if (!session)
        throw new Error(`ERROR: cannot find session with id "${sessionId}"`);
      const method = data.method;
      const params = data.params || {};
      if (!id)
        throw new Error(`ERROR: every message must have an 'id' parameter`);
      if (!method)
        throw new Error(`ERROR: every message must have a 'method' parameter`);

      const [domain, methodName] = method.split('.');
      const descriptor = protocol.domains[domain] ? protocol.domains[domain].methods[methodName] : null;
      if (!descriptor)
        throw new Error(`ERROR: method '${method}' is not supported`);
      let details = {};
      if (!checkScheme(descriptor.params || {}, params, details))
        throw new Error(`ERROR: failed to call method '${method}' with parameters ${JSON.stringify(params, null, 2)}\n${details.error}`);

      const result = await session.dispatch(method, params);

      details = {};
      if ((descriptor.returns || result) && !checkScheme(descriptor.returns, result, details))
        throw new Error(`ERROR: failed to dispatch method '${method}' result ${JSON.stringify(result, null, 2)}\n${details.error}`);

      this._connection.send(JSON.stringify({id, sessionId, result}));
    } catch (e) {
      dump(`
        ERROR: ${e.message} ${e.stack}
      `);
      this._connection.send(JSON.stringify({id, sessionId, error: {
        message: e.message,
        data: e.stack
      }}));
    }
  }

  _emitEvent(sessionId, eventName, params) {
    const [domain, eName] = eventName.split('.');
    
    // Camoufox: Log internal events
    if (ChromeUtils.isCamouDebug() && !EXCLUDED_DBG.includes(eventName) && domain !== 'Network') {
      ChromeUtils.camouDebug(`[${new Date().toLocaleString()}]`
        + `\nInternal event: ${eventName}\nParams: ${JSON.stringify(params, null, 2)}`);
    }
    
    const scheme = protocol.domains[domain] ? protocol.domains[domain].events[eName] : null;
    if (!scheme)
      throw new Error(`ERROR: event '${eventName}' is not supported`);
    const details = {};
    if (!checkScheme(scheme, params || {}, details))
      throw new Error(`ERROR: failed to emit event '${eventName}' ${JSON.stringify(params, null, 2)}\n${details.error}`);
    this._connection.send(JSON.stringify({method: eventName, params, sessionId}));
  }
}

class ProtocolSession {
  constructor(dispatcher, sessionId) {
    this._sessionId = sessionId;
    this._dispatcher = dispatcher;
    this._handler = null;
  }

  sessionId() {
    return this._sessionId;
  }

  setHandler(handler) {
    this._handler = handler;
  }

  _dispose() {
    if (this._handler)
      this._handler.dispose();
    this._handler = null;
    this._dispatcher = null;
  }

  emitEvent(eventName, params) {
    if (!this._dispatcher)
      throw new Error(`Session has been disposed.`);
    this._dispatcher._emitEvent(this._sessionId, eventName, params);
  }

  async dispatch(method, params) {
    if (!this._handler)
      throw new Error(`Session does not have a handler!`);
    if (!this._handler[method])
      throw new Error(`Handler for does not implement method "${method}"`);
    return await this._handler[method](params);
  }
}

this.EXPORTED_SYMBOLS = ['Dispatcher'];
this.Dispatcher = Dispatcher;


function formatDate(date) {
  const pad = (num) => String(num).padStart(2, '0');
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function truncateObject(obj, maxDepth = 8, maxLength = 100) {
  if (maxDepth < 0) return '[Max Depth Reached]';
  
  if (typeof obj !== 'object' || obj === null) {
    return typeof obj === 'string' ? truncateString(obj, maxLength) : obj;
  }
  
  if (Array.isArray(obj)) {
    return obj.slice(0, 10).map(item => truncateObject(item, maxDepth - 1, maxLength));
  }
  
  const truncated = {};
  for (const [key, value] of Object.entries(obj)) {
    if (Object.keys(truncated).length >= 10) {
      truncated['...'] = '[Truncated]';
      break;
    }
    truncated[key] = truncateObject(value, maxDepth - 1, maxLength);
  }
  return truncated;
}

function truncateString(str, maxLength) {
  if (str.length <= maxLength) return str;
  ChromeUtils.camouDebug(`String length: ${str.length}`);
  return str.substr(0, maxLength) + '... [truncated]';
}

function safeJsonStringify(data) {
  try {
    return JSON.stringify(truncateObject(data), null, 2);
  } catch (error) {
    return `[Unable to stringify: ${error.message}]`;
  }
}