import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class SeedVectors extends GhidraScript {
    @Override
    public void run() throws Exception {
        SymbolTable st = currentProgram.getSymbolTable();

        // Basic M32R exception vectors: RI, SBI, RIE, AE (16 bytes apart), then 16 TRAP vectors + EI (4 bytes apart)
        long[] basicVectors = new long[] {
            0x00L, 0x10L, 0x20L, 0x30L,
            0x40L, 0x44L, 0x48L, 0x4CL, 0x50L, 0x54L, 0x58L, 0x5CL,
            0x60L, 0x64L, 0x68L, 0x6CL, 0x70L, 0x74L, 0x78L, 0x7CL,
            0x80L
        };

        // Secondary dispatch table: 31 entries at 0x94..0x10C, each POINTING AT an ISR stub
        // (we read these values with Python already: 0x20000, 0x20004, ..., 0x20078)
        long[] isrStubs = new long[31];
        for (int i = 0; i < 31; i++) {
            isrStubs[i] = 0x20000L + i * 4L;
        }

        int seeded = 0;
        for (long v : basicVectors) {
            seeded += seedOne(toAddr(v), st);
        }
        for (long v : isrStubs) {
            seeded += seedOne(toAddr(v), st);
        }
        println("Seeded " + seeded + " addresses (out of " + (basicVectors.length + isrStubs.length) + " attempted)");

        println("Running full auto-analysis...");
        analyzeAll(currentProgram);
        println("Auto-analysis complete.");

        FunctionManager fm = currentProgram.getFunctionManager();
        println("=== Function count after vector-seeded analysis: " + fm.getFunctionCount() + " ===");

        Listing listing = currentProgram.getListing();
        long totalInsnBytes = 0;
        InstructionIterator iit = listing.getInstructions(true);
        int insnCount = 0;
        while (iit.hasNext()) {
            Instruction i = iit.next();
            totalInsnBytes += i.getLength();
            insnCount++;
        }
        println("Total instructions disassembled: " + insnCount + "  (" + totalInsnBytes + " bytes)");
    }

    private int seedOne(Address a, SymbolTable st) {
        try {
            disassemble(a);
            createFunction(a, null);
            st.addExternalEntryPoint(a);
            return 1;
        } catch (Exception e) {
            println("  failed to seed " + a + ": " + e.getMessage());
            return 0;
        }
    }
}
