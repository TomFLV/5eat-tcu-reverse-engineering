import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class SeedRealISRs extends GhidraScript {
    @Override
    public void run() throws Exception {
        SymbolTable st = currentProgram.getSymbolTable();
        long[] targets = new long[] {0x000245BCL, 0x00020A14L, 0x00026748L, 0x00025828L};
        for (long v : targets) {
            Address a = toAddr(v);
            disassemble(a);
            createFunction(a, null);
            st.addExternalEntryPoint(a);
        }
        println("Running full auto-analysis...");
        analyzeAll(currentProgram);
        println("Auto-analysis complete.");

        FunctionManager fm = currentProgram.getFunctionManager();
        println("=== Function count: " + fm.getFunctionCount() + " ===");
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

        for (long v : targets) {
            Address a = toAddr(v);
            Function f = fm.getFunctionAt(a);
            println("Target 0x" + Long.toHexString(v) + " -> function: " + (f == null ? "NONE" : f.getName() + " size=" + f.getBody().getNumAddresses()));
        }
    }
}
