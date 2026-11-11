#include "ca_frame_trace.h"
#include <stddef.h>
#include <stdint.h>

/* Deliberately independent of SDK C++ private headers. Scalar signatures and
 * offsets below are pinned to the original 20F66 UUIDs and recovered dispatch
 * tables. uint64_t preserves finish_update/begin_update's raw x0 result. */
typedef uintptr_t (*display_update_fn)(void *, void *, uint32_t);
typedef uintptr_t (*display_begin_fn)(void *, void *);
typedef uint32_t (*display_can_fn)(void *, uint32_t);
typedef int32_t (*swap_end_fn)(void *);
typedef int32_t (*swap_wait_fn)(void *, uint32_t, uint32_t);

extern const char *getprogname(void);
extern int *__error(void);
extern uint32_t _dyld_image_count(void);
extern const char *_dyld_get_image_name(uint32_t);
extern const void *_dyld_get_image_header(uint32_t);
extern intptr_t _dyld_get_image_vmaddr_slide(uint32_t);
extern int getpagesize(void);
extern uint32_t mach_task_self_;
extern int32_t vm_region_64(uint32_t, uint64_t *, uint64_t *, int32_t,
                            int32_t *, uint32_t *, uint32_t *);
extern int32_t vm_protect(uint32_t, uint64_t, uint64_t, int32_t, int32_t);
extern int32_t mach_port_deallocate(uint32_t, uint32_t);

static nabu_ca_trace_sink trace_sink;
static display_update_fn original_finish;
static display_begin_fn original_begin;
static display_can_fn original_can;
static swap_end_fn original_swap;
static swap_wait_fn original_wait;
static uint32_t capabilities;
static int installation;

static uint32_t word(const void *base, size_t offset)
{
    return *(const volatile uint32_t *)((const unsigned char *)base+offset);
}
static uint64_t wide(const void *base, size_t offset)
{
    return word(base,offset)|((uint64_t)word(base,offset+4)<<32);
}
static void *pointer(const void *base, size_t offset)
{ return (void *)(uintptr_t)wide(base,offset); }
static uint64_t pair(uint32_t low, uint32_t high)
{ return low|((uint64_t)high<<32); }
static int same(const char *a,const char *b)
{
    if(!a||!b)return 0;
    while(*a&&*a==*b){++a;++b;}
    return *a==*b;
}
static void mark(uint32_t event, const void *identity, uint64_t a,uint64_t b,uint64_t c)
{
    /* The sink may use a syscall: do not let its errno affect an original call
     * or the caller's observed errno. No logging, allocation or clock calls. */
    int saved=*__error();
    trace_sink(event,(uintptr_t)identity,a,b,c);
    *__error()=saved;
}

/* These are raw, bounded observations, not coherent state transitions. The
 * original call owns Display/Update and the tree's object references. We read
 * no object after the original returns and retain no object or surface. */
static void pages(void *display,uint32_t phase)
{
    uint32_t count=word(display,0x360);
    for(uint32_t i=0;i<count&&i<3;++i)
        mark(NabuCaPage,display,pair(i|(phase<<8),word(display,0x3a8+i*0x30)),
             pair(word(display,0x3c0+i*0x30),word(display,0x3d0+i*0x30)),
             wide(display,0x3b8+i*0x30));
}
static void queue_snapshot(void *queue,void *update)
{
    void *shmem=pointer(queue,0x10);
    if(!shmem)return;
    void *shared=pointer(shmem,0x18);
    if(!shared)return;
    uint32_t count=word(queue,0x88);
    mark(NabuCaQueue,queue,(uintptr_t)shared,
         pair(word(update,0xe0),word(queue,0x94)),pair(word(shared,0x0c),count));
    mark(NabuCaQueueWords,shared,pair(word(shared,0x08),word(shared,0x20)),
         pair(word(shared,0x14),word(shared,0x24)),pair(word(shared,0x28),word(queue,0x98)));
    for(uint32_t i=0;i<count&&i<4;++i){
        const unsigned char *sample=(const unsigned char *)shared+0x188+i*0x88;
        if(!word(sample,0x44))continue;
        mark(NabuCaSample,shared,pair(i,word(sample,0x38)),
             pair(word(sample,0x3c),word(sample,0x40)),
             pair(word(sample,0x58),word(sample,0x5c)));
        mark(NabuCaSampleTimes,shared,i,wide(sample,0),wide(sample,0x28));
        mark(NabuCaSampleWords,shared,pair(i,word(sample,0x44)),
             pair(word(sample,0x54),word(sample,0x60)),
             pair(word(sample,0x64),word(sample,0x48)));
    }
    if(count>4)mark(NabuCaSnapshotLimit,queue,1,count,4);
}
static void update_snapshot(void *update)
{
    if(!update)return;
    mark(NabuCaUpdateTimes,update,wide(update,0x48),wide(update,0x68),wide(update,0x70));
    void *end=(unsigned char *)update+0x2e8;
    void *node=pointer(update,0x2e0);
    unsigned objects=0,queues=0,steps=0;
    while(node&&node!=end&&objects<8&&queues<2&&steps<32){
        ++objects;
        void *object=pointer(node,0x20);
        if(object&&*((const volatile unsigned char *)object+0x0c)==0x1a){
            queue_snapshot(object,update);++queues;
        }
        void *right=pointer(node,8);
        if(right){
            node=right;
            while(pointer(node,0)&&steps<32){node=pointer(node,0);++steps;}
        }else{
            void *parent=pointer(node,0x10);
            while(parent!=end&&node!=pointer(parent,0)&&steps<32){
                node=parent;parent=pointer(parent,0x10);++steps;
            }
            node=parent;
        }
    }
    if(node&&node!=end)mark(NabuCaSnapshotLimit,update,2,pair(objects,queues),steps);
}

static int32_t traced_wait(void *fb,uint32_t swap,uint32_t flags)
{
    uintptr_t caller=(uintptr_t)__builtin_return_address(0);
    mark(NabuCaWaitEnter,fb,pair(swap,flags),caller,0);
    int32_t result=original_wait(fb,swap,flags);
    mark(NabuCaWaitLeave,fb,pair(swap,flags),(uint32_t)result,caller);
    return result;
}
static int32_t traced_swap(void *fb)
{
    /* _kern_SwapEnd sends exactly fb+0x18, size0x46c, selector5. Capture that
     * same request before calling it; never inspect it after the return. */
    const unsigned char *request=(const unsigned char *)fb+0x18;
    uint32_t swap=word(request,0x50);
    uintptr_t caller=(uintptr_t)__builtin_return_address(0);
    mark(NabuCaSwapEnter,fb,swap,wide(request,0),caller);
    mark(NabuCaSwapLayers,fb,pair(word(request,0x54),word(request,0x58)),
         pair(word(request,0x5c),word(request,0x60)),
         pair(word(request,0x104),word(request,0x108)));
    int32_t result=original_swap(fb);
    mark(NabuCaSwapLeave,fb,swap,(uint32_t)result,caller);
    return result;
}
static void observe_framebuffer(void *display)
{
    if(!(capabilities&NabuCaFramebufferHooksSupported))return;
    void *fb=pointer(display,0x318);
    if(!fb)return;
    uintptr_t *swap=(uintptr_t *)((unsigned char *)fb+0x730);
    uintptr_t *wait=(uintptr_t *)((unsigned char *)fb+0x750);
    uintptr_t s=__atomic_load_n(swap,__ATOMIC_ACQUIRE);
    uintptr_t w=__atomic_load_n(wait,__ATOMIC_ACQUIRE);
    if(s==(uintptr_t)traced_swap&&w==(uintptr_t)traced_wait)return;
    /* These are per-handle writable dispatch entries, not cache instructions.
     * Do not overwrite an unknown backend or another observer's function. */
    if((s!=(uintptr_t)original_swap&&s!=(uintptr_t)traced_swap)||
       (w!=(uintptr_t)original_wait&&w!=(uintptr_t)traced_wait)){
        mark(NabuCaFramebufferHooks,display,(uintptr_t)fb,s,w);return;
    }
    uintptr_t expected=(uintptr_t)original_swap;
    __atomic_compare_exchange_n(swap,&expected,(uintptr_t)traced_swap,0,__ATOMIC_RELEASE,__ATOMIC_RELAXED);
    expected=(uintptr_t)original_wait;
    __atomic_compare_exchange_n(wait,&expected,(uintptr_t)traced_wait,0,__ATOMIC_RELEASE,__ATOMIC_RELAXED);
    mark(NabuCaFramebufferHooks,display,(uintptr_t)fb,
         __atomic_load_n(swap,__ATOMIC_ACQUIRE),__atomic_load_n(wait,__ATOMIC_ACQUIRE));
}
static uint32_t traced_can(void *display,uint32_t flags)
{
    int saved=*__error();
    observe_framebuffer(display);
    mark(NabuCaCanEnter,display,flags,pair(word(display,0x358),word(display,0x360)),wide(display,0x318));
    pages(display,0);*__error()=saved;
    uint32_t result=original_can(display,flags);
    mark(NabuCaCanLeave,display,result,flags,pair(word(display,0x358),word(display,0x438)));
    return result;
}
static uintptr_t traced_begin(void *display,void *update)
{
    int saved=*__error();observe_framebuffer(display);
    uint32_t frame=update?word(update,0xe0):0;
    mark(NabuCaBeginEnter,update,(uintptr_t)display,frame,wide(display,0x318));
    *__error()=saved;
    uintptr_t result=original_begin(display,update);
    mark(NabuCaBeginLeave,update,(uintptr_t)display,frame,result);
    return result;
}
static uintptr_t traced_finish(void *display,void *update,uint32_t flags)
{
    int saved=*__error();observe_framebuffer(display);
    uint32_t frame=update?word(update,0xe0):0;
    mark(NabuCaFinishEnter,update,(uintptr_t)display,pair(frame,flags),wide(display,0x318));
    pages(display,1);update_snapshot(update);*__error()=saved;
    uintptr_t result=original_finish(display,update,flags);
    mark(NabuCaFinishLeave,update,(uintptr_t)display,pair(frame,flags),result);
    return result;
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
static int image_slide(const char *name,const unsigned char uuid[16],intptr_t *slide)
{
    for(uint32_t i=0;i<_dyld_image_count();++i)
        if(same(_dyld_get_image_name(i),name)&&uuid_matches(_dyld_get_image_header(i),uuid)){
            *slide=_dyld_get_image_vmaddr_slide(i);return 1;
        }
    return 0;
}
struct site {uintptr_t address,target,replacement;};
struct page_change {uint64_t address;int32_t protection;};

/* Validate every slot before any write, then privatize only data pages. The
 * library is process-lifetime; installed wrappers call the original addresses.
 * There is deliberately no restoration/unload race with active render calls. */
static int install_sites(struct site *sites,unsigned count)
{
    struct page_change changed[12];unsigned pages_count=0;
    uint64_t page_size=(uint64_t)getpagesize();
    if(!page_size||(page_size&(page_size-1)))return -2;
    for(unsigned i=0;i<count;++i)
        if(__atomic_load_n((uintptr_t *)sites[i].address,__ATOMIC_ACQUIRE)!=sites[i].target)return -3;
    for(unsigned i=0;i<count;++i){
        uint64_t page=sites[i].address&~(page_size-1);unsigned j=0;
        while(j<pages_count&&changed[j].address!=page)++j;
        if(j<pages_count)continue;
        uint64_t start=page,length=0;int32_t info[9]={0};uint32_t words=9,object=0;
        int32_t result=vm_region_64(mach_task_self_,&start,&length,9,info,&words,&object);
        if(object)mach_port_deallocate(mach_task_self_,object);
        if(result||words<1||start>page||page+page_size>start+length||!(info[0]&1)||(info[0]&4))goto undo;
        if(vm_protect(mach_task_self_,page,page_size,0,info[0]|2|16))goto undo;
        changed[pages_count++]=(struct page_change){page,info[0]};
    }
    for(unsigned i=0;i<count;++i)__atomic_store_n((uintptr_t *)sites[i].address,sites[i].replacement,__ATOMIC_RELEASE);
    {
        int result=(int)(NabuCaDisplayHooks|NabuCaSelectedQueueSnapshot);
        for(unsigned i=0;i<pages_count;++i)
            if(vm_protect(mach_task_self_,changed[i].address,page_size,0,changed[i].protection))result=-5;
        return result;
    }
undo:
    for(unsigned i=0;i<pages_count;++i)
        (void)vm_protect(mach_task_self_,changed[i].address,page_size,0,changed[i].protection);
    return -4;
}
uint32_t nabu_ca_frame_trace_capabilities(void)
{return __atomic_load_n(&capabilities,__ATOMIC_ACQUIRE);}
int nabu_ca_frame_trace_install(nabu_ca_trace_sink sink)
{
    int saved=*__error();
    if(!sink||!same(getprogname(),"backboardd"))return 0;
    int expected=0;
    if(!__atomic_compare_exchange_n(&installation,&expected,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))
        return __atomic_load_n(&installation,__ATOMIC_ACQUIRE)==2?(int)capabilities:-1;
    static const unsigned char qc_uuid[16]={0xdc,0x2d,0xd4,0xc1,0x78,0x66,0x34,0x43,0x80,0x50,0xfc,0x91,0x5a,0x02,0x04,0xc1};
    static const unsigned char fb_uuid[16]={0xa8,0x51,0x78,0x01,0x7f,0x27,0x36,0x41,0xb9,0x77,0xc5,0x83,0x1e,0x37,0xfe,0x9f};
    intptr_t qc=0,fb=0;
    if(!image_slide("/System/Library/Frameworks/QuartzCore.framework/QuartzCore",qc_uuid,&qc)){
        __atomic_store_n(&installation,3,__ATOMIC_RELEASE);*__error()=saved;return 0;
    }
    int have_fb=image_slide("/System/Library/PrivateFrameworks/IOMobileFramebuffer.framework/IOMobileFramebuffer",fb_uuid,&fb);
    original_can=(display_can_fn)(uintptr_t)(qc+0x18829cd88ULL);
    original_begin=(display_begin_fn)(uintptr_t)(qc+0x18825dda4ULL);
    original_finish=(display_update_fn)(uintptr_t)(qc+0x188248568ULL);
    if(have_fb){
        original_swap=(swap_end_fn)(uintptr_t)(fb+0x1af12c530ULL);
        original_wait=(swap_wait_fn)(uintptr_t)(fb+0x1af12c648ULL);
    }
    static const uintptr_t tables[]={0x1d57ddc60ULL,0x1d57de420ULL,0x1d57ebd00ULL,0x1d57ec520ULL};
    struct site sites[12];unsigned n=0;
    for(unsigned i=0;i<4;++i){
        uintptr_t table=tables[i]+qc+16;
        sites[n++]=(struct site){table+0x140,(uintptr_t)original_can,(uintptr_t)traced_can};
        sites[n++]=(struct site){table+0x170,(uintptr_t)original_begin,(uintptr_t)traced_begin};
        sites[n++]=(struct site){table+0x178,(uintptr_t)original_finish,(uintptr_t)traced_finish};
    }
    trace_sink=sink;
    capabilities=have_fb?NabuCaFramebufferHooksSupported:0;
    int result=install_sites(sites,n);
    if(result>0){capabilities|=(uint32_t)result;__atomic_store_n(&installation,2,__ATOMIC_RELEASE);result=(int)capabilities;}
    else {__atomic_store_n(&installation,3,__ATOMIC_RELEASE);/* -5 leaves installed transparent wrappers alive. */}
    *__error()=saved;return result;
}
