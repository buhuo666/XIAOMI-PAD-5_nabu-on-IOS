#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "../src/ca_frame_trace.c"

static int test_errno;
static unsigned original_calls,marks,seen[128],protect_calls,restore_calls;
static uint64_t last[128][4];
static const char *process="test";
static uintptr_t raw_return=UINT64_C(0xfedcba9876543210);
static uint32_t can_return;
static int fail_page;
static void *expected_server,*expected_update;
static uint32_t *expected_flags;
static unsigned render_backend,render_order;
static void *expected_context,*expected_surface;
static uint32_t expected_collect_all;
static unsigned context_entry,context_order;
static unsigned immediate_order,clock_calls;
static void *expected_immediate,*expected_immediate_display;
static uint64_t test_clock=UINT64_C(0x123456789abcdef0);
int *__error(void){return &test_errno;}
uint64_t mach_absolute_time(void){++clock_calls;test_errno=88;return test_clock;}
const char *getprogname(void){return process;}
uint32_t _dyld_image_count(void){return 0;}
const char *_dyld_get_image_name(uint32_t i){(void)i;return 0;}
const void *_dyld_get_image_header(uint32_t i){(void)i;return 0;}
intptr_t _dyld_get_image_vmaddr_slide(uint32_t i){(void)i;return 0;}
int getpagesize(void){return 4096;}
uint32_t mach_task_self_=43;
int32_t vm_region_64(uint32_t task,uint64_t *address,uint64_t *size,int32_t flavor,
                    int32_t *info,uint32_t *count,uint32_t *object)
{
    assert(task==43&&flavor==9&&*count==9);
    *address&=~UINT64_C(4095);*size=4096;info[0]=1;*object=0;return 0;
}
int32_t vm_protect(uint32_t task,uint64_t a,uint64_t size,int32_t maximum,int32_t p)
{
    assert(task==43&&a%4096==0&&size==4096&&!maximum);
    if(p==(1|2|16)){++protect_calls;if(fail_page&&(int)protect_calls==fail_page)return 5;}
    else{assert(p==1);++restore_calls;}return 0;
}
int32_t mach_port_deallocate(uint32_t task,uint32_t port){(void)task;(void)port;return 0;}
static void store32(void *b,size_t o,uint32_t v){memcpy((unsigned char *)b+o,&v,4);}
static void store64(void *b,size_t o,uint64_t v){memcpy((unsigned char *)b+o,&v,8);}
static void ptr(void *b,size_t o,const void *p){store64(b,o,(uintptr_t)p);}
static void sink(uint32_t event,uint64_t id,uint64_t a,uint64_t b,uint64_t c)
{
    assert(event>=96&&event<=126);++marks;++seen[event];
    if(event==NabuCaRenderEnter){assert(render_order==0);render_order=1;}
    if(event==NabuCaServerState){assert(render_order==1);render_order=2;}
    if(event==NabuCaRenderLeave){assert(render_order==3);render_order=0;}
    if(event==NabuCaCollectEnter||event==NabuCaMakeBufferEnter){
        assert(context_order==0);context_order=1;context_entry=event;
    }
    if(event==NabuCaCollectLeave||event==NabuCaMakeBufferLeave){
        assert(context_order==2&&event==context_entry+1);context_order=0;
    }
    if(event>=NabuCaImmediateEnter&&event<=NabuCaImmediateConfig){
        assert(immediate_order==event-NabuCaImmediateEnter);++immediate_order;
    }
    if(event==NabuCaImmediateLeave){assert(immediate_order==4);immediate_order=0;}
    last[event][0]=id;last[event][1]=a;last[event][2]=b;last[event][3]=c;
    test_errno=99;
}
static uintptr_t original_f(void *d,void *u,uint32_t flags)
{assert(d&&u&&flags==7&&test_errno==13);++original_calls;test_errno=47;return raw_return;}
static uintptr_t original_b(void *d,void *u)
{assert(d&&u&&test_errno==13);++original_calls;test_errno=47;return raw_return;}
static uint32_t original_c(void *d,uint32_t flags)
{assert(d&&flags==3&&test_errno==13);++original_calls;test_errno=47;return can_return;}
static int32_t original_w(void *d,uint32_t swap,uint32_t flags)
{assert(d&&swap==91&&flags==0x80000000u&&test_errno==13);++original_calls;test_errno=47;return (int32_t)0xe00002d5u;}
static int32_t original_s(void *d)
{assert(d&&test_errno==13);++original_calls;test_errno=47;return (int32_t)0xe00002c7u;}
static uintptr_t original_r(void *s,void *u,uint32_t *flags,unsigned backend)
{
    assert(s==expected_server&&u==expected_update&&flags==expected_flags);
    assert(*flags==7&&test_errno==13&&render_order==2&&render_backend==backend);
    ++original_calls;render_order=3;
    /* A post-call context dereference would fault. The result marker must
     * also retain the entry frame/flags, while the caller sees these changes. */
    store64(s,0xc0,1);store32(u,0xe0,88);*flags=0x13579bdfu;
    test_errno=47;return raw_return;
}
static uintptr_t original_ri(void *s,void *u,uint32_t *flags)
{return original_r(s,u,flags,1);}
static uintptr_t original_re(void *s,void *u,uint32_t *flags)
{return original_r(s,u,flags,2);}
static void check_render(int eagl,int contexts,int matching_table)
{
    /* A base instance stops at c8; ASan catches any accidental +318 read. */
    size_t server_bytes=eagl&&matching_table?0x320:0xc8;
    void *server=calloc(1,server_bytes);assert(server);
    uint64_t update[0xe8/8]={0};uint32_t flags=7;
    uint64_t sw[]={UINT64_C(0x1d57e5618)},hardware[]={UINT64_C(0x1d57e3e48)};
    uintptr_t vptr=eagl&&matching_table?eagl_vtable:UINT64_C(0x1d57dda98);
    store64(server,0,vptr);store32(update,0xe0,77);
    if(contexts)ptr(server,0xc0,sw);
    if(eagl&&matching_table&&contexts)ptr(server,0x318,hardware);
    expected_server=server;expected_update=update;expected_flags=&flags;render_backend=eagl?2:1;
    server_render_fn wrapper=eagl?traced_eagl_render:traced_iomfb_render;
    test_errno=13;assert(wrapper(server,update,&flags)==raw_return&&test_errno==47);
    assert(flags==0x13579bdfu&&word(update,0xe0)==88&&wide(server,0xc0)==1);
    assert(last[NabuCaRenderEnter][0]==(uintptr_t)update&&last[NabuCaRenderEnter][1]==(uintptr_t)server);
    assert(last[NabuCaRenderEnter][2]==pair(77,7));
    assert(last[NabuCaRenderEnter][3]==(uintptr_t)(eagl?original_re:original_ri));
    assert(last[NabuCaRenderLeave][0]==(uintptr_t)update&&last[NabuCaRenderLeave][1]==(uintptr_t)server);
    assert(last[NabuCaRenderLeave][2]==pair(77,7)&&last[NabuCaRenderLeave][3]==raw_return);
    assert(last[NabuCaServerState][0]==(uintptr_t)server&&last[NabuCaServerState][1]==vptr);
    assert(last[NabuCaServerState][2]==(contexts?sw[0]:0));
    assert(last[NabuCaServerState][3]==(eagl&&matching_table&&contexts?hardware[0]:0));
    assert(render_order==0);free(server);
}
static uintptr_t original_mc(void *context,uint32_t all)
{
    assert(context==expected_context&&all==expected_collect_all&&test_errno==13);
    assert(context_order==1&&context_entry==NabuCaCollectEnter);
    ++original_calls;context_order=2;
    free(context); /* ASan verifies that the leave path does not reread context. */
    test_errno=47;return raw_return;
}
static uintptr_t original_mb(void *context,void *surface)
{
    assert(context==expected_context&&surface==expected_surface&&test_errno==13);
    assert(context_order==1&&context_entry==NabuCaMakeBufferEnter);
    ++original_calls;context_order=2;
    free(context);
    test_errno=47;return raw_return;
}
static void check_context_call(int make_buffer,int nonzero)
{
    uint64_t *context=malloc(sizeof(*context));assert(context);
    const uint64_t vptr=UINT64_C(0x1d57e3e48);*context=vptr;
    const uintptr_t identity=(uintptr_t)context;
    expected_context=context;expected_collect_all=(uint32_t)nonzero;
    /* This opaque argument is deliberately unreadable. Only the original
     * implementation owns its interpretation; null is the unbind case. */
    expected_surface=nonzero?(void *)(uintptr_t)UINT64_C(0xfedcba9876543000):0;
    const uint64_t argument=make_buffer?(uintptr_t)expected_surface:expected_collect_all;
    const uint32_t event=make_buffer?NabuCaMakeBufferEnter:NabuCaCollectEnter;
    test_errno=13;
    uintptr_t result=make_buffer?traced_make_buffer(context,expected_surface):traced_collect(context,expected_collect_all);
    assert(result==raw_return&&test_errno==47&&context_order==0);
    assert(last[event][0]==identity&&last[event][1]==argument&&last[event][2]==vptr);
    assert(last[event][3]==(make_buffer?(uintptr_t)original_mb:(uintptr_t)original_mc));
    assert(last[event+1][0]==identity&&last[event+1][1]==argument&&last[event+1][2]==vptr);
    assert(last[event+1][3]==raw_return);
}
static uintptr_t original_im(void *server)
{
    assert(server==expected_immediate&&test_errno==13&&immediate_order==3);
    ++original_calls;immediate_order=4;
    /* Even the server may not be reread on leave. This also makes any
     * post-call display/global traversal visible to the sanitizers. */
    free(expected_immediate_display);free(server);
    test_errno=47;return raw_return;
}
static void check_immediate(int eagl)
{
    void *server=calloc(1,0x310),*display=calloc(1,0x238);assert(server&&display);
    const uint64_t target=UINT64_C(0x40a23456789abcde);
    const uint64_t immediate_target=UINT64_C(0x1122334455667788);
    const uint64_t native_time=UINT64_C(0x9988776655443322);
    const uint64_t mode=UINT64_C(0xabcdef0187654321);
    const uint64_t runloop=UINT64_C(0xfedc012398765432);
    uint64_t once=eagl?UINT64_MAX:0;
    uint8_t supported=0x12,forced=0x34,disabled=0x56;
    ptr(server,0,eagl?(void *)eagl_vtable:(void *)(uintptr_t)UINT64_C(0x1d57dda98));
    ptr(server,0x60,display);store64(server,0x118,target);store64(server,0x2d0,immediate_target);
    store64(server,0x2e0,native_time);store64(server,0x258,runloop);
    store32(server,0x160,0xbbaa9182u);*((unsigned char *)server+0x30d)=0xa5;
    store32(display,0x220,0x89abcdefu);*((unsigned char *)display+0x22c)=2;
    store64(display,0x230,mode);
    arbitration_once=&once;arbitration_supported=&supported;arbitration_forced=&forced;low_latency_disabled=&disabled;
    expected_immediate=server;expected_immediate_display=display;
    const uintptr_t identity=(uintptr_t)server;
    const unsigned calls_before=original_calls,clock_before=clock_calls;
    test_errno=13;assert(traced_immediate(server)==raw_return&&test_errno==47);
    assert(original_calls==calls_before+1&&clock_calls==clock_before+1&&immediate_order==0);
    assert(last[NabuCaImmediateEnter][0]==identity&&last[NabuCaImmediateEnter][1]==test_clock);
    assert(last[NabuCaImmediateEnter][2]==target&&last[NabuCaImmediateEnter][3]==immediate_target);
    assert(last[NabuCaImmediateState][0]==identity&&last[NabuCaImmediateState][1]==native_time);
    assert(last[NabuCaImmediateState][2]==pair(0x02a59182u,0x89abcdefu)&&last[NabuCaImmediateState][3]==mode);
    assert(last[NabuCaImmediateConfig][0]==identity&&last[NabuCaImmediateConfig][1]==runloop);
    assert(last[NabuCaImmediateConfig][2]==once&&last[NabuCaImmediateConfig][3]==0x563412u);
    assert(last[NabuCaImmediateLeave][0]==identity&&last[NabuCaImmediateLeave][1]==target);
    assert(last[NabuCaImmediateLeave][2]==immediate_target&&last[NabuCaImmediateLeave][3]==raw_return);
}
static void eighteen_slot_install(void)
{
    uintptr_t *slots=aligned_alloc(4096,18*4096);assert(slots);
    struct site sites[18];
    for(unsigned i=0;i<18;++i){slots[i*512]=i+1;sites[i]=(struct site){(uintptr_t)&slots[i*512],i+1,i+101};}
    sites[17].target=99;protect_calls=restore_calls=0;
    assert(install_sites(sites,18)==-3&&protect_calls==0);sites[17].target=18;
    fail_page=18;protect_calls=restore_calls=0;
    assert(install_sites(sites,18)==-4&&protect_calls==18&&restore_calls==17);
    for(unsigned i=0;i<18;++i)assert(slots[i*512]==i+1);
    fail_page=0;protect_calls=restore_calls=0;
    assert(install_sites(sites,18)==61&&protect_calls==18&&restore_calls==18);
    for(unsigned i=0;i<18;++i)assert(slots[i*512]==i+101);
    free(slots);
}

int main(void)
{
    trace_sink=sink;original_finish=original_f;original_begin=original_b;
    original_can=original_c;original_wait=original_w;original_swap=original_s;
    uint64_t display[0xa00/8]={0},update[0x340/8]={0},fb[0xb20/8]={0};
    uint64_t queue[0xd0/8]={0},shmem[4]={0},shared[(0x188+6*0x88)/8]={0},node[5]={0};
    void *end=(unsigned char *)update+0x2e8;
    ptr(display,0x318,fb);store32(display,0x360,3);store32(display,0x358,2);
    for(unsigned i=0;i<3;++i){store32(display,0x3a8+i*0x30,30+i);store32(display,0x3c0+i*0x30,90+i);}
    ptr(update,0x2e0,node);ptr(update,0x2e8,node);store32(update,0xe0,77);
    ptr(node,0x10,end);ptr(node,0x20,queue);*((unsigned char *)queue+0xc)=0x1a;
    ptr(queue,0x10,shmem);ptr(shmem,0x18,shared);store32(queue,0x88,6);store32(queue,0x94,77);
    store32(shared,0xc,0x24008000);
    for(unsigned i=0;i<6;++i){unsigned char *s=(unsigned char *)shared+0x188+i*0x88;
        store32(s,0x44,1);store32(s,0x38,101+i);store32(s,0x3c,0x11111111);
        store32(s,0x40,200+i);store32(s,0x58,77);store32(s,0x5c,76);
        store64(s,0,UINT64_C(0x4008000000000000));}
    unsigned char update_before[sizeof(update)],queue_before[sizeof(queue)],shared_before[sizeof(shared)];
    memcpy(update_before,update,sizeof(update));memcpy(queue_before,queue,sizeof(queue));memcpy(shared_before,shared,sizeof(shared));
    test_errno=13;assert(traced_finish(display,update,7)==raw_return&&test_errno==47);
    assert(original_calls==1&&seen[NabuCaFinishEnter]==1&&seen[NabuCaFinishLeave]==1);
    assert(seen[NabuCaPage]==3&&seen[NabuCaSample]==4&&seen[NabuCaSnapshotLimit]==1);
    assert(last[NabuCaSample][1]==pair(3,104));
    assert(!memcmp(update_before,update,sizeof(update))&&!memcmp(queue_before,queue,sizeof(queue))&&!memcmp(shared_before,shared,sizeof(shared)));
    test_errno=13;assert(traced_begin(display,update)==raw_return&&test_errno==47);
    for(unsigned i=0;i<2;++i){can_return=i;test_errno=13;assert(traced_can(display,3)==i&&test_errno==47);}
    store32(display,0x360,1000);unsigned pages_before=seen[NabuCaPage];pages(display,1);
    assert(seen[NabuCaPage]-pages_before==3);
    ptr(update,0x2e0,end);update_snapshot(update); /* empty tree */
    ptr(update,0x2e0,node);*((unsigned char *)queue+0xc)=0x19;
    unsigned qbefore=seen[NabuCaQueue];update_snapshot(update);assert(seen[NabuCaQueue]==qbefore);
    *((unsigned char *)queue+0xc)=0x1a;
    test_errno=13;assert(traced_wait(fb,91,0x80000000u)==(int32_t)0xe00002d5u&&test_errno==47);
    assert(last[NabuCaWaitLeave][1]==pair(91,0x80000000u)&&last[NabuCaWaitLeave][2]==0xe00002d5u);
    unsigned char *req=(unsigned char *)fb+0x18;store32(req,0x50,91);store64(req,0,123456);
    store32(req,0x54,101);store32(req,0x58,102);store32(req,0x104,7);store32(req,0x108,4);
    unsigned char fb_before[sizeof(fb)];memcpy(fb_before,fb,sizeof(fb));
    test_errno=13;assert(traced_swap(fb)==(int32_t)0xe00002c7u&&test_errno==47);
    assert(last[NabuCaSwapEnter][1]==91&&last[NabuCaSwapEnter][2]==123456);
    assert(last[NabuCaSwapLayers][1]==pair(101,102)&&last[NabuCaSwapLayers][3]==pair(7,4));
    assert(!memcmp(fb_before,fb,sizeof(fb)));
    capabilities=NabuCaFramebufferHooksSupported;ptr(fb,0x730,(void *)(uintptr_t)original_s);ptr(fb,0x750,(void *)(uintptr_t)original_w);
    observe_framebuffer(display);assert(pointer(fb,0x730)==(void *)(uintptr_t)traced_swap&&pointer(fb,0x750)==(void *)(uintptr_t)traced_wait);
    unsigned installed=seen[NabuCaFramebufferHooks];observe_framebuffer(display);assert(seen[NabuCaFramebufferHooks]==installed);
    ptr(fb,0x730,(void *)(uintptr_t)0x1234);observe_framebuffer(display);assert(pointer(fb,0x730)==(void *)(uintptr_t)0x1234);
    unsigned char image[56]={0};unsigned char uuid[16]={1,2,3};
    store32(image,0,0xfeedfacf);store32(image,16,1);store32(image,20,24);store32(image,32,27);store32(image,36,24);memcpy(image+40,uuid,16);
    assert(uuid_matches(image,uuid));image[40]^=1;assert(!uuid_matches(image,uuid));image[40]^=1;store32(image,36,0);assert(!uuid_matches(image,uuid));
    uintptr_t *slots=aligned_alloc(4096,8192);assert(slots);memset(slots,0,8192);slots[0]=11;slots[512]=22;
    struct site sites[]={{(uintptr_t)&slots[0],11,33},{(uintptr_t)&slots[512],22,44}};
    fail_page=2;protect_calls=restore_calls=0;assert(install_sites(sites,2)==-4&&slots[0]==11&&slots[512]==22&&restore_calls==1);
    fail_page=0;protect_calls=restore_calls=0;sites[1].target=23;assert(install_sites(sites,2)==-3&&protect_calls==0);sites[1].target=22;
    assert(install_sites(sites,2)==61&&slots[0]==33&&slots[512]==44&&protect_calls==2&&restore_calls==2);free(slots);
    original_iomfb_render=original_ri;original_eagl_render=original_re;eagl_vtable=UINT64_C(0x1d57edc68);
    check_render(0,0,0);check_render(0,1,0);check_render(1,0,1);check_render(1,1,1);check_render(1,1,0);
    original_collect=original_mc;original_make_buffer=original_mb;
    check_context_call(0,0);check_context_call(0,1);check_context_call(1,0);check_context_call(1,1);
    original_immediate=original_im;check_immediate(0);check_immediate(1);
    eighteen_slot_install();
    assert(nabu_ca_frame_trace_install(sink)==0);process="backboardd";installation=0;test_errno=13;
    assert(nabu_ca_frame_trace_install(sink)==0&&test_errno==13);
    printf("PASS: production wrappers preserve raw x0, exact arguments, errno, state; bounded pages/queues/samples; IOMFB/EAGL render dispatch and pre-call context state; Metal collect/buffer ABI, null unbind, no reads after return; immediate pre-call fields, clock/errno, no reads after server/display release; UUID and all 18-slot validation; COW failure rollback; %u markers\n",marks);
    return 0;
}
