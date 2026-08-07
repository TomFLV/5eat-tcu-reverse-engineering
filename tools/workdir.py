#!/usr/bin/env python3
"""Where this project's scratch space and inputs live, for anyone who clones it.

Most of the emulator tooling was written against one machine and says so: paths
like D:/5eat-work and C:/Users/Tom/Desktop/... were baked into fifteen files.
They work there and nowhere else, which for a public repository means the tools
cannot be run by the people the repository is for.

Everything resolves from two things instead:

  the repository root      computed from this file's location, so ROMs, listings
                           and definitions are always found relative to the clone

  the work directory       scratch space for the emulator, its build, and the
                           large intermediate files that should never be committed.
                           Set FIVEEAT_WORK to choose it; the default is a
                           "work" directory beside the repository.

Both a native and a WSL form are provided, because the emulator is built and run
under WSL while most of the driving scripts are Python on Windows, and translating
between the two by hand is how a run once wrote to one file and read a stale
other one.

    from workdir import REPO, WORK, WORK_WSL, wsl, rom, listing
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

#: Scratch space. Large, regenerable, and deliberately outside the repository.
WORK = os.environ.get("FIVEEAT_WORK") or os.path.join(os.path.dirname(REPO), "work")


def wsl(path):
    """A Windows path as WSL sees it. Returns POSIX paths unchanged.

    os.path.join on Windows produces backslashes, which WSL does not treat as
    separators, so a path built one way and used the other silently refers to
    something else. This is the one place that conversion happens.
    """
    p = str(path).replace("\\", "/")
    if len(p) > 1 and p[1] == ":":
        return "/mnt/%s%s" % (p[0].lower(), p[2:])
    return p


WORK_WSL = wsl(WORK)
REPO_WSL = wsl(REPO)


def ensure(*parts):
    """A directory under the work area, created if needed."""
    d = os.path.join(WORK, *parts)
    os.makedirs(d, exist_ok=True)
    return d


def rom(name, denso=True):
    """A ROM image by filename, from the family directory it belongs to."""
    return os.path.join(REPO, "rom-denso" if denso else "rom", name)


def listing(name):
    return os.path.join(REPO, "disasm-denso", name)


#: The image most of the Denso analysis is written against - the one whose
#: listing exists and against which addresses in FINDINGS are quoted.
DENSO_REFERENCE = "Impreza_STI_3.583_JDM2011.bin"
DENSO_ROM = rom(DENSO_REFERENCE)
DENSO_ASM = listing(DENSO_REFERENCE.replace(".bin", ".asm"))
SH2 = os.path.join(WORK, "sh2", "sh2")
SH2_WSL = wsl(SH2)


if __name__ == "__main__":
    print("repository : %s" % REPO)
    print("work area  : %s   (set FIVEEAT_WORK to change)" % WORK)
    print("work (wsl) : %s" % WORK_WSL)
    print("denso rom  : %s  %s" % (DENSO_ROM,
                                   "found" if os.path.exists(DENSO_ROM) else "MISSING"))
    print("emulator   : %s  %s" % (SH2, "built" if os.path.exists(SH2) else "not built"))
