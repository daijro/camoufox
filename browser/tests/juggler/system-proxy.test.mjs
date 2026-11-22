// usesSystemProxy: whether Firefox's connections go through a system proxy,
// as nsProtocolProxyService resolves it, for each OS's settings service.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {load} from './gecko.mjs';

const {usesSystemProxy} = await load('SystemProxy.js');

const NS_ERROR_FAILURE = 0x80004005;
const NS_ERROR_UNEXPECTED = 0x8000ffff;

function fails(result) {
  return () => {
    throw Object.assign(new Error('component returned failure'), {result});
  };
}

// What each OS's nsISystemProxySettings returns, from its source
// (toolkit/system/*proxy): PACURI and getProxyForURI's answer for an https URL.
function settings({pac, proxy}) {
  return {
    get PACURI() {
      return typeof pac === 'function' ? pac() : pac;
    },
    getProxyForURI() {
      return typeof proxy === 'function' ? proxy() : proxy;
    },
  };
}

// nsOSXSystemProxySettings::GetPACURI fails when no PAC file is set (#1116).
const macos = {
  none: settings({pac: fails(NS_ERROR_FAILURE), proxy: 'DIRECT'}),
  pac: settings({pac: 'http://wpad.example/proxy.pac', proxy: 'DIRECT'}),
  manual: settings({pac: fails(NS_ERROR_FAILURE), proxy: 'PROXY proxy.example:8080'}),
};
// nsUnixSystemProxySettings: an empty PACURI, and getProxyForURI fails when no
// proxy is set.
const linux = {
  none: settings({pac: '', proxy: fails(NS_ERROR_FAILURE)}),
  manual: settings({pac: '', proxy: 'SOCKS proxy.example:1080'}),
};
// nsWindowsSystemProxySettings: an empty PACURI, DIRECT when no proxy is set.
const windows = {
  none: settings({pac: '', proxy: 'DIRECT'}),
  pac: settings({pac: 'http://wpad.example/proxy.pac', proxy: 'DIRECT'}),
  manual: settings({pac: '', proxy: 'PROXY proxy.example:8080'}),
};

test('no system proxy: direct on every OS', () => {
  for (const os of [macos, linux, windows])
    assert.equal(usesSystemProxy(5, os.none), false);
});

test('a PAC file or a manual system proxy is a system proxy on every OS', () => {
  for (const s of [macos.pac, macos.manual, linux.manual, windows.pac, windows.manual])
    assert.equal(usesSystemProxy(5, s), true);
});

test('only network.proxy.type 5 uses the system settings', () => {
  for (const type of [0, 1, 2, 4])
    assert.equal(usesSystemProxy(type, macos.manual), false);
});

test('no settings service is no system proxy', () => {
  assert.equal(usesSystemProxy(5, null), false);
  assert.equal(usesSystemProxy(5, undefined), false);
});

test('any failure is an absent setting, as Firefox resolves it, never a throw', () => {
  const odd = settings({pac: fails(NS_ERROR_UNEXPECTED), proxy: fails(NS_ERROR_UNEXPECTED)});
  assert.equal(usesSystemProxy(5, odd), false);
  const pacFailsProxySet = settings({pac: fails(NS_ERROR_UNEXPECTED), proxy: 'PROXY proxy.example:8080'});
  assert.equal(usesSystemProxy(5, pacFailsProxySet), true);
});
