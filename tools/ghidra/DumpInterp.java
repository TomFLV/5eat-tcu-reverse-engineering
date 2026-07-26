import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;

public class DumpInterp extends GhidraScript {
    @Override
    public void run() throws Exception {
        Address a = toAddr(0x0004515cL);
        FunctionManager fm = currentProgram.getFunctionManager();
        Function f = fm.getFunctionContaining(a);
        println("Function containing 0x4515c: " + (f == null ? "NONE" : f.getName() + " @ " + f.getEntryPoint() + " size=" + f.getBody().getNumAddresses()));

        Listing listing = currentProgram.getListing();
        Instruction ins = listing.getInstructionAt(f != null ? f.getEntryPoint() : a);
        int count = 0;
        while (ins != null && count < 120) {
            println(ins.getAddress() + "  " + ins.toString());
            ins = ins.getNext();
            count++;
        }
    }
}
