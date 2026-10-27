// Static ARM64 Mach-O investigation only. The imported program is never run.
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
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class ExportSetupFlow extends GhidraScript {
    private static final String[] TERMS = {
        "activation", "wifi", "wi-fi", "wireless", "network", "internet",
        "setupassistant", "purplebuddy", "locale", "language", "region",
        "timezone", "time zone", "country"
    };
    private static final int MAX_STRINGS = 1200;
    private static final int MAX_REFS = 12000;
    private static final int MAX_MATCHED_STRINGS = 20000;
    private static final int MAX_FUNCTIONS = 8;
    private static final int MAX_FUNCTION_CHARS = 2500;

    private static final class Node {
        final Address address;
        final int depth;

        Node(Address address, int depth) {
            this.address = address;
            this.depth = depth;
        }
    }

    private static final class Candidate {
        final Function function;
        final Set<String> evidence = new LinkedHashSet<>();
        int score;

        Candidate(Function function) {
            this.function = function;
        }
    }

    private static final class StringHit {
        final Address address;
        final String text;

        StringHit(Address address, String text) {
            this.address = address;
            this.text = text;
        }
    }

    private boolean matches(String text) {
        String lower = text.toLowerCase();
        for (String term : TERMS) {
            if (lower.contains(term)) {
                return true;
            }
        }
        return false;
    }

    private int weight(String text) {
        String lower = text.toLowerCase();
        if (lower.contains("activation")) return 8;
        if (lower.contains("wifi") || lower.contains("wi-fi") || lower.contains("wireless")) return 7;
        if (lower.contains("network") || lower.contains("internet")) return 5;
        if (lower.contains("locale") || lower.contains("language") ||
            lower.contains("region") || lower.contains("timezone") ||
            lower.contains("time zone") || lower.contains("country")) return 3;
        return 2;
    }

    private String clean(String value) {
        return value.replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n");
    }

    private String redactUrls(String value) {
        return value.replaceAll("(?i)https?://[^\\s\\\"']+", "[URL]");
    }

    private void addFunction(Map<Address, Candidate> candidates, Address from,
                             String evidence) {
        Function function = getFunctionContaining(from);
        if (function == null || function.isExternal() || function.isThunk()) {
            return;
        }
        Address entry = function.getEntryPoint();
        Candidate candidate = candidates.get(entry);
        if (candidate == null) {
            candidate = new Candidate(function);
            candidates.put(entry, candidate);
        }
        if (candidate.evidence.add(evidence)) {
            candidate.score += weight(evidence);
        }
    }

    private int traceReferences(Address start, String evidence,
                                Map<Address, Candidate> candidates,
                                PrintWriter referenceOutput, int edgeBudget) {
        ArrayDeque<Node> pending = new ArrayDeque<>();
        Set<Address> visited = new HashSet<>();
        pending.add(new Node(start, 0));
        int examined = 0;
        while (!pending.isEmpty() && examined < edgeBudget) {
            Node node = pending.removeFirst();
            if (!visited.add(node.address)) {
                continue;
            }
            Reference[] refs = getReferencesTo(node.address);
            for (Reference ref : refs) {
                if (examined >= edgeBudget) {
                    break;
                }
                examined++;
                Address from = ref.getFromAddress();
                addFunction(candidates, from, evidence);
                Function function = getFunctionContaining(from);
                referenceOutput.println(start + "\t" + clean(evidence) + "\t" +
                                        clean(ref.getReferenceType().getName()) + "\t" +
                                        from + "\t" +
                                        (function == null ? "" : function.getEntryPoint()) + "\t" +
                                        (function == null ? "" : clean(function.getName())));
                if (node.depth >= 3) {
                    continue;
                }
                Data source = currentProgram.getListing().getDataContaining(from);
                if (source != null && !source.getMinAddress().equals(node.address)) {
                    pending.addLast(new Node(source.getMinAddress(), node.depth + 1));
                }
            }
        }
        return examined;
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 2) {
            throw new IllegalArgumentException("usage: ExportSetupFlow <target-id> <report-root>");
        }
        String target = args[0];
        File reportRoot = new File(args[1]);
        File targetDir = new File(reportRoot, target);
        if (!targetDir.isDirectory() && !targetDir.mkdirs()) {
            throw new java.io.IOException("cannot create report directory");
        }

        Map<Address, Candidate> candidates = new HashMap<>();
        List<StringHit> hits = new ArrayList<>();
        int definedStrings = 0;
        int referencesExamined = 0;
        boolean stringScanCapped = false;

        try (PrintWriter strings = new PrintWriter(
                 Files.newBufferedWriter(new File(targetDir, "strings.tsv").toPath(),
                                         StandardCharsets.UTF_8));
             PrintWriter refs = new PrintWriter(
                 Files.newBufferedWriter(new File(targetDir, "string-references.tsv").toPath(),
                                         StandardCharsets.UTF_8))) {
            strings.println("address\tstring");
            refs.println("string_address\tstring\treference_type\treference_address\tfunction_address\tfunction_name");
            DataIterator data = currentProgram.getListing().getDefinedData(true);
            while (data.hasNext()) {
                monitor.checkCancelled();
                Data item = data.next();
                Object value = item.getValue();
                if (!(value instanceof String)) {
                    continue;
                }
                definedStrings++;
                String text = (String) value;
                if (!matches(text)) {
                    continue;
                }
                if (hits.size() >= MAX_MATCHED_STRINGS) {
                    stringScanCapped = true;
                    break;
                }
                hits.add(new StringHit(item.getAddress(), text));
            }

            hits.sort(Comparator.comparingInt((StringHit hit) -> weight(hit.text)).reversed()
                                .thenComparing(hit -> hit.address));
            int selectedStrings = Math.min(MAX_STRINGS, hits.size());
            for (int i = 0; i < selectedStrings && referencesExamined < MAX_REFS; i++) {
                monitor.checkCancelled();
                StringHit hit = hits.get(i);
                String safeText = clean(redactUrls(hit.text));
                strings.println(hit.address + "\t" + safeText);
                referencesExamined += traceReferences(
                    hit.address, safeText, candidates, refs,
                    MAX_REFS - referencesExamined);
            }

            FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
            while (functions.hasNext()) {
                monitor.checkCancelled();
                Function function = functions.next();
                String name = function.getName();
                if (!function.isExternal() && !function.isThunk() && matches(name)) {
                    Candidate candidate = candidates.get(function.getEntryPoint());
                    if (candidate == null) {
                        candidate = new Candidate(function);
                        candidates.put(function.getEntryPoint(), candidate);
                    }
                    candidate.evidence.add("function-name:" + clean(name));
                    candidate.score += 2;
                }
            }

            List<Candidate> ranked = new ArrayList<>(candidates.values());
            ranked.sort(Comparator.comparingInt((Candidate c) -> c.score).reversed()
                                  .thenComparing(c -> c.function.getEntryPoint()));
            try (PrintWriter index = new PrintWriter(
                     Files.newBufferedWriter(new File(targetDir, "candidate-functions.tsv").toPath(),
                                             StandardCharsets.UTF_8))) {
                index.println("address\tscore\tname\tevidence");
                for (Candidate candidate : ranked) {
                    StringBuilder evidence = new StringBuilder();
                    for (String item : candidate.evidence) {
                        if (evidence.length() > 0) evidence.append(" | ");
                        evidence.append(clean(item));
                    }
                    index.println(candidate.function.getEntryPoint() + "\t" +
                                  candidate.score + "\t" +
                                  clean(candidate.function.getName()) + "\t" + evidence);
                }
            }

            DecompInterface decompiler = new DecompInterface();
            if (!decompiler.openProgram(currentProgram)) {
                throw new java.io.IOException("Decompiler initialization failed");
            }
            int attempted = 0;
            int succeeded = 0;
            try (PrintWriter output = new PrintWriter(
                     Files.newBufferedWriter(new File(targetDir, "candidate-decompilation.txt").toPath(),
                                             StandardCharsets.UTF_8))) {
                output.println("Static Ghidra reconstruction; not original source.");
                output.println("Target: " + target + " SHA256: " +
                               currentProgram.getExecutableSHA256());
                for (Candidate candidate : ranked) {
                    if (attempted >= MAX_FUNCTIONS) break;
                    if (candidate.score < 3) continue;
                    monitor.checkCancelled();
                    attempted++;
                    DecompileResults result = decompiler.decompileFunction(
                        candidate.function, 30, monitor);
                    output.println("\n=== " + candidate.function.getEntryPoint() + " " +
                                   candidate.function.getName() + " ===");
                    if (!result.decompileCompleted()) {
                        output.println("DECOMPILE_FAILED: " + clean(result.getErrorMessage()));
                        continue;
                    }
                    String pseudocode = result.getDecompiledFunction().getC();
                    if (pseudocode.length() > MAX_FUNCTION_CHARS) {
                        pseudocode = pseudocode.substring(0, MAX_FUNCTION_CHARS) +
                                     "\n/* truncated for report size */";
                    }
                    output.println(redactUrls(pseudocode));
                    succeeded++;
                }
            } finally {
                decompiler.dispose();
            }

            try (PrintWriter coverage = new PrintWriter(
                     Files.newBufferedWriter(new File(targetDir, "coverage.txt").toPath(),
                                             StandardCharsets.UTF_8))) {
                coverage.println("target=" + target);
                coverage.println("sha256=" + currentProgram.getExecutableSHA256());
                coverage.println("language=" + currentProgram.getLanguageID());
                coverage.println("defined_strings_scanned=" + definedStrings);
                coverage.println("string_scan_capped=" + stringScanCapped);
                coverage.println("matched_strings_retained=" + hits.size());
                coverage.println("matched_strings_selected=" + selectedStrings);
                coverage.println("reference_edges_examined=" + referencesExamined);
                coverage.println("candidate_functions=" + ranked.size());
                coverage.println("functions_decompiled=" + attempted);
                coverage.println("functions_succeeded=" + succeeded);
                coverage.println("search_terms=" + String.join(",", TERMS));
                coverage.println("Limitations: string references are followed through at most three data-reference hops; indirect calls and runtime behavior are not established.");
            }
        }
    }
}
