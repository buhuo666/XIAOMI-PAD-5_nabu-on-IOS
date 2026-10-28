// Static ARM64 Mach-O analysis only. Imported Apple binaries are never run.
// @category Nabu
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;

import java.io.File;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class ExportTimerCandidates extends GhidraScript {
    private static final String[] TERMS = {
        "mobiletimer", "mach_continuous_time", "dispatch_source",
        "dispatch_after", "timer", "deadline", "schedule", "wakeup",
        "wake", "sleep", "runloop", "run loop", "continuous time",
        "power assertion", "assertion", "expiration", "fire"
    };
    private static final int MAX_STRINGS = 1000;
    private static final int MAX_REFS = 12000;
    private static final int MAX_CANDIDATES = 800;
    private static final int MAX_DECOMPILED = 32;
    private static final int MAX_FUNCTION_CHARS = 16000;

    private static final class Candidate {
        final Function function;
        final Set<String> evidence = new LinkedHashSet<>();
        int score;

        Candidate(Function function) {
            this.function = function;
        }
    }

    private boolean matches(String value) {
        String lower = value.toLowerCase();
        for (String term : TERMS) {
            if (lower.contains(term)) return true;
        }
        return false;
    }

    private int weight(String value) {
        String lower = value.toLowerCase();
        if (lower.contains("mach_continuous_time") || lower.contains("dispatch_source") ||
            lower.contains("mobiletimer")) return 20;
        if (lower.contains("timer") || lower.contains("deadline") ||
            lower.contains("schedule") || lower.contains("wakeup") ||
            lower.contains("expiration")) return 10;
        return 3;
    }

    private String clean(String value) {
        return value.replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n");
    }

    private static String hex(long value) {
        return String.format("0x%x", value);
    }

    private void addCandidate(Map<Address, Candidate> candidates, Address from, String evidence) {
        Function function = getFunctionContaining(from);
        if (function == null || function.isExternal() || function.isThunk()) return;
        Address entry = function.getEntryPoint();
        Candidate candidate = candidates.get(entry);
        if (candidate == null) {
            if (candidates.size() >= MAX_CANDIDATES) return;
            candidate = new Candidate(function);
            candidates.put(entry, candidate);
        }
        if (candidate.evidence.add(evidence)) candidate.score += weight(evidence);
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 2) {
            throw new IllegalArgumentException(
                "usage: ExportTimerCandidates <target-id> <report-root>");
        }
        String target = args[0];
        File targetDir = new File(args[1], target);
        if (!targetDir.isDirectory() && !targetDir.mkdirs()) {
            throw new java.io.IOException("cannot create timer report directory");
        }

        Map<Address, Candidate> candidates = new LinkedHashMap<>();
        int stringsScanned = 0;
        int referencesScanned = 0;
        DataIterator data = currentProgram.getListing().getDefinedData(true);
        while (data.hasNext() && stringsScanned < MAX_STRINGS * 20 &&
               referencesScanned < MAX_REFS) {
            monitor.checkCancelled();
            Data item = data.next();
            Object raw = item.getValue();
            if (!(raw instanceof String)) continue;
            stringsScanned++;
            String value = (String) raw;
            if (!matches(value)) continue;
            for (Reference reference : getReferencesTo(item.getAddress())) {
                if (++referencesScanned > MAX_REFS) break;
                addCandidate(candidates, reference.getFromAddress(), value);
            }
        }

        FunctionIterator iterator = currentProgram.getFunctionManager().getFunctions(true);
        int functionsScanned = 0;
        while (iterator.hasNext()) {
            monitor.checkCancelled();
            Function function = iterator.next();
            functionsScanned++;
            if (function.isExternal() || function.isThunk()) continue;
            String name = function.getName();
            if (matches(name)) {
                addCandidate(candidates, function.getEntryPoint(),
                             "function-name:" + name);
            }
        }

        List<Candidate> ranked = new ArrayList<>(candidates.values());
        ranked.sort(Comparator.comparingInt((Candidate c) -> c.score).reversed()
                              .thenComparing(c -> c.function.getEntryPoint()));
        if (ranked.isEmpty()) {
            throw new java.io.IOException("no timer-related functions were identified");
        }

        DecompInterface decompiler = new DecompInterface();
        if (!decompiler.openProgram(currentProgram)) {
            throw new java.io.IOException("Decompiler initialization failed");
        }
        int attempted = 0;
        int succeeded = 0;
        try (PrintWriter functions = new PrintWriter(Files.newBufferedWriter(
                 new File(targetDir, "timer-candidates.tsv").toPath(), StandardCharsets.UTF_8));
             PrintWriter callers = new PrintWriter(Files.newBufferedWriter(
                 new File(targetDir, "timer-callers.tsv").toPath(), StandardCharsets.UTF_8));
             PrintWriter pseudocode = new PrintWriter(Files.newBufferedWriter(
                 new File(targetDir, "timer-decompilation.txt").toPath(), StandardCharsets.UTF_8))) {
            functions.println("entry\tscore\tname\tbody_min\tbody_max\tevidence");
            callers.println("function_entry\tfunction_name\tcaller_entry\tcaller_name");
            pseudocode.println("Ghidra static reconstruction; not original source.");
            pseudocode.println("target=" + clean(target));
            pseudocode.println("executable_sha256=" + currentProgram.getExecutableSHA256());
            for (Candidate candidate : ranked) {
                Function function = candidate.function;
                Address min = function.getBody().getMinAddress();
                Address max = function.getBody().getMaxAddress();
                StringBuilder evidence = new StringBuilder();
                for (String item : candidate.evidence) {
                    if (evidence.length() != 0) evidence.append(" | ");
                    evidence.append(clean(item));
                }
                functions.println(hex(function.getEntryPoint().getOffset()) + "\t" +
                                  candidate.score + "\t" + clean(function.getName()) + "\t" +
                                  (min == null ? "-" : hex(min.getOffset())) + "\t" +
                                  (max == null ? "-" : hex(max.getOffset())) + "\t" +
                                  evidence);
                if (attempted >= MAX_DECOMPILED) continue;
                monitor.checkCancelled();
                if (attempted < 8) {
                    for (Function caller : function.getCallingFunctions(monitor)) {
                        if (caller.isExternal() || caller.isThunk()) continue;
                        callers.println(hex(function.getEntryPoint().getOffset()) + "\t" +
                                        clean(function.getName()) + "\t" +
                                        hex(caller.getEntryPoint().getOffset()) + "\t" +
                                        clean(caller.getName()));
                    }
                }
                attempted++;
                DecompileResults result = decompiler.decompileFunction(function, 45, monitor);
                pseudocode.println("\n=== " + hex(function.getEntryPoint().getOffset()) +
                                   " " + clean(function.getName()) + " ===");
                if (!result.decompileCompleted()) {
                    pseudocode.println("DECOMPILE_FAILED: " + clean(result.getErrorMessage()));
                    continue;
                }
                String body = result.getDecompiledFunction().getC();
                if (body.length() > MAX_FUNCTION_CHARS) {
                    body = body.substring(0, MAX_FUNCTION_CHARS) + "\n/* truncated */";
                }
                pseudocode.println(body);
                succeeded++;
            }
        } finally {
            decompiler.dispose();
        }

        try (PrintWriter coverage = new PrintWriter(Files.newBufferedWriter(
                 new File(targetDir, "timer-coverage.txt").toPath(), StandardCharsets.UTF_8))) {
            coverage.println("target=" + clean(target));
            coverage.println("executable_sha256=" + currentProgram.getExecutableSHA256());
            coverage.println("strings_scanned=" + stringsScanned);
            coverage.println("references_scanned=" + referencesScanned);
            coverage.println("functions_scanned=" + functionsScanned);
            coverage.println("candidate_functions=" + ranked.size());
            coverage.println("functions_decompiled=" + attempted);
            coverage.println("functions_succeeded=" + succeeded);
            coverage.println("limitations=String-ranked static candidates do not prove the runtime CPU-burning path.");
        }
        if (succeeded == 0) {
            throw new java.io.IOException("no timer candidate decompilation succeeded");
        }
    }
}
