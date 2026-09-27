/**
 * Locale + geolocation handling: re-exports locales.ts and geolocation.ts,
 * the twins of pythonlib/camoufox/locales.py and geolocation.py.
 *
 * Kept so existing `./locale.js` imports keep working.
 */
export * from "./geolocation.js";
export * from "./locales.js";
