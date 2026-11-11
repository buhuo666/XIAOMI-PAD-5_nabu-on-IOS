// SPDX-License-Identifier: MIT
#import <QuartzCore/CAMetalLayer.h>
#include "ca_trace_marker.h"
#include <cstdlib>

static std::atomic<bool> gCaPresentTrace{false};
extern "C" void native_bridge_metal_set_ca_trace(bool enabled) {
 gCaPresentTrace.store(enabled, std::memory_order_relaxed);
}
// Snapshot only identity before present. No new completion or ownership change.
static void nabuCaPresent(id<MTLDrawable> drawable, bool timed, CFTimeInterval time) {
 const bool trace = gCaPresentTrace.load(std::memory_order_relaxed);
 uint64_t identity=0, surfaceID=0, pointer=0;
 if(trace) {
  identity=drawable.drawableID;
  if([(id)drawable respondsToSelector:@selector(texture)]) {
   IOSurfaceRef surface=[(id<CAMetalDrawable>)drawable texture].iosurface;
   if(surface)surfaceID=IOSurfaceGetID(surface);
  }
  pointer=(uint64_t)(uintptr_t)(__bridge void *)drawable;
  nabu_ca_trace_marker(81,identity,surfaceID,pointer,timed);
 }
 if(timed)[drawable presentAtTime:time];else [drawable present];
 if(trace)nabu_ca_trace_marker(82,identity,surfaceID,pointer,timed);
}
