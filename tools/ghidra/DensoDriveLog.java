// Run a simulated drive against a Denso TCU and log every RAM address that moves.
//
// WHY THIS AND NOT THE PROBE. Probing one function at a time with a fresh emulator
// each run costs ~20 seconds of JVM and project load per data point, so a drive of
// any length is impossible that way. It also throws the state away between runs,
// which is exactly wrong: a transmission controller is a state machine, and what it
// does at this instant depends on where it has been.
//
// This keeps one emulator alive for the whole drive. Each step writes the inputs for
// that instant, runs the control function, and records every RAM byte that changed.
// State carries forward, so integrators wind up, timers advance and shift decisions
// depend on the gear the previous step left behind.
//
// Usage as a headless post-script:
//
//   DensoDriveLog.java <entry> <profile.csv> <out.csv> [maxStepsPerTick]
//
// The profile is one row per tick:
//
//   tick,addr:size=value,addr:size=value,...
//   0,FFFF9F55:1=0,FFFF8A88:1=10
//   1,FFFF9F55:1=0,FFFF8A88:1=12
//
// The output is one row per tick with every RAM address whose value changed during
// that tick, so a column that moves with an input is that input's effect, and one
// that moves on its own is internal state.
//@category 5EAT

import ghidra.app.script.GhidraScript;
import ghidra.app.emulator.EmulatorHelper;
import ghidra.program.model.address.Address;

import java.io.*;
import java.util.*;

public class DensoDriveLog extends GhidraScript {

    private static final long RAM_BASE = 0xFFFF0000L;
    private static final int RAM_SIZE = 0x10000;
    private static final long SENTINEL = 0x00FFFFF0L;

    @Override
    public void run() throws Exception {
        String[] a = getScriptArgs();
        if (a.length < 3) {
            println("RESULT error=need <entry> <profile.csv> <out.csv>");
            return;
        }
        long entry = Long.parseLong(a[0].replace("0x", ""), 16);
        long maxSteps = a.length > 3 ? Long.parseLong(a[3]) : 200000L;

        List<String[]> profile = new ArrayList<>();
        try (BufferedReader r = new BufferedReader(new FileReader(a[1]))) {
            String line;
            while ((line = r.readLine()) != null) {
                line = line.trim();
                if (!line.isEmpty() && !line.startsWith("#")) {
                    profile.add(line.split(","));
                }
            }
        }
        if (profile.isEmpty()) {
            println("RESULT error=empty profile");
            return;
        }

        EmulatorHelper emu = new EmulatorHelper(currentProgram);
        PrintWriter out = new PrintWriter(new BufferedWriter(new FileWriter(a[2]), 1 << 20));
        try {
            byte[] prev = null;
            Set<Long> everChanged = new TreeSet<>();
            List<Map<Long, Integer>> ticks = new ArrayList<>();
            long totalInstr = 0;

            for (String[] row : profile) {
                if (monitor.isCancelled()) {
                    break;
                }
                // Inputs for this instant.
                for (int i = 1; i < row.length; i++) {
                    String[] kv = row[i].split("=", 2);
                    if (kv.length != 2) {
                        continue;
                    }
                    String[] spec = kv[0].split(":", 2);
                    long where = Long.parseLong(spec[0].trim(), 16);
                    int size = spec.length > 1 ? Integer.parseInt(spec[1]) : 1;
                    long value = Long.decode(kv[1].trim());
                    byte[] bytes = new byte[size];
                    for (int b = 0; b < size; b++) {
                        bytes[size - 1 - b] = (byte) ((value >> (8 * b)) & 0xFF);
                    }
                    emu.writeMemory(toAddr(where), bytes);
                }

                // One tick of the control function. Registers are reset each tick
                // but MEMORY IS NOT - that is the whole point.
                emu.writeRegister(emu.getPCRegister(), entry);
                emu.writeRegister("r15", 0xFFFFBF00L);
                emu.writeRegister("pr", SENTINEL);

                long steps = 0;
                while (steps++ < maxSteps) {
                    Address pc = emu.getExecutionAddress();
                    if (pc == null) {
                        break;
                    }
                    long off = pc.getOffset();
                    if (off == SENTINEL || off == 0 || off > 0x000FFFFFL) {
                        break;
                    }
                    if (!emu.step(monitor)) {
                        break;
                    }
                }
                totalInstr += steps;

                byte[] now = emu.readMemory(toAddr(RAM_BASE), RAM_SIZE);
                Map<Long, Integer> delta = new LinkedHashMap<>();
                if (prev != null) {
                    for (int i = 0; i < RAM_SIZE; i++) {
                        if (now[i] != prev[i]) {
                            long addr = RAM_BASE + i;
                            delta.put(addr, now[i] & 0xFF);
                            everChanged.add(addr);
                        }
                    }
                }
                ticks.add(delta);
                prev = now;
            }

            // One column per address that moved at any point in the drive.
            List<Long> cols = new ArrayList<>(everChanged);
            StringBuilder head = new StringBuilder("tick");
            for (Long c : cols) {
                head.append(String.format(",%08X", c));
            }
            out.println(head);

            Map<Long, Integer> state = new HashMap<>();
            for (int t = 0; t < ticks.size(); t++) {
                state.putAll(ticks.get(t));
                StringBuilder line = new StringBuilder(Integer.toString(t));
                for (Long c : cols) {
                    Integer v = state.get(c);
                    line.append(',').append(v == null ? "" : v.toString());
                }
                out.println(line);
            }

            println(String.format(
                "RESULT ticks=%d instructions=%d changed=%d -> %s",
                ticks.size(), totalInstr, cols.size(), a[2]));
        } finally {
            out.close();
            emu.dispose();
        }
    }
}
