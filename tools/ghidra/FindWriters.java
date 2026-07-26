import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;

public class FindWriters extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] targets = new long[] {0x0080885AL, 0x00808B40L, 0x00808B3CL};
        Listing listing = currentProgram.getListing();
        FunctionManager fm = currentProgram.getFunctionManager();
        for (long t : targets) {
            Address a = toAddr(t);
            println("\n=== References to 0x" + Long.toHexString(t) + " ===");
            ReferenceIterator refs = currentProgram.getReferenceManager().getReferencesTo(a);
            int count = 0;
            while (refs.hasNext()) {
                Reference r = refs.next();
                Address from = r.getFromAddress();
                Instruction ins = listing.getInstructionAt(from);
                Function f = fm.getFunctionContaining(from);
                println("  " + from + "  " + (ins == null ? "?" : ins.toString()) + "   [in " + (f == null ? "?" : f.getName()) + "]");
                count++;
            }
            if (count == 0) println("  (none found)");
        }
    }
}
