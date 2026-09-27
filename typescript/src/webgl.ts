/**
 * WebGL identities, drawn from the Firefox devices fpgen has recorded.
 *
 * TypeScript twin of pythonlib/camoufox/webgl.py. Everything a page can read
 * from WebGL -- vendor, renderer, context attributes, extensions, parameters
 * and shader precisions, for WebGL1 and WebGL2 -- comes from one recorded
 * device. fpgen's `webgl` node is conditioned on the GPU, and `webgl2` on the
 * GPU and the `webgl` chosen for it, so a WebGL2 limit never contradicts its
 * WebGL1 counterpart.
 *
 * Every draw takes one seeded PyRandom, in a fixed order (GPU, then webgl,
 * then webgl2), so a seeded identity presents the same device in both
 * launchers.
 */
import { gpuFitsOs } from "./coherence.js";
import {
	FPGEN_OS,
	gpuScreenIsPlausible,
	isSoftwareRenderer,
} from "./fingerprints.js";
import { type TraceResult, traceWithEvidence } from "./fpgen/trace.js";
import { lookupPossibilities } from "./fpgen/utils.js";
import {
	comparePyStr,
	KeyError,
	orjsonDumps,
	parsePyJson,
	pyStr,
	pyStrRepr,
	ValueError,
} from "./pycompat.js";
import { PyRandom, type PySeed } from "./pyrandom.js";

export type TargetOS = "win" | "mac" | "lin";

/** The config keys a WebGL identity sets. */
export interface WebGLData {
	"webGl:vendor": string;
	"webGl:renderer": string;
	webGl2Enabled?: boolean;
	[key: string]: any;
}

// Extensions a release Firefox never exposes (draft extensions behind
// webgl.enable-draft-extensions, or mobile-only): fpgen's corpus carries some
// of them, and a spoofed list that names one is a tell on its own.
const NEVER_EXPOSED_EXTENSIONS: ReadonlySet<string> = new Set([
	"WEBGL_multi_draw",
	"WEBGL_clip_cull_distance",
	"EXT_texture_norm16",
	"WEBGL_compressed_texture_etc1",
]);

// OVR_multiview2 depends on the graphics backend: ANGLE's D3D11 backend has it
// on every Windows GPU, a Linux or macOS host driver may not, and the browser
// answers from the spoofed list without asking the host.
const HOST_DEPENDENT_EXTENSIONS: ReadonlySet<string> = new Set([
	"OVR_multiview2",
]);

// What Firefox reports under privacy.resistFingerprinting, which a Camoufox
// identity otherwise does not present.
const RFP_RENDERER = "Mozilla";

function filteredExtensions(targetOs: string): ReadonlySet<string> {
	if (targetOs === "win") return NEVER_EXPOSED_EXTENSIONS;
	return new Set([...NEVER_EXPOSED_EXTENSIONS, ...HOST_DEPENDENT_EXTENSIONS]);
}

function fpgenOs(targetOs: string): string {
	const name = FPGEN_OS[targetOs];
	if (name === undefined) throw new KeyError(pyStrRepr(targetOs));
	return name;
}

type Pin = readonly [node: string, index: string];

/**
 * Evidence fixing `node` to exactly the value stored as `text`.
 *
 * A dict passed to fpgen as a condition is flattened into one condition per
 * leaf, and each leaf replaces the node's evidence, so only the last one
 * applies. Pinning the value's own lookup index is exact.
 */
function pin(node: string, text: string): Pin {
	const index = lookupPossibilities(node, false)?.get(text);
	if (index === undefined) throw new KeyError(pyStrRepr(text));
	return [node, index];
}

const traceCache = new Map<string, readonly TraceResult[]>();

/** fpgen's distribution of `target` for Firefox on `targetOs`, in its order. */
function trace(
	target: string,
	targetOs: string,
	pinned: readonly Pin[] = [],
): readonly TraceResult[] {
	const key = JSON.stringify([target, targetOs, pinned]);
	let results = traceCache.get(key);
	if (!results) {
		results = traceWithEvidence(
			target,
			{ browser: "Firefox", os: fpgenOs(targetOs) },
			{},
			new Map(pinned.map(([node, index]) => [node, new Set([index])])),
		) as TraceResult[];
		traceCache.set(key, results);
	}
	return results;
}

function choose(rng: PyRandom, results: readonly TraceResult[]): TraceResult {
	return rng.choices(results, {
		weights: results.map((result) => result.probability),
	})[0];
}

/**
 * Every (vendor, renderer) that fpgen has seen Firefox report on this OS.
 *
 * A GPU outside this set has no recorded WebGL parameters behind it, so an
 * identity naming it could only borrow another device's.
 */
export function firefoxGpus(targetOs: string): Array<[string, string]> {
	return trace("gpu", targetOs.toLowerCase()).map((result) => [
		result.value.vendor,
		result.value.renderer,
	]);
}

function contextConfig(
	prefix: string,
	webgl: Record<string, any>,
	targetOs: string,
): Record<string, any> {
	const blocked = filteredExtensions(targetOs);
	return {
		[`${prefix}:contextAttributes`]: webgl.contextAttributes,
		[`${prefix}:supportedExtensions`]: (
			webgl.supportedExtensions as string[]
		).filter((extension) => !blocked.has(extension)),
		[`${prefix}:parameters`]: Object.fromEntries(
			Object.entries(webgl.params as Record<string, any>).map(
				([pname, param]) => [pname, param.value],
			),
		),
		[`${prefix}:shaderPrecisionFormats`]: Object.fromEntries(
			(webgl.shaderPrecisionFormats as Array<Record<string, any>>).map(
				(entry) => [
					`${entry.shaderType},${entry.precisionType}`,
					entry.shaderPrecisionFormat,
				],
			),
		),
	};
}

/**
 * fpgen's `webgl` and `webgl2` values as Camoufox config keys. `webgl2` is
 * `[]` for a device without WebGL2.
 *
 * Read the values with parsePyJson, as Python reads them, so an integral
 * float and an integer past 2**53 reach CAMOU_CONFIG as the same digits.
 */
export function toConfig(
	webgl: Record<string, any>,
	webgl2: any,
	targetOs: string,
): WebGLData {
	const hasWebgl2 = Array.isArray(webgl2)
		? webgl2.length > 0
		: Object.keys(webgl2 ?? {}).length > 0;
	const config: Record<string, any> = {
		"webGl:vendor": webgl.vendor,
		"webGl:renderer": webgl.renderer,
		...contextConfig("webGl", webgl, targetOs),
		webGl2Enabled: hasWebgl2,
	};
	if (hasWebgl2)
		Object.assign(config, contextConfig("webGl2", webgl2, targetOs));
	// The values are the trace's cached objects; the caller gets its own copy.
	return parsePyJson(orjsonDumps(config, false));
}

function webglConfig(
	targetOs: string,
	gpuText: string,
	rng: PyRandom,
): WebGLData {
	const gpuPin = pin("gpu", gpuText);
	const webgl = choose(rng, trace("webgl", targetOs, [gpuPin]));
	const webgl2 = choose(
		rng,
		trace("webgl2", targetOs, [gpuPin, pin("webgl", webgl.text)]),
	);
	return toConfig(parsePyJson(webgl.text), parsePyJson(webgl2.text), targetOs);
}

/**
 * The WebGL config of a device with this GPU, as Firefox on `targetOs`
 * reports it.
 *
 * @throws ValueError for a GPU fpgen has never seen Firefox report on that OS:
 * it has no recorded parameters, and another device's would contradict it.
 */
export function webglForGpu(
	targetOs: string,
	vendor: string,
	renderer: string,
	seed?: PySeed,
): WebGLData {
	const gpus = firefoxGpus(targetOs);
	if (!gpus.some(([v, r]) => v === vendor && r === renderer)) {
		const pairs = [...gpus]
			.sort((a, b) => comparePyStr(a[0], b[0]) || comparePyStr(a[1], b[1]))
			.map(([v, r]) => `(${pyStrRepr(v)}, ${pyStrRepr(r)})`);
		throw new ValueError(
			`No recorded WebGL data for vendor ${pyStrRepr(vendor)} and renderer ${pyStrRepr(renderer)} ` +
				`from Firefox on ${fpgenOs(targetOs)}. Possible pairs: [${pairs.join(", ")}]`,
		);
	}
	return webglConfig(
		targetOs,
		orjsonDumps({ vendor, renderer }, false),
		new PyRandom(seed),
	);
}

/**
 * Draw a GPU for a synthetic identity, weighted as fpgen records Firefox on
 * `targetOs`, and its WebGL config.
 *
 * Only GPUs the rest of the identity can stand beside are drawn: never a
 * software rasteriser, a GPU the OS cannot report, the resistFingerprinting
 * mask, or a discrete GPU behind a netbook panel. The screen is left alone:
 * it has already been reconciled with the real display and the window (#499).
 *
 * @throws ValueError when no recorded GPU fits.
 */
export function sampleWebglForScreen(
	targetOs: string,
	width?: number | null,
	height?: number | null,
	seed?: PySeed,
): WebGLData {
	const candidates = trace("gpu", targetOs).filter(
		(result) =>
			!isSoftwareRenderer(result.value.renderer) &&
			result.value.renderer !== RFP_RENDERER &&
			gpuFitsOs(result.value.renderer, targetOs) &&
			gpuScreenIsPlausible(result.value.renderer, width, height),
	);
	if (!candidates.length) {
		throw new ValueError(
			`No recorded ${targetOs} GPU fits a ${pyStr(width)}x${pyStr(height)} screen`,
		);
	}
	const rng = new PyRandom(seed);
	return webglConfig(targetOs, choose(rng, candidates).text, rng);
}
