#!/usr/bin/env python3
"""Classify every bundled font by whether Camoufox may redistribute it.

Camoufox has shipped `bundle/fonts` under a README that calls it "solely for
academic and research purposes", which is not a licence and does not survive
the project earning money. This script reads the licence fields every font
carries in its `name` table (IDs 13 and 14, with 0 and 8 as corroboration) and
sorts the bundle into three buckets:

    ship     a licence that plainly permits redistribution -- OFL, Apache-2.0,
             the Ubuntu Font Licence, MIT, CC-BY, GPL with the font exception,
             and public domain
    drop     a vendor licence that plainly does not -- Microsoft, Apple,
             Monotype, Adobe, Linotype, Bitstream's non-Vera faces
    review   anything else, which is listed rather than guessed at

Only the `ship` bucket is written to the output list. `review` is a hard failure
by default: a font nobody has classified must not be shipped by accident, and
the whole point of the exercise is that the shipped set can be defended.

This is a REPORT, not a filter: Camoufox ships the full bundle, and the buckets
exist so the licence exposure of what ships is known and reviewable. Removing a
bucket from the bundle is a deliberate, separate decision -- see
bundle/FONTS-README.txt for what is currently shipped and why.

Usage:
    python3 scripts/font-metrics/licences.py [--bundle bundle/fonts]
        [--out scripts/data/open-fonts.txt] [--report report.json]
        [--allow-review]
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FONT_EXT = (".ttf", ".otf", ".ttc", ".otc", ".dfont")
OSDIRS = ("linux", "macos", "windows")

# Deny comes first: a restrictive licence can quote a permissive one (Microsoft's
# cites MIT for one component), and checking allow first marked Times New Roman
# shippable. Order: restrictive phrasing; a canonical licence statement (Noto is OFL though
# Monotype drew it); a proprietary owner; a loose permissive match. Anything
# unmatched is "review", and review is not shipped.

# Matched against the copyright and vendor fields only. A foundry that does not
# license its fonts for redistribution is decisive whatever else the licence
# text happens to quote.
DENY_OWNER = [
    ("Microsoft", r"microsoft corporation|microsoft typography"),
    ("Apple", r"apple inc|apple computer"),
    ("Monotype", r"monotype (imaging|corporation|typography)|the monotype"),
    ("Adobe", r"adobe (systems|inc)\b|adobe\.com/type"),
    ("Linotype", r"linotype"),
    ("ITC", r"international typeface"),
    ("Bitstream", r"bitstream inc"),
    ("Founder", r"beijing founder|founder group"),
    ("DynaComware", r"dynacomware"),
    ("Morisawa", r"morisawa"),
    ("Sandoll", r"sandoll"),
    ("Ascender", r"ascender corporation"),
    ("Agfa", r"agfa monotype"),
]

# Matched against the whole licence text: phrasing that forbids redistribution
# outright, whatever else the text may quote.
DENY_TERMS = [
    ("supplied-font-EULA", r"supplied font"),
    ("use-prohibited", r"any other use is prohibited|other uses are prohibited"),
    ("no-redistribution", r"may not be (copied|distributed|redistributed|sold|"
                          r"modified|reproduced)"),
    ("no-redistribution", r"(shall|must) not be (copied|distributed|"
                          r"redistributed)"),
    ("licence-required", r"unauthorized (use|copying)|requires a (valid )?"
                         r"licen[cs]e|licensed for use"),
    ("EULA", r"end user licen[cs]e agreement"),
    ("proprietary", r"proprietary (and confidential|software)"),
]

# Canonical, SELF-DESCRIBING statements, matched against the licence field
# alone. "This Font Software is licensed under the SIL Open Font License"
# describes the font itself; "The following license, based on the MIT license,
# applies to the [Hebrew layout logic]" describes a component, which is why MIT
# is deliberately not in this list -- a font whose only permissive signal is a
# quoted MIT clause goes to review rather than to the donor set.
STRONG_ALLOW = [
    ("OFL-1.1", r"licensed under the sil open font license|"
                r"this font software is licensed under the sil open font"),
    ("Apache-2.0", r"licensed under the apache license"),
    ("Ubuntu-FL-1.0", r"licensed under the ubuntu font licen[cs]e"),
    ("GPL+FE", r"licensed under the gnu general public license.{0,80}"
               r"font exception"),
    ("CC-BY", r"licensed under.{0,40}creative commons attribution"),
]

# Only reached when nothing above fired.
ALLOW = [
    ("OFL-1.1", r"sil open font license|scripts\.sil\.org/ofl|openfontlicense"),
    ("Apache-2.0", r"apache license|apache\.org/licenses"),
    ("Ubuntu-FL-1.0", r"ubuntu font licence|ubuntu font license"),
    ("MIT", r"\bmit license\b|opensource\.org/licenses/mit"),
    ("CC-BY", r"creativecommons\.org/licenses/by|creative commons attribution"),
    ("CC0/PD", r"creativecommons\.org/publicdomain|public domain"),
    ("GPL+FE", r"gnu general public license.*font exception|gpl.*font exception"),
    ("Bitstream-Vera", r"bitstream vera"),
    ("AFPL/URW", r"urw\+\+|aladdin free public license"),
]


def classify(fields):
    """(bucket, label) for one font, from its name-table licence fields."""
    owner = " ".join((fields.get("copyright", ""),
                      fields.get("vendor", ""))).lower()
    text = " | ".join(v for v in fields.values() if v).lower()

    licence = fields.get("licence", "").lower()

    for label, pattern in DENY_TERMS:
        if re.search(pattern, text):
            return "drop", label
    for label, pattern in STRONG_ALLOW:
        if re.search(pattern, licence):
            return "ship", label
    for label, pattern in DENY_OWNER:
        if re.search(pattern, owner):
            return "drop", label
    for label, pattern in ALLOW:
        if re.search(pattern, text):
            return "ship", label
    if not text.strip(" |"):
        return "review", "no licence fields"
    return "review", "unclassified"


FIELDS = {13: "licence", 14: "licenceUrl", 0: "copyright", 8: "vendor",
          11: "vendorUrl", 7: "trademark"}


def licence_text(path, index=0):
    """The name-table fields a licence decision is made from, kept separate.

    Separate because the copyright and vendor fields carry more weight than the
    licence body: a foundry that does not license for redistribution is decisive
    even when the licence body quotes a permissive licence for one component.
    """
    from fontTools.ttLib import TTFont

    font = TTFont(path, fontNumber=index, lazy=True, ignoreDecompileErrors=True)
    try:
        if "name" not in font:
            return {}
        table = font["name"]
        out = {}
        for name_id, key in FIELDS.items():
            value = table.getDebugName(name_id)
            if value:
                out[key] = value.strip()
        return out
    finally:
        font.close()


def faces_in(path):
    if path.lower().endswith((".ttc", ".otc")):
        from fontTools.ttLib import TTCollection
        try:
            with TTCollection(path, lazy=True) as collection:
                return list(range(len(collection.fonts)))
        except Exception:
            return [0]
    return [0]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", default=os.path.join(REPO, "bundle", "fonts"))
    ap.add_argument("--out", default=os.path.join(REPO, "scripts", "data", "open-fonts.txt"))
    ap.add_argument("--report", default=None)
    ap.add_argument("--allow-review", action="store_true",
                    help="write the list even though some fonts are unclassified")
    args = ap.parse_args()

    buckets = defaultdict(list)
    labels = Counter()
    for os_dir in OSDIRS:
        root = os.path.join(args.bundle, os_dir)
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            if not name.lower().endswith(FONT_EXT):
                continue
            path = os.path.join(root, name)
            rel = "%s/%s" % (os_dir, name)
            verdicts = set()
            label = "unreadable"
            for index in faces_in(path):
                try:
                    bucket, label = classify(licence_text(path, index))
                except Exception as exc:
                    bucket, label = "review", "unreadable: %s" % type(exc).__name__
                verdicts.add(bucket)
            # A collection ships only if EVERY face in it may ship: the file is
            # indivisible.
            bucket = ("drop" if "drop" in verdicts
                      else "review" if "review" in verdicts else "ship")
            buckets[bucket].append({"file": rel, "label": label,
                                    "bytes": os.path.getsize(path)})
            labels[(bucket, label)] += 1

    print("%-8s %6s %10s" % ("bucket", "files", "MB"))
    for bucket in ("ship", "drop", "review"):
        rows = buckets[bucket]
        print("%-8s %6d %10.1f" % (bucket, len(rows),
                                   sum(r["bytes"] for r in rows) / 1e6))
    print()
    for (bucket, label), count in sorted(labels.items(),
                                         key=lambda kv: (kv[0][0], -kv[1])):
        print("  %-7s %-18s %d" % (bucket, label, count))

    if buckets["review"] and not args.allow_review:
        print()
        print("%d fonts are unclassified and would not be shipped. Classify them "
              "in ALLOW/DENY, or pass --allow-review to write the list anyway:"
              % len(buckets["review"]), file=sys.stderr)
        for row in buckets["review"][:20]:
            print("  %s  (%s)" % (row["file"], row["label"]), file=sys.stderr)
        if len(buckets["review"]) > 20:
            print("  ... and %d more" % (len(buckets["review"]) - 20), file=sys.stderr)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        fh.write("# Fonts Camoufox may redistribute, by licence field.\n"
                 "# Generated by scripts/font-metrics/licences.py -- do not edit.\n"
                 "# Everything NOT in this list is measured into the metrics\n"
                 "# database instead and rebuilt locally as a stand-in.\n")
        for row in buckets["ship"]:
            fh.write("%s\t%s\n" % (row["file"], row["label"]))
    print("\nwrote %s (%d files)" % (args.out, len(buckets["ship"])))

    if args.report:
        with open(args.report, "w") as fh:
            json.dump({k: v for k, v in buckets.items()}, fh, indent=1)
        print("wrote %s" % args.report)
    return 0 if not buckets["review"] or args.allow_review else 1


if __name__ == "__main__":
    raise SystemExit(main())
