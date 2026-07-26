import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;

public class DisasmTest extends GhidraScript {
    @Override
    public void run() throws Exception {
        Address start = toAddr(0x0);
        disassemble(start);
        Listing listing = currentProgram.getListing();
        Instruction ins = listing.getInstructionAt(start);
        int count = 0;
        println("=== Disassembly from address 0 ===");
        while (ins != null && count < 40) {
            println(ins.getAddress() + "  " + ins.toString() + "   ; bytes=" + ins.getBytes().length);
            ins = ins.getNext();
            count++;
        }
        if (count == 0) {
            println("No instructions decoded at address 0 -- disassembly failed here.");
        }

        // Also try disassembling at the start of what we believe is the code region: file offset 0x20000
        Address codeStart = toAddr(0x20000);
        disassemble(codeStart);
        Instruction ins2 = listing.getInstructionAt(codeStart);
        println("\n=== Disassembly from address 0x20000 (suspected code region) ===");
        int count2 = 0;
        while (ins2 != null && count2 < 40) {
            println(ins2.getAddress() + "  " + ins2.toString());
            ins2 = ins2.getNext();
            count2++;
        }
        if (count2 == 0) {
            println("No instructions decoded at 0x20000 either.");
        }
    }
}
