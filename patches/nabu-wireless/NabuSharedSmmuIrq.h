// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "NabuWlanFault.h"

// WLAN and audio have separate context IRQs but share the one global IRQ.
// join/leave run under hakios_smmu_lock. Callbacks never take that mutex.
struct NabuSharedSmmuIrq {
    using Handler=void (*)(void *,uint32_t);
    struct Subscriber { Handler handler=nullptr; void *cookie=nullptr; } subscribers[2];
    NabuWlanFault::IrqOps irq{};
    void (*pause)()=nullptr;
    unsigned users=0,active=0;

    static void dispatch(void *cookie,uint32_t intid) {
        auto &self=*(NabuSharedSmmuIrq *)cookie;
        __atomic_fetch_add(&self.active,1,__ATOMIC_SEQ_CST);
        for(auto &entry:self.subscribers) {
            Handler handler=__atomic_load_n(&entry.handler,__ATOMIC_SEQ_CST);
            if(handler)handler(entry.cookie,intid);
        }
        __atomic_fetch_sub(&self.active,1,__ATOMIC_SEQ_CST);
    }
    int join(Handler handler,void *cookie) {
        for(auto &entry:subscribers)if(!__atomic_load_n(&entry.handler,__ATOMIC_SEQ_CST)) {
            entry.cookie=cookie;
            __atomic_store_n(&entry.handler,handler,__ATOMIC_SEQ_CST);
            if(!users&&irq.attach(irq.cookie,NabuWlanFault::global_irq,false,dispatch,this)) {
                __atomic_store_n(&entry.handler,Handler(nullptr),__ATOMIC_SEQ_CST);
                entry.cookie=nullptr;return -1;
            }
            ++users;return 0;
        }
        return -1;
    }
    void leave(void *cookie) {
        for(auto &entry:subscribers)if(entry.cookie==cookie&&__atomic_load_n(&entry.handler,__ATOMIC_SEQ_CST)) {
            __atomic_store_n(&entry.handler,Handler(nullptr),__ATOMIC_SEQ_CST);
            // Wait for any IRQ that already loaded this subscriber. A later
            // IRQ sees null; its cookie and MMIO can then be released safely.
            while(__atomic_load_n(&active,__ATOMIC_SEQ_CST))pause();
            entry.cookie=nullptr;
            if(!--users)irq.detach(irq.cookie,NabuWlanFault::global_irq);
            return;
        }
    }
};
