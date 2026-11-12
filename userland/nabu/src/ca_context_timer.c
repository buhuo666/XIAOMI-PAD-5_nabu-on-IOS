#include "ca_context_timer.h"
#include <stddef.h>
#include <stdint.h>

/* 20F66 Server::set_next_update(double, Render::NextUpdateTime): this in x0,
 * last in d0 and the 24-byte by-value aggregate indirectly in x1 on arm64.
 * Use the real aggregate ABI so each original receives its own writable copy.
 * All recovered call sites ignore the method's result (C++ void). */
struct next_update_time { double time; uint64_t reasons, flags; };
_Static_assert(sizeof(struct next_update_time)==24, "20F66 NextUpdateTime ABI");
_Static_assert(offsetof(struct next_update_time,flags)==16, "20F66 flags offset");
typedef void (*set_next_fn)(void *,double,struct next_update_time);
typedef void (*server_call_fn)(void *);
typedef uint32_t (*display_value_fn)(void *);

extern const char *getprogname(void);
extern char *getenv(const char *);
extern int *__error(void);
extern uint32_t _dyld_image_count(void);
extern const char *_dyld_get_image_name(uint32_t);
extern const void *_dyld_get_image_header(uint32_t);
extern intptr_t _dyld_get_image_vmaddr_slide(uint32_t);
extern int getpagesize(void);
extern uint32_t mach_task_self_;
extern int32_t vm_region_64(uint32_t,uint64_t *,uint64_t *,int32_t,
                            int32_t *,uint32_t *,uint32_t *);
extern int32_t vm_protect(uint32_t,uint64_t,uint64_t,int32_t,int32_t);
extern int32_t mach_port_deallocate(uint32_t,uint32_t);

static set_next_fn original_next,base_next;
static server_call_fn server_lock,server_unlock,enable_vsync;
static int installation,installation_result,active;

static uint32_t word(const void *base,size_t offset)
{ return *(const volatile uint32_t *)((const unsigned char *)base+offset); }
static uint8_t byte(const void *base,size_t offset)
{ return *((const volatile uint8_t *)base+offset); }
static void *pointer(const void *base,size_t offset)
{ return *(void *const volatile *)((const unsigned char *)base+offset); }
static display_value_fn display_method(void *display,size_t offset)
{ return (display_value_fn)pointer(pointer(display,0),offset); }
static int same(const char *a,const char *b)
{
    if(!a||!b)return 0;
    while(*a&&*a==*b){++a;++b;}
    return *a==*b;
}

static void context_next(void *server,double last,struct next_update_time next)
{
    /* context_changed supplies {0,4,4} and last=0 for ordinary ready commits
     * (0x188246fac..0x188246fd0). Do not move finite future deadlines to the
     * generic timer: their firing could outlive three physical keepalive ticks.
     * Comparisons include -0, matching the original base method; arguments are
     * forwarded with their original bits, including NaNs on the fallback. */
    const int saved=*__error();
    struct next_update_time copy=next;
    if(last==0.0&&next.time==0.0){
        void *mutex=(unsigned char *)server+0x178;
        server_lock(mutex);
        void *display=pointer(server,0x60);
        if(display_method(display,0xb8)(display)&&
           (byte(server,0x30d)&2)&&pointer(server,0x268)){
            /* Original IOMFB keepalive, under its original mutex. The enable
             * routine owns +0x1b8 and physical VSync registration. Preserve the
             * exact uint32_t three-times interval, including its wrap behavior. */
            if(!word(server,0x308))enable_vsync(server);
            display=pointer(server,0x60);
            uint32_t interval=display_method(display,0x2e0)(display);
            *(volatile uint32_t *)((unsigned char *)server+0x308)=interval*UINT32_C(3);
            /* Keep the original fallback's lock order: +178 -> schedule's
             * callback lock. Base shutdown removes pending callbacks under
             * that same callback lock. Unlocking before schedule would add a
             * new cancellation/requeue window absent from 0x188478158. */
            *__error()=saved;
            base_next(server,last,copy);
            const int result_errno=*__error();
            server_unlock(mutex);
            *__error()=result_errno;
            return;
        }
        server_unlock(mutex);
    }
    /* Base mutates its by-value aggregate when time=0. The explicit local copy
     * and by-value call preserve all 24 caller bytes. No custom clocks, target
     * writes, App callback shifts, surface leases or VSync deadlines here. */
    *__error()=saved;
    original_next(server,last,copy);
}

static int uuid_matches(const void *image,const unsigned char expected[16])
{
    if(!image||word(image,0)!=0xfeedfacf)return 0;
    uint32_t commands=word(image,16),bytes=word(image,20);size_t offset=32;
    if(bytes>65536||commands>2048)return 0;
    for(uint32_t i=0;i<commands;++i){
        if(offset+8>32+(size_t)bytes)return 0;
        uint32_t command=word(image,offset),size=word(image,offset+4);
        if(size<8||offset+size>32+(size_t)bytes)return 0;
        if(command==27&&size==24){
            for(unsigned j=0;j<16;++j)
                if(*((const unsigned char *)image+offset+8+j)!=expected[j])return 0;
            return 1;
        }
        offset+=size;
    }
    return 0;
}
static int quartzcore_slide(intptr_t *slide)
{
    static const unsigned char uuid[16]={0xdc,0x2d,0xd4,0xc1,0x78,0x66,0x34,0x43,
                                         0x80,0x50,0xfc,0x91,0x5a,0x02,0x04,0xc1};
    for(uint32_t i=0;i<_dyld_image_count();++i)
        if(same(_dyld_get_image_name(i),"/System/Library/Frameworks/QuartzCore.framework/QuartzCore")&&
           uuid_matches(_dyld_get_image_header(i),uuid)){
            *slide=_dyld_get_image_vmaddr_slide(i);return 1;
        }
    return 0;
}
struct site { uintptr_t address,target,replacement; };
struct page_change { uint64_t address;int32_t protection; };
enum { ContextTimerSlotCount=2 };

/* Both slots are validated before any write. COW only data pages; keep the
 * original protections per page. The constructor and all originals remain
 * loaded even if the final protection restore returns an error. */
static int install_sites(const struct site sites[ContextTimerSlotCount])
{
    struct page_change changed[ContextTimerSlotCount];unsigned pages=0;
    uint64_t page_size=(uint64_t)getpagesize();
    if(!page_size||(page_size&(page_size-1)))return -2;
    for(unsigned i=0;i<ContextTimerSlotCount;++i)
        if(__atomic_load_n((uintptr_t *)sites[i].address,__ATOMIC_ACQUIRE)!=sites[i].target)return -3;
    for(unsigned i=0;i<ContextTimerSlotCount;++i){
        uint64_t page=sites[i].address&~(page_size-1);unsigned j=0;
        while(j<pages&&changed[j].address!=page)++j;
        if(j<pages)continue;
        uint64_t start=page,length=0;int32_t info[9]={0};uint32_t words=9,object=0;
        int32_t result=vm_region_64(mach_task_self_,&start,&length,9,info,&words,&object);
        if(object)mach_port_deallocate(mach_task_self_,object);
        if(result||words<1||start>page||page+page_size>start+length||!(info[0]&1)||(info[0]&4))goto undo;
        if(vm_protect(mach_task_self_,page,page_size,0,info[0]|2|16))goto undo;
        changed[pages++]=(struct page_change){page,info[0]};
    }
    for(unsigned i=0;i<ContextTimerSlotCount;++i)
        __atomic_store_n((uintptr_t *)sites[i].address,sites[i].replacement,__ATOMIC_RELEASE);
    __atomic_store_n(&active,1,__ATOMIC_RELEASE);
    int result=1;
    for(unsigned i=0;i<pages;++i)
        if(vm_protect(mach_task_self_,changed[i].address,page_size,0,changed[i].protection))result=-5;
    return result;
undo:
    for(unsigned i=0;i<pages;++i)
        (void)vm_protect(mach_task_self_,changed[i].address,page_size,0,changed[i].protection);
    return -4;
}
int nabu_ca_context_timer_active(void)
{ return __atomic_load_n(&active,__ATOMIC_ACQUIRE); }
int nabu_ca_context_timer_install(void)
{
    const int saved=*__error();
    if(!same(getenv("NABU_CA_CONTEXT_TIMER"),"1")||!same(getprogname(),"backboardd")){
        *__error()=saved;return 0;
    }
    int expected=0;
    if(!__atomic_compare_exchange_n(&installation,&expected,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)){
        int result=expected==2?installation_result:-1;
        *__error()=saved;return result;
    }
    intptr_t qc=0;int result=0;
    if(quartzcore_slide(&qc)){
        original_next=(set_next_fn)(uintptr_t)(qc+UINT64_C(0x188478040));
        base_next=(set_next_fn)(uintptr_t)(qc+UINT64_C(0x18846bbc8));
        server_lock=(server_call_fn)(uintptr_t)(qc+UINT64_C(0x1884c9ec0));
        server_unlock=(server_call_fn)(uintptr_t)(qc+UINT64_C(0x1884c9ed8));
        enable_vsync=(server_call_fn)(uintptr_t)(qc+UINT64_C(0x1882f3218));
        const struct site sites[ContextTimerSlotCount]={
            {(uintptr_t)(qc+UINT64_C(0x1d57ddb48)),(uintptr_t)original_next,(uintptr_t)context_next},
            {(uintptr_t)(qc+UINT64_C(0x1d57edd18)),(uintptr_t)original_next,(uintptr_t)context_next}
        };
        result=install_sites(sites);
    }
    installation_result=result;
    __atomic_store_n(&installation,2,__ATOMIC_RELEASE);
    *__error()=saved;return result;
}
