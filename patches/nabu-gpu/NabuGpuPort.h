/* SPDX-License-Identifier: MIT */
#ifndef NABU_GPU_PORT_H
#define NABU_GPU_PORT_H

#include <stdint.h>

#if (defined(NABU_GPU_USERLAND) && NABU_GPU_USERLAND) || (defined(NABU_GPU_METAL) && NABU_GPU_METAL)
#define NABU_GPU_CLIENT 1
#else
#define NABU_GPU_CLIENT 0
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Called by the existing DataBlock kmod after its storage and log service.
 * nabu-gpu=1 remains the explicit hardware start gate. */
void nabu_gpu_start(void);
void native_adreno_a6xx_dump_stats(void);

/* The completion SPI is drained from thread context before stopping GPU DMA.
 * Fault callbacks only mask it; they must never wait for their own handler. */
void nabu_gpu_detach_completion_irq(void);
struct NabuGpuIrqStats {
    uint64_t entries, callbacks, disabled, smmuPolls, fences, faults;
};
extern struct NabuGpuIrqStats nabu_gpu_irq_stats;
void nabu_gpu_irq_snapshot(struct NabuGpuIrqStats *);

/* Current append-only capture interfaces. The status function is implemented
 * beside the storage log pump and takes its existing reader/writer lock. Zero
 * means live capture; a nonzero result means unavailable, finished or failed.
 * No GPU code may seal the capture or directly write a log slot. */
uint32_t nabu_log_capture_length(void);
int nabu_gpu_log_status(uint64_t *committed, uint32_t *error);

#ifdef __cplusplus
}
#endif
#endif
