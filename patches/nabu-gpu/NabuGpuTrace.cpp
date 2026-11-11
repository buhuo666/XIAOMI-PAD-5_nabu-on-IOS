// SPDX-License-Identifier: MIT
#include "NabuGpuTrace.h"
#include "NativeAdrenoKernelTime.h"
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>

namespace NabuGpuTrace {
namespace {
IOSimpleLock *lock;
NabuFrameTrace::Recorder recorder;
uint32_t activeWindow;
uint64_t currentWorker;

uint64_t nowUs() {
    uint64_t now = 0;
    NativeAdrenoKernelTime::now_us(nullptr, &now);
    return now;
}
IOReturn status(NabuFrameTrace::Status value) {
    switch (value) {
        case NabuFrameTrace::Ok: return kIOReturnSuccess;
        case NabuFrameTrace::Busy: return kIOReturnBusy;
        case NabuFrameTrace::NotStopped: return kIOReturnNotReady;
        case NabuFrameTrace::Invalid: return kIOReturnBadArgument;
    }
    return kIOReturnBadArgument;
}
void publishWindow() {
    const auto &m = recorder.metadata();
    __atomic_store_n(&activeWindow, m.active ? m.window : 0, __ATOMIC_RELEASE);
}
}

IOReturn initialize() {
    if (lock) return kIOReturnSuccess;
    auto allocatedLock = IOSimpleLockAlloc();
    auto allocatedStorage = IONewData(NabuFrameTrace::Record, Capacity);
    if (!allocatedLock || !allocatedStorage) {
        if (allocatedLock) IOSimpleLockFree(allocatedLock);
        if (allocatedStorage) IODeleteData(allocatedStorage, NabuFrameTrace::Record, Capacity);
        return kIOReturnNoMemory;
    }
    recorder.initialize(allocatedStorage, Capacity);
    lock = allocatedLock;
    return kIOReturnSuccess;
}
IOReturn start(uint32_t durationMs) {
    if (!lock) return kIOReturnNotReady;
    const IOInterruptState irq = IOSimpleLockLockDisableInterrupt(lock);
    const uint64_t now = nowUs();
    recorder.expire(now);
    const auto result = recorder.start(now, durationMs);
    publishWindow();
    IOSimpleLockUnlockEnableInterrupt(lock, irq);
    return status(result);
}
void stop() {
    if (!lock) return;
    const IOInterruptState irq = IOSimpleLockLockDisableInterrupt(lock);
    const uint64_t now = nowUs();
    recorder.stop(now); publishWindow();
    IOSimpleLockUnlockEnableInterrupt(lock, irq);
}
uint32_t window() { return __atomic_load_n(&activeWindow, __ATOMIC_ACQUIRE); }
void record(uint32_t event, uint64_t identity, uint64_t a, uint64_t b, uint64_t c) {
    const uint32_t captured = window();
    if (captured) recordWindow(captured, event, identity, a, b, c);
}
void recordAt(uint64_t timeUs, uint32_t event, uint64_t identity, uint64_t a, uint64_t b, uint64_t c) {
    const uint32_t captured = window();
    if (!captured) return;
    const IOInterruptState irq = IOSimpleLockLockDisableInterrupt(lock);
    if (recorder.metadata().window == captured) {
        recorder.append(timeUs, event, identity, a, b, c); publishWindow();
    }
    IOSimpleLockUnlockEnableInterrupt(lock, irq);
}
void recordWindow(uint32_t expectedWindow, uint32_t event, uint64_t identity,
                  uint64_t a, uint64_t b, uint64_t c) {
    if (!expectedWindow || window() != expectedWindow) return;
    const uint64_t now = nowUs();
    const IOInterruptState irq = IOSimpleLockLockDisableInterrupt(lock);
    if (recorder.metadata().window == expectedWindow) {
        recorder.append(now, event, identity, a, b, c); publishWindow();
    }
    IOSimpleLockUnlockEnableInterrupt(lock, irq);
}
IOReturn snapshot(NabuFrameTrace::Metadata *metadata) {
    if (!lock) return kIOReturnNotReady;
    if (!metadata) return kIOReturnBadArgument;
    const IOInterruptState irq = IOSimpleLockLockDisableInterrupt(lock);
    const uint64_t now = nowUs();
    recorder.expire(now); publishWindow(); *metadata = recorder.metadata();
    IOSimpleLockUnlockEnableInterrupt(lock, irq);
    return kIOReturnSuccess;
}
IOReturn read(uint32_t expectedWindow, uint32_t offset, NabuFrameTrace::Record *out, uint32_t limit,
              uint32_t *copied, NabuFrameTrace::Metadata *metadata) {
    if (copied) *copied = 0;
    if (!lock) return kIOReturnNotReady;
    if (!metadata || limit > 4096) return kIOReturnBadArgument;
    const IOInterruptState irq = IOSimpleLockLockDisableInterrupt(lock);
    const uint64_t now = nowUs();
    recorder.expire(now); publishWindow();
    const bool matches = expectedWindow && expectedWindow == recorder.metadata().window;
    const bool stopped = !recorder.metadata().active;
    *metadata = recorder.metadata();
    IOSimpleLockUnlockEnableInterrupt(lock, irq);
    // The export lock excludes Start/Stop/Read/Acknowledge; a stopped recorder
    // cannot append. Copying up to 192 KiB must not block GPU/display IRQs.
    const auto result = !matches ? NabuFrameTrace::Invalid : !stopped ? NabuFrameTrace::NotStopped :
        recorder.read(offset, out, limit, copied);
    if (matches && stopped) *metadata = recorder.metadata();
    return status(result);
}
IOReturn acknowledge(uint32_t expectedWindow, uint32_t count) {
    if (!lock) return kIOReturnNotReady;
    const IOInterruptState irq = IOSimpleLockLockDisableInterrupt(lock);
    const auto result = expectedWindow && expectedWindow == recorder.metadata().window ?
        recorder.acknowledge(count) : NabuFrameTrace::Invalid;
    IOSimpleLockUnlockEnableInterrupt(lock, irq);
    return status(result);
}
void setWorker(uint64_t sequence) { currentWorker = sequence; }
uint64_t worker() { return currentWorker; }
}
