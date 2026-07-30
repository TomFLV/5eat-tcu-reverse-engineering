import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

import java.util.*;

/**
 * Seeds entry points and runs full auto-analysis, deriving the real interrupt
 * handlers from the ROM itself rather than hardcoding them.
 *
 * On this TCU family the vector layout is three levels deep; the useful level
 * is the handler address table at 0x20000 (31 x 4-byte slots). Most slots hold
 * the same default value (the main entry point) and only a handful are real
 * handlers. Seeding just those real ones is what unlocks the bulk of the code
 * region -- seeding every slot, or only the reset vector, does not.
 *
 * Works unchanged across firmware revisions, which matters because the handler
 * addresses shift between them.
 */
public class SeedAuto extends GhidraScript {

    private static final long VECTOR_TABLE = 0x20000L;
    private static final int  VECTOR_SLOTS = 31;

    @Override
    public void run() throws Exception {
        SymbolTable st = currentProgram.getSymbolTable();

        // Read the handler table and work out which value is the "unused" default.
        long[] slots = new long[VECTOR_SLOTS];
        Map<Long, Integer> freq = new HashMap<>();
        for (int i = 0; i < VECTOR_SLOTS; i++) {
            slots[i] = getInt(toAddr(VECTOR_TABLE + i * 4L)) & 0xFFFFFFFFL;
            freq.merge(slots[i], 1, Integer::sum);
        }
        long dflt = 0;
        int best = -1;
        for (Map.Entry<Long, Integer> e : freq.entrySet()) {
            if (e.getValue() > best) {
                best = e.getValue();
                dflt = e.getKey();
            }
        }
        println("Vector default 0x" + Long.toHexString(dflt) + " (x" + best + ")");

        // Seed set: reset, fallback boot path, main entry (the default), and every
        // genuinely distinct handler.
        TreeSet<Long> seeds = new TreeSet<>(Arrays.asList(0x0L, 0x4000L, dflt));
        for (long s : slots) {
            if (s != dflt && s != 0 && s != 0xFFFFFFFFL) {
                seeds.add(s);
            }
        }

        for (long v : seeds) {
            Address a = toAddr(v);
            println("  seeding 0x" + Long.toHexString(v));
            disassemble(a);
            createFunction(a, null);
            st.addExternalEntryPoint(a);
        }

        println("Running full auto-analysis (this takes a while)...");
        analyzeAll(currentProgram);

        FunctionManager fm = currentProgram.getFunctionManager();
        int insnCount = 0;
        long insnBytes = 0;
        for (InstructionIterator it = currentProgram.getListing().getInstructions(true);
             it.hasNext(); ) {
            Instruction i = it.next();
            insnBytes += i.getLength();
            insnCount++;
        }
        println("=== functions: " + fm.getFunctionCount());
        println("=== instructions: " + insnCount + " (" + insnBytes + " bytes)");

        for (long v : seeds) {
            Function f = fm.getFunctionAt(toAddr(v));
            println("  0x" + Long.toHexString(v) + " -> "
                    + (f == null ? "NONE" : f.getName() + " size=" + f.getBody().getNumAddresses()));
        }
    }
}
