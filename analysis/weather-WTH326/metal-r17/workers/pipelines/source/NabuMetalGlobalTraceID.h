// SPDX-License-Identifier: MIT
#pragma once
#include "NabuMetalProblemReporter.h"
#include "NabuMetalGlobalTraceProtocol.h"
#include <mutex>

// Each block is allocated by the shared kernel service; local counters are
// never used to invent identities when the service refuses the request.
static uint64_t nabuMetalNextGlobalTraceID() {
    using ReadProperty=int (*)(unsigned,const char *,void *,unsigned *);
    static std::mutex lock;
    static uint64_t next=0,end=0;
    static ReadProperty readProperty=nullptr;
    std::lock_guard<std::mutex> guard(lock);
    if(next==end) {
        if(!readProperty) {
            void *iokit=dlopen("/System/Library/Frameworks/IOKit.framework/IOKit",RTLD_NOW|RTLD_LOCAL);
            if(iokit)readProperty=reinterpret_cast<ReadProperty>(dlsym(iokit,"IORegistryEntryGetProperty"));
        }
        NabuMetalTraceIDBlock block{};
        unsigned length=sizeof(block);
        const unsigned port=nabumetalproblem::gPort.load(std::memory_order_acquire);
        if(!port || !readProperty || readProperty(port,NabuMetalTraceIDProperty,&block,&length)!=0 ||
           length!=sizeof(block) || block.version!=1 || block.count!=NabuMetalTraceIDBlockCount || !block.first) {
            [NSException raise:NSInternalInconsistencyException format:@"Metal global trace ID allocation failed"];
        }
        next=block.first;
        end=block.first+block.count;
    }
    return next++;
}
