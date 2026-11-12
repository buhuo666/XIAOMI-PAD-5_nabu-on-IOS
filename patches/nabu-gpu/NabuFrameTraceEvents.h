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
    PresentSourceRect, PresentDestinationRect, PresentLayerFlags,
    // Non-pixel transaction: id=swap, a=mask; queued b=depth,
    // complete b=IOReturn/c=cumulative successful clears. Exclude from FPS.
    InactiveLayerClearQueued, InactiveLayerClearComplete,
    // Same physical VBlank retained until accepted flip resources retire.
    VsyncRetirementWait, VsyncRetirementPublished,
    // Successful acquired read: id=lease; a=physical segment count,
    // b=merged mapping ranges, c=initial reservation storage count.
    ProducerReadShape,
    // Non-pixel partial commit inherits layer0: id=new swap, a=old swap,
    // b=surface, c=transferred lease. Its later scan acceptance is not new FPS.
    InactiveLayerClearInherited
};
enum PresentRejection : uint32_t {
    ShortSwap = 0, ExtraLayers = 1, SourceRect = 2, DestinationRect = 3,
    MissingSurfaceAndClear = 4
};
}
#endif
