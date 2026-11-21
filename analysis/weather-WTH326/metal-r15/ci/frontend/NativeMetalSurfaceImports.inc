// SPDX-License-Identifier: MIT
// Replace only the frontend's IOSurface import cache. Texture and command
// owners still hold their original NBBuffer/runtime objects and pinned pages.
static NSMapTable<NSValue *,NBBuffer *> *gSurfaceImports;
static std::mutex gSurfaceImportLock;
struct HeldImport {
 NBBuffer *buffer;
 IOSurfaceRef surface;
};
static auto &gHeldImports=*new std::map<std::tuple<uint64_t,uint64_t,uint64_t>,HeldImport>;
static NSUInteger gSurfaceImportsPruned=64;
static dispatch_source_t gImportPressureSource;

static void pruneHeldImports(bool all,std::vector<NBBuffer *> &released) {
 for(auto it=gHeldImports.begin();it!=gHeldImports.end();) {
  if(all || CFGetRetainCount(it->second.surface)<=1) {
   released.push_back(it->second.buffer);
   it=gHeldImports.erase(it);
  } else {
   ++it;
  }
 }
}

static void trimHeldImports(bool all) {
 std::vector<NBBuffer *> released;
 {
  std::lock_guard<std::mutex> lock(gSurfaceImportLock);
  pruneHeldImports(all,released);
 }
 released.clear();
}

extern "C" void native_bridge_metal_trim_surface_imports(void) {
 trimHeldImports(false);
}

static void watchImportPressure() {
 static dispatch_once_t once;
 dispatch_once(&once,^{
  gImportPressureSource=dispatch_source_create(DISPATCH_SOURCE_TYPE_MEMORYPRESSURE,0,
   DISPATCH_MEMORYPRESSURE_WARN|DISPATCH_MEMORYPRESSURE_CRITICAL,dispatch_get_global_queue(QOS_CLASS_UTILITY,0));
  if(!gImportPressureSource)return;
  dispatch_source_set_event_handler(gImportPressureSource,^{trimHeldImports(true);});
  dispatch_activate(gImportPressureSource);
 });
}

static void holdImport(uint64_t identity,uint64_t address,uint64_t bytes,NBBuffer *buffer,std::vector<NBBuffer *> &released) {
 pruneHeldImports(false,released);
 gHeldImports[{identity,address,bytes}]={buffer,buffer.importedSurface};
}

static NBBuffer *surfaceBuffer(IOSurfaceRef surface,void *base,size_t bytes) {
 struct Key {uint64_t identity,address,bytes;};
 const Key value={IOSurfaceGetID(surface),(uintptr_t)base,bytes};
 NSValue *key=value.identity?[NSValue valueWithBytes:&value objCType:@encode(Key)]:nil;
 watchImportPressure();

 // Destroy detached cache owners outside the mutex: their runtime deallocator
 // may call the frontend again. A racing creator is checked after every unlock.
 std::vector<NBBuffer *> released;
 std::unique_lock<std::mutex> lock(gSurfaceImportLock);
 if(!gSurfaceImports)gSurfaceImports=[NSMapTable strongToWeakObjectsMapTable];
 NBBuffer *buffer=key?[gSurfaceImports objectForKey:key]:nil;
 if(buffer) {
  holdImport(value.identity,value.address,value.bytes,buffer,released);
  return buffer;
 }
 pruneHeldImports(false,released);
 lock.unlock();released.clear();lock.lock();

 for(unsigned attempt=0;attempt<2;++attempt) {
  buffer=key?[gSurfaceImports objectForKey:key]:nil;
  if(buffer) {
   holdImport(value.identity,value.address,value.bytes,buffer,released);
   return buffer;
  }
  NmbBuffer *handle=nmb_buffer_new_no_copy_releasing(gDevice,base,bytes,MTLResourceStorageModeShared,
                                                   releaseSurface,(void *)CFRetain(surface));
  if(!handle) {
   // LAST is per-thread and another release can change it. Retain the exact
   // failure before dropping cache owners or invoking the bridge again.
   NSString *failure=[lastError() copy];
   CFRelease(surface); // A refused bridge call does not run its deallocator.
   if(!attempt && [failure isEqualToString:@"no-copy buffer: OutOfMemory(Device)"]) {
    // Only cache references leave here. Live texture/command/runtime owners
    // still retain their imports; this never declares GPU work complete.
    pruneHeldImports(true,released);
    lock.unlock();released.clear();lock.lock();
    continue;
   }
   NBLOG(@"native-metal: surface import refused at %llx+%zx id%u %ux%u %08x: %@",
    (unsigned long long)(uintptr_t)base,bytes,(unsigned)IOSurfaceGetID(surface),
    (unsigned)IOSurfaceGetWidth(surface),(unsigned)IOSurfaceGetHeight(surface),
    (unsigned)IOSurfaceGetPixelFormat(surface),failure);
   return nil;
  }
  gSurfaceImportsMade++;
  buffer=[NBBuffer new];buffer.handle=handle;buffer.options=MTLResourceStorageModeShared;
  buffer.importedSurface=surface;
  if(key) {
   if(gSurfaceImports.count>=gSurfaceImportsPruned) {
    for(NSValue *old in gSurfaceImports.keyEnumerator.allObjects)
     if(![gSurfaceImports objectForKey:old])[gSurfaceImports removeObjectForKey:old];
    gSurfaceImportsPruned=MAX(gSurfaceImports.count*2,(NSUInteger)64);
   }
   [gSurfaceImports setObject:buffer forKey:key];
   holdImport(value.identity,value.address,value.bytes,buffer,released);
  }
  return buffer;
 }
 return nil;
}
