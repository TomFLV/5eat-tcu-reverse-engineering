# Getting this working in RomRaider

Tested against RomRaider 1.0.0 (DEC01 2023) on Windows. Nothing here is
version-specific in a way that should break on other builds, but that's the one it
was developed against.

---

## 1. Point RomRaider at the definition file

RomRaider reads its configuration from `%USERPROFILE%\.RomRaider\settings.xml`.
You can set this through the GUI (**File → Settings → Definitions**), or edit the
file directly. The relevant element is:

```xml
<ecudefinitionfile>C:\path\to\definitions\5eat_tcu_91D1206000_romraider_def.xml</ecudefinitionfile>
```

If you edit `settings.xml` by hand, close RomRaider first — it rewrites the file on
exit and will overwrite your change.

## 2. Open the ROM

**File → Open** and select `rom/91D1206000_5EAT.bin`.

You should get a category tree on the left with entries including *Info*,
*Transmission - Gear Ratios*, *Transmission - Temperature*,
*Diagnostic Trouble Codes*, and several *Transmission - …* table groups.

Read the **Info → Read This First** entry before editing anything.

---

## 3. If no tables appear

This is the common failure, and it's almost always one of two things.

**Check the file is actually a file.** If you extracted the ROM from a zip, you may
have ended up with a *directory* named `91D1206000_5EAT.bin` containing the real
file. RomRaider will open it without complaint and show nothing.

**Check the ROM matches.** The definition identifies the ROM by matching the ASCII
string `MB431M` at offset `0x8008`. If your ROM is a different firmware revision,
RomRaider will correctly refuse to apply this definition — that's the safety
mechanism working, not a bug. Confirm with:

```bash
xxd -s 0x8008 -l 16 your_rom.bin
```

You should see `MB431M  VF000`. If you see something else, this definition is not
for your ROM, and the table addresses will not transfer — they differ between
firmware revisions.

### Turning on debug logging

RomRaider logs almost nothing at default level. To see what it's actually doing,
edit `<RomRaider install>\lib\log4j.properties` (needs admin rights, it's under
Program Files):

```properties
log4j.rootLogger=debug,stdout,LOGFILE
```

The log then lands in `%USERPROFILE%\.RomRaider\rr_system.log`.

Be aware RomRaider scans the *whole* definitions directory. If you have unrelated
`.xml` files in there — a saved web page, for instance — you'll see parse errors
that have nothing to do with this definition.

---

## 4. Fixing the checksum — do not skip this

**RomRaider cannot correct this ROM's checksum.** Its checksum support is hardcoded
per known ECU family in Java, not driven by the definition XML, and this M32R TCU
isn't a family it knows. There is deliberately no "Checksum Fix" table in this
definition, because including one would imply it works.

After saving a modified ROM out of RomRaider:

```bash
python tools/checksum.py --fix edited.bin
```

To check without modifying:

```bash
python tools/checksum.py --verify edited.bin
```

The algorithm is a 32-bit big-endian two's-complement additive checksum stored
redundantly at `0x8000` and `0x8004`, computed over the first `0x60000` bytes.
Details in [TECHNICAL-NOTES.md](TECHNICAL-NOTES.md).

If you'd rather not take the tool's word for it, there's a test suite:

```bash
python tools/test_checksum.py                    # bundled ROM
python tools/test_checksum.py path/to/other.bin  # any other ROM
```

It edits a copy, confirms the tool flags it, fixes it, and confirms that undoing
the edit and re-fixing reproduces the original ROM byte for byte. Verification is
done by independently re-deriving the checksum invariant rather than by calling
the same function under test.

---

## 5. What you can and can't do with this

**This is a static file editor only.** You cannot connect to the vehicle through
RomRaider with this definition. RomRaider's live logging and flashing are built
around Subaru engine ECUs on a completely different CPU family (Renesas SH) — this
is an M32R TCU and the transports differ.

For actually reading and writing the TCU, look at
[FastECU](https://github.com/miikasyvanen/FastECU), which has real support for this
chip family (`sub_tcu_hitachi_m32r_can`). Its protocol config confirms flashing
happens over CAN (`iso15765`) while logging uses K-Line SSM.

---

## 6. Reading the definition file sensibly

A few conventions used throughout:

- **`raw`** as the unit means there is no confirmed conversion. The value is still
  the real stored number and still editable — it just isn't labelled in engineering
  units, because guessing would be worse than admitting it.
- **`userlevel="5"`** marks expert-only tables. The *Shift State Bit Pattern* tables
  are the main ones: every stock value is a power of two because they're bit
  patterns, not numbers. Editing them as ordinary values will produce invalid
  patterns, and an invalid clutch pattern can command two elements at once and bind
  the driveline.
- **DTC "off" states are experimental.** They follow the convention used by real
  Subaru engine ECU definitions (zero the code bytes), but that behaviour has not
  been confirmed on this TCU — the code that reads the DTC table wasn't located.
  Verify the code is actually gone before relying on it.

---

## 7. Regenerating the definition

The XML is generated, not hand-maintained. Don't hand-edit it — edit the generator
and re-run:

```bash
python tools/generate_romraider_def.py
python tools/validate_xml_defs.py
```

The validator re-derives every table's address from the ROM's own embedded count
fields and checks them against what the XML claims. It should report no errors.
This exists because hand-editing addresses caused real bugs early on.
