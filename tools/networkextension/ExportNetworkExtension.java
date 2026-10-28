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
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class ExportNetworkExtension extends GhidraScript {
    private static final String[] TERMS = {
        "NetworkExtension", "SharedWebCredentials", "trackingDomain",
        "trackingDomainInfo", "SWC", "SCPreferences", "SCDynamicStore",
        "SCPreferencesLock", "SCPreferencesCommitChanges", "SCPreferencesApplyChanges",
        "getCurrentIndex", "loadConfigurations", "saveConfigurationToDisk",
        "NEHelper", "nehelper", "nesessionmanager", "profiled",
        "managedconfiguration", "cloudconfiguration", "checkIn",
        "com.apple.swcd", "com.apple.nehelper", "com.apple.networkextension",
        "com.apple.SystemConfiguration", "com.apple.notifyd", "com.apple.configd",
        "MachServices", "xpc_connection", "sendMessageWithReply",
        "xpc_connection_send_message_with_reply_sync", "preferences",
        "default_factors", "network service", "NEConfigurationManager",
        "NEProfileIngestion", "CaptiveNetwork", "NEHelperSession"
    };
    private static final int MAX_STRINGS = 2000;
    private static final int MAX_MATCHED_STRINGS = 20000;
    private static final int MAX_REFS = 20000;
    private static final int MAX_FUNCTIONS = 40;
    private static final int MAX_CALLER_FUNCTIONS = 24;
    private static final int MAX_FUNCTION_CHARS = 9000;
    private static final int MAX_TABLE_ROWS = 400000;

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
        final String value;

        StringHit(Address address, String value) {
            this.address = address;
            this.value = value;
        }
    }

    private boolean matches(String value) {
        String lower = value.toLowerCase();
        for (String term : TERMS) {
            if (lower.contains(term.toLowerCase())) return true;
        }
        return false;
    }

    private int weight(String value) {
        String lower = value.toLowerCase();
        if (lower.contains("trackingdomain") || lower.contains("sharedwebcredentials") ||
            lower.contains("getcurrentindex") || lower.contains("loadconfigurations") ||
            lower.contains("saveconfigurationtodisk") || lower.contains("checkin")) return 20;
        if (lower.contains("networkextension") || lower.contains("nehelper") ||
            lower.contains("swcd") || lower.contains("cloudconfiguration") ||
            lower.contains("scpreferences")) return 12;
        return 3;
    }

    private String clean(String value) {
        return value.replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n");
    }

    private String safeString(String value) {
        return value.replaceAll("(?i)https?://[^\\s\\\"']+", "[URL]");
    }

    private static String hex(long value) {
        return String.format("0x%x", value);
    }

    private String functionRange(Function function) {
        Address bodyMin = function.getBody().getMinAddress();
        Address bodyMax = function.getBody().getMaxAddress();
        if (bodyMin == null || bodyMax == null) return "-1\t-1";
        return hex(bodyMin.getOffset()) + "\t" + hex(bodyMax.getOffset());
    }

    private void addFunction(Map<Address, Candidate> candidates, Address from, String reason) {
        Function function = getFunctionContaining(from);
        if (function == null || function.isExternal() || function.isThunk()) return;
        Address entry = function.getEntryPoint();
        Candidate candidate = candidates.get(entry);
        if (candidate == null) {
            candidate = new Candidate(function);
            candidates.put(entry, candidate);
        }
        if (candidate.evidence.add(reason)) candidate.score += weight(reason);
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 2) {
            throw new IllegalArgumentException(
                "usage: ExportNetworkExtension <target-id> <report-root>");
        }
        String target = args[0];
        File reportRoot = new File(args[1]);
        File targetDir = new File(reportRoot, target);
        if (!targetDir.isDirectory() && !targetDir.mkdirs()) {
            throw new java.io.IOException("cannot create target report directory");
        }

        Map<Address, Candidate> candidates = new HashMap<>();
        List<StringHit> hits = new ArrayList<>();
        int stringsScanned = 0;
        boolean scanCapped = false;
        DataIterator data = currentProgram.getListing().getDefinedData(true);
        while (data.hasNext() && stringsScanned < MAX_STRINGS * 40) {
            monitor.checkCancelled();
            Data item = data.next();
            Object raw = item.getValue();
            if (!(raw instanceof String)) continue;
            stringsScanned++;
            String value = (String) raw;
            if (!matches(value)) continue;
            if (hits.size() >= MAX_MATCHED_STRINGS) {
                scanCapped = true;
                break;
            }
            hits.add(new StringHit(item.getAddress(), value));
        }
        hits.sort(Comparator.comparingInt((StringHit hit) -> weight(hit.value)).reversed()
                            .thenComparing(hit -> hit.address));
        int selected = Math.min(MAX_STRINGS, hits.size());
        int references = 0;
        boolean referenceCapped = false;
        try (PrintWriter strings = new PrintWriter(Files.newBufferedWriter(
                 new File(targetDir, "strings.tsv").toPath(), StandardCharsets.UTF_8));
             PrintWriter refs = new PrintWriter(Files.newBufferedWriter(
                 new File(targetDir, "string-xrefs.tsv").toPath(), StandardCharsets.UTF_8))) {
            strings.println("address\tstring");
            refs.println("string_address\tstring\treference_type\treference_address\tfunction_address\tfunction_name");
            for (int i = 0; i < selected && references < MAX_REFS; i++) {
                monitor.checkCancelled();
                StringHit hit = hits.get(i);
                String value = safeString(hit.value);
                strings.println(hex(hit.address.getOffset()) + "\t" + clean(value));
                for (Reference reference : getReferencesTo(hit.address)) {
                    if (references >= MAX_REFS) {
                        referenceCapped = true;
                        break;
                    }
                    references++;
                    Address from = reference.getFromAddress();
                    Function function = getFunctionContaining(from);
                    refs.println(hex(hit.address.getOffset()) + "\t" + clean(value) + "\t" +
                                 clean(reference.getReferenceType().getName()) + "\t" +
                                 hex(from.getOffset()) + "\t" +
                                 (function == null ? "" : hex(function.getEntryPoint().getOffset())) +
                                 "\t" + (function == null ? "" : clean(function.getName())));
                    addFunction(candidates, from, value);
                }
            }
        }

        Address low = currentProgram.getMemory().getMinAddress();
        Address high = currentProgram.getMemory().getMaxAddress();
        Address base = currentProgram.getImageBase();
        if (base == null || base.getOffset() == 0) base = low;

        FunctionIterator iterator = currentProgram.getFunctionManager().getFunctions(true);
        int functionsScanned = 0;
        Set<Address> bodySeen = new LinkedHashSet<>();
        try (PrintWriter table = new PrintWriter(Files.newBufferedWriter(
                 new File(targetDir, "functions.tsv").toPath(), StandardCharsets.UTF_8))) {
            table.println("entry\tname\tsize\tbody_min\tbody_max\tthunk\texternal");
            while (iterator.hasNext()) {
                monitor.checkCancelled();
                Function function = iterator.next();
                if (++functionsScanned > MAX_TABLE_ROWS) {
                    throw new java.io.IOException("function bound exceeded");
                }
                if (!bodySeen.add(function.getEntryPoint())) continue;
                if (function.isExternal() || function.isThunk()) continue;
                Address bodyMin = function.getBody().getMinAddress();
                Address bodyMax = function.getBody().getMaxAddress();
                long size = bodyMin == null || bodyMax == null
                    ? 0 : bodyMax.getOffset() - bodyMin.getOffset() + 1;
                table.println(hex(function.getEntryPoint().getOffset()) + "\t" +
                              clean(function.getName()) + "\t" + size + "\t" +
                              functionRange(function) + "\t" + function.isThunk() + "\t" +
                              function.isExternal());
                if (matches(function.getName())) {
                    addFunction(candidates, function.getEntryPoint(),
                                "function-name:" + function.getName());
                }
            }
        }

        List<Candidate> ranked = new ArrayList<>(candidates.values());
        ranked.sort(Comparator.comparingInt((Candidate candidate) -> candidate.score).reversed()
                              .thenComparing(candidate -> candidate.function.getEntryPoint()));

        int attempted = 0;
        int succeeded = 0;
        DecompInterface decompiler = new DecompInterface();
        try {
            if (!decompiler.openProgram(currentProgram)) {
                throw new java.io.IOException("Decompiler initialization failed");
            }
            try (PrintWriter functions = new PrintWriter(Files.newBufferedWriter(
                     new File(targetDir, "candidate-functions.tsv").toPath(), StandardCharsets.UTF_8));
                 PrintWriter pseudocode = new PrintWriter(Files.newBufferedWriter(
                     new File(targetDir, "candidate-decompilation.txt").toPath(), StandardCharsets.UTF_8));
                 PrintWriter callers = new PrintWriter(Files.newBufferedWriter(
                     new File(targetDir, "candidate-callers.tsv").toPath(), StandardCharsets.UTF_8))) {
                functions.println("address\tscore\tname\tevidence");
                pseudocode.println("Ghidra static reconstruction; not original source.");
                pseudocode.println("target=" + target + " sha256=" +
                                   currentProgram.getExecutableSHA256());
                callers.println("function_entry\tfunction_name\tcaller_entry\tcaller_name");

                List<Function> queue = new ArrayList<>();
                Set<Address> queued = new LinkedHashSet<>();
                for (Candidate candidate : ranked) {
                    StringBuilder evidence = new StringBuilder();
                    for (String reason : candidate.evidence) {
                        if (evidence.length() > 0) evidence.append(" | ");
                        evidence.append(clean(reason));
                    }
                    functions.println(hex(candidate.function.getEntryPoint().getOffset()) + "\t" +
                                      candidate.score + "\t" +
                                      clean(candidate.function.getName()) + "\t" + evidence);
                    if (candidate.score < 3 || queue.size() >= MAX_FUNCTIONS) continue;
                    if (queued.add(candidate.function.getEntryPoint())) queue.add(candidate.function);
                }

                int callerCount = Math.min(MAX_CALLER_FUNCTIONS, queue.size());
                for (int i = 0; i < queue.size() && attempted < MAX_FUNCTIONS; i++) {
                    Function function = queue.get(i);
                    monitor.checkCancelled();
                    attempted++;
                    boolean selectedCandidate = i < callerCount;
                    if (selectedCandidate) {
                        for (Function caller : function.getCallingFunctions(monitor)) {
                            if (caller.isExternal() || caller.isThunk()) continue;
                            callers.println(hex(function.getEntryPoint().getOffset()) + "\t" +
                                            clean(function.getName()) + "\t" +
                                            hex(caller.getEntryPoint().getOffset()) + "\t" +
                                            clean(caller.getName()));
                        }
                    }
                    DecompileResults result = decompiler.decompileFunction(function, 60, monitor);
                    pseudocode.println("\n=== " + (selectedCandidate ? "priority " : "") +
                                       hex(function.getEntryPoint().getOffset()) + " " +
                                       clean(function.getName()) + " ===");
                    if (!result.decompileCompleted()) {
                        pseudocode.println("DECOMPILE_FAILED: " +
                                           clean(result.getErrorMessage()));
                        continue;
                    }
                    String body = safeString(result.getDecompiledFunction().getC());
                    if (body.length() > MAX_FUNCTION_CHARS) {
                        body = body.substring(0, MAX_FUNCTION_CHARS) + "\n/* truncated */";
                    }
                    pseudocode.println(body);
                    succeeded++;
                }
            }
        } finally {
            decompiler.dispose();
        }

        String executableSha = currentProgram.getExecutableSHA256();
        String executableFormat = currentProgram.getExecutableFormat();
        try (PrintWriter image = new PrintWriter(Files.newBufferedWriter(
                 new File(targetDir, "image.txt").toPath(), StandardCharsets.UTF_8))) {
            image.println("target=" + target);
            image.println("name=" + clean(currentProgram.getName()));
            image.println("executable_format=" + clean(executableFormat));
            image.println("language=" + currentProgram.getLanguageID());
            image.println("image_base=" + hex(base.getOffset()));
            image.println("min_address=" + hex(low.getOffset()));
            image.println("max_address=" + hex(high.getOffset()));
            image.println("image_bytes=" + (high.getOffset() - low.getOffset() + 1));
            image.println("executable_sha256=" + executableSha);
            image.println("functions_in_table=" + functionsScanned);
        }

        try (PrintWriter coverage = new PrintWriter(Files.newBufferedWriter(
                 new File(targetDir, "coverage.txt").toPath(), StandardCharsets.UTF_8))) {
            coverage.println("target=" + target);
            coverage.println("sha256=" + executableSha);
            coverage.println("format=" + executableFormat);
            coverage.println("language=" + currentProgram.getLanguageID());
            coverage.println("image_base=" + hex(base.getOffset()));
            coverage.println("defined_strings_scanned=" + stringsScanned);
            coverage.println("string_scan_capped=" + scanCapped);
            coverage.println("matched_strings_found=" + hits.size());
            coverage.println("matched_strings_selected=" + selected);
            coverage.println("direct_reference_edges=" + references);
            coverage.println("reference_edge_capped=" + referenceCapped);
            coverage.println("functions_scanned=" + functionsScanned);
            coverage.println("candidate_functions=" + ranked.size());
            coverage.println("functions_decompiled=" + attempted);
            coverage.println("functions_succeeded=" + succeeded);
            coverage.println("limitations=Static strings and direct references do not prove runtime " +
                             "XPC endpoints, server replies, deadlock, or forward progress.");
        }
        if (stringsScanned == 0 || functionsScanned == 0) {
            throw new java.io.IOException("incomplete Mach-O analysis");
        }
    }
}
