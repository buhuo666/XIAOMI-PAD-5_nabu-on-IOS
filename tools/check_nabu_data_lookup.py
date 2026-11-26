"""Exercise the production Data volume selection with a host IOKit registry fixture."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    production = (ROOT/'patches/nabu-apfs/NabuDataLookup.cpp').read_text()
    production = production[production.index('extern "C" int nabu_data_device_path'):]
    fixture = r'''
#include <cassert>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <strings.h>
#include <map>
#include <string>
#include <vector>
struct OSObject {virtual ~OSObject()=default;};
struct OSString:OSObject {std::string text;OSString(const char*s):text(s){} const char*getCStringNoCopy(){return text.c_str();}};
struct OSDictionary:OSObject {void release(){delete this;}};
struct OSIterator:OSObject {
 std::vector<OSObject*> values;size_t at=0;
 OSIterator(const std::vector<OSObject*>&v):values(v){}
 OSObject*getNextObject(){return at<values.size()?values[at++]:nullptr;}
 void release(){delete this;}
};
struct IORegistryEntry:OSObject {
 const char*kind;IORegistryEntry*parent;
 IORegistryEntry(const char*k,IORegistryEntry*p=nullptr):kind(k),parent(p){}
 void*metaCast(const char*k){return !strcmp(kind,k)?this:nullptr;}
 IORegistryEntry*getParentEntry(int){return parent;}
};
static std::vector<OSObject*> registry;
struct IOService:IORegistryEntry {
 std::map<std::string,OSObject*> props;
 using IORegistryEntry::IORegistryEntry;
 OSObject*getProperty(const char*k){return props.count(k)?props[k]:nullptr;}
 static OSDictionary*serviceMatching(const char*k){assert(!strcmp(k,"IOMedia"));return new OSDictionary;}
 static OSIterator*getMatchingServices(OSDictionary*){return new OSIterator(registry);}
};
#define OSDynamicCast(type,pointer) dynamic_cast<type*>(pointer)
static const char*kIOBSDNameKey="BSD Name";
static int gIOServicePlane=1;
static const char*requested=nullptr;
static bool PE_parse_boot_argn(const char*key,void*out,unsigned size){
 assert(!strcmp(key,"nabu-data-uuid"));
 if(!requested)return false;
 snprintf((char*)out,size,"%s",requested);return true;
}
''' + production + r'''
int main(){
 char out[64];
 IOService data("NabuDataBlock"),system("OtherBlock"),container("AppleAPFSContainer",&data);
 IOService wrong("AppleAPFSVolume",&system),volume("AppleAPFSVolume",&container),raw("IOMedia",&data);
 OSString oldUUID("168f804b-0cb5-4167-a239-c71953e36966"),newUUID("10325476-98ba-4cde-8f01-23456789abcd");
 OSString wrongName("disk0s1"),name("disk3s7"),rawName("disk3");
 wrong.props={{"UUID",&oldUUID},{"BSD Name",&wrongName}};
 volume.props={{"UUID",&newUUID},{"BSD Name",&name}};
 raw.props={{"UUID",&newUUID},{"BSD Name",&rawName}};
 registry={&wrong,&raw,&volume};
 assert(nabu_data_device_path(out,sizeof(out))==0&&!strcmp(out,"/dev/disk3s7"));
 for(unsigned id=0;id<256;++id){
  char text[37];snprintf(text,sizeof(text),"%08x-1234-4567-89ab-cdef01234567",id);
  newUUID.text=text;assert(nabu_data_device_path(out,sizeof(out))==0&&!strcmp(out,"/dev/disk3s7"));
 }
 requested=oldUUID.getCStringNoCopy();assert(nabu_data_device_path(out,sizeof(out))==ENXIO);
 requested=newUUID.getCStringNoCopy();assert(nabu_data_device_path(out,sizeof(out))==0);
 requested=nullptr;registry={&wrong,&raw};assert(nabu_data_device_path(out,sizeof(out))==ENXIO);
 registry={&volume};assert(nabu_data_device_path(out,4)==ENAMETOOLONG);
 volume.props.erase("BSD Name");assert(nabu_data_device_path(out,sizeof(out))==ENXIO);
 puts("PASS: arbitrary Data UUIDs, Data provider ancestry, unrelated system/raw media excluded, explicit UUID override, deferred publication and path size");
}
'''
    source = args.output/'DataLookup.cpp'
    source.write_text(fixture)
    executable = args.output/'DataLookup'
    subprocess.run(['clang++','-std=c++17','-Wall','-Wextra','-Werror',
                    '-fsanitize=address,undefined',str(source),'-o',str(executable)],check=True)
    output = subprocess.check_output([str(executable)],text=True)
    report = dict(passed=True,output=output,scope='Production lookup with simulated IOKit registry; device acceptance pending')
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(output)


if __name__ == '__main__':
    main()
