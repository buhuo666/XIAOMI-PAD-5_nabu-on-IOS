/* SPDX-License-Identifier: MIT */
#ifndef NABU_CA_IPC_TRACE_H
#define NABU_CA_IPC_TRACE_H
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#ifndef NABU_CA_IPC_HOST_TEST
#include <ipc/ipc_kmsg.h>
#include <kern/task.h>
#include <kern/thread.h>
#include <mach/ndr.h>
#endif

#ifdef __cplusplus
extern "C" {
#endif
/* The XNU-owned bridge is inert until the GPU recorder registers its callbacks. */
uint32_t nabu_ca_ipc_trace_window(void);
void nabu_ca_ipc_trace_record(uint32_t window, uint32_t event, uint64_t identity,
    uint64_t a, uint64_t b, uint64_t c);
#ifdef __cplusplus
}
#endif

/* All fields are raw integers. No port name is used as a cross-process key.
 * cookie is an opaque kmsg address, valid only within its recorded lifetime.
 * token is unique for begin/result pairs in mach_msg.c, including pointer reuse.
 * Missing begins, overflow, window boundaries and ambiguous reuse stay unmatched.
 *
 * event                    identity a              b                         c
 * SendBegin/ReceiveBegin    token    cookie         senderPID:msgID           flags:bodyID
 * SendPayload              token    inputTimeBits  options64                 sendTimeoutMs
 * SendResult               token    cookie         raw status                phase (1 copyin,2 send)
 * SendReturn               token    cookie         final trap status         0
 * Queued                   cookie   senderPID:ID   flags:bodyID              msgcount:headSeqno
 * Direct/Dequeued           cookie   senderPID:ID   flags:bodyID              receiverPID:seqno
 * ReceivePayload           token    inputTimeBits  receiverPID:seqno         initial receive status
 * ReceiveResult            token    cookie         final receive status      auxCopied:msgCopied
 * Dropped                  cookie   senderPID:ID   reason                    raw cause
 * ReceiveNotTaken           cookie   senderPID:ID   flags:bodyID              receiverPID:status
 * ':' packs high32:low32. A queue head seqno is NOT this message's assigned seqno.
 * 40205 bodyID=context identifier, 40402 bodyID=queue identifier, never seed.
 */
enum NabuCaIpcTraceEvent {
    NabuCaIpcSendBegin = 64, NabuCaIpcSendPayload = 65,
    NabuCaIpcSendResult = 66, NabuCaIpcSendReturn = 67,
    NabuCaIpcQueued = 68, NabuCaIpcDirect = 69, NabuCaIpcDequeued = 70,
    NabuCaIpcReceiveBegin = 71, NabuCaIpcReceivePayload = 72,
    NabuCaIpcReceiveResult = 73, NabuCaIpcDropped = 74,
    NabuCaIpcReceiveNotTaken = 75
};
enum NabuCaIpcDropReason {
    NabuCaIpcCircular = 1, NabuCaIpcInactivePort = 2,
    NabuCaIpcPortDiedWhileSending = 3, NabuCaIpcPostDestroyed = 4
};
typedef struct NabuCaIpcSnapshot {
    uint64_t cookie, token, inputTimeBits;
    uint32_t window, messageID, senderPID, bodyID, flags;
} NabuCaIpcSnapshot;

static inline uint64_t
nabu_ca_ipc_pair(uint32_t high, uint32_t low)
{
    return ((uint64_t)high << 32) | low;
}

/* Called only while the caller owns the kmsg, or holds its queue lock.
 * This never allocates, copies user memory, changes the message, or logs.
 * sender_override is needed before copyin initializes the kernel audit trailer.
 */
static inline NabuCaIpcSnapshot
nabu_ca_ipc_capture(ipc_kmsg_t kmsg, int32_t sender_override)
{
    NabuCaIpcSnapshot s = {0};
    uint32_t window = nabu_ca_ipc_trace_window();
    if (!window || kmsg == IKM_NULL) return s;
    const mach_msg_header_t *h = ikm_header(kmsg);
    const uint32_t id = (uint32_t)h->msgh_id;
    const uint32_t bytes = id == 40205 ? 24 : id == 40402 ? 12 : 0;
    if (!bytes || (h->msgh_bits & MACH_MSGH_BITS_COMPLEX) ||
        h->msgh_size != sizeof(mach_msg_header_t) + bytes) return s;
    const uint8_t *p = (const uint8_t *)ikm_udata(kmsg, 0, false);
    if (memcmp(p, &NDR_record, sizeof(NDR_record_t)) != 0) return s;
    s.window = window; s.cookie = (uint64_t)(uintptr_t)kmsg; s.messageID = id;
    s.senderPID = sender_override >= 0 ? (uint32_t)sender_override :
        ipc_kmsg_get_trailer(kmsg, false)->msgh_audit.val[5];
    memcpy(&s.bodyID, p + 8, sizeof(s.bodyID));
    if (id == 40205) {
        memcpy(&s.flags, p + 12, sizeof(s.flags));
        memcpy(&s.inputTimeBits, p + 16, sizeof(s.inputTimeBits));
    }
    return s;
}

/* Both paired begin sites are in mach_msg.c. Queue-only snapshots need no token. */
static inline void
nabu_ca_ipc_begin(NabuCaIpcSnapshot *s, uint32_t event)
{
    static uint64_t next_token;
    if (!s->window) return;
    s->token = __atomic_add_fetch(&next_token, 1, __ATOMIC_RELAXED);
    nabu_ca_ipc_trace_record(s->window, event, s->token, s->cookie,
        nabu_ca_ipc_pair(s->senderPID, s->messageID), nabu_ca_ipc_pair(s->flags, s->bodyID));
}
static inline void
nabu_ca_ipc_paired(const NabuCaIpcSnapshot *s, uint32_t event,
    uint64_t a, uint64_t b, uint64_t c)
{
    if (s->window) nabu_ca_ipc_trace_record(s->window, event, s->token, a, b, c);
}
static inline void
nabu_ca_ipc_stage(const NabuCaIpcSnapshot *s, uint32_t event, uint64_t route)
{
    if (s->window) nabu_ca_ipc_trace_record(s->window, event, s->cookie,
        nabu_ca_ipc_pair(s->senderPID, s->messageID), nabu_ca_ipc_pair(s->flags, s->bodyID), route);
}
static inline void
nabu_ca_ipc_drop(const NabuCaIpcSnapshot *s, uint32_t reason, uint32_t cause)
{
    if (s->window) nabu_ca_ipc_trace_record(s->window, NabuCaIpcDropped, s->cookie,
        nabu_ca_ipc_pair(s->senderPID, s->messageID), reason, cause);
}
#endif
