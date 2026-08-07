#!/usr/bin/env python3
"""Rename the interface from ECU to TCU, in the translation bundles.

The interface came from RomRaider, which is an engine tool, so it says ECU on
every screen: "ECU Revision", "ECU Definition Error", "Please check ECU definition
file". This build edits transmission controllers and ships transmission
definitions, so the noun is wrong wherever it refers to the controller being
edited.

Run from build-standalone.sh against the checked-out i18n directory, rather than
carried as patch hunks: it is sixty strings across twenty bundles including
translations, and a diff that size would need rebasing on every upstream change
while telling a reader nothing that the rules here do not.

    python3 rename-ecu-to-tcu.py <path to i18n>

TWO THINGS ARE DELIBERATELY LEFT ALONE.

The resource KEYS - LBLECU, ECUDEF, RESETECU - are internal identifiers referenced
from Java source. Renaming them means touching every call site and changes nothing
anyone sees.

The strings about the engine controller as a distinct thing stay as they are:
global timing adjustment, idle RPM, the ATM sensor. There the word is correct, and
renaming it would turn a true sentence about an engine into a false one about a
transmission. They are listed explicitly rather than guessed at.
"""

import io
import os
import re
import sys

KEEP = {
    "GAATITLE", "GAACONFIRM", "GAASUCCESSMSG", "GAAERRORMSG", "GAACANCELMSG",
    "ELEVATION_TT",
}

# French elides the vowel in de/le before a vowel sound, so the original bundles
# correctly read "Editeur d'ECU". ECU begins with a vowel sound and TCU does not,
# so substituting the noun alone leaves "Editeur d'TCU" - wrong in a way a French
# speaker notices at once. Order matters: "de l'TCU" before the bare "l'TCU", or
# it becomes "de le TCU".
FRENCH = [
    (r"\bde l'TCU\b", "du TCU"),
    (r"\bd'TCU\b", "de TCU"),
    (r"\bl'TCU\b", "le TCU"),
]


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: rename-ecu-to-tcu.py <path to i18n directory>")
    src = sys.argv[1]
    if not os.path.isdir(src):
        sys.exit("not a directory: %s" % src)

    renamed, files = 0, 0
    for root, _dirs, names in os.walk(src):
        for name in sorted(names):
            if not name.endswith(".properties"):
                continue
            path = os.path.join(root, name)
            raw = io.open(path, "rb").read()
            try:
                text, enc = raw.decode("utf-8"), "utf-8"
            except UnicodeDecodeError:
                text, enc = raw.decode("latin-1"), "latin-1"

            out, n = [], 0
            for line in text.split("\n"):
                if not line or line.lstrip().startswith("#") or "=" not in line:
                    out.append(line)
                    continue
                key, _, value = line.partition("=")
                if key.strip() in KEEP or "ECU" not in value:
                    out.append(line)
                    continue
                new = re.sub(r"\bECU's\b", "TCU's", value)
                new = re.sub(r"\bECU\b", "TCU", new)
                if new != value:
                    n += 1
                out.append(key + "=" + new)

            result = "\n".join(out)
            for pat, rep in FRENCH:
                result = re.sub(pat, rep, result)

            if result != text:
                io.open(path, "w", encoding=enc, newline="\n").write(result)
                renamed += n
                files += 1

    print("  %d strings renamed across %d bundle(s)" % (renamed, files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
