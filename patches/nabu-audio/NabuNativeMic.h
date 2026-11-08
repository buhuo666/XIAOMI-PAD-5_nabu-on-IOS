// SPDX-License-Identifier: BSD-2-Clause-Patent
// Native48k/S16 mono input. Samples are supplied only by real DSP READ_DONE.
#pragma once
extern "C" {
#include <sys/conf.h>
#include <sys/uio.h>
#include <sys/errno.h>
#include <sys/stat.h>
#include <miscfs/devfs/devfs.h>
}
namespace NabuNativeMic {
static constexpr unsigned Frames=16384;
static int16_t *ring;
static uint32_t head,tail,wanted,available;
static uint64_t received,read_frames,dropped,nonzero;
static uint32_t peak;
static int device_open(dev_t,int,int,struct proc *) {
    if(!__atomic_load_n(&available,__ATOMIC_ACQUIRE))return ENXIO;
    if(__atomic_exchange_n(&wanted,1,__ATOMIC_ACQ_REL))return EBUSY;
    __atomic_store_n(&tail,__atomic_load_n(&head,__ATOMIC_ACQUIRE),__ATOMIC_RELEASE);
    return 0;
}
static int device_close(dev_t,int,int,struct proc *) {
    __atomic_store_n(&wanted,0,__ATOMIC_RELEASE);return 0;
}
static int device_read(dev_t,struct uio *uio,int) {
    uint32_t t=tail,h=__atomic_load_n(&head,__ATOMIC_ACQUIRE);
    uint32_t count=h-t;uint64_t want=uint64_t(uio_resid(uio))/2;
    if(want<count)count=uint32_t(want);
    while(count) {
        unsigned at=t&(Frames-1),n=count<Frames-at?count:Frames-at;
        int error=uiomove((caddr_t)(ring+at),int(n*2),uio);if(error)return error;
        t+=n;count-=n;read_frames+=n;__atomic_store_n(&tail,t,__ATOMIC_RELEASE);
    }
    return 0;
}
static const struct cdevsw operations={
    .d_open=device_open,.d_close=device_close,.d_read=device_read,.d_write=eno_rdwrt,
    .d_ioctl=eno_ioctl,.d_stop=eno_stop,.d_reset=eno_reset,.d_ttys=nullptr,.d_select=eno_select,
    .d_mmap=eno_mmap,.d_strategy=eno_strat,.d_reserved_1=nullptr,.d_reserved_2=nullptr,.d_type=0
};
static bool publish() {
    ring=(int16_t *)IOMalloc(Frames*2);if(!ring)return false;
    int major=cdevsw_add(-1,&operations);
    if(major<0) {IOFree(ring,Frames*2);ring=nullptr;return false;}
    if(!devfs_make_node(makedev(major,0),DEVFS_CHAR,0,0,0666,"hakios-mic")) {
        cdevsw_remove(major,&operations);IOFree(ring,Frames*2);ring=nullptr;return false;
    }
    __atomic_store_n(&available,1,__ATOMIC_RELEASE);return true;
}
static void push(const int16_t *samples,uint32_t count) {
    if(!__atomic_load_n(&wanted,__ATOMIC_ACQUIRE))return;
    uint32_t h=head,t=__atomic_load_n(&tail,__ATOMIC_ACQUIRE),space=Frames-(h-t);
    uint32_t take=count<space?count:space;
    for(unsigned i=0;i<take;++i) {
        int32_t sample=samples[i];ring[(h+i)&(Frames-1)]=int16_t(sample);
        uint32_t magnitude=sample<0?-sample:sample;
        if(magnitude>peak)peak=magnitude;nonzero+=sample!=0;
    }
    received+=take;dropped+=count-take;__atomic_store_n(&head,h+take,__ATOMIC_RELEASE);
}
static bool requested() {return __atomic_load_n(&wanted,__ATOMIC_ACQUIRE)!=0;}
static void offline() {__atomic_store_n(&available,0,__ATOMIC_RELEASE);__atomic_store_n(&wanted,0,__ATOMIC_RELEASE);}
}
