// Export recovered code from the supplied ARM64 PE; never execute firmware.
// @category Nabu
import java.io.File;
import java.io.PrintWriter;
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;

public class ExportHandoff extends GhidraScript {
    @Override public void run() throws Exception {
        File output = new File(getScriptArgs()[0]);
        output.mkdirs();
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        int count = 0, failed = 0;
        try (PrintWriter code = new PrintWriter(new File(output, "DarwinBoot.c"));
             PrintWriter assembly = new PrintWriter(new File(output, "DarwinBoot.asm"));
             PrintWriter metadata = new PrintWriter(new File(output, "analysis.txt"))) {
            metadata.println("input=" + currentProgram.getExecutablePath());
            metadata.println("sha256=" + currentProgram.getExecutableSHA256());
            metadata.println("language=" + currentProgram.getLanguageID());
            metadata.println("image_base=" + currentProgram.getImageBase());
            metadata.println("scope=Static recovered pseudocode; no device execution.");
            FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
            while (functions.hasNext() && !monitor.isCancelled()) {
                Function function = functions.next();
                code.println("\n/* " + function.getEntryPoint() + " " + function.getName() + " */");
                DecompileResults result = decompiler.decompileFunction(function, 60, monitor);
                if (result.decompileCompleted()) code.println(result.getDecompiledFunction().getC());
                else { code.println("/* Unresolved: " + result.getErrorMessage() + " */"); failed++; }
                count++;
            }
            InstructionIterator instructions = currentProgram.getListing().getInstructions(true);
            while (instructions.hasNext()) {
                Instruction instruction = instructions.next();
                assembly.println(instruction.getAddress() + " " + instruction);
            }
            metadata.println("functions=" + count);
            metadata.println("unresolved=" + failed);
            if (count == 0 || failed != 0) throw new RuntimeException("Incomplete function export");
        } finally { decompiler.dispose(); }
        println("Exported " + count + " recovered DarwinBoot functions");
    }
}
