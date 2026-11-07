// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <kern/thread.h>
#include <sys/errno.h>
extern "C" {
#include "../../src/hakios-8796/xnu/files/bsd/sys/hakios.qrtr.h"
}
#include "NabuAth10kQrtr.h"
#include "NabuAth10kQrtr.api.h"

struct hakios_qrtr_port { uint32_t id=0,node=0;bool retired=false; };
struct NabuQrtrNative {
    // Placement construction initializes the large queues in their heap storage,
    // without making a 64KiB aggregate temporary on the kernel stack.
    static void *operator new(size_t,void *address){return address;}
    NabuAth10kQrtr router;
    IOLock *lock=nullptr;
    thread_t owner=nullptr;
    bool stopping=true,peer_seen=false,control_lease=false,polling=false;
    uint32_t peer_node=0;
    hakios_qrtr_port ports[NabuAth10kQrtr::port_count]{};
};
static NabuQrtrNative *native;
using Router=NabuAth10kQrtr;
static int qrtr_error(Router::Result r) {
    switch(r) {
        case Router::Ok:return 0;case Router::Full:return ENOBUFS;
        case Router::TooLarge:return EMSGSIZE;case Router::Closed:return ENXIO;
        case Router::NotConnected:return ENOTCONN;case Router::Busy:return EBUSY;
        case Router::Empty:return EWOULDBLOCK;case Router::InstanceLost:return ENETDOWN;
        default:return EINVAL;
    }
}
static bool valid_port(const hakios_qrtr_port *port) {
    for(auto &p:native->ports)if(&p==port)return p.id&&!p.retired;
    return false;
}
static hakios_qrtr_port *qrtr_open(hakios_qrtr_receive_t receive,hakios_qrtr_server_t server,void *context) {
    if(!native)return nullptr;
    IOLockLock(native->lock);hakios_qrtr_port *out=nullptr;
    if(!native->stopping)for(auto &p:native->ports)if(!p.id) {
        if(native->router.open(receive,server,context,p.id)==Router::Ok)out=&p;
        break;
    }
    IOLockUnlock(native->lock);return out;
}
static int qrtr_send(hakios_qrtr_port *port,uint32_t node,uint32_t to,const void *data,size_t bytes) {
    if(!native)return ENXIO;
    IOLockLock(native->lock);
    int result=valid_port(port)?qrtr_error(native->router.send(port->id,node,to,data,bytes)):ENXIO;
    IOLockUnlock(native->lock);return result;
}
static int qrtr_lookup(hakios_qrtr_port *port,uint32_t service,uint32_t version,uint32_t instance) {
    if(!native)return ENXIO;
    IOLockLock(native->lock);
    int result=valid_port(port)?qrtr_error(native->router.lookup(port->id,service,version,instance)):ENXIO;
    IOLockUnlock(native->lock);return result;
}
static void qrtr_close(hakios_qrtr_port *port) {
    if(!native)return;
    IOLockLock(native->lock);
    if(!valid_port(port)){IOLockUnlock(native->lock);return;}
    native->router.begin_close(port->id);
    while(native->router.finish_close(port->id)==Router::Busy) {
        // Real ath10k callbacks only post work. They must not release their
        // own handle synchronously while the QMI delivery stack still uses it.
        if(current_thread()==native->owner)panic("Nabu QRTR: synchronous close inside owner lease");
        IOLockSleep(native->lock,&native->router,THREAD_UNINT);
    }
    if(native->peer_seen&&!native->stopping&&native->router.instance_live()) {
        port->node=native->peer_node;port->retired=true; // owner sends DEL_CLIENT before slot reuse.
    } else *port={};
    IOLockWakeup(native->lock,&native->router,false);
    IOLockUnlock(native->lock);
}
static const hakios_qrtr_ops qrtr_ops={qrtr_open,qrtr_send,qrtr_lookup,qrtr_close};

extern "C" bool nabu_ath10k_qrtr_prepare() {
    if(native)return true;
    IOLock *lock=IOLockAlloc();if(!lock)return false;
    void *memory=IOMalloc(sizeof(NabuQrtrNative));
    if(!memory){IOLockFree(lock);return false;}
    native=new (memory) NabuQrtrNative;native->lock=lock;return true;
}
extern "C" const hakios_qrtr_ops *nabu_ath10k_qrtr_transport(){return &qrtr_ops;}
extern "C" bool nabu_ath10k_qrtr_start_instance() {
    if(!native)return false;
    IOLockLock(native->lock);
    bool free=!native->polling&&!native->control_lease;
    for(auto &p:native->ports)if(p.id)free=false;
    bool ok=free&&native->router.start_instance()==Router::Ok;
    if(ok){native->owner=current_thread();native->stopping=false;native->peer_seen=false;}
    IOLockUnlock(native->lock);
    if(ok)hakios_qmi_set_transport(&qrtr_ops);
    return ok;
}
extern "C" int nabu_ath10k_qrtr_announce(uint32_t service,uint32_t version,uint32_t instance,uint32_t node,uint32_t port) {
    if(!native)return ENXIO;
    IOLockLock(native->lock);
    Router::Result result=Router::Invalid;
    if(!native->stopping&&current_thread()==native->owner) {
        result=native->router.announce({service,version,instance,node,port});
        if(result==Router::Ok){native->peer_node=node;native->peer_seen=true;}
        else if(result==Router::InstanceLost) {
            native->peer_seen=false;for(auto &p:native->ports)if(p.retired)p={};
        }
    }
    IOLockUnlock(native->lock);return qrtr_error(result);
}
extern "C" int nabu_ath10k_qrtr_withdraw(uint32_t service,uint32_t version,uint32_t instance,uint32_t node,uint32_t port) {
    if(!native)return ENXIO;
    IOLockLock(native->lock);
    Router::Result result=Router::Invalid;
    if(!native->stopping&&current_thread()==native->owner) {
        result=native->router.withdraw({service,version,instance,node,port});
        if(result==Router::Ok) {
            native->peer_seen=false;for(auto &p:native->ports)if(p.retired)p={};
        }
    }
    IOLockUnlock(native->lock);return qrtr_error(result);
}
extern "C" bool nabu_ath10k_qrtr_receive(uint32_t local,uint32_t node,uint32_t port,const void *data,size_t bytes) {
    if(!native)return false;
    IOLockLock(native->lock);
    bool owned=native->router.owns_port(local);
    if(owned&&!native->stopping&&current_thread()==native->owner)
        (void)native->router.receive(local,node,port,data,bytes);
    IOLockUnlock(native->lock);return owned;
}
extern "C" int nabu_ath10k_qrtr_poll(NabuAth10kQrtrSend send,void *cookie) {
    if(!native||!send)return EINVAL;
    IOLockLock(native->lock);
    if(native->stopping||current_thread()!=native->owner||native->polling) {
        int result=native->stopping?ENETDOWN:current_thread()!=native->owner?EPERM:EBUSY;
        IOLockUnlock(native->lock);return result;
    }
    native->polling=true;
    // Retired native slots reserve their number until DEL_CLIENT is actually
    // copied to the owner transport. The id check also permits cancellation
    // by shutdown/invalidation while a control packet is outside the lock.
    for(auto &p:native->ports)if(p.retired) {
        uint32_t id=p.id,node=p.node,body[5]={6,1,id,0,0};
        native->control_lease=true;
        IOLockUnlock(native->lock);
        bool sent=send(cookie,6,id,node,0xfffffffe,body,sizeof(body));
        IOLockLock(native->lock);
        native->control_lease=false;IOLockWakeup(native->lock,&native->router,false);
        if(sent&&p.id==id&&p.retired)p={};
        if(!sent||native->stopping)break;
    }
    for(unsigned i=0;i<Router::queue_count&&!native->stopping;++i) {
        Router::Send packet;
        if(native->router.begin_send(packet)!=Router::Ok)break;
        IOLockUnlock(native->lock);
        bool sent=send(cookie,1,packet.local,packet.node,packet.port,packet.data,packet.bytes);
        IOLockLock(native->lock);
        native->router.finish_send(packet.ticket,sent);IOLockWakeup(native->lock,&native->router,false);
        if(!sent)break;
    }
    for(unsigned i=0;i<Router::port_count+Router::queue_count&&!native->stopping;++i) {
        Router::Callback callback;
        if(native->router.begin_callback(callback)!=Router::Ok)break;
        IOLockUnlock(native->lock);callback.invoke();IOLockLock(native->lock);
        native->router.finish_callback(callback.ticket);IOLockWakeup(native->lock,&native->router,false);
    }
    native->polling=false;IOLockWakeup(native->lock,&native->router,false);
    IOLockUnlock(native->lock);return 0;
}
extern "C" void nabu_ath10k_qrtr_invalidate() {
    if(!native)return;
    IOLockLock(native->lock);native->router.invalidate();native->peer_seen=false;
    for(auto &p:native->ports)if(p.retired)p={};
    IOLockWakeup(native->lock,&native->router,false);IOLockUnlock(native->lock);
}
extern "C" void nabu_ath10k_qrtr_shutdown() {
    if(!native)return;
    hakios_qmi_set_transport(nullptr);
    IOLockLock(native->lock);native->stopping=true;native->peer_seen=false;native->router.invalidate();
    for(auto &p:native->ports)if(p.retired)p={};else if(p.id)native->router.begin_close(p.id);
    while(native->router.has_leases()||native->control_lease||native->polling) {
        if(current_thread()==native->owner)panic("Nabu QRTR: shutdown inside owner lease");
        IOLockSleep(native->lock,&native->router,THREAD_UNINT);
    }
    IOLockUnlock(native->lock);
}
