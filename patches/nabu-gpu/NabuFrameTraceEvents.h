// SPDX-License-Identifier: MIT
#pragma once
#ifndef NABU_FRAME_TRACE_EVENTS_H
#define NABU_FRAME_TRACE_EVENTS_H
#include <stdint.h>
namespace NabuGpuTrace {
enum Event : uint32_t {
    GpuAccepted = 1, GpuIssued, GpuCompleted, GpuIrq,
    WorkerBegin, WorkerLocked, WorkerEnd, ProducerCallback,
    GpuHardwareTicks, GpuClockBracket, GpuHardwareValidity, ProducerWriter,
    GpuClockRelation, GpuClockContract,
    Present = 32, Queued, ProducerReady, Mapped, ScanSubmit, Accepted, Retired,
    Vblank, VblankNotify, DisplayWorker, DisplayFailure, ScanAcceptedCounters,
    NativeVblankDelivery, PresentRejected, PresentSurfaceList,
    PresentSourceRect, PresentDestinationRect
};
enum PresentRejection : uint32_t {
    ShortSwap = 0, ExtraLayers = 1, SourceRect = 2, DestinationRect = 3,
    MissingSurfaceAndClear = 4
};
}
#endif
