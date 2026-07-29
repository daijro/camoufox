(() => {
  const boot = window.CAMOUFOX_CONSOLE_BOOTSTRAP || {};
  const apiBase = (boot.apiBase || "http://127.0.0.1:50325").replace(/\/$/, "");
  const profileId = boot.profileId || "";
  const token = boot.sessionToken || "";

  const $ = (id) => document.getElementById(id);
  let homeData = null;
  let remain = 0;

  function isGeminiEligible(acc) {
    if (!acc) return false;
    if (acc.autoLoginEligible) return true;
    const url = acc.platformUrl || "";
    return url.includes("gemini.google.com");
  }

  function setClock() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    $("clock").textContent =
      d.toLocaleString(undefined, { timeZoneName: "short" }) +
      " · " +
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  async function fetchHome() {
    if (!profileId || !token) {
      $("geoLine").textContent = "缺少 bootstrap（profileId / sessionToken）";
      return;
    }
    const url =
      `${apiBase}/api/v1/home/${encodeURIComponent(profileId)}` +
      `?token=${encodeURIComponent(token)}`;
    const res = await fetch(url);
    if (!res.ok) {
      $("geoLine").textContent = `首页接口失败 HTTP ${res.status}`;
      return;
    }
    homeData = await res.json();
    render(homeData);
    maybeAutoStartLogin(homeData);
  }

  function render(data) {
    $("profileBadge").textContent = data.profileName || profileId;

    if (data.ipChanged) {
      $("ipWarn").classList.remove("hidden");
      $("ipWarn").textContent =
        data.ipWarnMessage ||
        "您的 IP 地址已发生变化，请注意，访问账号的操作可能存在风险。";
    } else {
      $("ipWarn").classList.add("hidden");
    }

    const geo = [data.country, data.region, data.city].filter(Boolean).join(" / ") || "未知地区";
    $("geoLine").textContent = geo;
    $("ipLine").textContent = data.exitIp ? `IP: ${data.exitIp}` : "IP: —";

    const acc = data.account;
    if (!acc) {
      $("noAccount").classList.remove("hidden");
      $("accountBlock").classList.add("hidden");
    } else {
      $("noAccount").classList.add("hidden");
      $("accountBlock").classList.remove("hidden");
      const a = $("platformUrl");
      a.href = acc.platformUrl || "#";
      a.textContent = acc.platformLabel
        ? `${acc.platformLabel} · ${acc.platformUrl}`
        : acc.platformUrl || "—";
      $("username").textContent = acc.username || "—";
      $("passwordMask").textContent = acc.hasPassword ? "••••••••" : "（无密码）";
      remain = acc.totpRemaining || 0;
      $("totpCode").textContent = acc.totpCode || "——————";
      $("totpRemain").textContent = acc.totpCode
        ? `${remain}s 后刷新`
        : "未配置 2FA";

      const gemini = isGeminiEligible(acc) && acc.autoLogin !== false;
      if (gemini) {
        $("btnAutoLogin").classList.remove("hidden");
        $("autoLoginNextWrap").classList.remove("hidden");
      } else {
        $("btnAutoLogin").classList.add("hidden");
        $("autoLoginNextWrap").classList.add("hidden");
      }
    }

    const fp = data.fingerprint || {};
    const win = data.window || {};
    const rows = [
      ["备注", win.note || "—"],
      ["项目/分组", win.group || "—"],
      ["标签", (win.tags || []).join(", ") || "—"],
      ["系统", fp.os || "—"],
      ["指纹摘要", fp.summary || "—"],
      ["策略", fp.strategy || "—"],
      ["User Agent", fp.userAgent || "—"],
    ];
    $("fpList").innerHTML = rows
      .map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(String(v))}</dd>`)
      .join("");
  }

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function copyText(text) {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
  }

  function requestAutoLogin() {
    $("autoLoginStatus").textContent = "正在启动自动登录…";
    browser.runtime
      .sendMessage({
        type: "startGoogleAutoLogin",
        apiBase,
        profileId,
        sessionToken: token,
      })
      .then((r) => {
        if (!r || !r.ok) {
          $("autoLoginStatus").textContent =
            "启动失败：" + ((r && r.error) || "unknown");
        }
      })
      .catch((e) => {
        $("autoLoginStatus").textContent = "启动失败：" + String(e);
      });
  }

  let autoStarted = false;
  function maybeAutoStartLogin(data) {
    if (autoStarted) return;
    const acc = data && data.account;
    if (!isGeminiEligible(acc) || acc.autoLogin === false) return;
    browser.storage.local.get(["autoLoginOnNextStart"]).then((st) => {
      if (!st.autoLoginOnNextStart) return;
      autoStarted = true;
      void browser.storage.local.set({ autoLoginOnNextStart: false });
      $("chkAutoLoginNext").checked = false;
      setTimeout(() => requestAutoLogin(), 1500);
    });
  }

  function pollLoginStatus() {
    browser.runtime.sendMessage({ type: "getGoogleLoginStatus" }).then((st) => {
      if (!st || !st.message) return;
      const label =
        st.status === "success"
          ? "✓ "
          : st.status === "need_manual"
            ? "⚠ "
            : st.status === "error"
              ? "✗ "
              : "";
      $("autoLoginStatus").textContent = label + st.message;
    }).catch(() => {});
  }

  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!homeData || !homeData.account) return;
      const kind = btn.getAttribute("data-copy");
      const acc = homeData.account;
      if (kind === "username") await copyText(acc.username || "");
      if (kind === "password") await copyText(acc.password || "");
      if (kind === "totp") await copyText(acc.totpCode || "");
      btn.textContent = "已复制";
      setTimeout(() => {
        btn.textContent =
          kind === "username" ? "复制账号" : kind === "password" ? "复制密码" : "复制验证码";
      }, 1200);
    });
  });

  $("btnOpenPlatform").addEventListener("click", () => {
    const url = homeData && homeData.account && homeData.account.platformUrl;
    if (url) window.open(url, "_blank");
  });

  $("btnAutoLogin").addEventListener("click", () => requestAutoLogin());

  $("chkAutoLoginNext").addEventListener("change", () => {
    void browser.storage.local.set({
      autoLoginOnNextStart: !!$("chkAutoLoginNext").checked,
    });
  });

  browser.storage.local.get(["autoLoginOnNextStart"]).then((st) => {
    $("chkAutoLoginNext").checked = !!st.autoLoginOnNextStart;
  });

  $("btnRefreshIp").addEventListener("click", () => {
    void fetchHome();
  });

  setClock();
  setInterval(setClock, 1000);
  setInterval(pollLoginStatus, 1000);
  void fetchHome();

  setInterval(() => {
    if (!homeData || !homeData.account || !homeData.account.totpCode) return;
    remain -= 1;
    if (remain <= 0) {
      void fetchHome();
      return;
    }
    $("totpRemain").textContent = `${remain}s 后刷新`;
  }, 1000);
})();
