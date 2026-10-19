/**
 * Helpers to find the user's public IP address for geolocation.
 *
 * TypeScript twin of python/src/camoufox/ip.py.
 */
import { isIPv4, isIPv6 } from "node:net";
import { Impit } from "impit";
import { InvalidIP, InvalidProxy } from "./exceptions.js";

export interface ProxyConfig {
	server: string;
	username?: string;
	password?: string;
	bypass?: string;
}

// biome-ignore lint/complexity/noStaticOnlyClass: these are the Python Proxy dataclass's methods; the data itself is ProxyConfig
export class ProxyHelper {
	/**
	 * Parses the proxy server string.
	 */
	static parseServer(server: string): {
		schema: string;
		url: string;
		port?: string;
	} {
		const proxyMatch = server.match(/^(?:(\w+):\/\/)?(.*?)(?::(\d+))?$/);
		if (!proxyMatch) {
			throw new InvalidProxy(`Invalid proxy server: ${server}`);
		}
		return {
			schema: proxyMatch[1] || "http",
			url: proxyMatch[2],
			port: proxyMatch[3],
		};
	}

	static asString(proxy: ProxyConfig): string {
		const { schema, url, port } = ProxyHelper.parseServer(proxy.server);
		let result = `${schema}://`;
		// Percent-encode the credentials: a raw `#`, `/`, `?` or `@` breaks the
		// URL, and a raw `%XX` is decoded into a different password.
		if (proxy.username) {
			result += encodeURIComponent(proxy.username);
			if (proxy.password) {
				result += `:${encodeURIComponent(proxy.password)}`;
			}
			result += "@";
		}
		result += url;
		if (port) {
			result += `:${port}`;
		}
		return result;
	}
}

export function validIPv4(ip: string | false): boolean {
	if (!ip) {
		return false;
	}
	return isIPv4(ip);
}

export function validIPv6(ip: string | false): boolean {
	if (!ip) {
		return false;
	}
	return isIPv6(ip);
}

export function validateIP(ip: string): void {
	if (!validIPv4(ip) && !validIPv6(ip)) {
		throw new InvalidIP(`Invalid IP address: ${ip}`);
	}
}

// Impit has no close/dispose API: each instance's native client (Tokio
// runtime resources, one UDP resolver socket) is only reclaimed when the
// JS wrapper is GC'd -- and V8 rarely collects the tiny wrappers, so
// per-call instances leak fds in long-running processes. Reuse instances
// via a small LRU keyed by proxy URL; evicted entries are reclaimed by GC.
const IMPIT_CACHE_MAX = 8;
const impitCache = new Map<string, Impit>();

// Probing the exit IP through a proxy adds a hop and a TLS handshake behind it;
// 5 s is not enough for a proxy that routes the long way round, and every URL
// timing out fails the whole launch. Direct probes keep 5 s.
export const DIRECT_IP_TIMEOUT_MS = 5000;
export const PROXIED_IP_TIMEOUT_MS = 15000;

function getImpit(proxy?: string): Impit {
	const key = proxy ?? "";
	const cached = impitCache.get(key);
	if (cached) {
		impitCache.delete(key);
		impitCache.set(key, cached);
		return cached;
	}
	// Certificates are verified (the Python twin's verify=True): an IP lookup
	// is what geoip trusts for the whole identity, so a MITM must not pick it.
	const impit = new Impit({
		proxyUrl: proxy,
		timeout: proxy ? PROXIED_IP_TIMEOUT_MS : DIRECT_IP_TIMEOUT_MS,
		ignoreTlsErrors: false,
	});
	impitCache.set(key, impit);
	if (impitCache.size > IMPIT_CACHE_MAX) {
		impitCache.delete(impitCache.keys().next().value as string);
	}
	return impit;
}

const PROXY_LOOKUP_FAILED =
	"Could not look up the proxy's exit IP and timezone. Pass webrtc_ip and " +
	"timezone_id explicitly to skip the lookup";

/**
 * The exit IP of `proxy` and that IP's timezone, looked up through the proxy.
 * Throws InvalidIP when the lookup fails: a context that silently kept the
 * host's WebRTC IP and timezone behind a proxy would be a leak.
 */
export async function proxyExitGeo(proxy: string): Promise<[string, string]> {
	let data: {
		status?: string;
		message?: string;
		query?: string;
		timezone?: string;
	};
	try {
		const response = await getImpit(proxy).fetch(
			"http://ip-api.com/json?fields=status,message,query,timezone",
		);
		if (!response.ok) {
			throw new Error(`${response.status} Error: ${response.statusText}`);
		}
		data = await response.json();
	} catch (error) {
		throw new InvalidIP(`${PROXY_LOOKUP_FAILED}: ${error}`);
	}
	if (data.status !== "success" || !data.query || !data.timezone) {
		throw new InvalidIP(
			`${PROXY_LOOKUP_FAILED}: ${data.message ?? JSON.stringify(data)}`,
		);
	}
	validateIP(data.query);
	return [data.query, data.timezone];
}

const PUBLIC_IP_URLS = [
	// Prefers IPv4
	"https://api.ipify.org",
	"https://checkip.amazonaws.com",
	"https://ipinfo.io/ip",
	// IPv4 & IPv6
	"https://icanhazip.com",
	"https://ifconfig.co/ip",
	"https://ipecho.net/plain",
];

// The Python twin memoizes public_ip() with lru_cache; mirror that so repeated
// launches through the same proxy don't re-hit the API endpoints.
const publicIPCache = new Map<string, Promise<string>>();

let publicIPv6Pending: Promise<string | null> | undefined;

/**
 * This host's public IPv6 address, or null when it has none it can reach the
 * internet from. The hosts have AAAA records only, so an answer proves the route.
 */
export function publicIPv6(): Promise<string | null> {
	publicIPv6Pending ??= resolvePublicIPv6();
	return publicIPv6Pending;
}

async function resolvePublicIPv6(): Promise<string | null> {
	for (const url of ["https://api6.ipify.org", "https://v6.ident.me"]) {
		let ip: string;
		try {
			const response = await getImpit().fetch(url);
			if (!response.ok) {
				continue;
			}
			ip = (await response.text()).trim();
		} catch {
			continue;
		}
		if (validIPv6(ip)) {
			return ip;
		}
	}
	return null;
}

/**
 * Sends a request to a public IP api.
 */
export function publicIP(proxy?: string): Promise<string> {
	const key = proxy ?? "";
	const cached = publicIPCache.get(key);
	if (cached) {
		return cached;
	}
	const pending = resolvePublicIP(proxy).catch((error) => {
		// Never cache a failure: the next launch should retry.
		publicIPCache.delete(key);
		throw error;
	});
	publicIPCache.set(key, pending);
	return pending;
}

async function resolvePublicIP(proxy?: string): Promise<string> {
	let endException: unknown;

	for (const url of PUBLIC_IP_URLS) {
		try {
			const response = await getImpit(proxy).fetch(url);
			if (!response.ok) {
				// requests' raise_for_status()
				throw new Error(
					`${response.status} Error: ${response.statusText} for url: ${url}`,
				);
			}
			const ip = (await response.text()).trim();
			validateIP(ip);
			return ip;
		} catch (error) {
			endException = error;
			if (process.env.CAMOUFOX_DEBUG) {
				console.warn(
					new InvalidProxy(
						`camoufox(warn): Failed to fetch public IP from ${url}, retrying with another URL...`,
						{ cause: error },
					),
				);
			}
		}
	}

	const detail =
		endException instanceof Error ? endException.message : String(endException);
	throw new InvalidIP(`Failed to get IP address: ${detail}`, {
		cause: endException,
	});
}
