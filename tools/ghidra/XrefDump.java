import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import ghidra.program.model.mem.Memory;

public class XrefDump extends GhidraScript {
    // Addresses of interest, as raw FILE offsets (we'll add the base 0x100000 CS0 load address).
    long[] fileOffsets = new long[] {
        0x010D88L, 0x011340L, 0x011468L, 0x01040AL, 0x0116BAL, 0x0154A0L
    };
    long base = 0x0L;

    @Override
    public void run() throws Exception {
        FunctionManager fm = currentProgram.getFunctionManager();
        int nFuncs = fm.getFunctionCount();
        println("=== Function count from auto-analysis: " + nFuncs + " ===");
        int shown = 0;
        FunctionIterator fit = fm.getFunctions(true);
        while (fit.hasNext() && shown < 200) {
            Function f = fit.next();
            println("FUNC " + f.getEntryPoint() + "  " + f.getName());
            shown++;
        }

        for (long off : fileOffsets) {
            Address addr = toAddr(base + off);
            println("\n=== Target 0x" + Long.toHexString(base + off) + " (file offset 0x" + Long.toHexString(off) + ") ===");
            ReferenceIterator refs = currentProgram.getReferenceManager().getReferencesTo(addr);
            int count = 0;
            while (refs.hasNext()) {
                Reference r = refs.next();
                Address from = r.getFromAddress();
                println("  ref from " + from + "  type=" + r.getReferenceType());
                Instruction ins = currentProgram.getListing().getInstructionAt(from);
                if (ins != null) {
                    println("    insn: " + ins.toString());
                    // print a few instructions of context around it
                    Instruction cur = ins;
                    for (int i = 0; i < 3 && cur != null; i++) {
                        cur = cur.getNext();
                    }
                }
                count++;
            }
            if (count == 0) {
                println("  (no references found by Ghidra's analysis)");
                Data d = currentProgram.getListing().getDataAt(addr);
                if (d != null) println("  data at addr: " + d.toString());
                Instruction ins = currentProgram.getListing().getInstructionAt(addr);
                if (ins != null) println("  instruction at addr: " + ins.toString());
            }
        }
    }
}
