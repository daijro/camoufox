import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { FileNotFoundError } from "../src/exceptions.js";
import {
	AvailableVersion,
	formatAssetDate,
	LOCAL_DATA,
	loadYaml,
	OS_ARCH_MATRIX,
	OS_NAME,
	pkgmanDeps,
	RepoConfig,
	Version,
} from "../src/pkgman.js";

describe("Version ordering", () => {
	it("orders alpha < beta < numeric builds", () => {
		const alpha = new Version("alpha.5");
		const beta = new Version("beta.5");
		expect(alpha.lessThan(beta)).toBe(true);
		expect(beta.lessThan(alpha)).toBe(false);
	});

	it("orders numerically within a channel", () => {
		expect(new Version("beta.9").lessThan(new Version("beta.20"))).toBe(true);
		expect(new Version("beta.20").lessThan(new Version("beta.9"))).toBe(false);
	});

	it("treats equal builds as equal", () => {
		expect(new Version("beta.20").equals(new Version("beta.20"))).toBe(true);
	});

	it("reports the full version string", () => {
		expect(new Version("beta.28", "152.0.4").fullString).toBe(
			"152.0.4-beta.28",
		);
	});

	it("detects the alpha channel", () => {
		expect(new Version("alpha.26").isAlpha).toBe(true);
		expect(new Version("beta.26").isAlpha).toBe(false);
	});

	it("accepts builds inside the supported range", () => {
		// CONSTRAINTS is alpha.1 <= v < 1, raised by the Playwright floor
		// (beta.30 from Playwright 1.61).
		const saved = pkgmanDeps.resolvedPlaywrightVersion;
		try {
			pkgmanDeps.resolvedPlaywrightVersion = () => [1, 60, 0];
			expect(new Version("beta.28").isSupported()).toBe(true);
			expect(new Version("alpha.1").isSupported()).toBe(true);
			pkgmanDeps.resolvedPlaywrightVersion = () => [1, 62, 0];
			expect(new Version("beta.28").isSupported()).toBe(false);
			expect(new Version("beta.30").isSupported()).toBe(true);
			expect(new Version("1").isSupported()).toBe(false);
		} finally {
			pkgmanDeps.resolvedPlaywrightVersion = saved;
		}
	});

	it("reads version.json like the Python twin (release/tag win over build)", () => {
		const dir = fs.mkdtempSync(path.join(os.tmpdir(), "camoufox-vj-"));
		try {
			const write = (data: object) =>
				fs.writeFileSync(path.join(dir, "version.json"), JSON.stringify(data));
			write({ version: "1.0", build: "beta.1" });
			expect(Version.fromPath(dir).fullString).toBe("1.0-beta.1");
			write({ version: "1.0", build: "beta.1", release: "beta.2" });
			expect(Version.fromPath(dir).build).toBe("beta.2");
			write({ version: "1.0", tag: "beta.3" });
			expect(Version.fromPath(dir).build).toBe("beta.3");
			fs.rmSync(path.join(dir, "version.json"));
			expect(() => Version.fromPath(dir)).toThrow(FileNotFoundError);
		} finally {
			fs.rmSync(dir, { recursive: true, force: true });
		}
	});
});

describe("RepoConfig", () => {
	it("parses the comma-separated fallback repo list", () => {
		const official = RepoConfig.findByName("Official");
		expect(official).toBeDefined();
		expect(official?.repos).toEqual(["daijro/camoufox", "camoufox/camoufox"]);
		expect(official?.repo).toBe("daijro/camoufox");
	});

	it("defaults to the repo named in the config", () => {
		expect(RepoConfig.getDefaultName()).toBe("Official");
		expect(RepoConfig.getDefault().name).toBe("Official");
	});

	it("builds an asset regex that captures name/version/build", () => {
		const config = RepoConfig.getDefault();
		const pattern = config.buildPattern("lin", "x86_64");
		const match = pattern.exec("camoufox-152.0.4-beta.28-lin.x86_64.zip");
		expect(match?.groups?.version).toBe("152.0.4");
		expect(match?.groups?.build).toBe("beta.28");
	});

	it("does not match another platform's asset", () => {
		const pattern = RepoConfig.getDefault().buildPattern("lin", "x86_64");
		expect(pattern.exec("camoufox-152.0.4-beta.28-win.x86_64.zip")).toBeNull();
	});

	it("applies the stable channel's build floor", () => {
		const official = RepoConfig.getDefault();
		// Official pins stable to beta.19+; prerelease is unbounded.
		expect(official.isVersionSupported(new Version("beta.28"), false)).toBe(
			true,
		);
		expect(official.isVersionSupported(new Version("beta.10"), false)).toBe(
			false,
		);
		expect(official.isVersionSupported(new Version("alpha.1"), true)).toBe(
			true,
		);
	});

	it("treats a repo with no browser constraints as unbounded", () => {
		const coryking = RepoConfig.findByName("CoryKing");
		expect(coryking?.isVersionSupported(new Version("beta.1"), false)).toBe(
			true,
		);
	});
});

describe("platform matrix", () => {
	it("knows the arches the current OS ships", () => {
		expect(OS_ARCH_MATRIX[OS_NAME].length).toBeGreaterThan(0);
	});
});

describe("formatAssetDate", () => {
	it("omits the year for the current year", () => {
		const now = new Date("2026-08-02T00:00:00Z");
		expect(formatAssetDate("2026-03-14T10:00:00Z", now)).toMatch(/^Mar 1[34]$/);
	});

	it("includes the year for another year", () => {
		const now = new Date("2026-08-02T00:00:00Z");
		expect(formatAssetDate("2024-03-14T10:00:00Z", now)).toMatch(
			/^Mar 1[34], 2024$/,
		);
	});

	it("returns empty for missing or unparseable input", () => {
		expect(formatAssetDate(undefined)).toBe("");
		expect(formatAssetDate("not-a-date")).toBe("");
	});
});

describe("repos.yml", () => {
	it("is the file the Python package ships", () => {
		const shipped = fs.readFileSync(
			path.join(import.meta.dirname, "../../pythonlib/camoufox/repos.yml"),
			"utf-8",
		);
		const ours = fs.readFileSync(path.join(LOCAL_DATA, "repos.yml"), "utf-8");
		expect(ours).toBe(shipped);
		expect(loadYaml("repos.yml").default.browser).toBe("Official");
	});
});

describe("AvailableVersion.toMetadata", () => {
	it("writes unknown fields as null, as orjson does for None", () => {
		const v = new AvailableVersion({
			version: new Version("beta.30", "152.0.4"),
			url: "u",
			isPrerelease: false,
		});
		expect(JSON.stringify(v.toMetadata())).toBe(
			'{"version":"152.0.4","build":"beta.30","prerelease":false,"asset_id":null,"asset_size":null,"asset_updated_at":null,"sha256":null,"created_at":null}',
		);
	});
});
