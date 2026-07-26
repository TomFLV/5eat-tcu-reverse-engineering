import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;

public class ContextDump extends GhidraScript {
    @Override
    public void run() throws Exception {
        long[] points = new long[] {0x0005cd5aL, 0x0005d53eL};
        Listing listing = currentProgram.getListing();
        FunctionManager fm = currentProgram.getFunctionManager();
        for (long p : points) {
            Address a = toAddr(p);
            Function f = fm.getFunctionContaining(a);
            println("\n=== Context around 0x" + Long.toHexString(p) + "  (function: " + (f == null ? "NONE" : f.getName() + " @ " + f.getEntryPoint()) + ") ===");
            Instruction ins = listing.getInstructionAt(a);
            // back up ~25 instructions
            Instruction cur = ins;
            for (int i = 0; i < 25 && cur != null; i++) {
                Instruction prev = cur.getPrevious();
                if (prev == null) break;
                cur = prev;
            }
            // print forward ~50 instructions from there
            for (int i = 0; i < 55 && cur != null; i++) {
                String marker = cur.getAddress().equals(a) ? "  <<<< TARGET" : "";
                println(cur.getAddress() + "  " + cur.toString() + marker);
                cur = cur.getNext();
            }
        }
    }
}
