// Prints decompiled C for the functions containing the given addresses.
// Usage: analyzeHeadless <proj> taz -process taz.exe -noanalysis -readOnly -postScript Decompile.java <out.c> <hex addr>...
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import java.io.PrintWriter;

public class Decompile extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        DecompInterface dec = new DecompInterface();
        dec.openProgram(currentProgram);
        try (PrintWriter out = new PrintWriter(args[0])) {
            for (int i = 1; i < args.length; i++) {
                Function f = getFunctionContaining(toAddr(Long.parseLong(args[i], 16)));
                if (f == null) {
                    out.printf("// %s: no function%n%n", args[i]);
                    continue;
                }
                DecompileResults r = dec.decompileFunction(f, 60, monitor);
                out.printf("// ---- %s (%s) ----%n%s%n", f.getEntryPoint(), f.getName(),
                           r.decompileCompleted() ? r.getDecompiledFunction().getC() : r.getErrorMessage());
            }
        }
    }
}
