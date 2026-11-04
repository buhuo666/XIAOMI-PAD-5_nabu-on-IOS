// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef NABU_LOG_CAPTURE_H
#define NABU_LOG_CAPTURE_H

#include <stdint.h>

/* Storage is append-only even after a disk checkpoint: a published prefix is
 * immutable for the entire boot. No allocator, device operation or printf is
 * permitted on these producer paths. Kernel callers serialize PutLocked and
 * SealLocked with loader_log_lock. Failed-lock producers may only call Lost. */
#define NABU_LOG_CAPTURE_BYTES (56U * 1024U * 1024U)
#define NABU_LOG_CAPTURE_SEALED (UINT64_C(1) << 63)
#define NABU_LOG_CAPTURE_LOST_MASK (NABU_LOG_CAPTURE_SEALED - 1)

/* Tests supply the same acquire/release operations using host atomics. */
#ifndef NABU_LOG_CAPTURE_LOAD
#define NABU_LOG_CAPTURE_LOAD(p, order) os_atomic_load((p), order)
#define NABU_LOG_CAPTURE_STORE(p, value, order) os_atomic_store((p), (value), order)
#define NABU_LOG_CAPTURE_CAS(p, old, value, order) os_atomic_cmpxchg((p), (old), (value), order)
#define NABU_LOG_CAPTURE_OR(p, value, order) os_atomic_or((p), (value), order)
#endif

struct NabuLogCaptureState {
  char data[NABU_LOG_CAPTURE_BYTES];
  uint32_t length;
  /* The seal bit and loss counter share one atomic word: loss increments
   * either precede sealing or are excluded by it. A sealed loss count is final. */
  uint64_t loss_and_seal;
};

static inline uint32_t
nabuLogCaptureLength(const struct NabuLogCaptureState *s)
{
  return NABU_LOG_CAPTURE_LOAD(&s->length, acquire);
}

static inline uint64_t
nabuLogCaptureLostBytes(const struct NabuLogCaptureState *s)
{
  return NABU_LOG_CAPTURE_LOAD(&s->loss_and_seal, acquire) & NABU_LOG_CAPTURE_LOST_MASK;
}

static inline void
nabuLogCaptureLost(struct NabuLogCaptureState *s)
{
  uint64_t old = NABU_LOG_CAPTURE_LOAD(&s->loss_and_seal, relaxed);
  for (;;) {
    if ((old & NABU_LOG_CAPTURE_SEALED) || old == NABU_LOG_CAPTURE_LOST_MASK) return;
    if (NABU_LOG_CAPTURE_CAS(&s->loss_and_seal, old, old + 1, relaxed)) return;
    old = NABU_LOG_CAPTURE_LOAD(&s->loss_and_seal, relaxed);
  }
}

static inline void
nabuLogCapturePutLocked(struct NabuLogCaptureState *s, char c)
{
  if (NABU_LOG_CAPTURE_LOAD(&s->loss_and_seal, relaxed) & NABU_LOG_CAPTURE_SEALED) return;
  uint32_t at = NABU_LOG_CAPTURE_LOAD(&s->length, relaxed);
  if (at == NABU_LOG_CAPTURE_BYTES) {
    nabuLogCaptureLost(s);
    return;
  }
  s->data[at] = c;
  /* The writer may read only through an acquired length snapshot. */
  NABU_LOG_CAPTURE_STORE(&s->length, at + 1, release);
}

static inline void
nabuLogCaptureSealLocked(struct NabuLogCaptureState *s)
{
  NABU_LOG_CAPTURE_OR(&s->loss_and_seal, NABU_LOG_CAPTURE_SEALED, release);
}

#endif
