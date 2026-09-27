/**
 * The pinned fpgen model: a copy of scripts/data/fpgen-model.json.
 *
 * That file is the single source of truth for the Python build; this constant
 * is its twin for the npm package, which does not ship the repo's scripts/.
 * tests/fpgen-model.test.ts fails if the two ever disagree, so bumping the
 * model means editing both (the sha256 is the gate in each).
 *
 * See pythonlib/camoufox/fpgen_model.py for why fpgen's own downloader is not used:
 * it disables TLS verification, never checks a digest, and its "first listed
 * release" rule cannot reach this tag.
 */

export interface ModelPin {
	readonly tag: string;
	readonly asset: string;
	readonly size: number;
	readonly sha256: string;
	readonly url: string;
	readonly repo: string;
	readonly files: readonly string[];
	/** Each file's sha256, for checking an installed model without its archive. */
	readonly file_sha256: Readonly<Record<string, string>>;
	/**
	 * sha256 of each file the model decompresses to. values.dat is shared with
	 * pythonlib when CAMOUFOX_FPGEN_DATA points at its fpgen `data/`, and this
	 * is how pythonlib tells one decompressed from the pinned model.
	 */
	readonly decompressed_sha256: Readonly<Record<string, string>>;
}

export const MODEL_PIN: ModelPin = {
	tag: "model-2/2026",
	asset: "model-release.zip",
	size: 1564571,
	sha256: "6530b8322cdaa4ec042921c8d9a0369a0e6e0269ba636c01a7203e4a2f109936",
	url: "https://github.com/scrapfly/fingerprint-generator/releases/download/model-2/2026/model-release.zip",
	repo: "scrapfly/fingerprint-generator",
	files: ["fingerprint-network.json.zst", "values.dat.zst", "values.json.zst"],
	file_sha256: {
		"fingerprint-network.json.zst":
			"e1b0a7e60837c347f4b7d5dad4a20c356d521e0593e1bf4a8be39ea1e6a41ac4",
		"values.dat.zst":
			"3da2cf0891a4a85ef6458f0fbdf9346acfcd04e5fd279a0ea22d7919e4eaf122",
		"values.json.zst":
			"294decde5b6a1a52ed53d50a894130fa5c58f7cc804b78198f5c33f55b3ba66f",
	},
	decompressed_sha256: {
		"values.dat":
			"9ce7d16630e91654e73988f7d37e8c99987c09b9c779a7bb9dc7ad6355dcc2f0",
	},
};
