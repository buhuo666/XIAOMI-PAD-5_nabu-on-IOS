#!/usr/bin/env python3
"""Exercise the production family cache through a real Objective-C IMP and ARC."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from build_nabu_surface_import_cache import (
    FAMILY_INSTALL_NEW, FAMILY_INSTALL_OLD, FAMILY_PATCH, stage_family_answers,
)

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <mutex>
#include <string>

struct NmbDevice {};
static NmbDevice runtime;
static NmbDevice *gDevice=&runtime;
struct Reply {uint64_t value=0;unsigned failures=0;unsigned calls=0;};
static std::mutex replyLock;
static std::map<uint64_t,Reply> replies;
static std::atomic<unsigned> logged{0},queries{0};
static thread_local std::string errorText;
static NSString *lastError(){return [NSString stringWithUTF8String:errorText.c_str()];}
static bool nmb_device_answer(NmbDevice *device,const char *selector,uint64_t arg,uint64_t *out) {
 assert(device==gDevice&&strcmp(selector,"supportsFamily:")==0&&out);
 std::lock_guard<std::mutex> lock(replyLock);
 auto found=replies.find(arg);assert(found!=replies.end());
 Reply &reply=found->second;++reply.calls;++queries;
 if(reply.failures){--reply.failures;errorText="injected transient query failure";return false;}
 *out=reply.value;return true;
}
#define NBLOG(...) do{NSString *message=[NSString stringWithFormat:__VA_ARGS__];assert([message hasSuffix:@"injected transient query failure"]);++logged;}while(0)
#include "NativeMetalFamilyAnswers.inc"

@interface FamilyDevice : NSObject
@end
@implementation FamilyDevice
@end

static SEL familySelector;
static BOOL ask(id device,NSUInteger family) {
 return ((BOOL(*)(id,SEL,NSUInteger))objc_msgSend)(device,familySelector,family);
}
static void reply(uint64_t family,uint64_t value,unsigned failures=0) {
 std::lock_guard<std::mutex> lock(replyLock);replies[family]={value,failures,0};
}
static unsigned calls(uint64_t family) {
 std::lock_guard<std::mutex> lock(replyLock);return replies.at(family).calls;
}
static void repeated_true_false_and_parameters() {
 @autoreleasepool {
  id device=[FamilyDevice new];
  // Values are injected bridge outcomes, not a table of claimed GPU support.
  // Noncanonical nonzero values preserve the original flagAnswer normalization.
  reply(1001,7);reply(1008,0);
  for(unsigned i=0;i<1000;++i){assert(ask(device,1001)==YES);assert(ask(device,1008)==NO);}
  assert(calls(1001)==1&&calls(1008)==1);
  const uint64_t raw[]={0,1,0x100000001ULL,0x8000000000000001ULL,UINT64_MAX};
  const uint64_t value[]={0,UINT64_MAX,0,1,0};
  for(unsigned i=0;i<5;++i)reply(raw[i],value[i]);
  for(unsigned repeat=0;repeat<8;++repeat)
   for(unsigned i=0;i<5;++i)assert(ask(device,(NSUInteger)raw[i])==(value[i]!=0));
  for(uint64_t family:raw)assert(calls(family)==1);
  NSDictionary *cache=objc_getAssociatedObject(device,&gFamilyAnswersKey);
  assert(cache.count==7);
 }
}
static void separate_device_owners() {
 @autoreleasepool {
  id first=[FamilyDevice new],second=[FamilyDevice new];reply(1010,0);
  assert(ask(first,1010)==NO&&ask(first,1010)==NO&&calls(1010)==1);
  assert(ask(second,1010)==NO&&ask(second,1010)==NO&&calls(1010)==2);
  id a=objc_getAssociatedObject(first,&gFamilyAnswersKey),b=objc_getAssociatedObject(second,&gFamilyAnswersKey);
  assert(a&&b&&a!=b);
 }
}
static void concurrent_first_query() {
 @autoreleasepool {
  id device=[FamilyDevice new];reply(2002,1);reply(3003,0);
  dispatch_apply(64,dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^(size_t i){
   (void)i;@autoreleasepool {
    for(unsigned repeat=0;repeat<20;++repeat){assert(ask(device,2002)==YES);assert(ask(device,3003)==NO);}
   }
  });
  assert(calls(2002)==1&&calls(3003)==1);
 }
}
static void failure_retries_then_caches() {
 @autoreleasepool {
  id device=[FamilyDevice new];reply(4001,1,2);reply(4002,0,1);
  assert(ask(device,4001)==NO&&ask(device,4001)==NO&&calls(4001)==2);
  assert(!objc_getAssociatedObject(device,&gFamilyAnswersKey));
  assert(ask(device,4001)==YES&&ask(device,4001)==YES&&calls(4001)==3);
  assert(ask(device,4002)==NO&&calls(4002)==1);
  NSDictionary *cache=objc_getAssociatedObject(device,&gFamilyAnswersKey);
  assert(!cache[@4002]);
  assert(ask(device,4002)==NO&&ask(device,4002)==NO&&calls(4002)==2);
  assert(logged==3);
 }
}
static void association_lifetime_and_abi() {
 __weak id weakDevice=nil,weakCache=nil;
 reply(5001,1);
 @autoreleasepool {
  __attribute__((objc_precise_lifetime)) id device=[FamilyDevice new];weakDevice=device;
  assert(ask(device,5001)==YES);
  weakCache=objc_getAssociatedObject(device,&gFamilyAnswersKey);
  assert(weakDevice&&weakCache);
 }
 assert(!weakDevice&&!weakCache);
 @autoreleasepool {id next=[FamilyDevice new];assert(ask(next,5001)==YES&&calls(5001)==2);}
 assert(class_getInstanceSize([FamilyDevice class])==class_getInstanceSize([NSObject class]));
}
int main(){@autoreleasepool{
 static_assert(sizeof(NSUInteger)==8,"The deployed Objective-C ABI uses full 64-bit arguments");
 familySelector=sel_registerName("supportsFamily:");
 assert(class_addMethod([FamilyDevice class],familySelector,(IMP)familyArgAnswer,"B24@0:8Q16"));
 assert(class_getMethodImplementation([FamilyDevice class],familySelector)==(IMP)familyArgAnswer);
 repeated_true_false_and_parameters();separate_device_owners();concurrent_first_query();
 failure_retries_then_caches();association_lifetime_and_abi();
 assert(queries==18&&logged==3);
 puts("PASS: production IMP, true/false cache, full 64-bit arguments, distinct device owners, 64 concurrent callers, retry, ARC lifetime and unchanged instance size");
 printf("COUNTS: backend_queries=%u logged_failures=%u\n",queries.load(),logged.load());
}return 0;}
'''


def check_staging(source_input,out):
    original=(source_input/'NativeBridgeMetalFrontend.mm').read_text(encoding='utf-8')
    stage=out/'frontend';stage.mkdir(exist_ok=True)
    path=stage/'NativeBridgeMetalFrontend.mm'
    path.write_text(original,encoding='utf-8',newline='\n')
    stage_family_answers(ROOT,stage)
    updated=path.read_text(encoding='utf-8')
    anchor='static void installAnswers(Class cls) {'
    expected=original.replace(anchor,'#include "'+FAMILY_PATCH+'"\n\n'+anchor,1)
    expected=expected.replace(FAMILY_INSTALL_OLD,FAMILY_INSTALL_NEW,1)
    assert updated==expected
    assert (stage/FAMILY_PATCH).read_bytes()==(ROOT/'patches/nabu-metal'/FAMILY_PATCH).read_bytes()
    for name in ('NativeMetalCaPresentTrace.inc','NativeMetalSurfaceImports.inc'):
        assert updated.count('#include "'+name+'"')==original.count('#include "'+name+'"')
    try:
        stage_family_answers(ROOT,stage)
    except ValueError as error:
        assert 'already staged' in str(error)
    else:
        raise AssertionError('A repeated patch must be refused')
    assert path.read_text(encoding='utf-8')==updated
    # Both anchors must be unique before any source edit.
    for label,broken in [('missing',original.replace(FAMILY_INSTALL_OLD,'')),
                         ('duplicate',original+'\n'+anchor+'\n')]:
        invalid=out/label;invalid.mkdir(exist_ok=True)
        invalid_path=invalid/'NativeBridgeMetalFrontend.mm'
        invalid_path.write_text(broken,encoding='utf-8',newline='\n')
        try:
            stage_family_answers(ROOT,invalid)
        except ValueError:
            pass
        else:
            raise AssertionError('Changed qualified anchors must be refused')
        assert invalid_path.read_text(encoding='utf-8')==broken
        assert not (invalid/FAMILY_PATCH).exists()
    return dict(passed=True,only_two_source_sites_changed=True,cache_patch_copied_exactly=True,
                existing_ca_and_surface_cache_includes_preserved=True,
                repeated_or_changed_anchors_refused_before_edit=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source-input',type=Path)
    p.add_argument('--stage-only',action='store_true')
    args=p.parse_args()
    if args.stage_only and not args.source_input:p.error('--stage-only requires --source-input')
    if not args.stage_only and sys.platform!='darwin':p.error('Actual Objective-C/ARC checks require macOS')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    staging=check_staging(args.source_input.resolve(),out) if args.source_input else None
    if args.stage_only:
        report=dict(stage_only=True,staging=staging,actual_objc_imp=False,actual_arc=False,device_executed=False)
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report));return
    source=out/'family.mm';source.write_text(HARNESS,encoding='utf-8',newline='\n')
    shutil.copyfile(ROOT/'patches/nabu-metal'/FAMILY_PATCH,out/FAMILY_PATCH)
    command=['xcrun','--sdk','macosx','clang++','-std=c++17','-O1','-g','-fobjc-arc',
             '-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer',
             source,'-framework','Foundation','-o',out/'family']
    for label,argv in [('compile',command),('run',[out/'family'])]:
        r=subprocess.run(list(map(str,argv)),capture_output=True,timeout=120)
        (out/(label+'.log')).write_bytes(r.stdout+r.stderr)
        if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode(errors='replace')[-6000:])
    output=(out/'run.log').read_text(encoding='utf-8')
    if 'COUNTS: backend_queries=18 logged_failures=3' not in output:
        raise RuntimeError('Production IMP query counts missing from execution')
    report=dict(passed=True,stage_only=False,staging=staging,actual_objc_imp=True,actual_arc=True,
                production_cache_used=True,concurrent_callers=64,backend_queries=18,logged_failures=3,
                true_and_false_cached=True,full_uint64_arguments_preserved=True,device_caches_independent=True,
                failed_queries_retried=True,device_association_released=True,instance_size_unchanged=True,
                mocked=['Rust device family query outcomes'],device_executed=False)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report))


if __name__=='__main__':main()
