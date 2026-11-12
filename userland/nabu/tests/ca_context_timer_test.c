#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Test the actual production core, with only its external platform calls
 * replaced. These names avoid interposing the sanitizer runtime's libc calls. */
#define getenv test_getenv
#define getprogname test_getprogname
#define __error test_error
#include "../src/ca_context_timer.c"
#undef getenv
#undef getprogname
#undef __error

static int test_errno;
static char *setting="1";
static const char *process="backboardd";
static uint32_t image_count;
static uint64_t image_header[7];
static intptr_t image_offset;
static unsigned queried_images,regions,prepares,restores,deallocates;
static unsigned fail_prepare,fail_restore,fail_region,executable_region;
static int test_page_size=4096;
static uintptr_t *check_slots[2];
static uintptr_t expected_slot;
static uint64_t changed_pages[2],restored_pages[2];
static int32_t initial_protections[2],restored_protections[2];

int *test_error(void){return &test_errno;}
char *test_getenv(const char *name)
{assert(!strcmp(name,"NABU_CA_CONTEXT_TIMER"));test_errno=90;return setting;}
const char *test_getprogname(void){test_errno=91;return process;}
uint32_t _dyld_image_count(void){++queried_images;test_errno=92;return image_count;}
const char *_dyld_get_image_name(uint32_t i)
{assert(i==0);return "/System/Library/Frameworks/QuartzCore.framework/QuartzCore";}
const void *_dyld_get_image_header(uint32_t i){assert(i==0);return image_header;}
intptr_t _dyld_get_image_vmaddr_slide(uint32_t i){assert(i==0);return image_offset;}
int getpagesize(void){return test_page_size;}
uint32_t mach_task_self_=43;
int32_t vm_region_64(uint32_t task,uint64_t *address,uint64_t *size,int32_t flavor,
                     int32_t *info,uint32_t *count,uint32_t *object)
{
    assert(task==43&&flavor==9&&*count==9);
    ++regions;*size=4096;*object=89;test_errno=93;
    assert(*address%4096==0);
    assert(!check_slots[0]||(*check_slots[0]==expected_slot&&*check_slots[1]==expected_slot));
    if(regions==fail_region)return 5;
    info[0]=regions==executable_region?5:(regions==2?3:1);
    initial_protections[regions-1]=info[0];return 0;
}
int32_t vm_protect(uint32_t task,uint64_t address,uint64_t size,int32_t maximum,int32_t prot)
{
    assert(task==43&&address%4096==0&&size==4096&&!maximum);test_errno=94;
    if(prot&16){
        assert(prot==(1|2|16));
        changed_pages[prepares++]=address;
        assert(!check_slots[0]||(*check_slots[0]==expected_slot&&*check_slots[1]==expected_slot));
        return prepares==fail_prepare?5:0;
    }
    assert(prot==1||prot==3);
    restored_pages[restores]=address;restored_protections[restores++]=prot;
    return restores==fail_restore?5:0;
}
int32_t mach_port_deallocate(uint32_t task,uint32_t port)
{assert(task==43&&port==89);++deallocates;return 0;}

static void store32(void *p,size_t offset,uint32_t value)
{memcpy((unsigned char *)p+offset,&value,sizeof(value));}
static void store64(void *p,size_t offset,uint64_t value)
{memcpy((unsigned char *)p+offset,&value,sizeof(value));}
static void storeptr(void *p,size_t offset,const void *value)
{memcpy((unsigned char *)p+offset,&value,sizeof(value));}
static uint64_t bits(double value){uint64_t v;memcpy(&v,&value,8);return v;}
static double number(uint64_t value){double v;memcpy(&v,&value,8);return v;}

static void *expected_server,*expected_display;
static uint32_t enabled=1,interval=1;
static unsigned locked,lock_calls,unlock_calls,enable_calls,display_calls,interval_calls;
static unsigned base_calls,original_calls,disable_calls;
static int free_on_call;
static double expected_last;
static struct next_update_time expected_next;
static char order[32];
static unsigned order_size;
static void step(char c){assert(order_size<sizeof(order)-1);order[order_size++]=c;order[order_size]=0;}
static void fixture_lock(void *mutex)
{assert(mutex==(unsigned char *)expected_server+0x178&&!locked);locked=1;++lock_calls;step('L');test_errno=95;}
static void fixture_unlock(void *mutex)
{assert(mutex==(unsigned char *)expected_server+0x178&&locked);locked=0;++unlock_calls;step('U');test_errno=96;}
static uint32_t fixture_enabled(void *display)
{assert(display==expected_display&&locked);++display_calls;step('D');test_errno=97;return enabled;}
static uint32_t fixture_interval(void *display)
{assert(display==expected_display&&locked);++interval_calls;step('I');test_errno=98;return interval;}
static void fixture_enable(void *server)
{
    assert(server==expected_server&&locked&&!word(server,0x308));
    ++enable_calls;step('E');test_errno=99;
    /* Original enable owns +0x30c, as recovered at 0x1882f3238..0x1882f3244. */
    *((unsigned char *)server+0x30c)=1;
}
static void check_arguments(void *server,double last,struct next_update_time *next)
{
    assert(server==expected_server&&test_errno==13);
    assert(bits(last)==bits(expected_last)&&!memcmp(next,&expected_next,sizeof(*next)));
    /* Like the recovered base, overwrite all three words of this callee's
     * by-value parameter. Any forwarding of the caller's object is a failure. */
    volatile struct next_update_time *local=next;
    local->time=1234.5;local->reasons=0;local->flags=0;
    if(free_on_call){assert(!locked);free(expected_server);free(expected_display);}
    test_errno=47;
}
static void fixture_base(void *server,double last,struct next_update_time next)
{assert(locked);++base_calls;step('B');check_arguments(server,last,&next);}
static void fixture_original(void *server,double last,struct next_update_time next)
{assert(!locked);++original_calls;step('O');check_arguments(server,last,&next);}

static void reset_calls(void)
{
    locked=lock_calls=unlock_calls=enable_calls=display_calls=interval_calls=0;
    base_calls=original_calls=disable_calls=0;order_size=0;order[0]=0;free_on_call=0;
    original_next=fixture_original;base_next=fixture_base;
    server_lock=fixture_lock;server_unlock=fixture_unlock;enable_vsync=fixture_enable;
}
static void initialize_objects(void *server,void *display,uintptr_t *vtable,
                               uint32_t keepalive,uint8_t mode,int source)
{
    memset(server,0xa5,0x310);memset(display,0x5a,0x238);
    memset(vtable,0,0x2e8);vtable[0xb8/8]=(uintptr_t)fixture_enabled;
    vtable[0x2e0/8]=(uintptr_t)fixture_interval;
    storeptr(server,0x60,display);storeptr(display,0,vtable);
    storeptr(server,0x268,source?server:0);store32(server,0x308,keepalive);
    *((unsigned char *)server+0x30c)=keepalive!=0;
    *((unsigned char *)server+0x30d)=mode;
    store64(server,0x2b0,UINT64_C(0x7ff0000000000000));
    expected_server=server;expected_display=display;
}
static void check_case(uint64_t last_bits,uint64_t next_bits,uint32_t keepalive,
                       uint32_t min_interval,uint32_t display_enabled,uint8_t mode,int source)
{
    uint64_t server[0x310/8],display[0x238/8];uintptr_t table[0x2e8/8];
    reset_calls();enabled=display_enabled;interval=min_interval;
    initialize_objects(server,display,table,keepalive,mode,source);
    unsigned char before[sizeof(server)],display_before[sizeof(display)];
    memcpy(before,server,sizeof(server));memcpy(display_before,display,sizeof(display));
    expected_last=number(last_bits);
    expected_next=(struct next_update_time){number(next_bits),UINT64_C(0x123456789abcdef0),UINT64_C(0xfedcba9876543210)};
    struct next_update_time next=expected_next;
    test_errno=13;context_next(server,expected_last,next);
    assert(test_errno==47&&!memcmp(&next,&expected_next,sizeof(next))&&!locked);
    const int zero=(last_bits<<1)==0&&(next_bits<<1)==0;
    const int selected=zero&&display_enabled&&(mode&2)&&source;
    assert(base_calls==(unsigned)selected&&original_calls==(unsigned)!selected);
    assert(lock_calls==(unsigned)zero&&unlock_calls==(unsigned)zero&&display_calls==(unsigned)zero);
    assert(interval_calls==(unsigned)selected&&enable_calls==(unsigned)(selected&&!keepalive));
    if(selected){
        store32(before,0x308,min_interval*UINT32_C(3));
        if(!keepalive)before[0x30c]=1;
        assert(!strcmp(order,keepalive?"LDIBU":"LDEIBU"));
    }else assert(!strcmp(order,zero?"LDUO":"O"));
    /* Includes +0x118, +0x2b0/+0x2b8/+0x2c0, +0x2d0, physical timestamp,
     * shared timing/display fields and every other byte outside keepalive. */
    assert(!memcmp(before,server,sizeof(server))&&!memcmp(display_before,display,sizeof(display)));
}

/* Recovered native callback idle branch only (0x188231910..0x18823195c):
 * an infinite VSync deadline and nonzero +308 decrement on the real callback;
 * reaching zero disables notifications. This is a lifetime model, not timer
 * execution or proof that the real runloop fires before a physical deadline. */
static void native_idle_tick(void *server)
{
    uint64_t deadline;memcpy(&deadline,(unsigned char *)server+0x2b0,8);
    if((deadline&UINT64_C(0x7fffffffffffffff))==UINT64_C(0x7ff0000000000000)&&word(server,0x308)){
        uint32_t remaining=word(server,0x308)-1;store32(server,0x308,remaining);
        if(!remaining){++disable_calls;*((unsigned char *)server+0x30c)=0;}
    }
}
static void check_keepalive(void)
{
    uint64_t server[0x310/8],display[0x238/8];uintptr_t table[0x2e8/8];
    reset_calls();enabled=1;interval=1;initialize_objects(server,display,table,0,3,1);
    expected_last=0;expected_next=(struct next_update_time){0,4,4};
    test_errno=13;context_next(server,expected_last,expected_next);
    assert(word(server,0x308)==3&&enable_calls==1);
    native_idle_tick(server);native_idle_tick(server);
    assert(word(server,0x308)==1&&!disable_calls);
    order_size=0;test_errno=13;context_next(server,expected_last,expected_next);
    assert(word(server,0x308)==3&&enable_calls==1);
    native_idle_tick(server);native_idle_tick(server);native_idle_tick(server);
    assert(!word(server,0x308)&&disable_calls==1&&!byte(server,0x30c));
    order_size=0;test_errno=13;context_next(server,expected_last,expected_next);
    assert(word(server,0x308)==3&&enable_calls==2&&byte(server,0x30c));
    /* The wrapper leaves an existing future native deadline untouched; its
     * non-idle behavior remains the original callback's responsibility. */
    store64(server,0x2b0,bits(1000));native_idle_tick(server);
    assert(word(server,0x308)==3&&disable_calls==1);
}
static void check_no_post_call_reads(void)
{
    /* The base call still owns the original mutex, which must be unlocked.
     * Only the original-override tail can destroy the object before returning. */
    for(unsigned checked_display=0;checked_display<2;++checked_display){
        void *server=malloc(0x310),*display=malloc(0x238);uintptr_t table[0x2e8/8];
        assert(server&&display);reset_calls();enabled=0;interval=1;
        initialize_objects(server,display,table,0,3,1);
        expected_last=checked_display?0:1;expected_next=(struct next_update_time){0,4,4};free_on_call=1;
        test_errno=13;context_next(server,expected_last,expected_next);assert(test_errno==47);
        assert(original_calls==1&&!base_calls&&lock_calls==checked_display&&unlock_calls==checked_display);
    }
}

static void reset_install(void)
{
    installation=installation_result=active=0;
    queried_images=regions=prepares=restores=deallocates=0;
    fail_prepare=fail_restore=fail_region=executable_region=0;test_page_size=4096;
    setting="1";process="backboardd";image_count=1;
    memset(image_header,0,sizeof(image_header));store32(image_header,0,0xfeedfacf);
    store32(image_header,16,1);store32(image_header,20,24);
    store32(image_header,32,27);store32(image_header,36,24);
    const unsigned char uuid[16]={0xdc,0x2d,0xd4,0xc1,0x78,0x66,0x34,0x43,0x80,0x50,0xfc,0x91,0x5a,0x02,0x04,0xc1};
    memcpy((unsigned char *)image_header+40,uuid,16);
    check_slots[0]=check_slots[1]=0;
}
static void check_gates(void)
{
    char *settings[]={0,"0","true","01","1 "};
    for(unsigned i=0;i<sizeof(settings)/sizeof(settings[0]);++i){
        reset_install();setting=settings[i];test_errno=13;
        assert(nabu_ca_context_timer_install()==0&&!nabu_ca_context_timer_active()&&test_errno==13&&!queried_images);
    }
    const char *processes[]={0,"BackBoardd","SpringBoard","FrameBench"};
    for(unsigned i=0;i<sizeof(processes)/sizeof(processes[0]);++i){
        reset_install();process=processes[i];test_errno=13;
        assert(nabu_ca_context_timer_install()==0&&test_errno==13&&!queried_images);
    }
    reset_install();image_count=0;test_errno=13;
    assert(nabu_ca_context_timer_install()==0&&test_errno==13&&!regions);
    reset_install();((unsigned char *)image_header)[40]^=1;test_errno=13;
    assert(nabu_ca_context_timer_install()==0&&test_errno==13&&!regions);
    reset_install();store32(image_header,36,128);test_errno=13;
    assert(nabu_ca_context_timer_install()==0&&test_errno==13&&!regions);
    reset_install();installation=1;test_errno=13;
    assert(nabu_ca_context_timer_install()==-1&&test_errno==13&&!regions);
}
static void check_installer(void)
{
    /* Real slot spacing and page offsets, translated through a synthetic dyld
     * slide. This exercises the production UUID/slide/installation path. */
    const size_t size=0x12000;
    void *mapping=aligned_alloc(4096,size);assert(mapping);
    for(unsigned scenario=0;scenario<7;++scenario){
        reset_install();memset(mapping,0,size);
        image_offset=(intptr_t)mapping-(intptr_t)UINT64_C(0x1d57dd000);
        check_slots[0]=(uintptr_t *)((unsigned char *)mapping+0xb48);
        check_slots[1]=(uintptr_t *)((unsigned char *)mapping+0x10d18);
        expected_slot=(uintptr_t)(image_offset+UINT64_C(0x188478040));
        *check_slots[0]=*check_slots[1]=expected_slot;
        int expected=1;
        if(scenario==1){*check_slots[1]^=8;expected=-3;}
        if(scenario==2){fail_prepare=2;expected=-4;}
        if(scenario==3){fail_restore=1;expected=-5;}
        if(scenario==4){fail_region=2;expected=-4;}
        if(scenario==5){executable_region=2;expected=-4;}
        if(scenario==6){test_page_size=3000;expected=-2;}
        const uintptr_t before[2]={*check_slots[0],*check_slots[1]};
        test_errno=13;assert(nabu_ca_context_timer_install()==expected&&test_errno==13);
        const int installed=expected==1||expected==-5;
        assert(nabu_ca_context_timer_active()==installed);
        for(unsigned i=0;i<2;++i)
            assert(*check_slots[i]==(installed?(uintptr_t)context_next:before[i]));
        if(installed){
            assert(prepares==2&&restores==2&&regions==2&&deallocates==2);
            assert(restored_pages[0]==changed_pages[0]&&restored_pages[1]==changed_pages[1]);
            assert(restored_protections[0]==1&&restored_protections[1]==3);
            assert(original_next==(set_next_fn)expected_slot);
            assert(base_next==(set_next_fn)(uintptr_t)(image_offset+UINT64_C(0x18846bbc8)));
            assert(server_lock==(server_call_fn)(uintptr_t)(image_offset+UINT64_C(0x1884c9ec0)));
            assert(server_unlock==(server_call_fn)(uintptr_t)(image_offset+UINT64_C(0x1884c9ed8)));
            assert(enable_vsync==(server_call_fn)(uintptr_t)(image_offset+UINT64_C(0x1882f3218)));
        }else if(expected==-4){
            assert(restores==1&&restored_pages[0]==changed_pages[0]&&restored_protections[0]==1);
            assert(deallocates==2);
        }else assert(!regions&&!prepares&&!restores);
        unsigned before_regions=regions;test_errno=13;
        assert(nabu_ca_context_timer_install()==expected&&test_errno==13&&regions==before_regions);
        if(installed){
            /* Even -5 leaves valid, process-lifetime hooks in both tables. */
            for(unsigned i=0;i<2;++i){
                uint64_t server[0x310/8],display[0x238/8];uintptr_t table[0x2e8/8];
                reset_calls();enabled=1;interval=1;initialize_objects(server,display,table,0,3,1);
                expected_last=0;expected_next=(struct next_update_time){0,4,4};test_errno=13;
                ((set_next_fn)*check_slots[i])(server,expected_last,expected_next);
                assert(base_calls==1&&test_errno==47);
            }
        }
    }
    free(mapping);check_slots[0]=check_slots[1]=0;
}
static void check_shared_page(void)
{
    void *mapping=aligned_alloc(4096,4096);assert(mapping);reset_install();
    uintptr_t *slots=mapping;slots[0]=slots[1]=17;
    const struct site sites[2]={{(uintptr_t)&slots[0],17,19},{(uintptr_t)&slots[1],17,23}};
    assert(install_sites(sites)==1&&regions==1&&prepares==1&&restores==1);
    assert(slots[0]==19&&slots[1]==23);free(mapping);
}
int main(void)
{
    const uint64_t values[]={0,UINT64_C(0x8000000000000000),UINT64_C(0x3ff0000000000000),
        UINT64_C(0xbff0000000000000),UINT64_C(0x7ff0000000000000),UINT64_C(0xfff0000000000000),
        UINT64_C(0x7ff8123456789abc),UINT64_C(0xfff923456789abcd),1,UINT64_C(0x8000000000000001)};
    unsigned cases=0;
    for(unsigned l=0;l<sizeof(values)/sizeof(values[0]);++l)
        for(unsigned n=0;n<sizeof(values)/sizeof(values[0]);++n){
            check_case(values[l],values[n],0,1,1,3,1);++cases;
        }
    check_case(0,0,2,1,1,3,1);++cases;
    check_case(0,0,0,2,1,2,1);++cases;
    check_case(0,0,0,UINT32_MAX,1,3,1);++cases;
    check_case(0,0,0,UINT32_C(0x55555556),1,3,1);++cases;
    check_case(0,0,0,0,1,3,1);++cases;
    check_case(0,0,7,1,0,3,1);++cases;
    check_case(0,0,7,1,1,1,1);++cases;
    check_case(0,0,7,1,1,3,0);++cases;
    check_keepalive();check_no_post_call_reads();check_gates();check_installer();check_shared_page();
    printf("PASS: %u scheduling/ABI cases; keepalive/idle/resume; opt-in/process/UUID; two-slot COW, rollback, live restore failure; no post-call reads\n",cases);
    return 0;
}
