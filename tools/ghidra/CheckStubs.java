import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;

public class CheckStubs extends GhidraScript {
    @Override
    public void run() throws Exception {
        Listing listing = currentProgram.getListing();
        for (int i = 0; i < 31; i++) {
            long addrVal = 0x20000L + i * 4L;
            Address a = toAddr(addrVal);
            Instruction ins = listing.getInstructionAt(a);
            Data d = listing.getDataAt(a);
            CodeUnit cu = listing.getCodeUnitAt(a);
            String status;
            if (ins != null) {
                status = "INSTRUCTION: " + ins.toString();
            } else if (d != null) {
                status = "DATA: " + d.toString() + "  (type=" + d.getDataType().getName() + ")";
            } else if (cu != null) {
                status = "CODEUNIT(other): " + cu.toString();
            } else {
                status = "UNDEFINED";
            }
            println(String.format("0x%05X: %s", addrVal, status));
        }

        // Try to force-disassemble one and report the boolean result + any exception
        Address test = toAddr(0x20000L);
        boolean cleared = false;
        try {
            clearListing(test, test.add(0x7C));
            cleared = true;
        } catch (Exception e) {
            println("clearListing failed: " + e.getMessage());
        }
        println("cleared=" + cleared);
        boolean ok = disassemble(test);
        println("disassemble(0x20000) returned: " + ok);
        Instruction ins2 = listing.getInstructionAt(test);
        println("instruction now at 0x20000: " + (ins2 == null ? "still none" : ins2.toString()));
    }
}
