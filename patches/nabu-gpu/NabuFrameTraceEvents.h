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
    // b=surface, c=retained lease. This event is not a new pixel acceptance.
    InactiveLayerClearInherited,
    // Atomic no-pixel ownership handoff: id=new swap, a=old swap,
    // b=unchanged mapping token, c=unchanged real scan sequence. Ends the old
    // transaction, not its still-active resources; never substitutes for 38.
    InactiveLayerClearOwnership
};
enum PresentRejection : uint32_t {
    ShortSwap = 0, ExtraLayers = 1, SourceRect = 2, DestinationRect = 3,
    MissingSurfaceAndClear = 4
};
}
#endif
