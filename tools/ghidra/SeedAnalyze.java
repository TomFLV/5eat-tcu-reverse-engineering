import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class SeedAnalyze extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] seeds = new long[] {0x0L, 0x4000L, 0x20100L};
        SymbolTable st = currentProgram.getSymbolTable();
        for (long s : seeds) {
            Address a = toAddr(s);
            disassemble(a);
            createFunction(a, null);
            st.addExternalEntryPoint(a);
        }
        println("Running full auto-analysis (this may take a while)...");
        analyzeAll(currentProgram);
        println("Auto-analysis complete.");

        FunctionManager fm = currentProgram.getFunctionManager();
        int nFuncs = fm.getFunctionCount();
        println("=== Function count after seeded analysis: " + nFuncs + " ===");

        // Report code coverage: total disassembled instruction bytes
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
}
