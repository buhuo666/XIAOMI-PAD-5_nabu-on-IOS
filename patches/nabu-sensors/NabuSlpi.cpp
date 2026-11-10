// SPDX-License-Identifier: BSD-2-Clause-Patent
// Opt-in root-PD diagnostic, not an operational iPadOS sensor provider.
// All APPS polling has deadlines. A secure-world SMC itself cannot be timed out
// by this worker; the known ADSP continuation risk also applies to first SLPI bring-up.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>
#include <kern/clock.h>
#include <kern/thread_call.h>
#include <kern/thread.h>
#include <kern/locks.h>
#include <mach/vm_param.h>
#include <vm/memory_types.h>
#include <pexpert/pexpert.h>
#include "NabuSlpiProtocol.h"
#include "NabuSlpiGlink.h"
#include "NabuSscCensus.h"
#include "NabuSscRegistry.h"
#include "NabuFastRpcSession.h"
#include "NabuFastRpcArchive.h"
#include "NabuSlpiDma.h"
#if NABU_SLPI_NATIVE
#include "NabuSscNative.h"
#include "NabuSscClock.h"
#include "NabuSscControl.h"
#endif
#include "../nabu-wireless/NabuWlanController.h"
extern "C" vm_offset_t ml_io_map_unmappable(vm_offset_t,vm_size_t,unsigned int);
extern "C" void ml_io_unmap(vm_offset_t,vm_size_t);
extern "C" const uint8_t *hakios_image_file(const char *,const char *,uint64_t *,int *);
extern "C" void loader_log_line(const char *);
extern "C" lck_mtx_t hakios_aop_mailbox_lock,hakios_rsc_lock,hakios_smem_alloc_lock;
extern "C" lck_mtx_t hakios_smmu_lock;
extern "C" vm_offset_t ml_vtophys(vm_offset_t);
extern "C" kern_return_t thread_terminate(thread_t);
namespace {
static thread_call_t slpi_call;
static uint32_t slpi_mode;
#if NABU_SLPI_NATIVE
static uint32_t slpi_clock_epoch;
#endif
static char report[16384];
static unsigned report_bytes;
static void publish() {
    IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane);
    if (chosen) { chosen->setProperty("nabu-slpi-report", report); chosen->release(); }
}
static void log(const char *format, ...) __attribute__((format(printf, 1, 2)));
static void log(const char *format, ...) {
    char line[512]; va_list args; va_start(args, format);
    vsnprintf(line, sizeof(line), format, args); va_end(args); IOLog("%s", line);
    unsigned bytes = unsigned(strlen(line));
    // FastRPC may read hundreds of files. Keep the latest complete lines in
    // /chosen so the final result remains readable; the disk log retains all.
    while(bytes>=sizeof(report)-report_bytes){
        const char *end=strchr(report,'\n');
        unsigned drop=end?unsigned(end-report)+1:report_bytes;
        memmove(report,report+drop,report_bytes-drop+1);report_bytes-=drop;
    }
    memcpy(report + report_bytes, line, bytes + 1); report_bytes += bytes;
}
static uint32_t rd(vm_offset_t at) { return *(volatile uint32_t *)at; }
static void wr(vm_offset_t at, uint32_t value) { *(volatile uint32_t *)at = value; __asm__ volatile("dsb sy" ::: "memory"); }
static bool wait_value(vm_offset_t at, uint32_t value, unsigned ms) {
    for (unsigned i = 0; i < ms; ++i) { if (rd(at) == value) return true; IOSleep(1); }
    return false;
}
static vm_offset_t map(const char *name, vm_offset_t physical, vm_size_t bytes, unsigned attributes) {
    vm_offset_t address = ml_io_map_unmappable(physical, bytes, attributes);
    log("NABU SLPI: map %s pa=%#llx bytes=%#llx ok=%u\n", name, (uint64_t)physical, (uint64_t)bytes, address != 0);
    return address;
}
static void unmap(vm_offset_t address, vm_size_t bytes) {
    // io_map returns allocation base + physical page offset. ml_io_unmap
    // expects the full VM allocation, including on 16K VM / 4K hardware pages.
    vm_offset_t base = trunc_page(address);
    vm_size_t span = round_page(address - base + bytes);
    log("NABU SLPI: unmap va=%#llx bytes=%#llx base=%#llx span=%#llx\n",
        (uint64_t)address, (uint64_t)bytes, (uint64_t)base, (uint64_t)span);
    ml_io_unmap(base, span);
}
// Narrow SCM boundary trace: stack formatting and the existing panic-capable
// loader logger only. MPIDR records CPU affinity; DAIF is sampled before logging.
// Do not allocate, publish registry properties or change the caller's IRQ state.
static __attribute__((noinline)) char *trace_text(char *at, const char *text) {
#pragma clang loop vectorize(disable) interleave(disable) unroll(disable)
    while (*text) *at++ = *text++;
    return at;
}
static __attribute__((noinline)) char *trace_hex(char *at, uint64_t value) {
    at = trace_text(at, "0x");
#pragma clang loop vectorize(disable) interleave(disable) unroll(disable)
    for (int shift = 60; shift >= 0; shift -= 4) {
        unsigned digit = (value >> shift) & 15;
        *at++ = digit < 10 ? '0' + digit : 'a' + digit - 10;
    }
    return at;
}
static __attribute__((noinline)) void trace_smc(const char *phase, unsigned command, unsigned attempt,
    uint64_t x0, uint64_t x1, uint64_t x6) {
    uint64_t mpidr, daif;
    __asm__ volatile("mrs %0, mpidr_el1\n\tmrs %1, daif" : "=r"(mpidr), "=r"(daif) : : "memory");
    char line[256];
    char *at = trace_text(line, "NABU SLPI SMC "); at = trace_text(at, phase);
    at = trace_text(at, " command="); at = trace_hex(at, command);
    at = trace_text(at, " attempt="); at = trace_hex(at, attempt);
    at = trace_text(at, " MPIDR="); at = trace_hex(at, mpidr);
    at = trace_text(at, " DAIF="); at = trace_hex(at, daif);
    at = trace_text(at, " x0="); at = trace_hex(at, x0);
    at = trace_text(at, " x1="); at = trace_hex(at, x1);
    at = trace_text(at, " x6="); at = trace_hex(at, x6);
    *at++ = '\n'; *at = 0; loader_log_line(line);
}
static bool pas(unsigned command, uint64_t types, uint64_t b = 0, uint64_t c = 0) {
    uint64_t session = 0;
    log("NABU SLPI: PAS12 command=%u arg1=%#llx arg2=%#llx\n", command, b, c); publish();
    for (unsigned attempt = 0; attempt < 100; ++attempt) {
        uint64_t request = attempt ? 1 : 0x42000200 | command;
        trace_smc("enter", command, attempt, request, types, session);
        register uint64_t x0 __asm__("x0") = request;
        register uint64_t x1 __asm__("x1") = types;
        register uint64_t x2 __asm__("x2") = 12;
        register uint64_t x3 __asm__("x3") = b;
        register uint64_t x4 __asm__("x4") = c;
        register uint64_t x5 __asm__("x5") = 0;
        register uint64_t x6 __asm__("x6") = session;
        register uint64_t x7 __asm__("x7") = 0;
        __asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3), "+r"(x4), "+r"(x5), "+r"(x6), "+r"(x7)
            : : "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory");
        uint64_t result = x0, response = x1;
        session = x6;
        trace_smc("return", command, attempt, result, response, session);
        if (result != 1) {
            log("NABU SLPI: PAS12 command=%u result=%lld response=%#llx\n", command, result, response); publish();
            return result == 0 && response == 0;
        }
    }
    log("NABU SLPI: PAS12 command=%u continuation limit reached\n", command); return false;
}

struct Trial {
    NabuSlpi::Image image{};
    vm_offset_t aop=0,ipc=0,rsc=0,smem_va=0,hwlock=0;
    uint32_t mailbox=0,our_item=0,last_state=0xffffffff;
    void *metadata=nullptr;
    IOPhysicalAddress metadata_pa=0;
    NabuSmem smem{};
    NabuSlpiGlink::Link<Trial> glink{*this};
    NabuSsc::Census<Trial> census{*this};
    NabuSsc::Registry<Trial> registry{*this};
    NabuFastRpc::Session<Trial> rpc{*this};
    NabuFastRpc::Archive rpc_files{};
    NabuSlpiDma dma{};
    NabuWlanFault dma_faults{};
    vm_offset_t dma_va=0;
    bool dma_active=false;
#if NABU_SLPI_NATIVE
    NabuSsc::Native<Trial> native{*this};
    NabuSsc::ClockMapping native_clock{};
    NabuSsc::ClockQualification native_clock_qualification{};
    NabuSsc::ClockCursor native_cursors[NabuSensorKindCount]{};
    NabuSsc::ControlSession<Trial> native_controls{*this};
    uint64_t native_now_ms=0,native_last_report_ms=0;
    unsigned native_clock_rejected=0;
    IOLock *native_control_lock=nullptr;
    struct NativeMailbox {
        unsigned kind=0,control=0;
        uint64_t microseconds=0;
        IOReturn result=kIOReturnNotReady;
        bool running=false,occupied=false,queued=false,done=false,abandoned=false;
    } native_mailbox;
    static NabuSsc::ClockBracket clock_bracket(){
        NabuSsc::ClockBracket b;
        clock_get_uptime(&b.mach_before);
        __asm__ volatile("isb\n\tmrs %0, cntpct_el0\n\tisb\n\tmrs %1, cntvct_el0\n\tmrs %2, cntfrq_el0"
            : "=r"(b.physical_ticks),"=r"(b.virtual_ticks),"=r"(b.frequency) : : "memory");
        clock_get_uptime(&b.mach_after);return b;
    }
    bool native_begin(){
        IOReturn result=nabu_sensor_hid_initialize();
        if(result){log("NABU SENSOR: source initialization failed=%#x\n",result);return false;}
        native_control_lock=IOLockAlloc();if(!native_control_lock)return false;
        native_mailbox.running=true;
        nabu_sensor_hid_set_control_handler(control_request,this);
        const auto b=clock_bracket();
        const auto update=native_clock.observe(b,NabuSsc::ClockFrequency/1000);
        // The domain is an explicit board policy. Even with that policy, four
        // live accelerometer samples over >=100ms must corroborate it first.
        // This initial no-batching trial uses a 1s age and 500ms sample-gap bound.
        // No sample-receipt offset is fitted and no ALS snapshot qualifies it.
        const NabuSsc::ClockQualificationPolicy policy{1,4,NabuSsc::ClockFrequency/10,
            NabuSsc::ClockFrequency,NabuSsc::ClockFrequency/2};
        native_clock_qualification.arm(native_clock,static_cast<NabuSsc::ClockEpoch>(slpi_clock_epoch),policy);
        log("NABU SENSOR CLOCK: begin=%u epoch-policy=%u valid=%u generation=%llu physical=%llu virtual=%llu mach=%llu..%llu frequency=%llu\n",
            unsigned(update),slpi_clock_epoch,native_clock.valid(),native_clock.generation(),b.physical_ticks,b.virtual_ticks,b.mach_before,b.mach_after,b.frequency);
        census.stream(receive_native,this);return true;
    }
    static void receive_native(void *context,unsigned kind,NabuSsc::Suid suid,uint64_t ticks,const NabuSsc::Sample &sample){
        auto &self=*static_cast<Trial *>(context);if(kind>=NabuSensorKindCount)return;
        NabuSsc::Suid selected;
        if(self.native.source(kind,selected)&&!NabuSsc::equal(selected,suid))return;
        const uint64_t generation=self.native_clock.generation();
        const auto update=self.native_clock.observe(clock_bracket(),NabuSsc::ClockFrequency/1000);
        if(self.native_clock.generation()!=generation){
            log("NABU SENSOR CLOCK: discontinuity generation=%llu; epoch confirmation withdrawn\n",self.native_clock.generation());
            self.native.stop(kIOReturnAborted);
        }
        (void)update;
        if(!self.native_clock_qualification.qualified(self.native_clock)){
            bool streaming=false;
            const auto &d=self.census.discovery[kind];
            for(unsigned i=0;i<d.count;++i)if(NabuSsc::equal(d.candidates[i].suid,suid))
                streaming=d.candidates[i].state==NabuSsc::State::Ready&&d.candidates[i].attributes.stream_type==0;
            const auto qualified=self.native_clock_qualification.consider(self.native_clock,kind,streaming,ticks,suid.low,suid.high);
            if(qualified==NabuSsc::ClockQualificationResult::Qualified){
                const auto offset=self.native_clock.offset(self.native_clock.epoch());
                log("NABU SENSOR CLOCK: live qualification accepted epoch=%u generation=%llu samples=%u offset=%lld..%lld\n",
                    unsigned(self.native_clock.epoch()),self.native_clock.generation(),self.native_clock_qualification.samples(0),offset.low,offset.high);
            }
        }
        NabuSsc::ClockStamp stamp;
        const uint64_t max_age_ms=self.native_timeout_ms(kind),ticks_per_ms=NabuSsc::ClockFrequency/1000;
        const uint64_t age_limit=kind==NabuSensorAmbientLight||max_age_ms>UINT64_MAX/ticks_per_ms?
            UINT64_MAX:max_age_ms*ticks_per_ms;
        const auto result=self.native_clock.convert(ticks,self.native_cursors[kind],age_limit,stamp);
        if(result!=NabuSsc::ClockSampleResult::Converted){
            if(++self.native_clock_rejected<=8)log("NABU SENSOR CLOCK: rejected kind=%u reason=%u ssc=%llu generation=%llu\n",
                kind,unsigned(result),ticks,self.native_clock.generation());
            return;
        }
        self.native.sample(self.census,kind,suid,ticks,sample,stamp.mach_ticks,self.native_now_ms);
    }
    int32_t native_submit(const NabuSensorDescription &description,const NabuSensorRecord &record){
        IOReturn result=nabu_sensor_hid_submit(&description,&record);
        if(result)log("NABU SENSOR: source submit kind=%u failed=%#x\n",description.kind,result);
        return result;
    }
    void native_invalidate(unsigned kind,int32_t reason){
        nabu_sensor_hid_invalidate(kind,reason);
        log("NABU SENSOR: source invalidated kind=%u reason=%#x\n",kind,reason);
    }
    uint64_t native_timeout_ms(unsigned kind)const{
        const auto *settings=native_controls.settings(kind);
        if(!settings)return 2000;
        return 2000+settings->report_interval_us/1000+settings->batch_interval_us/1000;
    }
    static IOReturn control_result(NabuSsc::ControlStatus status){
        using S=NabuSsc::ControlStatus;
        switch(status){
            case S::Accepted:return kIOReturnSuccess;
            case S::Busy:return kIOReturnBusy;
            case S::NotReady:return kIOReturnNotReady;
            case S::Unsupported:return kIOReturnUnsupported;
            case S::BadArgument:return kIOReturnBadArgument;
            case S::TimedOut:return kIOReturnTimeout;
            case S::Cancelled:return kIOReturnAborted;
            default:return kIOReturnIOError;
        }
    }
    static int32_t control_request(void *context,uint32_t kind,uint32_t control,uint64_t microseconds){
        auto &self=*static_cast<Trial *>(context);
        IOLockLock(self.native_control_lock);auto &m=self.native_mailbox;
        if(!m.running||m.occupied){IOReturn r=m.running?kIOReturnBusy:kIOReturnNotReady;IOLockUnlock(self.native_control_lock);return r;}
        m.kind=kind;m.control=control;m.microseconds=microseconds;
        m.occupied=m.queued=true;m.done=m.abandoned=false;m.result=kIOReturnNotReady;
        uint64_t deadline;clock_interval_to_deadline(2,NSEC_PER_SEC,&deadline);
        while(m.running&&!m.done){
            int wait=IOLockSleepDeadline(self.native_control_lock,&m,deadline,THREAD_ABORTSAFE);
            if(wait!=THREAD_AWAKENED&&!m.done){
                m.abandoned=true;IOLockUnlock(self.native_control_lock);
                return wait==THREAD_TIMED_OUT?kIOReturnTimeout:kIOReturnAborted;
            }
        }
        IOReturn result=m.done?m.result:kIOReturnNotReady;m.occupied=false;
        IOLockUnlock(self.native_control_lock);return result;
    }
    void native_tick(){
        if(census.result.has_client&&!census.result.stopping&&!census.result.done){
            native_controls.start(glink.result().ssc_node,glink.result().ssc_port,census.result.client);
            for(unsigned kind=0;kind<NabuSensorKindCount;++kind){
                const auto *settings=native_controls.settings(kind);if(!settings)continue;
                bool subscribed=false;
                for(unsigned i=0;i<census.stream_count;++i){
                    const auto &s=census.streams[i];
                    if(NabuSsc::equal(s.suid,settings->suid)&&s.configured&&!s.failed&&!s.disabled)subscribed=true;
                }
                if(!subscribed)native_controls.unbind(kind);
            }
            for(unsigned i=0;i<census.stream_count;++i){
                const auto &s=census.streams[i];NabuSsc::Suid selected;
                if(s.type>=NabuSensorKindCount||!s.configured||s.failed||s.disabled||
                   !native.source(s.type,selected)||!NabuSsc::equal(selected,s.suid))continue;
                const auto &d=census.discovery[s.type];
                for(unsigned c=0;c<d.count;++c)if(NabuSsc::equal(d.candidates[c].suid,s.suid))
                    native_controls.bind(s.type,s.suid,d.candidates[c].attributes.stream_type==1);
            }
        }else if(census.result.stopping||census.result.done){
            for(unsigned kind=0;kind<NabuSensorKindCount;++kind)native_controls.unbind(kind);
        }
        IOLockLock(native_control_lock);auto &m=native_mailbox;
        if(m.queued){
            m.queued=false;
            if(m.abandoned)m.occupied=false;
            else{
                const auto status=native_controls.queue(m.kind,m.control,m.microseconds,native_now_ms);
                if(status!=NabuSsc::ControlStatus::Queued){m.result=control_result(status);m.done=true;IOLockWakeup(native_control_lock,&m,false);}
            }
        }
        IOLockUnlock(native_control_lock);
        native_controls.tick(native_now_ms);
        NabuSsc::ControlCompletion completion;
        if(native_controls.take_result(completion)){
            log("NABU SENSOR CONTROL: kind=%u control=%u us=%llu transaction=%#x status=%u sent=%u qmi=%u/%u ssc=%u\n",
                completion.kind,completion.control,completion.microseconds,completion.transaction,unsigned(completion.status),completion.sent,
                completion.qmi_result,completion.qmi_error,completion.ssc_response);
            IOLockLock(native_control_lock);
            if(m.abandoned)m.occupied=false;
            else if(m.occupied){m.result=control_result(completion.status);m.done=true;IOLockWakeup(native_control_lock,&m,false);}
            IOLockUnlock(native_control_lock);
        }
        native.tick(census,native_now_ms,kIOReturnNotReady,kIOReturnTimeout);
        if(native_now_ms-native_last_report_ms>=5000){
            native_last_report_ms=native_now_ms;
            log("NABU SENSOR: samples=%u/%u/%u/%u clock-rejected=%u source-rejected=%u invalidations=%u epoch=%u generation=%llu\n",
                native.accepted[0],native.accepted[1],native.accepted[2],native.accepted[3],native_clock_rejected,native.rejected,
                native.invalidations,unsigned(native_clock.epoch()),native_clock.generation());publish();
        }
    }
    void native_end(){
        if(!native_control_lock||!native_mailbox.running)return;
        native.stop(kIOReturnNotReady);native_controls.stop();native_clock.invalidate();
        nabu_sensor_hid_set_control_handler(nullptr,nullptr);
        IOLockLock(native_control_lock);native_mailbox.running=false;
        native_mailbox.done=true;native_mailbox.result=kIOReturnNotReady;
        IOLockWakeup(native_control_lock,&native_mailbox,false);IOLockUnlock(native_control_lock);
        // The retained source userclient may be leaving control_request. Keep
        // this small lock with Trial for the remainder of the kernel lifetime.
    }
#endif
    void put(uint32_t offset, uint32_t value) { wr(smem_va + offset, value); }
    uint32_t read32(uint32_t offset) {
        uint32_t value = rd(smem_va + offset);
        __asm__ volatile("dsb sy" ::: "memory");
        return value;
    }
    void write32(uint32_t offset, uint32_t value) {
        __asm__ volatile("dsb sy" ::: "memory"); // FIFO bytes precede published head / tail.
        put(offset, value);
    }
    uint8_t read8(uint32_t offset) { return smem.data[offset]; }
    void write8(uint32_t offset, uint8_t value) { *(volatile uint8_t *)(smem_va + offset) = value; }
    void ring() { wr(ipc, 1u << NabuSlpi::GlinkDoorbell); }
    void rpc_publish(void *cpu,unsigned bytes){
        for(uintptr_t at=reinterpret_cast<uintptr_t>(cpu);at<reinterpret_cast<uintptr_t>(cpu)+bytes;at+=64)
            __asm__ volatile("dc civac, %0" :: "r"(at) : "memory");
        __asm__ volatile("dsb sy" ::: "memory");
    }
    void rpc_consume(void *cpu,unsigned bytes){
        for(uintptr_t at=reinterpret_cast<uintptr_t>(cpu);at<reinterpret_cast<uintptr_t>(cpu)+bytes;at+=64)
            __asm__ volatile("dc ivac, %0" :: "r"(at) : "memory");
        __asm__ volatile("dsb sy" ::: "memory");
    }
    bool rpc_send(const uint8_t *data,uint32_t bytes){return glink.send_rpc(data,bytes);}
    void rpc_call_log(unsigned stage,uint64_t context,int32_t result){
        if(stage!=NabuFastRpc::Session<Trial>::Next||result)
            log("NABU FASTRPC: stage=%u context=%#llx result=%d\n",stage,context,result);
    }
    void rpc_reverse_log(uint32_t handle,uint32_t sc,uint32_t input,uint32_t output,int32_t result){
        log("NABU FASTRPC REVERSE: handle=%u sc=%#x input=%u output=%u result=%d\n",handle,sc,input,output,result);
    }
    bool rpc_file_open(const char *path,const uint8_t *&data,uint32_t &bytes){return rpc_files.open(path,data,bytes);}
    int rpc_file_list(const char *path,unsigned index,char *name,unsigned capacity,uint32_t &bytes){
        return rpc_files.list(path,index,name,capacity,bytes);
    }
    const char *rpc_file_env(const char *name){
        if(!strcmp(name,"ADSP_LIBRARY_PATH"))return "/vendor/dsp/sdsp;/vendor/dsp;/vendor/etc/sensors";
        if(!strcmp(name,"ADSP_SENSOR_PATH"))return "/vendor/etc/sensors/config";
        return nullptr;
    }
    void rpc_file_log(uint32_t handle,uint32_t method,const char *path,int32_t result){
        log("NABU FASTRPC FILE: handle=%u method=%u result=%d path=%s\n",handle,method,result,path);
    }
    bool prepare_dma(){
        dma_va=map("SLPI-SMMU",0x15000000,0x100000,VM_WIMG_IO);if(!dma_va)return false;
        NabuSlpiDma::Platform ops{};ops.cookie=this;
        ops.allocate=[](void *,unsigned bytes){
            void *cpu=IOMallocContiguous(bytes,16384,nullptr);if(!cpu)return NabuSlpiDma::Memory{};
            bzero(cpu,bytes);return NabuSlpiDma::Memory{cpu,ml_vtophys(reinterpret_cast<vm_offset_t>(cpu))};
        };
        ops.release=[](void *,NabuSlpiDma::Memory memory,unsigned bytes){IOFreeContiguous(memory.cpu,bytes);};
        ops.publish=[](void *x,void *cpu,unsigned bytes){static_cast<Trial *>(x)->rpc_publish(cpu,bytes);};
        ops.lock=[](void *){lck_mtx_lock(&hakios_smmu_lock);};
        ops.unlock=[](void *){lck_mtx_unlock(&hakios_smmu_lock);};
        ops.io={this,0x100000,
            [](void *x,size_t at,uint32_t *v){*v=rd(static_cast<Trial *>(x)->dma_va+at);return 0;},
            [](void *x,size_t at,uint64_t *v){*v=*reinterpret_cast<volatile uint64_t *>(static_cast<Trial *>(x)->dma_va+at);return 0;},
            [](void *x,size_t at,uint32_t v){wr(static_cast<Trial *>(x)->dma_va+at,v);return 0;},
            [](void *x,size_t at,uint64_t v){*reinterpret_cast<volatile uint64_t *>(static_cast<Trial *>(x)->dma_va+at)=v;return 0;},
            [](void *){__asm__ volatile("dsb sy" ::: "memory");return 0;}};
        if(!dma.prepare(ops)){log("NABU SLPI DMA: prepare failed phase=%u status=%u\n",dma.prepare_failure,dma.status);return false;}
        dma_active=dma.attach([](void *x,unsigned bank,const ArmSmmu4KIo *io){
            return nabu_smmu_fault_install(static_cast<NabuWlanFault *>(x),bank,io,NabuSlpiDma::first_sid)?0:-1;
        },[](void *x,unsigned){nabu_smmu_fault_remove(static_cast<NabuWlanFault *>(x));},&dma_faults);
        log("NABU SLPI DMA: active=%u phase=%u status=%u sid=%#x bank=%u iova=%#llx bits=%u pa=%#llx bytes=%u\n",
            dma_active,dma.attach_phase,dma.status,NabuSlpiDma::first_sid,dma.bank,NabuSlpiDma::iova_base,
            dma.mapping.input_bits,dma.blocks[0].physical,NabuSlpiDma::block_bytes);
        return dma_active;
    }
    bool dma_healthy(){
        NabuWlanFault::Record context{},global{};uint32_t flags=dma_faults.snapshot(context,global);
        if(flags){log("NABU SLPI DMA: fault flags=%u status=%#x address=%#llx sid=%#x global=%#x\n",
            flags,context.status,context.address,context.sid,global.status);dma.lost();return false;}
        return dma.observe();
    }
    bool allocate(uint16_t id, uint32_t bytes, uint32_t &offset) {
        lck_mtx_lock(&hakios_smem_alloc_lock);
        bool held = false;
        for (unsigned i = 0; i < 1000; ++i) { wr(hwlock, 1); if (rd(hwlock) == 1) { held = true; break; } IODelay(10); }
        bool ok = held && NabuSlpi::allocate(smem, *this, id, bytes, offset);
        if (held) wr(hwlock, 0);
        lck_mtx_unlock(&hakios_smem_alloc_lock);
        log("NABU SLPI: SMEM host=3 allocate id=%u bytes=%u ok=%u offset=%#x\n", id, bytes, ok, ok ? offset : 0);
        return ok;
    }
    bool prepare() {
        uint64_t bytes = 0;
        if(slpi_mode>=3){
            const uint8_t *archive=hakios_image_file("rpc","files.bin",&bytes,nullptr);
            if(!archive||bytes>UINT32_MAX||!rpc_files.load(archive,unsigned(bytes))){
                log("NABU FASTRPC: original-file archive missing/invalid bytes=%llu\n",bytes);return false;
            }
            log("NABU FASTRPC: original-file archive entries=%u bytes=%u\n",rpc_files.entries(),rpc_files.size());
        }
        const uint8_t *header = hakios_image_file("fw", "slpi_nb.mdt", &bytes, nullptr);
        if (!NabuSlpi::parse_image(header, bytes, image)) { log("NABU SLPI: invalid/missing MDT bytes=%llu\n", bytes); return false; }
        uint64_t file_bytes = 0, memory_bytes = 0;
        for (unsigned i = 0; i < image.count; ++i) {
            NabuSlpi::Segment &segment = image.segments[i];
            if (segment.file_bytes) {
                char name[24]; snprintf(name, sizeof(name), "slpi_nb.b%02u", segment.index);
                segment.file = hakios_image_file("fw", name, &bytes, nullptr);
                if (!segment.file || bytes != segment.file_bytes) { log("NABU SLPI: segment=%u expected=%u bytes=%llu unavailable\n", segment.index, segment.file_bytes, bytes); return false; }
            }
            file_bytes += segment.file_bytes; memory_bytes += segment.memory_bytes;
        }
        log("NABU SLPI: firmware MDT=%u segments=%u file-bytes=%llu memory-bytes=%llu reserved=%#x+%#x\n",
            image.metadata_bytes, image.count, file_bytes, memory_bytes, NabuSlpi::MemoryBase, NabuSlpi::MemorySize);
        metadata = IOMallocContiguous(NabuSlpi::MetadataLimit, NabuSlpi::MetadataLimit, &metadata_pa);
        if (!metadata) return false;
        bzero(metadata, NabuSlpi::MetadataLimit); memcpy(metadata, image.metadata, image.metadata_bytes);
        for (uintptr_t at = (uintptr_t)metadata; at < (uintptr_t)metadata + NabuSlpi::MetadataLimit; at += 64)
            __asm__ volatile("dc civac, %0" : : "r"(at));
        __asm__ volatile("dsb sy" ::: "memory");
        aop = map("AOP", 0x0c300000, 0x1000, VM_WIMG_IO);
        ipc = map("APCS", 0x17c0000c, 4, VM_WIMG_IO);
        rsc = map("RPMh", 0x18220000, 0x4000, VM_WIMG_IO);
        smem_va = map("SMEM", 0x86000000, NabuSlpi::SmemSize, VM_WIMG_IO);
        hwlock = map("SMEM-lock3", 0x01f43000, 0x1000, VM_WIMG_IO);
        if (!aop || !ipc || !rsc || !smem_va || !hwlock) return false;
        smem = {(const volatile uint8_t *)smem_va, NabuSlpi::SmemSize};
        uint32_t base, line;
        if (!NabuSlpi::partition(smem, base, line)) { log("NABU SLPI: no host3/common SMEM partition\n"); return false; }
        log("NABU SLPI: SMEM selected hosts=%u:%u base=%#x size=%#x line=%u\n", smem.u16(base + 4), smem.u16(base + 6), base, smem.u32(base + 8), line);
        log("NABU SLPI: SMP2P inbound=%u SLPI->APPS outbound=%u APPS->SLPI\n", NabuSlpi::Incoming, NabuSlpi::Outgoing);
        NabuSmemItem existing;
        if (NabuSlpi::find(smem, NabuSlpi::Incoming, existing) || NabuSlpi::find(smem, NabuSlpi::Outgoing, existing)) {
            log("NABU SLPI: preexisting SMP2P edge; cold-boot trial stops before PAS/AOP\n"); return false;
        }
        if (!allocate(NabuSlpi::Outgoing, NabuSlpi::Smp2pBytes, our_item)) return false;
        NabuSlpi::publish_smp2p(*this, our_item); wr(ipc, 1u << NabuSlpi::Smp2pDoorbell);
        uint32_t descriptor = 0, fifo = 0;
        if (!allocate(478, 32, descriptor) || !allocate(479, 16384, fifo)) return false;
        put(descriptor + 4, 0); put(descriptor + 8, 0); // APPS TX head / RX tail only
        log("NABU SLPI: SMP2P master-kernel published; host3 GLINK APPS queues prepared\n"); publish();
        return true;
    }
    bool qmp_open() {
        if (rd(aop) != 0x4d41494c || rd(aop + 4) != 1) return false;
        uint32_t offset = rd(aop + 0x38), size = rd(aop + 0x34);
        if (offset < 0x3c || offset > 0x1000 || size < 68 || size > 0x1000 - offset) return false;
        wr(aop + 0x10, rd(aop + 0x0c)); wr(aop + 0x24, 0xffff); wr(ipc, 1);
        if (!wait_value(aop + 0x28, 0xffff, 1000)) return false;
        wr(aop + 0x2c, 0xffff); wr(ipc, 1);
        if (!wait_value(aop + 0x14, 0xffff, 1000)) return false;
        wr(aop + 0x18, 0xffff); wr(ipc, 1);
        if (!wait_value(aop + 0x30, 0xffff, 1000)) return false;
        mailbox = offset; return true;
    }
    bool aop_vote(bool on) {
        lck_mtx_lock(&hakios_aop_mailbox_lock);
        bool open = mailbox || qmp_open(), ok = false;
        if (open && wait_value(aop + mailbox, 0, 1000)) {
            char message[64]{};
            snprintf(message, sizeof(message), "{class: image, res: load_state, name: slpi, val: %s}", on ? "on" : "off");
            for (unsigned i = 0; i < 16; ++i) wr(aop + mailbox + 4 + i * 4, NabuSlpi::le32((const uint8_t *)message + i * 4));
            wr(aop + mailbox, sizeof(message)); wr(ipc, 1);
            ok = wait_value(aop + mailbox, 0, 1000);
        }
        lck_mtx_unlock(&hakios_aop_mailbox_lock);
        log("NABU SLPI: AOP slpi=%s open=%u acknowledged=%u\n", on ? "on" : "off", open, ok); publish();
        return ok;
    }
    bool proxy_vote() {
        vm_offset_t db_va=map("command-db",0x85f20000,0x20000,VM_WIMG_IO);
        if(!db_va)return false;
        NabuSmem db{(const volatile uint8_t*)db_va,0x20000};
        uint32_t address[3]{},value[3]{};
        if(db.u32(4)==0x0c0330db)for(unsigned s=0;s<8;++s) {
            unsigned slave=8+s*16,first=144+db.u16(slave+2),count=db.u16(slave+6);
            if(!db.u16(slave)||!db.span(first,count*24))continue;
            for(unsigned i=0;i<count;++i) {
                unsigned at=first+i*24;char name[9]{};
                for(unsigned j=0;j<8;++j)name[j]=db.data[at+j];
                if(!strcmp(name,"xo.lvl")){address[2]=db.u32(at+16);value[2]=3;}
                int slot=!strcmp(name,"lcx.lvl")?0:!strcmp(name,"lmx.lvl")?1:-1;
                if(slot<0)continue;
                unsigned aux=144+db.u16(slave+4)+db.u16(at+22),length=db.u16(at+20);
                if(!db.span(aux,length))continue;
                // DT supply phandles 0x6c/0x7e resolve to LCX/LMX (not CX/MX).
                // Both specify 385: TURBO384 + regulator consumer offset1.
                for(unsigned level=0;level<length/2;++level)if(db.u16(aux+level*2)>=384) {
                    address[slot]=db.u32(at+16);value[slot]=level;
                    log("NABU SLPI: %s resource=%#x position=%u raw-level=%u\n",name,address[slot],level,db.u16(aux+level*2));break;
                }
            }
        }
        unmap(db_va,0x20000);if(!address[0]||!address[1]||!address[2])return false;
        lck_mtx_lock(&hakios_rsc_lock);vm_offset_t tcs=rsc+0xd00;
        if(!rd(tcs+0x18)||rd(tcs+0x1c)){lck_mtx_unlock(&hakios_rsc_lock);return false;}
        wr(rsc+0xd08,1);
        for(unsigned i=0;i<3;++i){wr(tcs+0x30+i*20,0x10108);wr(tcs+0x34+i*20,address[i]);wr(tcs+0x38+i*20,value[i]);}
        wr(tcs+0x10,7);wr(tcs+0x1c,7);wr(tcs+0x14,1u<<16);wr(tcs+0x14,(1u<<16)|(1u<<24));
        bool done=false;for(unsigned i=0;i<5000;++i){if(rd(rsc+0xd04)&1){done=true;break;}IODelay(10);}
        uint32_t status[3]={rd(tcs+0x3c),rd(tcs+0x50),rd(tcs+0x64)};
        wr(tcs+0x14,0);wr(tcs+0x1c,0);wr(tcs+0x10,0);wr(rsc+0xd08,1);lck_mtx_unlock(&hakios_rsc_lock);
        log("NABU SLPI: LCX/LMX/XO proxy done=%u status=%#x,%#x,%#x; shared votes retained\n",done,status[0],status[1],status[2]);
        return done&&(status[0]&0x10000)&&(status[1]&0x10000)&&(status[2]&0x10000);
    }
    bool init_image() { return pas(1, 0x82, metadata_pa); }
    bool memory_setup() { return pas(2, 3, NabuSlpi::MemoryBase, image.load_bytes); }
    bool copy_segments() {
        for (unsigned i = 0; i < image.count; ++i) {
            const NabuSlpi::Segment &segment = image.segments[i];
            vm_offset_t page = trunc_page(segment.physical);
            vm_size_t bytes = round_page(segment.physical - page + segment.memory_bytes);
            vm_offset_t mapping = map("segment", page, bytes, VM_WIMG_WCOMB);
            if (!mapping) return false;
            vm_offset_t target = mapping + segment.physical - page;
            if (segment.file_bytes) memcpy((void *)target, segment.file, segment.file_bytes);
            bzero((void *)(target + segment.file_bytes), segment.memory_bytes - segment.file_bytes);
            __asm__ volatile("dsb sy" ::: "memory"); unmap(mapping, bytes);
            log("NABU SLPI: copied b%02u pa=%#x file=%u memory=%u\n", segment.index, segment.physical, segment.file_bytes, segment.memory_bytes);
        }
        publish(); return true;
    }
    bool auth_reset() { return pas(5, 1); }
    NabuSlpi::Peer state() {
        NabuSlpi::Peer peer = NabuSlpi::peer(smem);
        if (!peer.valid) return peer;
        put(our_item + 4, ((peer.features & 1) << 8) | 1);
        uint32_t flags = smem.u32(our_item + 16), ack = (peer.flags & 1) ? 2 : 0;
        if ((peer.features & 1) && (flags & 2) != ack) {
            put(our_item + 16, (flags & ~2u) | ack); wr(ipc, 1u << NabuSlpi::Smp2pDoorbell);
        }
        if (peer.state != last_state) {
            last_state = peer.state;
            log("NABU SLPI: slave-kernel=%#x fatal=%u ready=%u handover=%u stop-ack=%u shutdown-ack=%u\n",
                peer.state, !!(peer.state & 1), !!(peer.state & 2), !!(peer.state & 4), !!(peer.state & 8), !!(peer.state & 128)); publish();
        }
        return peer;
    }
    bool wait_ready() {
        for (unsigned i = 0; i < 1000; ++i) {
            NabuSlpi::Peer peer = state();
            if (peer.valid && (peer.state & 1)) return false;
            if (peer.valid && (peer.state & 2)) return true;
            IOSleep(10);
        }
        log("NABU SLPI: ready wait timed out after 10000ms\n"); return false;
    }
    void observe() {
        NabuSmemItem item;
        const unsigned smp2p_ids[] = {NabuSlpi::Incoming, NabuSlpi::Outgoing};
        for (unsigned id : smp2p_ids) {
            bool found = NabuSlpi::find(smem, uint16_t(id), item);
            log("NABU SLPI: SMP2P item=%u found=%u bytes=%u\n", id, found, found ? item.size : 0);
            if (found && item.size >= 20) {
                log("NABU SLPI: SMP2P item=%u magic=%#x version/features=%#x pid=%#x entries=%#x flags=%#x\n",
                    id, smem.u32(item.offset), smem.u32(item.offset+4), smem.u32(item.offset+8),
                    smem.u32(item.offset+12), smem.u32(item.offset+16));
            }
        }
        for(unsigned id=478;id<=480;++id){bool found=NabuSlpi::find(smem,uint16_t(id),item);log("NABU SLPI: host3 item=%u found=%u bytes=%u\n",id,found,found?item.size:0);}
        uint32_t base,line;
        if(smem.partition(0xfffe,&base,&line)&&smem.item_in(base,line,424,&item)){
            char reason[193]{};unsigned n=item.size<sizeof(reason)-1?item.size:sizeof(reason)-1;
            for(unsigned i=0;i<n;++i){reason[i]=smem.data[item.offset+i];if(!reason[i])break;}
            log("NABU SLPI: crash-reason item424=%s\n",reason[0]?reason:"(empty)");
        }
        publish();
    }
    void server(uint32_t command,uint32_t service,uint32_t instance,uint32_t node,uint32_t port){
        log("NABU SLPI QRTR: command=%u service=%u instance=%#x node=%u port=%u\n",command,service,instance,node,port);
    }
    bool send_ssc(uint32_t node,uint32_t port,uint32_t from,const uint8_t *data,uint32_t size){
        return glink.send_data(node,port,from,data,size);
    }
    static void receive_ssc(void *context,uint32_t node,uint32_t port,uint32_t local_port,const uint8_t *data,uint32_t size){
        Trial &trial=*static_cast<Trial *>(context);
#if NABU_SLPI_NATIVE
        if(slpi_mode==4&&trial.native_controls.receive(node,port,local_port,data,size,trial.native_now_ms))return;
#endif
        if(local_port==NabuSsc::Registry<Trial>::ClientPort)trial.registry.receive(node,port,data,size);
        else trial.census.receive(node,port,local_port,data,size);
    }
    static void receive_rpc(void *context,const uint8_t *data,uint32_t size){static_cast<Trial *>(context)->rpc.receive(data,size);}
    void ssc_event(unsigned type,NabuSsc::Suid suid,uint32_t id,uint64_t ticks,NabuSsc::Span payload){
        const char *name=NabuSsc::Census<Trial>::type(type);
        if(id==NabuSsc::SampleEvent){
            uint64_t mach,virtual_ticks,physical_ticks,frequency;
            clock_get_uptime(&mach);
            __asm__ volatile("mrs %0, cntvct_el0\n\tmrs %1, cntpct_el0\n\tmrs %2, cntfrq_el0"
                : "=r"(virtual_ticks),"=r"(physical_ticks),"=r"(frequency));
            log("NABU SSC CLOCK: type=%s ssc=%llu mach=%llu virtual=%llu physical=%llu frequency=%llu\n",
                name,ticks,mach,virtual_ticks,physical_ticks,frequency);
        }
        log("NABU SSC EVENT: type=%s id=%u suid=%016llx%016llx ticks=%llu bytes=%u\n",
            name,id,suid.high,suid.low,ticks,unsigned(payload.size));
        for(unsigned at=0;at<payload.size;at+=96){
            char hex[193];unsigned n=unsigned(payload.size)-at;if(n>96)n=96;
            const char digits[]="0123456789abcdef";
            for(unsigned i=0;i<n;++i){uint8_t b=payload.data[at+i];hex[i*2]=digits[b>>4];hex[i*2+1]=digits[b&15];}
            hex[n*2]=0;
            log("NABU SSC DATA: type=%s id=%u ticks=%llu offset=%u hex=%s\n",name,id,ticks,at,hex);
        }
    }
    void ssc_summary(){
        const auto &r=census.result;
        log("NABU SSC: started=%u done=%u tx=%u responses=%u invalid=%u foreign=%u qmi-failures=%u errors=%u streams=%u\n",
            r.started,r.done,r.sent,r.responses,r.invalid,r.foreign,r.qmi_failures,r.errors,census.stream_count);
        for(unsigned i=0;i<NabuSsc::Census<Trial>::TypeCount;++i){
            const auto &d=census.discovery[i];
            log("NABU SSC: type=%s state=%u candidates=%u\n",NabuSsc::Census<Trial>::type(i),unsigned(d.state),d.count);
            for(unsigned c=0;c<d.count;++c){
                const auto &a=d.candidates[c].attributes;
                log("NABU SSC: type=%s name=%s available=%u physical-present=%u physical=%u state=%u\n",
                    d.data_type,a.name,a.available,a.has(21),a.physical,unsigned(d.candidates[c].state));
            }
        }
        for(unsigned i=0;i<census.stream_count;++i){
            const auto &s=census.streams[i];
            log("NABU SSC: stream=%s configured=%u disabled=%u samples=%u nonmonotonic=%u first=%llu last=%llu accuracy=%u\n",
                NabuSsc::Census<Trial>::type(s.type),s.configured,s.disabled,s.samples,s.nonmonotonic,s.first,s.last,s.latest.status);
        }
        publish();
    }
    void probe(){
        NabuSmemItem desc,tx,rx;bool found=false;
        for(unsigned i=0;i<100;++i){if(NabuSlpi::find(smem,480,rx)){found=true;break;}if(state().state&1)break;IOSleep(10);}
        if(!found||!NabuSlpi::find(smem,478,desc)||desc.size!=32||!NabuSlpi::find(smem,479,tx)){
            log("NABU SLPI: GLINK queues unavailable; census ended\n");return;
        }
        if(slpi_mode>=3){
            if(!prepare_dma())return;
            glink.enable_rpc(receive_rpc,this);glink.sampling_window(45000);
        }
#if NABU_SLPI_NATIVE
        if(slpi_mode==4){
            if(!native_begin())return;
            glink.sampling_window(0);
        }
#endif
        if(!glink.begin(desc.offset,tx.offset,tx.size,rx.offset,rx.size,slpi_mode>=2,receive_ssc,this)){
#if NABU_SLPI_NATIVE
            if(slpi_mode==4)native_end();
#endif
            return;
        }
        uint64_t started;clock_get_uptime(&started);
        while(!glink.done()){
            uint64_t current,nanos;clock_get_uptime(&current);absolutetime_to_nanoseconds(current-started,&nanos);
            uint64_t elapsed=nanos/1000000;
            bool established=false;
#if NABU_SLPI_NATIVE
            if(slpi_mode==4){
                native_now_ms=elapsed;
                for(unsigned kind=0;kind<NabuSensorKindCount;++kind)established|=native.accepted[kind]!=0;
            }
#endif
            if(elapsed>60000&&!established){glink.abort();break;}
            NabuSlpi::Peer p=state();if(!p.valid||(p.state&3)!=2){glink.abort();break;}
            glink.step(uint32_t(elapsed));
            if(slpi_mode>=2&&!glink.done()){
                const auto &r=glink.result();
                if(slpi_mode>=3){
                    if(!dma_healthy()){glink.abort();break;}
                    if(r.rpc_opened&&!rpc.result.started)rpc.start(static_cast<uint8_t *>(dma.blocks[0].cpu),NabuSlpiDma::iova_base,elapsed);
                    rpc.tick(elapsed);
                    if(rpc.result.failed){glink.finish();IOSleep(10);continue;}
                    if(rpc.result.ready&&r.ssc_found&&!registry.started)registry.start(r.ssc_node,r.ssc_port,elapsed);
                    registry.tick(elapsed);
                    if(registry.timeout||registry.failed){glink.finish();IOSleep(10);continue;}
                }
                if(r.ssc_found&&!census.result.started&&(slpi_mode==2||registry.ready))census.start(r.ssc_node,r.ssc_port,elapsed);
                if(census.result.started&&!r.ssc_found){glink.abort();break;}
                census.tick(elapsed);
#if NABU_SLPI_NATIVE
                if(slpi_mode==4)native_tick();
#endif
                if(census.result.done)glink.finish();
            }
            if(!glink.done())IOSleep(10);
        }
#if NABU_SLPI_NATIVE
        if(slpi_mode==4)native_end();
#endif
        const auto &r=glink.result();
        log("NABU SLPI: GLINK negotiated=%u open=%u tx=%u rx=%u QRTR=%u servers=%u SSC=%u node=%u port=%u instance=%#x close=%u timeout=%u error=%u\n",
            r.negotiated,r.opened,r.tx,r.rx,r.qrtr_packets,r.servers,r.ssc_found,r.ssc_node,r.ssc_port,r.ssc_instance,r.close_ack,r.timeout,r.error);
        if(slpi_mode>=2)ssc_summary();
        if(slpi_mode>=3){
            const auto &f=rpc.result;
            log("NABU FASTRPC: open=%u rcid=%u tx=%u rx=%u close=%u stage=%u attached=%u registered=%u ready=%u failed=%u status=%d calls=%u replies=%u reverse=%u invalid=%u\n",
                r.rpc_opened,r.rpc_rcid,r.rpc_tx,r.rpc_rx,r.rpc_close_ack,rpc.stage(),f.attached,f.registered,f.ready,f.failed,f.status,f.calls,f.responses,f.reverse_calls,f.invalid);
            log("NABU SSC REGISTRY: started=%u sent=%u replies=%u events=%u ready=%u candidates=%u timeout=%u failed=%u invalid=%u\n",
                registry.started,registry.sent,registry.responses,registry.events,registry.ready,registry.candidates,registry.timeout,registry.failed,registry.invalid);
        }
        log("NABU SLPI: live-census=%u FastRPC=%u source-mode=%u; native HID/API results require userland verification\n",slpi_mode>=2,slpi_mode>=3,slpi_mode==4);publish();
    }
    bool request_stop(){
        put(our_item+36,1);wr(ipc,1u<<NabuSlpi::Smp2pDoorbell);bool ack=false;
        for(unsigned i=0;i<500;++i){auto p=state();if(p.valid&&(p.state&8)){ack=true;break;}if(p.valid&&(p.state&1))break;IOSleep(10);}
        put(our_item+36,0);wr(ipc,1u<<NabuSlpi::Smp2pDoorbell);
        log("NABU SLPI: force-stop cleared ack=%u\n",ack);return ack;
    }
    bool shutdown(){return pas(6,1);}
    void release(){
        if(dma_va){
            bool freed=dma.release_after_stop();log("NABU SLPI DMA: released=%u status=%u phase=%u\n",freed,dma.status,dma.stop.phase);
            if(freed){unmap(dma_va,0x100000);dma_va=0;dma_active=false;}
        }
        if(metadata){IOFreeContiguous(metadata,NabuSlpi::MetadataLimit);metadata=nullptr;}
        if(hwlock){unmap(hwlock,0x1000);hwlock=0;}if(smem_va){unmap(smem_va,NabuSlpi::SmemSize);smem_va=0;}
        if(rsc){unmap(rsc,0x4000);rsc=0;}if(ipc){unmap(ipc,4);ipc=0;}if(aop){unmap(aop,0x1000);aop=0;}
    }
};
static Trial trial;
static void run_worker(){
    log("NABU SLPI: opt-in SLPI mode=%u begins\n",slpi_mode);publish();
    auto r=NabuSlpi::run(trial);
#if NABU_SLPI_NATIVE
    if(slpi_mode==4)trial.native_end();
#endif
    log("NABU SLPI: prepared=%u AOP=%u proxy=%u init=%u mem=%u copied=%u auth=%u ready=%u stop=%u shutdown=%u off=%u retained=%u\n",
        r.prepared,r.aop_on,r.proxy,r.init,r.memory,r.copied,r.auth,r.ready,r.stop_ack,r.shutdown,r.off,r.retained);
    if(r.retained)log("NABU SLPI: PAS shutdown failed; metadata and mappings retained until reboot\n");publish();
}
static void continuous_worker(void *,wait_result_t){run_worker();thread_terminate(current_thread());}
static void worker(thread_call_param_t,thread_call_param_t){
    if(slpi_mode==4){
        thread_t thread; kern_return_t status=kernel_thread_start(continuous_worker,nullptr,&thread);
        if(status==KERN_SUCCESS)thread_deallocate(thread);
        else{log("NABU SENSOR: dedicated worker start failed=%d\n",status);publish();}
    }else run_worker();
}
}
extern "C" void nabu_slpi_start(){
    if(slpi_call||!PE_parse_boot_argn("nabu-slpi",&slpi_mode,sizeof(slpi_mode))||slpi_mode<1||slpi_mode>4)return;
#if NABU_SLPI_NATIVE
    if(slpi_mode==4)PE_parse_boot_argn("nabu-ssc-clock",&slpi_clock_epoch,sizeof(slpi_clock_epoch));
#else
    if(slpi_mode==4){log("NABU SENSOR: continuous source not linked in this diagnostic kernel\n");publish();return;}
#endif
    slpi_call=thread_call_allocate(worker,nullptr);if(!slpi_call)return;
    log("NABU SLPI: nabu-slpi=%u scheduled after 60 seconds\n",slpi_mode);publish();
    uint64_t deadline;clock_interval_to_deadline(60,NSEC_PER_SEC,&deadline);thread_call_enter_delayed(slpi_call,deadline);
}
