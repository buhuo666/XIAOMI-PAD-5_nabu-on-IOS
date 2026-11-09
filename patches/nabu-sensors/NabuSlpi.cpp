// SPDX-License-Identifier: BSD-2-Clause-Patent
// Opt-in root-PD diagnostic, not an operational iPadOS sensor provider.
// All APPS polling has deadlines. A secure-world SMC itself cannot be timed out
// by this worker; the known ADSP continuation risk also applies to first SLPI bring-up.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>
#include <kern/clock.h>
#include <kern/thread_call.h>
#include <kern/locks.h>
#include <mach/vm_param.h>
#include <vm/memory_types.h>
#include <pexpert/pexpert.h>
#include "NabuSlpiProtocol.h"
#include "NabuSlpiGlink.h"
#include "NabuSscCensus.h"
extern "C" vm_offset_t ml_io_map_unmappable(vm_offset_t,vm_size_t,unsigned int);
extern "C" void ml_io_unmap(vm_offset_t,vm_size_t);
extern "C" const uint8_t *hakios_image_file(const char *,const char *,uint64_t *,int *);
extern "C" void loader_log_line(const char *);
extern "C" lck_mtx_t hakios_aop_mailbox_lock,hakios_rsc_lock,hakios_smem_alloc_lock;
namespace {
static thread_call_t slpi_call;
static uint32_t slpi_mode;
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
        static_cast<Trial *>(context)->census.receive(node,port,local_port,data,size);
    }
    void ssc_event(unsigned type,NabuSsc::Suid suid,uint32_t id,uint64_t ticks,NabuSsc::Span payload){
        const char *name=NabuSsc::Census<Trial>::type(type);
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
        if(!glink.begin(desc.offset,tx.offset,tx.size,rx.offset,rx.size,slpi_mode==2,receive_ssc,this))return;
        uint64_t started;clock_get_uptime(&started);
        while(!glink.done()){
            uint64_t current,nanos;clock_get_uptime(&current);absolutetime_to_nanoseconds(current-started,&nanos);
            unsigned elapsed=unsigned(nanos/1000000);
            if(elapsed>30000){glink.abort();break;}
            NabuSlpi::Peer p=state();if(!p.valid||(p.state&3)!=2){glink.abort();break;}
            glink.step(elapsed);
            if(slpi_mode==2&&!glink.done()){
                const auto &r=glink.result();
                if(r.ssc_found&&!census.result.started)census.start(r.ssc_node,r.ssc_port,elapsed);
                if(census.result.started&&!r.ssc_found){glink.abort();break;}
                census.tick(elapsed);
                if(census.result.done)glink.finish();
            }
            if(!glink.done())IOSleep(10);
        }
        const auto &r=glink.result();
        log("NABU SLPI: GLINK negotiated=%u open=%u tx=%u rx=%u QRTR=%u servers=%u SSC=%u node=%u port=%u instance=%#x close=%u timeout=%u error=%u\n",
            r.negotiated,r.opened,r.tx,r.rx,r.qrtr_packets,r.servers,r.ssc_found,r.ssc_node,r.ssc_port,r.ssc_instance,r.close_ack,r.timeout,r.error);
        if(slpi_mode==2)ssc_summary();
        log("NABU SLPI: live-census=%u sensor_pd/FastRPC/registry file service not implemented; no native iPadOS sensor published\n",slpi_mode==2);publish();
    }
    bool request_stop(){
        put(our_item+36,1);wr(ipc,1u<<NabuSlpi::Smp2pDoorbell);bool ack=false;
        for(unsigned i=0;i<500;++i){auto p=state();if(p.valid&&(p.state&8)){ack=true;break;}if(p.valid&&(p.state&1))break;IOSleep(10);}
        put(our_item+36,0);wr(ipc,1u<<NabuSlpi::Smp2pDoorbell);
        log("NABU SLPI: force-stop cleared ack=%u\n",ack);return ack;
    }
    bool shutdown(){return pas(6,1);}
    void release(){
        if(metadata){IOFreeContiguous(metadata,NabuSlpi::MetadataLimit);metadata=nullptr;}
        if(hwlock){unmap(hwlock,0x1000);hwlock=0;}if(smem_va){unmap(smem_va,NabuSlpi::SmemSize);smem_va=0;}
        if(rsc){unmap(rsc,0x4000);rsc=0;}if(ipc){unmap(ipc,4);ipc=0;}if(aop){unmap(aop,0x1000);aop=0;}
    }
};
static Trial trial;
static void worker(thread_call_param_t,thread_call_param_t){
    log("NABU SLPI: opt-in root-PD census begins; native sensor service inactive\n");publish();
    auto r=NabuSlpi::run(trial);
    log("NABU SLPI: prepared=%u AOP=%u proxy=%u init=%u mem=%u copied=%u auth=%u ready=%u stop=%u shutdown=%u off=%u retained=%u\n",
        r.prepared,r.aop_on,r.proxy,r.init,r.memory,r.copied,r.auth,r.ready,r.stop_ack,r.shutdown,r.off,r.retained);
    if(r.retained)log("NABU SLPI: PAS shutdown failed; metadata and mappings retained until reboot\n");publish();
}
}
extern "C" void nabu_slpi_start(){
    if(slpi_call||!PE_parse_boot_argn("nabu-slpi",&slpi_mode,sizeof(slpi_mode))||(slpi_mode!=1&&slpi_mode!=2))return;
    slpi_call=thread_call_allocate(worker,nullptr);if(!slpi_call)return;
    log("NABU SLPI: nabu-slpi=%u scheduled after 60 seconds\n",slpi_mode);publish();
    uint64_t deadline;clock_interval_to_deadline(60,NSEC_PER_SEC,&deadline);thread_call_enter_delayed(slpi_call,deadline);
}
