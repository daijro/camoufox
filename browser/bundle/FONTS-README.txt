DO NOT MODIFY THE CONTENTS OF THIS DIRECTORY

Any adjustment to bundled fonts will result in an altered fingerprint. Font
fingerprinting is more than just detecting what fonts you have, it also includes
font fallbacks and characters (unicode code points) and any change in those can
be measured.


WHAT IS HERE

NOTHING, until you run `make fetch-fonts`. The bundle is a RELEASE ASSET, not
repo content: ~2.1 GB extracted, ~843 MB as .tar.xz. GitHub rejects files over
100 MiB, and an xz archive cannot be delta-compressed, so committing it would
append the whole archive to history on every font change. It is pinned by
scripts/data/font-bundle.json (asset name + size + sha256) so a given commit
still names exactly one bundle. See scripts/fetch-fonts.py.

    make fetch-fonts     download + verify the archive (bundle/fonts-bundle-*.tar.xz)
    make fonts-extract   unpack it to bundle/fonts/   (gitignored; a no-op once
                         unpacked -- the tree is stamped with the archive's sha256)
    make fonts-check     verify the archive against the pin
    make fonts-clean     delete the unpacked copy, keep the archive

Once extracted, each face is stored EXACTLY ONCE, in a directory named for the
set of OSes that use it:

    L  M  W        used by one OS only
    LM LW MW       used by two
    LMW            used by all three

    1513 faces, 2.1 GB, with bundle/fonts/groups.json recording which groups
    each OS reads:
        lin -> L + LM + LMW + LW    (792 files)
        mac -> LM + LMW + M + MW    (779 files)
        win -> LMW + LW + MW + W    (809 files)

The bundle used to be three per-OS directories, which meant 41% of it (1.63 GB)
was byte-identical copies of the same faces. Grouping removed that without
changing a single reportable family -- python/src/camoufox/fonts.json is
byte-identical across the change.

The group directory is also the per-OS GATE on Linux: utils._generate_fontconfig
hands fontconfig exactly the four directories the claimed OS reads, so a face
Windows must not see is never on the search path. That replaced a 455-entry
<rejectfont> glob list in ../fontconfig/windows/fonts.conf, which was unsound
anyway -- 114 bundled filenames contain [ ] (e.g. ReemKufi[wght].ttf), which
fontconfig parses as a character class, so those rejects silently matched
nothing. macOS (CoreText) and Windows (DirectWrite) cannot read subfolders, so
package.py flattens the groups for those targets and the allowlist does the
gating there, as it always did.

File names carry the prefixes Holo's merge-drop.sh gave them (NN__, z__, u__);
they make basenames unique across groups, which is what lets the macOS/Windows
packages flatten safely (scripts/verify-fonts.py checks).


SOURCES

- Linux: the Tor Browser bundle set plus Ubuntu / Mint desktop defaults
  (Noto, DejaVu, Ubuntu, Liberation, URW base35, ...) and the open additions
  (LibreOffice, developer and web fonts) Holo's fonts-manifests.ts draws from.
- Windows: the Windows 11 default families (measured on real hardware; the
  Windows 10 base was dropped from the model on 2026-09-23), the Office and
  Pan-European FOD sets, LibreOffice, and open developer/web fonts.
  The Windows CJK Feature-on-Demand fonts and third-party Adobe/Kozuka CJK
  are deliberately absent (Holo's CJK_EXCLUDE_WIN).
- macOS: the Sonoma, Tahoe 26 and macOS 27 system fonts, including PingFang and
  Kefa, plus Apple's optional "document support" families and open
  developer/web fonts. A few Devanagari families are still absent.

Adobe's fonts (Minion Pro, Myriad Pro, the Adobe/Kozuka CJK and script
faces -- 185 files, 240 MB) were REMOVED on 2026-09-22: Adobe permits no
redistribution, and the fpgen corpus puts every one of those families on under
2% of real machines (Minion Pro 1.5%, the rest at 0.0%), so shipping them bought
no realism. The `adobe-cc` unit was dropped from scripts/data/font-manifests.json
in the same change, because reporting a family the bundle cannot render is a
reverse leak. Run scripts/font-metrics/licences.py for the current licence split.

The per-OS list of families the launcher may REPORT is generated from these
files, in this order, and checked by scripts/verify-fonts.py:

    scripts/gen-fonts-json.py     bundle + font-manifests.json -> fonts.json
                                  (--print-bases also prints the
                                  _ESSENTIAL_FONTS_* literals for
                                  python/src/camoufox/fingerprints.py, which are
                                  the INTERSECTION of that OS's version bases)
    scripts/gen-font-groups.py    fonts.json + font-manifests.json ->
                                  font-groups.json (the addition units, each
                                  with its own real-world probability) and
                                  font-bases.json (the OS-version bases with
                                  their weights)

Run both after the bundle or the manifest changes, in that order.


Disclaimer:

This project utilizes copyrighted fonts solely for academic and research purposes. The fonts used in this project are the intellectual property of their respective owners. No commercial use or distribution of these fonts is intended or permitted. All rights to the fonts are retained by their respective copyright holders. If you wish to use these fonts for any other purpose, please contact the copyright owners for appropriate permissions. If you wish a font to be removed from this repository, please open an issue.
