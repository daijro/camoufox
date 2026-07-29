/** Console Home: soft open — do not steal restored session tabs. */

function homeUrl() {
  return browser.runtime.getURL("home.html");
}

/** Open home only when there is no existing http(s) tab (fresh profile). */
function openHomeIfEmpty() {
  const url = homeUrl();
  browser.tabs.query({}).then((tabs) => {
    const existingHome = tabs.find((t) => t.url && t.url.startsWith(url));
    if (existingHome && existingHome.id != null) {
      return;
    }
    const hasContent = tabs.some((t) => {
      const u = t.url || "";
      return (
        u.startsWith("http://") ||
        u.startsWith("https://") ||
        u.startsWith("file://")
      );
    });
    if (hasContent) return;
    browser.tabs.create({ url, active: true }).catch(() => {});
  }).catch(() => {});
}

browser.runtime.onInstalled.addListener(() => {
  // First install of temporary addon: open home once if empty.
  setTimeout(openHomeIfEmpty, 600);
});

// Do NOT force-open on every onStartup / timer — session restore owns first paint.

function isGeminiUrl(url) {
  if (!url) return false;
  try {
    const u = new URL(url);
    return u.hostname === "gemini.google.com" || u.hostname.endsWith(".gemini.google.com");
  } catch {
    return String(url).includes("gemini.google.com");
  }
}

async function fetchHomePayload(apiBase, profileId, sessionToken) {
  const url =
    `${apiBase.replace(/\/$/, "")}/api/v1/home/${encodeURIComponent(profileId)}` +
    `?token=${encodeURIComponent(sessionToken)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`home HTTP ${res.status}`);
  return res.json();
}

async function startGoogleAutoLogin(opts) {
  const apiBase = (opts.apiBase || "").replace(/\/$/, "");
  const profileId = opts.profileId || "";
  const sessionToken = opts.sessionToken || "";
  if (!apiBase || !profileId || !sessionToken) {
    await setLoginStatus("error", "缺少 bootstrap");
    return { ok: false, error: "missing bootstrap" };
  }

  let data;
  try {
    data = await fetchHomePayload(apiBase, profileId, sessionToken);
  } catch (e) {
    await setLoginStatus("error", String(e.message || e));
    return { ok: false, error: String(e.message || e) };
  }

  const acc = data.account;
  if (!acc) {
    await setLoginStatus("error", "无当前平台账号");
    return { ok: false, error: "no account" };
  }
  if (!acc.autoLoginEligible && !isGeminiUrl(acc.platformUrl)) {
    await setLoginStatus("error", "当前服务不是 Gemini，无法自动登录");
    return { ok: false, error: "not eligible" };
  }
  if (acc.autoLogin === false) {
    await setLoginStatus("error", "已关闭自动登录");
    return { ok: false, error: "disabled" };
  }
  if (!acc.username) {
    await setLoginStatus("error", "缺少账号");
    return { ok: false, error: "no username" };
  }

  const targetUrl = acc.platformUrl || "https://gemini.google.com/";
  const credentials = {
    username: acc.username || "",
    password: acc.password || "",
    totpCode: acc.totpCode || "",
    profileId,
    apiBase,
    sessionToken,
  };

  await browser.storage.local.set({
    googleAutoLoginCreds: credentials,
    googleAutoLoginArmed: true,
    googleAutoLoginStatus: { status: "starting", message: "正在打开 Gemini…", at: Date.now() },
  });

  const tab = await browser.tabs.create({ url: targetUrl, active: true });
  await browser.storage.local.set({ googleAutoLoginTabId: tab.id });

  const trySend = async () => {
    try {
      await browser.tabs.sendMessage(tab.id, {
        type: "runGoogleAutoLogin",
        credentials,
      });
      return true;
    } catch {
      return false;
    }
  };

  for (let i = 0; i < 20; i++) {
    await new Promise((r) => setTimeout(r, 800));
    if (await trySend()) break;
  }

  return { ok: true, tabId: tab.id };
}

async function setLoginStatus(status, message) {
  await browser.storage.local.set({
    googleAutoLoginStatus: { status, message, at: Date.now() },
  });
}

browser.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || !msg.type) return;

  if (msg.type === "startGoogleAutoLogin") {
    startGoogleAutoLogin(msg)
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true;
  }

  if (msg.type === "googleLoginProgress") {
    void setLoginStatus(msg.status || "running", msg.message || "");
    if (msg.status === "success") {
      void browser.storage.local.remove(["googleAutoLoginCreds"]);
    }
    sendResponse({ ok: true });
    return true;
  }

  if (msg.type === "getGoogleLoginStatus") {
    browser.storage.local.get(["googleAutoLoginStatus"]).then((st) => {
      sendResponse(st.googleAutoLoginStatus || null);
    });
    return true;
  }

  if (msg.type === "openConsoleHome") {
    browser.tabs.create({ url: homeUrl(), active: true }).then(() => sendResponse({ ok: true }));
    return true;
  }
});

browser.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !tab.url) return;
  void browser.storage.local
    .get(["googleAutoLoginTabId", "googleAutoLoginCreds"])
    .then((st) => {
      if (st.googleAutoLoginTabId !== tabId) return;
      if (!st.googleAutoLoginCreds) return;
      const url = tab.url || "";
      if (!url.includes("accounts.google.com") && !url.includes("gemini.google.com")) return;
      browser.tabs
        .sendMessage(tabId, {
          type: "runGoogleAutoLogin",
          credentials: st.googleAutoLoginCreds,
        })
        .catch(() => {});
    });
});
