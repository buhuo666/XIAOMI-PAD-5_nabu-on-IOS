// SPDX-License-Identifier: MIT
#include "NabuAllocationPressure.h"

static size_t releaseImportsForAllocationPressure() {
 std::vector<NBBuffer *> released;
 {
  std::lock_guard<std::mutex> lock(gSurfaceImportLock);
  pruneHeldImports(true,released);
 }
 const size_t removed=released.size();
 released.clear();
 return removed;
}

template<class Allocate>
static auto allocateWithImportPressure(NSString *operation,NSString *oom,Allocate allocate)
 -> decltype(allocate()) {
 return nabuAllocateWithImportPressure(allocate,
  [&]{return [lastError() isEqualToString:oom];},
  releaseImportsForAllocationPressure,
  [&](size_t removed,bool recovered){
   NBLOG(@"native-metal: allocation-pressure operation=%@ cache_refs_dropped=%zu recovered=%u",
         operation,removed,unsigned(recovered));
  });
}
