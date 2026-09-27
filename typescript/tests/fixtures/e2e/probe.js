async () => {
	const out = {};
	// An await that never settles would hang the whole test with no clue which
	// one; this records "timeout: <what>" in the result instead.
	const within = (promise, what, ms = 10000) =>
		Promise.race([
			promise,
			new Promise((_, reject) =>
				setTimeout(() => reject(new Error(`timeout: ${what} (${ms} ms)`)), ms),
			),
		]);
	const nav = navigator;
	out.navigator = {
		userAgent: nav.userAgent,
		platform: nav.platform,
		oscpu: nav.oscpu,
		appVersion: nav.appVersion,
		hardwareConcurrency: nav.hardwareConcurrency,
		maxTouchPoints: nav.maxTouchPoints,
		language: nav.language,
		languages: [...nav.languages],
		doNotTrack: nav.doNotTrack,
		globalPrivacyControl: nav.globalPrivacyControl,
		webdriver: nav.webdriver,
	};
	out.screen = {
		width: screen.width,
		height: screen.height,
		availWidth: screen.availWidth,
		availHeight: screen.availHeight,
		colorDepth: screen.colorDepth,
		pixelDepth: screen.pixelDepth,
	};
	out.window = {
		outerWidth: window.outerWidth,
		outerHeight: window.outerHeight,
		devicePixelRatio: window.devicePixelRatio,
		screenX: window.screenX,
		screenY: window.screenY,
	};
	const ro = Intl.DateTimeFormat().resolvedOptions();
	out.intl = {
		timeZone: ro.timeZone,
		locale: ro.locale,
		offset: new Date(Date.UTC(2026, 0, 15, 12)).getTimezoneOffset(),
		number: new Intl.NumberFormat().format(1234567.891),
	};
	const fonts = [
		"Arial", "Helvetica", "Times New Roman", "Courier New", "Segoe UI", "Calibri",
		"DejaVu Sans", "Liberation Sans", "Noto Sans", "Ubuntu", "Menlo", "Monaco",
		"Comic Sans MS", "Verdana", "Georgia", "Cantarell", "Tahoma", "Impact",
	];
	const canvas = document.createElement("canvas");
	const ctx = canvas.getContext("2d");
	const width = (family) => {
		ctx.font = `32px "${family}", monospace`;
		return ctx.measureText("mmmmmmmmmmlli1WQ@#").width;
	};
	const base = width("__no_such_font__");
	out.fonts = Object.fromEntries(fonts.map((f) => [f, width(f) !== base]));
	out.fontWidths = Object.fromEntries(fonts.map((f) => [f, width(f)]));
	canvas.width = 220;
	canvas.height = 40;
	ctx.textBaseline = "top";
	ctx.font = "16px Arial";
	ctx.fillStyle = "#f60";
	ctx.fillRect(10, 1, 62, 20);
	ctx.fillStyle = "#069";
	ctx.fillText("Camoufox parity <canvas> 1.0", 2, 15);
	ctx.beginPath();
	ctx.arc(180, 20, 12, 0, Math.PI * 1.5);
	ctx.strokeStyle = "rgba(10, 120, 40, 0.7)";
	ctx.stroke();
	const data = canvas.toDataURL();
	// FNV-1a over the data URL: the probe runs in Camoufox's isolated world,
	// where handing TypedArrays across the Xray boundary is forbidden.
	let h = 0x811c9dc5;
	for (let i = 0; i < data.length; i++) {
		h ^= data.charCodeAt(i);
		h = Math.imul(h, 0x01000193) >>> 0;
	}
	out.canvasHash = `${h.toString(16)}:${data.length}`;
	const gl = document.createElement("canvas").getContext("webgl");
	if (gl) {
		const dbg = gl.getExtension("WEBGL_debug_renderer_info");
		out.webgl = {
			vendor: dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : null,
			renderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : null,
			maxTextureSize: gl.getParameter(gl.MAX_TEXTURE_SIZE),
			extensions: gl.getSupportedExtensions(),
		};
	} else {
		out.webgl = null;
	}
	const voices = await new Promise((resolve) => {
		const got = speechSynthesis.getVoices();
		if (got.length) return resolve(got);
		const t = setTimeout(() => resolve(speechSynthesis.getVoices()), 1500);
		speechSynthesis.onvoiceschanged = () => {
			clearTimeout(t);
			resolve(speechSynthesis.getVoices());
		};
	});
	out.voices = voices.map((v) => `${v.name}|${v.lang}|${v.default}|${v.localService}`);
	try {
		out.storageQuota = (await within(navigator.storage.estimate(), "storage.estimate")).quota;
	} catch (e) {
		out.storageQuota = `error: ${e}`;
	}
	out.media = {
		colorScheme: matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light",
		reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches,
	};
	try {
		const devices = await within(
			navigator.mediaDevices.enumerateDevices(),
			"enumerateDevices",
		);
		out.mediaDevices = devices.map((d) => d.kind).sort();
	} catch (e) {
		out.mediaDevices = `error: ${e}`;
	}
	try {
		out.permissionsGeo = (
			await within(navigator.permissions.query({ name: "geolocation" }), "permissions.query")
		).state;
	} catch (e) {
		out.permissionsGeo = `error: ${e}`;
	}
	out.historyLength = history.length;
	return out;
}
