#!/usr/bin/env python3
"""Run the production surface cache with real ARC/IOSurface and injected bridge outcomes."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from build_nabu_surface_import_cache import stage_surface_import_cache

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <IOSurface/IOSurfaceRef.h>
#include <atomic>
#include <cassert>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <tuple>
#include <vector>
struct NmbDevice {};
using Releaser=void (*)(void*,void*,uint64_t);
static std::atomic<unsigned> attempts{0},allocations{0},releases{0},live{0},injected{0};
static std::atomic<unsigned> expectedReleases{0};
static std::function<void()> releaseHook;
static thread_local std::string errorText;
static std::string injectedError;
static NSString *logged;
static std::atomic<uint64_t> gSurfaceImportsMade,gSurfaceImportsReleased;
static NmbDevice *gDevice;
struct Import {
 Releaser release;void *context,*pointer;uint64_t length;
 Import(Releaser r,void *c,void *p,uint64_t n):release(r),context(c),pointer(p),length(n){++allocations;++live;}
 ~Import(){--live;++releases;release(context,pointer,length);
  if(releaseHook){auto hook=std::move(releaseHook);releaseHook={};hook();}}
};
struct NmbBuffer {std::shared_ptr<Import> owner;};
static NmbBuffer *nmb_buffer_new_no_copy_releasing(NmbDevice*,void *p,uint64_t n,uint64_t,Releaser release,void *context) {
 ++attempts;assert(releases>=expectedReleases);
 unsigned remaining=injected;
 while(remaining&&!injected.compare_exchange_weak(remaining,remaining-1)){}
 if(remaining){errorText=injectedError;return nullptr;}
 return new NmbBuffer{std::make_shared<Import>(release,context,p,n)};
}
static void nmb_buffer_release(NmbBuffer *p){delete p;}
static NSString *lastError(){return [NSString stringWithUTF8String:errorText.c_str()];}
static void releaseSurface(void *context,void*,uint64_t){++gSurfaceImportsReleased;CFRelease((IOSurfaceRef)context);}
#define NBLOG(...) do{logged=[NSString stringWithFormat:__VA_ARGS__];}while(0)
@interface NBBuffer : NSObject
@property(nonatomic) NmbBuffer *handle;
@property(nonatomic) MTLResourceOptions options;
@property(nonatomic) IOSurfaceRef importedSurface;
@end
@implementation NBBuffer
- (void)dealloc {nmb_buffer_release(_handle);}
@end
@interface TextureOwner : NSObject
@property(nonatomic,strong) NBBuffer *buffer;
@end
@implementation TextureOwner
@end
#include "NativeMetalSurfaceImports.inc"

static IOSurfaceRef makeSurface() {
 return IOSurfaceCreate((__bridge CFDictionaryRef)@{(id)kIOSurfaceWidth:@64,(id)kIOSurfaceHeight:@64,
  (id)kIOSurfaceBytesPerElement:@4,(id)kIOSurfaceBytesPerRow:@256,(id)kIOSurfacePixelFormat:@0x42475241});
}
static NBBuffer *get(IOSurfaceRef s){assert(s);return surfaceBuffer(s,IOSurfaceGetBaseAddress(s),IOSurfaceGetAllocSize(s));}
static void reset() {
 trimHeldImports(true);assert(!live&&gHeldImports.empty());
 {std::lock_guard<std::mutex> lock(gSurfaceImportLock);[gSurfaceImports removeAllObjects];}
 attempts=allocations=releases=injected=expectedReleases=0;gSurfaceImportsMade=gSurfaceImportsReleased=0;
 logged=nil;releaseHook={};injectedError.clear();
}
static void expired_before_allocate() {
 reset();
 @autoreleasepool {IOSurfaceRef first=makeSurface();assert(get(first));CFRelease(first);}
 assert(live==1);expectedReleases=1;
 // Release re-enters the real cache function; it would deadlock under its mutex.
 releaseHook=[]{native_bridge_metal_trim_surface_imports();};
 @autoreleasepool {IOSurfaceRef second=makeSurface();assert(get(second));assert(attempts==2&&releases==1);CFRelease(second);}
 trimHeldImports(false);assert(releases==2&&live==0);
}
static void device_oom_drops_only_cache() {
 reset();IOSurfaceRef first=makeSurface();
 @autoreleasepool {assert(get(first));}
 assert(CFGetRetainCount(first)>1&&live==1);
 injected=1;injectedError="no-copy buffer: OutOfMemory(Device)";
 releaseHook=[]{native_bridge_metal_trim_surface_imports();errorText="changed by release";};
 @autoreleasepool {IOSurfaceRef second=makeSurface();assert(get(second));assert(attempts==3&&releases==1&&live==1);CFRelease(second);}
 assert(CFGetRetainCount(first)==1);CFRelease(first);trimHeldImports(false);assert(!live&&releases==2);
}
static void texture_and_pending_command_survive() {
 reset();IOSurfaceRef first=makeSurface(),second=makeSurface();
 TextureOwner *texture=[TextureOwner new];std::shared_ptr<Import> pending;
 @autoreleasepool {texture.buffer=get(first);pending=texture.buffer.handle->owner;}
 injected=2;injectedError="no-copy buffer: OutOfMemory(Device)";
 @autoreleasepool {assert(!get(second));}
 assert(attempts==3&&allocations==1&&releases==0&&live==1&&gHeldImports.empty());
 assert([logged hasSuffix:@"no-copy buffer: OutOfMemory(Device)"]);
 @autoreleasepool {texture=nil;}
 assert(releases==0&&live==1); // fake runtime pending job owns the import, beyond NBBuffer lifetime
 pending.reset();assert(releases==1&&!live);
 assert(CFGetRetainCount(first)==1&&CFGetRetainCount(second)==1);CFRelease(first);CFRelease(second);
}
static void exact_failure_and_single_retry() {
 for(const char *reason:{"no-copy buffer: OutOfMemory(Host)","no-copy buffer: InvalidExternalHandle"}) {
  reset();IOSurfaceRef first=makeSurface(),second=makeSurface();@autoreleasepool{assert(get(first));}
  injected=3;injectedError=reason;
  @autoreleasepool{assert(!get(second));}
  assert(attempts==2&&live==1&&releases==0&&gHeldImports.size()==1);
  assert([logged hasSuffix:[NSString stringWithUTF8String:reason]]&&CFGetRetainCount(second)==1);
  CFRelease(first);CFRelease(second);trimHeldImports(false);
 }
 reset();IOSurfaceRef s=makeSurface();injected=3;injectedError="no-copy buffer: OutOfMemory(Device)";
 @autoreleasepool{assert(!get(s));}
 assert(attempts==2&&allocations==0&&injected==1&&CFGetRetainCount(s)==1);CFRelease(s);
}
static void concurrent_cache_recheck() {
 reset();IOSurfaceRef s=makeSurface();
 @autoreleasepool {
  NSMutableArray<NBBuffer*> *owners=[NSMutableArray array];
  dispatch_apply(64,dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^(size_t i){
   (void)i;@autoreleasepool{NBBuffer *b=get(s);assert(b);@synchronized(owners){[owners addObject:b];}}
  });
  assert(attempts==1&&allocations==1&&owners.count==64);
  for(NBBuffer *b in owners)assert(b==owners[0]);
 }
 CFRelease(s);trimHeldImports(false);assert(releases==1&&!live);
}
static void reentrant_creator_wins_oom_gap() {
 reset();IOSurfaceRef first=makeSurface(),target=makeSurface();@autoreleasepool{assert(get(first));}
 injected=1;injectedError="no-copy buffer: OutOfMemory(Device)";
 NBBuffer *winner=nil;
 releaseHook=[&]{@autoreleasepool{winner=get(target);assert(winner);}};
 @autoreleasepool{NBBuffer *answer=get(target);assert(answer&&answer==winner);}
 assert(attempts==3&&allocations==2&&releases==1); // old + failed + racing winner; no duplicate retry import
 winner=nil;CFRelease(first);CFRelease(target);trimHeldImports(false);assert(!live&&releases==2);
}
int main(){@autoreleasepool{
 expired_before_allocate();device_oom_drops_only_cache();texture_and_pending_command_survive();
 exact_failure_and_single_retry();concurrent_cache_recheck();reentrant_creator_wins_oom_gap();reset();
 puts("PASS: actual ARC surface cache prune, OOM retry, lock-free release, live owners, pending runtime, parallel and racing creators");
}return 0;}
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source-input',type=Path)
    p.add_argument('--stage-only',action='store_true')
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    source=out/'cache.mm';source.write_text(HARNESS,encoding='utf-8')
    shutil.copyfile(ROOT/'patches/nabu-metal/NativeMetalSurfaceImports.inc',out/'NativeMetalSurfaceImports.inc')
    if args.source_input:
        stage=out/'frontend';stage.mkdir(exist_ok=True)
        original=(args.source_input/'NativeBridgeMetalFrontend.mm').read_text(encoding='utf-8')
        (stage/'NativeBridgeMetalFrontend.mm').write_text(original,encoding='utf-8')
        stage_surface_import_cache(ROOT,stage)
        updated=(stage/'NativeBridgeMetalFrontend.mm').read_text(encoding='utf-8')
        begin=original.index('static NSMapTable<NSValue *,NBBuffer *> *gSurfaceImports;')
        end=original.index('static uint64_t textureRotation(',begin)
        assert updated==original[:begin]+'#include "NativeMetalSurfaceImports.inc"\n\n'+original[end:]
    if args.stage_only:
        print('Only the recorded cache region changed; ARC execution still requires macOS');return
    if sys.platform!='darwin':p.error('Actual ARC/IOSurface checks require macOS')
    command=['xcrun','--sdk','macosx','clang++','-std=c++17','-O1','-g','-fobjc-arc',
             '-Wall','-Wextra','-Werror','-Wno-deprecated-declarations','-fsanitize=address,undefined',
             '-fno-omit-frame-pointer',source,'-framework','Foundation','-framework','Metal',
             '-framework','IOSurface','-o',out/'cache']
    for label,argv in [('compile',command),('run',[out/'cache'])]:
        r=subprocess.run(list(map(str,argv)),capture_output=True,timeout=120)
        (out/(label+'.log')).write_bytes(r.stdout+r.stderr)
        if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode(errors='replace')[-6000:])
    report=dict(passed=True,actual_arc=True,actual_iosurface=True,production_cache_used=True,
                release_outside_mutex=True,concurrent_callers=64,device_oom_retry_limit=1,
                texture_and_pending_runtime_ownership_preserved=True,
                mocked=['Vulkan bridge allocation/failure','pending GPU runtime owner'],device_executed=False)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
