// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
struct hakios_qrtr_ops;
// The callback runs only on the GLINK owner, outside the adapter lock. Payload
// storage is borrowed until return. true means copied into the real GLINK FIFO;
// false means retain/retry. type is QRTR_DATA(1) or QRTR_DEL_CLIENT(6).
typedef bool (*NabuAth10kQrtrSend)(void *cookie,uint32_t type,uint32_t from,
    uint32_t node,uint32_t to,const void *data,size_t bytes);
bool nabu_ath10k_qrtr_prepare(void); // Once, before exposing clients; heap state persists for this boot.
bool nabu_ath10k_qrtr_start_instance(void); // Call on the sole GLINK owner; old handles must be released.
const struct hakios_qrtr_ops *nabu_ath10k_qrtr_transport(void);
int nabu_ath10k_qrtr_announce(uint32_t service,uint32_t version,uint32_t instance,uint32_t node,uint32_t port);
int nabu_ath10k_qrtr_withdraw(uint32_t service,uint32_t version,uint32_t instance,uint32_t node,uint32_t port);
// True means the destination belongs to this adapter, including retired port
// numbers and rejected old/wrong-source packets. Do not route it to old services.
bool nabu_ath10k_qrtr_receive(uint32_t local,uint32_t node,uint32_t port,const void *data,size_t bytes);
int nabu_ath10k_qrtr_poll(NabuAth10kQrtrSend send,void *cookie);
void nabu_ath10k_qrtr_invalidate(void); // PFR/BYE: notify removal on the next owner poll.
void nabu_ath10k_qrtr_shutdown(void); // Stop delivery, wait for leases; QMI clients must still release handles.
// All int results are zero or positive errno. No function fabricates a QMI reply.
// qmi_handle_release must run outside a currently executing owner callback.
#ifdef __cplusplus
}
#endif
