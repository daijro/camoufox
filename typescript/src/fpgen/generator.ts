/**
 * Ported from fpgen/generator.py (scrapfly/fingerprint-generator, Apache-2.0;
 * see ./NOTICE).
 *
 * Python keyword arguments become two objects: the conditions, then the
 * options (`strict`, `flatten`, `target`). `Generator(conditions, options)`,
 * `generator.generate(conditions, options)`, and so on.
 *
 * The model must be on disk before any of this runs: `await ensureModel()`.
 */
import { RestrictiveConstraints } from "./exceptions.js";
import { getModel } from "./model.js";
import {
	type TraceOptions,
	type TraceResult,
	type TraceResultDict,
	traceWithEvidence,
} from "./trace.js";
import {
	assertConditions,
	buildEvidence,
	type Conditions,
	type EvidenceMap,
	findRoots,
	makeOutputDict,
	maybeFlatten,
	reassembleTargets,
} from "./utils.js";

export interface GeneratorOptions {
	/** Throw when the conditions are too strict (default true). */
	strict?: boolean;
	/** Flatten the output object into dotted keys (default false). */
	flatten?: boolean;
}

export interface GenerateOptions {
	/** Overrides the Generator's `strict`. */
	strict?: boolean;
	/** Overrides the Generator's `flatten`. */
	flatten?: boolean;
	/** Only generate specific value(s): a node, a path inside one, or a prefix. */
	target?: string | readonly string[];
}

/** A generated fingerprint (nested unless `flatten`). */
export type Fingerprint = Record<string, any>;

function hasConditions(conditions: Conditions | null | undefined): boolean {
	return !!conditions && Object.keys(conditions).length > 0;
}

/** Generates realistic browser fingerprints. */
export class Generator {
	strict: boolean;
	flatten: boolean;
	readonly evidence: EvidenceMap = new Map();

	/**
	 * Conditions and options given here are inherited by every generate().
	 */
	constructor(
		conditions?: Conditions | null,
		{ strict = true, flatten = false }: GeneratorOptions = {},
	) {
		assertConditions(conditions);
		this.strict = strict;
		this.flatten = flatten;
		if (hasConditions(conditions)) {
			// fpgen passes no `strict` here, so construction is always strict.
			buildEvidence(conditions as Conditions, this.evidence);
		}
	}

	/** Generate a fingerprint, or just `target` when given. */
	generate(
		conditions: Conditions | null | undefined,
		options: GenerateOptions & { target: string },
	): any;
	generate(
		conditions?: Conditions | null,
		options?: GenerateOptions,
	): Fingerprint;
	generate(conditions?: Conditions | null, options: GenerateOptions = {}): any {
		assertConditions(conditions);
		const { network } = getModel();

		const strict = options.strict ?? this.strict;
		const flatten = options.flatten ?? this.flatten;
		const { target } = options;

		// Inherit the evidence from the instance
		const evidence: EvidenceMap = new Map(this.evidence);
		if (hasConditions(conditions)) {
			buildEvidence(conditions as Conditions, evidence, strict);
		}

		const targetTup =
			target === undefined
				? null
				: typeof target === "string"
					? [target]
					: [...target];
		const hasTarget = !!target && (targetTup as string[]).length > 0;
		const targetRoots = hasTarget
			? new Set(findRoots(targetTup as string[]))
			: null;

		let fingerprint: Map<string, string> | null;
		while (true) {
			fingerprint = targetRoots?.size
				? network.generateCertainNodes(evidence, targetRoots)
				: network.generateConsistentSample(evidence);
			if (fingerprint !== null) break;
			if (strict) {
				throw new RestrictiveConstraints(
					"Cannot generate fingerprint. Constraints are too restrictive.",
				);
			}
			// Relax the evidence until something can be generated
			evidence.delete(evidence.keys().next().value as string);
		}

		if (hasTarget) {
			// Don't flatten yet
			let output: any = reassembleTargets(
				targetTup as string[],
				makeOutputDict(fingerprint, false),
			);
			if (typeof target === "string") output = output[target];
			return maybeFlatten(flatten, output);
		}
		return makeOutputDict(fingerprint, flatten);
	}

	/** Generate a specific target. Shortcut for `generate(..., {target})`. */
	generateTarget(
		target: string,
		conditions?: Conditions | null,
		options: Omit<GenerateOptions, "target"> = {},
	): any {
		return this.generate(conditions, { ...options, target });
	}

	/**
	 * The probability distribution(s) of a target given conditions, on top of
	 * this Generator's conditions.
	 */
	trace(
		target: string | readonly string[],
		conditions?: Conditions | null,
		options: TraceOptions = {},
	): TraceResult[] | TraceResultDict {
		return traceWithEvidence(
			target,
			conditions,
			options,
			new Map(this.evidence),
		);
	}
}

/*
 * A global generate() for callers that don't build a Generator.
 */
let GLOBAL_GENERATOR: Generator | null = null;

/** Generate a fingerprint with a shared, condition-less Generator. */
export function generate(
	conditions: Conditions | null | undefined,
	options: GenerateOptions & { target: string },
): any;
export function generate(
	conditions?: Conditions | null,
	options?: GenerateOptions,
): Fingerprint;
export function generate(
	conditions?: Conditions | null,
	options?: GenerateOptions,
): any {
	GLOBAL_GENERATOR ??= new Generator();
	return GLOBAL_GENERATOR.generate(conditions, options);
}

/** Generate a specific target. Shortcut for `generate(..., {target})`. */
export function generateTarget(
	target: string,
	conditions?: Conditions | null,
	options: Omit<GenerateOptions, "target"> = {},
): any {
	return generate(conditions, { ...options, target });
}
