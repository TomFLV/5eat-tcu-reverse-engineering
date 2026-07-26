import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.util.task.ConsoleTaskMonitor;

public class Decompile extends GhidraScript {
    @Override
    public void run() throws Exception {
        DecompInterface decomp = new DecompInterface();
        DecompileOptions opts = new DecompileOptions();
        decomp.setOptions(opts);
        decomp.openProgram(currentProgram);

        long[] targets = new long[] {0x0004ca24L, 0x00045070L, 0x0004515cL, 0x0005cd04L, 0x0005d4e8L};
        FunctionManager fm = currentProgram.getFunctionManager();
        for (long t : targets) {
            Function f = fm.getFunctionAt(toAddr(t));
            if (f == null) { println("no function at 0x" + Long.toHexString(t)); continue; }
            println("\n\n=========== DECOMPILED: " + f.getName() + " @ " + f.getEntryPoint() + " ===========");
            DecompileResults res = decomp.decompileFunction(f, 60, new ConsoleTaskMonitor());
            if (res.decompileCompleted()) {
                println(res.getDecompiledFunction().getC());
            } else {
                println("DECOMPILE FAILED: " + res.getErrorMessage());
            }
        }
        decomp.dispose();
    }
}
