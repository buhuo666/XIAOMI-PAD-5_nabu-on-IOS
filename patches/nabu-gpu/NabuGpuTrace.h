// SPDX-License-Identifier: MIT
#pragma once
#include "NabuFrameTraceCore.h"
#include "NabuFrameTraceEvents.h"
#include <IOKit/IOTypes.h>

namespace NabuGpuTrace {
// 48 MiB: 17,476 events/second for a 60-second window. At 120 fps with
// three GPU jobs/frame the expected 5.5-6.5k events/s fits with headroom.
// A ten-minute load still needs separate bounded windows and full-run counters.
constexpr uint32_t Capacity = 1048576;
// Called once by the service's publishing thread. Allocates ordinary kernel
// memory, never DMA storage. Recording stays disabled until a requested window.
IOReturn initialize();
IOReturn start(uint32_t durationMs);
void stop();
uint32_t window();
void record(uint32_t event, uint64_t identity, uint64_t a = 0, uint64_t b = 0, uint64_t c = 0);
void recordAt(uint64_t timeUs, uint32_t event, uint64_t identity,
              uint64_t a = 0, uint64_t b = 0, uint64_t c = 0);
void recordWindow(uint32_t expectedWindow, uint32_t event, uint64_t identity,
                  uint64_t a = 0, uint64_t b = 0, uint64_t c = 0);
// Control calls are serialized by the publication service's export lock.
// A stopped window is immutable. Reads may be retried; the host acknowledges
// its durable complete export separately. No allocation, I/O or bulk copy
// occurs under the IRQ lock.
IOReturn snapshot(NabuFrameTrace::Metadata *metadata);
IOReturn read(uint32_t expectedWindow, uint32_t offset, NabuFrameTrace::Record *out, uint32_t limit,
              uint32_t *copied, NabuFrameTrace::Metadata *metadata);
IOReturn acknowledge(uint32_t expectedWindow, uint32_t count);
// Caller holds the GPU scheduler lock. Zero denotes advance() outside its
// completion worker; no thread identity is inferred from timestamp proximity.
void setWorker(uint64_t sequence);
uint64_t worker();
}
