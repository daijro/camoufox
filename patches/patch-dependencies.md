# Patch Dependencies

Quick reference for which patches depend on shared infrastructure.

## camoucfg (MaskConfig)

Most patches read config via `MaskConfig::GetBool()`, `MaskConfig::GetString()`, etc. from `/camoucfg`. Any patch that adds `LOCAL_INCLUDES += ["/camoucfg"]` to a `moz.build` file depends on `config.patch` being applied first (which provides the `camoucfg` directory).

### Patches using MaskConfig

| Patch | Config keys | What it does |
|-------|-------------|--------------|
| `media-codec-spoofing.patch` | `media:spoof_codecs` | Bypasses `PDMFactory::Supports()` checks in `MP4Decoder` and `MatroskaDecoder` so `canPlayType()`/`isTypeSupported()` don't leak system codec libraries |
| `navigator-spoofing.patch` | Various `navigator:*` keys | Per-context navigator property spoofing |
| `geolocation-spoofing.patch` | `geo:*` keys | Geolocation coordinate spoofing |
| `locale-spoofing.patch` | `locale:*` keys | Language/locale spoofing |

## RoverfoxStorageManager

Per-context patches that use cross-process storage depend on `cross-process-storage.patch`.

## Playwright

All patches should be applied after `0-playwright.patch` and `1-leak-fixes.patch`.
