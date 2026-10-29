// Lists every instruction that references the given addresses, with its function.
// Usage: analyzeHeadless <proj> taz -process taz.exe -noanalysis -readOnly -postScript XRefs.java <out.txt> <hex addr>...
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;
import java.io.PrintWriter;

public class XRefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        try (PrintWriter out = new PrintWriter(args[0])) {
            for (int i = 1; i < args.length; i++) {
                out.printf("== %s%n", args[i]);
                for (Reference r : getReferencesTo(toAddr(Long.parseLong(args[i], 16)))) {
                    Function f = getFunctionContaining(r.getFromAddress());
                    Instruction ins = getInstructionAt(r.getFromAddress());
                    out.printf("  %s %-6s %s  [%s]%n", r.getFromAddress(), r.getReferenceType().isWrite() ? "WRITE" : "read",
                               ins != null ? ins.toString() : "?", f != null ? f.getEntryPoint() : "-");
                }
            }
        }
    }
}
