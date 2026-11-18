/**
 * TypeScript twin of python/src/camoufox/exceptions.py.
 *
 * The Python hierarchy leans on builtin bases (FileNotFoundError, ValueError,
 * ImportError) that have no JS analogue; those become plain Error subclasses
 * here. Every relationship that callers actually catch on -- LocaleError,
 * VirtualDisplayError -- is preserved.
 */

/** The Python twin relies on the builtin FileNotFoundError; JS has no such
 *  class, so version-lookup misses raise this instead. */
export class FileNotFoundError extends Error {
	constructor(message?: string) {
		super(message ?? "File couldn't be found.");
		this.name = "FileNotFoundError";
	}
}

export class UnsupportedVersion extends Error {
	constructor(message?: string) {
		super(message ?? "The Camoufox executable is outdated.");
		this.name = "UnsupportedVersion";
	}
}

export class MissingRelease extends Error {
	constructor(message?: string) {
		super(message ?? "A required GitHub release asset is missing.");
		this.name = "MissingRelease";
	}
}

/** Raised when a downloaded asset does not match its expected sha256 digest. */
export class CorruptedDownload extends Error {
	constructor(message?: string) {
		super(
			message ??
				"A downloaded asset does not match its expected sha256 digest.",
		);
		this.name = "CorruptedDownload";
	}
}

export class UnsupportedArchitecture extends Error {
	constructor(message?: string) {
		super(message ?? "The architecture is not supported.");
		this.name = "UnsupportedArchitecture";
	}
}

export class UnsupportedOS extends Error {
	constructor(message?: string) {
		super(message ?? "The OS is not supported.");
		this.name = "UnsupportedOS";
	}
}

export class InvalidPropertyType extends Error {
	constructor(message?: string) {
		super(message ?? "The property type is invalid.");
		this.name = "InvalidPropertyType";
	}
}

export class InvalidAddonPath extends FileNotFoundError {
	constructor(message?: string) {
		super(message ?? "The addon path is invalid.");
		this.name = "InvalidAddonPath";
	}
}

export class LocaleError extends Error {
	constructor(message?: string) {
		super(message ?? "The locale is invalid.");
		this.name = "LocaleError";
	}
}

export class InvalidIP extends Error {
	constructor(message?: string, options?: ErrorOptions) {
		super(message ?? "An IP address is invalid.", options);
		this.name = "InvalidIP";
	}
}

export class InvalidProxy extends Error {
	constructor(message?: string, options?: ErrorOptions) {
		super(message ?? "A proxy is invalid.", options);
		this.name = "InvalidProxy";
	}
}

export class UnknownIPLocation extends LocaleError {
	constructor(message?: string) {
		super(message ?? "The location of an IP is unknown.");
		this.name = "UnknownIPLocation";
	}
}

export class InvalidLocale extends LocaleError {
	constructor(message?: string) {
		super(message ?? "The locale input is invalid.");
		this.name = "InvalidLocale";
	}

	static invalidInput(locale: string): InvalidLocale {
		return new InvalidLocale(
			`Invalid locale: '${locale}'. Must be either a region, language, language-region, or language-script-region.`,
		);
	}
}

export class UnknownTerritory extends InvalidLocale {
	constructor(message?: string) {
		super(message ?? "The territory is unknown.");
		this.name = "UnknownTerritory";
	}
}

export class UnknownLanguage extends InvalidLocale {
	constructor(message?: string) {
		super(message ?? "The language is unknown.");
		this.name = "UnknownLanguage";
	}
}

export class NotInstalledGeoIPExtra extends Error {
	constructor(message?: string) {
		super(message ?? "The GeoIP database reader is not available.");
		this.name = "NotInstalledGeoIPExtra";
	}
}

export class NonFirefoxFingerprint extends Error {
	constructor(message?: string) {
		super(message ?? "A passed fingerprint is not a Firefox fingerprint.");
		this.name = "NonFirefoxFingerprint";
	}
}

export class InvalidOS extends Error {
	constructor(message?: string) {
		super(message ?? "The target OS is invalid.");
		this.name = "InvalidOS";
	}
}

export class VirtualDisplayError extends Error {
	constructor(message?: string) {
		super(message ?? "There is an error with the virtual display.");
		this.name = "VirtualDisplayError";
	}
}

export class CannotFindXvfb extends VirtualDisplayError {
	constructor(message?: string) {
		super(message ?? "Xvfb cannot be found.");
		this.name = "CannotFindXvfb";
	}
}

export class CannotExecuteXvfb extends VirtualDisplayError {
	constructor(message?: string) {
		super(message ?? "Xvfb cannot be executed.");
		this.name = "CannotExecuteXvfb";
	}
}

export class VirtualDisplayNotSupported extends VirtualDisplayError {
	constructor(message?: string) {
		super(
			message ?? "The user tried to use a virtual display on a non-Linux OS.",
		);
		this.name = "VirtualDisplayNotSupported";
	}
}

export class GpuDisplayError extends VirtualDisplayError {
	constructor(message?: string) {
		super(message ?? "The headless='virtual-gpu' display cannot be used.");
		this.name = "GpuDisplayError";
	}
}

export class NoGpuFound extends GpuDisplayError {
	constructor(message?: string) {
		super(message ?? "No GPU render node with a PCI address was found.");
		this.name = "NoGpuFound";
	}
}

export class AmbiguousGpuSelection extends GpuDisplayError {
	constructor(message?: string) {
		super(
			message ?? "Several GPUs match, or several exist and none was named.",
		);
		this.name = "AmbiguousGpuSelection";
	}
}

export class GpuNotFound extends GpuDisplayError {
	constructor(message?: string) {
		super(message ?? "The GPU selector matches no GPU.");
		this.name = "GpuNotFound";
	}
}

export class CannotFindXorg extends GpuDisplayError {
	constructor(message?: string) {
		super(message ?? "Xorg cannot be found.");
		this.name = "CannotFindXorg";
	}
}

export class CannotExecuteXorg extends GpuDisplayError {
	constructor(message?: string) {
		super(message ?? "Xorg cannot be started, or exited right after starting.");
		this.name = "CannotExecuteXorg";
	}
}

export class GpuVtTakeover extends GpuDisplayError {
	constructor(message?: string) {
		super(message ?? "The Xorg server switched the active console VT.");
		this.name = "GpuVtTakeover";
	}
}

export class GpuSoftwareFallback extends GpuDisplayError {
	constructor(message?: string) {
		super(message ?? "The browser on a GPU display never rendered on the GPU.");
		this.name = "GpuSoftwareFallback";
	}
}

export class CamoufoxNotInstalled extends FileNotFoundError {
	constructor(message?: string) {
		super(message ?? "Camoufox is not installed.");
		this.name = "CamoufoxNotInstalled";
	}
}

/** Raised when Camoufox's required runtime directory cannot be prepared. */
export class ProfileDirectoryError extends Error {
	constructor(message?: string, options?: ErrorOptions) {
		super(
			message ?? "Camoufox's runtime directory could not be prepared.",
			options,
		);
		this.name = "ProfileDirectoryError";
	}
}
