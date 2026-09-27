/**
 * Ported from fpgen/trace.py (scrapfly/fingerprint-generator, Apache-2.0; see
 * ./NOTICE): the probability distribution of a target given conditions.
 */
import { RestrictiveConstraints, ValueError } from "./exceptions.js";
import { getModel } from "./model.js";
import {
	assertConditions,
	buildEvidence,
	type Conditions,
	type EvidenceMap,
	findRoots,
} from "./utils.js";

export class TraceResult {
	constructor(
		readonly value: any,
		readonly probability: number,
		/**
		 * The value's JSON as the model stores it (a TypeScript addition). It
		 * is the key of the node's lookup index, and JSON.parse cannot always
		 * give it back: 2**64 re-serialises as 18446744073709552000, where
		 * the store holds orjson's 1.8446744073709552e19.
		 */
		readonly text: string,
	) {}

	toString(): string {
		return `<${typeof this.value === "string" ? this.value : JSON.stringify(this.value)}: ${(this.probability * 100).toFixed(5)}%>`;
	}
}

/** Recursive result type for several targets. */
export interface TraceResultDict {
	[key: string]: TraceResult[] | TraceResultDict;
}

export interface TraceOptions {
	/** Return a flat {node: results} object for several targets. */
	flatten?: boolean;
}

/**
 * The probability distribution(s) of a target given conditions.
 *
 * One target resolving to one node -> TraceResult[] (most likely first);
 * otherwise an object of them.
 */
export function trace(
	target: string,
	conditions?: Conditions | null,
	options?: TraceOptions,
): TraceResult[] | TraceResultDict;
export function trace(
	target: readonly string[],
	conditions?: Conditions | null,
	options?: TraceOptions,
): TraceResultDict | TraceResult[];
export function trace(
	target: string | readonly string[],
	conditions?: Conditions | null,
	options: TraceOptions = {},
): TraceResult[] | TraceResultDict {
	return traceWithEvidence(target, conditions, options, new Map());
}

/** trace() with evidence inherited from a Generator (Python's __evidence__). */
export function traceWithEvidence(
	target: string | readonly string[],
	conditions: Conditions | null | undefined,
	{ flatten = false }: TraceOptions,
	evidence: EvidenceMap,
): TraceResult[] | TraceResultDict {
	assertConditions(conditions);
	getModel();

	if (conditions && Object.keys(conditions).length) {
		buildEvidence(conditions, evidence);
	}

	const targetTup = typeof target === "string" ? [target] : [...target];
	const targetRoots = findRoots(targetTup);

	if (!targetTup.length) {
		throw new ValueError("Please pass at least one valid target.");
	}

	// One target: return its results directly
	if (targetRoots.length === 1) return pullTarget(targetRoots[0], evidence);

	if (flatten) {
		const out: TraceResultDict = {};
		for (const root of targetRoots) out[root] = pullTarget(root, evidence);
		return out;
	}

	// NOTE: fpgen builds the intermediate dicts but then assigns every leaf at
	// the TOP level (`output[parts[-1]] = ...`, not `d[parts[-1]]`). Kept as-is
	// so the output has the same shape in both languages.
	const output: TraceResultDict = {};
	for (const root of targetRoots) {
		const parts = root.split(".");
		let d: TraceResultDict = output;
		for (const part of parts.slice(0, -1)) {
			if (!Object.hasOwn(d, part)) d[part] = {};
			d = d[part] as TraceResultDict;
		}
		output[parts[parts.length - 1]] = pullTarget(root, evidence);
	}
	return output;
}

function pullTarget(target: string, evidence: EvidenceMap): TraceResult[] {
	const model = getModel();
	const possibilities = model.network.trace(target, evidence);
	if (!possibilities.size) {
		throw new RestrictiveConstraints(
			`Restraints are too restrictive. No possible values for ${target}.`,
		);
	}
	const data = model.lookupValueList(possibilities.keys());
	const probs = [...possibilities.values()];
	const resp = data.map(
		(text, i) => new TraceResult(JSON.parse(text), probs[i], text),
	);
	// list.sort is stable, as is Array.prototype.sort.
	resp.sort((a, b) => b.probability - a.probability);
	return resp;
}
