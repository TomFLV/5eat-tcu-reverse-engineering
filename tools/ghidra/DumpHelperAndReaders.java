import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;

public class DumpHelperAndReaders extends GhidraScript {
    @Override
    public void run() throws Exception {
        FunctionManager fm = currentProgram.getFunctionManager();
        Listing listing = currentProgram.getListing();

        println("\n\n=========== Helper 0x45070 ===========");
        dumpFunc(0x00045070L, fm, listing, 80);

        long[] readerContexts = new long[] {0x0004a530L, 0x0005c738L, 0x0005ccacL, 0x0005d478L};
        for (long p : readerContexts) {
            Address a = toAddr(p);
            Function f = fm.getFunctionContaining(a);
            println("\n\n=========== Context around 0x" + Long.toHexString(p) + " (in " + (f == null ? "?" : f.getName()) + ") ===========");
            Instruction ins = listing.getInstructionAt(a);
            Instruction cur = ins;
            for (int i = 0; i < 15 && cur != null; i++) {
                Instruction prev = cur.getPrevious();
                if (prev == null) break;
                cur = prev;
            }
            for (int i = 0; i < 35 && cur != null; i++) {
                String marker = cur.getAddress().equals(a) ? "  <<<< TARGET" : "";
                println(cur.getAddress() + "  " + cur.toString() + marker);
                cur = cur.getNext();
            }
        }
    }

    private void dumpFunc(long addr, FunctionManager fm, Listing listing, int max) {
        Function f = fm.getFunctionContaining(toAddr(addr));
        if (f == null) { println("no function at 0x" + Long.toHexString(addr)); return; }
        println("Function: " + f.getName() + " @ " + f.getEntryPoint() + " size=" + f.getBody().getNumAddresses());
        Instruction ins = listing.getInstructionAt(f.getEntryPoint());
        int count = 0;
        while (ins != null && count < max) {
            println(ins.getAddress() + "  " + ins.toString());
            ins = ins.getNext();
            if (ins != null && !f.getBody().contains(ins.getAddress())) break;
            count++;
        }
    }
}
