// Focused export around native Bluetooth transport and controller initialization.
// @category Nabu
import java.io.File;
import java.io.PrintWriter;
import java.util.LinkedHashSet;
import java.util.Set;
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.symbol.Reference;

public class ExportBluetoothUserland extends GhidraScript {
    private void addAt(Set<Function> set, Address address) {
        Function function = getFunctionContaining(address);
        if (function != null) set.add(function);
    }
    @Override public void run() throws Exception {
        File output = new File(getScriptArgs()[0]);
        String name = getScriptArgs()[1];
        output.mkdirs();
        Set<Function> seeds = new LinkedHashSet<>();
        String[] terms = {"/dev/uart.bluetooth", "/dev/cu.bluetooth", "/dev/btwake", "/dev/btreset", "/dev/btpoweroff",
            "com.apple.uart", "BT_HCI_TRANSPORT", "BT_DEVICE_ADDRESS"};
        try (PrintWriter selected = new PrintWriter(new File(output, name + "-seeds.log"))) {
            DataIterator data = currentProgram.getListing().getDefinedData(true);
            while (data.hasNext() && !monitor.isCancelled()) {
                Data item = data.next();
                Object value = item.getValue();
                if (!(value instanceof String)) continue;
                String text = (String)value;
                boolean match = false;
                for (String term : terms) if (text.contains(term)) match = true;
                if (!match) continue;
                selected.println(item.getAddress() + " " + text);
                for (Reference reference : getReferencesTo(item.getAddress())) addAt(seeds, reference.getFromAddress());
            }
            if (name.equals("BlueTool")) {
                long[] entries = {0x10003eec8L,0x10003f358L,0x1000400ecL,0x10003f77cL,0x10003fa34L,0x10003fd34L,
                    0x1000161a0L,0x100016474L,0x10001c06cL,0x100040958L};
                for (long entry : entries) addAt(seeds, toAddr(entry));
            } else {
                long[] entries = {0x100155f8cL,0x10015627cL,0x10006669cL,0x100271e60L,
                    0x100272b10L,0x100272b88L,0x100272c00L,0x100068004L,0x1000670d0L,
                    0x1000673c8L,0x10029a5ecL,0x10029a5acL,0x1000689f0L,0x100027194L};
                for (long entry : entries) addAt(seeds, toAddr(entry));
            }
            Set<Function> functions = new LinkedHashSet<>(seeds);
            for (Function seed : seeds) {
                functions.addAll(seed.getCallingFunctions(monitor));
                functions.addAll(seed.getCalledFunctions(monitor));
            }
            DecompInterface decompiler = new DecompInterface();
            if (!decompiler.openProgram(currentProgram)) throw new Exception(decompiler.getLastMessage());
            int recovered = 0;
            try (PrintWriter code = new PrintWriter(new File(output, name + ".c"));
                 PrintWriter assembly = new PrintWriter(new File(output, name + ".asm"))) {
                for (Function function : functions) {
                    if (monitor.isCancelled()) break;
                    selected.println("FUNCTION " + function.getEntryPoint() + " " + function.getName());
                    code.println("\n/* " + function.getEntryPoint() + " " + function.getName() + " */");
                    DecompileResults result = decompiler.decompileFunction(function, 20, monitor);
                    if (result.decompileCompleted()) { code.println(result.getDecompiledFunction().getC()); recovered++; }
                    else code.println("/* Unresolved: " + result.getErrorMessage() + " */");
                    InstructionIterator instructions = currentProgram.getListing().getInstructions(function.getBody(), true);
                    while (instructions.hasNext()) {
                        Instruction instruction = instructions.next();
                        assembly.println(instruction.getAddress() + " " + instruction);
                    }
                }
            } finally { decompiler.dispose(); }
            try (PrintWriter report = new PrintWriter(new File(output, name + "-decompilation.json"))) {
                report.println("{\"selected\":" + functions.size() + ",\"decompiled\":" + recovered + "}");
            }
            selected.println("Seed functions=" + seeds.size() + " selected functions=" + functions.size());
        }
    }
}
