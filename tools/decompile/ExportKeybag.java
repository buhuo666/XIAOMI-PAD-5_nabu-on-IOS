// Static analysis only; never executes the imported target.
// @category Nabu
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
public class ExportKeybag extends GhidraScript {
 public void run() throws Exception {
  File out=new File(getScriptArgs()[0]); out.mkdirs();
  DecompInterface d=new DecompInterface();
  if(!d.openProgram(currentProgram)) throw new IOException("Decompiler initialization failed");
  int count=0, failed=0;
  try(PrintWriter report=new PrintWriter(new File(out,"pseudocode.c")); PrintWriter refs=new PrintWriter(new File(out,"string-xrefs.tsv"))) {
   report.println("/* Ghidra static reconstruction; not original source. Indirect calls and inferred types may be incomplete. */");
   DataIterator data=currentProgram.getListing().getDefinedData(true);
   while(data.hasNext()) {
    Data s=data.next(); Object v=s.getValue(); if(!(v instanceof String)) continue;
    String text=(String)v; String lower=text.toLowerCase();
    if(!(lower.contains("keybag")||lower.contains("effaceable")||lower.contains("shared_datavolume")||lower.contains("mkb_init"))) continue;
    refs.println("STRING\t"+s.getAddress()+"\t"+text.replace("\n","\\n"));
    for(Reference r:getReferencesTo(s.getAddress())) {
     Function f=getFunctionContaining(r.getFromAddress());
     refs.println("REF\t"+r.getFromAddress()+"\t"+(f==null?"unknown":f.getEntryPoint()+" "+f.getName()));
    }
   }
   FunctionIterator it=currentProgram.getFunctionManager().getFunctions(true);
   while(it.hasNext()) {
    monitor.checkCancelled(); Function f=it.next(); if(f.isExternal()||f.isThunk()) continue;
    if(++count>2000) throw new IOException("Function coverage bound exceeded");
    report.println("\n/* FUNCTION "+f.getEntryPoint()+" "+f.getName()+" */");
    DecompileResults r=d.decompileFunction(f,45,monitor);
    if(r.decompileCompleted()) report.println(r.getDecompiledFunction().getC());
    else {failed++; report.println("/* FAILED: "+r.getErrorMessage()+" */");}
   }
  } finally {d.dispose();}
  try(PrintWriter meta=new PrintWriter(new File(out,"coverage.txt"))) {
   meta.println("Input SHA256: "+currentProgram.getExecutableSHA256());
   meta.println("Language: "+currentProgram.getLanguageID());
   meta.println("Functions attempted: "+count+"; failed: "+failed);
   meta.println("Defined-string direct xrefs only; pointer/CFString indirection may require manual tracing. Static results do not establish runtime success.");
  }
  if(count==0) throw new IOException("No functions recovered");
 }
}
