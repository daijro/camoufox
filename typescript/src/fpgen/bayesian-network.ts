/**
 * Ported from fpgen/bayesian_network.py (scrapfly/fingerprint-generator,
 * Apache-2.0; see ./NOTICE).
 *
 * The inference is a line-for-line port: the same beam search, the same
 * BEAM_WIDTH, the same multiplication order, the same stable top-k pruning.
 * `trace()` therefore returns bit-identical probabilities to Python (the tests
 * compare them). Only the draws differ, because Python uses `random.random()`
 * and this uses `Math.random()`.
 *
 * Kept on purpose, because they change results:
 *  - probability tables are Maps in document order (see pyjson.ts);
 *  - validate_evidence passes a single *string* as the allowed values, and
 *    Python's `value in "abc"` is a substring test. `isAllowed` reproduces it,
 *    so the same condition sets are rejected in both languages.
 *
 * Not ported: get_distribution_for_node, get_shared_possibilities,
 * _intersect_parents and collect_parents. Nothing in fpgen calls them (the
 * docstring marks get_shared_possibilities deprecated since 1.3.0).
 */
import { RestrictiveConstraints } from "./exceptions.js";
import { casefold } from "./pyjson.js";

/** Width for beam search. Cuts off values that are way too low or contaminated. */
export const BEAM_WIDTH = 1000;

/** A conditional probability table: parent value -> ... -> value -> p. */
export type CPT = Map<string, CPT | number>;
/** A distribution over value ids, in insertion order (Python dict order). */
export type Distribution = Map<string, number>;
/** Allowed value ids for a node. A bare string is Python's `str` (substring `in`). */
export type Allowed = ReadonlySet<string> | string;
export type Evidence = ReadonlyMap<string, Allowed>;

/** Anything that can turn value ids into their stored JSON text. */
export interface ValueLookup {
	lookupValueList(indexList: Iterable<string>): string[];
}

function isAllowed(allowed: Allowed, value: string): boolean {
	return typeof allowed === "string"
		? allowed.includes(value)
		: allowed.has(value);
}

function sumValues(dist: Distribution): number {
	let total = 0;
	for (const p of dist.values()) total += p;
	return total;
}

/** A single node in the network, with its conditional probability table. */
export class BayesianNode {
	readonly name: string;
	readonly parentNames: readonly string[];
	readonly possibleValues: readonly string[];
	readonly probabilities: CPT;

	constructor(
		readonly nodeDefinition: Map<string, unknown>,
		readonly index: number,
	) {
		this.name = nodeDefinition.get("name") as string;
		this.parentNames = nodeDefinition.get("parentNames") as string[];
		this.possibleValues = nodeDefinition.get("possibleValues") as string[];
		this.probabilities = nodeDefinition.get("conditionalProbabilities") as CPT;
	}

	/** This node's value probabilities given its parents' values. */
	getProbabilitiesGivenKnownValues(
		parentValues: ReadonlyMap<string, string>,
	): Distribution {
		let probabilities: CPT = this.probabilities;
		for (const parentName of this.parentNames) {
			const parentValue = parentValues.get(parentName) as string;
			const next = probabilities.get(parentValue);
			probabilities = next instanceof Map ? next : new Map();
		}
		return probabilities as Distribution;
	}
}

/** Map with casefolded string keys (structs.CaseInsensitiveDict). */
export class CaseInsensitiveMap<V> extends Map<string, V> {
	override get(key: string): V | undefined {
		return super.get(casefold(key));
	}
	override set(key: string, value: V): this {
		return super.set(casefold(key), value);
	}
	override has(key: string): boolean {
		return super.has(casefold(key));
	}
	override delete(key: string): boolean {
		return super.delete(casefold(key));
	}
}

interface BeamEntry {
	/** Assigned value ids, aligned with the trace's ordered node list. */
	readonly values: string[];
	readonly prob: number;
}

export class BayesianNetwork {
	readonly nodesInSamplingOrder: BayesianNode[];
	readonly nodesByName: CaseInsensitiveMap<BayesianNode>;
	/** The original (cased) node names, in sampling order. */
	readonly nodeNames: readonly string[];
	readonly ancestorsByName = new Map<string, Set<string>>();

	constructor(
		networkDefinition: unknown,
		readonly values: ValueLookup,
	) {
		const nodes = (networkDefinition as Map<string, unknown>).get(
			"nodes",
		) as Map<string, unknown>[];
		this.nodesInSamplingOrder = nodes.map(
			(def, index) => new BayesianNode(def, index),
		);
		// dict comprehension: a later duplicate name replaces the node but keeps
		// the first one's position.
		const byName = new Map<string, BayesianNode>();
		for (const node of this.nodesInSamplingOrder) byName.set(node.name, node);
		this.nodesByName = new CaseInsensitiveMap<BayesianNode>();
		for (const [name, node] of byName) this.nodesByName.set(name, node);
		this.nodeNames = [...byName.keys()];
		for (const node of this.nodesInSamplingOrder) {
			this.getAllAncestors(node.name);
		}
	}

	/** Look up a node by (case-insensitive) name; KeyError -> Error. */
	node(name: string): BayesianNode {
		const node = this.nodesByName.get(name);
		if (!node) throw new Error(`KeyError: '${casefold(name)}'`);
		return node;
	}

	/** Generate a full sample from the network. */
	generateConsistentSample(
		evidence: ReadonlyMap<string, ReadonlySet<string>>,
	): Map<string, string> | null {
		const result = new Map<string, string>();
		// A working copy of the evidence, updated in place.
		const currentEvidence = new Map<string, Allowed>();
		for (const [k, v] of evidence) currentEvidence.set(k, new Set(v));

		for (const node of this.nodesInSamplingOrder) {
			const nodeName = node.name;
			let sampledValue: string;

			const allowedValues = currentEvidence.get(nodeName);
			if (allowedValues !== undefined) {
				// Explicit evidence: leave the node itself out of the beam search.
				const searchEvidence = new Map(currentEvidence);
				searchEvidence.delete(nodeName);
				const distribution = this.trace(nodeName, searchEvidence);

				// Filter the distribution to allowed values and renormalize.
				let filtered: Distribution = new Map();
				for (const [k, v] of distribution) {
					if (isAllowed(allowedValues, k)) filtered.set(k, v);
				}
				if (filtered.size === 0 || sumValues(filtered) <= 0) {
					// Only ever a Set here: it came from build_evidence or from
					// a sampled value.
					const allowed = allowedValues as ReadonlySet<string>;
					const uniform = 1.0 / allowed.size;
					filtered = new Map([...allowed].map((v) => [v, uniform]));
				} else {
					const total = sumValues(filtered);
					for (const [k, v] of filtered) filtered.set(k, v / total);
				}
				sampledValue = this.sampleValueFromDistribution(filtered);
			} else {
				// Unconstrained node: use all current evidence.
				const distribution = this.trace(nodeName, currentEvidence);
				sampledValue = this.sampleValueFromDistribution(distribution);
			}

			result.set(nodeName, sampledValue);
			// Update current evidence with the newly sampled value.
			currentEvidence.set(nodeName, new Set([sampledValue]));
		}
		return result;
	}

	/** Generate values for target nodes given conditions. */
	generateCertainNodes(
		evidence: ReadonlyMap<string, ReadonlySet<string>>,
		targets?: Iterable<string> | null,
	): Map<string, string> | null {
		// If no target specified, generate full sample
		if (targets == null) return this.generateConsistentSample(evidence);

		const result = new Map<string, string>();
		for (const targetNode of targets) {
			let distribution = this.trace(targetNode, evidence);

			// Handle multi-value conditions for the target
			const allowedValues = evidence.get(targetNode);
			if (allowedValues !== undefined) {
				const filtered: Distribution = new Map();
				for (const [k, v] of distribution) {
					if (allowedValues.has(k)) filtered.set(k, v);
				}
				if (filtered.size === 0 || sumValues(filtered) <= 0) {
					throw new RestrictiveConstraints(
						`Cannot generate fingerprint: No valid values for ${targetNode} with current conditions.`,
					);
				}
				const total = sumValues(filtered);
				for (const [k, v] of filtered) filtered.set(k, v / total);
				distribution = filtered;
			}

			if (distribution.size) {
				result.set(targetNode, this.sampleValueFromDistribution(distribution));
			} else {
				throw new RestrictiveConstraints(
					`Cannot generate fingerprint: Empty distribution for ${targetNode}.`,
				);
			}
		}
		return result;
	}

	/**
	 * Validate that the evidence is mutually compatible given the network
	 * structure. Throws RestrictiveConstraints when it isn't.
	 */
	validateEvidence(evidence: ReadonlyMap<string, ReadonlySet<string>>): void {
		// Skip validation for single constraint
		if (evidence.size <= 1) return;

		for (const [nodeName, allowedValues] of evidence) {
			// The other conditions pinned to a single value.
			const fixed = new Map<string, string>();
			for (const [k, v] of evidence) {
				if (k !== nodeName && v.size === 1) fixed.set(k, [...v][0]);
			}
			if (!fixed.size) continue;

			const dist = this.trace(nodeName, fixed);
			if (
				dist.size &&
				[...allowedValues].every((val) => (dist.get(val) ?? 0) <= 0)
			) {
				const allowed = [...allowedValues];
				let valuesStr = this.values
					.lookupValueList(allowed.slice(0, 5))
					.join(", ");
				if (allowed.length > 5) valuesStr += ", ...";
				const constraintValues = this.values.lookupValueList(fixed.values());
				const constraintsStr = [...fixed.keys()]
					.map((k, i) => `${k}=${constraintValues[i]}`)
					.join(", ");
				throw new RestrictiveConstraints(
					`Cannot generate fingerprint: ${nodeName}=(${valuesStr}) ` +
						`is impossible with constraint: ${constraintsStr}`,
				);
			}
		}
	}

	/** All ancestors of a node (the nodes that can influence its value). */
	getAllAncestors(nodeName: string): Set<string> {
		const cached = this.ancestorsByName.get(nodeName);
		if (cached) return cached;

		const node = this.node(nodeName);
		const ancestors = new Set<string>();
		for (const parent of node.parentNames) {
			ancestors.add(parent);
			for (const a of this.getAllAncestors(parent)) ancestors.add(a);
		}
		this.ancestorsByName.set(nodeName, ancestors);
		return ancestors;
	}

	/**
	 * The conditional distribution of `target` given `evidence`, by beam
	 * search. Empty when the evidence admits nothing.
	 */
	trace(target: string, evidence: Evidence): Distribution {
		// The actual target name, and the nodes that matter for it.
		const targetName = this.node(target).name;
		const relevant = new Set(this.getAllAncestors(targetName));
		relevant.add(targetName);
		for (const evNode of evidence.keys()) {
			if (this.nodesByName.has(evNode)) {
				relevant.add(evNode);
				for (const a of this.getAllAncestors(evNode)) relevant.add(a);
			}
		}

		// Relevant nodes in sampling order, with each parent's slot.
		const ordered = this.nodesInSamplingOrder.filter((n) =>
			relevant.has(n.name),
		);
		const slot = new Map<string, number>();
		for (const [i, n] of ordered.entries()) slot.set(n.name, i);

		let beam: BeamEntry[] = [{ values: [], prob: 1.0 }];

		for (let i = 0; i < ordered.length; i++) {
			const node = ordered[i];
			const nodeName = node.name;
			const allowedValues = evidence.get(nodeName);
			const parentSlots = node.parentNames.map((p) => {
				const s = slot.get(p);
				if (s === undefined) throw new Error(`KeyError: '${p}'`);
				return s;
			});
			const newBeam: BeamEntry[] = [];
			// Python keys its cache by (node, parent values); one per node here.
			const cptCache = new Map<string, Distribution>();

			for (const { values, prob } of beam) {
				const parentValues = parentSlots.map((s) => values[s]);
				const cacheKey = parentValues.join("\u0000");
				let cpt = cptCache.get(cacheKey);
				if (cpt === undefined) {
					const known = new Map<string, string>();
					node.parentNames.forEach((p, j) => {
						known.set(p, parentValues[j]);
					});
					cpt = node.getProbabilitiesGivenKnownValues(known);
					// Use a uniform distribution if the table has no row.
					if (!cpt.size && node.possibleValues.length) {
						const uniform = 1.0 / node.possibleValues.length;
						cpt = new Map(node.possibleValues.map((v) => [v, uniform]));
					}
					cptCache.set(cacheKey, cpt);
				}

				// Expand the beam with new assignments
				for (const [value, p] of cpt) {
					if (
						(allowedValues === undefined || isAllowed(allowedValues, value)) &&
						p > 0
					) {
						const next = values.slice();
						next.push(value);
						newBeam.push({ values: next, prob: prob * p });
					}
				}
			}

			if (!newBeam.length) return new Map();
			if (newBeam.length > BEAM_WIDTH) {
				// heapq.nlargest(k, ..., key=prob) == sorted(reverse=True)[:k],
				// which keeps equal-probability entries in their original order.
				// Array.prototype.sort is stable, so this is the same list.
				newBeam.sort((a, b) => b.prob - a.prob);
				newBeam.length = BEAM_WIDTH;
			}
			beam = newBeam;
		}

		// Extract the target distribution
		const targetSlot = slot.get(targetName) as number;
		const targetDist: Distribution = new Map();
		let totalProb = 0.0;
		for (const { values, prob } of beam) {
			const value = values[targetSlot];
			targetDist.set(value, (targetDist.get(value) ?? 0) + prob);
			totalProb += prob;
		}
		if (totalProb > 0) {
			for (const [v, p] of targetDist) targetDist.set(v, p / totalProb);
			return targetDist;
		}
		return new Map();
	}

	/** Draw a value from a distribution (cumulative, falls back to the first). */
	sampleValueFromDistribution(distribution: Distribution): string {
		const anchor = Math.random();
		let cumulative = 0.0;
		for (const [value, probability] of distribution) {
			cumulative += probability;
			if (anchor < cumulative) return value;
		}
		return distribution.keys().next().value as string;
	}
}
