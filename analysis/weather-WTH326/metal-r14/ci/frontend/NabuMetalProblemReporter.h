// SPDX-License-Identifier: MIT
// Retains the factory's already validated accelerator service for diagnostic
// IOServiceOpen markers. No GPU connection, selectors, resources or waits.
#pragma once
#include "NabuMetalProblemStream.h"
#include <atomic>
#include <dlfcn.h>
#include <mach/mach.h>

namespace nabumetalproblem {
using OpenFn=int (*)(unsigned,unsigned,uint32_t,unsigned *);
using CloseFn=int (*)(unsigned);
using RetainFn=int (*)(unsigned);
static OpenFn gOpen;
static CloseFn gClose;
static std::atomic<unsigned> gPort{0};
static Stream gStream;

static bool send(const char *text,bool exception=false) {
    const unsigned port=gPort.load(std::memory_order_acquire);
    if(!port)return false;
    gStream.send([port](uint32_t value) {
        unsigned connection=0;
        // Unsupported is the expected return: the kernel logs the marker
        // without constructing a user client or obtaining the GPU's lock.
        if(gOpen(port,mach_task_self(),0x41470000u|value,&connection)==0 && connection)
            gClose(connection);
    },text,exception);
    return true;
}
static void start(unsigned port) {
    static std::once_flag once;
    std::call_once(once,[port] {
        void *iokit=dlopen("/System/Library/Frameworks/IOKit.framework/IOKit",RTLD_NOW|RTLD_LOCAL);
        if(!iokit)return;
        auto retain=reinterpret_cast<RetainFn>(dlsym(iokit,"IOObjectRetain"));
        auto open=reinterpret_cast<OpenFn>(dlsym(iokit,"IOServiceOpen"));
        auto close=reinterpret_cast<CloseFn>(dlsym(iokit,"IOServiceClose"));
        if(!retain || !open || !close || retain(port)!=0)return;
        gOpen=open;gClose=close;
        gPort.store(port,std::memory_order_release);
        send("METAL-DIAG ready");
    });
}
} // namespace nabumetalproblem
