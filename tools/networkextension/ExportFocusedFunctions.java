// Static ARM64 Mach-O analysis only. Imported Apple binaries are never run.
// @category Nabu
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.listing.Function;

import java.io.File;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.LinkedHashSet;
import java.util.Set;

public class ExportFocusedFunctions extends GhidraScript {
    private static String clean(String value) {
        return value.replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n");
    }

    private static String hex(long value) {
        return String.format("0x%x", value);
    }

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 3) {
            throw new IllegalArgumentException(
                "usage: ExportFocusedFunctions <target-id> <report-root> <address-csv>");
        }

        String target = args[0];
        File reportRoot = new File(args[1]);
        File targetDir = new File(reportRoot, target);
        if (!targetDir.isDirectory() && !targetDir.mkdirs()) {
            throw new java.io.IOException("cannot create focused report directory");
        }

        DecompInterface decompiler = new DecompInterface();
        if (!decompiler.openProgram(currentProgram)) {
            throw new java.io.IOException("Decompiler initialization failed");
        }

        int requested = 0;
        int resolved = 0;
        int succeeded = 0;
        try (PrintWriter functions = new PrintWriter(Files.newBufferedWriter(
                 new File(targetDir, "focused-functions.tsv").toPath(), StandardCharsets.UTF_8));
             PrintWriter callers = new PrintWriter(Files.newBufferedWriter(
                 new File(targetDir, "focused-callers.tsv").toPath(), StandardCharsets.UTF_8));
             PrintWriter assembly = new PrintWriter(Files.newBufferedWriter(
                 new File(targetDir, "focused-assembly.txt").toPath(), StandardCharsets.UTF_8));
             PrintWriter pseudocode = new PrintWriter(Files.newBufferedWriter(
                 new File(targetDir, "focused-decompilation.txt").toPath(), StandardCharsets.UTF_8))) {
            functions.println("requested_address\tresolved_entry\tname\tbody_min\tbody_max\tstatus");
            callers.println("requested_address\tfunction_entry\tfunction_name\tcaller_entry\tcaller_name");
            pseudocode.println("Ghidra static reconstruction; not original source.");
            pseudocode.println("target=" + clean(target));
            pseudocode.println("executable_sha256=" + currentProgram.getExecutableSHA256());
            assembly.println("Ghidra instruction listing; static image addresses.");
            assembly.println("target=" + clean(target));
            assembly.println("executable_sha256=" + currentProgram.getExecutableSHA256());

            Set<Long> unique = new LinkedHashSet<>();
            for (String token : args[2].split(",")) {
                String value = token.trim();
                if (value.isEmpty()) continue;
                long rawAddress = Long.decode(value);
                if (!unique.add(rawAddress)) continue;
                requested++;

                Address address = toAddr(rawAddress);
                Function function = getFunctionAt(address);
                if (function == null) function = getFunctionContaining(address);
                if (function == null || function.isExternal() || function.isThunk()) {
                    functions.println(hex(rawAddress) + "\t-\t-\t-\t-\tunresolved");
                    pseudocode.println("\n=== " + hex(rawAddress) + " UNRESOLVED ===");
                    continue;
                }

                resolved++;
                Address min = function.getBody().getMinAddress();
                Address max = function.getBody().getMaxAddress();
                functions.println(hex(rawAddress) + "\t" +
                                  hex(function.getEntryPoint().getOffset()) + "\t" +
                                  clean(function.getName()) + "\t" +
                                  (min == null ? "-" : hex(min.getOffset())) + "\t" +
                                  (max == null ? "-" : hex(max.getOffset())) + "\tresolved");

                for (Function caller : function.getCallingFunctions(monitor)) {
                    if (caller.isExternal() || caller.isThunk()) continue;
                    callers.println(hex(rawAddress) + "\t" +
                                    hex(function.getEntryPoint().getOffset()) + "\t" +
                                    clean(function.getName()) + "\t" +
                                    hex(caller.getEntryPoint().getOffset()) + "\t" +
                                    clean(caller.getName()));
                }

                assembly.println("\n=== " + hex(rawAddress) + " -> " +
                                 hex(function.getEntryPoint().getOffset()) + " " +
                                 clean(function.getName()) + " ===");
                InstructionIterator instructions = currentProgram.getListing()
                    .getInstructions(function.getBody(), true);
                int instructionCount = 0;
                while (instructions.hasNext() && instructionCount < 512) {
                    monitor.checkCancelled();
                    Instruction instruction = instructions.next();
                    assembly.println(hex(instruction.getAddress().getOffset()) + "\t" +
                                     clean(instruction.toString()));
                    instructionCount++;
                }
                if (instructions.hasNext()) assembly.println("TRUNCATED_AFTER_512_INSTRUCTIONS");

                DecompileResults result = decompiler.decompileFunction(function, 45, monitor);
                pseudocode.println("\n=== " + hex(rawAddress) + " -> " +
                                   hex(function.getEntryPoint().getOffset()) + " " +
                                   clean(function.getName()) + " ===");
                if (!result.decompileCompleted()) {
                    pseudocode.println("DECOMPILE_FAILED: " + clean(result.getErrorMessage()));
                    continue;
                }
                String body = result.getDecompiledFunction().getC();
                if (body.length() > 24000) {
                    body = body.substring(0, 24000) + "\n/* truncated */";
                }
                pseudocode.println(body);
                succeeded++;
            }
        } finally {
            decompiler.dispose();
        }

        try (PrintWriter coverage = new PrintWriter(Files.newBufferedWriter(
                 new File(targetDir, "focused-coverage.txt").toPath(), StandardCharsets.UTF_8))) {
            coverage.println("target=" + clean(target));
            coverage.println("executable_sha256=" + currentProgram.getExecutableSHA256());
            coverage.println("requested_functions=" + requested);
            coverage.println("resolved_functions=" + resolved);
            coverage.println("functions_decompiled=" + succeeded);
        }
        if (requested == 0 || resolved == 0) {
            throw new java.io.IOException("no requested function address was resolved");
        }
    }
}
