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
int *__error(void){return &test_errno;}
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
    assert(event>=96&&event<=115);++marks;++seen[event];
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
    assert(install_sites(sites,2)==5&&slots[0]==33&&slots[512]==44&&protect_calls==2&&restore_calls==2);free(slots);
    assert(nabu_ca_frame_trace_install(sink)==0);process="backboardd";installation=0;test_errno=13;
    assert(nabu_ca_frame_trace_install(sink)==0&&test_errno==13);
    printf("PASS: production wrappers preserve raw x0, exact arguments, errno, state; bounded pages/queues/samples; UUID and all-slot validation; COW failure rollback; %u markers\n",marks);
    return 0;
}
