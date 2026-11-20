/**
 * Proxy credentials for Juggler: the SOCKS5 username and password Playwright
 * refuses to pass. The proxy and public-IP lookups are camoucore's (camoucore/ip.js).
 *
 * TypeScript twin of python/src/camoufox/ip.py.
 */
import type { ProxyConfig } from "camoucore/ip.js";
import { InvalidProxy } from "./exceptions.js";

export interface ProxyAuth {
	host: string;
	port: number | null;
	username: string;
	password: string;
}

/**
 * Splits a SOCKS5 proxy's username and password from what Playwright is given.
 *
 * Playwright refuses a `socks5://` proxy that has a username ("Browser does
 * not support socks5 proxy authentication"), but Juggler can send them
 * (RFC 1929). Returns the proxy without its credentials, and the credentials
 * with the proxy's host and port, for Juggler; or the proxy unchanged and
 * null when it is not SOCKS5 or has no credentials.
 */
export function socks5Auth<T extends ProxyConfig | undefined | null>(
	proxy: T,
): [T, ProxyAuth | null] {
	if (!proxy || !(proxy.username || proxy.password)) return [proxy, null];
	const server = String(proxy.server ?? "");
	// As Playwright reads the server: without a scheme, it is an HTTP proxy.
	let url: URL;
	try {
		url = new URL(server.includes("://") ? server : `http://${server}`);
	} catch (error) {
		throw new InvalidProxy(`Invalid proxy server: ${server}`, { cause: error });
	}
	if (url.protocol.toLowerCase() !== "socks5:" || !url.hostname)
		return [proxy, null];
	const { username, password, ...bare } = proxy;
	return [
		bare as T,
		{
			host: url.hostname.replace(/^\[(.*)\]$/, "$1"),
			port: url.port ? Number(url.port) : null,
			username: username || "",
			password: password || "",
		},
	];
}

/**
 * The environment variable that carries a launch-level SOCKS5 proxy's
 * credentials to Juggler (TargetRegistry.js), which clears it once read.
 */
export const PROXY_AUTH_ENV = "CAMOU_PROXY_AUTH";

/** The environment that hands a launch-level proxy's credentials to Juggler. */
export function proxyAuthEnv(auth: ProxyAuth): Record<string, string> {
	return { [PROXY_AUTH_ENV]: JSON.stringify(auth) };
}

/**
 * The init script that hands a context's SOCKS5 credentials to Juggler.
 *
 * Juggler takes it out of the context's init scripts (TargetRegistry.js), so
 * it never reaches a page or a content process. It is valid JavaScript that
 * does nothing, should a browser without that support run it.
 */
export function proxyAuthInitScript(auth: ProxyAuth): string {
	return `camoufoxProxyAuth: (${JSON.stringify(auth)});`;
}
