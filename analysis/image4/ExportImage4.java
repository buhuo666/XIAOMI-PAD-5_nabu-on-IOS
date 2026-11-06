// Export every recovered function so the Image4 AES/ignition callers are searchable.
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

public class ExportImage4 extends GhidraScript {
    @Override public void run() throws Exception {
        File output = new File(getScriptArgs()[0]);
        String name = getScriptArgs().length > 1 ? getScriptArgs()[1] : "AppleImage4";
        output.mkdirs();
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        int count = 0;
        try (PrintWriter code = new PrintWriter(new File(output, name + ".c"));
             PrintWriter assembly = new PrintWriter(new File(output, name + ".asm"))) {
            FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
            while (functions.hasNext() && !monitor.isCancelled()) {
                Function function = functions.next();
                code.println("\n/* " + function.getEntryPoint() + " " + function.getName() + " */");
                DecompileResults result = decompiler.decompileFunction(function, 60, monitor);
                if (result.decompileCompleted()) code.println(result.getDecompiledFunction().getC());
                else code.println("/* Unresolved: " + result.getErrorMessage() + " */");
                count++;
            }
            InstructionIterator instructions = currentProgram.getListing().getInstructions(true);
            while (instructions.hasNext()) {
                Instruction instruction = instructions.next();
                assembly.println(instruction.getAddress() + " " + instruction);
            }
        } finally { decompiler.dispose(); }
        println("Exported " + count + " recovered " + name + " functions");
    }
}
