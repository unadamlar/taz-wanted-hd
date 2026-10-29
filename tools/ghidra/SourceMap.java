// Counts functions and maps them to source files via the assert path strings left in the exe.
// Usage: analyzeHeadless ... -postScript SourceMap.java <out.csv>
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.data.StringDataInstance;
import java.io.PrintWriter;
import java.util.*;
import java.util.regex.*;

public class SourceMap extends GhidraScript {
    private static final Pattern SRC = Pattern.compile("C:\\\\(Taz|Babel)\\\\[^\\s\"]+\\.(cpp|c|h)", Pattern.CASE_INSENSITIVE);

    @Override
    public void run() throws Exception {
        Listing listing = currentProgram.getListing();
        FunctionManager fm = currentProgram.getFunctionManager();
        ReferenceManager refs = currentProgram.getReferenceManager();

        Map<Function, Set<String>> fileOf = new HashMap<>();
        for (Data d : listing.getDefinedData(true)) {
            if (!StringDataInstance.isString(d)) continue;
            Matcher m = SRC.matcher(String.valueOf(d.getValue()));
            if (!m.find()) continue;
            String file = m.group().replace('\\', '/');
            for (Reference r : refs.getReferencesTo(d.getAddress())) {
                Function f = fm.getFunctionContaining(r.getFromAddress());
                if (f != null) fileOf.computeIfAbsent(f, k -> new TreeSet<>()).add(file);
            }
        }

        int total = 0, named = 0, thunks = 0;
        long bytes = 0;
        try (PrintWriter out = new PrintWriter(getScriptArgs()[0])) {
            out.println("address,size,name,source");
            for (Function f : fm.getFunctions(true)) {
                total++;
                if (f.isThunk()) thunks++;
                if (!f.getName().startsWith("FUN_") && !f.isThunk()) named++;
                long size = f.getBody().getNumAddresses();
                bytes += size;
                Set<String> files = fileOf.getOrDefault(f, Set.of());
                out.printf("%s,%d,%s,%s%n", f.getEntryPoint(), size, f.getName(), String.join(";", files));
            }
        }
        Set<String> allFiles = new TreeSet<>();
        fileOf.values().forEach(allFiles::addAll);
        println(String.format("SUMMARY functions=%d thunks=%d named_by_ghidra=%d code_bytes=%d functions_with_source=%d source_files=%d",
                total, thunks, named, bytes, fileOf.size(), allFiles.size()));
    }
}
