/**
 * Camoufox version constants.
 *
 * TypeScript twin of pythonlib/camoufox/__version__.py.
 */

// biome-ignore lint/complexity/noStaticOnlyClass: mirrors the Python twin's CONSTRAINTS class so both launchers read the same
export class CONSTRAINTS {
	/**
	 * The minimum and maximum supported versions of the Camoufox browser.
	 */
	static readonly MIN_VERSION: string = "alpha.1";
	static readonly MAX_VERSION: string = "1";

	/**
	 * The browser floor is conditional on the resolved Playwright, not fixed.
	 *
	 * Each entry is [playwrightVersion, requiredBrowserBuild]: from that
	 * Playwright on, the browser must be at least that build. 1.61 began
	 * sending viewport isMobile/screenSize in Browser.setDefaultViewport and
	 * Page.setViewportSize; beta.30 is the first build whose Protocol.js schema
	 * accepts them. Below that pairing every newContext() dies with
	 * "Protocol error (Browser.setDefaultViewport)". Measured: 1.60 works on
	 * beta.29 and beta.30; 1.61 and 1.62 fail on beta.29 and pass on beta.30.
	 *
	 * A flat MIN_VERSION cannot express this. It only knows about the browser,
	 * so to stay safe it has to assume the worst Playwright and force *every*
	 * user to re-download -- including the majority on <1.61, who are in no
	 * danger -- and it leaves the library unusable until the matching browser
	 * release is published. Keyed on Playwright, only the users who would
	 * actually break get moved.
	 */
	static readonly PLAYWRIGHT_BROWSER_FLOORS: ReadonlyArray<
		readonly [readonly number[], string]
	> = [[[1, 61], "beta.30"]];
}

/** Version of this launcher library. Kept in step with package.json and
 *  pythonlib's pyproject.toml. */
export const LIBRARY_VERSION = "0.5.7";
