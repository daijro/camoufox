/**
 * TypeScript port of fpgen 1.3.0 (scrapfly/fingerprint-generator), the
 * fingerprint generator the Python launcher uses. Apache-2.0; see ./NOTICE.
 *
 *   import { ensureModel, Generator } from "./fpgen/index.js";
 *   await ensureModel();                       // pinned model, sha256-checked
 *   const fp = new Generator().generate({ browser: "Firefox", os: "Windows" });
 *
 * Everything after ensureModel() is synchronous, like the Python API.
 */
export {
	BayesianNetwork,
	BayesianNode,
	BEAM_WIDTH,
	type Distribution,
} from "./bayesian-network.js";
export {
	InvalidConstraints,
	InvalidNode,
	ModelNotInstalled,
	ModelVerificationError,
	NetworkError,
	NodePathError,
	RestrictiveConstraints,
	ValueError,
} from "./exceptions.js";
export {
	type Fingerprint,
	type GenerateOptions,
	Generator,
	type GeneratorOptions,
	generate,
	generateTarget,
} from "./generator.js";
export {
	downloadArchive,
	type EnsureModelOptions,
	ensureModel,
	FpgenModel,
	getModel,
	installArchive,
	isModelInstalled,
	modelDir,
	resetModelCache,
	verifyArchive,
} from "./model.js";
export { MODEL_PIN, type ModelPin } from "./pin.js";
export {
	type TraceOptions,
	TraceResult,
	type TraceResultDict,
	trace,
} from "./trace.js";
export {
	type Conditions,
	type Predicate,
	query,
} from "./utils.js";
