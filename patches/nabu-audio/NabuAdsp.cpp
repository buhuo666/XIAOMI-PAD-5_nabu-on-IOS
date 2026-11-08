// SPDX-License-Identifier: BSD-2-Clause-Patent
// Nabu PAS1 boot/control trial. nabu-adsp=1 runs once, 40 seconds after startup.
// It stops the DSP after collecting readiness and host-2 GLINK evidence.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>
#include <kern/clock.h>
#include <kern/thread_call.h>
#include <kern/locks.h>
#include <mach/vm_param.h>
#include <vm/memory_types.h>
#include <pexpert/pexpert.h>
#include "NabuAdspProtocol.h"
#include "NabuAdspGlink.h"
#include "NabuAmpI2c.h"
#include "NabuCs35l41.h"
#include "NabuCs35l41Run.h"
#include "NabuSlimNgd.h"
#include "NabuTavil.h"
#include "../nabu-wireless/NabuWlanController.h"

extern "C" vm_offset_t ml_io_map_unmappable(vm_offset_t, vm_size_t, unsigned int);
extern "C" void ml_io_unmap(vm_offset_t, vm_size_t);
extern "C" const uint8_t *hakios_image_file(const char *, const char *, uint64_t *, int *);
extern "C" void loader_log_line(const char *);
extern "C" lck_mtx_t hakios_aop_mailbox_lock;
extern "C" lck_mtx_t hakios_rsc_lock;
extern "C" lck_mtx_t hakios_smem_alloc_lock;
extern "C" lck_mtx_t hakios_smmu_lock;
extern "C" vm_offset_t ml_vtophys(vm_offset_t);
extern "C" void hakios_audio_set_sink(const char *,uint32_t (*)(const int16_t *,uint32_t));
extern "C" bool hakios_audio_volume(uint32_t *,bool *,uint32_t *);

namespace {
static thread_call_t adsp_call;
static char report[24576];
static unsigned report_bytes;
static int16_t *native_ring;
static constexpr uint32_t NativeRingFrames=32768;
static uint32_t native_head,native_tail;
static uint64_t native_received,native_dropped,native_fed,native_silence;
static uint32_t native_peak;
static uint32_t native_sink(const int16_t *samples,uint32_t frames) {
    uint32_t head=native_head,tail=__atomic_load_n(&native_tail,__ATOMIC_ACQUIRE);
    uint32_t room=NativeRingFrames-(head-tail),take=frames<room?frames:room;
    for(unsigned i=0;i<take;++i) {
        unsigned at=(head+i)&(NativeRingFrames-1);
        native_ring[at*2]=samples[i*2];native_ring[at*2+1]=samples[i*2+1];
        for(unsigned ch=0;ch<2;++ch) {int32_t sample=samples[i*2+ch];uint32_t peak=sample<0?-sample:sample;if(peak>native_peak)native_peak=peak;}
    }
    __atomic_store_n(&native_head,head+take,__ATOMIC_RELEASE);
    native_received+=take;native_dropped+=frames-take;return take;
}

static void publish() {
    IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane);
    if (chosen) { chosen->setProperty("nabu-adsp-report", report); chosen->release(); }
}
static void log(const char *format, ...) __attribute__((format(printf, 1, 2)));
static void log(const char *format, ...) {
    char line[512]; va_list args; va_start(args, format);
    vsnprintf(line, sizeof(line), format, args); va_end(args); IOLog("%s", line);
    unsigned bytes = unsigned(strlen(line));
    if (bytes < sizeof(report) - report_bytes) { memcpy(report + report_bytes, line, bytes + 1); report_bytes += bytes; }
}
static uint32_t rd(vm_offset_t at) { return *(volatile uint32_t *)at; }
static void wr(vm_offset_t at, uint32_t value) { *(volatile uint32_t *)at = value; __asm__ volatile("dsb sy" ::: "memory"); }
static bool wait_value(vm_offset_t at, uint32_t value, unsigned ms) {
    for (unsigned i = 0; i < ms; ++i) { if (rd(at) == value) return true; IOSleep(1); }
    return false;
}
static vm_offset_t map(const char *name, vm_offset_t physical, vm_size_t bytes, unsigned attributes) {
    vm_offset_t address = ml_io_map_unmappable(physical, bytes, attributes);
    log("NABU ADSP: map %s pa=%#llx bytes=%#llx ok=%u\n", name, (uint64_t)physical, (uint64_t)bytes, address != 0);
    return address;
}
static void unmap(vm_offset_t address, vm_size_t bytes) {
    // io_map returns allocation base + physical page offset. ml_io_unmap
    // expects the full VM allocation, including on 16K VM / 4K hardware pages.
    vm_offset_t base = trunc_page(address);
    vm_size_t span = round_page(address - base + bytes);
    log("NABU ADSP: unmap va=%#llx bytes=%#llx base=%#llx span=%#llx\n",
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
    char *at = trace_text(line, "NABU ADSP SMC "); at = trace_text(at, phase);
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
    log("NABU ADSP: PAS1 command=%u arg1=%#llx arg2=%#llx\n", command, b, c); publish();
    for (unsigned attempt = 0; attempt < 100; ++attempt) {
        uint64_t request = attempt ? 1 : 0x42000200 | command;
        trace_smc("enter", command, attempt, request, types, session);
        register uint64_t x0 __asm__("x0") = request;
        register uint64_t x1 __asm__("x1") = types;
        register uint64_t x2 __asm__("x2") = 1;
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
            log("NABU ADSP: PAS1 command=%u result=%lld response=%#llx\n", command, result, response); publish();
            return result == 0 && response == 0;
        }
    }
    log("NABU ADSP: PAS1 command=%u continuation limit reached\n", command); return false;
}

struct Trial {
    NabuAdsp::Image image{};
    vm_offset_t aop = 0, ipc = 0, rsc = 0, smem_va = 0, hwlock = 0;
    uint32_t mailbox = 0, our_item = 0;
    void *metadata = nullptr;
    IOPhysicalAddress metadata_pa = 0;
    NabuSmem smem{};
    uint32_t last_state = 0xffffffff;
    NabuAdspGlink::Link<Trial> glink{*this};
    NabuAudioDma dma{};
    NabuWlanFault dma_faults{};
    vm_offset_t dma_va = 0;
    bool dma_active = false;
    vm_offset_t tdm_pins=0,amp_reset=0;
    uint32_t tdm_config[6]{},tdm_output[6]{},amp_reset_config=0,amp_reset_output=0;
    bool retain_for_amp=false;
    struct AmpPins {
        vm_offset_t base=0;
        uint32_t config[2]{},output[2]{};
        void take() {for(unsigned i=0;i<2;++i){config[i]=rd(base+i*0x1000);output[i]=rd(base+i*0x1000+4)&2;}}
        void restore() {
            for(unsigned i=0;i<2;++i)wr(base+i*0x1000+4,output[i]);
            for(unsigned i=0;i<2;++i)wr(base+i*0x1000,config[i]);
        }
        void line(bool scl,bool high) {
            vm_offset_t at=base+(scl?0x1000:0);
            wr(at+4,0);wr(at,3|(high?0:0x200)); // input releases, output only drives low
        }
        bool level(bool scl) {return (rd(base+(scl?0x1000:0)+4)&1)!=0;}
        void delay_us(unsigned us) {IODelay(us);}
    } amp_io{};
    NabuAmpI2c::Bus<AmpPins> amp_bus{amp_io};
    struct AmpBackend {
        NabuAmpI2c::Bus<AmpPins> &bus;
        uint8_t address;
        unsigned bus_error=0;
        bool result(bool ok) {if(!ok&&!bus_error)bus_error=bus.error();return ok;}
        bool read(uint32_t reg,uint32_t &value) {return result(bus.read_register(address,reg,value));}
        bool write(uint32_t reg,uint32_t value) {return result(bus.write_register(address,reg,value));}
        bool raw_write(uint32_t reg,const uint8_t *data,uint32_t bytes) {return result(bus.raw_write(address,reg,data,bytes));}
        void delay_us(uint32_t us) {if(us>=1000)IOSleep((us+999)/1000);else IODelay(us);}
        const uint8_t *firmware(const char *name,uint32_t &bytes) {
            uint64_t size=0;const uint8_t *data=hakios_image_file("fw",name,&size,nullptr);
            bytes=uint32_t(size);return data;
        }
    };
    AmpBackend amp_backend[4]={{amp_bus,0x43},{amp_bus,0x41},{amp_bus,0x42},{amp_bus,0x40}};
    using AmpCore=NabuCs35l41Run::Trial<AmpBackend>;
    AmpCore amp_core[4]={AmpCore{amp_backend[0]},AmpCore{amp_backend[1]},AmpCore{amp_backend[2]},AmpCore{amp_backend[3]}};
    unsigned amp_touched=0;
    bool amps_finished=false;
    struct SlimRegisters {
        vm_offset_t base=0;
        uint32_t read(uint32_t offset) {return rd(base+offset);}
        void write(uint32_t offset,uint32_t value) {wr(base+offset,value);}
    } slim_io{};
    NabuSlimNgd::Bus<SlimRegisters> slim_bus{slim_io};
    NabuTavil::Codec<NabuSlimNgd::Bus<SlimRegisters>> codec{slim_bus};
    vm_offset_t codec_reset=0;
    uint32_t codec_reset_config=0,codec_reset_output=0;
    bool mic_attempted=false,mic_started=false,mic_finished=false,codec_begun=false;
    bool native_attached=false;
    uint32_t native_generation=0,native_gain=1u<<24,native_volume_below=0;
    bool native_muted=false;
    unsigned stream_report_start=0;
    void microphone_report() {
        const auto &s=glink.slim_result();const auto &n=slim_bus.result();const auto &c=codec.result();
        log("NABU MIC QMI: open=%u peer=%u server=%u node=%u port=%#x select=%u active=%u released=%u rx=%u tx=%u error=%u result=%u code=%u\n",
            s.opened,s.peer,s.server,s.node,s.port,s.selected,s.active,s.released,s.rx,s.tx,s.error,s.qmi_result,s.qmi_error);
        log("NABU MIC NGD: version=%#x bank=%#x status=%#x interrupt=%#x capability=%u reported=%u ready=%u tx=%u rx=%u last=%#x/%#x error=%u\n",
            n.version,n.bank,n.status,n.interrupt,n.capability,n.reported,n.ready,n.tx,n.rx,n.last_tx0,n.last_rx0,n.error);
        log("NABU MIC TAVIL: PGD=%#x IFD=%#x phase=%u step=%u major=%#x minor=%#x identified=%u error=%u; physical capture not yet active\n",
            c.pgd,c.ifd,c.phase,c.step,c.major,c.minor,c.identified,c.error);publish();
    }
    bool codec_power() {
        vm_offset_t db_va=map("codec-command-db",0x85f20000,0x20000,VM_WIMG_IO);
        if(!db_va)return false;
        NabuSmem db{(const volatile uint8_t *)db_va,0x20000};uint32_t bob=0,clock=0;
        if(db.u32(4)==0x0c0330db)for(unsigned s=0;s<8;++s) {
            unsigned slave=8+s*16,first=144+db.u16(slave+2),count=db.u16(slave+6);
            if(!db.u16(slave)||!db.span(first,count*24))continue;
            for(unsigned i=0;i<count;++i) {
                unsigned at=first+i*24;char name[9]{};
                for(unsigned j=0;j<8;++j)name[j]=db.data[at+j];
                if(!strcmp(name,"bobc1"))bob=db.u32(at+16);
                if(!strcmp(name,"lnbclka2"))clock=db.u32(at+16);
            }
        }
        unmap(db_va,0x20000);
        if(!bob||!clock) {log("NABU MIC: missing original resource bob=%#x lnbclk=%#x\n",bob,clock);return false;}
        // S4 is the original 1.8V stub/always-on supply. BOB requests are in mV;
        // PMIC5 BOB mode2 is the original PASS default. Clock is an enable vote.
        uint32_t address[]={bob,bob+4,bob+8,clock+4},value[]={3300,1,2,1};
        lck_mtx_lock(&hakios_rsc_lock);vm_offset_t tcs=rsc+0xd00;
        if(!rd(tcs+0x18)||rd(tcs+0x1c)) {lck_mtx_unlock(&hakios_rsc_lock);return false;}
        wr(rsc+0xd08,1);
        for(unsigned i=0;i<4;++i) {wr(tcs+0x30+i*20,0x10108);wr(tcs+0x34+i*20,address[i]);wr(tcs+0x38+i*20,value[i]);}
        wr(tcs+0x10,15);wr(tcs+0x1c,15);wr(tcs+0x14,1u<<16);wr(tcs+0x14,(1u<<16)|(1u<<24));
        bool done=false;for(unsigned i=0;i<5000;++i) {if(rd(rsc+0xd04)&1) {done=true;break;}IODelay(10);}
        uint32_t status[4];for(unsigned i=0;i<4;++i) {status[i]=rd(tcs+0x3c+i*20);done=done&&bool(status[i]&0x10000);}
        wr(tcs+0x14,0);wr(tcs+0x1c,0);wr(tcs+0x10,0);wr(rsc+0xd08,1);lck_mtx_unlock(&hakios_rsc_lock);
        log("NABU MIC: S4=1800000uV fixed; BOB=%#x 3300mV/pass/enable LNBB2=%#x enable; acknowledged=%u status=%#x/%#x/%#x/%#x; shared votes retained until reboot\n",
            bob,clock,done,status[0],status[1],status[2],status[3]);return done;
    }
    bool prepare_microphone(uint32_t elapsed) {
        if(!codec_power())return false;
        codec_reset=map("Tavil-reset-GPIO143",0x3d8f000,0x1000,VM_WIMG_IO);
        if(!codec_reset)return false;
        codec_reset_config=rd(codec_reset);codec_reset_output=rd(codec_reset+4)&2;
        // Preserve an already active reset, as the original codec helper does.
        if(!(rd(codec_reset+4)&1)) {wr(codec_reset+4,0);wr(codec_reset,0x200);IOSleep(20);}
        wr(codec_reset+4,2);wr(codec_reset,0x2c1);IOSleep(20);
        slim_io.base=map("SLIM-NGD",0x171c0000,0x2c000,VM_WIMG_IO);
        if(!slim_io.base)return false;
        slim_bus.begin(elapsed);mic_started=true;return true;
    }
    void stop_microphone() {
        if(mic_started) {slim_bus.stop();mic_started=false;}
        if(slim_io.base) {unmap(slim_io.base,0x2c000);slim_io.base=0;}
        if(codec_reset) {
            wr(codec_reset+4,codec_reset_output);wr(codec_reset,codec_reset_config);
            unmap(codec_reset,0x1000);codec_reset=0;
        }
    }
    void slim_stop() {stop_microphone();}
    void microphone_step(uint32_t elapsed) {
        if(mic_finished)return;
        if(glink.slim_result().error!=NabuAdspSlim::Ok) {mic_finished=true;microphone_report();stop_microphone();glink.finish_slim();return;}
        if(!mic_attempted&&glink.slim_ready()) {
            mic_attempted=true;
            if(!prepare_microphone(elapsed)) {mic_finished=true;log("NABU MIC: codec power/reset preparation failed\n");microphone_report();stop_microphone();glink.finish_slim();}
        }
        if(!mic_started)return;
        slim_bus.step(elapsed);
        if(slim_bus.result().ready&&slim_bus.idle()&&!codec_begun) {codec.begin();codec_begun=true;}
        if(codec_begun)codec.step(elapsed);
        if(codec.done()||slim_bus.result().error) {
            mic_finished=true;microphone_report();
            if(!codec.result().identified) {stop_microphone();glink.finish_slim();}
        }
    }
    void stream_report() {
        report_bytes=stream_report_start;report[report_bytes]=0;
        const auto &p=glink.playback_result();
        log("NABU NATIVE AUDIO: attached=%u received=%llu fed=%llu silence=%llu dropped=%llu queued=%u peak=%u writes=%u done=%u underflows=%u failed=%u opcode=%#x status=%#x\n",
            native_attached,native_received,native_fed,native_silence,native_dropped,
            __atomic_load_n(&native_head,__ATOMIC_ACQUIRE)-native_tail,native_peak,p.writes,p.completions,p.underflows,p.failed,p.failed_opcode,p.status);
        log("NABU NATIVE VOLUME: eighths-below=%u muted=%u generation=%u gain-q24=%u\n",
            native_volume_below,native_muted,native_generation,native_gain);
        publish();
    }

    bool prepare_tdm_pins() {
        // Original quat_tdm pinctrl: SOUTH GPIO137..142, qua_mi2s function1.
        tdm_pins=map("quat-TDM-GPIO137-142",0x03d89000,0x6000,VM_WIMG_IO);
        if(!tdm_pins)return false;
        for(unsigned i=0;i<6;++i) {
            vm_offset_t at=tdm_pins+i*0x1000;
            tdm_config[i]=rd(at);tdm_output[i]=rd(at+4)&2;
            bool output=i<2||i==3||i==5;
            uint32_t config=4|((i<2?2:1)<<6)|(output?0x200:0);
            if(output)wr(at+4,2);
            wr(at,config);
            log("NABU AFE PINS: gpio%u config=%#x->%#x output=%#x->%#x\n",137+i,tdm_config[i],rd(at),tdm_output[i],rd(at+4));
        }
        return true;
    }
    void restore_audio_pins() {
        if(amp_io.base) {unmap(amp_io.base,0x2000);amp_io.base=0;}
        if(amp_reset) {
            wr(amp_reset+4,amp_reset_output);wr(amp_reset,amp_reset_config);
            log("NABU AMP CORE: reset restored=%#x/%#x after AFE teardown\n",rd(amp_reset),rd(amp_reset+4));
            unmap(amp_reset,0x1000);amp_reset=0;
        }
        if(tdm_pins) {
            for(unsigned i=0;i<6;++i)wr(tdm_pins+i*0x1000+4,tdm_output[i]);
            for(unsigned i=0;i<6;++i)wr(tdm_pins+i*0x1000,tdm_config[i]);
            log("NABU AFE PINS: six original GPIO configurations restored\n");
            unmap(tdm_pins,0x6000);tdm_pins=0;
        }
    }

    bool prepare_dma() {
        dma_va = map("audio-SMMU", 0x15000000, 0x100000, VM_WIMG_IO);
        if (!dma_va) return false;
        NabuAudioDma::Platform ops{}; ops.cookie = this;
        ops.allocate = [](void *, unsigned bytes) {
            void *cpu = IOMallocContiguous(bytes, 16384, nullptr);
            if (!cpu) return NabuAudioDma::Memory{};
            bzero(cpu, bytes);
            return NabuAudioDma::Memory{cpu, ml_vtophys((vm_offset_t)cpu)};
        };
        ops.release = [](void *, NabuAudioDma::Memory memory, unsigned bytes) { IOFreeContiguous(memory.cpu, bytes); };
        ops.publish = [](void *, void *cpu, unsigned bytes) {
            for (uintptr_t at = (uintptr_t)cpu; at < (uintptr_t)cpu + bytes; at += 64)
                __asm__ volatile("dc civac, %0" :: "r"(at) : "memory");
            __asm__ volatile("dsb sy" ::: "memory");
        };
        ops.lock = [](void *) { lck_mtx_lock(&hakios_smmu_lock); };
        ops.unlock = [](void *) { lck_mtx_unlock(&hakios_smmu_lock); };
        ops.io = {this, 0x100000,
            [](void *x, size_t at, uint32_t *v) { *v = rd(((Trial *)x)->dma_va + at); return 0; },
            [](void *x, size_t at, uint64_t *v) { *v = *(volatile uint64_t *)(((Trial *)x)->dma_va + at); return 0; },
            [](void *x, size_t at, uint32_t v) { wr(((Trial *)x)->dma_va + at, v); return 0; },
            [](void *x, size_t at, uint64_t v) { *(volatile uint64_t *)(((Trial *)x)->dma_va + at) = v; return 0; },
            [](void *) { __asm__ volatile("dsb sy" ::: "memory"); return 0; }};
        if (!dma.prepare(ops)) {
            log("NABU ADSP DMA: prepare failed phase=%u status=%u\n", dma.prepare_failure, dma.status);
            return false;
        }
        dma_active = dma.attach(
            [](void *x, unsigned bank, const ArmSmmu4KIo *io) {
                return nabu_smmu_fault_install((NabuWlanFault *)x, bank, io, NabuAudioDma::first_sid) ? 0 : -1;
            },
            [](void *x, unsigned) { nabu_smmu_fault_remove((NabuWlanFault *)x); }, &dma_faults);
        log("NABU ADSP DMA: attached=%u phase=%u status=%u sid=%#x bank=%u asid=%u slot=%u iova=%#llx bytes=%u pa=%#llx tables=%u\n",
            dma_active, dma.attach_phase, dma.status, NabuAudioDma::first_sid, dma.bank, dma.context.asid,
            dma.routes[0].slot, NabuAudioDma::iova_base, NabuAudioDma::block_bytes, dma.blocks[0].physical,
            (unsigned)dma.built.table_pages);
        if (!dma_active) log("NABU ADSP DMA: selection=%u conflict-slot=%u smr=%#x s2cr=%#x CB-stage=%u stream-stage=%u\n",
            dma.selection.stage, dma.selection.conflict_slot, dma.selection.conflict_smr,
            dma.selection.conflict_s2cr, dma.program.phase, dma.stream_result.phase);
        return dma_active;
    }
    bool dma_healthy() {
        NabuWlanFault::Record context{}, global{};
        uint32_t flags = dma_faults.snapshot(context, global);
        if (flags) {
            log("NABU ADSP DMA: fault flags=%u context=%#x address=%#llx sid=%#x global=%#x\n",
                flags, context.status, context.address, context.sid, global.status);
            dma.lost(); return false;
        }
        bool healthy = dma.observe();
        if (!healthy) log("NABU ADSP DMA: observation failed status=%u\n", dma.status);
        return healthy;
    }
    void prepare_pcm() {
        uint8_t *memory=(uint8_t *)dma.blocks[0].cpu;
        for(unsigned frame=0;frame<NabuAsmPcm::InputBytes/8;++frame)
            for(unsigned ch=0;ch<2;++ch)
                NabuAsmPcm::put32(memory+frame*8+ch*4,NabuAsmPcm::sample(frame,ch));
        memset(memory+NabuAsmPcm::OutputOffset,0xa5,NabuAsmPcm::OutputBytes);
        dma.platform.publish(dma.platform.cookie,memory,NabuAudioDma::block_bytes);
    }
    void observe_pcm() {
        const auto &p=glink.pcm_result();
        log("NABU ADSP PCM: open-sent=%u opened=%u input-format=%u output-format=%u running=%u read-sent=%u write-sent=%u eos-sent=%u read-done=%u write-done=%u close-sent=%u closed=%u failed=%u opcode=%#x status=%#x timeout=%u commands=%u ignored=%u\n",
            p.open_sent,p.opened,p.input_format,p.output_format,p.running,p.read_sent,p.write_sent,p.eos_sent,
            p.read_done,p.write_done,p.close_sent,p.closed,p.failed,p.failed_opcode,p.status,p.timeout,p.commands,p.ignored);
        log("NABU ADSP PCM: read-status=%#x write-status=%#x bytes=%u offset=%u flags=%#x frames=%u read-token=%#x write-token=%#x\n",
            p.read_status,p.write_status,p.read_bytes,p.read_offset,p.read_flags,p.read_frames,p.read_token,p.write_token);
        if(!dma_active||!p.read_done||p.read_status)return;
        uint8_t *output=(uint8_t *)dma.blocks[0].cpu+NabuAsmPcm::OutputOffset;
        for(uintptr_t at=(uintptr_t)output;at<(uintptr_t)output+NabuAsmPcm::OutputBytes;at+=64)
            __asm__ volatile("dc ivac, %0" :: "r"(at):"memory");
        __asm__ volatile("dsb sy" ::: "memory");
        unsigned matches=0,mismatches=0,changed=0;
        for(unsigned i=0;i<NabuAsmPcm::OutputBytes;++i)changed+=output[i]!=0xa5;
        const uint8_t *samples=output+p.read_offset;
        for(unsigned i=0;i<p.read_bytes/4;++i) {
            uint32_t expected=NabuAsmPcm::sample(i/2,i%2);
            if(NabuAsmPcm::u32(samples+i*4)==expected)++matches;else ++mismatches;
        }
        log("NABU ADSP PCM: output-changed-bytes=%u matched-words=%u mismatched-words=%u exact=%u; synthetic memory roundtrip, no speaker/microphone route\n",
            changed,matches,mismatches,p.read_bytes==NabuAsmPcm::InputBytes&&!mismatches&&!(p.read_flags&0x40000000));
        for(unsigned i=0;i<p.read_bytes/4&&i<8;++i)
            log("NABU ADSP PCM: sample[%u]=%#x expected=%#x\n",i,NabuAsmPcm::u32(samples+i*4),NabuAsmPcm::sample(i/2,i%2));
    }
    void observe_tdm_pins() {
        for(unsigned pin=0;pin<2;++pin) {
            uint32_t last=rd(tdm_pins+pin*0x1000+4)&1,changes=0,ones=0;
            uint64_t start,end,nanos;clock_get_uptime(&start);
            for(unsigned i=0;i<20000;++i) {
                uint32_t bit=rd(tdm_pins+pin*0x1000+4)&1;
                changes+=bit!=last;ones+=bit;last=bit;
            }
            clock_get_uptime(&end);absolutetime_to_nanoseconds(end-start,&nanos);
            log("NABU AFE PINS: gpio%u reads=20000 changes=%u ones=%u elapsed-ns=%llu; activity sample, not frequency measurement\n",137+pin,changes,ones,nanos);
        }
    }
    void report_amplifier(unsigned amp,const char *when) {
        const auto &k=amp_core[amp].result();const char *name=NabuCs35l41::Positions[amp].name;
        log("NABU AMP PLAY: %s %s started=%u enabled=%u complete=%u phase=%u error=%u reg=%#x detail=%#x bus-error=%u\n",
            name,when,k.started,k.output_enabled,k.complete,k.phase,k.error,k.failed_reg,k.detail,amp_backend[amp].bus_error);
        log("NABU AMP PLAY: %s HALO=%#x CSPL=%#x error=%#x heartbeat=%u->%u PLL=%#x raw3=%#x detect=%#x sample-rate=%#x DSP-clock=%#x override=%#x\n",
            name,k.halo_state,k.cspl_state,k.cspl_error,k.heartbeat_first,k.heartbeat_last,k.pll_running,k.pll_raw3,
            k.clock_detect,k.global_sample_rate,k.dsp_clock,k.ctrl_override);
        log("NABU AMP PLAY: %s resume=%u/%u/%u pause=%u/%u/%u volume-code=%#x volume=%#x PWR-active=%#x/%#x DAC=%#x\n",
            name,k.resume.sent,k.resume.ack,k.resume.state,k.pause.sent,k.pause.ack,k.pause.state,
            k.volume_code,k.volume_reg,k.pwr1_active,k.pwr2_active,k.dac_source);
        log("NABU AMP PLAY: %s faults=%#x/%#x/%#x/%#x MPU=%#x/%#x/%#x muted=%u PDN=%u cleanup=%u core-off=%u output-off=%u clocks-may-stop=%u\n",
            name,k.fault_running[0],k.fault_running[1],k.fault_running[2],k.fault_running[3],
            k.mpu_fault[0],k.mpu_fault[1],k.mpu_fault[2],k.muted,k.pdn_done,k.cleanup,k.core_off,k.output_off,k.clocks_may_stop);
    }
    bool prepare_amplifiers() {
        amp_io.base=map("amp-I2C-GPIO98-99",0x03d62000,0x2000,VM_WIMG_IO);
        amp_reset=map("amp-reset-GPIO92",0x0395c000,0x1000,VM_WIMG_IO);
        if(amp_reset) {amp_reset_config=rd(amp_reset);amp_reset_output=rd(amp_reset+4)&2;}
        if(!amp_io.base||!amp_reset)return false;
        observe_tdm_pins();
        wr(amp_reset+4,0);wr(amp_reset,0x200);IOSleep(2);wr(amp_reset+4,2);IOSleep(2);
        for(unsigned amp=0;amp<4;++amp) {
            const auto &position=NabuCs35l41::Positions[amp];
            NabuCs35l41::Preloader<AmpBackend> loader(amp_backend[amp]);auto r=loader.run(amp);
            log("NABU AMP PRELOAD: %s complete=%u error=%u reg=%#x program=%u coefficients=%u identity=%u CAL_R=%u STATUS=%u CHECKSUM=%u CH_BAL=%#x quiet=%u\n",
                position.name,r.complete,r.error,r.failed_reg,r.program_bytes,r.coefficient_bytes,
                r.identity_verified,r.cal_r,r.cal_status,r.cal_checksum,r.ch_bal,r.quiet);publish();
            if(!r.complete)return false;
            amp_touched=amp+1;bool ok=amp_core[amp].start();report_amplifier(amp,"start");publish();
            if(!ok)return false;
        }
        return true;
    }
    bool enable_amplifiers() {
        for(unsigned amp=0;amp<4;++amp) {
            bool ok=amp_core[amp].enable_output();report_amplifier(amp,"enable");publish();
            if(!ok)return false;
        }
        log("NABU AMP PLAY: four protected outputs enabled at original 0 dB; native PCM sink and system volume\n");publish();return true;
    }
    bool finish_amplifiers() {
        bool stopped=true;
        for(unsigned amp=0;amp<amp_touched;++amp) {
            if(amp_core[amp].result().output_enabled)amp_core[amp].observe();
            auto r=amp_core[amp].finish();stopped=stopped&&r.clocks_may_stop;
            report_amplifier(amp,"finish");
        }
        bool reset_low=false;
        if(amp_reset) {
            wr(amp_reset+4,0);wr(amp_reset,0x200);IOSleep(2);reset_low=(rd(amp_reset+4)&1)==0;
        }
        amps_finished=true;
        log("NABU AMP PLAY: cores-stopped=%u shared-reset-low=%u before AFE clock removal\n",stopped,reset_low);publish();
        return stopped||reset_low;
    }
    void playback_fill(unsigned period,uint32_t first_frame,uint32_t frames) {
        (void)first_frame;
        int16_t *samples=(int16_t *)((uint8_t *)dma.blocks[0].cpu+period*4096);
        if(!native_attached) {native_attached=true;hakios_audio_set_sink("Nabu protected CS35L41 speakers",native_sink);}
        uint32_t generation,below;bool muted;
        // This runs on the DSP feeder, outside the audio writer's lock. The
        // original volume ioctl stores the HAL setting for the physical sink.
        if(hakios_audio_volume(&below,&muted,&generation)&&generation!=native_generation) {
            native_generation=generation;native_volume_below=below;native_muted=muted;
            uint64_t gain=1u<<24;
            // 10^(-0.125/20) in Q24; calculate only when the user changes volume.
            for(unsigned i=0;i<below;++i)gain=(gain*16537501+(1u<<23))>>24;
            native_gain=muted?0:uint32_t(gain);
        }
        uint32_t tail=native_tail,head=__atomic_load_n(&native_head,__ATOMIC_ACQUIRE);
        uint32_t available=head-tail,take=frames<available?frames:available;
        for(unsigned i=0;i<take;++i) {
            unsigned at=(tail+i)&(NativeRingFrames-1);
            samples[i*2]=int16_t((int64_t(native_ring[at*2])*native_gain)/(1<<24));
            samples[i*2+1]=int16_t((int64_t(native_ring[at*2+1])*native_gain)/(1<<24));
        }
        memset(samples+take*2,0,(frames-take)*4);
        __atomic_store_n(&native_tail,tail+take,__ATOMIC_RELEASE);
        native_fed+=take;native_silence+=frames-take;
        dma.platform.publish(dma.platform.cookie,samples,frames*4);
    }

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
    void ring() { wr(ipc, 1u << NabuAdsp::GlinkDoorbell); }
    bool allocate(uint16_t id, uint32_t bytes, uint32_t &offset) {
        lck_mtx_lock(&hakios_smem_alloc_lock);
        bool held = false;
        for (unsigned i = 0; i < 1000; ++i) { wr(hwlock, 1); if (rd(hwlock) == 1) { held = true; break; } IODelay(10); }
        bool ok = held && NabuAdsp::allocate(smem, *this, id, bytes, offset);
        if (held) wr(hwlock, 0);
        lck_mtx_unlock(&hakios_smem_alloc_lock);
        log("NABU ADSP: SMEM host=2 allocate id=%u bytes=%u ok=%u offset=%#x\n", id, bytes, ok, ok ? offset : 0);
        return ok;
    }
    bool prepare() {
        uint64_t bytes = 0;
        const uint8_t *header = hakios_image_file("fw", "adsp.mdt", &bytes, nullptr);
        if (!NabuAdsp::parse_image(header, bytes, image)) { log("NABU ADSP: invalid/missing MDT bytes=%llu\n", bytes); return false; }
        uint64_t file_bytes = 0, memory_bytes = 0;
        for (unsigned i = 0; i < image.count; ++i) {
            NabuAdsp::Segment &segment = image.segments[i];
            if (segment.file_bytes) {
                char name[24]; snprintf(name, sizeof(name), "adsp.b%02u", segment.index);
                segment.file = hakios_image_file("fw", name, &bytes, nullptr);
                if (!segment.file || bytes != segment.file_bytes) { log("NABU ADSP: segment=%u expected=%u bytes=%llu unavailable\n", segment.index, segment.file_bytes, bytes); return false; }
            }
            file_bytes += segment.file_bytes; memory_bytes += segment.memory_bytes;
        }
        log("NABU ADSP: firmware MDT=%u segments=%u file-bytes=%llu memory-bytes=%llu reserved=%#x+%#x\n",
            image.metadata_bytes, image.count, file_bytes, memory_bytes, NabuAdsp::MemoryBase, NabuAdsp::MemorySize);
        metadata = IOMallocContiguous(NabuAdsp::MetadataLimit, NabuAdsp::MetadataLimit, &metadata_pa);
        if (!metadata) return false;
        bzero(metadata, NabuAdsp::MetadataLimit); memcpy(metadata, image.metadata, image.metadata_bytes);
        for (uintptr_t at = (uintptr_t)metadata; at < (uintptr_t)metadata + NabuAdsp::MetadataLimit; at += 64)
            __asm__ volatile("dc civac, %0" : : "r"(at));
        __asm__ volatile("dsb sy" ::: "memory");
        aop = map("AOP", 0x0c300000, 0x1000, VM_WIMG_IO);
        ipc = map("APCS", 0x17c0000c, 4, VM_WIMG_IO);
        rsc = map("RPMh", 0x18220000, 0x4000, VM_WIMG_IO);
        smem_va = map("SMEM", 0x86000000, NabuAdsp::SmemSize, VM_WIMG_IO);
        hwlock = map("SMEM-lock3", 0x01f43000, 0x1000, VM_WIMG_IO);
        if (!aop || !ipc || !rsc || !smem_va || !hwlock) return false;
        smem = {(const volatile uint8_t *)smem_va, NabuAdsp::SmemSize};
        uint32_t base, line;
        if (!NabuAdsp::partition(smem, base, line)) { log("NABU ADSP: no host2/common SMEM partition\n"); return false; }
        log("NABU ADSP: SMEM selected hosts=%u:%u base=%#x size=%#x line=%u\n", smem.u16(base + 4), smem.u16(base + 6), base, smem.u32(base + 8), line);
        NabuSmemItem existing;
        if (NabuAdsp::find(smem, NabuAdsp::Incoming, existing) || NabuAdsp::find(smem, NabuAdsp::Outgoing, existing)) {
            log("NABU ADSP: preexisting SMP2P edge; cold-boot trial stops before PAS/AOP\n"); return false;
        }
        if (!allocate(NabuAdsp::Outgoing, NabuAdsp::Smp2pBytes, our_item)) return false;
        NabuAdsp::publish_smp2p(*this, our_item); wr(ipc, 1u << NabuAdsp::Smp2pDoorbell);
        uint32_t descriptor = 0, fifo = 0;
        if (!allocate(478, 32, descriptor) || !allocate(479, 16384, fifo)) return false;
        put(descriptor + 4, 0); put(descriptor + 8, 0); // APPS TX head / RX tail only
        log("NABU ADSP: SMP2P master-kernel published; host2 GLINK APPS queues prepared\n"); publish();
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
            snprintf(message, sizeof(message), "{class: image, res: load_state, name: adsp, val: %s}", on ? "on" : "off");
            for (unsigned i = 0; i < 16; ++i) wr(aop + mailbox + 4 + i * 4, NabuAdsp::le32((const uint8_t *)message + i * 4));
            wr(aop + mailbox, sizeof(message)); wr(ipc, 1);
            ok = wait_value(aop + mailbox, 0, 1000);
        }
        lck_mtx_unlock(&hakios_aop_mailbox_lock);
        log("NABU ADSP: AOP adsp=%s open=%u acknowledged=%u\n", on ? "on" : "off", open, ok); publish();
        return ok;
    }
    bool proxy_vote() {
        vm_offset_t db_va = map("command-db", 0x85f20000, 0x20000, VM_WIMG_IO);
        if (!db_va) return false;
        NabuSmem db{(const volatile uint8_t *)db_va, 0x20000};
        uint32_t address[2]{}, value[2]{};
        if (db.u32(4) == 0x0c0330db) for (unsigned s = 0; s < 8; ++s) {
            unsigned slave = 8 + s * 16, first = 144 + db.u16(slave + 2), count = db.u16(slave + 6);
            if (!db.u16(slave) || !db.span(first, count * 24)) continue;
            for (unsigned i = 0; i < count; ++i) {
                unsigned at = first + i * 24; char name[9]{};
                for (unsigned j = 0; j < 8; ++j) name[j] = db.data[at + j];
                if (!strcmp(name, "xo.lvl")) { address[1] = db.u32(at + 16); value[1] = 3; }
                if (!strcmp(name, "cx.lvl")) {
                    unsigned aux = 144 + db.u16(slave + 4) + db.u16(at + 22), length = db.u16(at + 20);
                    if (!db.span(aux, length)) continue;
                    // Original DT level385 = TURBO(384) + consumer offset1.
                    for (unsigned level = 0; level < length / 2; ++level) if (db.u16(aux + level * 2) >= 384) {
                        address[0] = db.u32(at + 16); value[0] = level;
                        log("NABU ADSP: CX resource=%#x position=%u raw-level=%u\n", address[0], level, db.u16(aux + level * 2)); break;
                    }
                }
            }
        }
        unmap(db_va, 0x20000);
        if (!address[0] || !address[1]) return false;
        log("NABU ADSP: XO resource=%#x value=%u\n", address[1], value[1]);
        lck_mtx_lock(&hakios_rsc_lock);
        vm_offset_t tcs = rsc + 0xd00;
        if (!rd(tcs + 0x18) || rd(tcs + 0x1c)) { lck_mtx_unlock(&hakios_rsc_lock); return false; }
        wr(rsc + 0xd08, 1);
        for (unsigned i = 0; i < 2; ++i) {
            wr(tcs + 0x30 + i * 20, 0x10108); wr(tcs + 0x34 + i * 20, address[i]); wr(tcs + 0x38 + i * 20, value[i]);
        }
        wr(tcs + 0x10, 3); wr(tcs + 0x1c, 3); wr(tcs + 0x14, 1u << 16); wr(tcs + 0x14, (1u << 16) | (1u << 24));
        bool done = false;
        for (unsigned i = 0; i < 5000; ++i) { if (rd(rsc + 0xd04) & 1) { done = true; break; } IODelay(10); }
        uint32_t cx = rd(tcs + 0x3c), xo = rd(tcs + 0x50);
        wr(tcs + 0x14, 0); wr(tcs + 0x1c, 0); wr(tcs + 0x10, 0); wr(rsc + 0xd08, 1);
        lck_mtx_unlock(&hakios_rsc_lock);
        log("NABU ADSP: proxy CX/XO complete=%u status=%#x,%#x; shared votes retained until reboot\n", done, cx, xo); publish();
        return done && (cx & 0x10000) && (xo & 0x10000);
    }
    bool init_image() { return pas(1, 0x82, metadata_pa); }
    bool memory_setup() { return pas(2, 3, NabuAdsp::MemoryBase, NabuAdsp::MemorySize); }
    bool copy_segments() {
        for (unsigned i = 0; i < image.count; ++i) {
            const NabuAdsp::Segment &segment = image.segments[i];
            vm_offset_t page = trunc_page(segment.physical);
            vm_size_t bytes = round_page(segment.physical - page + segment.memory_bytes);
            vm_offset_t mapping = map("segment", page, bytes, VM_WIMG_WCOMB);
            if (!mapping) return false;
            vm_offset_t target = mapping + segment.physical - page;
            if (segment.file_bytes) memcpy((void *)target, segment.file, segment.file_bytes);
            bzero((void *)(target + segment.file_bytes), segment.memory_bytes - segment.file_bytes);
            __asm__ volatile("dsb sy" ::: "memory"); unmap(mapping, bytes);
            log("NABU ADSP: copied b%02u pa=%#x file=%u memory=%u\n", segment.index, segment.physical, segment.file_bytes, segment.memory_bytes);
        }
        publish(); return true;
    }
    bool auth_reset() { return pas(5, 1); }
    NabuAdsp::Peer state() {
        NabuAdsp::Peer peer = NabuAdsp::peer(smem);
        if (!peer.valid) return peer;
        put(our_item + 4, ((peer.features & 1) << 8) | 1);
        uint32_t flags = smem.u32(our_item + 16), ack = (peer.flags & 1) ? 2 : 0;
        if ((peer.features & 1) && (flags & 2) != ack) {
            put(our_item + 16, (flags & ~2u) | ack); wr(ipc, 1u << NabuAdsp::Smp2pDoorbell);
        }
        if (peer.state != last_state) {
            last_state = peer.state;
            log("NABU ADSP: slave-kernel=%#x fatal=%u ready=%u handover=%u stop-ack=%u shutdown-ack=%u\n",
                peer.state, !!(peer.state & 1), !!(peer.state & 2), !!(peer.state & 4), !!(peer.state & 8), !!(peer.state & 128)); publish();
        }
        return peer;
    }
    bool wait_ready() {
        for (unsigned i = 0; i < 1000; ++i) {
            NabuAdsp::Peer peer = state();
            if (peer.valid && (peer.state & 1)) return false;
            if (peer.valid && (peer.state & 2)) return true;
            IOSleep(10);
        }
        log("NABU ADSP: ready wait timed out after 10000ms\n"); return false;
    }
    void observe() {
        // Allow the remote transport to publish its FIFO; do not consume its data.
        NabuSmemItem item;
        for (unsigned i = 0; i < 100 && !NabuAdsp::find(smem, 480, item); ++i) { state(); IOSleep(10); }
        for (unsigned id = 478; id <= 480; ++id) {
            bool found = NabuAdsp::find(smem, uint16_t(id), item);
            log("NABU ADSP: GLINK host=2 item=%u found=%u bytes=%u\n", id, found, found ? item.size : 0);
            if (found && id == 478 && item.size == 32)
                log("NABU ADSP: GLINK tx-tail=%u tx-head=%u rx-tail=%u rx-head=%u; transport not negotiated\n",
                    smem.u32(item.offset), smem.u32(item.offset + 4), smem.u32(item.offset + 8), smem.u32(item.offset + 12));
        }
        uint32_t base, line;
        if (smem.partition(0xfffe, &base, &line) && smem.item_in(base, line, 423, &item)) {
            char reason[193]{}; unsigned count = item.size < sizeof(reason) - 1 ? item.size : sizeof(reason) - 1;
            for (unsigned i = 0; i < count; ++i) { reason[i] = smem.data[item.offset + i]; if (!reason[i]) break; }
            log("NABU ADSP: crash-reason item423=%s\n", reason[0] ? reason : "(empty)");
        }
        publish();
    }
    void probe() {
        NabuAdsp::Peer peer = state();
        if (!peer.valid || (peer.state & 3) != 2) {
            log("NABU ADSP: GLINK probe skipped: peer not ready or fatal\n"); return;
        }
        NabuSmemItem descriptor, tx, rx;
        if (!NabuAdsp::find(smem, 478, descriptor) || descriptor.size != 32 ||
            !NabuAdsp::find(smem, 479, tx) || !NabuAdsp::find(smem, 480, rx) ||
            tx.size != 16384 || rx.size != 16384) {
            log("NABU ADSP: GLINK probe queues unavailable\n"); return;
        }
        bool mapping = prepare_dma();
        native_ring=(int16_t *)IOMalloc(NativeRingFrames*4);
        bool tdm=mapping&&native_ring&&prepare_tdm_pins(),amplifiers_done=false,output_attempted=false;
        // Original audio-ion masks SID0x1b21 by0xf and embeds1 in address bits63:32.
        uint64_t tagged_iova = (uint64_t(NabuAudioDma::first_sid & 15) << 32) | NabuAudioDma::iova_base;
        log("NABU ADSP: host2 GLINK/APR protected speaker PCM trial begins, local-channel=2 doorbell=8 dma=%u\n", mapping); publish();
        uint64_t started; clock_get_uptime(&started);
        uint32_t logged_rx = 0, trace_count = 0, last_peer_check = 0,last_stream_report=0,playing_since=0;
        glink.begin(descriptor.offset, tx.offset, tx.size, rx.offset, rx.size, true,
            mapping ? tagged_iova : 0, mapping ? NabuAudioDma::block_bytes : 0, false,tdm,tdm,true);
        while (!glink.done()) {
            uint64_t current, nanos; clock_get_uptime(&current);
            absolutetime_to_nanoseconds(current - started, &nanos);
            uint32_t elapsed = uint32_t(nanos / 1000000);
            if(!playing_since&&elapsed>=180000) {glink.abort();break;}
            if (elapsed - last_peer_check >= 10) {
                peer = state(); last_peer_check = elapsed;
                if (!peer.valid || (peer.state & 3) != 2) { glink.abort(); break; }
                if (dma_active && !dma_healthy()) { glink.abort(); break; }
            }
            glink.step(elapsed);
            microphone_step(elapsed);
            if(glink.afe_ready()&&!amplifiers_done&&mic_finished) {
                log("NABU AFE: TDM clock/port acknowledged; preload and start four protection cores\n");publish();
                amplifiers_done=true;
                if(!prepare_amplifiers()) {
                    if(!finish_amplifiers()) {retain_for_amp=true;break;}
                    glink.finish_afe();
                } else {
                    clock_get_uptime(&current);absolutetime_to_nanoseconds(current-started,&nanos);
                    glink.begin_playback(uint32_t(nanos/1000000));
                }
                continue;
            }
            if(glink.playback_ready()&&!output_attempted) {
                output_attempted=true;
                if(enable_amplifiers()) {
                    log("NABU PCM PLAY: continuous native speaker stream, no generated test tone\n");publish();
                    glink.play();playing_since=elapsed;stream_report_start=report_bytes;
                } else glink.abort_playback();
                continue;
            }
            if(glink.playback_done()) {
                if(native_attached) {hakios_audio_set_sink("none",nullptr);native_attached=false;}
                if(stream_report_start)stream_report();
                if(!finish_amplifiers()) {retain_for_amp=true;break;}
                stop_microphone();
                glink.finish_playback();continue;
            }
            if(playing_since&&!amps_finished&&elapsed-last_stream_report>=2000) {stream_report();last_stream_report=elapsed;}
            const NabuAdspGlink::Result &r = glink.result();
            if (r.rx != logged_rx && trace_count < 24) {
                log("NABU ADSP GLINK: rx=%u last-command=%u cid=%u value=%#x elapsed-ms=%u\n",
                    r.rx, r.last_command, r.last_cid, r.last_value, elapsed);
                logged_rx = r.rx; ++trace_count;
            }
            if (!glink.done()) IOSleep(1);
        }
        if(native_attached) {hakios_audio_set_sink("none",nullptr);native_attached=false;}
        stop_microphone();
        if(amp_touched&&!amps_finished&&!finish_amplifiers())retain_for_amp=true;
        const NabuAdspGlink::Result &r = glink.result();
        log("NABU ADSP GLINK: negotiated=%u features=%#x open=%u local=%u remote=%u remote-open=%u open-ack=%u tx=%u rx=%u unknown-channels=%u close-sent=%u close-ack=%u remote-closed=%u broken=%u timeout=%u error=%u\n",
            r.negotiated, r.features, r.opened, r.lcid, r.rcid, r.remote_open, r.local_open_ack,
            r.tx, r.rx, r.unknown_channels, r.close_sent, r.close_ack, r.remote_closed, r.broken, r.timeout, r.error);
        log("NABU ADSP GLINK: peer-intents=%u last-iid=%#x last-size=%u intent-invalid=%u uncached=%u replaced=%u (0=none,2=zero-size)\n",
            r.peer_intents, r.last_peer_iid, r.last_peer_size, r.intent_invalid_reason,
            r.peer_uncached, r.peer_replaced);
        log("NABU ADSP APR: get-state-sent=%u queries=%u matched-response=%u token=%#x raw-state=%#x ready=%u packets=%u ignored=%u basic-responses=%u basic-status=%#x field=%#x type=%u matched-opcode=%#x matched-token=%#x; speaker/microphone routes inactive\n",
            r.apr_sent, r.queries, r.apr_response, r.token, r.apr_state, r.apr_ready,
            r.apr_packets, r.apr_ignored, r.basic_responses, r.basic_status,
            r.apr_field, r.apr_type, r.matched_opcode, r.matched_token);
        log("NABU ADSP AVCS: version-sent=%u response=%u token=%#x basic-response=%u status=%#x timeout=%u invalid=%u field=%#x type=%u build=%u.%u.%u.%u services=%u\n",
            r.version_sent, r.version_response, r.version_token, r.version_basic_response,
            r.version_status, r.version_timeout, r.version_invalid, r.version_field, r.version_type,
            r.build_version[0], r.build_version[1], r.build_version[2], r.build_version[3], r.service_count);
        for (unsigned i = 0; i < r.service_count; ++i)
            log("NABU ADSP AVCS: service=%#x api=%u branch=%u\n", r.services[i].id, r.services[i].api, r.services[i].branch);
        log("NABU ADSP ASM: map-sent=%u response=%u token=%#x handle=%#x basic=%u status=%#x timeout=%u unmap-sent=%u response=%u token=%#x status=%#x timeout=%u\n",
            r.map_sent, r.map_response, r.map_token, r.map_handle, r.map_basic_response, r.map_status,
            r.map_timeout, r.unmap_sent, r.unmap_response, r.unmap_token, r.unmap_status, r.unmap_timeout);
        const auto &a=glink.afe_result();
        log("NABU AFE: island=%u clock-sent=%u on=%u group-config=%u enable-sent=%u on=%u port-config=%u slots=%u start-sent=%u started=%u\n",
            a.island_configured,a.clock_sent,a.clock_on,a.group_configured,a.group_sent,a.group_on,
            a.port_configured,a.slots_configured,a.start_sent,a.started);
        log("NABU AFE: stop-sent=%u stopped=%u group-off-sent=%u off=%u clock-off-sent=%u off=%u failed=%u timeout=%u opcode=%#x status=%#x cleanup-failed=%u commands=%u ignored=%u\n",
            a.stop_sent,a.stopped,a.group_off_sent,a.group_off,a.clock_off_sent,a.clock_off,
            a.failed,a.timeout,a.failed_opcode,a.status,a.cleanup_failed,a.commands,a.ignored);
        const auto &p=glink.playback_result();
        log("NABU PCM PLAY: ADM=%u COPP=%u ASM=%u route=%u format=%u run=%u play=%u writes=%u done=%u bytes=%u/%u pending=%#x underflows=%u\n",
            p.adm_opened,p.copp_id,p.asm_opened,p.routed,p.formatted,p.running,p.play_started,p.writes,
            p.completions,p.bytes_sent,p.bytes_completed,p.pending_mask,p.underflows);
        log("NABU PCM PLAY: EOS=%u ack=%u rendered=%u stream-closed=%u COPP-closed=%u mapping-retained=%u failed=%u timeout=%u opcode=%#x status=%#x first-ms=%u last-ms=%u\n",
            p.eos_sent,p.eos_acked,p.rendered,p.closed,p.copp_closed,p.mapping_retained,p.failed,
            p.timeout,p.failed_opcode,p.status,p.first_write_ms,p.last_done_ms);
        if (dma_active) (void)dma_healthy();
        publish();
        // The fixed protocol buffers remain with Trial through PAS shutdown,
        // including the existing retain-until-reboot path on shutdown failure.
    }
    bool request_stop() {
        if(retain_for_amp)return false;
        put(our_item + 36, 1); wr(ipc, 1u << NabuAdsp::Smp2pDoorbell);
        bool ack = false;
        for (unsigned i = 0; i < 500; ++i) {
            NabuAdsp::Peer peer = state();
            if (peer.valid && (peer.state & 8)) { ack = true; break; }
            if (peer.valid && (peer.state & 1)) break;
            IOSleep(10);
        }
        put(our_item + 36, 0); wr(ipc, 1u << NabuAdsp::Smp2pDoorbell);
        log("NABU ADSP: force-stop cleared acknowledged=%u\n", ack); return ack;
    }
    bool shutdown() { return !retain_for_amp&&pas(6, 1); }
    void release() {
        if(native_ring) {IOFree(native_ring,NativeRingFrames*4);native_ring=nullptr;}
        restore_audio_pins();
        if (dma_va) {
            bool released = dma.release_after_stop();
            log("NABU ADSP DMA: released=%u phase=%u status=%u retained=%u offset=%#x expected=%#x actual=%#x\n",
                released, dma.stop.phase, dma.status, !released, dma.stop.offset, dma.stop.expected, dma.stop.actual);
            if (released) { dma_active = false; unmap(dma_va, 0x100000); dma_va = 0; }
        }
        if (metadata) { IOFreeContiguous(metadata, NabuAdsp::MetadataLimit); metadata = nullptr; }
        if (hwlock) { unmap(hwlock, 0x1000); hwlock = 0; }
        if (smem_va) { unmap(smem_va, NabuAdsp::SmemSize); smem_va = 0; }
        if (rsc) { unmap(rsc, 0x4000); rsc = 0; }
        if (ipc) { unmap(ipc, 4); ipc = 0; }
        if (aop) { unmap(aop, 0x1000); aop = 0; }
        // hakios_image_file returns borrowed pointers into the mounted boot image.
    }
};
static Trial trial;
static void worker(thread_call_param_t, thread_call_param_t) {
    log("NABU ADSP: bounded PAS1 protected speaker trial begins; microphone inactive\n"); publish();
    NabuAdsp::Outcome result = NabuAdsp::run(trial);
    log("NABU ADSP: result prepared=%u aop-on=%u proxy=%u init=%u mem=%u copied=%u auth=%u ready=%u stop-ack=%u shutdown=%u aop-off=%u retained=%u\n",
        result.prepared, result.aop_on, result.proxy, result.init, result.memory, result.copied, result.auth,
        result.ready, result.stop_ack, result.shutdown, result.off, result.retained);
    if (result.retained) log("NABU ADSP: shutdown not completed; AOP vote, metadata and mappings retained until reboot\n");
    publish();
}
} // namespace

extern "C" void nabu_adsp_start() {
    uint32_t enabled = 0;
    if (adsp_call || !PE_parse_boot_argn("nabu-adsp", &enabled, sizeof(enabled)) || enabled != 1) return;
    adsp_call = thread_call_allocate(worker, nullptr);
    if (!adsp_call) return;
    log("NABU ADSP: nabu-adsp=1 scheduled after 40 seconds\n"); publish();
    uint64_t deadline; clock_interval_to_deadline(40, NSEC_PER_SEC, &deadline);
    thread_call_enter_delayed(adsp_call, deadline);
}
