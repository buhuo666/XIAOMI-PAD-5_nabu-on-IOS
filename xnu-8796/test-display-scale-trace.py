#!/usr/bin/env python3
"""Run the patched scale trace in a host model; does not build XNU."""
import argparse
from pathlib import Path
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--xnu-source", required=True, type=Path)
p.add_argument("--cc", default="clang++")
a = p.parse_args()
source = (a.xnu_source / "iokit/Kernel/IOUserClient.cpp").read_text()
start = source.index("static void\nnabu_scale_property_trace(")
end = source.index("\n#endif", start)
helper = source[start:end]
function_start = source.index("static OSObject *\nIOCopyPropertyCompatible(")
function_end = source.index("\n/* Routine io_registry_entry_get_property */", function_start)
function = source[function_start:function_end]
assert function.count("nabu_scale_property_trace(") == 2
assert '"direct"' in function and '"compat-or-missing"' in function
assert not any(x in helper for x in ("setProperty(", "removeProperty(", "->release(", "->retain("))
prelude = r'''
#include <cassert>
#include <cstdint>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
using SInt32 = int32_t;
static int config;
static int parse_calls;
static std::vector<std::string> records;
bool PE_parse_boot_argn(const char *key, void *dst, size_t length) {
 assert(std::string(key)=="nabuscalelog" && length==sizeof(int));
 ++parse_calls; memcpy(dst,&config,length); return config!=0;
}
int32_t OSIncrementAtomic(volatile int32_t *p) { int32_t old=*p; *p=old+1; return old; }
void proc_selfname(char *dst, int size) { snprintf(dst,size,"SpringBoard"); }
void IOLog(const char *fmt,...) {
 char text[512]; va_list args; va_start(args,fmt);
 vsnprintf(text,sizeof(text),fmt,args); va_end(args); records.emplace_back(text);
}
void bcopy(const void *from,void *to,size_t n) { memcpy(to,from,n); }
struct Meta { const char *name; const char *getClassName() { return name; } };
struct OSObject {
 virtual ~OSObject() {} Meta meta={"Other"};
 Meta *getMetaClass() { return &meta; }
};
struct OSData:OSObject {
 uint32_t value; unsigned length; bool serializable;
 OSData(uint32_t v,unsigned n,bool s=true):value(v),length(n),serializable(s) {meta.name="OSData";}
 unsigned getLength() {return length;}
 const void *getBytesNoCopy() {assert(length==4);return &value;}
 bool isSerializable() {return serializable;}
};
struct OSNumber:OSObject {
 unsigned long long value;
 OSNumber(unsigned long long v):value(v) {meta.name="OSNumber";}
 unsigned long long unsigned64BitValue() {return value;}
};
struct IORegistryEntry {const char *getName() {return "chosen";}};
#define OSDynamicCast(T,o) dynamic_cast<T*>(o)
'''
main = r'''
int main(int argc,char **argv) {
 config=argc>1 ? atoi(argv[1]):0;
 IORegistryEntry entry; OSData good(1,4), shortData(0,3), hidden(2,4,false);
 OSNumber number(2); OSObject other;
 nabu_scale_property_trace(&entry,"serial-number",&good,"direct");
 nabu_scale_property_trace(&entry,nullptr,nullptr,"direct");
 assert(records.empty());
 nabu_scale_property_trace(&entry,"display-scale",&good,"direct");
 nabu_scale_property_trace(&entry,"display-rotation",&shortData,"direct");
 nabu_scale_property_trace(&entry,"artwork-scale-factor",&number,"direct");
 nabu_scale_property_trace(&entry,"display-scale",nullptr,"compat-or-missing");
 nabu_scale_property_trace(&entry,"display-scale",&hidden,"direct");
 nabu_scale_property_trace(&entry,"display-scale",&other,"direct");
 assert(parse_calls==1);
 if(!config) {assert(records.empty());return 0;}
 assert(records.size()==6);
 assert(records[0].find("length=4 serializable=1 word=0x1")!=std::string::npos);
 assert(records[1].find("length=3 serializable=1 word=0x0")!=std::string::npos);
 assert(records[2].find("type=OSNumber")!=std::string::npos);
 assert(records[2].find("number=2")!=std::string::npos);
 assert(records[3].find("source=compat-or-missing type=missing")!=std::string::npos);
 assert(records[4].find("serializable=0 word=0x2")!=std::string::npos);
 for(int i=0;i<200;i++) nabu_scale_property_trace(&entry,"display-scale",&good,"direct");
 assert(records.size()==96);
 assert(good.value==1 && number.value==2);
}
'''
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    cpp = root / "test.cpp"
    cpp.write_text(prelude + helper + main)
    exe = root / "test"
    subprocess.run([a.cc, "-std=c++14", "-Wall", "-Wextra", "-Werror",
                    str(cpp), "-o", str(exe)], check=True)
    for enabled in ("0", "1"):
        subprocess.run([str(exe), enabled], check=True)
print("Display-scale trace model passed: disabled, typed values, missing, budget, no mutation.")
