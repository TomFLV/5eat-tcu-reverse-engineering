import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;

public class DumpGearFunc extends GhidraScript {
    @Override
    public void run() throws Exception {
        FunctionManager fm = currentProgram.getFunctionManager();
        Function f = fm.getFunctionAt(toAddr(0x0004ca24L));
        println("Function: " + f.getName() + " size=" + f.getBody().getNumAddresses());
        Listing listing = currentProgram.getListing();
        Instruction ins = listing.getInstructionAt(f.getEntryPoint());
        int count = 0;
        while (ins != null && count < 260) {
            println(ins.getAddress() + "  " + ins.toString());
            ins = ins.getNext();
            if (ins != null && !f.getBody().contains(ins.getAddress())) break;
            count++;
        }
    }
}
