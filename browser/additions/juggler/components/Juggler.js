/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Services is available as a global in XPCOM component context

// Load SimpleChannel in browser-process global.
Services.scriptloader.loadSubScript('resource://gre/modules/juggler/SimpleChannel.js');
const {Dispatcher} = ChromeUtils.importESModule("resource://gre/modules/juggler/protocol/Dispatcher.js");
const {BrowserHandler} = ChromeUtils.importESModule("resource://gre/modules/juggler/protocol/BrowserHandler.js");
const {NetworkObserver} = ChromeUtils.importESModule("resource://gre/modules/juggler/NetworkObserver.js");
const {TargetRegistry} = ChromeUtils.importESModule("resource://gre/modules/juggler/TargetRegistry.js");
const {Helper} = ChromeUtils.importESModule('resource://gre/modules/juggler/Helper.js');
const {ActorManagerParent} = ChromeUtils.importESModule('resource://gre/modules/ActorManagerParent.sys.mjs');
const helper = new Helper();

const Cc = Components.classes;
const Ci = Components.interfaces;

// Camoufox: everything Juggler changes in a page is installed only once a
// driver is attached (-juggler-pipe). Its frame actor turns off every
// top-level docShell's bfcache.
// focusmanager.testmode belongs to the driver too: it keeps a window that
// loses focus to another window or a native dialog from being lowered, which a
// page reads as the missing blur (stock's default is false).
function installDriverOverrides() {
  Services.prefs.getDefaultBranch("").setBoolPref("focusmanager.testmode", true);
  // Juggler follows frames within one content process: keep cross-site iframes in their
  // parent's process. A browser nobody drives keeps Firefox's isolation, which a page can tell.
  Services.prefs.getDefaultBranch("").setIntPref("fission.webContentIsolationStrategy", 0);
  // Juggler cannot report a page restored from bfcache, so a driven browser keeps none
  // (this alone disables it; docShell.disallowBFCache does not under SHIP).
  Services.prefs.getDefaultBranch("").setBoolPref("fission.bfcacheInParent", false);
  // A driver's first page is about:blank, its URL on the command line: a headed
  // launch otherwise opens the home page instead. No page can read this pref.
  Services.prefs.getDefaultBranch("").setIntPref("browser.startup.page", 0);
  // Register JSWindowActors that will be instantiated for each frame.
  ActorManagerParent.addJSWindowActors({
    JugglerFrame: {
      parent: {
        esModuleURI: 'resource://gre/modules/juggler/JugglerFrameParent.sys.mjs',
      },
      child: {
        esModuleURI: 'resource://gre/modules/juggler/JugglerFrameChild.sys.mjs',
        // Instantiate an actor when a new window is created. An observer topic,
        // not DOMWindowCreated: an event handed to the actor gets its reflector
        // in the page's window, which defines `Event` there before the page's
        // first script runs, as it never is in a browser nobody drives.
        observers: ['content-document-global-created'],
        events: {
          DOMContentLoaded: {},
          DOMWillOpenModalDialog: {},
          DOMModalDialogClosed: {},
        },
      },
      allFrames: true,
      safeForUntrustedWebProcess: true,
    },
  });
}

let browserStartupFinishedCallback;
let browserStartupFinishedPromise = new Promise(x => browserStartupFinishedCallback = x);

export class Juggler {
  get classDescription() { return "Sample command-line handler"; }
  get classID() { return Components.ID('{f7a74a33-e2ab-422d-b022-4fb213dd2639}'); }
  get contractID() { return "@mozilla.org/remote/juggler;1" }
  get QueryInterface() {
    return ChromeUtils.generateQI([ Ci.nsICommandLineHandler, Ci.nsIObserver ]);
  }
  get helpInfo() {
    return "  --juggler            Enable Juggler automation\n";
  }

  handle(cmdLine) {
    // flag has to be consumed in nsICommandLineHandler:handle
    // to avoid issues on macos. See Marionette.jsm::handle() for more details.
    // TODO: remove after Bug 1724251 is fixed.
    cmdLine.handleFlag("juggler-pipe", false);
  }

  // This flow is taken from Remote agent and Marionette.
  // See https://github.com/mozilla-firefox/firefox/blob/35e22180b0b61413dd8eccf6c00b1c6fac073eee/remote/components/RemoteAgent.sys.mjs#L417
  async observe(subject, topic) {
    switch (topic) {
      case "profile-after-change":
        Services.obs.addObserver(this, "command-line-startup");
        Services.obs.addObserver(this, "browser-idle-startup-tasks-finished");
        break;
      case "command-line-startup":
        Services.obs.removeObserver(this, topic);
        const cmdLine = subject;
        const jugglerPipeFlag = cmdLine.handleFlag('juggler-pipe', false);
        if (!jugglerPipeFlag)
          return;
        installDriverOverrides();

        this._silent = cmdLine.findFlag('silent', false) >= 0;
        if (this._silent) {
          Services.startup.enterLastWindowClosingSurvivalArea();
          browserStartupFinishedCallback();
        }
        Services.obs.addObserver(this, "final-ui-startup");
        break;
      case "browser-idle-startup-tasks-finished":
        browserStartupFinishedCallback();
        break;
      // Used to wait until the initial application window has been opened.
      case "final-ui-startup":
        Services.obs.removeObserver(this, topic);

        const targetRegistry = new TargetRegistry({ lastWindowQuits: !this._silent });
        new NetworkObserver(targetRegistry);

        const loadStyleSheet = () => {
          // Camoufox: upstream Playwright hides content scrollbars in headless
          // with an agent sheet (scrollbar-width: none !important). A page can
          // read that back -- getComputedStyle(document.body).scrollbarWidth is
          // "none" and overflow:scroll boxes lose their gutter -- and no stock
          // Firefox does it. Scrollbar appearance is left to the platform
          // look-and-feel instead (the launcher sets ui.useOverlayScrollbars to
          // what the claimed OS shows), so headless matches headed.
        };

        // Force create hidden window here, otherwise its creation later closes the web socket!
        // Since https://phabricator.services.mozilla.com/D219834, hiddenDOMWindow is only available on MacOS.
        if (Services.appShell.hasHiddenWindow) {
          Services.appShell.hiddenDOMWindow;
        }

        let pipeStopped = false;
        let browserHandler;
        const pipe = Cc['@mozilla.org/juggler/remotedebuggingpipe;1'].getService(Ci.nsIRemoteDebuggingPipe);
        const connection = {
          QueryInterface: ChromeUtils.generateQI([Ci.nsIRemoteDebuggingPipeClient]),
          receiveMessage(message) {
            if (this.onmessage)
              this.onmessage({ data: message });
          },
          disconnected() {
            if (browserHandler)
              browserHandler['Browser.close']();
          },
          send(message) {
            if (pipeStopped) {
              // We are missing the response to Browser.close,
              // but everything works fine. Once we actually need it,
              // we have to stop the pipe after the response is sent.
              return;
            }
            pipe.sendMessage(message);
          },
        };
        pipe.init(connection);
        const dispatcher = new Dispatcher(connection);
        browserHandler = new BrowserHandler(dispatcher.rootSession(), dispatcher, targetRegistry, browserStartupFinishedPromise, () => {
          if (this._silent)
            Services.startup.exitLastWindowClosingSurvivalArea();
          connection.onclose();
          pipe.stop();
          pipeStopped = true;
        });
        dispatcher.rootSession().setHandler(browserHandler);
        loadStyleSheet();
        dump(`\nJuggler listening to the pipe\n`);
        break;
    }
  }

}

const jugglerInstance = new Juggler();

// This is used by the XPCOM codepath which expects a constructor
export var JugglerFactory = function() {
  return jugglerInstance;
};

