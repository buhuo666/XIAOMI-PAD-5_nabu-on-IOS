#!/usr/bin/env python3
"""Execute the patched display-property publisher against a small IOKit model.

Host test only. XNU must still compile on macOS; real CoreAnimation acceptance
and panel presentation are separate device checks.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--xnu-source", type=Path, required=True)
p.add_argument("--cc", default="clang++")
a = p.parse_args()
source = (a.xnu_source / "iokit/Kernel/arm/NabuFramebuffer.cpp").read_text()
start = source.index("static bool\nnabu_mode_number(")
end = source.index("\nvoid\nAppleCLCD::vsyncFired", start)
publisher = source[start:end]
assert source.index("if (!publishDisplayModes())") < source.index("\tregisterService();")
block_start = source.index("\tif (selector == kNabuFBGetBlock)")
block_end = source.index("\tif (selector >= 64", block_start)
block = source[block_start:block_end]
assert source.index("bzero(args->structureOutput") < block_start
prelude = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <vector>
#include <cstdio>
static int fail_after=-1, allocated=0;
static bool allocation() { return fail_after<0 || allocated++ != fail_after; }
struct Object { virtual ~Object() {} void release() {} };
struct Bool : Object {};
static Bool falseObject;
#define kOSBooleanFalse (&falseObject)
struct OSNumber : Object {
 uint32_t value;
 static OSNumber *withNumber(uint32_t v,int bits) {
  assert(bits==32); if(!allocation()) return nullptr;
  auto *o=new OSNumber; o->value=v; return o;
 }
};
struct OSDictionary : Object {
 std::map<std::string,Object*> values;
 static OSDictionary *withCapacity(int) { return allocation()?new OSDictionary:nullptr; }
 bool setObject(const char *key,Object *value) { values[key]=value; return true; }
};
struct OSArray : Object {
 std::vector<Object*> values;
 static OSArray *withCapacity(int) { return allocation()?new OSArray:nullptr; }
 bool setObject(Object *value) { values.push_back(value); return true; }
};
#define OSSafeReleaseNULL(x) do { if(x) (x)->release(); (x)=nullptr; } while(0)
#define IOLog(...) ((void)0)
struct AppleCLCD {
 uint32_t fLogicalW=1600,fLogicalH=2560;
 std::map<std::string,Object*> properties;
 bool setProperty(const char *key,Object *value) { properties[key]=value; return true; }
 void removeProperty(const char *key) { properties.erase(key); }
 bool publishDisplayModes();
};
struct Arguments {
 void *structureOutputDescriptor=nullptr;
 void *structureOutput=nullptr;
 uint32_t structureOutputSize=0,scalarInputCount=1;
 uint64_t scalarInput[1]={0x40};
};
enum { kNabuFBGetBlock=79,kIOReturnBadArgument=1 };
int getblock(Arguments *args) { int selector=79,ret=0;
 if(args->structureOutput) memset(args->structureOutput,0,args->structureOutputSize);
'''
main = r'''
 return ret;
}
uint32_t number(OSDictionary *d,const char *k) {
 return dynamic_cast<OSNumber*>(d->values.at(k))->value;
}
int main() {
 fail_after=10000; AppleCLCD fb; assert(fb.publishDisplayModes());
 int allocations=allocated;
 auto *timings=dynamic_cast<OSArray*>(fb.properties.at("TimingElements"));
 auto *colors=dynamic_cast<OSArray*>(fb.properties.at("ColorElements"));
 assert(timings->values.size()==1 && colors->values.size()==1);
 auto *timing=dynamic_cast<OSDictionary*>(timings->values[0]);
 auto *color=dynamic_cast<OSDictionary*>(colors->values[0]);
 auto *h=dynamic_cast<OSDictionary*>(timing->values.at("HorizontalAttributes"));
 auto *v=dynamic_cast<OSDictionary*>(timing->values.at("VerticalAttributes"));
 assert(number(timing,"ID")==1 && number(color,"ID")==1);
 assert(number(h,"Active")==1600 && number(v,"Active")==2560);
 assert(number(v,"SyncRate")==60u<<16 && number(v,"PreciseSyncRate")==60u<<16);
 assert(number(color,"Depth")==8 && number(color,"EOTF")==1);
 for(int i=0;i<allocations;i++) {
  allocated=0; fail_after=i; AppleCLCD failing;
  assert(!failing.publishDisplayModes()); assert(failing.properties.empty());
 }
 uint8_t buf[40]; Arguments args;args.structureOutput=buf;args.structureOutputSize=sizeof(buf);
 assert(getblock(&args)==0);uint32_t ids[2];memcpy(ids,buf+4,8);
 assert(ids[0]==1 && ids[1]==1 && buf[0]==0 && buf[39]==0);
 args.structureOutputSize=11;assert(getblock(&args)==kIOReturnBadArgument);
 args.structureOutputSize=40;args.structureOutputDescriptor=buf;
 assert(getblock(&args)==kIOReturnBadArgument);
 args.structureOutputDescriptor=nullptr;args.scalarInputCount=0;
 assert(getblock(&args)==kIOReturnBadArgument);
}
'''
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    cpp, exe = root / "mode.cpp", root / "mode-test"
    cpp.write_text(prelude.split("int getblock(")[0] + publisher +
                   "int getblock(" + prelude.split("int getblock(", 1)[1] + block + main)
    subprocess.run([a.cc, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    str(cpp), "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print("Display publisher and current-mode block passed host model tests")
