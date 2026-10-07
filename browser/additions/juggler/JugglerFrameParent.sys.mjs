"use strict";

const { TargetRegistry } = ChromeUtils.importESModule('chrome://juggler/content/TargetRegistry.js');
const { Helper } = ChromeUtils.importESModule('chrome://juggler/content/Helper.js');

const helper = new Helper();

export class JugglerFrameParent extends JSWindowActorParent {
  constructor() {
    super();
  }

  receiveMessage() { }

  async actorCreated() {
    // Actors are registered per the WindowGlobalParent / WindowGlobalChild pair. We are only
    // interested in those WindowGlobalParent actors that are matching current browsingContext
    // window global.
    // See https://github.com/mozilla/gecko-dev/blob/cd2121e7d83af1b421c95e8c923db70e692dab5f/testing/mochitest/BrowserTestUtils/BrowserTestUtilsParent.sys.mjs#L15
    if (!this.manager?.isCurrentGlobal)
      return;

    // Firefox 152+: the actor may be created BEFORE the chrome-side PageTarget
    // exists (notably for window.open popups, where the content WindowGlobal is
    // created before the `TabOpen` event fires). Delegate to the registry, which
    // tracks the actor and binds it whenever the target appears — in either
    // order. The previous implementation looked up the target here and bailed
    // with no retry when it was missing, leaving the popup's page channel
    // permanently unbound (Page.ready never sent -> no `popup` event).
    TargetRegistry.instance()?.onActorCreated(this);
  }

  didDestroy() {
    TargetRegistry.instance()?.onActorDestroyed(this);
  }
}
