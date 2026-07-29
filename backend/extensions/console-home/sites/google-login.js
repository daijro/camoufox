/**
 * Google / Gemini login autofill — best-effort selectors.
 * DOM and anti-bot change often; failures report via runtime messages.
 */
(function () {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  let running = false;

  function report(status, message, extra) {
    try {
      browser.runtime.sendMessage({
        type: "googleLoginProgress",
        status,
        message,
        url: location.href,
        ...(extra || {}),
      });
    } catch (_) {
      /* ignore */
    }
  }

  function visible(el) {
    if (!el) return false;
    const st = window.getComputedStyle(el);
    return st.display !== "none" && st.visibility !== "hidden" && el.offsetParent !== null;
  }

  function q(sel) {
    const el = document.querySelector(sel);
    return visible(el) ? el : null;
  }

  function setNativeValue(input, value) {
    const proto = window.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) desc.set.call(input, value);
    else input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function clickNext() {
    const candidates = [
      "#identifierNext",
      "#passwordNext",
      "#totpNext",
      "button[type=button]#identifierNext",
      "button[jsname='LgbsSe']",
      "div[role=button]#identifierNext",
      "div[role=button]#passwordNext",
      "button:not([disabled])",
    ];
    for (const sel of candidates) {
      const els = document.querySelectorAll(sel);
      for (const el of els) {
        if (!visible(el)) continue;
        const t = (el.textContent || "").trim().toLowerCase();
        if (
          sel.includes("Next") ||
          t === "next" ||
          t === "下一步" ||
          t.includes("next") ||
          t.includes("继续") ||
          t.includes("verify") ||
          t.includes("验证")
        ) {
          el.click();
          return true;
        }
      }
    }
    // Fallback: primary-looking button
    const btn = q("button[type=submit]") || q("div[role=button].VfPpkd-LgbsSe");
    if (btn) {
      btn.click();
      return true;
    }
    return false;
  }

  function detectChallenge() {
    const text = (document.body && document.body.innerText) || "";
    const lower = text.toLowerCase();
    const hasTotpField = !!(
      q('input[name="totpPin"]') ||
      q("#totpPin") ||
      q('input[autocomplete="one-time-code"]')
    );
    if (hasTotpField) return null;
    if (
      lower.includes("captcha") ||
      lower.includes("recaptcha") ||
      lower.includes("unusual traffic") ||
      text.includes("人机验证")
    ) {
      return "需要人机验证或设备确认，请手动完成";
    }
    return null;
  }

  async function waitFor(fn, timeoutMs, stepMs) {
    const end = Date.now() + timeoutMs;
    while (Date.now() < end) {
      const v = fn();
      if (v) return v;
      await sleep(stepMs || 400);
    }
    return null;
  }

  async function runWithCreds(creds) {
    if (running) return;
    running = true;
    try {
      await runWithCredsInner(creds);
    } finally {
      running = false;
    }
  }

  async function runWithCredsInner(creds) {
    if (!creds || !creds.username) {
      report("error", "缺少账号凭据");
      return;
    }

    // Already on Gemini app (logged in) — only if no Google login chrome and chat UI-ish
    if (
      location.hostname.includes("gemini.google.com") &&
      !location.href.includes("ServiceLogin") &&
      !location.href.includes("accounts.google") &&
      !document.querySelector("#identifierId") &&
      !document.querySelector('input[type="email"]') &&
      !document.querySelector('input[name="Passwd"]')
    ) {
      // Wait a bit: gemini often redirects to accounts shortly after load
      await sleep(2500);
      if (
        location.hostname.includes("accounts.google.com") ||
        document.querySelector("#identifierId") ||
        document.querySelector('input[type="email"]')
      ) {
        // Fall through to login flow
      } else if (location.hostname.includes("gemini.google.com")) {
        report("success", "已在 Gemini（可能已登录）");
        return;
      }
    }

    report("running", "开始 Google 登录填表");

    // Email step
    const emailInput =
      (await waitFor(
        () =>
          q("#identifierId") ||
          q('input[type="email"]') ||
          q('input[name="identifier"]') ||
          q('input[autocomplete="username"]'),
        8000,
      )) || null;

    if (emailInput) {
      setNativeValue(emailInput, creds.username);
      await sleep(400 + Math.random() * 300);
      if (!clickNext()) {
        report("error", "找不到邮箱下一步按钮");
        return;
      }
      report("running", "已提交邮箱");
      await sleep(1200);
    }

    const hard = detectChallenge();
    if (hard) {
      report("need_manual", hard);
      return;
    }

    // Password step
    const passInput = await waitFor(
      () =>
        q('input[name="Passwd"]') ||
        q('input[type="password"]') ||
        q('input[name="password"]') ||
        q('input[autocomplete="current-password"]'),
      12000,
    );

    if (passInput) {
      if (!creds.password) {
        report("need_manual", "未配置密码，请手动输入");
        return;
      }
      setNativeValue(passInput, creds.password);
      await sleep(400 + Math.random() * 300);
      if (!clickNext()) {
        report("error", "找不到密码下一步按钮");
        return;
      }
      report("running", "已提交密码");
      await sleep(1500);
    }

    const hard2 = detectChallenge();
    if (hard2) {
      report("need_manual", hard2);
      return;
    }

    // TOTP step
    const totpInput = await waitFor(
      () =>
        q('input[name="totpPin"]') ||
        q("#totpPin") ||
        q('input[autocomplete="one-time-code"]') ||
        q('input[id="idvPreregisteredPhonePin"]') ||
        q('input[type="tel"]'),
      6000,
    );

    if (totpInput) {
      let code = creds.totpCode || "";
      if (!code && creds.profileId && creds.apiBase && creds.sessionToken) {
        try {
          const u =
            `${creds.apiBase}/api/v1/home/${encodeURIComponent(creds.profileId)}` +
            `?token=${encodeURIComponent(creds.sessionToken)}`;
          const res = await fetch(u);
          if (res.ok) {
            const data = await res.json();
            code = (data.account && data.account.totpCode) || "";
          }
        } catch (_) {
          /* ignore */
        }
      }
      if (!code) {
        report("need_manual", "出现 2FA 但无验证码，请手动输入");
        return;
      }
      setNativeValue(totpInput, code);
      await sleep(350);
      clickNext();
      report("running", "已提交 TOTP");
      await sleep(2000);
    }

    if (location.hostname.includes("gemini.google.com")) {
      report("success", "已进入 Gemini");
      return;
    }

    // Wait briefly for redirect
    await sleep(2500);
    if (location.hostname.includes("gemini.google.com")) {
      report("success", "已进入 Gemini");
      return;
    }

    const hard3 = detectChallenge();
    if (hard3) {
      report("need_manual", hard3);
      return;
    }

    report(
      "need_manual",
      "登录流程未完全自动完成（可能已部分成功），请检查页面",
    );
  }

  browser.runtime.onMessage.addListener((msg) => {
    if (!msg || msg.type !== "runGoogleAutoLogin") return;
    void runWithCreds(msg.credentials || {});
  });

  // Auto-run when armed (covers SPA / late inject). Keep armed until login fields seen
  // so redirect gemini → accounts.google.com still picks up credentials.
  browser.storage.local.get(["googleAutoLoginCreds", "googleAutoLoginArmed"]).then((st) => {
    if (!st.googleAutoLoginArmed || !st.googleAutoLoginCreds) return;
    const onAccounts = location.hostname.includes("accounts.google.com");
    const onGemini = location.hostname.includes("gemini.google.com");
    if (onAccounts) {
      void browser.storage.local.set({ googleAutoLoginArmed: false });
      void runWithCreds(st.googleAutoLoginCreds);
    } else if (onGemini) {
      void runWithCreds(st.googleAutoLoginCreds);
    }
  });
})();
