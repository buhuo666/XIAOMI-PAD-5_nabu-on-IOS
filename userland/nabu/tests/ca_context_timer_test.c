#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

/* Test the actual production core, with only its external platform calls
 * replaced. These names avoid interposing the sanitizer runtime's libc calls. */
#define getenv test_getenv
#define getprogname test_getprogname
#define __error test_error
#include "../src/ca_context_timer.c"
/* Include the unchanged observer core as well, renaming only file-local names
 * that collide. Chaining checks execute its actual can wrapper and sink path. */
#define installation trace_installation
#define word trace_word
#define byte trace_byte
#define pointer trace_pointer
#define same trace_same
#define uuid_matches trace_uuid_matches
#define site trace_site
#define page_change trace_page_change
#define install_sites trace_install_sites
#include "../src/ca_frame_trace.c"
#undef installation
#undef word
#undef byte
#undef pointer
#undef same
#undef uuid_matches
#undef site
#undef page_change
#undef install_sites
#undef getenv
#undef getprogname
#undef __error

static _Thread_local int test_errno;
static char *setting="1";
static char *single_setting;
static const char *process="backboardd";
static uint32_t image_count;
static uint64_t image_header[7];
static intptr_t image_offset;
static unsigned queried_images,regions,prepares,restores,deallocates;
static unsigned fail_prepare,fail_restore,fail_region,executable_region;
static int test_page_size=4096;
static uintptr_t *check_slots[6];
static uintptr_t check_before[6];
static unsigned checked_slots;
static uintptr_t expected_slot;
static uint64_t changed_pages[6],restored_pages[6];
static int32_t initial_protections[6],restored_protections[6];

int *test_error(void){return &test_errno;}
char *test_getenv(const char *name)
{
    test_errno=90;
    if(!strcmp(name,"NABU_CA_CONTEXT_TIMER"))return setting;
    assert(!strcmp(name,"NABU_CA_SINGLE_FREE_PAGE"));return single_setting;
}
uint64_t mach_absolute_time(void){return 123456;}
static void unchanged_slots(void)
{for(unsigned i=0;i<checked_slots;++i)assert(*check_slots[i]==check_before[i]);}
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
    unchanged_slots();
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
        unchanged_slots();
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
    installation=installation_result=active=single_free_page=0;installed_slots=0;
    trace_installation=0;capabilities=0;
    queried_images=regions=prepares=restores=deallocates=0;
    fail_prepare=fail_restore=fail_region=executable_region=0;test_page_size=4096;
    setting="1";single_setting=0;process="backboardd";image_count=1;
    memset(image_header,0,sizeof(image_header));store32(image_header,0,0xfeedfacf);
    store32(image_header,16,1);store32(image_header,20,24);
    store32(image_header,32,27);store32(image_header,36,24);
    const unsigned char uuid[16]={0xdc,0x2d,0xd4,0xc1,0x78,0x66,0x34,0x43,0x80,0x50,0xfc,0x91,0x5a,0x02,0x04,0xc1};
    memcpy((unsigned char *)image_header+40,uuid,16);
    memset(check_slots,0,sizeof(check_slots));checked_slots=0;
}
static void check_gates(void)
{
    char *settings[]={0,"0","true","01","1 "};
    for(unsigned i=0;i<sizeof(settings)/sizeof(settings[0]);++i){
        reset_install();setting=settings[i];single_setting="1";test_errno=13;
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
    for(unsigned scenario=0;scenario<12;++scenario){
        reset_install();memset(mapping,0,size);
        image_offset=(intptr_t)mapping-(intptr_t)UINT64_C(0x1d57dd000);
        check_slots[0]=(uintptr_t *)((unsigned char *)mapping+0xb48);
        check_slots[1]=(uintptr_t *)((unsigned char *)mapping+0x10d18);
        expected_slot=(uintptr_t)(image_offset+UINT64_C(0x188478040));
        *check_slots[0]=*check_slots[1]=expected_slot;
        checked_slots=2;check_before[0]=check_before[1]=expected_slot;
        int expected=1;
        if(scenario==1){*check_slots[1]^=8;expected=-3;}
        if(scenario==2){fail_prepare=2;expected=-4;}
        if(scenario==3){fail_restore=1;expected=-5;}
        if(scenario==4){fail_region=2;expected=-4;}
        if(scenario==5){executable_region=2;expected=-4;}
        if(scenario==6){test_page_size=3000;expected=-2;}
        if(scenario>=7){char *disabled[]={"0","true","01","1 ",""};single_setting=disabled[scenario-7];}
        const uintptr_t before[2]={*check_slots[0],*check_slots[1]};
        test_errno=13;assert(nabu_ca_context_timer_install()==expected&&test_errno==13);
        const int installed=expected==1||expected==-5;
        assert(nabu_ca_context_timer_active()==installed);
        assert(!nabu_ca_single_free_page_active());
        assert(nabu_ca_context_timer_slots()==(installed?2u:0u));
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
    free(mapping);memset(check_slots,0,sizeof(check_slots));checked_slots=0;
}
static void check_shared_page(void)
{
    void *mapping=aligned_alloc(4096,4096);assert(mapping);reset_install();
    uintptr_t *slots=mapping;slots[0]=slots[1]=17;
    const struct site sites[2]={{(uintptr_t)&slots[0],17,19},{(uintptr_t)&slots[1],17,23}};
    assert(install_sites(sites,2)==1&&regions==1&&prepares==1&&restores==1);
    assert(slots[0]==19&&slots[1]==23);free(mapping);
}
static void check_six_slot_install(void)
{
    void *mapping=aligned_alloc(4096,0x12000);assert(mapping);
    const size_t offsets[]={0xb48,0x10d18,0xdb0,0x1570,0xee50,0xf670};
    const context_can_fn wrappers[]={single_free_can0,single_free_can1,single_free_can2,single_free_can3};
    for(unsigned chain=0;chain<3;++chain)for(unsigned scenario=0;scenario<24;++scenario){
        reset_install();single_setting="1";memset(mapping,0,0x12000);
        image_offset=(intptr_t)mapping-(intptr_t)UINT64_C(0x1d57dd000);
        const uintptr_t next=(uintptr_t)(image_offset+UINT64_C(0x188478040));
        const uintptr_t native=(uintptr_t)(image_offset+UINT64_C(0x18829cd88));
        trace_installation=2;capabilities=NabuCaDisplayHooks;
        assert(nabu_ca_frame_trace_can_predecessor()==(uintptr_t)traced_can);
        for(unsigned i=0;i<6;++i){
            check_slots[i]=(uintptr_t *)((unsigned char *)mapping+offsets[i]);
            *check_slots[i]=i<2?next:chain==1||(chain==2&&(i&1))?(uintptr_t)traced_can:native;
        }
        int expected=1;
        if(scenario>=1&&scenario<=5){fail_prepare=scenario;expected=-4;}
        if(scenario>=6&&scenario<=10){fail_region=scenario-5;expected=-4;}
        if(scenario>=11&&scenario<=15){fail_restore=scenario-10;expected=-5;}
        if(scenario>=16&&scenario<=20){*check_slots[scenario-15]^=8;expected=-3;}
        if(scenario==21){trace_installation=3;*check_slots[2]=(uintptr_t)traced_can;expected=-3;}
        if(scenario==22){executable_region=3;expected=-4;}
        if(scenario==23){test_page_size=3000;expected=-2;}
        checked_slots=6;
        for(unsigned i=0;i<6;++i)check_before[i]=*check_slots[i];
        test_errno=13;assert(nabu_ca_context_timer_install()==expected&&test_errno==13);
        const int installed=expected==1||expected==-5;
        assert(nabu_ca_context_timer_active()==installed);
        assert(nabu_ca_single_free_page_active()==installed);
        assert(nabu_ca_context_timer_slots()==(installed?6u:0u));
        for(unsigned i=0;i<6;++i){
            const uintptr_t replacement=i<2?(uintptr_t)context_next:(uintptr_t)wrappers[i-2];
            assert(*check_slots[i]==(installed?replacement:check_before[i]));
            if(installed&&i>=2)assert((uintptr_t)can_predecessors[i-2]==check_before[i]);
        }
        if(installed){
            assert(regions==5&&prepares==5&&restores==5&&deallocates==5);
            for(unsigned i=0;i<5;++i){
                assert(changed_pages[i]==restored_pages[i]);
                assert(initial_protections[i]==restored_protections[i]);
            }
        }else if(expected==-4){
            const unsigned prior=fail_prepare?fail_prepare-1:fail_region?fail_region-1:executable_region-1;
            assert(restores==prior);
            for(unsigned i=0;i<prior;++i)assert(changed_pages[i]==restored_pages[i]);
        }else assert(!regions&&!prepares&&!restores);
        const unsigned reads=regions;test_errno=13;
        assert(nabu_ca_context_timer_install()==expected&&test_errno==13&&regions==reads);
    }
    free(mapping);checked_slots=0;
    /* Disabled new opt-in retains the original two hooks. Getter never invents
     * a predecessor when the observer failed (including its live -5 state). */
    reset_install();trace_installation=2;capabilities=0;
    assert(!nabu_ca_frame_trace_can_predecessor());
    capabilities=NabuCaDisplayHooks;trace_installation=3;
    assert(!nabu_ca_frame_trace_can_predecessor());
}

static pthread_mutex_t page_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t change_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t change_condition=PTHREAD_COND_INITIALIZER;
static unsigned gate_locks,gate_unlocks,page_locked,can_calls,can_flags[4];
static uint32_t first_result,second_result;
static unsigned can_marks,mark_event[32];
static uint64_t mark_flags[32];
static int mutate_after_check,change_started,change_done,free_first,clear_first;
static void *can_display;
static void page_lock(void *mutex)
{
    assert(mutex==(unsigned char *)can_display+0x368);
    assert(!pthread_mutex_lock(&page_mutex));assert(!page_locked);page_locked=1;
    ++gate_locks;test_errno=95;
}
static void page_unlock(void *mutex)
{
    assert(mutex==(unsigned char *)can_display+0x368&&page_locked);page_locked=0;
    ++gate_unlocks;assert(!pthread_mutex_unlock(&page_mutex));test_errno=96;
    if(mutate_after_check){
        assert(!pthread_mutex_lock(&change_mutex));change_started=1;
        assert(!pthread_cond_broadcast(&change_condition));
        while(!change_done)assert(!pthread_cond_wait(&change_condition,&change_mutex));
        assert(!pthread_mutex_unlock(&change_mutex));
    }
}
static void *concurrent_page_change(void *unused)
{
    (void)unused;assert(!pthread_mutex_lock(&change_mutex));
    while(!change_started)assert(!pthread_cond_wait(&change_condition,&change_mutex));
    assert(!pthread_mutex_unlock(&change_mutex));
    assert(!pthread_mutex_lock(&page_mutex));
    store32(can_display,0x3a8+2*0x30,17);store32(can_display,0x3c0+2*0x30,19);
    assert(!pthread_mutex_unlock(&page_mutex));
    assert(!pthread_mutex_lock(&change_mutex));change_done=1;
    assert(!pthread_cond_broadcast(&change_condition));
    assert(!pthread_mutex_unlock(&change_mutex));return 0;
}
static uint32_t fixture_can(void *display,uint32_t flags)
{
    assert(display==can_display&&!page_locked&&can_calls<2);
    assert(test_errno==(can_calls?47:13));can_flags[can_calls]=flags;
    if(can_calls++==0){
        if(clear_first)store32(display,0x3a8+2*0x30,0);
        if(free_first)free(display);
        test_errno=47;return first_result;
    }
    /* A platform-boundary substitute rechecks the state under the same lock.
     * The real can_update implementation is not reimplemented in this test. */
    assert(!pthread_mutex_lock(&page_mutex));
    const int changed=word(display,0x3a8+2*0x30)!=0;
    assert(!pthread_mutex_unlock(&page_mutex));
    test_errno=59;return changed?0:second_result;
}
static void can_sink(uint32_t event,uint64_t identity,uint64_t a,uint64_t b,uint64_t c)
{
    (void)c;assert(identity==(uintptr_t)can_display&&can_marks<32);
    if(event==NabuCaCanEnter||event==NabuCaCanLeave){
        mark_event[can_marks]=event;mark_flags[can_marks++]=event==NabuCaCanEnter?a:b;
    }
    test_errno=201;
}
static void initialize_can(void *display)
{
    memset(display,0,0x450);store32(display,0x358,2);store32(display,0x35c,1);store32(display,0x360,3);
    /* The other page remains busy. Its descriptor and swap are never modified. */
    store32(display,0x3a8,7);store32(display,0x3c0,9);store64(display,0x3b8,UINT64_C(0x123456789));
    can_display=display;gate_locks=gate_unlocks=page_locked=can_calls=can_marks=0;
    first_result=0;second_result=1;mutate_after_check=change_started=change_done=free_first=clear_first=0;
    server_lock=page_lock;server_unlock=page_unlock;
    capabilities=NabuCaDisplayHooks;trace_sink=can_sink;original_can=fixture_can;
}
static unsigned check_single_free(void)
{
    unsigned cases=0;
    const context_can_fn wrappers[]={single_free_can0,single_free_can1,single_free_can2,single_free_can3};
    for(unsigned observed=0;observed<2;++observed)for(unsigned slot=0;slot<4;++slot){
        for(unsigned scenario=0;scenario<18;++scenario){
            uint64_t display[0x450/8];initialize_can(display);
            uint32_t flags=0;int retry=1;uint32_t result=1;
            if(scenario==1){first_result=77;retry=0;result=77;}
            if(scenario==2){second_result=0;result=0;}
            if(scenario==3){second_result=73;result=73;}
            if(scenario==4){flags=1;retry=0;result=0;}
            if(scenario==5){flags=2;retry=0;result=0;}
            if(scenario==6){flags=UINT32_MAX;retry=0;result=0;}
            if(scenario==7){store32(display,0x360,2);retry=0;result=0;}
            if(scenario==8){store32(display,0x360,4);retry=0;result=0;}
            if(scenario==9){store32(display,0x358,3);retry=0;result=0;}
            if(scenario==10){store32(display,0x358,1);retry=0;result=0;}
            if(scenario>=11&&scenario<=15){
                const unsigned resource[]={0x3a8,0x3c0,0x3b0,0x3b8,0x3c8};
                if(scenario<13)store32(display,resource[scenario-11]+2*0x30,5);
                else store64(display,resource[scenario-11]+2*0x30,UINT64_C(1)<<40);
                retry=0;result=0;
            }
            if(scenario==16){store32(display,0x3a8+2*0x30,17);clear_first=1;}
            if(scenario==17){store32(display,0x3d0+2*0x30,2);}
            can_predecessors[slot]=observed?traced_can:fixture_can;
            unsigned char before[sizeof(display)];memcpy(before,display,sizeof(display));
            test_errno=13;assert(wrappers[slot](display,flags)==result);
            assert(can_calls==(retry?2u:1u)&&can_flags[0]==flags);
            assert(test_errno==(retry?59:47)&&!page_locked);
            assert(gate_locks==((first_result||flags)?0u:1u)&&gate_unlocks==gate_locks);
            if(retry)assert(can_flags[1]==1);
            if(clear_first)store32(before,0x3a8+2*0x30,0);
            assert(!memcmp(before,display,sizeof(display)));
            if(observed){
                assert(can_marks==can_calls*2);
                for(unsigned call=0;call<can_calls;++call){
                    assert(mark_event[call*2]==NabuCaCanEnter&&mark_event[call*2+1]==NabuCaCanLeave);
                    assert(mark_flags[call*2]==can_flags[call]&&mark_flags[call*2+1]==can_flags[call]);
                }
            }else assert(!can_marks);
            ++cases;
        }
        uint64_t display[0x450/8];initialize_can(display);
        can_predecessors[slot]=observed?traced_can:fixture_can;mutate_after_check=1;
        pthread_t writer;assert(!pthread_create(&writer,0,concurrent_page_change,0));
        test_errno=13;assert(wrappers[slot](display,0)==0&&can_calls==2&&test_errno==59);
        assert(!pthread_join(writer,0));assert(word(display,0x3a8+2*0x30)==17);
        assert(word(display,0x3c0+2*0x30)==19&&word(display,0x3c0)==9);++cases;
    }
    /* A successful original can return without any wrapper object access. */
    void *display=malloc(0x450);assert(display);initialize_can(display);free_first=1;first_result=91;
    can_predecessors[0]=fixture_can;test_errno=13;
    assert(single_free_can0(display,0)==91&&test_errno==47&&!gate_locks);++cases;
    return cases;
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
    check_six_slot_install();const unsigned single_cases=check_single_free();
    printf("PASS: %u scheduling/ABI cases; keepalive/idle/resume; opt-in/process/UUID; two-slot COW, rollback, live restore failure; no post-call reads\n",cases);
    printf("PASS: %u single-free-page cases; original false/flags0/3-page/resource gates; raw return and errno; actual observer chaining; concurrent revalidation; 72 six-slot COW/install scenarios\n",single_cases);
    return 0;
}
