/**
 * Leak and fallback warnings, and the warning channel the launcher reports through.
 *
 * TypeScript twin of pythonlib/camoufox/_warnings.py. The messages are read
 * from the same warnings.yml the Python package ships, so both launchers say
 * the same thing.
 *
 * Python routes these through the `warnings` module; the Node equivalent is
 * `process.emitWarning`, which prints `(node:<pid>) <Category>: <message>` to
 * stderr and fires `process.on("warning")`. Python's
 * `warnings.catch_warnings(record=True)` is `recordWarnings()` here.
 */
import { AsyncLocalStorage } from "node:async_hooks";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { parse as parseYaml } from "yaml";
import { LIBRARY_VERSION } from "./__version__.js";
import { CamoufoxNotInstalled } from "./exceptions.js";
import { LOCAL_DATA } from "./paths.js";
import { installedVerStr } from "./pkgman.js";

let warningsData: Record<string, string> | undefined;

/** warnings.yml, loaded once. */
export function loadWarnings(): Record<string, string> {
	warningsData ??= parseYaml(
		fs.readFileSync(path.join(LOCAL_DATA, "warnings.yml"), "utf-8"),
	) as Record<string, string>;
	return warningsData;
}

export interface RecordedWarning {
	category: string;
	message: string;
}

const recorder = new AsyncLocalStorage<RecordedWarning[]>();

/**
 * Emit a warning. While a `recordWarnings()` block is active the warning is
 * captured instead of printed, as Python's catch_warnings(record=True) does.
 */
export function warn(message: string, category = "RuntimeWarning"): void {
	const captured = recorder.getStore();
	if (captured) {
		captured.push({ category, message });
		return;
	}
	process.emitWarning(message, { type: category });
}

/**
 * Run `fn`, capturing every warning it emits (sync or async) instead of
 * printing it. Scoped by AsyncLocalStorage, so concurrent work outside the
 * block is not captured; nested blocks capture into the innermost one.
 */
export async function recordWarnings<T>(
	fn: () => T | Promise<T>,
): Promise<{ result?: T; error?: unknown; warnings: RecordedWarning[] }> {
	const captured: RecordedWarning[] = [];
	try {
		return { result: await recorder.run(captured, fn), warnings: captured };
	} catch (error) {
		return { error, warnings: captured };
	}
}

/**
 * Emitted when a caller has a setting enabled that can cause detection.
 */
export class LeakWarning extends Error {
	constructor(message: string) {
		super(message);
		this.name = "LeakWarning";
	}

	/**
	 * Warns the caller if a passed parameter can cause leaks.
	 */
	static warn(warningKey: string, iKnowWhatImDoing?: boolean): void {
		let warning = loadWarnings()[warningKey];
		if (iKnowWhatImDoing) {
			return;
		}
		if (iKnowWhatImDoing !== undefined) {
			warning += "\nIf this is intentional, pass `i_know_what_im_doing=True`.";
		}
		warn(warning, "LeakWarning");
	}
}

function browserVersion(): string {
	try {
		return installedVerStr();
	} catch (error) {
		if (error instanceof CamoufoxNotInstalled) return "not installed";
		throw error;
	}
}

/**
 * Emitted when part of an identity could not be drawn and a substitute was used.
 */
export class FallbackWarning extends Error {
	constructor(message: string) {
		super(message);
		this.name = "FallbackWarning";
	}

	/**
	 * Warns that `what` failed with `error` and the identity uses `instead`,
	 * with a block of versions and the error for the user to paste into an issue.
	 */
	static warn(
		what: string,
		instead: string,
		error: unknown,
		identity?: string | null,
	): void {
		const lines = [
			`camoufox: ${LIBRARY_VERSION} (npm)`,
			`browser: ${browserVersion()}`,
			`os: ${os.type()}-${os.release()}-${os.arch()}`,
			`node: ${process.versions.node}`,
			`error: ${error instanceof Error ? `${error.name}: ${error.message}` : String(error)}`,
		];
		if (identity) lines.push(`identity: ${identity}`);
		const values: Record<string, string> = {
			what,
			instead,
			report: lines.map((line) => `    ${line}`).join("\n"),
		};
		warn(
			loadWarnings().fallback.replace(
				/\{(what|instead|report)\}/g,
				(_, key: string) => values[key],
			),
			"FallbackWarning",
		);
	}
}
