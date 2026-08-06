// Emulate a Denso TCU function and record which calibration tables it reads.
//
// WHY. A table's shape says nothing about its purpose, and static context only says
// what a table is read *near*. Running the code says what it actually does: set the
// inputs, execute, and watch which addresses in the calibration region are read and
// what value comes back.
//
// Ghidra's p-code emulator works against whatever language the program was loaded
// with, so this runs on the SH-2E definition this project added rather than on an
// approximation of it.
//
// Usage, as a headless post-script:
//
//   DensoEmuTable.java <entry> [maxSteps] [reg=value ...]
//
//   DensoEmuTable.java 0x0002C3DA 20000 r4=0x40 r5=0x1000
//
// Registers are the SH-2 calling convention: r4 through r7 carry the first four
// arguments. Reads inside the calibration region are reported with the value.
//
// Nothing is written back to the program - the emulator works on its own state.
//@category 5EAT

import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;

import java.util.LinkedHashMap;
import java.util.Map;

public class DensoEmuTable extends GhidraScript {

    // Calibration data on these images starts here; below it is code.
    private static final long CAL_START = 0xA0000L;

    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        if (a.length < 1) {
            println("RESULT error=need an entry address");
            return;
        }
        Address entry = toAddr(Long.parseLong(a[0].replace("0x", ""), 16));
        long maxSteps = a.length > 1 ? Long.parseLong(a[1]) : 20000L;

        EmulatorHelper emu = new EmulatorHelper(currentProgram);
        try {
            emu.writeRegister(emu.getPCRegister(), entry.getOffset());
            // A stack somewhere harmless in on-chip RAM. The routines under test do
            // not use much, and anything they push is discarded with the emulator.
            emu.writeRegister("r15", 0xFFFFBF00L);

            // Arguments are either registers (r4=0x40) or memory, which is what the
            // interesting inputs are: the transmission logic reads pedal position,
            // gear and speed out of RAM, not off the stack. Memory is written as
            // @address:size=value, e.g. @FFFF30FB:1=0x80 for pedal at half travel.
            for (int i = 2; i < a.length; i++) {
                String[] kv = a[i].split("=", 2);
                if (kv.length != 2) {
                    continue;
                }
                long value = Long.decode(kv[1]);
                if (kv[0].startsWith("@")) {
                    String[] spec = kv[0].substring(1).split(":", 2);
                    long where = Long.parseLong(spec[0], 16);
                    int size = spec.length > 1 ? Integer.parseInt(spec[1]) : 1;
                    byte[] bytes = new byte[size];
                    for (int b = 0; b < size; b++) {
                        bytes[size - 1 - b] = (byte) ((value >> (8 * b)) & 0xFF);
                    }
                    emu.writeMemory(toAddr(where), bytes);
                    byte[] back = emu.readMemory(toAddr(where), size);
                    StringBuilder rb = new StringBuilder();
                    for (byte x : back) {
                        rb.append(String.format("%02X", x));
                    }
                    println("SET " + kv[0] + " readback=" + rb);
                    continue;
                }
                Register r = currentProgram.getLanguage().getRegister(kv[0]);
                if (r == null) {
                    println("unknown register: " + kv[0]);
                    continue;
                }
                emu.writeRegister(r, value);
            }

            // Returning to this address is the signal that the function finished.
            long sentinel = 0x00FFFFF0L;
            emu.writeRegister("pr", sentinel);

            // Record the path taken. Which tables the run touched is then read off
            // the literal loads on that path - the emulator does not expose a
            // memory-read hook, but every calibration access on this core goes
            // through a PC-relative literal, so the path is enough (section 46).
            Map<Long, Long> calReads = new LinkedHashMap<>();
            StringBuilder path = new StringBuilder();
            long steps = 0, romEnd = currentProgram.getMaxAddress().getOffset();
            String stopped = "maxSteps";

            while (steps++ < maxSteps) {
                if (monitor.isCancelled()) {
                    stopped = "cancelled";
                    break;
                }
                Address pc = emu.getExecutionAddress();
                if (pc == null) {
                    stopped = "no pc";
                    break;
                }
                long off = pc.getOffset();
                // Returning to the sentinel, to zero, or off the end of the image
                // all mean the routine is done rather than that it faulted.
                if (off == sentinel || off == 0 || off > romEnd) {
                    stopped = "returned";
                    break;
                }
                if (path.length() < 200000) {
                    path.append(String.format("%06X ", off));
                }
                if (!emu.step(monitor)) {
                    stopped = "fault: " + emu.getLastError();
                    break;
                }
            }
            println("PATH " + path.toString().trim());

            // Dump the RAM the run left behind. Without this the only observable is
            // the path, which cannot show a table index changing - and an index is
            // exactly what an input like pedal position produces. Ranges are given
            // as @start-end and printed as hex so two runs can be diffed.
            for (int i = 2; i < a.length; i++) {
                if (!a[i].startsWith("dump@")) {
                    continue;
                }
                String[] range = a[i].substring(5).split("-", 2);
                long from = Long.parseLong(range[0], 16);
                long to = range.length > 1 ? Long.parseLong(range[1], 16) : from + 16;
                int len = (int) Math.min(to - from + 1, 4096);
                if (len <= 0) {
                    continue;
                }
                byte[] mem = emu.readMemory(toAddr(from), len);
                StringBuilder hex = new StringBuilder();
                for (byte x : mem) {
                    hex.append(String.format("%02X", x));
                }
                println(String.format("DUMP %08X %s", from, hex));
            }

            // The emulator records what it faulted on rather than every access, so
            // report the calibration reads by replaying the instruction stream's
            // resolved literals instead: anything the run loaded that lands in the
            // calibration region is a table this path touched.
            StringBuilder b = new StringBuilder();
            b.append("RESULT entry=").append(entry)
             .append(" steps=").append(steps - 1)
             .append(" stopped=").append(stopped);
            b.append(" r0=0x").append(Long.toHexString(emu.readRegister("r0").longValue()));
            b.append(" r1=0x").append(Long.toHexString(emu.readRegister("r1").longValue()));
            println(b.toString());

            for (Map.Entry<Long, Long> e : calReads.entrySet()) {
                println(String.format("READ %06X = 0x%X", e.getKey(), e.getValue()));
            }
        } finally {
            emu.dispose();
        }
    }
}
