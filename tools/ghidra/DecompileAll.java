import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionManager;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.util.task.ConsoleTaskMonitor;
import java.io.PrintWriter;
import java.io.FileWriter;

public class DecompileAll extends GhidraScript {
    @Override
    public void run() throws Exception {
        DecompInterface decomp = new DecompInterface();
        DecompileOptions opts = new DecompileOptions();
        decomp.setOptions(opts);
        decomp.openProgram(currentProgram);

        FunctionManager fm = currentProgram.getFunctionManager();
        String outPath = System.getProperty("decompile.out", "decompiled.c");
        PrintWriter out = new PrintWriter(new FileWriter(outPath));

        FunctionIterator fit = fm.getFunctions(true);
        int ok = 0, fail = 0;
        while (fit.hasNext()) {
            Function f = fit.next();
            out.println("\n// ================= " + f.getName() + " @ " + f.getEntryPoint() + " =================");
            try {
                DecompileResults res = decomp.decompileFunction(f, 30, new ConsoleTaskMonitor());
                if (res.decompileCompleted()) {
                    out.println(res.getDecompiledFunction().getC());
                    ok++;
                } else {
                    out.println("// DECOMPILE FAILED: " + res.getErrorMessage());
                    fail++;
                }
            } catch (Exception e) {
                out.println("// EXCEPTION: " + e.getMessage());
                fail++;
            }
        }
        out.close();
        decomp.dispose();
        println("Decompiled " + ok + " functions OK, " + fail + " failed. Wrote " + outPath);
    }
}
