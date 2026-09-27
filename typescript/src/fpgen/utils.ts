/**
 * Ported from fpgen/utils.py (scrapfly/fingerprint-generator, Apache-2.0; see
 * ./NOTICE): condition parsing (build_evidence), query(), and the helpers that
 * walk node names up and down the network and assemble output.
 *
 * Conditions, in JS terms (Python's kwargs become one object):
 *   - a plain object is flattened into dotted keys, like a Python dict;
 *   - a function is a predicate. NOTE, as in Python: it is called with the
 *     value parsed from the CASEFOLDED JSON, so strings arrive lowercased
 *     (`os: (v) => v === "windows"`, not "Windows");
 *   - a Set is a list of alternatives (Python's set/tuple). An array is one
 *     value, as a Python list is;
 *   - anything else is one JSON value; `undefined` means "no condition".
 *
 * One deliberate deviation: Python matches a plain value by comparing
 * orjson.dumps(value) with the stored JSON text, so `1.0` only matches "1.0".
 * JS cannot write 1.0, so when the exact text finds nothing the lookup falls
 * back to comparing the re-serialised stored value. That only ever turns a
 * Python InvalidConstraints into a match on the numerically equal value.
 */
import type { BayesianNetwork } from "./bayesian-network.js";
import {
	InvalidConstraints,
	InvalidNode,
	NodePathError,
	RestrictiveConstraints,
	ValueError,
} from "./exceptions.js";
import { type FpgenModel, getModel } from "./model.js";
import {
	casefold,
	isPlainObject,
	parsePyTyped,
	pyCompare,
	pyDumps,
	pyEquals,
	pyTypeName,
	unwrapPy,
} from "./pyjson.js";

/** A predicate over a (casefolded, parsed) node value. */
export type Predicate = (value: any) => unknown;
export type ConditionValue = unknown;
/** Conditions for generation / tracing. See the module header. */
export type Conditions = Record<string, ConditionValue>;
/** Evidence: node name -> allowed value ids, in insertion order. */
export type EvidenceMap = Map<string, Set<string>>;

export function model(): FpgenModel {
	return getModel();
}

function network(): BayesianNetwork {
	return getModel().network;
}

/**
 * Query the possible values of a target.
 *
 * @param target  a node, a path inside a node's value, or a prefix of nodes
 * @param options.flatten  flatten the output dictionary
 * @param options.sort     sort the output arrays
 */
export function query(
	target: string,
	{ flatten = false, sort = false }: { flatten?: boolean; sort?: boolean } = {},
): Record<string, any> | any[] {
	getModel();
	return unwrapPy(queryTyped(target, flatten, sort)) as
		| Record<string, any>
		| any[];
}

function queryTyped(target: string, flatten: boolean, sort: boolean): unknown {
	// Check node list first
	const values = lookupPossibilities(target, false);
	if (values?.size) {
		const output = [...values.keys()].map(parsePyTyped);
		// Merge dicts if the data is all dicts, else return a deduped list
		if (output.every(isPlainObject)) {
			return maybeFlatten(flatten, mergeDicts(output, sort));
		}
		return dedupe(output, sort);
	}

	// Target is within a node: look up the tree
	const nestedKeys: string[] = [];
	const rootData = lookupRootPossibilities(target, {
		nestedKeys,
		noneIfMissing: true,
		casefold: false,
	});
	if (rootData !== null) {
		const output = [...rootData[1].keys()].map((d) =>
			atPath(parsePyTyped(d), nestedKeys),
		);
		if (output.every(isPlainObject)) {
			return maybeFlatten(flatten, mergeDicts(output, sort));
		}
		return dedupe(output, sort);
	}

	// Search down the tree
	const data = searchDownward(target);
	const resp = new Map<string, unknown[]>();
	for (const key of data) {
		const stripped = key.startsWith(`${target}.`)
			? key.slice(target.length + 1)
			: key;
		resp.set(
			stripped,
			[...(lookupPossibilities(key, false)?.keys() ?? [])].map(parsePyTyped),
		);
	}
	if (flatten) {
		const deduped: Record<string, unknown> = {};
		for (const [node, vals] of resp) deduped[node] = dedupe(vals, sort);
		return flattenDict(deduped);
	}
	return unflatten(resp, sort);
}

/* Helpers for searching for nodes up/down the network */

/** The value at a nested path (_at_path). Throws NodePathError(key). */
export function atPath(
	data: unknown,
	pathKeys: Iterable<string>,
	{ casefold: fold = false }: { casefold?: boolean } = {},
): any {
	let cur: any = data;
	for (const key of pathKeys) {
		if (!isPlainObject(cur)) throw new NodePathError(key);
		if (fold) {
			// CaseInsensitiveDict(data)[key]: last colliding key wins.
			const want = casefold(key);
			let found = false;
			let value: unknown;
			for (const k of Object.keys(cur)) {
				if (casefold(k) === want) {
					found = true;
					value = cur[k];
				}
			}
			if (!found) throw new NodePathError(key);
			cur = value;
		} else {
			if (!Object.hasOwn(cur, key)) throw new NodePathError(key);
			cur = cur[key];
		}
	}
	return cur;
}

/**
 * Find the first node that is a prefix of `key` and return [node, its
 * possibilities]. `nestedKeys` receives the remaining path.
 */
export function lookupRootPossibilities(
	key: string,
	{
		nestedKeys,
		casefold: fold = true,
		noneIfMissing = false,
	}: {
		nestedKeys?: string[];
		casefold?: boolean;
		noneIfMissing?: boolean;
	} = {},
): [string, Map<string, string>] | null {
	if (!key) throw new InvalidNode("Key cannot be empty.");
	let possibleValues: Map<string, string> | null = null;
	while (key) {
		const cut = key.lastIndexOf(".");
		// Ran out of keys to parse
		if (cut === -1) {
			if (noneIfMissing) return null;
			throw new InvalidNode(`${key} is not a valid node`);
		}
		const sliced = key.slice(cut + 1);
		key = key.slice(0, cut);
		nestedKeys?.push(sliced);

		possibleValues = lookupPossibilities(key, fold);
		if (possibleValues !== null) break;
	}
	if (possibleValues === null) {
		if (noneIfMissing) return null;
		throw new InvalidNode(`${key} is not a valid node`);
	}
	nestedKeys?.reverse();
	return [key, possibleValues];
}

/**
 * The possible values of a node as {value JSON text: value id}, or null when
 * the node doesn't exist. `fold` casefolds the text (the default, as in fpgen).
 */
export function lookupPossibilities(
	nodeName: string,
	fold = true,
): Map<string, string> | null {
	const node = network().nodesByName.get(nodeName);
	if (!node) return null;
	const lookupValues = node.possibleValues;
	const actual = model().lookupValueList(lookupValues);
	const out = new Map<string, string>();
	actual.forEach((text, i) => {
		out.set(fold ? casefold(text) : text, lookupValues[i]);
	});
	return out;
}

/** All (original-cased) node names under `domain`. Throws when there are none. */
export function searchDownward(domain: string): string[] {
	const net = network();
	const found: string[] = [];
	let i = 0;
	for (const node of net.nodesByName.keys()) {
		const n = i++;
		if (!node.startsWith(domain)) continue;
		if (node.length > domain.length && node[domain.length] !== ".") continue;
		found.push(net.nodeNames[n]);
	}
	if (!found.length) throw new InvalidNode(`Unknown node: "${domain}"`);
	return found;
}

/** The nodes that make up each target's data (_find_roots). */
export function findRoots(targets: Iterable<string>): string[] {
	const net = network();
	const out: string[] = [];
	for (const t of targets) {
		let target = casefold(t);
		while (true) {
			// Found a valid target
			if (net.nodesByName.has(target)) {
				out.push(target);
				break;
			}
			const cut = target.lastIndexOf(".");
			if (cut !== -1) {
				target = target.slice(0, cut);
				continue;
			}
			// At the root key: find nodes below it before giving up
			out.push(...searchDownward(target));
			break;
		}
	}
	return out;
}

export function reassembleTargets(
	targets: readonly string[],
	fingerprint: Record<string, any>,
): Record<string, any> {
	const result: Record<string, any> = {};
	for (const target of targets) {
		try {
			result[target] = atPath(fingerprint, target.split("."), {
				casefold: true,
			});
		} catch (e) {
			if (e instanceof NodePathError) {
				throw new InvalidNode(
					`'${target}' is not a valid key path (missing ${e.message}).`,
				);
			}
			throw e;
		}
	}
	return result;
}

/* Miscellaneous list/dict helpers */

/** Group items by Python type, dedupe each group, order groups by type name. */
export function dedupe(list: Iterable<unknown>, sort: boolean): unknown[] {
	const groups = new Map<string, unknown[]>();
	for (const item of list) {
		const t = pyTypeName(item);
		let group = groups.get(t);
		if (!group) {
			group = [];
			groups.set(t, group);
		}
		if (!group.some((g) => pyEquals(g, item))) group.push(item);
	}
	const result: unknown[] = [];
	for (const t of [...groups.keys()].sort(pyCompare)) {
		const items = groups.get(t) as unknown[];
		if (!sort || t === "list" || t === "dict") result.push(...items);
		else result.push(...[...items].sort(pyCompare));
	}
	return result;
}

function unflatten(
	dictionary: Map<string, unknown>,
	sort: boolean,
): Record<string, any> {
	const result: Record<string, any> = {};
	for (const [key, raw] of dictionary) {
		const parts = key.split(".");
		let d = result;
		for (const part of parts.slice(0, -1)) {
			if (!Object.hasOwn(d, part)) d[part] = {};
			d = d[part];
		}
		d[parts[parts.length - 1]] = Array.isArray(raw) ? dedupe(raw, sort) : raw;
	}
	return result;
}

/** Turn a nested dictionary into a flattened one (dotted keys). */
export function flattenDict(
	dictionary: Record<string, any>,
	parentKey = "",
): Record<string, any> {
	const items: Record<string, any> = {};
	for (const [key, value] of Object.entries(dictionary)) {
		const newKey = parentKey ? `${parentKey}.${key}` : key;
		if (isPlainObject(value)) Object.assign(items, flattenDict(value, newKey));
		else items[newKey] = value;
	}
	return items;
}

export function maybeFlatten(flatten: boolean | undefined, data: any): any {
	if (!isPlainObject(data)) return data;
	return flatten ? flattenDict(data) : data;
}

/**
 * Merge a list of dicts: dict values merge recursively, list values are
 * concatenated and deduped, anything else is deduped.
 */
function mergeDicts(
	dictList: Record<string, unknown>[],
	sort: boolean,
): Record<string, any> {
	if (!dictList.length) return {};
	const merged: Record<string, any> = {};
	const allKeys = new Set<string>();
	for (const d of dictList) for (const k of Object.keys(d)) allKeys.add(k);
	for (const key of allKeys) {
		const values = dictList
			.filter((d) => Object.hasOwn(d, key))
			.map((d) => d[key]);
		if (values.every(isPlainObject)) {
			merged[key] = mergeDicts(values as Record<string, unknown>[], sort);
		} else if (values.every(Array.isArray)) {
			merged[key] = dedupe((values as unknown[][]).flat(), sort);
		} else {
			merged[key] = dedupe(values, sort);
		}
	}
	return merged;
}

/* Parse user input */

/** A flattened condition: one JSON text, a predicate, or alternatives. */
type FlatCondition = string | Predicate | readonly (string | Predicate)[];

/** Flatten nested conditions into dotted keys (_flatten_conditions). */
export function flattenConditions(
	dictionary: Record<string, unknown>,
	parentKey = "",
	fold = false,
): Map<string, FlatCondition> {
	const items = new Map<string, FlatCondition>();
	for (const [key, value] of Object.entries(dictionary)) {
		if (value === undefined) continue;
		let newKey = parentKey ? `${parentKey}.${key}` : key;
		if (isPlainObject(value)) {
			// As in Python, the recursion does not casefold.
			for (const [k, v] of flattenConditions(value, newKey)) items.set(k, v);
			continue;
		}
		let flat: FlatCondition;
		if (value instanceof Set) {
			// A set (Python: set/tuple) is a list of alternatives.
			flat = [...value].map((v) => pyDumps(v));
		} else if (typeof value === "function") {
			flat = value as Predicate;
		} else {
			flat = pyDumps(value);
		}
		if (fold) newKey = casefold(newKey);
		items.set(newKey, flat);
	}
	return items;
}

function describe(val: unknown): string {
	if (typeof val === "function") {
		return `<function ${val.name || "<anonymous>"}>`;
	}
	return String(val);
}

/**
 * Turn user conditions into evidence (node -> allowed value ids), validating
 * them against the network. Mutates `evidence`.
 */
export function buildEvidence(
	conditions: Record<string, unknown>,
	evidence: EvidenceMap,
	strict?: boolean | null,
): void {
	if (strict == null) strict = true;
	const net = network();

	// Flatten to match the format of the fingerprint network
	const flat = flattenConditions(conditions, "", true);

	for (let [key, value] of flat) {
		let possibleValues = lookupPossibilities(key);

		// Handle nested keys
		let nestedKeys: string[] = [];
		if (possibleValues === null) {
			[key, possibleValues] = lookupRootPossibilities(key, {
				nestedKeys,
			}) as [string, Map<string, string>];
		}
		// Get the real name for the key
		key = net.node(key).name;

		const allowed = new Set<string>();
		evidence.set(key, allowed);

		const alternatives: readonly (string | Predicate)[] =
			typeof value === "string" || typeof value === "function"
				? [value]
				: value;

		for (const valueCon of alternatives) {
			// Read the passed value
			const val: unknown =
				typeof valueCon === "function"
					? valueCon
					: JSON.parse(casefold(valueCon));

			// Nested keys: keep the possible values whose value at the nested
			// path matches.
			if (nestedKeys.length) {
				nestedKeys = nestedKeys.map(casefold);
				for (const [possValue, lookupIndex] of possibleValues) {
					const outputtedPossible = JSON.parse(possValue);
					let targetValue: unknown;
					try {
						targetValue = atPath(outputtedPossible, nestedKeys);
					} catch (e) {
						if (e instanceof NodePathError) continue; // bad data
						throw e;
					}
					if (typeof val === "function" && val(targetValue)) {
						allowed.add(lookupIndex);
					} else if (pyEquals(targetValue, val)) {
						allowed.add(lookupIndex);
					}
				}
				if (!allowed.size) {
					if (typeof val === "function") {
						throw new InvalidConstraints(
							`The passed function (${describe(val)}) yielded no possible values for "${key}" ` +
								`at "${nestedKeys.join(".")}"`,
						);
					}
					throw new InvalidConstraints(
						`${describe(valueCon)} is not a possible value for "${key}" ` +
							`at "${nestedKeys.join(".")}"`,
					);
				}
				continue;
			}

			// ===== NON NESTED VALUE HANDLING =====

			if (typeof val === "function") {
				let found = false;
				for (const [possibleVal, lookupIndex] of possibleValues) {
					if (val(JSON.parse(possibleVal))) {
						allowed.add(lookupIndex);
						found = true;
					}
				}
				if (!found) {
					throw new InvalidConstraints(
						`The passed function (${describe(val)}) yielded no possible values for "${key}"`,
					);
				}
				continue;
			}

			// Non nested values: look the JSON text up directly
			const wanted = casefold(valueCon as string);
			let lookupIndex = possibleValues.get(wanted);
			if (lookupIndex === undefined) {
				// JS has no 1.0; compare against the re-serialised stored value.
				for (const [possibleVal, idx] of possibleValues) {
					if (JSON.stringify(JSON.parse(possibleVal)) === wanted) {
						lookupIndex = idx;
						break;
					}
				}
			}
			if (lookupIndex === undefined) {
				throw new InvalidConstraints(
					`${describe(valueCon)} is not a possible value for "${key}"`,
				);
			}
			allowed.add(lookupIndex);
		}
	}

	// Validate the evidence (or, when not strict, relax it once). fpgen drops
	// the FIRST key and does not re-validate; so does this.
	try {
		net.validateEvidence(evidence);
	} catch (e) {
		if (strict || !(e instanceof RestrictiveConstraints)) {
			throw e;
		}
		const first = evidence.keys().next();
		if (!first.done) evidence.delete(first.value);
	}
}

/** Conditions must be a plain object when given (_assert_dict_xor_kwargs). */
export function assertConditions(conditions: unknown): void {
	if (conditions == null) return;
	if (!isPlainObject(conditions)) {
		throw new ValueError(
			"Invalid argument. Constraints must be passed as kwargs or as a dictionary.",
		);
	}
}

/* Convert network output to human readable output */

/** Unflatten (or flatten) a sampled {node: value id} into the output object. */
export function makeOutputDict(
	data: Map<string, string>,
	flatten: boolean | undefined,
): Record<string, any> {
	const keys = [...data.keys()];
	const values = model().lookupValueList(data.values());
	if (flatten) {
		const flat: Record<string, any> = {};
		keys.forEach((k, i) => {
			flat[k] = JSON.parse(values[i]);
		});
		// Flatten node values that themselves are dicts
		return flattenDict(flat);
	}
	const result: Record<string, any> = {};
	keys.forEach((key, i) => {
		const parts = key.split(".");
		let d = result;
		for (const part of parts.slice(0, -1)) {
			if (!Object.hasOwn(d, part)) d[part] = {};
			d = d[part];
		}
		d[parts[parts.length - 1]] = JSON.parse(values[i]);
	});
	return result;
}
