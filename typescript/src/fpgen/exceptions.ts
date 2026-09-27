/**
 * Ported from fpgen/exceptions.py (scrapfly/fingerprint-generator, Apache-2.0).
 * See ./NOTICE.
 *
 * The hierarchy and the class names are kept: the Python launcher tells a
 * constraint that matched nothing apart from one that was too restrictive by
 * `type(exc).__name__`, so `name` is set to the exact Python class name.
 * Python's builtin ValueError has no JS twin; it becomes a plain Error subclass
 * with the same name, and NetworkError still derives from it.
 */

export class ValueError extends Error {
	constructor(message?: string) {
		super(message);
		this.name = "ValueError";
	}
}

/** Error with the network. */
export class NetworkError extends ValueError {
	constructor(message?: string) {
		super(message);
		this.name = "NetworkError";
	}
}

/** Raised when a constraint isn't possible. */
export class InvalidConstraints extends NetworkError {
	constructor(message?: string) {
		super(message);
		this.name = "InvalidConstraints";
	}
}

/** Raised when the passed constraints are too restrictive. */
export class RestrictiveConstraints extends InvalidConstraints {
	constructor(message?: string) {
		super(message);
		this.name = "RestrictiveConstraints";
	}
}

/** Raised when a node doesn't exist. */
export class InvalidNode extends NetworkError {
	constructor(message?: string) {
		super(message);
		this.name = "InvalidNode";
	}
}

/** Raised when a key path doesn't exist. The message is the missing key. */
export class NodePathError extends InvalidNode {
	constructor(message?: string) {
		super(message);
		this.name = "NodePathError";
	}
}

/**
 * The pinned model is not on disk. Python fpgen downloads at import time; the
 * TypeScript API is synchronous, so the download is a separate, awaited step
 * (`ensureModel()`), and the synchronous calls throw this until it has run.
 */
export class ModelNotInstalled extends Error {
	constructor(message?: string) {
		super(
			message ??
				"The fpgen model is not installed. Call `await ensureModel()` first.",
		);
		this.name = "ModelNotInstalled";
	}
}

/** The downloaded model failed its size / sha256 check, or is malformed. */
export class ModelVerificationError extends Error {
	constructor(message?: string) {
		super(message);
		this.name = "ModelVerificationError";
	}
}
